"""
Multiprocessing worker entry point: one Chrome + one depot per process.

Must remain a top-level function for Windows spawn compatibility.

After a successful depot run, optional POST_EXECUTE keepalive (see
automation.multiprocess.keep_browser_open) keeps the WebDriver and Chrome open
so the SAP session stays visible; no driver.quit() unless disabled or on error.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config_loader import get_app_config
from . import execution_logging as elog
from . import bid_logging as blog
from .depot_normalization import normalize_depot_name
from .depot_bidding_engine import DepotBiddingEngine, DesiredBid
from .driver_factory import create_driver
from .login_service import login
from .logging_service import configure_named_logger, get_logging_settings
from .start_in_observer import start_observer_for_worker
from .window_rotation import register_window, unregister_window

_ENGINE_LOGGER_NAME = "backend_automation.depot_bidding_engine"


class _EnginePrefixFormatter(logging.Formatter):
    def __init__(self, prefix: str, inner: logging.Formatter | None) -> None:
        super().__init__()
        self._prefix = prefix
        self._inner = inner

    def format(self, record: logging.LogRecord) -> str:
        if self._inner is not None:
            body = self._inner.format(record)
        else:
            body = record.getMessage()
        return f"{self._prefix} {body}"


def _apply_engine_log_prefix(depot_name: str) -> List[Tuple[logging.Handler, logging.Formatter | None]]:
    pid = os.getpid()
    prefix = f"[Worker PID={pid} | Depot {depot_name}]"
    eng = logging.getLogger(_ENGINE_LOGGER_NAME)
    restored: List[Tuple[logging.Handler, logging.Formatter | None]] = []
    for h in eng.handlers:
        restored.append((h, h.formatter))
        h.setFormatter(_EnginePrefixFormatter(prefix, h.formatter))
    return restored


def _restore_engine_log_formatters(
    restored: List[Tuple[logging.Handler, logging.Formatter | None]],
) -> None:
    for h, fmt in restored:
        try:
            h.setFormatter(fmt)
        except Exception:
            pass


def _configure_worker_logging(depot_name: str) -> logging.LoggerAdapter:
    tag = depot_name or "unknown"
    settings = get_logging_settings()
    console = bool(settings.get("general_console_enabled", True))
    base = logging.getLogger(f"selenium_worker.{tag}")
    configure_named_logger(base, tag, level=logging.INFO, console=console)
    # Also attach All_logs.log handler so selenium_worker logs appear in unified log
    gen_dir = Path(__file__).resolve().parent.parent / str(settings.get("general_log_dir", "logs/All_logs"))
    gen_dir.mkdir(parents=True, exist_ok=True)
    all_logs_path = gen_dir / "All_logs.log"
    # Check if handler already exists
    has_all_logs = any(
        getattr(h, 'baseFilename', None) == str(all_logs_path)
        for h in base.handlers
    )
    if not has_all_logs:
        fh = logging.FileHandler(str(all_logs_path), mode="a", encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        base.addHandler(fh)
    return logging.LoggerAdapter(base, {"depot_tag": tag})


def _env_truthy(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _session_keepalive_settings(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Multiprocess worker: keep Chrome open after depot run (see application.yaml automation.multiprocess)."""
    mp_cfg = (cfg.get("automation") or {}).get("multiprocess") or {}
    keep = bool(mp_cfg.get("keep_browser_open", True))
    if os.getenv("AUTOMATION_KEEP_BROWSER_OPEN") is not None:
        keep = _env_truthy("AUTOMATION_KEEP_BROWSER_OPEN", default=keep)
    only_after_auto = bool(mp_cfg.get("keep_browser_open_only_after_automation", False))
    mode = str(mp_cfg.get("post_execute_mode", "passive")).strip().lower()
    if mode not in ("passive", "monitor"):
        mode = "passive"
    interval = float(mp_cfg.get("post_execute_interval_seconds", 5) or 5)
    if interval < 1.0:
        interval = 1.0
    max_sec = mp_cfg.get("post_execute_max_seconds")
    max_f: Optional[float] = None
    if max_sec is not None and str(max_sec).strip() != "":
        try:
            max_f = float(max_sec)
        except (TypeError, ValueError):
            max_f = None
    return {
        "keep_browser_open": keep,
        "keep_browser_open_only_after_automation": only_after_auto,
        "post_execute_mode": mode,
        "post_execute_interval_seconds": interval,
        "post_execute_max_seconds": max_f,
    }


def _post_execute_keepalive(
    engine: DepotBiddingEngine,
    log: logging.LoggerAdapter,
    settings: Dict[str, Any],
) -> None:
    """
    POST_EXECUTE / IDLE: keep process alive so Chrome stays open. No bidding actions.
    monitor mode: read-only timer text for observation (does not trigger EXEC).
    Exits immediately if bid was stopped via user_control.
    """
    mode = settings["post_execute_mode"]
    interval = float(settings["post_execute_interval_seconds"])
    max_f: Optional[float] = settings.get("post_execute_max_seconds")

    deadline: Optional[float] = None
    if max_f is not None and max_f > 0:
        deadline = time.monotonic() + max_f

    log.info(
        "POST_EXECUTE: state=IDLE mode=%s interval=%.1fs max_seconds=%s — SAP session kept open (no driver.quit)",
        mode,
        interval,
        "unlimited" if deadline is None else str(max_f),
    )
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            log.info("POST_EXECUTE: max keepalive elapsed — worker will release WebDriver")
            return

        # Check if bid was stopped via user_control - exit keepalive immediately
        try:
            from .live_bids_store import get_user_control
            job_id = getattr(engine, 'job_id', None)
            depot_name = getattr(engine, 'depot_name', None)
            if job_id and depot_name:
                for db in (engine._desired_bids if hasattr(engine, '_desired_bids') else []):
                    qty = getattr(db, 'quantity', 0)
                    dest = getattr(db, 'destination', None)
                    control = get_user_control(job_id, depot_name, qty, dest)
                    if control == "stopped":
                        log.info(
                            "POST_EXECUTE: user_control=stopped detected for job_id=%s depot=%s — exiting keepalive",
                            job_id, depot_name,
                        )
                        return
        except Exception:
            pass  # Don't crash keepalive on DB check failure

        time.sleep(interval)
        if mode == "monitor":
            try:
                t = engine._read_timer_text()
                log.info("POST_EXECUTE: monitor timer=%r", (t or "")[:160])
            except Exception as e:
                log.warning("POST_EXECUTE: monitor read failed: %s", e)
        else:
            log.info(
                "POST_EXECUTE: session alive — PID=%s (passive)",
                os.getpid(),
            )


def run_depot_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    depot = normalize_depot_name(str(payload.get("depot_name", "")).strip())
    truck_id = str(payload.get("truck_id", ""))
    desired_raw: List[dict] = payload.get("desired_bids") or []
    job_id = payload.get("job_id")
    outer_retries = max(1, int(payload.get("worker_retry_attempts", 2)))
    rotation_registry = payload.get("rotation_registry")
    rotation_lock = payload.get("rotation_lock")
    rotation_expected_raw = payload.get("rotation_expected_depots")
    rotation_expected_depots = (
        [str(x) for x in rotation_expected_raw]
        if isinstance(rotation_expected_raw, (list, tuple))
        else None
    )
    
    # Get headless and record overrides from payload
    headless_override = payload.get("headless")
    record_on_bid_start = payload.get("record_on_bid_start")

    log = _configure_worker_logging(depot or "unknown")
    
    if headless_override is not None:
        log.info(f"Headless mode from API: {headless_override}")
    if record_on_bid_start is not None:
        log.info(f"Record on bid start from API: {record_on_bid_start}")

    t0 = time.perf_counter()
    pid = os.getpid()
    elog.init_execution_logging(str(job_id) if job_id else None, depot or "unknown", pid)
    
    # Check if bid was stopped before starting browser
    if desired_raw and job_id:
        from .live_bids_store import get_user_control
        for b in desired_raw:
            qty = float(b.get("quantity", 0))
            if qty <= 0:
                continue
            bd = b.get("depot")
            dd = (
                normalize_depot_name(str(bd))
                if bd is not None and str(bd).strip()
                else depot
            )
            control = get_user_control(
                job_id=str(job_id),
                depot=dd or depot or "",
                quantity=qty,
                destination=b.get("destination"),
            )
            if control == "stopped":
                log.warning(
                    "[Depot %s] Bid was stopped before starting - exiting worker",
                    depot or "?",
                )
                return {
                    "depot": depot or "",
                    "status": "stopped",
                    "rows": 0,
                    "prepared_bids": [],
                    "automation_executed": False,
                    "bids_submitted": 0,
                }
    
    # Log worker start with bid context
    if desired_raw and job_id:
        blog.log_bid_start(
            job_id=str(job_id),
            depot=depot,
            quantity=desired_raw[0].get("quantity", 0) if desired_raw else 0,
            destination=desired_raw[0].get("destination", "")
        )

    # Register worker PID in registry for force-kill on stop
    _registered_leg_ids = []
    if desired_raw and job_id:
        from .worker_registry import register_worker, unregister_worker
        from .live_bids_store import make_leg_id
        for b in desired_raw:
            qty = float(b.get("quantity", 0))
            if qty <= 0:
                continue
            bd = b.get("depot")
            dd = (
                normalize_depot_name(str(bd))
                if bd is not None and str(bd).strip()
                else depot
            )
            dest = b.get("destination")
            lid = make_leg_id(str(job_id), dd or depot or "", qty, dest)
            register_worker(lid, pid, str(job_id), dd or depot or "")
            _registered_leg_ids.append(lid)
        log.info(
            "[Depot %s] Registered %d leg(s) in worker registry (PID=%d)",
            depot or "?", len(_registered_leg_ids), pid,
        )
    
    elog.set_phase("WORKER")
    elog.log_event(
        phase="WORKER",
        component="worker",
        action="START",
        status="ok",
        message=f"Worker started truck_id={truck_id}",
        outer_retries=outer_retries,
        registry=rotation_registry is not None,
    )
    log.info(
        "[Depot %s] Worker started (PID=%s) truck_id=%s (no pre-driver delay; batching is orchestrator-only)",
        depot or "?",
        pid,
        truck_id,
    )
    log.info(
        "[ROTATION][REG] Worker started "
        "job_id=%s depot=%s worker_pid=%s registry=%s lock=%s",
        str(job_id) if job_id else "n/a",
        depot or "?",
        pid,
        rotation_registry is not None,
        rotation_lock is not None,
    )
    elog.log_event(
        phase="ROTATION",
        component="rotation",
        action="REG_WORKER_START",
        status="ok",
        message="Worker rotation registry context",
        registry=rotation_registry is not None,
        lock=rotation_lock is not None,
    )
    if rotation_registry is None:
        log.info(
            "[ROTATION][REG] Registry unavailable "
            "job_id=%s depot=%s worker_pid=%s "
            "reason=rotation_registry_is_None",
            str(job_id) if job_id else "n/a",
            depot or "?",
            pid,
        )

    desired: List[DesiredBid] = []
    for b in desired_raw:
        q = float(b.get("quantity", 0))
        if q <= 0:
            continue
        bd = b.get("depot")
        dd = (
            normalize_depot_name(str(bd))
            if bd is not None and str(bd).strip()
            else depot
        )
        desired.append(
            DesiredBid(quantity=q, destination=b.get("destination"), depot=dd)
        )

    cfg_early = get_app_config()
    session_cfg = _session_keepalive_settings(cfg_early)
    log.info(
        "[Depot %s] Session policy: keep_browser_open=%s only_after_automation=%s post_execute_mode=%s",
        depot or "?",
        session_cfg["keep_browser_open"],
        session_cfg.get("keep_browser_open_only_after_automation", False),
        session_cfg["post_execute_mode"],
    )

    last_error: str | None = None
    for attempt in range(1, outer_retries + 1):
        driver = None
        engine = None
        restored: List[Tuple[logging.Handler, logging.Formatter | None]] = []
        skip_driver_quit = False
        rotation_registered = False
        start_in_obs = None
        try:
            restored = _apply_engine_log_prefix(depot or "?")
            elog.set_phase("BROWSER")
            elog.log_event(
                phase="BROWSER",
                component="driver",
                action="CREATE_START",
                status="ok",
                message=f"Creating driver attempt={attempt}/{outer_retries}",
                retry=f"{attempt}/{outer_retries}",
            )
            log.info(
                "[Depot %s] Creating driver (outer attempt %d/%d)",
                depot or "?",
                attempt,
                outer_retries,
            )
            t_drv = time.perf_counter()
            driver = create_driver(headless_override=headless_override)
            elog.log_timing(
                "Driver creation",
                (time.perf_counter() - t_drv) * 1000.0,
                phase="BROWSER",
                component="driver",
            )
            driver.set_page_load_timeout(90)
            driver.implicitly_wait(0)
            elog.log_event(
                phase="BROWSER",
                component="driver",
                action="CREATE_OK",
                status="ok",
                message="Driver created",
            )
            log.info("[Depot %s] Driver created (PID=%s)", depot or "?", os.getpid())

            cfg = get_app_config()
            session_cfg = _session_keepalive_settings(cfg)
            base_url = (cfg.get("sap", {}) or {}).get("base_url")
            if not base_url:
                raise RuntimeError("sap.base_url missing")

            driver.get(base_url)
            elog.set_phase("LOGIN")
            elog.log_event(
                phase="LOGIN",
                component="login",
                action="START",
                status="ok",
                message="Phase: SAP login",
            )
            log.info("Phase: SAP login")
            t_login = time.perf_counter()
            login(driver)
            elog.log_timing(
                "Login",
                (time.perf_counter() - t_login) * 1000.0,
                phase="LOGIN",
                component="login",
            )
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            elog.log_event(
                phase="LOGIN",
                component="login",
                action="SUCCESS",
                status="ok",
                message="Login completed; session active",
            )
            log.info("Login completed; session active in this process")

            engine = DepotBiddingEngine(
                driver=driver,
                depot_name=depot,
                desired_bids=desired,
                job_id=str(job_id) if job_id else None,
            )
            elog.set_phase("APP")
            elog.log_event(
                phase="APP",
                component="bidding_app",
                action="OPEN_START",
                status="ok",
                message="Phase: open E-Bidding app",
            )
            log.info("Phase: open E-Bidding app")
            t_app = time.perf_counter()
            engine._open_bidding_app()
            elog.log_timing(
                "Open E-Bidding app",
                (time.perf_counter() - t_app) * 1000.0,
                phase="APP",
                component="bidding_app",
            )
            elog.log_event(
                phase="APP",
                component="bidding_app",
                action="OPEN_OK",
                status="ok",
                message="E-Bidding app ready; depot processing + live monitoring",
            )
            log.info("E-Bidding app ready; phase: depot processing + live monitoring")

            # Operator visibility only — never gates bidding / Search / execute.
            if rotation_registry is not None:
                log.info(
                    "[ROTATION][REG] Registration about to start "
                    "job_id=%s depot=%s worker_pid=%s",
                    str(job_id) if job_id else "n/a",
                    depot or "?",
                    os.getpid(),
                )
                rotation_registered = register_window(
                    rotation_registry,
                    job_id=str(job_id) if job_id else "",
                    depot=depot or "",
                    driver=driver,
                    lock=rotation_lock,
                    expected_depots=rotation_expected_depots,
                )
                elog.log_event(
                    phase="ROTATION",
                    component="rotation",
                    action="REG_RESULT",
                    status="ok" if rotation_registered else "warn",
                    message=f"Window registration registered={rotation_registered}",
                )
            else:
                log.info(
                    "[ROTATION][REG] Registration skipped "
                    "job_id=%s depot=%s worker_pid=%s "
                    "reason=rotation_registry_is_None",
                    str(job_id) if job_id else "n/a",
                    depot or "?",
                    os.getpid(),
                )
                elog.log_event(
                    phase="ROTATION",
                    component="rotation",
                    action="REG_SKIP",
                    status="skip",
                    message="Registration skipped — rotation_registry is None",
                )

            # Independent SAP Start In investigation observer (does not alter bidding).
            elog.set_phase("OBSERVER")
            start_in_obs = start_observer_for_worker(
                driver,
                job_id=str(job_id) if job_id else "",
                depot=depot or "",
                cfg=cfg,
            )
            elog.log_event(
                phase="OBSERVER",
                component="start_in",
                action="INSTALL_RESULT",
                status="ok" if start_in_obs is not None else "skip",
                message=f"Start In observer active={start_in_obs is not None}",
            )

            elog.set_phase("MONITOR")
            result = engine.process_single_depot(depot)
            result = dict(result)
            result["worker_pid"] = os.getpid()
            result["worker_duration_sec"] = round(time.perf_counter() - t0, 2)
            result["outer_attempt"] = attempt
            result["browser_session_kept_open"] = bool(session_cfg["keep_browser_open"])
            elog.log_timing(
                "Worker duration",
                (time.perf_counter() - t0) * 1000.0,
                phase="WORKER",
                component="worker",
            )
            elog.log_event(
                phase="WORKER",
                component="worker",
                action="COMPLETED",
                status=str(result.get("status") or "ok"),
                message=f"Worker completed rows={result.get('rows')}",
                rows=result.get("rows"),
            )
            log.info(
                "[Depot %s] Worker completed status=%s rows=%s (PID=%s)",
                depot or "?",
                result.get("status"),
                result.get("rows"),
                os.getpid(),
            )
            
            # Log worker end with bid context
            if desired_raw and job_id:
                duration_ms = (time.perf_counter() - t0) * 1000
                # Check database for actual status (orphaned/stopped) before logging
                bid_status = str(result.get("status") or "completed")
                try:
                    from .live_bids_store import get_user_control
                    
                    # Check each desired bid for user_control status
                    for b in desired_raw:
                        qty = float(b.get("quantity", 0))
                        if qty <= 0:
                            continue
                        bd = b.get("depot")
                        dd = (
                            normalize_depot_name(str(bd))
                            if bd is not None and str(bd).strip()
                            else depot
                        )
                        control = get_user_control(
                            job_id=str(job_id),
                            depot=dd or depot or "",
                            quantity=qty,
                            destination=b.get("destination"),
                        )
                        if control == "stopped":
                            bid_status = "stopped"
                            log.info(
                                "[BID] STOPPED via user_control job_id=%s depot=%s qty=%s bid_id=%s",
                                str(job_id),
                                dd or depot or "",
                                qty,
                                blog._get_bid_id(),
                            )
                            break
                    
                    # Check if any bid was marked as orphaned in the database
                    from .live_bids_store import list_live_bids
                    live_bids = list_live_bids(job_id=str(job_id))
                    for bid in live_bids.get("items", []):
                        if bid.get("status") == "orphaned":
                            bid_status = "orphaned"
                            log.info(
                                "[BID] BID ORPHANED job_id=%s depot=%s qty=%.1f bid_id=%s",
                                str(job_id),
                                bid.get("depot"),
                                bid.get("quantity", 0),
                                blog._get_bid_id(),
                            )
                            break
                            
                except Exception:
                    pass  # Use default status if database check fails
                
                blog.log_bid_end(
                    job_id=str(job_id),
                    status=bid_status,
                    duration_ms=duration_ms
                )
                log.info(
                    "[BID] BID END job_id=%s status=%s duration_ms=%.0f",
                    str(job_id),
                    bid_status,
                    duration_ms,
                )

            # Leave rotation immediately on depot completion (even if Chrome stays open).
            if rotation_registered:
                unregister_window(
                    rotation_registry,
                    depot or "",
                    lock=rotation_lock,
                    reason="completed",
                    expected_depots=rotation_expected_depots,
                )
                rotation_registered = False

            if session_cfg["keep_browser_open"]:
                need_keep = True
                # Skip POST_EXECUTE if bid was stopped by user
                result_status = result.get("status", "") if isinstance(result, dict) else ""
                log.info(
                    "[Depot %s] keep_browser_open check: result_status=%s need_keep=%s skip_driver_quit=%s",
                    depot or "?",
                    result_status,
                    need_keep,
                    skip_driver_quit,
                )
                if result_status in ("stopped", "no_rows"):
                    need_keep = False
                    log.info(
                        "[Depot %s] Skipping POST_EXECUTE: bid was stopped (status=%s)",
                        depot or "?",
                        result_status,
                    )
                if session_cfg.get("keep_browser_open_only_after_automation") and not result.get(
                    "automation_executed"
                ):
                    need_keep = False
                    log.info(
                        "[Depot %s] keep_browser_open_only_after_automation: no automation — will close WebDriver",
                        depot or "?",
                    )
                if need_keep:
                    skip_driver_quit = True
                    log.info(
                        "[Depot %s] Keeping WebDriver alive after depot run (POST_EXECUTE / IDLE)",
                        depot or "?",
                    )
                    elog.set_phase("POST_EXEC")
                    elog.log_event(
                        phase="POST_EXEC",
                        component="keepalive",
                        action="START",
                        status="ok",
                        message="Keeping WebDriver alive after depot run",
                    )
                    _post_execute_keepalive(engine, log, session_cfg)
                    # After keepalive ends, check if it was stopped by user
                    # If stopped, close the browser. Otherwise keep it open.
                    try:
                        from .live_bids_store import get_user_control
                        _job_id = getattr(engine, 'job_id', None)
                        _depot_name = getattr(engine, 'depot_name', None)
                        _was_stopped = False
                        if _job_id and _depot_name:
                            for _db in (engine._desired_bids if hasattr(engine, '_desired_bids') else []):
                                _qty = getattr(_db, 'quantity', 0)
                                _dest = getattr(_db, 'destination', None)
                                _ctrl = get_user_control(_job_id, _depot_name, _qty, _dest)
                                if _ctrl == "stopped":
                                    _was_stopped = True
                                    break
                        if _was_stopped:
                            skip_driver_quit = False
                            log.info(
                                "[Depot %s] Bid was STOPPED — browser will be closed",
                                depot or "?",
                            )
                        else:
                            skip_driver_quit = True
                            log.info(
                                "[Depot %s] POST_EXECUTE ended — browser kept open (keep_browser_open=true)",
                                depot or "?",
                            )
                    except Exception:
                        # If check fails, close browser to be safe
                        skip_driver_quit = False
                        log.info(
                            "[Depot %s] POST_EXECUTE ended — closing browser (safety fallback)",
                            depot or "?",
                        )
            elog.shutdown_execution_logging(
                status=str(result.get("status") or "ok"),
                message="Worker returning success path",
                duration_sec=time.perf_counter() - t0,
            )
            # Unregister worker from registry on exit
            for lid in _registered_leg_ids:
                try:
                    from .worker_registry import unregister_worker
                    unregister_worker(lid)
                except Exception:
                    pass
            return result
        except Exception as e:
            last_error = str(e)
            
            # Check database for actual status (orphaned/stopped)
            bid_status = "failed"
            if desired_raw and job_id:
                try:
                    from .live_bids_store import get_user_control, list_live_bids
                    
                    # Check each desired bid for user_control status
                    for b in desired_raw:
                        qty = float(b.get("quantity", 0))
                        if qty <= 0:
                            continue
                        bd = b.get("depot")
                        dd = (
                            normalize_depot_name(str(bd))
                            if bd is not None and str(bd).strip()
                            else depot
                        )
                        control = get_user_control(
                            job_id=str(job_id),
                            depot=dd or depot or "",
                            quantity=qty,
                            destination=b.get("destination"),
                        )
                        if control == "stopped":
                            bid_status = "stopped"
                            break
                    
                    # Check if any bid was marked as orphaned in the database
                    live_bids = list_live_bids(job_id=str(job_id))
                    for bid in live_bids.get("items", []):
                        if bid.get("status") == "orphaned":
                            bid_status = "orphaned"
                            break
                            
                except Exception:
                    pass  # Use default status if database check fails
            
            elog.log_error(
                phase="WORKER",
                component="worker",
                action="ATTEMPT_FAIL",
                message=f"Worker attempt {attempt} failed - status={bid_status}",
                exc=e,
                retry=f"{attempt}/{outer_retries}",
                recovery="stop" if bid_status == "orphaned" or bid_status == "stopped" else ("retry" if attempt < outer_retries else "exhaust"),
            )
            log.exception("Worker attempt %d failed: %s", attempt, e)
        finally:
            elog.set_phase("CLEANUP")
            if start_in_obs is not None:
                try:
                    start_in_obs.stop()
                    elog.log_event(
                        phase="OBSERVER",
                        component="start_in",
                        action="STOP",
                        status="ok",
                        message="Start In observer stopped",
                    )
                except Exception:
                    pass
                start_in_obs = None
            if rotation_registered:
                unregister_window(
                    rotation_registry,
                    depot or "",
                    lock=rotation_lock,
                    reason="worker_exit",
                    expected_depots=rotation_expected_depots,
                )
                elog.log_event(
                    phase="ROTATION",
                    component="rotation",
                    action="UNREG",
                    status="ok",
                    message="Window unregistered reason=worker_exit",
                )
                rotation_registered = False
            quit_drv = engine.driver if engine is not None else driver
            if quit_drv and not skip_driver_quit:
                try:
                    log.info(
                        "[Depot %s] WebDriver quit (lifecycle cleanup, PID=%s, skip_driver_quit=%s)",
                        depot or "?",
                        os.getpid(),
                        skip_driver_quit,
                    )
                    quit_drv.quit()
                    elog.log_event(
                        phase="CLEANUP",
                        component="driver",
                        action="QUIT",
                        status="ok",
                        message="WebDriver quit",
                    )
                except Exception as e:
                    log.warning("WebDriver quit failed: %s", e)
                    elog.log_error(
                        phase="CLEANUP",
                        component="driver",
                        action="QUIT_FAIL",
                        message="WebDriver quit failed",
                        exc=e,
                        recovery="ignore",
                    )
            elif quit_drv and skip_driver_quit:
                log.info(
                    "[Depot %s] WebDriver NOT quit (skip_driver_quit=True, keep_browser_open, PID=%s)",
                    depot or "?",
                    os.getpid(),
                )
            else:
                log.info(
                    "[Depot %s] WebDriver NOT quit (no driver available, PID=%s)",
                    depot or "?",
                    os.getpid(),
                )
            _restore_engine_log_formatters(restored)
        time.sleep(min(5.0, 1.0 * attempt))

    elog.shutdown_execution_logging(
        status="failed",
        message=last_error or "worker_exhausted",
        duration_sec=time.perf_counter() - t0,
    )
    # Unregister worker from registry on exit
    for lid in _registered_leg_ids:
        try:
            from .worker_registry import unregister_worker
            unregister_worker(lid)
        except Exception:
            pass
    return {
        "depot": depot,
        "status": "failed",
        "rows": 0,
        "prepared_bids": [],
        "error": last_error or "worker_exhausted",
        "worker_pid": os.getpid(),
        "worker_duration_sec": round(time.perf_counter() - t0, 2),
    }
