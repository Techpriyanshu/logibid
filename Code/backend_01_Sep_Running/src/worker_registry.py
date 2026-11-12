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
import os
import signal
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


def kill_worker_for_leg(leg_id: str) -> bool:
    """
    Kill the worker process for a bid leg.
    Returns True if the process was killed, False if not found or already dead.
    Also kills child processes (Chrome browser) spawned by the worker.
    """
    pid = get_worker_pid(leg_id)
    if pid is None:
        logger.info("[REGISTRY] No worker found for leg_id=%s (already exited or never started)", leg_id)
        return False

    logger.info("[REGISTRY] kill_worker_for_leg: leg_id=%s worker_pid=%d - starting kill", leg_id, pid)

    try:
        import psutil
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        logger.info("[REGISTRY] Worker pid=%d has %d children", pid, len(children))
        # Kill children first (Chrome processes)
        for child in children:
            try:
                logger.info("[REGISTRY] Killing child process pid=%d name=%s for leg_id=%s", child.pid, child.name(), leg_id)
                child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        # Kill parent worker
        parent.kill()
        logger.info("[REGISTRY] Killed worker pid=%d and %d children for leg_id=%s", pid, len(children), leg_id)
        
        # Also kill any orphaned chromedriver/chrome processes spawned by this worker
        # On macOS, Chrome may not be a direct child of the worker
        try:
            for proc in psutil.process_iter(['pid', 'ppid', 'name', 'cmdline']):
                try:
                    pinfo = proc.info
                    pname = (pinfo.get('name') or '').lower()
                    cmdline = pinfo.get('cmdline') or []
                    cmdline_str = ' '.join(cmdline)
                    # Kill chromedriver or Chrome processes that were children of our worker
                    if pinfo.get('ppid') == pid or (
                        ('chromedriver' in pname or 'chrome' in pname) and
                        f'scoped_dir' in cmdline_str and
                        pinfo['pid'] not in [c.pid for c in children]
                    ):
                        logger.info("[REGISTRY] Killing orphaned process pid=%d name=%s for leg_id=%s",
                                    pinfo['pid'], pname, leg_id)
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            logger.debug("[REGISTRY] Orphan cleanup error: %s", e)
        
        unregister_worker(leg_id)
        return True
    except ImportError:
        # psutil not available, fall back to SIGTERM + SIGKILL
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info("[REGISTRY] Sent SIGTERM to worker pid=%d for leg_id=%s (psutil not available)", pid, leg_id)
            # NOTE: Do NOT use os.killpg() here — worker shares process group with parent (uvicorn).
            # Killing the process group would kill the backend server.
            unregister_worker(leg_id)
            return True
        except ProcessLookupError:
            logger.info("[REGISTRY] Worker pid=%d already dead for leg_id=%s", pid, leg_id)
            unregister_worker(leg_id)
            return False
    except psutil.NoSuchProcess:
        logger.info("[REGISTRY] Worker pid=%d already dead for leg_id=%s", pid, leg_id)
        unregister_worker(leg_id)
        return False
    except Exception as e:
        # Fallback: try os.kill
        try:
            os.kill(pid, signal.SIGKILL)
            logger.info("[REGISTRY] Sent SIGKILL to worker pid=%d for leg_id=%s", pid, leg_id)
            unregister_worker(leg_id)
            return True
        except Exception:
            pass
        logger.error("[REGISTRY] Failed to kill pid=%d for leg_id=%s: %s", pid, leg_id, e)
        return False


def kill_all_workers_for_job(job_id: str) -> int:
    """Kill all worker processes for a job. Returns count of processes killed."""
    workers = get_workers_for_job(job_id)
    killed = 0
    for lid, pid in workers.items():
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info("[REGISTRY] Sent SIGTERM to worker pid=%d for leg_id=%s job_id=%s", pid, lid, job_id)
            killed += 1
        except ProcessLookupError:
            logger.info("[REGISTRY] Worker pid=%d already dead for leg_id=%s", pid, lid)
        except Exception as e:
            logger.error("[REGISTRY] Failed to kill pid=%d: %s", pid, e)
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
