"""
SQLite persistence for system notifications.
Additive observer/event layer — never affects bidding execution.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config_loader import BASE_DIR
from .depot_normalization import normalize_depot_name

_DB_PATH = BASE_DIR / "data" / "notifications.db"
_OUTCOMES_DB = BASE_DIR / "data" / "bid_outcomes.db"
_JOBS_DB = BASE_DIR / "data" / "jobs.db"
_LOCK = threading.Lock()

VALID_EVENT_TYPES = frozenset({
    "automation_started",
    "job_completed",
    "bid_won",
    "bid_lost",
    "execution_completed",
    "fleet_request_created",
    "fleet_request_approved",
    "fleet_request_rejected",
})

VALID_UI_TYPES = frozenset({"info", "success", "warning", "request"})

JOB_TERMINAL_STATUSES = frozenset({"completed", "failed", "partial_failed"})


def _db_path() -> Path:
    return _DB_PATH


def _connect(path: Optional[Path] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or _db_path()), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_db() -> None:
    """Create notifications.db and indexes (additive only)."""
    with _LOCK:
        _db_path().parent.mkdir(parents=True, exist_ok=True)
        conn = _connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'info',
                    job_id TEXT,
                    leg_id TEXT,
                    depot TEXT,
                    destination TEXT,
                    quantity REAL,
                    truck_number TEXT,
                    rank INTEGER,
                    read_at TEXT,
                    created_at TEXT NOT NULL,
                    source_key TEXT UNIQUE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notifications_created_at
                ON notifications (created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notifications_read_at
                ON notifications (read_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notifications_event_type
                ON notifications (event_type)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notifications_job_id
                ON notifications (job_id)
                """
            )
            conn.commit()
        finally:
            conn.close()


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "event_type": row["event_type"],
        "title": row["title"],
        "message": row["message"],
        "type": row["type"],
        "job_id": row["job_id"],
        "leg_id": row["leg_id"],
        "depot": row["depot"],
        "destination": row["destination"],
        "quantity": float(row["quantity"]) if row["quantity"] is not None else None,
        "truck_number": row["truck_number"],
        "rank": int(row["rank"]) if row["rank"] is not None else None,
        "read_at": row["read_at"],
        "created_at": row["created_at"],
        "is_read": row["read_at"] is not None,
    }


def insert_notification(
    *,
    event_type: str,
    title: str,
    message: str,
    type: str = "info",
    job_id: Optional[str] = None,
    leg_id: Optional[str] = None,
    depot: Optional[str] = None,
    destination: Optional[str] = None,
    quantity: Optional[float] = None,
    truck_number: Optional[str] = None,
    rank: Optional[int] = None,
    source_key: Optional[str] = None,
) -> Optional[str]:
    """
    Insert one notification (INSERT OR IGNORE when source_key is set).
    Returns new id if inserted, None on duplicate or failure. Never raises.
    """
    et = str(event_type or "").strip()
    if et not in VALID_EVENT_TYPES:
        return None
    ui_type = str(type or "info").strip().lower()
    if ui_type not in VALID_UI_TYPES:
        ui_type = "info"
    if not str(title or "").strip() or not str(message or "").strip():
        return None
    depot_norm = None
    if depot:
        depot_norm = normalize_depot_name(depot) or str(depot).strip().upper() or None
    try:
        init_db()
        notif_id = uuid.uuid4().hex[:16]
        ts = utc_now_iso()
        with _LOCK:
            conn = _connect()
            try:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO notifications (
                        id, event_type, title, message, type,
                        job_id, leg_id, depot, destination, quantity,
                        truck_number, rank, read_at, created_at, source_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        notif_id,
                        et,
                        str(title).strip(),
                        str(message).strip(),
                        ui_type,
                        job_id,
                        leg_id,
                        depot_norm,
                        (destination or "").strip() or None,
                        float(quantity) if quantity is not None else None,
                        (truck_number or "").strip() or None,
                        int(rank) if rank is not None else None,
                        ts,
                        source_key,
                    ),
                )
                conn.commit()
                if cur.rowcount == 0:
                    return None
                return notif_id
            finally:
                conn.close()
    except Exception:
        return None


def list_notifications(
    *,
    unread_only: bool = False,
    limit: Optional[int] = 100,
) -> Dict[str, Any]:
    """List notifications newest first."""
    clauses: List[str] = []
    params: List[Any] = []
    if unread_only:
        clauses.append("read_at IS NULL")
    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    limit_sql = ""
    if limit is not None and int(limit) > 0:
        limit_sql = " LIMIT ?"
        params.append(int(limit))
    sql = (
        "SELECT id, event_type, title, message, type, job_id, leg_id, depot, "
        "destination, quantity, truck_number, rank, read_at, created_at "
        f"FROM notifications{where_sql} "
        f"ORDER BY created_at DESC, id DESC{limit_sql}"
    )
    try:
        init_db()
        with _LOCK:
            conn = _connect()
            try:
                rows = conn.execute(sql, params).fetchall()
                unread_row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM notifications WHERE read_at IS NULL"
                ).fetchone()
            finally:
                conn.close()
        items = [_row_to_dict(r) for r in rows]
        unread_count = int(unread_row["cnt"]) if unread_row else 0
        return {"items": items, "total": len(items), "unread_count": unread_count}
    except Exception:
        return {"items": [], "total": 0, "unread_count": 0}


def mark_notification_read(notification_id: str) -> Tuple[bool, Optional[str]]:
    """Mark one notification as read. Returns (ok, error)."""
    if not str(notification_id or "").strip():
        return False, "notification id is required"
    try:
        init_db()
        ts = utc_now_iso()
        with _LOCK:
            conn = _connect()
            try:
                cur = conn.execute(
                    "UPDATE notifications SET read_at = ? WHERE id = ? AND read_at IS NULL",
                    (ts, notification_id),
                )
                conn.commit()
                if cur.rowcount == 0:
                    row = conn.execute(
                        "SELECT id FROM notifications WHERE id = ?", (notification_id,)
                    ).fetchone()
                    if row is None:
                        return False, "notification not found"
                return True, None
            finally:
                conn.close()
    except Exception as e:
        return False, str(e)


def mark_all_notifications_read() -> int:
    """Mark all unread notifications as read. Returns count updated. Never raises."""
    try:
        init_db()
        ts = utc_now_iso()
        with _LOCK:
            conn = _connect()
            try:
                cur = conn.execute(
                    "UPDATE notifications SET read_at = ? WHERE read_at IS NULL",
                    (ts,),
                )
                conn.commit()
                return int(cur.rowcount)
            finally:
                conn.close()
    except Exception:
        return 0


def delete_notification(notification_id: str) -> Tuple[bool, Optional[str]]:
    """Delete one notification."""
    if not str(notification_id or "").strip():
        return False, "notification id is required"
    try:
        init_db()
        with _LOCK:
            conn = _connect()
            try:
                cur = conn.execute(
                    "DELETE FROM notifications WHERE id = ?", (notification_id,)
                )
                conn.commit()
                if cur.rowcount == 0:
                    return False, "notification not found"
                return True, None
            finally:
                conn.close()
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Safe emitters (called from backend_server.py only)
# ---------------------------------------------------------------------------


def emit_automation_started(
    *,
    job_id: str,
    depots: Optional[List[str]] = None,
    desired_bids_count: int = 0,
) -> None:
    try:
        depot_label = ", ".join(depots) if depots else "AUTO"
        insert_notification(
            event_type="automation_started",
            title="Bidding Started",
            message=(
                f"Automation started for job {job_id[:8]}… "
                f"({desired_bids_count} leg(s), depots: {depot_label})"
            ),
            type="success",
            job_id=job_id,
            source_key=f"automation_started:{job_id}",
        )
    except Exception:
        pass


def emit_fleet_request_created(rec: Dict[str, Any]) -> None:
    try:
        req_type = str(rec.get("request_type") or "ACTION")
        depot = rec.get("depot_name") or rec.get("depotName") or ""
        tonnage = rec.get("tonnage")
        insert_notification(
            event_type="fleet_request_created",
            title=f"Fleet {req_type} Request",
            message=(
                f"Fleet user {rec.get('requested_by')} requested {req_type} "
                f"for {depot} {tonnage}T"
            ),
            type="request",
            job_id=rec.get("job_id"),
            leg_id=rec.get("leg_id"),
            depot=str(depot) if depot else None,
            destination=rec.get("destination"),
            quantity=float(tonnage) if tonnage is not None else None,
            truck_number=rec.get("truck_number"),
            source_key=f"fleet_request_created:{rec.get('id')}",
        )
    except Exception:
        pass


def emit_fleet_request_resolved(rec: Dict[str, Any], *, approved: bool) -> None:
    try:
        req_type = str(rec.get("request_type") or "ACTION")
        depot = rec.get("depot_name") or rec.get("depotName") or ""
        tonnage = rec.get("tonnage")
        event_type = "fleet_request_approved" if approved else "fleet_request_rejected"
        title = f"Fleet Request {'Approved' if approved else 'Rejected'}"
        resolver = rec.get("resolved_by") or "vendor"
        insert_notification(
            event_type=event_type,
            title=title,
            message=(
                f"{req_type} request for {depot} {tonnage}T was "
                f"{'approved' if approved else 'rejected'} by {resolver}"
            ),
            type="success" if approved else "warning",
            job_id=rec.get("job_id"),
            leg_id=rec.get("leg_id"),
            depot=str(depot) if depot else None,
            destination=rec.get("destination"),
            quantity=float(tonnage) if tonnage is not None else None,
            truck_number=rec.get("truck_number"),
            source_key=f"{event_type}:{rec.get('id')}",
        )
    except Exception:
        pass


def _read_outcomes() -> List[Dict[str, Any]]:
    """Read outcomes from MySQL if available, otherwise from SQLite file."""
    try:
        from .db import get_engine, get_bid_outcomes_table
        engine = get_engine()
        if engine:
            # MySQL path
            from sqlalchemy import select
            with engine.connect() as conn:
                table = get_bid_outcomes_table()
                stmt = select(table).order_by(table.c.completed_at.desc())
                rows = conn.execute(stmt).fetchall()
                return [dict(r) for r in rows]
    except Exception:
        pass
    
    # SQLite fallback
    if not _OUTCOMES_DB.exists():
        return []
    try:
        conn = _connect(_OUTCOMES_DB)
        try:
            rows = conn.execute(
                """
                SELECT outcome_id, leg_id, job_id, depot, destination, quantity,
                       rank, outcome_status, completed_at
                FROM bid_outcomes
                ORDER BY completed_at DESC
                """
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _read_terminal_jobs() -> List[Dict[str, Any]]:
    """Read terminal jobs from MySQL if available, otherwise from SQLite file."""
    try:
        from .db import get_engine, get_tables
        engine = get_engine()
        if engine:
            # MySQL path
            from sqlalchemy import select
            with engine.connect() as conn:
                _, _, jobs_table = get_tables()
                stmt = select(jobs_table).where(
                    jobs_table.c.status.in_(["completed", "failed", "partial_failed"])
                )
                rows = conn.execute(stmt).fetchall()
                out: List[Dict[str, Any]] = []
                for r in rows:
                    depots_raw = r.depots if hasattr(r, "depots") else r[3]
                    depots = json.loads(depots_raw) if depots_raw else []
                    out.append({
                        "job_id": r.job_id if hasattr(r, "job_id") else r[0],
                        "status": r.status if hasattr(r, "status") else r[1],
                        "truck_id": r.truck_id if hasattr(r, "truck_id") else r[2],
                        "depots": depots if isinstance(depots, list) else [],
                        "summary": r.summary if hasattr(r, "summary") else r[4],
                        "completed_at": r.completed_at if hasattr(r, "completed_at") else r[5],
                    })
                return out
    except Exception:
        pass
    
    # SQLite fallback
    if not _JOBS_DB.exists():
        return []
    try:
        conn = _connect(_JOBS_DB)
        try:
            rows = conn.execute(
                """
                SELECT job_id, status, truck_id, depots_json, summary, completed_at
                FROM bid_jobs
                WHERE status IN ('completed', 'failed', 'partial_failed')
                """
            ).fetchall()
        finally:
            conn.close()
        out: List[Dict[str, Any]] = []
        for r in rows:
            depots = json.loads(r["depots_json"] or "[]")
            out.append({
                "job_id": r["job_id"],
                "status": r["status"],
                "truck_id": r["truck_id"],
                "depots": depots if isinstance(depots, list) else [],
                "summary": r["summary"],
                "completed_at": r["completed_at"],
            })
        return out
    except Exception:
        return []


def _outcome_event_type(outcome_status: str) -> str:
    st = str(outcome_status or "").strip().lower()
    if st == "won":
        return "bid_won"
    if st == "lost":
        return "bid_lost"
    return "execution_completed"


def sync_notifications_from_outcomes() -> int:
    """
    Read-only observer on bid_outcomes.db.
    Creates notifications for outcomes not yet emitted. Never raises.
    """
    inserted = 0
    try:
        for row in _read_outcomes():
            outcome_id = str(row.get("outcome_id") or "")
            if not outcome_id:
                continue
            outcome_status = str(row.get("outcome_status") or "")
            event_type = _outcome_event_type(outcome_status)
            depot = row.get("depot") or ""
            qty = row.get("quantity")
            rank = row.get("rank")
            dest = row.get("destination") or ""

            if event_type == "bid_won":
                title = "Rank 1 Achieved"
                msg = f"Bid won at {depot} {qty}T" + (f" → {dest}" if dest else "")
                ui_type = "success"
            elif event_type == "bid_lost":
                title = "Bid Unsuccessful"
                msg = f"Bid completed at {depot} {qty}T with rank {rank or '—'}"
                ui_type = "warning"
            else:
                title = "Execution Completed"
                msg = (
                    f"Leg at {depot} {qty}T ended with status "
                    f"{outcome_status.upper()}"
                )
                ui_type = "info"

            nid = insert_notification(
                event_type=event_type,
                title=title,
                message=msg,
                type=ui_type,
                job_id=row.get("job_id"),
                leg_id=row.get("leg_id"),
                depot=str(depot) if depot else None,
                destination=str(dest) if dest else None,
                quantity=float(qty) if qty is not None else None,
                rank=int(rank) if rank is not None else None,
                source_key=f"outcome:{outcome_id}",
            )
            if nid:
                inserted += 1
    except Exception:
        pass
    return inserted


def sync_notifications_from_jobs() -> int:
    """
    Read-only observer on jobs.db for terminal job status.
    Never raises.
    """
    inserted = 0
    try:
        for job in _read_terminal_jobs():
            job_id = str(job.get("job_id") or "")
            if not job_id:
                continue
            status = str(job.get("status") or "")
            depots = job.get("depots") or []
            depot_label = ", ".join(str(d) for d in depots) if depots else job.get("truck_id", "")
            summary = (job.get("summary") or "").strip()
            if status == "completed":
                title = "Job Completed"
                ui_type = "success"
            elif status == "partial_failed":
                title = "Job Partially Failed"
                ui_type = "warning"
            else:
                title = "Job Failed"
                ui_type = "warning"
            msg = f"Job {job_id[:8]}… finished ({status})"
            if depot_label:
                msg += f" — depots: {depot_label}"
            if summary:
                msg += f". {summary[:200]}"

            nid = insert_notification(
                event_type="job_completed",
                title=title,
                message=msg,
                type=ui_type,
                job_id=job_id,
                depot=str(depots[0]) if depots else None,
                truck_number=str(job.get("truck_id") or "") or None,
                source_key=f"job_completed:{job_id}",
            )
            if nid:
                inserted += 1
    except Exception:
        pass
    return inserted


def sync_notifications_from_observers() -> Dict[str, int]:
    """Run all read-only observers. Never raises."""
    return {
        "outcomes": sync_notifications_from_outcomes(),
        "jobs": sync_notifications_from_jobs(),
    }
