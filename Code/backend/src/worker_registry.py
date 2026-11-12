"""
Worker PID Registry — tracks running worker processes for force-kill on bid stop.

File-based registry that maps leg_id → worker PID.
Uses JSON file so both parent (FastAPI) and child (worker subprocess) can read/write.

Used by:
  - selenium_worker.py: register_worker() on start, unregister_worker() on exit
  - backend_server.py: kill_worker_for_leg() when bid is stopped from GUI
"""

from __future__ import annotations

import json
import threading
import logging
from pathlib import Path
from typing import Dict, Optional

from .logging_service import get_logger

logger = get_logger("worker_registry")

_LOCK = threading.Lock()
_REGISTRY_FILE = Path(__file__).resolve().parent.parent / "data" / "worker_registry.json"


def _read_registry() -> Dict[str, Dict]:
    """Read registry from file."""
    try:
        if _REGISTRY_FILE.exists():
            data = json.loads(_REGISTRY_FILE.read_text())
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _write_registry(data: Dict[str, Dict]) -> None:
    """Write registry to file."""
    try:
        _REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _REGISTRY_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error("[REGISTRY] Failed to write registry file: %s", e)


def register_worker(leg_id: str, pid: int, job_id: str, depot: str) -> None:
    """Register a worker process for a bid leg."""
    with _LOCK:
        registry = _read_registry()
        registry[leg_id] = {"pid": pid, "job_id": job_id, "depot": depot}
        _write_registry(registry)
    logger.info(
        "[REGISTRY] Registered worker: leg_id=%s pid=%d job_id=%s depot=%s",
        leg_id, pid, job_id, depot,
    )


def unregister_worker(leg_id: str) -> None:
    """Unregister a worker process when it exits."""
    with _LOCK:
        registry = _read_registry()
        entry = registry.pop(leg_id, None)
        _write_registry(registry)
    if entry:
        logger.info(
            "[REGISTRY] Unregistered worker: leg_id=%s pid=%d job_id=%s depot=%s",
            leg_id, entry["pid"], entry["job_id"], entry["depot"],
        )


def get_worker_pid(leg_id: str) -> Optional[int]:
    """Get the PID for a running worker by leg_id."""
    with _LOCK:
        registry = _read_registry()
    entry = registry.get(leg_id)
    return entry["pid"] if entry else None


def get_workers_for_job(job_id: str) -> Dict[str, int]:
    """Get all running worker PIDs for a job. Returns {leg_id: pid}."""
    with _LOCK:
        registry = _read_registry()
    return {
        lid: entry["pid"]
        for lid, entry in registry.items()
        if entry.get("job_id") == job_id
    }


def _kill_browser_children(pid: int, leg_id: str) -> int:
    """
    Kill only the browser/driver children of a worker PID.

    ProcessPoolExecutor owns the worker's IPC pipe. Sending any signal to the
    worker PID itself (SIGTERM/SIGKILL/.kill()) closes that pipe from the
    child side and causes BrokenProcessPool / WinError 233 on the parent's
    next pool.submit() or future.result(). Only ever touch the worker's
    children (Chrome/chromedriver), never the worker process itself.
    """
    try:
        import psutil
    except ImportError:
        logger.warning("[REGISTRY] psutil not available — cannot clean up browser children for pid=%d", pid)
        return 0

    killed = 0
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
    except psutil.NoSuchProcess:
        logger.info("[REGISTRY] Worker pid=%d already dead for leg_id=%s", pid, leg_id)
        return 0

    logger.info("[REGISTRY] Worker pid=%d has %d children", pid, len(children))
    for child in children:
        try:
            logger.info("[REGISTRY] Killing child process pid=%d name=%s for leg_id=%s", child.pid, child.name(), leg_id)
            child.kill()
            killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Also kill any orphaned chromedriver/chrome processes spawned by this worker
    # On macOS, Chrome may not be a direct child of the worker
    try:
        child_pids = {c.pid for c in children}
        for proc in psutil.process_iter(['pid', 'ppid', 'name', 'cmdline']):
            try:
                pinfo = proc.info
                pname = (pinfo.get('name') or '').lower()
                cmdline_str = ' '.join(pinfo.get('cmdline') or [])
                if pinfo.get('ppid') == pid or (
                    ('chromedriver' in pname or 'chrome' in pname) and
                    'scoped_dir' in cmdline_str and
                    pinfo['pid'] not in child_pids
                ):
                    logger.info("[REGISTRY] Killing orphaned process pid=%d name=%s for leg_id=%s",
                                pinfo['pid'], pname, leg_id)
                    proc.kill()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception as e:
        logger.debug("[REGISTRY] Orphan cleanup error: %s", e)

    logger.info("[REGISTRY] Preserved executor worker pid=%d; killed %d browser children for leg_id=%s", pid, killed, leg_id)
    return killed


def kill_worker_for_leg(leg_id: str) -> bool:
    """
    Stop browser children without terminating the executor-owned worker.
    Returns True if browser children were killed, False if none were found.
    """
    pid = get_worker_pid(leg_id)
    if pid is None:
        logger.info("[REGISTRY] No worker found for leg_id=%s (already exited or never started)", leg_id)
        return False

    logger.info("[REGISTRY] kill_worker_for_leg: leg_id=%s worker_pid=%d - starting cleanup", leg_id, pid)
    killed = _kill_browser_children(pid, leg_id)
    unregister_worker(leg_id)
    return killed > 0


def kill_all_workers_for_job(job_id: str) -> int:
    """Kill browser children for every worker in a job. Returns count of processes killed."""
    workers = get_workers_for_job(job_id)
    killed = 0
    for lid, pid in workers.items():
        killed += _kill_browser_children(pid, lid)
    # Clean up registry
    with _LOCK:
        registry = _read_registry()
        for lid in workers:
            registry.pop(lid, None)
        _write_registry(registry)
    return killed


def list_workers() -> Dict[str, Dict]:
    """List all registered workers. For debugging."""
    with _LOCK:
        return _read_registry()
