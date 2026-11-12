"""
Operator-only Chrome window rotation (Phase 1 + Phase 2 freeze/resume).

Brings depot Chrome windows to the foreground on a fixed interval so an operator
can visually monitor parallel sessions. Does NOT interact with Selenium, bidding,
timers, Search, planning, execution, or rank logic.

Phase 2: pause OS foreground switching while any live_bids leg is executing or
waiting_rank. Workers are never paused, delayed, or synchronized.

Visibility never controls which depot executes.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, MutableMapping, Optional, Tuple

from . import execution_logging as elog
from .logging_service import get_logger

logger = get_logger("window_rotation")

TITLE_PREFIX = "LogiBid"

# Phase 2: freeze rotation while any job leg is in these live_bids statuses.
FREEZE_STATUSES = frozenset({"executing", "waiting_rank"})


def get_window_rotation_settings(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Read window_rotation block from app config (and env overrides)."""
    if cfg is None:
        from .config_loader import get_app_config

        cfg = get_app_config()
    wr = (cfg.get("window_rotation") or {}) if isinstance(cfg, dict) else {}
    enabled = bool(wr.get("enabled", False))
    env = os.getenv("WINDOW_ROTATION_ENABLED", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        enabled = True
    elif env in ("0", "false", "no", "off"):
        enabled = False
    try:
        interval = float(wr.get("interval_seconds", 5))
    except (TypeError, ValueError):
        interval = 5.0
    if interval < 1.0:
        interval = 1.0
    env_iv = os.getenv("WINDOW_ROTATION_INTERVAL_SECONDS", "").strip()
    if env_iv:
        try:
            interval = max(1.0, float(env_iv))
        except (TypeError, ValueError):
            pass
    freeze_on_execution = bool(wr.get("freeze_on_execution", True))
    env_fz = os.getenv("WINDOW_ROTATION_FREEZE_ON_EXECUTION", "").strip().lower()
    if env_fz in ("1", "true", "yes", "on"):
        freeze_on_execution = True
    elif env_fz in ("0", "false", "no", "off"):
        freeze_on_execution = False
    return {
        "enabled": enabled,
        "interval_seconds": interval,
        "freeze_on_execution": freeze_on_execution,
    }


def get_freeze_legs_for_job(job_id: str) -> List[Dict[str, str]]:
    """
    Read-only: legs for this job currently in executing / waiting_rank.
    Never raises; returns [] on any failure (rotation continues).
    """
    jid = (job_id or "").strip()
    if not jid:
        return []
    try:
        from .live_bids_store import list_live_bids

        data = list_live_bids(job_id=jid, active_only=False)
        items = data.get("items") or []
        out: List[Dict[str, str]] = []
        for row in items:
            status = str(row.get("status") or "").strip().lower()
            if status not in FREEZE_STATUSES:
                continue
            out.append(
                {
                    "depot": str(row.get("depot") or "").strip() or "?",
                    "status": status,
                }
            )
        return out
    except Exception as e:
        logger.debug("[ROTATION] freeze status read failed: %s", e)
        return []


def make_window_title(job_id: str, depot: str) -> str:
    jid = (job_id or "nojid").strip()[:12] or "nojid"
    dep = (depot or "unknown").strip() or "unknown"
    return f"{TITLE_PREFIX}|{jid}|{dep}"


def _win32_available() -> bool:
    if os.name != "nt":
        return False
    try:
        import win32gui  # noqa: F401
        import win32con  # noqa: F401
        import win32process  # noqa: F401

        return True
    except ImportError:
        return False


def _win32_unavailable_reason() -> str:
    """Observability-only: explain why Win32 APIs are unavailable (does not change gates)."""
    if os.name != "nt":
        return f"os.name={os.name!r} is not 'nt' (Windows required)"
    try:
        import win32gui  # noqa: F401
        import win32con  # noqa: F401
        import win32process  # noqa: F401

        return ""
    except ImportError as e:
        return f"ImportError: {e}"


def apply_window_title(driver: Any, title: str) -> bool:
    """
    Set the browser document title used to locate the HWND. Never raises.
    Returns True on success, False on failure (observability only — callers may ignore).
    """
    try:
        driver.execute_script("document.title = arguments[0];", title)
        return True
    except Exception as e:
        logger.warning(
            "[ROTATION][REG] Failed to set document title title=%r error=%s",
            title,
            e,
        )
        return False


def resolve_chrome_pid(driver: Any) -> Optional[int]:
    """Best-effort Chrome browser PID from undetected_chromedriver / service."""
    for attr in ("browser_pid", "browser_pid_"):
        try:
            pid = getattr(driver, attr, None)
            if pid is not None:
                return int(pid)
        except Exception:
            pass
    try:
        svc = getattr(driver, "service", None)
        proc = getattr(svc, "process", None) if svc is not None else None
        if proc is not None and getattr(proc, "pid", None):
            # ChromeDriver PID — useful fallback for EnumWindows filtering
            return int(proc.pid)
    except Exception:
        pass
    return None


def find_hwnd_by_title(title: str, chrome_pid: Optional[int] = None) -> Optional[int]:
    """Locate a top-level window whose title contains ``title``."""
    if not _win32_available() or not title:
        return None
    import win32gui
    import win32process

    needle = title.strip()
    matches: List[Tuple[int, str]] = []

    def _enum(hwnd: int, _: Any) -> None:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            text = win32gui.GetWindowText(hwnd) or ""
            if needle not in text:
                return
            if chrome_pid is not None:
                try:
                    _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
                    # Accept window owned by chrome_pid, or any match if PID unknown
                    if pid and int(pid) != int(chrome_pid):
                        # Title match is still authoritative when PIDs differ
                        # (title is unique per depot); keep the match.
                        pass
                except Exception:
                    pass
            matches.append((int(hwnd), text))
        except Exception:
            return

    try:
        win32gui.EnumWindows(_enum, None)
    except Exception as e:
        logger.warning("[ROTATION] EnumWindows failed: %s", e)
        return None

    if not matches:
        return None
    # Prefer exact-ish longest title containing needle (Chrome often appends " - Google Chrome")
    matches.sort(key=lambda t: len(t[1]), reverse=True)
    return matches[0][0]


def bring_hwnd_to_foreground(hwnd: int) -> bool:
    """OS-level foreground switch. Returns False if window is gone or focus denied."""
    if not _win32_available():
        logger.info(
            "[ROTATION][FOCUS] attempt hwnd=%s result=False reason=win32_unavailable",
            hwnd,
        )
        return False
    import win32api
    import win32con
    import win32gui
    import win32process

    try:
        hwnd = int(hwnd)
    except (TypeError, ValueError):
        logger.info(
            "[ROTATION][FOCUS] attempt hwnd=%r result=False reason=invalid_hwnd",
            hwnd,
        )
        return False
    t0 = time.perf_counter()
    try:
        is_window = bool(win32gui.IsWindow(hwnd))
        if not is_window:
            logger.info(
                "[ROTATION][FOCUS] attempt hwnd=%s is_window=False result=False "
                "reason=not_a_window",
                hwnd,
            )
            return False

        is_iconic = bool(win32gui.IsIconic(hwnd))
        if is_iconic:
            logger.info(
                "[ROTATION][FOCUS] iconic_restore hwnd=%s is_iconic=True",
                hwnd,
            )
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

        fg = win32gui.GetForegroundWindow()
        cur_tid = win32api.GetCurrentThreadId()
        fg_tid, fg_pid = win32process.GetWindowThreadProcessId(fg) if fg else (0, 0)
        target_tid, target_pid = win32process.GetWindowThreadProcessId(hwnd)

        logger.info(
            "[ROTATION][FOCUS] attempt hwnd=%s is_window=True is_iconic=%s "
            "fg_before=%s cur_tid=%s fg_tid=%s fg_pid=%s target_tid=%s target_pid=%s",
            hwnd,
            is_iconic,
            int(fg) if fg else 0,
            cur_tid,
            fg_tid,
            fg_pid,
            target_tid,
            target_pid,
        )

        attached_fg = False
        attached_tg = False
        setfg_ret: Optional[bool] = None
        try:
            if fg and fg_tid and fg_tid != cur_tid:
                attached_fg = bool(win32process.AttachThreadInput(cur_tid, fg_tid, True))
                logger.info(
                    "[ROTATION][FOCUS] attach_input hwnd=%s side=foreground "
                    "cur_tid=%s fg_tid=%s attached=%s",
                    hwnd,
                    cur_tid,
                    fg_tid,
                    attached_fg,
                )
            if target_tid and target_tid != cur_tid:
                attached_tg = bool(win32process.AttachThreadInput(cur_tid, target_tid, True))
                logger.info(
                    "[ROTATION][FOCUS] attach_input hwnd=%s side=target "
                    "cur_tid=%s target_tid=%s attached=%s",
                    hwnd,
                    cur_tid,
                    target_tid,
                    attached_tg,
                )
            win32gui.BringWindowToTop(hwnd)
            logger.info(
                "[ROTATION][FOCUS] bring_to_top hwnd=%s",
                hwnd,
            )
            setfg_ret = bool(win32gui.SetForegroundWindow(hwnd))
            logger.info(
                "[ROTATION][FOCUS] set_foreground hwnd=%s setfg_ret=%s",
                hwnd,
                setfg_ret,
            )
        finally:
            if attached_tg and target_tid:
                try:
                    win32process.AttachThreadInput(cur_tid, target_tid, False)
                except Exception:
                    pass
            if attached_fg and fg_tid:
                try:
                    win32process.AttachThreadInput(cur_tid, fg_tid, False)
                except Exception:
                    pass

        fg_after = win32gui.GetForegroundWindow()
        became_foreground = bool(fg_after) and int(fg_after) == int(hwnd)
        still_window = bool(win32gui.IsWindow(hwnd))
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        logger.info(
            "[ROTATION][FOCUS] result hwnd=%s fg_before=%s fg_after=%s "
            "setfg_ret=%s became_foreground=%s still_is_window=%s "
            "elapsed_ms=%s runtime_return=%s",
            hwnd,
            int(fg) if fg else 0,
            int(fg_after) if fg_after else 0,
            setfg_ret,
            became_foreground,
            still_window,
            elapsed_ms,
            still_window,
        )
        if not became_foreground:
            logger.info(
                "[ROTATION][FOCUS] denied hwnd=%s fg_after=%s setfg_ret=%s "
                "reason=foreground_unchanged_or_other_window",
                hwnd,
                int(fg_after) if fg_after else 0,
                setfg_ret,
            )
        # Runtime success criteria unchanged: IsWindow only (not became_foreground).
        return still_window
    except Exception as e:
        logger.info(
            "[ROTATION][FOCUS] exception hwnd=%s error=%s elapsed_ms=%s",
            hwnd,
            e,
            round((time.perf_counter() - t0) * 1000.0, 2),
        )
        return False


def register_window(
    registry: Optional[MutableMapping[str, Any]],
    *,
    job_id: str,
    depot: str,
    driver: Any,
    lock: Any = None,
    expected_depots: Optional[List[str]] = None,
) -> bool:
    """
    Register a worker's Chrome window in the shared registry.
    Safe no-op if registry is None. Never raises into the worker critical path.
    """
    jid = str(job_id or "") or "n/a"
    worker_pid = int(os.getpid())
    if registry is None:
        logger.info(
            "[ROTATION][REG] Registration skipped "
            "job_id=%s depot=%s worker_pid=%s reason=registry_unavailable",
            jid,
            (depot or "").strip() or "?",
            worker_pid,
        )
        return False
    depot_key = (depot or "").strip()
    if not depot_key:
        logger.warning(
            "[ROTATION][REG] Registration failed "
            "job_id=%s depot=%r worker_pid=%s reason=empty_depot",
            jid,
            depot,
            worker_pid,
        )
        return False
    try:
        title = make_window_title(job_id or "", depot_key)
        logger.info(
            "[ROTATION][REG] Window title created "
            "job_id=%s depot=%s worker_pid=%s title=%r",
            jid,
            depot_key,
            worker_pid,
            title,
        )
        title_ok = apply_window_title(driver, title)
        logger.info(
            "[ROTATION][REG] Window title applied "
            "job_id=%s depot=%s worker_pid=%s title=%r success=%s",
            jid,
            depot_key,
            worker_pid,
            title,
            title_ok,
        )
        # Brief settle so Chrome updates the OS title bar
        time.sleep(0.35)
        chrome_pid = resolve_chrome_pid(driver)
        logger.info(
            "[ROTATION][REG] Chrome PID resolved "
            "job_id=%s depot=%s worker_pid=%s chrome_pid=%s",
            jid,
            depot_key,
            worker_pid,
            chrome_pid,
        )
        logger.info(
            "[ROTATION][HWND] Search started "
            "job_id=%s depot=%s worker_pid=%s title=%r chrome_pid=%s attempt=1",
            jid,
            depot_key,
            worker_pid,
            title,
            chrome_pid,
        )
        hwnd = find_hwnd_by_title(title, chrome_pid=chrome_pid)
        if hwnd is not None:
            logger.info(
                "[ROTATION][HWND] Found "
                "job_id=%s depot=%s worker_pid=%s hwnd=%s attempt=1",
                jid,
                depot_key,
                worker_pid,
                hwnd,
            )
        if hwnd is None:
            # Retry once — title bar update can lag
            logger.info(
                "[ROTATION][HWND] Retry "
                "job_id=%s depot=%s worker_pid=%s retry_number=1 "
                "reason=hwnd_not_found_attempt_1",
                jid,
                depot_key,
                worker_pid,
            )
            time.sleep(0.5)
            title_ok_retry = apply_window_title(driver, title)
            logger.info(
                "[ROTATION][REG] Window title applied "
                "job_id=%s depot=%s worker_pid=%s title=%r success=%s attempt=2",
                jid,
                depot_key,
                worker_pid,
                title,
                title_ok_retry,
            )
            logger.info(
                "[ROTATION][HWND] Search started "
                "job_id=%s depot=%s worker_pid=%s title=%r chrome_pid=%s attempt=2",
                jid,
                depot_key,
                worker_pid,
                title,
                chrome_pid,
            )
            hwnd = find_hwnd_by_title(title, chrome_pid=chrome_pid)
            if hwnd is not None:
                logger.info(
                    "[ROTATION][HWND] Found "
                    "job_id=%s depot=%s worker_pid=%s hwnd=%s attempt=2",
                    jid,
                    depot_key,
                    worker_pid,
                    hwnd,
                )
        if hwnd is None:
            logger.warning(
                "[ROTATION][HWND] Final failure — not registered "
                "job_id=%s depot=%s worker_pid=%s title=%r chrome_pid=%s "
                "reason=hwnd_not_found_after_retry",
                jid,
                depot_key,
                worker_pid,
                title,
                chrome_pid,
            )
            return False

        entry = {
            "job_id": str(job_id or ""),
            "depot": depot_key,
            "worker_pid": worker_pid,
            "chrome_pid": int(chrome_pid) if chrome_pid is not None else None,
            "hwnd": int(hwnd),
            "title": title,
            "active": True,
            "registered_at": time.time(),
        }

        def _put() -> None:
            registry[depot_key] = entry

        if lock is not None:
            with lock:
                _put()
        else:
            _put()

        logger.info(
            "[ROTATION][REG] Registration success "
            "job_id=%s depot=%s hwnd=%s worker_pid=%s chrome_pid=%s",
            jid,
            depot_key,
            hwnd,
            entry["worker_pid"],
            entry.get("chrome_pid"),
        )
        log_registry_snapshot(
            registry,
            expected_depots=expected_depots,
            job_id=jid,
            lock=lock,
            source="register",
        )
        return True
    except Exception as e:
        logger.warning(
            "[ROTATION][REG] Registration failed "
            "job_id=%s depot=%s worker_pid=%s reason=exception error=%s",
            jid,
            depot_key,
            worker_pid,
            e,
        )
        return False


def unregister_window(
    registry: Optional[MutableMapping[str, Any]],
    depot: str,
    *,
    lock: Any = None,
    reason: str = "completed",
    expected_depots: Optional[List[str]] = None,
) -> bool:
    """Remove a depot from rotation immediately. Never raises."""
    jid = "n/a"
    worker_pid = int(os.getpid())
    if registry is None:
        return False
    depot_key = (depot or "").strip()
    if not depot_key:
        return False
    try:
        logger.info(
            "[ROTATION][REG] Unregister requested "
            "depot=%s worker_pid=%s reason=%s",
            depot_key,
            worker_pid,
            reason,
        )

        def _remove() -> bool:
            if depot_key not in registry:
                return False
            try:
                del registry[depot_key]
            except Exception:
                # Manager dict: mark inactive if delete fails
                try:
                    old = dict(registry.get(depot_key) or {})
                    old["active"] = False
                    registry[depot_key] = old
                except Exception:
                    return False
            return True

        removed = False
        if lock is not None:
            with lock:
                removed = _remove()
        else:
            removed = _remove()

        if removed:
            logger.info(
                "[ROTATION][REG] Unregister completed "
                "depot=%s worker_pid=%s reason=%s removed=True",
                depot_key,
                worker_pid,
                reason,
            )
            log_registry_snapshot(
                registry,
                expected_depots=expected_depots,
                job_id=jid,
                lock=lock,
                source="unregister",
            )
        else:
            logger.info(
                "[ROTATION][REG] Unregister completed "
                "depot=%s worker_pid=%s reason=%s removed=False",
                depot_key,
                worker_pid,
                reason,
            )
        return removed
    except Exception as e:
        logger.warning(
            "[ROTATION][REG] Unregister failed "
            "depot=%s worker_pid=%s reason=%s error=%s",
            depot_key,
            worker_pid,
            reason,
            e,
        )
        return False


def _active_entries(
    registry: MutableMapping[str, Any],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        items = list(registry.items())
    except Exception:
        return out
    for _key, raw in items:
        try:
            entry = dict(raw) if not isinstance(raw, dict) else dict(raw)
        except Exception:
            continue
        if not entry.get("active", True):
            continue
        if entry.get("hwnd") is None:
            continue
        out.append(entry)
    # Stable order by depot name for predictable round-robin
    out.sort(key=lambda e: str(e.get("depot") or ""))
    return out


def _read_expected_depots_from_registry(
    registry: Optional[MutableMapping[str, Any]],
    explicit: Optional[List[str]] = None,
) -> List[str]:
    """Observability-only: resolve expected depot list from explicit arg (never from registry)."""
    if explicit is not None:
        return [str(d) for d in explicit]
    return []


def format_registry_snapshot(
    registry: Optional[MutableMapping[str, Any]],
    *,
    expected_depots: Optional[List[str]] = None,
) -> str:
    """
    Build a single-line registry diagnostic string. READ-ONLY — never mutates registry.
    Registry is expected to contain only real depot window entries.
    """
    expected = _read_expected_depots_from_registry(registry, expected_depots)
    registered: List[str] = []
    entry_parts: List[str] = []
    active_count = 0
    inactive_count = 0
    now = time.time()

    items: List[Tuple[Any, Any]] = []
    if registry is not None:
        try:
            items = list(registry.items())
        except Exception:
            items = []

    for key, raw in items:
        key_s = str(key)
        try:
            entry = dict(raw) if not isinstance(raw, dict) else dict(raw)
        except Exception:
            inactive_count += 1
            registered.append(key_s)
            entry_parts.append(
                f"{{depot={key_s} hwnd=None worker_pid=None chrome_pid=None "
                f"registered_at=None age_s=None}}"
            )
            continue

        depot = str(entry.get("depot") or key_s)
        registered.append(depot)
        hwnd = entry.get("hwnd")
        is_active = bool(entry.get("active", True)) and hwnd is not None
        if is_active:
            active_count += 1
        else:
            inactive_count += 1

        reg_at = entry.get("registered_at")
        age_s: Optional[float] = None
        try:
            if reg_at is not None:
                age_s = round(max(0.0, now - float(reg_at)), 1)
        except (TypeError, ValueError):
            age_s = None

        entry_parts.append(
            "{{depot={} hwnd={} worker_pid={} chrome_pid={} registered_at={} age_s={}}}".format(
                depot,
                hwnd,
                entry.get("worker_pid"),
                entry.get("chrome_pid"),
                reg_at,
                age_s,
            )
        )

    registered_unique = sorted(set(registered))
    expected_norm = [str(d) for d in expected]
    missing = [d for d in expected_norm if d not in set(registered_unique)]
    size = len(registered_unique)

    return (
        "[ROTATION][REGISTRY] "
        "expected={exp} registered={reg} missing={miss} "
        "size={size} active={active} inactive={inactive} "
        "entries=[{entries}]".format(
            exp=expected_norm,
            reg=registered_unique,
            miss=missing,
            size=size,
            active=active_count,
            inactive=inactive_count,
            entries="; ".join(entry_parts),
        )
    )


def log_registry_snapshot(
    registry: Optional[MutableMapping[str, Any]],
    *,
    expected_depots: Optional[List[str]] = None,
    job_id: str = "",
    lock: Any = None,
    source: str = "",
) -> None:
    """
    Emit [ROTATION][REGISTRY] diagnostics. READ-ONLY — never mutates registry.
    Acquires lock only for the duration of the read when provided.
    """
    jid = str(job_id or "") or "n/a"

    def _emit() -> None:
        try:
            line = format_registry_snapshot(
                registry, expected_depots=expected_depots
            )
            logger.info("%s job_id=%s source=%s", line, jid, source or "n/a")
        except Exception as e:
            logger.warning(
                "[ROTATION][REGISTRY] snapshot_failed job_id=%s source=%s error=%s",
                jid,
                source or "n/a",
                e,
            )

    try:
        if lock is not None:
            with lock:
                _emit()
        else:
            _emit()
    except Exception as e:
        logger.warning(
            "[ROTATION][REGISTRY] snapshot_lock_failed job_id=%s source=%s error=%s",
            jid,
            source or "n/a",
            e,
        )


class WindowRotationManager:
    """
    Parent-process thread that round-robins OS foreground among registered Chromes.

    Phase 2: skips SetForegroundWindow while any live_bids leg for this job is
    executing or waiting_rank. Never talks to Selenium or the bidding engine;
    never waits on or signals workers.
    """

    def __init__(
        self,
        registry: MutableMapping[str, Any],
        *,
        interval_seconds: float = 5.0,
        lock: Any = None,
        job_id: str = "",
        freeze_on_execution: bool = True,
        expected_depots: Optional[List[str]] = None,
    ) -> None:
        self._registry = registry
        self._interval = max(1.0, float(interval_seconds))
        self._lock = lock
        self._job_id = job_id or ""
        self._freeze_on_execution = bool(freeze_on_execution)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._index = 0
        self._frozen = False
        # Observability-only counters (not used by rotation decisions)
        self._loop_seq = 0
        self._last_switch_mono: Optional[float] = None
        # Observability-only metadata (never consulted by _run / freeze / switching)
        self._expected_depots: List[str] = [str(d) for d in (expected_depots or [])]
        logger.info(
            "[ROTATION][MGR] Manager created "
            "job_id=%s interval=%.1f freeze_on_execution=%s registry_id=%s "
            "lock_available=%s thread_started=False expected_depots=%s",
            self._job_id or "n/a",
            self._interval,
            self._freeze_on_execution,
            id(self._registry),
            self._lock is not None,
            list(self._expected_depots),
        )

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        prior = self._thread
        prior_alive = bool(prior is not None and prior.is_alive())
        logger.info(
            "[ROTATION][MGR] Manager starting "
            "job_id=%s interval=%.1f freeze_on_execution=%s "
            "prior_thread_exists=%s prior_thread_alive=%s stop_event_set=%s",
            self._job_id or "n/a",
            self._interval,
            self._freeze_on_execution,
            prior is not None,
            prior_alive,
            self._stop.is_set(),
        )
        if not _win32_available():
            reason = _win32_unavailable_reason() or "Win32 APIs unavailable"
            logger.warning(
                "[ROTATION][MGR] Win32 unavailable — Rotation Manager not started "
                "job_id=%s os.name=%s reason=%s (install pywin32 on Windows)",
                self._job_id or "n/a",
                os.name,
                reason,
            )
            return
        self._stop.clear()
        self._frozen = False
        thread_name = f"window-rotation-{(self._job_id or '')[:8] or 'job'}"
        logger.info(
            "[ROTATION][THREAD] Creating thread "
            "job_id=%s name=%s daemon=True target=WindowRotationManager._run",
            self._job_id or "n/a",
            thread_name,
        )
        self._thread = threading.Thread(
            target=self._run,
            name=thread_name,
            daemon=True,
        )
        self._thread.start()
        t = self._thread
        logger.info(
            "[ROTATION][THREAD] Thread started "
            "job_id=%s name=%s ident=%s native_id=%s alive=%s "
            "interval=%.1f freeze_on_execution=%s",
            self._job_id or "n/a",
            t.name if t is not None else thread_name,
            getattr(t, "ident", None) if t is not None else None,
            getattr(t, "native_id", None) if t is not None else None,
            bool(t is not None and t.is_alive()),
            self._interval,
            self._freeze_on_execution,
        )

    def stop(self) -> None:
        t = self._thread
        alive_before = bool(t is not None and t.is_alive())
        logger.info(
            "[ROTATION][THREAD] Stop requested "
            "job_id=%s thread_alive=%s stop_event_set_before=%s",
            self._job_id or "n/a",
            alive_before,
            self._stop.is_set(),
        )
        self._stop.set()
        join_timeout = max(2.0, self._interval + 1.0)
        join_attempted = False
        if t is not None and t.is_alive():
            join_attempted = True
            t.join(timeout=join_timeout)
        alive_after = bool(t is not None and t.is_alive())
        join_success = (not join_attempted) or (not alive_after)
        self._thread = None
        self._frozen = False
        logger.info(
            "[ROTATION][THREAD] Thread stopped "
            "job_id=%s join_attempted=%s join_success=%s join_timeout_s=%.1f "
            "final_alive=%s loop_seq=%s",
            self._job_id or "n/a",
            join_attempted,
            join_success,
            join_timeout,
            alive_after,
            getattr(self, "_loop_seq", 0),
        )

    def _drop_stale(self, depot: str, reason: str) -> None:
        unregister_window(
            self._registry,
            depot,
            lock=self._lock,
            reason=reason,
            expected_depots=list(getattr(self, "_expected_depots", []) or []),
        )

    def _refresh_hwnd_for_entry(self, entry: Dict[str, Any]) -> Optional[int]:
        """
        Re-resolve a depot Chrome HWND by stored window title after IsWindow fails.
        Updates the shared registry in place when a live window is found.
        Does not touch bidding / Selenium / workers.
        """
        depot = str(entry.get("depot") or "").strip()
        title = str(entry.get("title") or "").strip()
        if not depot or not title:
            logger.info(
                "[ROTATION][HWND] Refresh skipped depot=%r reason=missing_depot_or_title",
                depot or entry.get("depot"),
            )
            return None

        chrome_pid_raw = entry.get("chrome_pid")
        chrome_pid: Optional[int]
        try:
            chrome_pid = int(chrome_pid_raw) if chrome_pid_raw is not None else None
        except (TypeError, ValueError):
            chrome_pid = None

        old_hwnd = entry.get("hwnd")
        logger.info(
            "[ROTATION][HWND] Refresh attempt depot=%s old_hwnd=%s title=%r chrome_pid=%s",
            depot,
            old_hwnd,
            title,
            chrome_pid,
        )
        new_hwnd = find_hwnd_by_title(title, chrome_pid=chrome_pid)
        if new_hwnd is None:
            logger.info(
                "[ROTATION][HWND] Refresh failed depot=%s title=%r reason=hwnd_not_found",
                depot,
                title,
            )
            return None

        new_hwnd_i = int(new_hwnd)

        def _update() -> bool:
            if depot not in self._registry:
                return False
            try:
                raw = self._registry.get(depot)
                updated = dict(raw) if not isinstance(raw, dict) else dict(raw)
            except Exception:
                return False
            updated["hwnd"] = new_hwnd_i
            updated["active"] = True
            self._registry[depot] = updated
            return True

        try:
            if self._lock is not None:
                with self._lock:
                    updated_ok = _update()
            else:
                updated_ok = _update()
        except Exception as e:
            logger.warning(
                "[ROTATION][HWND] Refresh registry update failed depot=%s error=%s",
                depot,
                e,
            )
            return None

        if not updated_ok:
            logger.info(
                "[ROTATION][HWND] Refresh aborted depot=%s reason=depot_not_in_registry",
                depot,
            )
            return None

        entry["hwnd"] = new_hwnd_i
        logger.info(
            "[ROTATION][HWND] Refresh success depot=%s old_hwnd=%s new_hwnd=%s",
            depot,
            old_hwnd,
            new_hwnd_i,
        )
        return new_hwnd_i

    def _apply_freeze_policy(self) -> bool:
        """
        Returns True when rotation must stay frozen (no foreground switch).
        Read-only against live_bids; never affects workers.
        """
        if not self._freeze_on_execution:
            if self._frozen:
                self._frozen = False
                logger.info(
                    "[ROTATION] Freeze OFF\n"
                    "No executing depots remaining\n"
                    "Resuming 5 second rotation"
                )
            return False

        freeze_legs = get_freeze_legs_for_job(self._job_id)
        should_freeze = len(freeze_legs) > 0

        if should_freeze and not self._frozen:
            # Prefer an executing depot in the reason line; else first waiting_rank.
            reason_leg = next(
                (x for x in freeze_legs if x.get("status") == "executing"),
                freeze_legs[0],
            )
            depot = str(reason_leg.get("depot") or "?").upper()
            status = str(reason_leg.get("status") or "?").upper()
            logger.info(
                "[ROTATION] Freeze ON\n"
                "Reason: Depot %s entered %s",
                depot,
                status,
            )
            elog.log_rotation_job(
                self._job_id,
                f"Freeze ON reason=Depot {depot} entered {status}",
                action="FREEZE_ON",
                depot=depot,
                leg_status=status,
            )
            for leg in freeze_legs:
                elog.mirror_to_execution(
                    self._job_id,
                    str(leg.get("depot") or depot),
                    action="FREEZE_ON",
                    message=f"ROTATION FREEZE ON reason=Depot entered {leg.get('status')}",
                    status="ok",
                    trigger_depot=depot,
                    leg_status=leg.get("status"),
                )
            self._frozen = True
        elif not should_freeze and self._frozen:
            logger.info(
                "[ROTATION] Freeze OFF\n"
                "No executing depots remaining\n"
                "Resuming 5 second rotation"
            )
            elog.log_rotation_job(
                self._job_id,
                "Freeze OFF — resuming rotation",
                action="FREEZE_OFF",
            )
            # Mirror to all expected depots (or active registry entries)
            try:
                targets = list(getattr(self, "_expected_depots", []) or [])
                if not targets:
                    targets = [
                        str(e.get("depot") or "")
                        for e in _active_entries(self._registry)
                    ]
            except Exception:
                targets = []
            for d in targets:
                if str(d).strip():
                    elog.mirror_to_execution(
                        self._job_id,
                        d,
                        action="FREEZE_OFF",
                        message="ROTATION FREEZE OFF — resuming 5s rotation",
                        status="ok",
                    )
            self._frozen = False

        return should_freeze

    def _run(self) -> None:
        """Rotation loop. Observability wrap only — loop body behaviour unchanged."""
        last_exc: Optional[BaseException] = None
        try:
            while not self._stop.is_set():
                self._loop_seq = int(getattr(self, "_loop_seq", 0)) + 1
                try:
                    if self._lock is not None:
                        with self._lock:
                            active = _active_entries(self._registry)
                    else:
                        active = _active_entries(self._registry)

                    # Phase 3 observability only — does not alter branches or decisions.
                    log_registry_snapshot(
                        self._registry,
                        expected_depots=list(getattr(self, "_expected_depots", []) or []),
                        job_id=self._job_id or "n/a",
                        lock=self._lock,
                        source="loop",
                    )

                    try:
                        registry_size = len(self._registry)
                    except Exception:
                        registry_size = -1
                    active_count = len(active)
                    now_mono = time.monotonic()
                    last_sw = getattr(self, "_last_switch_mono", None)
                    last_switch_age = (
                        round(now_mono - last_sw, 3) if last_sw is not None else None
                    )
                    next_switch_eta = float(self._interval)

                    if len(active) <= 1:
                        # No rotation when 0 or 1 active — workers unaffected
                        # Still evaluate freeze for clean ON/OFF logs if statuses clear.
                        self._apply_freeze_policy()
                        cur_depot = (
                            str(active[0].get("depot") or "?") if active_count == 1 else None
                        )
                        logger.info(
                            "[ROTATION][LOOP] skip "
                            "job_id=%s loop_seq=%s skip_reason=active_le_1 "
                            "active_count=%s registry_size=%s current_index=%s "
                            "current_depot=%s next_depot=%s frozen=%s "
                            "interval_seconds=%.1f last_switch_age=%s next_switch_eta=%.1f",
                            self._job_id or "n/a",
                            self._loop_seq,
                            active_count,
                            registry_size,
                            self._index,
                            cur_depot,
                            None,
                            self._frozen,
                            self._interval,
                            last_switch_age,
                            next_switch_eta,
                        )
                        elog.log_rotation_job(
                            self._job_id,
                            "skip reason=active_le_1",
                            action="SKIP",
                            depot=str(cur_depot or "*"),
                            loop_seq=self._loop_seq,
                            reason="active_le_1",
                        )
                        if cur_depot:
                            elog.mirror_to_execution(
                                self._job_id,
                                cur_depot,
                                action="SKIP",
                                message="ROTATION SKIP reason=active_le_1",
                                status="skip",
                                loop_seq=self._loop_seq,
                            )
                        self._stop.wait(self._interval)
                        continue

                    # Phase 2: pause switching only; do not force any window forward.
                    if self._apply_freeze_policy():
                        n = active_count
                        idx = self._index % n if n else 0
                        cur_depot = str(active[idx].get("depot") or "?") if n else None
                        next_depot = (
                            str(active[(idx + 1) % n].get("depot") or "?") if n else None
                        )
                        logger.info(
                            "[ROTATION][LOOP] skip "
                            "job_id=%s loop_seq=%s skip_reason=frozen "
                            "active_count=%s registry_size=%s current_index=%s "
                            "current_depot=%s next_depot=%s frozen=%s "
                            "interval_seconds=%.1f last_switch_age=%s next_switch_eta=%.1f",
                            self._job_id or "n/a",
                            self._loop_seq,
                            active_count,
                            registry_size,
                            self._index,
                            cur_depot,
                            next_depot,
                            self._frozen,
                            self._interval,
                            last_switch_age,
                            next_switch_eta,
                        )
                        elog.log_rotation_job(
                            self._job_id,
                            "skip reason=frozen",
                            action="SKIP",
                            depot=str(cur_depot or "*"),
                            loop_seq=self._loop_seq,
                            reason="frozen",
                            next_depot=next_depot,
                        )
                        if cur_depot:
                            elog.mirror_to_execution(
                                self._job_id,
                                cur_depot,
                                action="SKIP",
                                message="ROTATION SKIP reason=frozen",
                                status="skip",
                                loop_seq=self._loop_seq,
                                next_depot=next_depot,
                            )
                        self._stop.wait(self._interval)
                        continue

                    if self._index >= len(active):
                        self._index = 0
                    entry = active[self._index % len(active)]
                    idx_before = self._index
                    next_depot = str(
                        active[(self._index + 1) % len(active)].get("depot") or "?"
                    )
                    self._index = (self._index + 1) % len(active)

                    depot = str(entry.get("depot") or "?")
                    hwnd = entry.get("hwnd")
                    logger.info(
                        "[ROTATION][LOOP] switch_attempt "
                        "job_id=%s loop_seq=%s skip_reason=None "
                        "active_count=%s registry_size=%s current_index=%s "
                        "current_depot=%s next_depot=%s hwnd=%s frozen=%s "
                        "interval_seconds=%.1f last_switch_age=%s next_switch_eta=%.1f",
                        self._job_id or "n/a",
                        self._loop_seq,
                        active_count,
                        registry_size,
                        idx_before,
                        depot,
                        next_depot,
                        hwnd,
                        self._frozen,
                        self._interval,
                        last_switch_age,
                        next_switch_eta,
                    )
                    try:
                        ok = bring_hwnd_to_foreground(int(hwnd))
                    except (TypeError, ValueError):
                        ok = False

                    # Chrome may replace the top-level HWND while the session lives.
                    # Re-resolve by title once before permanently dropping the depot.
                    if not ok:
                        logger.info(
                            "[ROTATION][HWND] Focus failed — attempting HWND refresh "
                            "depot=%s hwnd=%s",
                            depot,
                            hwnd,
                        )
                        refreshed = self._refresh_hwnd_for_entry(entry)
                        if refreshed is not None:
                            hwnd = refreshed
                            try:
                                ok = bring_hwnd_to_foreground(int(hwnd))
                            except (TypeError, ValueError):
                                ok = False
                            logger.info(
                                "[ROTATION][HWND] Focus retry after refresh "
                                "depot=%s hwnd=%s ok=%s",
                                depot,
                                hwnd,
                                ok,
                            )

                    if ok:
                        self._last_switch_mono = time.monotonic()
                        logger.info("[ROTATION] Switching to depot: %s", depot)
                        logger.info(
                            "[ROTATION][LOOP] switch_ok "
                            "job_id=%s loop_seq=%s current_depot=%s "
                            "active_count=%s current_index=%s",
                            self._job_id or "n/a",
                            self._loop_seq,
                            depot,
                            active_count,
                            self._index,
                        )
                        elog.log_rotation_job(
                            self._job_id,
                            f"Switching to depot={depot}",
                            action="SWITCH_OK",
                            depot=depot,
                            loop_seq=self._loop_seq,
                            hwnd=hwnd,
                            current_index=self._index,
                        )
                        elog.mirror_to_execution(
                            self._job_id,
                            depot,
                            action="SWITCH",
                            message=f"ROTATION WINDOW SWITCH focus ok hwnd={hwnd}",
                            status="ok",
                            loop_seq=self._loop_seq,
                            hwnd=hwnd,
                            current_index=self._index,
                            next_depot=next_depot,
                        )
                    else:
                        logger.warning(
                            "[ROTATION] Stale window for depot=%s — removing from rotation "
                            "(refresh also failed)",
                            depot,
                        )
                        logger.info(
                            "[ROTATION][LOOP] stale_removed "
                            "job_id=%s loop_seq=%s depot=%s reason=stale_hwnd "
                            "active_count=%s hwnd=%s",
                            self._job_id or "n/a",
                            self._loop_seq,
                            depot,
                            active_count,
                            hwnd,
                        )
                        elog.mirror_to_execution(
                            self._job_id,
                            depot,
                            action="STALE_REMOVED",
                            message="ROTATION stale HWND removed after focus/refresh failure",
                            status="warn",
                            hwnd=hwnd,
                        )
                        self._drop_stale(depot, reason="stale_hwnd")
                except Exception as e:
                    last_exc = e
                    logger.warning("[ROTATION] Rotation loop error: %s", e)
                    logger.info(
                        "[ROTATION][LOOP] error "
                        "job_id=%s loop_seq=%s error=%s",
                        self._job_id or "n/a",
                        getattr(self, "_loop_seq", 0),
                        e,
                    )

                self._stop.wait(self._interval)
        except BaseException as e:
            last_exc = e
            raise
        finally:
            # Unexpected if the thread ends without stop() having been requested.
            if not self._stop.is_set():
                logger.error(
                    "[ROTATION][THREAD] Unexpected thread exit "
                    "job_id=%s loop_seq=%s last_exception=%r timestamp=%.6f",
                    self._job_id or "n/a",
                    getattr(self, "_loop_seq", 0),
                    last_exc,
                    time.time(),
                )


def should_enable_rotation(enabled: bool, depot_count: int) -> bool:
    """Phase 1 gate: feature on AND more than one depot in the job."""
    return bool(enabled) and int(depot_count) > 1
