"""
Execution-centric logging for All_logs/ (additive; does not replace legacy logging_service).

Logging-only module. Never raises into callers. Never affects bidding control flow.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import traceback
import uuid
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ALL_LOGS_DEFAULT = "logs/All_logs"

_ctx_job_id: ContextVar[str] = ContextVar("elog_job_id", default="")
_ctx_depot: ContextVar[str] = ContextVar("elog_depot", default="")
_ctx_worker_pid: ContextVar[int] = ContextVar("elog_worker_pid", default=0)
_ctx_execution_id: ContextVar[str] = ContextVar("elog_execution_id", default="")
_ctx_phase: ContextVar[str] = ContextVar("elog_phase", default="")
_ctx_enabled: ContextVar[bool] = ContextVar("elog_enabled", default=False)

_lock = threading.RLock()
_job_loggers: dict[str, logging.Logger] = {}
_exec_loggers: dict[str, logging.Logger] = {}
_settings_cache: dict[str, Any] | None = None
_summary_lock = threading.RLock()

_THRESHOLDS = frozenset({10, 5, 4, 3, 2, 1, 0})


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _default_settings() -> dict[str, Any]:
    return {
        "enabled": True,
        "all_logs_root": _ALL_LOGS_DEFAULT,
        "legacy_fanout_unchanged": True,
        "timer_heartbeat_seconds": 5.0,
        "timer_info_raw_polls": False,
        "console_echo": False,
    }


def get_execution_logging_settings() -> dict[str, Any]:
    global _settings_cache
    if _settings_cache is not None:
        return _settings_cache
    settings = _default_settings()
    try:
        import yaml

        path = _PROJECT_ROOT / "config" / "application.yaml"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            block = raw.get("execution_logging")
            if isinstance(block, dict):
                settings.update(block)
    except Exception:
        pass
    env_en = os.getenv("EXECUTION_LOGGING_ENABLED", "").strip().lower()
    if env_en in ("1", "true", "yes", "on"):
        settings["enabled"] = True
    elif env_en in ("0", "false", "no", "off"):
        settings["enabled"] = False
    env_root = os.getenv("EXECUTION_LOGGING_ROOT", "").strip()
    if env_root:
        settings["all_logs_root"] = env_root
    _settings_cache = settings
    return settings


def is_enabled() -> bool:
    return bool(get_execution_logging_settings().get("enabled", True))


def all_logs_root() -> Path:
    rel = str(get_execution_logging_settings().get("all_logs_root") or _ALL_LOGS_DEFAULT)
    p = Path(rel)
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_job_id(job_id: str | None) -> str:
    raw = (job_id or "").strip() or "nojid"
    return re.sub(r"[^\w\-]+", "_", raw)[:64] or "nojid"


def _safe_depot(depot: str | None) -> str:
    d = (depot or "UNKNOWN").strip().upper() or "UNKNOWN"
    return re.sub(r"[^\w\-]+", "_", d)[:64] or "UNKNOWN"


def job_dir(job_id: str | None) -> Path:
    d = all_logs_root() / _safe_job_id(job_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "executions").mkdir(parents=True, exist_ok=True)
    return d


def execution_log_path(job_id: str | None, depot: str | None) -> Path:
    return job_dir(job_id) / "executions" / f"{_safe_depot(depot)}_execution.log"


def timer_samples_path(job_id: str | None) -> Path:
    return job_dir(job_id) / "timer_samples.jsonl"


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

def set_phase(phase: str) -> None:
    _ctx_phase.set(str(phase or ""))


def get_phase() -> str:
    return _ctx_phase.get() or ""


def new_execution_id() -> str:
    eid = uuid.uuid4().hex[:12]
    _ctx_execution_id.set(eid)
    return eid


def get_execution_id() -> str:
    return _ctx_execution_id.get() or ""


def set_execution_id(execution_id: str) -> None:
    _ctx_execution_id.set(str(execution_id or ""))


def current_job_id() -> str:
    return _ctx_job_id.get() or ""


def current_depot() -> str:
    return _ctx_depot.get() or ""


# ---------------------------------------------------------------------------
# Handlers / loggers
# ---------------------------------------------------------------------------

class _ExecutionFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.") + f"{int(datetime.now().microsecond / 1000):03d}"
        job = getattr(record, "elog_job_id", "") or ""
        eid = getattr(record, "elog_execution_id", "") or ""
        depot = getattr(record, "elog_depot", "") or ""
        pid = getattr(record, "elog_pid", 0) or 0
        phase = getattr(record, "elog_phase", "") or ""
        component = getattr(record, "elog_component", "") or ""
        action = getattr(record, "elog_action", "") or ""
        status = getattr(record, "elog_status", "") or ""
        msg = record.getMessage()
        return (
            f"{ts} | job={job} | exec={eid} | depot={depot} | pid={pid} | "
            f"phase={phase} | component={component} | action={action} | "
            f"status={status} | {msg}"
        )


def _make_file_logger(name: str, path: Path, *, console: bool = False) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(_ExecutionFormatter())
    logger.addHandler(fh)
    if console and bool(get_execution_logging_settings().get("console_echo", False)):
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(_ExecutionFormatter())
        logger.addHandler(ch)
    return logger


def _job_logger(job_id: str, filename: str) -> logging.Logger:
    key = f"{_safe_job_id(job_id)}::{filename}"
    with _lock:
        if key in _job_loggers:
            return _job_loggers[key]
        path = job_dir(job_id) / filename
        lg = _make_file_logger(f"logibid.job.{key}", path)
        _job_loggers[key] = lg
        return lg


def _exec_logger(job_id: str, depot: str) -> logging.Logger:
    key = f"{_safe_job_id(job_id)}::{_safe_depot(depot)}"
    with _lock:
        if key in _exec_loggers:
            return _exec_loggers[key]
        path = execution_log_path(job_id, depot)
        lg = _make_file_logger(f"logibid.exec.{key}", path)
        _exec_loggers[key] = lg
        return lg


# ---------------------------------------------------------------------------
# Job / execution lifecycle
# ---------------------------------------------------------------------------

def init_job_logging(
    job_id: str,
    depots: list[str] | None = None,
    *,
    extra: dict[str, Any] | None = None,
) -> Path | None:
    """Parent process: create All_logs job folder, summary/job/orchestrator files, pre-create execution files."""
    if not is_enabled():
        return None
    try:
        jid = str(job_id or "").strip()
        if not jid:
            return None
        root = job_dir(jid)
        dep_list = [_safe_depot(d) for d in (depots or []) if str(d).strip()]
        for d in dep_list:
            p = execution_log_path(jid, d)
            if not p.exists():
                p.write_text(
                    f"# Execution log pre-created for depot={d} job={jid}\n",
                    encoding="utf-8",
                )
            _exec_logger(jid, d)

        _job_logger(jid, "summary.log")
        _job_logger(jid, "job.log")
        _job_logger(jid, "orchestrator.log")
        _job_logger(jid, "rotation.log")

        meta_path = root / "meta.json"
        already = meta_path.exists()
        meta = {
            "job_id": jid,
            "depots": dep_list,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "parent_pid": os.getpid(),
        }
        if extra:
            meta.update(extra)
        if not already:
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        _init_summary_state(jid, dep_list)

        if not already:
            log_job(
                jid,
                phase="JOB",
                component="job",
                action="START",
                status="ok",
                message=f"Job started depots={dep_list}",
                depot="*",
            )
            log_summary_line(
                jid, f"JOB_START job={jid} depots={','.join(dep_list)} pid={os.getpid()}"
            )
        return root
    except Exception:
        return None


def init_execution_logging(
    job_id: str | None,
    depot: str | None,
    worker_pid: int | None = None,
) -> Path | None:
    """Worker process: bind context and open depot execution log."""
    if not is_enabled():
        _ctx_enabled.set(False)
        return None
    try:
        jid = str(job_id or "").strip() or "nojid"
        dep = _safe_depot(depot)
        pid = int(worker_pid or os.getpid())
        _ctx_job_id.set(jid)
        _ctx_depot.set(dep)
        _ctx_worker_pid.set(pid)
        _ctx_execution_id.set("")
        _ctx_phase.set("WORKER")
        _ctx_enabled.set(True)
        path = execution_log_path(jid, dep)
        _exec_logger(jid, dep)
        log_event(
            phase="WORKER",
            component="worker",
            action="START",
            status="ok",
            message=f"Execution logging bound depot={dep} worker_pid={pid}",
            job_id=jid,
            depot=dep,
        )
        return path
    except Exception:
        _ctx_enabled.set(False)
        return None


def shutdown_execution_logging(
    *,
    status: str = "ok",
    message: str = "Worker shutdown",
    duration_sec: float | None = None,
) -> None:
    try:
        if not _ctx_enabled.get() and not is_enabled():
            return
        meta: dict[str, Any] = {}
        if duration_sec is not None:
            meta["duration_sec"] = round(float(duration_sec), 2)
        log_event(
            phase="SHUTDOWN",
            component="worker",
            action="EXIT",
            status=status,
            message=message,
            **meta,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Emitters
# ---------------------------------------------------------------------------

def _format_meta(meta: dict[str, Any]) -> str:
    if not meta:
        return ""
    parts: list[str] = []
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, float):
            parts.append(f"{k}={v:.4g}")
        else:
            s = str(v).replace("\n", " ").strip()
            if len(s) > 200:
                s = s[:200] + "…"
            if " " in s or "=" in s:
                s = repr(s)
            parts.append(f"{k}={s}")
    return (" | " + " ".join(parts)) if parts else ""


def log_event(
    *,
    phase: str | None = None,
    component: str = "",
    action: str = "",
    status: str = "ok",
    message: str = "",
    level: int = logging.INFO,
    job_id: str | None = None,
    depot: str | None = None,
    execution_id: str | None = None,
    worker_pid: int | None = None,
    **meta: Any,
) -> None:
    """Write one structured line to the depot execution log (and never raise)."""
    try:
        if not is_enabled():
            return
        jid = str(job_id if job_id is not None else _ctx_job_id.get() or "").strip()
        dep = _safe_depot(depot if depot is not None else _ctx_depot.get() or "UNKNOWN")
        if not jid:
            jid = "nojid"
        eid = str(execution_id if execution_id is not None else _ctx_execution_id.get() or "")
        pid = int(worker_pid if worker_pid is not None else (_ctx_worker_pid.get() or os.getpid()))
        ph = str(phase if phase is not None else (_ctx_phase.get() or ""))
        if phase:
            _ctx_phase.set(ph)

        lg = _exec_logger(jid, dep)
        body = f"{message}{_format_meta(meta)}"
        rec = lg.makeRecord(
            lg.name,
            level,
            "(execution_logging)",
            0,
            body,
            (),
            None,
        )
        rec.elog_job_id = jid
        rec.elog_execution_id = eid
        rec.elog_depot = dep
        rec.elog_pid = pid
        rec.elog_phase = ph
        rec.elog_component = component
        rec.elog_action = action
        rec.elog_status = status
        lg.handle(rec)
    except Exception:
        pass


def log_timing(
    name: str,
    duration_ms: float,
    *,
    phase: str | None = None,
    component: str = "performance",
    **meta: Any,
) -> None:
    log_event(
        phase=phase or get_phase() or "PERF",
        component=component,
        action="TIMING",
        status="ok",
        message=f"{name}",
        duration_ms=round(float(duration_ms), 2),
        **meta,
    )


def log_error(
    *,
    phase: str | None = None,
    component: str = "error",
    action: str = "EXCEPTION",
    message: str = "",
    exc: BaseException | None = None,
    recovery: str | None = None,
    retry: Any = None,
    timer: str | None = None,
    **meta: Any,
) -> None:
    fields: dict[str, Any] = dict(meta)
    if retry is not None:
        fields["retry"] = retry
    if timer is not None:
        fields["timer"] = timer
    if recovery:
        fields["recovery"] = recovery
    if exc is not None:
        fields["exc_type"] = type(exc).__name__
        fields["exc_msg"] = str(exc)
        try:
            fields["stack"] = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )[-1500:]
        except Exception:
            pass
    log_event(
        phase=phase or get_phase() or "ERROR",
        component=component,
        action=action,
        status="error",
        message=message or (str(exc) if exc else "error"),
        level=logging.ERROR,
        **fields,
    )


def log_job(
    job_id: str,
    *,
    phase: str = "JOB",
    component: str = "job",
    action: str = "",
    status: str = "ok",
    message: str = "",
    depot: str = "*",
    level: int = logging.INFO,
    file: str = "job.log",
    **meta: Any,
) -> None:
    try:
        if not is_enabled():
            return
        jid = str(job_id or "").strip()
        if not jid:
            return
        lg = _job_logger(jid, file)
        body = f"{message}{_format_meta(meta)}"
        rec = lg.makeRecord(lg.name, level, "(execution_logging)", 0, body, (), None)
        rec.elog_job_id = jid
        rec.elog_execution_id = ""
        rec.elog_depot = depot
        rec.elog_pid = os.getpid()
        rec.elog_phase = phase
        rec.elog_component = component
        rec.elog_action = action
        rec.elog_status = status
        lg.handle(rec)
    except Exception:
        pass


def log_orchestrator(job_id: str, message: str, **meta: Any) -> None:
    log_job(
        job_id,
        phase="ORCHESTRATOR",
        component="orchestrator",
        action=meta.pop("action", "INFO"),
        status=meta.pop("status", "ok"),
        message=message,
        file="orchestrator.log",
        **meta,
    )


def log_rotation_job(job_id: str, message: str, **meta: Any) -> None:
    log_job(
        job_id,
        phase="ROTATION",
        component="rotation",
        action=meta.pop("action", "INFO"),
        status=meta.pop("status", "ok"),
        message=message,
        file="rotation.log",
        depot=str(meta.pop("depot", "*")),
        **meta,
    )


def mirror_to_execution(
    job_id: str | None,
    depot: str | None,
    *,
    action: str,
    message: str,
    status: str = "ok",
    **meta: Any,
) -> None:
    """Parent → append into depot execution log (file bridge). Never raises."""
    try:
        if not is_enabled():
            return
        jid = str(job_id or "").strip()
        dep = _safe_depot(depot)
        if not jid or dep in ("", "UNKNOWN", "?"):
            return
        # Ensure file/logger exists even if worker has not started yet
        _exec_logger(jid, dep)
        log_event(
            phase="ROTATION",
            component="rotation",
            action=action,
            status=status,
            message=message,
            job_id=jid,
            depot=dep,
            worker_pid=os.getpid(),
            **meta,
        )
        bump_summary(jid, "rotation_events", 1)
        if action.upper().startswith("FREEZE_ON"):
            bump_summary(jid, "freeze_count", 1)
        if action.upper().startswith("FREEZE_OFF"):
            bump_summary(jid, "recovery_count", 1)
    except Exception:
        pass


def append_timer_sample_jsonl(job_id: str | None, record: dict[str, Any]) -> None:
    """Write analytics sample under All_logs (in addition to legacy path if caller keeps it)."""
    try:
        if not is_enabled():
            return
        jid = str(job_id or "").strip() or "nojid"
        path = timer_samples_path(jid)
        with _lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _summary_state_path(job_id: str) -> Path:
    return job_dir(job_id) / "summary_state.json"


def _init_summary_state(job_id: str, depots: list[str]) -> None:
    path = _summary_state_path(job_id)
    try:
        if path.exists():
            return
        state = {
            "job_id": job_id,
            "depots": depots,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "ended_at": None,
            "status": "running",
            "execution_count": 0,
            "failures": 0,
            "rotation_events": 0,
            "freeze_count": 0,
            "recovery_count": 0,
            "planner_accepts": 0,
            "planner_rejects": 0,
            "rank_one": 0,
            "depot_results": {},
        }
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def bump_summary(job_id: str | None, key: str, delta: int = 1) -> None:
    try:
        jid = str(job_id or "").strip()
        if not jid or not is_enabled():
            return
        path = _summary_state_path(jid)
        with _summary_lock:
            state: dict[str, Any] = {}
            if path.exists():
                try:
                    state = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    state = {}
            state[key] = int(state.get(key, 0) or 0) + int(delta)
            path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def record_depot_result_summary(
    job_id: str | None,
    depot: str,
    result: dict[str, Any] | None,
) -> None:
    try:
        jid = str(job_id or "").strip()
        if not jid or not is_enabled():
            return
        path = _summary_state_path(jid)
        with _summary_lock:
            state: dict[str, Any] = {}
            if path.exists():
                try:
                    state = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    state = {}
            dr = state.setdefault("depot_results", {})
            dr[_safe_depot(depot)] = {
                "status": (result or {}).get("status"),
                "rows": (result or {}).get("rows"),
                "error": (result or {}).get("error"),
                "worker_duration_sec": (result or {}).get("worker_duration_sec"),
            }
            if str((result or {}).get("status") or "").lower() == "failed":
                state["failures"] = int(state.get("failures", 0) or 0) + 1
            path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def log_summary_line(job_id: str | None, line: str) -> None:
    try:
        jid = str(job_id or "").strip()
        if not jid or not is_enabled():
            return
        lg = _job_logger(jid, "summary.log")
        rec = lg.makeRecord(lg.name, logging.INFO, "(summary)", 0, line, (), None)
        rec.elog_job_id = jid
        rec.elog_execution_id = ""
        rec.elog_depot = "*"
        rec.elog_pid = os.getpid()
        rec.elog_phase = "SUMMARY"
        rec.elog_component = "summary"
        rec.elog_action = "LINE"
        rec.elog_status = "ok"
        lg.handle(rec)
    except Exception:
        pass


def finalize_job_logging(
    job_id: str | None,
    *,
    status: str = "completed",
    duration_sec: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    try:
        jid = str(job_id or "").strip()
        if not jid or not is_enabled():
            return
        path = _summary_state_path(jid)
        with _summary_lock:
            state: dict[str, Any] = {}
            if path.exists():
                try:
                    state = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    state = {}
            state["ended_at"] = datetime.now().isoformat(timespec="seconds")
            state["status"] = status
            if duration_sec is not None:
                state["duration_sec"] = round(float(duration_sec), 2)
            if extra:
                state.update(extra)
            path.write_text(json.dumps(state, indent=2), encoding="utf-8")

        lines = [
            "======== JOB SUMMARY ========",
            f"job_id={jid}",
            f"status={state.get('status')}",
            f"started_at={state.get('started_at')}",
            f"ended_at={state.get('ended_at')}",
            f"duration_sec={state.get('duration_sec')}",
            f"depots={state.get('depots')}",
            f"execution_count={state.get('execution_count', 0)}",
            f"failures={state.get('failures', 0)}",
            f"rotation_events={state.get('rotation_events', 0)}",
            f"freeze_count={state.get('freeze_count', 0)}",
            f"recovery_count={state.get('recovery_count', 0)}",
            f"planner_accepts={state.get('planner_accepts', 0)}",
            f"planner_rejects={state.get('planner_rejects', 0)}",
            f"rank_one={state.get('rank_one', 0)}",
            f"depot_results={json.dumps(state.get('depot_results') or {}, ensure_ascii=False)}",
            "======== END SUMMARY ========",
        ]
        for line in lines:
            log_summary_line(jid, line)
        log_job(
            jid,
            phase="JOB",
            component="job",
            action="END",
            status=status,
            message=f"Job finished status={status}",
            duration_sec=state.get("duration_sec"),
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Timer poll summarizer (execution log only; does not change bidding)
# ---------------------------------------------------------------------------

class TimerPollSummarizer:
    """Compress high-frequency timer polls into meaningful execution-log events."""

    def __init__(self, heartbeat_seconds: float | None = None) -> None:
        cfg = get_execution_logging_settings()
        self._heartbeat = float(
            heartbeat_seconds
            if heartbeat_seconds is not None
            else cfg.get("timer_heartbeat_seconds", 5.0)
            or 5.0
        )
        self._last_text: str | None = None
        self._last_remaining: int | None = None
        self._polls = 0
        self._unchanged = 0
        self._last_heartbeat_mono = 0.0
        self._freeze_alerted = False
        self._freeze_threshold_polls = max(3, int(self._heartbeat / 0.1))

    def on_phase_start(self, *, timer_id: str, poll_interval: float, plan_rows: int) -> None:
        set_phase("TIMER")
        log_event(
            phase="TIMER",
            component="timer",
            action="PHASE_START",
            status="ok",
            message="Timer polling started",
            timer_id=timer_id,
            poll_interval=poll_interval,
            plan_rows=plan_rows,
        )

    def on_poll(self, text: str, *, is_trigger: bool) -> None:
        self._polls += 1
        t = (text or "").strip()
        remaining = _parse_remaining(t)

        # Raw polls only at DEBUG into execution log
        log_event(
            phase="TIMER",
            component="timer",
            action="POLL",
            status="ok",
            message=f"Current timer: {t}",
            level=logging.DEBUG,
            timer=t,
            remaining_s=remaining,
            poll_seq=self._polls,
        )

        if self._last_text is None:
            log_event(
                phase="TIMER",
                component="timer",
                action="TEXT_CHANGED",
                status="ok",
                message=f"Initial timer text={t!r}",
                timer=t,
                remaining_s=remaining,
            )
            self._last_text = t
            self._last_remaining = remaining
            self._last_heartbeat_mono = time.monotonic()
            return

        if t != self._last_text:
            if self._freeze_alerted:
                log_event(
                    phase="TIMER",
                    component="timer",
                    action="FREEZE_RECOVERED",
                    status="ok",
                    message=f"Timer recovered old={self._last_text!r} new={t!r}",
                    timer=t,
                    previous_timer=self._last_text,
                    remaining_s=remaining,
                )
                bump_summary(current_job_id(), "recovery_count", 1)
                self._freeze_alerted = False
            log_event(
                phase="TIMER",
                component="timer",
                action="TEXT_CHANGED",
                status="ok",
                message=f"Timer changed to {t!r}",
                timer=t,
                previous_timer=self._last_text,
                remaining_s=remaining,
            )
            if remaining is not None and remaining in _THRESHOLDS:
                log_event(
                    phase="TIMER",
                    component="timer",
                    action="THRESHOLD",
                    status="ok",
                    message=f"Threshold crossed remaining={remaining}",
                    timer=t,
                    remaining_s=remaining,
                )
            self._last_text = t
            self._last_remaining = remaining
            self._unchanged = 0
            self._last_heartbeat_mono = time.monotonic()
        else:
            self._unchanged += 1
            if (
                self._unchanged >= self._freeze_threshold_polls
                and not self._freeze_alerted
                and t
            ):
                self._freeze_alerted = True
                log_event(
                    phase="TIMER",
                    component="timer",
                    action="FREEZE_DETECTED",
                    status="warn",
                    message=f"Timer text unchanged for ~{self._unchanged} polls",
                    level=logging.WARNING,
                    timer=t,
                    remaining_s=remaining,
                    unchanged_polls=self._unchanged,
                )
            now = time.monotonic()
            if now - self._last_heartbeat_mono >= self._heartbeat:
                log_event(
                    phase="TIMER",
                    component="timer",
                    action="HEARTBEAT",
                    status="ok",
                    message=f"Timer heartbeat text={t!r}",
                    timer=t,
                    remaining_s=remaining,
                    polls=self._polls,
                    unchanged_polls=self._unchanged,
                )
                self._last_heartbeat_mono = now

        if is_trigger:
            mode = "EXPIRES_IN" if "Expires in" in t else "STARTS_IN"
            log_event(
                phase="TIMER",
                component="timer",
                action="TRIGGER",
                status="ok",
                message=f"Execution trigger matched mode={mode}",
                timer=t,
                remaining_s=remaining,
                mode=mode,
                poll_seq=self._polls,
            )

    def on_poll_error(self, err: BaseException, *, stale: bool = False) -> None:
        log_event(
            phase="TIMER",
            component="timer",
            action="POLL_ERROR" if not stale else "STALE_ELEMENT",
            status="warn",
            message=str(err),
            level=logging.WARNING,
            recovery="continue_polling",
        )


def _parse_remaining(text: str) -> int | None:
    if not text:
        return None
    m = re.search(r"(\d+)(?::(\d+))?(?::(\d+))?", text)
    if not m:
        return None
    try:
        parts = [int(x) for x in m.groups() if x is not None]
    except ValueError:
        return None
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None
