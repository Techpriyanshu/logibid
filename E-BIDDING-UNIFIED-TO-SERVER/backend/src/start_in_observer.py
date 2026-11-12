"""
Independent Start In observer for SAP synchronization investigation.

Observational only: never searches, plans, executes, or ranks.
Starts after E-Bidding opens (selenium_worker); works without a valid bid.

Behavior:
  - While timer text contains "Starts in", emit START_IN_SAMPLE every 5s
  - When Starts In disappears, stop sampling until it reappears
  - Freeze alert after 2 consecutive unchanged 5s samples (~10s)

Does not modify depot_bidding_engine control flow.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import execution_logging as elog
from .logging_service import get_logger

logger = get_logger("start_in_observer")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_STARTS_IN_RE = re.compile(r"starts\s*in", re.IGNORECASE)
_TIMER_VALUE_RE = re.compile(
    r"starts\s*in\s*([0-9]+(?::[0-9]+){0,2})",
    re.IGNORECASE,
)

_VALID_BID_CONTEXT_STATUSES = frozenset(
    {"planning", "ready", "executing", "waiting_rank"}
)

# In-page sampler: keep last timer text fresh; no file I/O in the browser.
_JS_INSTALL = r"""
(function(timerId) {
  if (window.__logiBidStartInObs && window.__logiBidStartInObs.v === 2) {
    return 'already';
  }
  window.__logiBidStartInObs = {
    v: 2,
    timerId: timerId,
    lastText: '',
    lastEpochMs: null
  };
  window.setInterval(function() {
    try {
      var e = document.getElementById(window.__logiBidStartInObs.timerId);
      var t = e ? String(e.textContent || e.innerText || '').trim() : '';
      window.__logiBidStartInObs.lastText = t;
      window.__logiBidStartInObs.lastEpochMs = Date.now();
    } catch (err) {}
  }, 200);
  return 'installed';
})(arguments[0]);
"""

_JS_READ_LAST = r"""
return (function() {
  var o = window.__logiBidStartInObs;
  if (!o) return null;
  return {
    text: o.lastText || '',
    epochMs: o.lastEpochMs
  };
})();
"""


def get_start_in_observer_settings(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if cfg is None:
        from .config_loader import get_app_config

        cfg = get_app_config()
    block = (cfg.get("start_in_observer") or {}) if isinstance(cfg, dict) else {}
    enabled = bool(block.get("enabled", True))
    env = os.getenv("START_IN_OBSERVER_ENABLED", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        enabled = True
    elif env in ("0", "false", "no", "off"):
        enabled = False

    def _float(key: str, default: float, minimum: float) -> float:
        try:
            v = float(block.get(key, default))
        except (TypeError, ValueError):
            v = default
        return max(minimum, v)

    sample = _float("sample_interval_seconds", 5.0, 1.0)
    poll = _float("poll_interval_seconds", 0.5, 0.2)
    try:
        freeze_n = int(block.get("freeze_unchanged_samples", 2))
    except (TypeError, ValueError):
        freeze_n = 2
    freeze_n = max(1, freeze_n)

    timer_id = str(
        block.get("timer_element_id")
        or (cfg.get("timer_element_id") if isinstance(cfg, dict) else None)
        or "__xmlview0--timer-inner"
    ).strip()

    return {
        "enabled": enabled,
        "sample_interval_seconds": sample,
        "poll_interval_seconds": poll,
        "freeze_unchanged_samples": freeze_n,
        "timer_element_id": timer_id or "__xmlview0--timer-inner",
    }


def _logs_dir() -> Path:
    d = _PROJECT_ROOT / "logs" / "start_in"
    d.mkdir(parents=True, exist_ok=True)
    return d


def parse_timer_value(raw: str) -> str:
    if not raw:
        return ""
    m = _TIMER_VALUE_RE.search(raw.strip())
    if not m:
        return ""
    return m.group(1).strip()


def parse_remaining_seconds(raw: str) -> Optional[int]:
    """Parse 'Starts in H:M:S' / 'M:S' / 'S' into total seconds."""
    frag = parse_timer_value(raw)
    if not frag:
        return None
    parts = frag.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 1:
        return nums[0]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None


def is_starts_in_text(raw: str) -> bool:
    return bool(raw and _STARTS_IN_RE.search(raw))


def valid_bid_context_present(job_id: str, depot: str) -> bool:
    """Debug-only: True if live_bids shows plan/exec path for this depot."""
    jid = (job_id or "").strip()
    dep = (depot or "").strip()
    if not jid or not dep:
        return False
    try:
        from .depot_normalization import normalize_depot_name
        from .live_bids_store import list_live_bids

        dn = normalize_depot_name(dep)
        data = list_live_bids(job_id=jid, active_only=False)
        for row in data.get("items") or []:
            if normalize_depot_name(str(row.get("depot") or "")) != dn:
                continue
            st = str(row.get("status") or "").strip().lower()
            if st in _VALID_BID_CONTEXT_STATUSES:
                return True
    except Exception:
        return False
    return False


def _append_jsonl(job_id: str, record: Dict[str, Any]) -> None:
    safe = re.sub(r"[^\w\-]+", "_", (job_id or "nojid").strip())[:64] or "nojid"
    path = _logs_dir() / f"{safe}.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _now_stamps() -> Tuple[datetime, datetime, str]:
    now = datetime.now().astimezone()
    utc = datetime.now(timezone.utc)
    display = now.strftime("%H:%M:%S.") + f"{int(now.microsecond / 1000):03d}"
    return now, utc, display


def _base_record(
    *,
    event: str,
    job_id: str,
    depot: str,
    worker_pid: int,
    timer_text_raw: str,
    seq: Optional[int],
    valid_bid: bool,
    period_id: int,
    remaining_seconds: Optional[int],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now, utc, display = _now_stamps()
    parsed = parse_timer_value(timer_text_raw)
    record: Dict[str, Any] = {
        "event": event,
        "job_id": str(job_id or ""),
        "depot": str(depot or ""),
        "worker_pid": int(worker_pid),
        "detected_at_local": now.isoformat(timespec="milliseconds"),
        "detected_at_utc": utc.isoformat(timespec="milliseconds"),
        "detected_at_local_display": display,
        "timer_text_raw": timer_text_raw,
        "timer_value_parsed": parsed,
        "remaining_seconds": remaining_seconds,
        "seq": seq,
        "period_id": period_id,
        "valid_bid": bool(valid_bid),
        "host_perf_counter": time.perf_counter(),
    }
    if extra:
        record.update(extra)
    return record


def emit_sample(record: Dict[str, Any]) -> None:
    try:
        _append_jsonl(str(record.get("job_id") or "nojid"), record)
    except Exception as e:
        logger.warning("[START_IN] JSONL write failed: %s", e)
    try:
        elog.append_timer_sample_jsonl(str(record.get("job_id") or "nojid"), record)
    except Exception:
        pass
    logger.info(
        "[START_IN] SAMPLE depot=%s time=%s timer=%r remaining=%s seq=%s valid_bid=%s",
        record.get("depot"),
        record.get("detected_at_local_display"),
        record.get("timer_text_raw"),
        record.get("remaining_seconds"),
        record.get("seq"),
        "Yes" if record.get("valid_bid") else "No",
    )
    elog.log_event(
        phase="OBSERVER",
        component="start_in",
        action="SAMPLE",
        status="ok",
        message="Start In sample",
        job_id=str(record.get("job_id") or ""),
        depot=str(record.get("depot") or ""),
        timer=record.get("timer_text_raw"),
        remaining_s=record.get("remaining_seconds"),
        seq=record.get("seq"),
        valid_bid=record.get("valid_bid"),
    )


def emit_freeze_alert(record: Dict[str, Any]) -> None:
    try:
        _append_jsonl(str(record.get("job_id") or "nojid"), record)
    except Exception as e:
        logger.warning("[START_IN] JSONL freeze write failed: %s", e)
    try:
        elog.append_timer_sample_jsonl(str(record.get("job_id") or "nojid"), record)
    except Exception:
        pass
    logger.warning(
        "[ALERT]\n"
        "Depot: %s\n"
        "\n"
        "Start In timer appears frozen.\n"
        "\n"
        "Previous Timer : %s\n"
        "\n"
        "Current Timer : %s\n"
        "\n"
        "Timer has not progressed for the expected interval.\n"
        "Unchanged samples: %s (interval=%ss)",
        record.get("depot"),
        record.get("previous_timer_text"),
        record.get("timer_text_raw"),
        record.get("unchanged_samples"),
        record.get("sample_interval_seconds"),
    )
    elog.log_event(
        phase="OBSERVER",
        component="start_in",
        action="FREEZE",
        status="warn",
        message="Start In timer appears frozen",
        level=logging.WARNING,
        job_id=str(record.get("job_id") or ""),
        depot=str(record.get("depot") or ""),
        timer=record.get("timer_text_raw"),
        previous_timer=record.get("previous_timer_text"),
        unchanged_samples=record.get("unchanged_samples"),
    )


class StartInObserver:
    """
    Background observer: 5s Start In samples + freeze alerts.
    Never calls Search / plan / execute / rank.
    """

    def __init__(
        self,
        driver: Any,
        *,
        job_id: str,
        depot: str,
        timer_element_id: str,
        sample_interval_seconds: float = 5.0,
        poll_interval_seconds: float = 0.5,
        freeze_unchanged_samples: int = 2,
    ) -> None:
        self._driver = driver
        self._job_id = str(job_id or "")
        self._depot = str(depot or "")
        self._timer_id = timer_element_id
        self._sample_interval = max(1.0, float(sample_interval_seconds))
        self._poll = max(0.2, float(poll_interval_seconds))
        self._freeze_n = max(1, int(freeze_unchanged_samples))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Observation state (in/out Starts In — not auction-cycle oriented)
        self._in_starts_in = False
        self._period_id = 0
        self._seq = 0
        self._last_sample_mono: Optional[float] = None
        self._last_remaining: Optional[int] = None
        self._last_timer_text: str = ""
        self._unchanged_streak = 0
        self._freeze_alerted = False

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        try:
            result = self._driver.execute_script(_JS_INSTALL, self._timer_id)
            logger.info(
                "[START_IN] Observer installed depot=%s timer_id=%s js=%s "
                "sample=%.1fs freeze_after=%d",
                self._depot,
                self._timer_id,
                result,
                self._sample_interval,
                self._freeze_n,
            )
            elog.log_event(
                phase="OBSERVER",
                component="start_in",
                action="INSTALL",
                status="ok",
                message="Start In observer JS installed",
                job_id=self._job_id,
                depot=self._depot,
                timer_id=self._timer_id,
            )
        except Exception as e:
            logger.warning(
                "[START_IN] JS install failed depot=%s — observer not started: %s",
                self._depot,
                e,
            )
            return False

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"start-in-obs-{(self._depot or 'depot')[:20]}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "[START_IN] Observer thread started depot=%s "
            "(independent of bidding; 5s samples while Starts In visible)",
            self._depot,
        )
        return True

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=max(2.0, self._sample_interval + 1.0))
        self._thread = None
        logger.info("[START_IN] Observer thread stopped depot=%s", self._depot)

    def _read_timer_snapshot(self) -> Optional[Dict[str, Any]]:
        try:
            data = self._driver.execute_script(_JS_READ_LAST)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return data

    def _reset_period_state(self) -> None:
        self._in_starts_in = False
        self._seq = 0
        self._last_sample_mono = None
        self._last_remaining = None
        self._last_timer_text = ""
        self._unchanged_streak = 0
        self._freeze_alerted = False

    def _emit_sample(self, text: str, remaining: Optional[int]) -> None:
        self._seq += 1
        valid = valid_bid_context_present(self._job_id, self._depot)
        record = _base_record(
            event="START_IN_SAMPLE",
            job_id=self._job_id,
            depot=self._depot,
            worker_pid=os.getpid(),
            timer_text_raw=text,
            seq=self._seq,
            valid_bid=valid,
            period_id=self._period_id,
            remaining_seconds=remaining,
            extra={"sample_interval_seconds": self._sample_interval},
        )
        emit_sample(record)

    def _check_freeze(self, text: str, remaining: Optional[int]) -> None:
        if remaining is None or self._last_remaining is None:
            self._unchanged_streak = 0
            return

        if remaining == self._last_remaining:
            self._unchanged_streak += 1
        else:
            if self._freeze_alerted:
                elog.log_event(
                    phase="OBSERVER",
                    component="start_in",
                    action="RECOVERY",
                    status="ok",
                    message="Start In timer recovered (remaining changed)",
                    job_id=self._job_id,
                    depot=self._depot,
                    timer=text,
                    remaining_s=remaining,
                    previous_remaining=self._last_remaining,
                )
            self._unchanged_streak = 0
            self._freeze_alerted = False
            return

        if self._unchanged_streak >= self._freeze_n and not self._freeze_alerted:
            self._freeze_alerted = True
            valid = valid_bid_context_present(self._job_id, self._depot)
            record = _base_record(
                event="START_IN_FREEZE",
                job_id=self._job_id,
                depot=self._depot,
                worker_pid=os.getpid(),
                timer_text_raw=text,
                seq=self._seq,
                valid_bid=valid,
                period_id=self._period_id,
                remaining_seconds=remaining,
                extra={
                    "previous_timer_text": self._last_timer_text,
                    "unchanged_samples": self._unchanged_streak,
                    "sample_interval_seconds": self._sample_interval,
                },
            )
            emit_freeze_alert(record)

    def _tick(self) -> None:
        data = self._read_timer_snapshot()
        if data is None:
            return
        text = str(data.get("text") or "").strip()
        in_si = is_starts_in_text(text)

        if not in_si:
            if self._in_starts_in:
                logger.info(
                    "[START_IN] Starts In ended depot=%s period_id=%s — sampling paused",
                    self._depot,
                    self._period_id,
                )
            self._reset_period_state()
            return

        # Entering Starts In from outside
        if not self._in_starts_in:
            self._period_id += 1
            self._in_starts_in = True
            self._seq = 0
            self._last_sample_mono = None
            self._last_remaining = None
            self._last_timer_text = ""
            self._unchanged_streak = 0
            self._freeze_alerted = False
            logger.info(
                "[START_IN] Starts In visible depot=%s period_id=%s — begin 5s sampling",
                self._depot,
                self._period_id,
            )

        now_mono = time.monotonic()
        due = (
            self._last_sample_mono is None
            or (now_mono - self._last_sample_mono) >= self._sample_interval
        )
        if not due:
            return

        remaining = parse_remaining_seconds(text)
        # Freeze check uses previous sample remaining before we overwrite it
        if self._last_sample_mono is not None:
            self._check_freeze(text, remaining)

        self._emit_sample(text, remaining)
        self._last_sample_mono = now_mono
        self._last_remaining = remaining
        self._last_timer_text = text

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.debug("[START_IN] tick error depot=%s: %s", self._depot, e)
            self._stop.wait(self._poll)


def start_observer_for_worker(
    driver: Any,
    *,
    job_id: str,
    depot: str,
    cfg: Optional[Dict[str, Any]] = None,
) -> Optional[StartInObserver]:
    """Factory used by selenium_worker. Returns None when disabled / install fails."""
    settings = get_start_in_observer_settings(cfg)
    if not settings["enabled"]:
        logger.info("[START_IN] Observer disabled by config — skipped")
        return None
    obs = StartInObserver(
        driver,
        job_id=job_id,
        depot=depot,
        timer_element_id=str(settings["timer_element_id"]),
        sample_interval_seconds=float(settings["sample_interval_seconds"]),
        poll_interval_seconds=float(settings["poll_interval_seconds"]),
        freeze_unchanged_samples=int(settings["freeze_unchanged_samples"]),
    )
    if not obs.start():
        return None
    return obs


def load_job_events(job_id: str) -> List[Dict[str, Any]]:
    """Load all JSONL events for a job (samples + freeze alerts)."""
    safe = re.sub(r"[^\w\-]+", "_", (job_id or "").strip())[:64]
    path = _logs_dir() / f"{safe}.jsonl"
    if not path.is_file():
        return []
    out: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out
