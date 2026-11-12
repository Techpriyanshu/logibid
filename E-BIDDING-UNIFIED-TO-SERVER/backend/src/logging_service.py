"""
Logging Service — Centralized multi-file routing (logging-only; no bidding side effects).

Folders under logs/:
  All_logs/          — single file: All_logs.log (all generic logs)
  All_logs/{job_id}/ — per-job execution logs (execution_phase)

Handlers fan out from a single logger.info/warning/error call.

Industry Standard Logging:
- All logs include: timestamp, level, job_id, bid_id, depot, phase, component, action, status, message
- Structured context for traceability and gap analysis
- Timeline tracking for process improvement
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------
# Project Root
# ---------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOGS_DIR = _PROJECT_ROOT / "logs"
_APP_CONFIG_FILE = _PROJECT_ROOT / "config" / "application.yaml"

# ---------------------------------------------------
# Logging Format
# ---------------------------------------------------

_DEFAULT_FORMAT = "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
_DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_ROOT_LOGGER_NAME = "backend_automation"

# Track created loggers
_loggers: dict[str, logging.Logger] = {}

# Track log paths (execution + optional general)
_logger_paths: dict[str, Path] = {}
_logger_general_paths: dict[str, Path] = {}

# Cached logging config from application.yaml
_logging_settings_cache: dict[str, Any] | None = None

# Thread-local execution window (valid combination found → post-exec)
_phase_local = threading.local()

# Substrings that identify mandatory execution-phase log lines (UNCHANGED behaviour)
_EXECUTION_MARKERS: tuple[str, ...] = (
    "Valid combination found",
    "[EXEC_PHASE]",
    "[TIMER]",
    "Current timer:",
    "[EXEC]",
    "EXECUTE_END",
    "total_execution_ms",
    "[POST_EXEC]",
    "POST_EXEC:",
    "Session maintained",
    "[REC][PLAN]",
    "[REC][EXEC]",
    "[REC][CLEANUP]",
    "[SYNC]",
    "Save button clicked",
    "Entered bid amount:",
    "EXEC:",
    "confirmation dialog",
    "Execution dialog sequence completed",
    "SHUBH_MODE_TRIGGER",
    "SEARCH_CLICK_BEFORE_EXEC",
    "DIRECT_EXECUTION_START",
    "FLOW: Fill",
    "[API]",
)

# Category routing markers (message content only — no call-site changes required)
_MONITORING_MARKERS: tuple[str, ...] = (
    "[LOOP]",
    "Monitoring cycle",
    "Monitoring bids",
    "Search refresh",
    "Clicking search / live monitor",
    "No valid combination",
    "Valid combination found",
    "Results loaded",
    "Searching available bids",
    "Search button clicked",
    "Search clicked",
    "Clicking Search",
    "NO_ROWS",
    "[PLAN]",
    "Prepared bids",
    "Processing bids",
    "parsed",
    "Parsed",
    "rows=",
    "live monitor",
)

_TIMER_MARKERS: tuple[str, ...] = (
    "[TIMER]",
    "Current timer:",
    "SHUBH_MODE_TRIGGER",
    "poll_start timer_id",
    "timer_text=",
    "not matching execution condition",
)

_RANK_MARKERS: tuple[str, ...] = (
    "[RANK]",
    "waiting_rank",
    "Waiting Rank",
    "Bid Rank",
    "Current Rank",
    "publish_waiting_rank",
    "waiting for rank",
)

_ROTATION_MARKERS: tuple[str, ...] = (
    "[ROTATION]",
)

_START_IN_MARKERS: tuple[str, ...] = (
    "[START_IN]",
)


# ---------------------------------------------------
# Execution phase context (minimal engine hooks — unchanged API)
# ---------------------------------------------------

def enter_execution_phase() -> None:
    """Mark current thread as inside valid-bid → post-exec logging window."""
    _phase_local.active = True


def exit_execution_phase() -> None:
    """Leave execution-phase window (e.g. resume live monitor loop)."""
    _phase_local.active = False


def is_execution_phase_active() -> bool:
    return bool(getattr(_phase_local, "active", False))


def _message_is_execution_phase(message: str) -> bool:
    return any(marker in message for marker in _EXECUTION_MARKERS)


def _message_has_any(message: str, markers: tuple[str, ...]) -> bool:
    return any(marker in message for marker in markers)


class ExecutionPhaseFilter(logging.Filter):
    """Allow only execution-window log records into the execution-phase file."""

    def filter(self, record: logging.LogRecord) -> bool:
        if is_execution_phase_active():
            return True
        return _message_is_execution_phase(record.getMessage())


class GeneralLogFilter(logging.Filter):
    """
    Legacy filter: non-execution only.

    Kept for compatibility. New general handlers intentionally do NOT use this
    filter so general/ captures the full lifecycle.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if is_execution_phase_active():
            return False
        return not _message_is_execution_phase(record.getMessage())


class MarkerFilter(logging.Filter):
    """Allow records whose message contains any of the given markers."""

    def __init__(self, markers: tuple[str, ...], name: str = "") -> None:
        super().__init__(name)
        self._markers = markers

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return _message_has_any(record.getMessage(), self._markers)
        except Exception:
            return False


class LevelAtLeastFilter(logging.Filter):
    """Allow records at or above a logging level (e.g. WARNING for errors/)."""

    def __init__(self, min_level: int = logging.WARNING, name: str = "") -> None:
        super().__init__(name)
        self._min_level = min_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self._min_level


# ---------------------------------------------------
# Config
# ---------------------------------------------------

def _default_logging_settings() -> dict[str, Any]:
    return {
        "execution_phase_file_enabled": True,
        "execution_phase_dir": "logs/execution_phase",
        "general_log_file_enabled": True,
        "general_log_dir": "logs/general",
        "general_console_enabled": True,
        "monitoring_log_enabled": True,
        "monitoring_log_dir": "logs/monitoring",
        "timer_log_enabled": True,
        "timer_log_dir": "logs/timer",
        "rank_log_enabled": True,
        "rank_log_dir": "logs/rank",
        "rotation_log_enabled": True,
        "rotation_log_dir": "logs/rotation",
        "start_in_log_file_enabled": True,
        "start_in_log_dir": "logs/start_in",
        "errors_log_enabled": True,
        "errors_log_dir": "logs/errors",
    }


def get_logging_settings() -> dict[str, Any]:
    global _logging_settings_cache
    if _logging_settings_cache is not None:
        return _logging_settings_cache

    settings = _default_logging_settings()
    try:
        import yaml

        if _APP_CONFIG_FILE.exists():
            with open(_APP_CONFIG_FILE, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            section = raw.get("logging")
            if isinstance(section, dict):
                settings.update(section)
    except Exception:
        pass

    _logging_settings_cache = settings
    return settings


def _resolve_log_dir(relative: str) -> Path:
    p = Path(relative)
    if p.is_absolute():
        out = p
    else:
        out = _PROJECT_ROOT / p
    out.mkdir(parents=True, exist_ok=True)
    return out


# ---------------------------------------------------
# Ensure logs directory
# ---------------------------------------------------

def _ensure_logs_dir() -> Path:
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return _LOGS_DIR


# ---------------------------------------------------
# Generate log filename (pid-scoped for multiprocess safety)
# ---------------------------------------------------

def _make_log_filename(depot_name: str | None) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = depot_name.lower() if depot_name else "app"
    return f"{prefix}_pid{os.getpid()}_{timestamp}.log"


def _is_special_logger(logger_key: str) -> bool:
    """Check if this is a special logger that should use single file routing."""
    return logger_key == "backend_api"


def _close_and_clear_handlers(logger: logging.Logger) -> None:
    for h in list(logger.handlers):
        try:
            logger.removeHandler(h)
            h.close()
        except Exception:
            pass


def _add_file_handler(
    logger: logging.Logger,
    *,
    directory: Path,
    filename: str,
    level: int,
    formatter: logging.Formatter,
    filt: logging.Filter | None = None,
) -> Path:
    path = directory / filename
    # Ensure directory exists
    directory.mkdir(parents=True, exist_ok=True)
    # Create file handler with unbuffered mode for immediate writes
    handler = logging.FileHandler(path, encoding="utf-8", delay=False, mode="a")
    handler.setLevel(level)
    handler.setFormatter(formatter)
    if filt is not None:
        handler.addFilter(filt)
    logger.addHandler(handler)
    return path


def _attach_handlers(
    logger: logging.Logger,
    logger_key: str,
    depot_name: str | None,
    level: int,
    console: bool,
) -> None:
    settings = get_logging_settings()
    formatter = logging.Formatter(_DEFAULT_FORMAT, datefmt=_DEFAULT_DATE_FORMAT)
    filename = _make_log_filename(depot_name)
    
    # Special logger routing: backend_api goes to single All_logs.log file
    if _is_special_logger(logger_key):
        # Special logger: only write to single All_logs.log file
        gen_dir = _resolve_log_dir(str(settings.get("execution_phase_dir", "logs/All_logs")))
        gen_path = _add_file_handler(
            logger,
            directory=gen_dir,
            filename="All_logs.log",
            level=level,
            formatter=formatter,
            filt=None,
        )
        _logger_general_paths[logger_key.upper()] = gen_path
        return

    # Execution phase (for per-bid logs in All_logs/{job_id}/)
    if bool(settings.get("execution_phase_file_enabled", True)):
        exec_dir = _resolve_log_dir(
            str(settings.get("execution_phase_dir", "logs/execution_phase"))
        )
        exec_path = _add_file_handler(
            logger,
            directory=exec_dir,
            filename=filename,
            level=level,
            formatter=formatter,
            filt=ExecutionPhaseFilter(),
        )
        _logger_paths[logger_key.upper()] = exec_path

    # Single generic log file for all other logs
    if bool(settings.get("general_log_file_enabled", False)):
        gen_dir = _resolve_log_dir(str(settings.get("general_log_dir", "logs/general")))
        gen_path = _add_file_handler(
            logger,
            directory=gen_dir,
            filename="All_logs.log",
            level=level,
            formatter=formatter,
            filt=None,
        )
        _logger_general_paths[logger_key.upper()] = gen_path

    # Category files (only if explicitly enabled)
    if bool(settings.get("monitoring_log_enabled", False)):
        mon_dir = _resolve_log_dir(
            str(settings.get("monitoring_log_dir", "logs/monitoring"))
        )
        _add_file_handler(
            logger,
            directory=mon_dir,
            filename=filename,
            level=level,
            formatter=formatter,
            filt=MarkerFilter(_MONITORING_MARKERS, name="monitoring"),
        )

    if bool(settings.get("timer_log_enabled", False)):
        tim_dir = _resolve_log_dir(str(settings.get("timer_log_dir", "logs/timer")))
        _add_file_handler(
            logger,
            directory=tim_dir,
            filename=filename,
            level=level,
            formatter=formatter,
            filt=MarkerFilter(_TIMER_MARKERS, name="timer"),
        )

    if bool(settings.get("rank_log_enabled", False)):
        rank_dir = _resolve_log_dir(str(settings.get("rank_log_dir", "logs/rank")))
        _add_file_handler(
            logger,
            directory=rank_dir,
            filename=filename,
            level=level,
            formatter=formatter,
            filt=MarkerFilter(_RANK_MARKERS, name="rank"),
        )

    if bool(settings.get("rotation_log_enabled", False)):
        rot_dir = _resolve_log_dir(
            str(settings.get("rotation_log_dir", "logs/rotation"))
        )
        _add_file_handler(
            logger,
            directory=rot_dir,
            filename=filename,
            level=level,
            formatter=formatter,
            filt=MarkerFilter(_ROTATION_MARKERS, name="rotation"),
        )

    if bool(settings.get("start_in_log_file_enabled", False)):
        si_dir = _resolve_log_dir(
            str(settings.get("start_in_log_dir", "logs/start_in"))
        )
        _add_file_handler(
            logger,
            directory=si_dir,
            filename=filename,
            level=level,
            formatter=formatter,
            filt=MarkerFilter(_START_IN_MARKERS, name="start_in"),
        )

    if bool(settings.get("errors_log_enabled", False)):
        err_dir = _resolve_log_dir(str(settings.get("errors_log_dir", "logs/errors")))
        _add_file_handler(
            logger,
            directory=err_dir,
            filename=filename,
            level=logging.WARNING,
            formatter=formatter,
            filt=LevelAtLeastFilter(logging.WARNING, name="errors"),
        )

    show_console = console
    if not bool(settings.get("general_console_enabled", False)):
        show_console = False

    if show_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)


# ---------------------------------------------------
# Main Logger Factory
# ---------------------------------------------------

def get_logger(
    depot_name: str | None = None,
    level: int = logging.INFO,
    console: bool = True,
) -> logging.Logger:

    logger_key = (depot_name or "app").lower()

    if logger_key in _loggers:
        return _loggers[logger_key]

    logger_name = f"{_ROOT_LOGGER_NAME}.{logger_key}"
    logger = logging.getLogger(logger_name)

    logger.setLevel(level)
    logger.propagate = False

    _attach_handlers(logger, logger_key, depot_name, level, console)

    _loggers[logger_key] = logger

    return logger


def configure_named_logger(
    logger: logging.Logger,
    name: str,
    level: int = logging.INFO,
    console: bool = True,
) -> Path | None:
    """
    Attach multi-file handlers to an existing logger — used by selenium_worker.
    Returns primary log file path when available.
    """
    logger.setLevel(level)
    logger.propagate = False
    _close_and_clear_handlers(logger)

    key = name.lower()
    # Drop stale path cache entries for this key so filenames refresh per worker
    _logger_paths.pop(key.upper(), None)
    _logger_general_paths.pop(key.upper(), None)

    _attach_handlers(logger, key, name, level, console)

    return _logger_paths.get(key.upper()) or _logger_general_paths.get(key.upper())


# ---------------------------------------------------
# Get Log File Path
# ---------------------------------------------------

def get_log_path(depot_name: str | None = None) -> Path:

    depot_key = (depot_name or "app").upper()

    if depot_key in _logger_paths:
        return _logger_paths[depot_key]

    logs_dir = _ensure_logs_dir()
    return logs_dir / _make_log_filename(depot_name)


def get_general_log_path(depot_name: str | None = None) -> Path | None:
    depot_key = (depot_name or "app").upper()
    return _logger_general_paths.get(depot_key)
