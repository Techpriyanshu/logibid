"""
Post-run helper: compare Start In samples across depots for one job.

Usage:
  python tools/compare_start_in.py --job-id <job_id>
  python tools/compare_start_in.py --job-id <job_id> --freezes

Reads logs/start_in/<job_id>.jsonl produced by start_in_observer.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.start_in_observer import load_job_events  # noqa: E402


def _parse_utc(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _bucket_key(iso_utc: str, bucket_seconds: int = 5) -> str:
    dt = _parse_utc(iso_utc)
    if dt is None:
        return iso_utc or "?"
    epoch = int(dt.timestamp())
    floored = epoch - (epoch % bucket_seconds)
    return datetime.fromtimestamp(floored, tz=dt.tzinfo).strftime("%H:%M:%S")


def print_sample_grid(events: List[Dict[str, Any]], bucket_seconds: int = 5) -> None:
    samples = [e for e in events if e.get("event") == "START_IN_SAMPLE"]
    if not samples:
        print("No START_IN_SAMPLE events found.")
        return

    depots = sorted({str(e.get("depot") or "?") for e in samples})
    # bucket -> depot -> best sample (prefer earliest in bucket)
    grid: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for e in samples:
        b = _bucket_key(str(e.get("detected_at_utc") or ""), bucket_seconds)
        dep = str(e.get("depot") or "?")
        prev = grid[b].get(dep)
        if prev is None or str(e.get("detected_at_utc") or "") < str(
            prev.get("detected_at_utc") or ""
        ):
            grid[b][dep] = e

    buckets = sorted(grid.keys())
    header = f"{'Time':<10}" + "".join(f"{d:<16}" for d in depots)
    print(header)
    print("-" * len(header))
    for b in buckets:
        row = f"{b:<10}"
        for d in depots:
            e = grid[b].get(d)
            if not e:
                row += f"{'—':<16}"
            else:
                cell = str(
                    e.get("timer_value_parsed")
                    or e.get("remaining_seconds")
                    or e.get("timer_text_raw")
                    or "?"
                )[:15]
                row += f"{cell:<16}"
        print(row)


def print_onset(events: List[Dict[str, Any]]) -> None:
    samples = [e for e in events if e.get("event") == "START_IN_SAMPLE"]
    first_by_depot: Dict[str, Dict[str, Any]] = {}
    for e in samples:
        dep = str(e.get("depot") or "?")
        if dep not in first_by_depot:
            first_by_depot[dep] = e
        else:
            if str(e.get("detected_at_utc") or "") < str(
                first_by_depot[dep].get("detected_at_utc") or ""
            ):
                first_by_depot[dep] = e

    rows = sorted(
        first_by_depot.values(),
        key=lambda r: str(r.get("detected_at_utc") or ""),
    )
    if not rows:
        return
    base = _parse_utc(str(rows[0].get("detected_at_utc") or ""))
    print("\nFirst sample per depot (onset skew):")
    print(f"{'Depot':<16} {'Local':<14} {'Timer':<20} {'Valid Bid':<10} {'Δms':>8}")
    print("-" * 72)
    for r in rows:
        dep = str(r.get("depot") or "")
        local = str(r.get("detected_at_local_display") or "")
        timer = str(r.get("timer_text_raw") or "")[:20]
        vb = "Yes" if r.get("valid_bid") else "No"
        delta = ""
        cur = _parse_utc(str(r.get("detected_at_utc") or ""))
        if base and cur:
            delta = f"{(cur - base).total_seconds() * 1000:+.0f}"
        print(f"{dep:<16} {local:<14} {timer:<20} {vb:<10} {delta:>8}")


def print_freezes(events: List[Dict[str, Any]]) -> None:
    freezes = [e for e in events if e.get("event") == "START_IN_FREEZE"]
    if not freezes:
        print("\nNo freeze alerts.")
        return
    print("\nFreeze alerts:")
    for e in freezes:
        print(
            f"  {e.get('depot')} @ {e.get('detected_at_local_display')} "
            f"prev={e.get('previous_timer_text')!r} cur={e.get('timer_text_raw')!r} "
            f"unchanged={e.get('unchanged_samples')}"
        )


def main() -> int:
    p = argparse.ArgumentParser(
        description="Compare Start In 5s samples across depots"
    )
    p.add_argument("--job-id", required=True, help="Automation job_id")
    p.add_argument(
        "--bucket-seconds",
        type=int,
        default=5,
        help="Wall-clock bucket size for the sync grid (default 5)",
    )
    p.add_argument(
        "--freezes",
        action="store_true",
        help="Also list freeze alerts",
    )
    args = p.parse_args()
    events = load_job_events(args.job_id)
    if not events:
        print(f"No Start In events found for job_id={args.job_id}")
        print("Expected file under logs/start_in/")
        return 1

    print(f"Job: {args.job_id}")
    print(f"Events: {len(events)}")
    print_onset(events)
    print("\nSync grid (timer value by wall-clock bucket):")
    print_sample_grid(events, bucket_seconds=max(1, int(args.bucket_seconds)))
    if args.freezes:
        print_freezes(events)
    else:
        # Always show freeze summary count
        n = sum(1 for e in events if e.get("event") == "START_IN_FREEZE")
        if n:
            print(f"\n({n} freeze alert(s) — re-run with --freezes to list)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
