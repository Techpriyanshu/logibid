"""
Multiprocess orchestration: ProcessPoolExecutor + optional async background thread.
Does not import FastAPI (safe for worker spawn).
"""

from __future__ import annotations

import multiprocessing as mp
import os
import threading
import time
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config_loader import get_app_config
from . import execution_logging as elog
from .job_store import job_store
from .logging_service import get_logger
from .depot_normalization import normalize_depot_name
from .live_bids_store import register_job_legs
from .selenium_worker import run_depot_worker
from .window_rotation import (
    WindowRotationManager,
    get_window_rotation_settings,
    should_enable_rotation,
)

logger = get_logger("parallel_orchestrator")


def log(message: str, **kwargs) -> None:
    """Add job_id, PID, file and line number to log messages for traceability."""
    import inspect
    import os
    
    job_id = kwargs.get("job_id")
    frame = inspect.currentframe()
    if frame and frame.f_back:
        caller = frame.f_back
        filename = os.path.basename(caller.f_code.co_filename)
        lineno = caller.f_lineno
        extra = f" [file={filename}:{lineno}]"
    else:
        extra = ""
    
    pid = os.getpid()
    if job_id:
        logger.info("[Orchestrator job=%s PID=%s]%s %s", job_id[:8], pid, extra, message)
    else:
        logger.info("[Orchestrator PID=%s]%s %s", pid, extra, message)


def _filter_desired_bids_for_depot(depot: str, desired_bids: List[dict]) -> List[dict]:
    """
    When any bid carries ``depot``, each worker receives matching rows **plus** bids
    with no ``depot`` (those apply to every worker). If no bid has ``depot``, preserve
    legacy behavior (same full list for all workers).
    """
    if not desired_bids:
        return []
    has_explicit = any(
        b.get("depot") is not None and str(b.get("depot")).strip() for b in desired_bids
    )
    if not has_explicit:
        return [dict(b) for b in desired_bids]
    dn = normalize_depot_name(depot)
    out: List[dict] = []
    for b in desired_bids:
        bd = b.get("depot")
        if bd is None or not str(bd).strip():
            out.append(dict(b))
            continue
        if normalize_depot_name(str(bd)) == dn:
            out.append(dict(b))
    return out


def _resolve_login_stagger_seconds(mp_cfg: Dict[str, Any]) -> float:
    """Read login_stagger_seconds from settings (yaml + env via get_multiprocess_settings)."""
    raw = mp_cfg.get("login_stagger_seconds", 210)
    try:
        stagger = float(raw)
    except (TypeError, ValueError):
        stagger = 210.0
    if stagger < 0:
        stagger = 0.0
    return stagger


def _submit_workers_sequential_stagger(
    pool: ProcessPoolExecutor,
    depot_list: List[str],
    truck_id: str,
    desired_bids: List[dict],
    worker_retry_attempts: int,
    login_stagger_seconds: float,
    job_id: Optional[str] = None,
    rotation_registry: Any = None,
    rotation_lock: Any = None,
    headless: bool | None = None,
    record_on_bid_start: bool | None = None,
) -> Dict[Future, str]:
    """
    Launch one depot worker at a time. After each launch (except the first), wait
    login_stagger_seconds before starting the next Chrome/login session.
    """
    future_map: Dict[Future, str] = {}
    n = len(depot_list)
    log(f"Submitting {n} workers for depots={depot_list}", job_id=job_id)
    
    for i, d in enumerate(depot_list):
        if i > 0 and login_stagger_seconds > 0:
            log(f"login_stagger waiting {login_stagger_seconds}s before launching depot={d} ({i+1}/{n})", job_id=job_id)
            time.sleep(login_stagger_seconds)

        payload = {
            "truck_id": truck_id,
            "depot_name": d,
            "desired_bids": _filter_desired_bids_for_depot(d, list(desired_bids or [])),
            "worker_retry_attempts": worker_retry_attempts,
            "job_id": job_id,
            "rotation_registry": rotation_registry,
            "rotation_lock": rotation_lock,
            # Observability-only copy for Phase 3 registry snapshots (not used for decisions)
            "rotation_expected_depots": list(depot_list) if rotation_registry is not None else None,
            # Browser mode overrides from API
            "headless": headless,
            "record_on_bid_start": record_on_bid_start,
        }
        log(f"Submitting worker for depot={d} with payload keys={list(payload.keys())}", job_id=job_id)
        fut = pool.submit(run_depot_worker, payload)
        future_map[fut] = d
        log(f"Launched depot={d} sequential index={i+1}/{n} (pre-launch wait={login_stagger_seconds if i > 0 else 0.0}s)", job_id=job_id)
    return future_map


def _maybe_start_window_rotation(
    ctx: Any,
    depot_list: List[str],
    job_id: Optional[str],
) -> Tuple[Any, Any, Any, Optional[WindowRotationManager]]:
    """
    Start Rotation Manager only when enabled and depot_count > 1.
    Phase 2 freeze/resume is handled inside WindowRotationManager (read-only live_bids).
    Returns (manager, registry, lock, rotation_manager).
    manager/registry/lock are None when rotation is disabled (zero overhead).
    """
    wr = get_window_rotation_settings()
    jid = str(job_id or "") or "n/a"
    logger.info(
        "[ROTATION][MGR] Configuration loaded "
        "job_id=%s enabled=%s interval=%s freeze_on_execution=%s "
        "total_depots=%d expected_depots=%s",
        jid,
        wr.get("enabled"),
        wr.get("interval_seconds"),
        wr.get("freeze_on_execution"),
        len(depot_list),
        list(depot_list),
    )
    if not should_enable_rotation(wr["enabled"], len(depot_list)):
        if not wr["enabled"]:
            logger.info(
                "[ROTATION][MGR] Rotation skipped "
                "job_id=%s reason=disabled "
                "enabled=False total_depots=%d expected_depots=%s",
                jid,
                len(depot_list),
                list(depot_list),
            )
        elif len(depot_list) <= 1:
            logger.info(
                "[ROTATION][MGR] Rotation skipped "
                "job_id=%s reason=single_depot "
                "enabled=%s total_depots=%d expected_depots=%s",
                jid,
                wr.get("enabled"),
                len(depot_list),
                list(depot_list),
            )
        return None, None, None, None

    mp_manager = ctx.Manager()
    registry = mp_manager.dict()
    lock = mp_manager.Lock()
    rotator = WindowRotationManager(
        registry,
        interval_seconds=float(wr["interval_seconds"]),
        lock=lock,
        job_id=str(job_id or ""),
        freeze_on_execution=bool(wr.get("freeze_on_execution", True)),
        expected_depots=list(depot_list),
    )
    rotator.start()
    return mp_manager, registry, lock, rotator


def _resolve_depot_list(
    depot: str | None,
    truck_id: str,
    depots: List[str] | None,
) -> List[str]:
    cfg = get_app_config()
    yaml_depots = (cfg.get("sap", {}) or {}).get("depots") or []
    if depots and len(depots) > 0:
        out = [normalize_depot_name(d) for d in depots if str(d).strip()]
        return [d for d in out if d]
    if yaml_depots:
        out = [normalize_depot_name(d) for d in yaml_depots if str(d).strip()]
        return [d for d in out if d]
    fallback = normalize_depot_name(depot) or normalize_depot_name(truck_id)
    return [fallback] if fallback else []


def get_multiprocess_settings() -> Dict[str, Any]:
    cfg = get_app_config()
    auto = cfg.get("automation", {}) or {}
    mp_cfg = auto.get("multiprocess", {}) or {}
    parallel = cfg.get("parallel", {}) or {}
    parallel_cap = int(parallel.get("max_workers", 4))
    raw_workers = mp_cfg.get("max_parallel_workers")
    if raw_workers is None:
        requested = parallel_cap
    else:
        requested = int(raw_workers)
    abs_cap = int(mp_cfg.get("max_parallel_workers_absolute_cap", 16))
    abs_cap = max(1, abs_cap)
    max_parallel_workers = max(1, min(requested, abs_cap))
    raw_stagger = mp_cfg.get("login_stagger_seconds", 210)
    try:
        login_stagger_seconds = float(raw_stagger)
    except (TypeError, ValueError):
        login_stagger_seconds = 210.0
    if login_stagger_seconds < 0:
        login_stagger_seconds = 0.0
    env_stagger = os.getenv("AUTOMATION_LOGIN_STAGGER_SECONDS", "").strip()
    if env_stagger:
        try:
            login_stagger_seconds = float(env_stagger)
        except (TypeError, ValueError):
            pass
        if login_stagger_seconds < 0:
            login_stagger_seconds = 0.0
    return {
        "max_parallel_workers": max_parallel_workers,
        "max_parallel_workers_requested": requested,
        "max_parallel_workers_absolute_cap": abs_cap,
        "login_stagger_seconds": login_stagger_seconds,
        "worker_retry_attempts": int(mp_cfg.get("worker_retry_attempts", 2)),
        "depot_timeout_seconds": mp_cfg.get("depot_timeout_seconds"),
        "keep_browser_open": bool(mp_cfg.get("keep_browser_open", True)),
        "keep_browser_open_only_after_automation": bool(
            mp_cfg.get("keep_browser_open_only_after_automation", False)
        ),
        "post_execute_mode": str(mp_cfg.get("post_execute_mode", "passive")).strip().lower(),
        "post_execute_interval_seconds": float(mp_cfg.get("post_execute_interval_seconds", 5)),
        "post_execute_max_seconds": mp_cfg.get("post_execute_max_seconds"),
    }


def run_multiprocess_job_sync(
    truck_id: str,
    depot: str | None,
    depots: List[str] | None,
    desired_bids: List[dict],
    job_id: Optional[str] = None,
    headless: bool | None = None,
    record_on_bid_start: bool | None = None,
) -> Dict[str, Any]:
    depot_list = _resolve_depot_list(depot, truck_id, depots)
    if job_id:
        register_job_legs(job_id, desired_bids)
    mp_cfg = get_multiprocess_settings()
    login_stagger_seconds = _resolve_login_stagger_seconds(mp_cfg)
    # Each depot keeps its own Chrome + monitor alive; pool must allow all depots concurrently.
    max_workers = max(1, len(depot_list))
    timeout = mp_cfg.get("depot_timeout_seconds")
    timeout_f = float(timeout) if timeout is not None else None

    t0 = time.perf_counter()
    results: List[Dict[str, Any]] = []
    ctx = mp.get_context("spawn")

    if job_id:
        elog.init_job_logging(str(job_id), depot_list)
        elog.log_orchestrator(
            str(job_id),
            "Multiprocess sync job starting",
            action="START",
            depots=len(depot_list),
            max_workers=max_workers,
            login_stagger_seconds=login_stagger_seconds,
        )

    logger.info(
        "[Orchestrator] execution_mode=multiprocess backend=ProcessPoolExecutor "
        "parent_pid=%s depots=%d max_workers=%d login_stagger_seconds=%.1f "
        "(sequential launch; each depot independent Chrome+login+monitor)",
        os.getpid(),
        len(depot_list),
        max_workers,
        login_stagger_seconds,
    )
    if mp_cfg["max_parallel_workers_requested"] > mp_cfg["max_parallel_workers_absolute_cap"]:
        logger.warning(
            "max_parallel_workers capped: requested=%s absolute_cap=%s effective=%s",
            mp_cfg["max_parallel_workers_requested"],
            mp_cfg["max_parallel_workers_absolute_cap"],
            mp_cfg["max_parallel_workers"],
        )

    mp_manager, rotation_registry, rotation_lock, rotator = _maybe_start_window_rotation(
        ctx, depot_list, job_id
    )
    try:
        with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as pool:
            future_map = _submit_workers_sequential_stagger(
                pool,
                depot_list,
                truck_id,
                desired_bids,
                mp_cfg["worker_retry_attempts"],
                login_stagger_seconds,
                job_id=job_id,
                rotation_registry=rotation_registry,
                rotation_lock=rotation_lock,
                headless=headless,
                record_on_bid_start=record_on_bid_start,
            )

            for fut in as_completed(future_map):
                name = future_map[fut]
                try:
                    if timeout_f is not None:
                        r = fut.result(timeout=timeout_f)
                    else:
                        r = fut.result()
                    results.append(r)
                    if job_id:
                        elog.record_depot_result_summary(str(job_id), name, r if isinstance(r, dict) else None)
                        elog.log_orchestrator(
                            str(job_id),
                            f"Depot finished {name}",
                            action="DEPOT_DONE",
                            depot=name,
                            status=str((r or {}).get("status") if isinstance(r, dict) else ""),
                            worker_pid=(r or {}).get("worker_pid") if isinstance(r, dict) else None,
                        )
                    if isinstance(r, dict) and r.get("worker_pid") is not None:
                        logger.info(
                            "[Orchestrator] Depot=%s finished worker_pid=%s status=%s",
                            name,
                            r.get("worker_pid"),
                            r.get("status"),
                        )
                except Exception as e:
                    logger.exception("Depot worker future failed depot=%s", name)
                    fail = {
                        "depot": name,
                        "status": "failed",
                        "rows": 0,
                        "prepared_bids": [],
                        "error": str(e),
                    }
                    results.append(fail)
                    if job_id:
                        elog.record_depot_result_summary(str(job_id), name, fail)
                        elog.log_orchestrator(
                            str(job_id),
                            f"Depot failed {name}: {e}",
                            action="DEPOT_FAIL",
                            status="error",
                            depot=name,
                        )
    finally:
        if rotator is not None:
            try:
                rotator.stop()
            except Exception:
                pass
        if mp_manager is not None:
            try:
                mp_manager.shutdown()
            except Exception:
                pass

    order = {d: i for i, d in enumerate(depot_list)}
    results.sort(key=lambda r: order.get(str(r.get("depot", "")), 9999))

    elapsed = time.perf_counter() - t0
    overall = "completed"
    if any(r.get("status") == "failed" for r in results):
        overall = "partial_failed" if any(r.get("status") != "failed" for r in results) else "failed"
    rows_found = sum(int(r.get("rows", 0) or 0) for r in results)

    if job_id:
        elog.finalize_job_logging(str(job_id), status=overall, duration_sec=elapsed)

    return {
        "status": overall,
        "truck_id": truck_id,
        "depot": depot or truck_id,
        "depots_processed": [r.get("depot") for r in results],
        "results": results,
        "rows_found": rows_found,
        "bids_submitted": 0,
        "execution_time": f"{elapsed:.1f} seconds",
        "message": "Multiprocess run finished; ready for manual bid locking (no automated submit)",
        "execution_mode": "multiprocess",
        "multiprocess_max_workers": max_workers,
        "bidding_result": {
            "status": overall,
            "depots_processed": [r.get("depot") for r in results],
            "rows_found": rows_found,
            "bids_submitted": 0,
            "execution_time": f"{elapsed:.1f} seconds",
            "results": results,
        },
    }


def _async_job_thread(
    job_id: str,
    truck_id: str,
    depot_list: List[str],
    desired_bids: List[dict],
    mp_cfg: Dict[str, Any],
    on_complete: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    headless: bool | None = None,
    record_on_bid_start: bool | None = None,
) -> None:
    try:
        logger.info("[Orchestrator] Thread started job_id=%s", job_id[:8])
        job_store.mark_running(job_id)
        log("Job marked as running", job_id=job_id)
        
        login_stagger_seconds = _resolve_login_stagger_seconds(mp_cfg)
        log(f"Login stagger: {login_stagger_seconds}s", job_id=job_id)
        
        max_workers = max(1, len(depot_list))
        log(f"Max workers: {max_workers}", job_id=job_id)
        
        timeout = mp_cfg.get("depot_timeout_seconds")
        timeout_f = float(timeout) if timeout is not None else None
        ctx = mp.get_context("spawn")
        t_job = time.perf_counter()
        elog.init_job_logging(job_id, depot_list)
        elog.log_orchestrator(
            job_id,
            "Multiprocess async job starting",
            action="START",
            depots=len(depot_list),
            max_workers=max_workers,
            login_stagger_seconds=login_stagger_seconds,
        )
        log("elog.init_job_logging and log_orchestrator complete", job_id=job_id)
        
        mp_manager, rotation_registry, rotation_lock, rotator = _maybe_start_window_rotation(
            ctx, depot_list, job_id
        )
        log(f"Window rotation: mp_manager={mp_manager is not None}, rotator={rotator is not None}", job_id=job_id)

        log(f"Async job_id={job_id[:8]} depots={len(depot_list)} max_workers={max_workers} login_stagger_seconds={login_stagger_seconds:.1f}", job_id=job_id)
        with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as pool:
            future_map = _submit_workers_sequential_stagger(
                pool,
                depot_list,
                truck_id,
                desired_bids,
                int(mp_cfg["worker_retry_attempts"]),
                login_stagger_seconds,
                job_id=job_id,
                rotation_registry=rotation_registry,
                rotation_lock=rotation_lock,
                headless=headless,
                record_on_bid_start=record_on_bid_start,
            )

            for fut in as_completed(future_map):
                name = future_map[fut]
                try:
                    if timeout_f is not None:
                        r = fut.result(timeout=timeout_f)
                    else:
                        r = fut.result()
                    job_store.record_depot_result(job_id, name, r)
                    elog.record_depot_result_summary(job_id, name, r if isinstance(r, dict) else None)
                    elog.log_orchestrator(
                        job_id,
                        f"Depot finished {name}",
                        action="DEPOT_DONE",
                        depot=name,
                        status=str((r or {}).get("status") if isinstance(r, dict) else ""),
                    )
                except Exception as e:
                    # Check if this was a user-initiated stop
                    from .live_bids_store import get_user_control
                    user_stopped = False
                    try:
                        from .live_bids_store import list_live_bids
                        bids = list_live_bids(job_id=job_id)
                        for bid in bids.get("items", []):
                            if bid.get("user_control") == "stopped":
                                user_stopped = True
                                break
                    except Exception:
                        pass
                    
                    if user_stopped:
                        logger.info("Async job depot stopped by user depot=%s", name)
                        job_store.record_depot_result(job_id, name, {"status": "stopped", "depot": name})
                        elog.record_depot_result_summary(
                            job_id, name, {"status": "stopped", "reason": "user_stopped"}
                        )
                        elog.log_orchestrator(
                            job_id,
                            f"Depot stopped by user {name}",
                            action="DEPOT_STOPPED",
                            status="stopped",
                            depot=name,
                        )
                    else:
                        logger.exception("Async job depot failed depot=%s", name)
                        job_store.record_depot_error(job_id, name, str(e))
                        elog.record_depot_result_summary(
                            job_id, name, {"status": "failed", "error": str(e)}
                        )
                        elog.log_orchestrator(
                            job_id,
                            f"Depot failed {name}: {e}",
                            action="DEPOT_FAIL",
                            status="error",
                            depot=name,
                        )

        snap = job_store.get_job(job_id)
        results = (snap or {}).get("results") or {}
        values = list(results.values()) if isinstance(results, dict) else []
        overall = "completed"
        # Check if user stopped the bid
        if any(isinstance(v, dict) and v.get("status") == "stopped" for v in values):
            overall = "stopped"
        elif any(isinstance(v, dict) and v.get("status") == "failed" for v in values):
            overall = (
                "partial_failed"
                if any(isinstance(v, dict) and v.get("status") != "failed" for v in values)
                else "failed"
            )
        job_store.finalize(job_id, overall, summary=f"depots={len(depot_list)}")
        elog.finalize_job_logging(
            job_id, status=overall, duration_sec=time.perf_counter() - t_job
        )
        log(f"Async job completed job_id={job_id[:8]} overall={overall}", job_id=job_id)
        if on_complete:
            on_complete(job_id, job_store.get_job(job_id) or {})
    except Exception as e:
        logger.exception("Async job crashed job_id=%s", job_id)
        log(f"Async job crashed job_id={job_id[:8]} error={str(e)}", job_id=job_id)
        job_store.finalize(job_id, "failed", summary=str(e))
        elog.finalize_job_logging(
            job_id, status="failed", duration_sec=time.perf_counter() - t_job
        )
    finally:
        log(f"Async job thread cleanup job_id={job_id[:8]}", job_id=job_id)
        if rotator is not None:
            try:
                rotator.stop()
            except Exception:
                pass
        if mp_manager is not None:
            try:
                mp_manager.shutdown()
            except Exception:
                pass


def start_multiprocess_job_async(
    truck_id: str,
    depot: str | None,
    depots: List[str] | None,
    desired_bids: List[dict],
    on_complete: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    headless: bool | None = None,
    record_on_bid_start: bool | None = None,
) -> Dict[str, Any]:
    depot_list = _resolve_depot_list(depot, truck_id, depots)
    
    # Validate inputs before creating job
    if not depot_list:
        return {"error": "No depots specified", "status": "invalid"}
    if not desired_bids:
        return {"error": "No bids specified", "status": "invalid"}
    
    payload = [
        {
            "quantity": b.get("quantity", 0),
            "destination": b.get("destination"),
            "depot": b.get("depot"),
        }
        for b in desired_bids
    ]
    job_id = job_store.create_job(
        truck_id, depot_list, desired_bids, payload=payload, headless=headless, record_on_bid_start=record_on_bid_start, execution_mode="multiprocess"
    )
    register_job_legs(job_id, desired_bids)
    mp_cfg = get_multiprocess_settings()
    elog.init_job_logging(job_id, depot_list)

    thread = threading.Thread(
        target=_async_job_thread,
        args=(job_id, truck_id, depot_list, desired_bids, mp_cfg, on_complete, headless, record_on_bid_start),
        daemon=True,
        name=f"mp-orchestrator-{job_id[:8]}",
    )
    print(f"Thread starting: {thread.name}, daemon={thread.daemon}")
    thread.start()
    print(f"Thread started: {thread.name}")

    return {
        "status": "queued",
        "job_id": job_id,
        "truck_id": truck_id,
        "depots": depot_list,
        "execution_mode": "multiprocess",
        "multiprocess_max_workers": mp_cfg["max_parallel_workers"],
        "message": "Job queued; poll GET /api/bid-job/{job_id}",
        "poll_path": f"/api/bid-job/{job_id}",
    }
