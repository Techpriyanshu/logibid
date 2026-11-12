"""
Bid Logging Service - Industry Standard Logging with Job Tracking

Architecture:
- Single log file: All_logs.log (appends to same file)
- Job boundaries: Clear headers for each job
- Daily rotation: Date-suffixed files (All_logs_2026-08-22.log)
- Auto ZIP: Daily archives for old logs
- Cleanup: Delete logs older than retention period (default 30 days)
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextvars import ContextVar

# Project Root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOGS_DIR = _PROJECT_ROOT / "logs"
_ALL_LOGS_ROOT = _LOGS_DIR / "All_logs"
_ALL_LOGS_FILE = _ALL_LOGS_ROOT / "All_logs.log"
_ALL_LOGS_ARCHIVE_DIR = _ALL_LOGS_ROOT / "archives"

# Context variables for bid tracking
_ctx_bid_id: ContextVar[str] = ContextVar("bid_id", default="")
_ctx_job_id: ContextVar[str] = ContextVar("job_id", default="")
_ctx_depot: ContextVar[str] = ContextVar("depot", default="")
_ctx_quantity: ContextVar[float] = ContextVar("quantity", default=0.0)
_ctx_destination: ContextVar[str] = ContextVar("destination", default="")

# Lock for thread-safe file operations
_log_lock = threading.RLock()

# Cached settings
_settings_cache: Dict[str, Any] | None = None


class ContextToken:
    """Thread-local context token."""
    def __init__(self, name: str, default: Any = None):
        self._name = name
        self._default = default
        self._local = threading.local()
    
    def get(self) -> Any:
        return getattr(self._local, 'value', self._default)
    
    def set(self, value: Any) -> None:
        self._local.value = value


def _get_bid_id() -> str:
    """Get current bid_id from context or generate one."""
    bid_id = _ctx_bid_id.get()
    if not bid_id:
        # Generate a short bid_id based on timestamp
        return f"bid_{int(time.time() * 1000) % 1000000:06d}"
    return bid_id


def get_bid_id() -> str:
    """Get current bid_id from context or generate one."""
    return _get_bid_id()



def _get_job_id() -> str:
    """Get current job_id from context."""
    return _ctx_job_id.get() or "nojob"


def _get_depot() -> str:
    """Get current depot from context."""
    return _ctx_depot.get() or "UNKNOWN"


def _get_quantity() -> float:
    """Get current quantity from context."""
    return _ctx_quantity.get() or 0.0


def _get_destination() -> str:
    """Get current destination from context."""
    return _ctx_destination.get() or ""


def _safe_filename(s: str) -> str:
    """Sanitize string for use in filenames."""
    return re.sub(r'[^\w\-]', '_', str(s))[:64] or "unknown"


def _get_bid_log_file(job_id: str, depot: str, quantity: float, destination: str) -> Path:
    """Get log file path for a specific bid."""
    safe_job = _safe_filename(job_id)
    safe_depot = _safe_filename(depot)
    safe_dest = _safe_filename(destination or "no_dest")
    qty_str = f"{quantity:.2f}".replace(".", "_")
    filename = f"{safe_job}_{safe_depot}_{qty_str}_{safe_dest}.log"
    return _ALL_LOGS_ROOT / filename


def _get_today_log_file() -> Path:
    """Get today's log file path with date suffix."""
    today = datetime.now().strftime("%Y-%m-%d")
    return _ALL_LOGS_ROOT / f"All_logs_{today}.log"


def _format_log_line(
    level: str,
    job_id: str,
    bid_id: str,
    depot: str,
    quantity: float,
    destination: str,
    phase: str,
    component: str,
    action: str,
    status: str,
    message: str,
    timestamp: str | None = None,
    **meta: Any
) -> str:
    """Format a log line with job headers and bid context for industry standard logging."""
    ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    
    # Create job header if this is a job boundary
    if action in ("JOB_START", "BID_START"):
        job_header = (
            f"[{ts}] === JOB: {job_id} | BID: {bid_id} | DEPOT: {depot} | "
            f"QTY: {quantity} | DEST: {destination} | START ==="
        )
        return f"{job_header}\n[{ts}] [{level}] {phase} {component}.{action} {status}: {message}"
    
    if action in ("JOB_END", "BID_END"):
        job_footer = (
            f"[{ts}] === JOB: {job_id} | BID: {bid_id} | DEPOT: {depot} | "
            f"QTY: {quantity} | DEST: {destination} | END | STATUS: {status} ==="
        )
        return f"{job_footer}\n[{ts}] [{level}] {phase} {component}.{action} {status}: {message}"
    
    # Industry standard format with structured context for traceability and gap analysis
    # Format: timestamp | level | phase | component.action | status | job_id | bid_id | depot | quantity | destination | message | meta
    meta_str = ""
    if meta:
        meta_parts = []
        for k, v in meta.items():
            if v is not None:
                meta_parts.append(f"{k}={v}")
        if meta_parts:
            meta_str = " | " + " ".join(meta_parts)
    
    return (
        f"[{ts}] [{level}] {phase} {component}.{action} {status} | "
        f"job={job_id} bid={bid_id} depot={depot} qty={quantity} dest={destination} | {message}{meta_str}"
    )


class BidLogger:
    """Logger for bid-specific events with job tracking."""
    
    def __init__(self):
        self._logger = logging.getLogger("bid_logger")
        self._logger.setLevel(logging.DEBUG)
        
        # Ensure log directories exist
        _ALL_LOGS_ROOT.mkdir(parents=True, exist_ok=True)
        _ALL_LOGS_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        
        # Single file handler
        self._setup_file_handler()
        
        # Per-bid logger (in-memory, writes to individual bid files)
        self._bid_loggers: Dict[str, logging.Logger] = {}
        self._bid_log_lock = threading.RLock()
    
    def _setup_file_handler(self) -> None:
        """Setup the file handler for the single log file with immediate flush."""
        try:
            # Remove existing handlers
            for h in list(self._logger.handlers):
                self._logger.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass
            
            # Create file handler with immediate flush
            fh = logging.FileHandler(_ALL_LOGS_FILE, encoding="utf-8", mode="a")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter("%(message)s"))
            
            # Set unbuffered mode
            fh.stream = open(_ALL_LOGS_FILE, mode="a", encoding="utf-8", buffering=1)
            
            self._logger.addHandler(fh)
        except Exception as e:
            print(f"Failed to setup log file handler: {e}")
    
    def log_bid_start(
        self,
        job_id: str,
        bid_id: str | None = None,
        depot: str | None = None,
        quantity: float | None = None,
        destination: str | None = None,
        **meta: Any
    ) -> str:
        """Log bid start with full context."""
        bid_id = bid_id or _get_bid_id()
        depot = depot or _get_depot()
        quantity = quantity or _get_quantity()
        destination = destination or _get_destination()
        
        with _log_lock:
            # Set context
            _ctx_bid_id.set(bid_id)
            _ctx_job_id.set(job_id)
            _ctx_depot.set(depot)
            _ctx_quantity.set(quantity)
            _ctx_destination.set(destination)
            
            # Log the start
            line = _format_log_line(
                level="INFO",
                job_id=job_id,
                bid_id=bid_id,
                depot=depot,
                quantity=quantity,
                destination=destination,
                phase="BID",
                component="bid",
                action="BID_START",
                status="ok",
                message=f"Bid started | depots={depot} qty={quantity} dest={destination}",
            )
            self._logger.info(line)
            
            # Also write to per-bid log file
            self._write_bid_log_file(job_id, depot, quantity, destination, line)
        
        return bid_id
    
    def _write_bid_log_file(
        self, job_id: str, depot: str, quantity: float, destination: str, message: str
    ) -> None:
        """Write to per-bid log file with immediate flush."""
        bid_log_path = _get_bid_log_file(job_id, depot, quantity, destination)
        try:
            # Ensure log directory exists
            bid_log_path.parent.mkdir(parents=True, exist_ok=True)
            
            with self._bid_log_lock:
                if bid_log_path not in self._bid_loggers:
                    # Setup per-bid logger
                    logger_name = f"bid_logger.{_safe_filename(job_id)}.{_safe_filename(depot)}"
                    logger = logging.getLogger(logger_name)
                    logger.setLevel(logging.DEBUG)
                    logger.propagate = False
                    
                    for h in list(logger.handlers):
                        logger.removeHandler(h)
                        try:
                            h.close()
                        except Exception:
                            pass
                    
                    fh = logging.FileHandler(bid_log_path, encoding="utf-8", mode="a")
                    fh.setLevel(logging.DEBUG)
                    fh.setFormatter(logging.Formatter("%(message)s"))
                    logger.addHandler(fh)
                    self._bid_loggers[bid_log_path] = logger
                
                # Log with immediate flush
                logger = self._bid_loggers[bid_log_path]
                logger.info(message)
                
                # Force flush to disk
                for h in logger.handlers:
                    try:
                        h.flush()
                        os.fsync(h.stream.fileno())
                    except Exception:
                        pass
        except Exception as e:
            # Silently fail - per-bid logs are optional
            pass
    
    def log_bid_event(
        self,
        job_id: str | None = None,
        bid_id: str | None = None,
        phase: str | None = None,
        component: str = "bid",
        action: str = "INFO",
        status: str = "ok",
        message: str = "",
        level: int = logging.INFO,
        depot: str | None = None,
        quantity: float | None = None,
        destination: str | None = None,
        **meta: Any
    ) -> None:
        """Log a bid event with immediate flush."""
        job_id = job_id or _get_job_id()
        bid_id = bid_id or _get_bid_id()
        phase = phase or "BID"
        
        # Get current context values if not provided
        depot = depot or _get_depot()
        quantity = quantity or _get_quantity()
        destination = destination or _get_destination()
        
        with _log_lock:
            line = _format_log_line(
                level=logging.getLevelName(level),
                job_id=job_id,
                bid_id=bid_id,
                depot=depot,
                quantity=quantity,
                destination=destination,
                phase=phase,
                component=component,
                action=action,
                status=status,
                message=message,
            )
            self._logger.log(level, line)
            
            # Force flush to disk
            for h in self._logger.handlers:
                try:
                    h.flush()
                    os.fsync(h.stream.fileno())
                except Exception:
                    pass
            
            # Write to per-bid log file
            self._write_bid_log_file(job_id, depot, quantity, destination, line)
    
    def log_bid_end(
        self,
        job_id: str | None = None,
        bid_id: str | None = None,
        status: str = "completed",
        duration_ms: float | None = None,
        depot: str | None = None,
        quantity: float | None = None,
        destination: str | None = None,
        **meta: Any
    ) -> None:
        """Log bid end with summary, checking database for orphaned/stopped status."""
        job_id = job_id or _get_job_id()
        bid_id = bid_id or _get_bid_id()
        
        depot = depot or _get_depot()
        quantity = quantity or _get_quantity()
        destination = destination or _get_destination()
        
        # Check database for actual status (orphaned/stopped)
        try:
            from .live_bids_store import get_user_control
            
            # Determine the actual status from user_control
            user_control = get_user_control(
                job_id=job_id,
                depot=depot,
                quantity=quantity,
                destination=destination,
            )
            
            # Map user_control to proper status
            if user_control == "stopped":
                status = "stopped"
            # Note: "orphaned" is set as a status in the database, not user_control
            # It would be checked via the status field if needed
            
        except Exception:
            pass  # Use provided status if database check fails
        
        summary_parts = [
            f"job={job_id}",
            f"bid={bid_id}",
            f"depot={depot}",
            f"qty={quantity}",
            f"dest={destination}",
        ]
        if duration_ms is not None:
            summary_parts.append(f"duration_ms={duration_ms:.2f}")
        
        summary = " | ".join(summary_parts)
        
        with _log_lock:
            line = _format_log_line(
                level="INFO",
                job_id=job_id,
                bid_id=bid_id,
                depot=depot,
                quantity=quantity,
                destination=destination,
                phase="BID",
                component="bid",
                action="BID_END",
                status=status,
                message=f"Bid completed | {summary}",
            )
            self._logger.info(line)
            
            # Write to per-bid log file
            self._write_bid_log_file(job_id, depot, quantity, destination, line)
    
    def log_bid_error(
        self,
        job_id: str | None = None,
        bid_id: str | None = None,
        phase: str | None = None,
        component: str = "bid",
        action: str = "ERROR",
        message: str = "",
        exception: Exception | None = None,
        depot: str | None = None,
        quantity: float | None = None,
        destination: str | None = None,
        **meta: Any
    ) -> None:
        """Log a bid error with exception details, checking database for orphaned/stopped status."""
        job_id = job_id or _get_job_id()
        bid_id = bid_id or _get_bid_id()
        phase = phase or "ERROR"
        
        depot = depot or _get_depot()
        quantity = quantity or _get_quantity()
        destination = destination or _get_destination()
        
        # Check database for actual status (orphaned/stopped)
        try:
            from .live_bids_store import get_user_control
            
            # Determine the actual status from user_control
            user_control = get_user_control(
                job_id=job_id,
                depot=depot,
                quantity=quantity,
                destination=destination,
            )
            
            # Map user_control to proper status for error logging
            if user_control == "stopped":
                status = "stopped"
            else:
                status = "error"
        except Exception:
            status = "error"  # Default to error
        
        full_message = message
        if exception:
            full_message = f"{message} | exception={type(exception).__name__}: {exception}"
        
        self.log_bid_event(
            job_id=job_id,
            bid_id=bid_id,
            phase=phase,
            component=component,
            action=action,
            status=status,
            message=full_message,
            level=logging.ERROR,
            **meta
        )
    
    def archive_old_logs(self, days: int = 1) -> List[str]:
        """Archive logs older than specified days into ZIP files."""
        archived = []
        cutoff = datetime.now() - timedelta(days=days)
        
        try:
            # Find all date-suffixed log files
            for log_file in _ALL_LOGS_ROOT.glob("All_logs_*.log"):
                if log_file.name == "All_logs.log":
                    continue
                
                # Extract date from filename (All_logs_2026-08-22.log)
                try:
                    date_str = log_file.stem.split("_")[-1]  # 2026-08-22
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                except (ValueError, IndexError):
                    continue
                
                # Archive if older than cutoff
                if file_date < cutoff:
                    zip_path = _ALL_LOGS_ARCHIVE_DIR / f"{date_str}.zip"
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                        zf.write(log_file, log_file.name)
                    log_file.unlink()  # Remove original after archiving
                    archived.append(str(zip_path))
        except Exception as e:
            print(f"Failed to archive old logs: {e}")
        
        return archived
    
    def cleanup_old_archives(self, days: int = 30) -> List[str]:
        """Delete archives older than specified days."""
        deleted = []
        cutoff = datetime.now() - timedelta(days=days)
        
        try:
            for zip_file in _ALL_LOGS_ARCHIVE_DIR.glob("*.zip"):
                try:
                    # Get file modification time
                    mtime = datetime.fromtimestamp(zip_file.stat().st_mtime)
                    if mtime < cutoff:
                        zip_file.unlink()
                        deleted.append(str(zip_file))
                except Exception:
                    continue
        except Exception as e:
            print(f"Failed to cleanup old archives: {e}")
        
        return deleted


# Global logger instance
_bid_logger = BidLogger()


def get_bid_logger() -> BidLogger:
    """Get the global bid logger instance."""
    return _bid_logger


# Convenience functions
def log_bid_start(
    job_id: str,
    bid_id: str | None = None,
    depot: str | None = None,
    quantity: float | None = None,
    destination: str | None = None,
    **meta: Any
) -> str:
    """Convenience function to log bid start."""
    return _bid_logger.log_bid_start(
        job_id=job_id,
        bid_id=bid_id,
        depot=depot,
        quantity=quantity,
        destination=destination,
        **meta
    )


def log_bid_event(
    job_id: str | None = None,
    bid_id: str | None = None,
    phase: str | None = None,
    component: str = "bid",
    action: str = "INFO",
    status: str = "ok",
    message: str = "",
    level: int = logging.INFO,
    depot: str | None = None,
    quantity: float | None = None,
    destination: str | None = None,
    **meta: Any
) -> None:
    """Convenience function to log bid event."""
    _bid_logger.log_bid_event(
        job_id=job_id,
        bid_id=bid_id,
        phase=phase,
        component=component,
        action=action,
        status=status,
        message=message,
        level=level,
        depot=depot,
        quantity=quantity,
        destination=destination,
        **meta
    )


def log_bid_end(
    job_id: str | None = None,
    bid_id: str | None = None,
    status: str = "completed",
    duration_ms: float | None = None,
    depot: str | None = None,
    quantity: float | None = None,
    destination: str | None = None,
    **meta: Any
) -> None:
    """Convenience function to log bid end."""
    _bid_logger.log_bid_end(
        job_id=job_id,
        bid_id=bid_id,
        status=status,
        duration_ms=duration_ms,
        depot=depot,
        quantity=quantity,
        destination=destination,
        **meta
    )


def log_bid_error(
    job_id: str | None = None,
    bid_id: str | None = None,
    phase: str | None = None,
    component: str = "bid",
    action: str = "ERROR",
    message: str = "",
    exception: Exception | None = None,
    depot: str | None = None,
    quantity: float | None = None,
    destination: str | None = None,
    **meta: Any
) -> None:
    """Convenience function to log bid error."""
    _bid_logger.log_bid_error(
        job_id=job_id,
        bid_id=bid_id,
        phase=phase,
        component=component,
        action=action,
        message=message,
        exception=exception,
        depot=depot,
        quantity=quantity,
        destination=destination,
        **meta
    )


def archive_logs(days: int = 1) -> List[str]:
    """Archive logs older than specified days."""
    return _bid_logger.archive_old_logs(days=days)


def cleanup_logs(days: int = 30) -> List[str]:
    """Delete archives older than specified days."""
    return _bid_logger.cleanup_old_archives(days=days)
