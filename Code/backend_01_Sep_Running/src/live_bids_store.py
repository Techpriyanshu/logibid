"""
Mixed persistence for live bidding session state (one row per desired bid leg).
Cross-process safe. Isolated from Selenium / bidding engine logic.
Uses SQLite by default. MySQL is used when DATABASE_URL is set and NOT sqlite://.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select, update

from .config_loader import BASE_DIR
from .db import get_engine, get_live_bids_table, DATABASE_URL
from .depot_normalization import normalize_depot_name
from .logging_service import get_logger

logger = get_logger("live_bids_store")

_DB_PATH = BASE_DIR / "data" / "live_bids.db"
_LOCK = threading.Lock()

# Check if MySQL is configured (lazy evaluation)
_USE_SQLITE = None


def _use_sqlite() -> bool:
    """Lazy check if MySQL is configured. Avoids DB init at module import."""
    global _USE_SQLITE
    if _USE_SQLITE is None:
        from .db import init_db as mysql_init
        mysql_init()  # Call init_db to ensure DATABASE_URL is set
        _USE_SQLITE = bool(DATABASE_URL and DATABASE_URL.startswith("sqlite://"))
    return _USE_SQLITE

USER_CONTROL_ACTIVE = "active"
USER_CONTROL_PAUSED = "paused"
USER_CONTROL_STOPPED = "stopped"
USER_CONTROL_RUNNING = "active"  # Alias for 'active' - used when restarting bids

TERMINAL_STATUSES = frozenset({"won", "completed", "stopped", "orphaned"})


def mark_stopped(job_id: str, depot: str, quantity: float, destination: Optional[str] = None) -> bool:
    """Mark a bid leg as stopped (user clicked Stop). Never raises."""
    if not job_id:
        return False
    try:
        if not _use_sqlite():
            return _mark_stopped_mysql(job_id, depot, quantity, destination)
        return _mark_stopped_sqlite(job_id, depot, quantity, destination)
    except Exception:
        return False


def _mark_stopped_sqlite(job_id: str, depot: str, quantity: float, destination: Optional[str] = None) -> bool:
    """SQLite implementation for mark_stopped."""
    depot_norm = normalize_depot_name(depot) or str(depot or "").strip().upper()
    dest = _normalize_destination(destination)
    leg_id = make_leg_id(job_id, depot_norm, quantity, dest)
    ts = utc_now_iso()
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                """
                UPDATE live_bids
                SET status = ?, user_control = ?, updated_at = ?
                WHERE id = ?
                """,
                ("stopped", USER_CONTROL_STOPPED, ts, leg_id),
            )
            conn.commit()
            # Log the stop action
            logger = logging.getLogger("live_bids_store")
            logger.info(
                "STOPPED job_id=%s depot=%s qty=%s dest=%s leg_id=%s",
                job_id,
                depot_norm,
                quantity,
                dest,
                leg_id,
            )
            return cur.rowcount > 0
        finally:
            conn.close()


def _mark_stopped_mysql(job_id: str, depot: str, quantity: float, destination: Optional[str] = None) -> bool:
    """MySQL implementation for mark_stopped."""
    depot_norm = normalize_depot_name(depot) or str(depot or "").strip().upper()
    dest = _normalize_destination(destination)
    leg_id = make_leg_id(job_id, depot_norm, quantity, dest)
    ts = utc_now_iso()
    engine = get_engine()
    if engine is None:
        return False
    with _LOCK:
        with engine.begin() as conn:
            from sqlalchemy import update
            stmt = (
                update(get_live_bids_table())
                .where(get_live_bids_table().c.id == leg_id)
                .values(status="stopped", user_control=USER_CONTROL_STOPPED, updated_at=ts)
            )
            result = conn.execute(stmt)
            conn.commit()
            logger = logging.getLogger("live_bids_store")
            logger.info(
                "STOPPED job_id=%s depot=%s qty=%s dest=%s leg_id=%s",
                job_id,
                depot_norm,
                quantity,
                dest,
                leg_id,
            )
            return result.rowcount > 0


def _db_path() -> Path:
    return _DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_destination(destination: Optional[str]) -> Optional[str]:
    if destination is None:
        return None
    s = str(destination).strip()
    return s or None


def make_leg_id(
    job_id: str,
    depot: str,
    quantity: float,
    destination: Optional[str] = None,
) -> str:
    """Deterministic id: one row per job + depot + quantity + destination."""
    depot_norm = normalize_depot_name(depot) or str(depot or "").strip().upper()
    dest_norm = (_normalize_destination(destination) or "").upper()
    key = f"{job_id}|{depot_norm}|{float(quantity):.4f}|{dest_norm}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def init_db() -> None:
    """Initialize database - create tables if MySQL, or ensure SQLite exists."""
    if not _use_sqlite():
        _init_db_mysql()
    else:
        _init_db_sqlite()


def _init_db_sqlite() -> None:
    """SQLite implementation for init_db."""
    with _LOCK:
        _db_path().parent.mkdir(parents=True, exist_ok=True)
        conn = _connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS live_bids (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    depot TEXT NOT NULL,
                    destination TEXT,
                    quantity REAL NOT NULL,
                    organization_name TEXT,
                    current_rank INTEGER,
                    status TEXT NOT NULL DEFAULT 'monitoring',
                    won_timestamp TEXT,
                    user_control TEXT NOT NULL DEFAULT 'active',
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_live_bids_job_id
                ON live_bids (job_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_live_bids_status
                ON live_bids (status)
                """
            )
            conn.commit()
        finally:
            conn.close()


def _init_db_mysql() -> None:
    """MySQL implementation for init_db."""
    engine = get_engine()  # This will call init_db() if engine is None
    if engine is None:
        return  # init_db() failed


def register_job_legs(job_id: str, desired_bids: List[dict]) -> int:
    """
    Insert one row per desired bid at job start (INSERT OR IGNORE).
    Returns count of newly inserted rows. Never raises.
    """
    if not job_id or not desired_bids:
        logger.debug("register_job_legs: job_id=%s desired_bids_count=%s", job_id, len(desired_bids or []))
        return 0
    logger.info("register_job_legs: job_id=%s desired_bids_count=%s", job_id, len(desired_bids or []))
    if not _use_sqlite():
        return _register_job_legs_mysql(job_id, desired_bids)
    return _register_job_legs_sqlite(job_id, desired_bids)


def _register_job_legs_sqlite(job_id: str, desired_bids: List[dict]) -> int:
    """SQLite implementation for register_job_legs."""
    if not job_id or not desired_bids:
        return 0
    inserted = 0
    try:
        init_db()
        ts = utc_now_iso()
        with _LOCK:
            conn = _connect()
            try:
                for b in desired_bids:
                    qty = float(b.get("quantity", 0) or 0)
                    if qty <= 0:
                        continue
                    raw_depot = b.get("depot")
                    depot_norm = (
                        normalize_depot_name(str(raw_depot))
                        if raw_depot is not None and str(raw_depot).strip()
                        else ""
                    )
                    if not depot_norm:
                        continue
                    dest = _normalize_destination(b.get("destination"))
                    leg_id = make_leg_id(job_id, depot_norm, qty, dest)
                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO live_bids
                            (id, job_id, depot, destination, quantity, status,
                             user_control, updated_at)
                        VALUES (?, ?, ?, ?, ?, 'monitoring', 'active', ?)
                        """,
                        (leg_id, job_id, depot_norm, dest, qty, ts),
                    )
                    if cur.rowcount > 0:
                        inserted += 1
                conn.commit()
            finally:
                conn.close()
    except Exception:
        return inserted
    return inserted


def _register_job_legs_mysql(job_id: str, desired_bids: List[dict]) -> int:
    """MySQL implementation for register_job_legs."""
    if not job_id or not desired_bids:
        return 0
    inserted = 0
    try:
        init_db()
        ts = utc_now_iso()
        engine = get_engine()
        if engine is None:
            logger.error("_register_job_legs_mysql: engine is None")
            return inserted
        logger.debug("_register_job_legs_mysql: inserting %s legs for job_id=%s", len(desired_bids), job_id)
        with _LOCK:
            with engine.begin() as conn:
                for b in desired_bids:
                    qty = float(b.get("quantity", 0) or 0)
                    if qty <= 0:
                        continue
                    raw_depot = b.get("depot")
                    depot_norm = (
                        normalize_depot_name(str(raw_depot))
                        if raw_depot is not None and str(raw_depot).strip()
                        else ""
                    )
                    if not depot_norm:
                        continue
                    dest = _normalize_destination(b.get("destination"))
                    leg_id = make_leg_id(job_id, depot_norm, qty, dest)
                    from sqlalchemy import insert
                    stmt = insert(get_live_bids_table()).values(
                        id=leg_id,
                        job_id=job_id,
                        depot=depot_norm,
                        destination=dest,
                        quantity=qty,
                        status="monitoring",
                        user_control="active",
                        updated_at=ts
                    )
                    try:
                        conn.execute(stmt)
                        inserted += 1
                        logger.debug("_register_job_legs_mysql: inserted leg_id=%s job_id=%s depot=%s qty=%s", leg_id, job_id, depot_norm, qty)
                    except Exception as insert_err:
                        logger.debug("_register_job_legs_mysql: leg_id=%s already exists error=%s", leg_id, str(insert_err))
                conn.commit()
        logger.info("_register_job_legs_mysql: completed job_id=%s inserted=%s", job_id, inserted)
    except Exception as e:
        logger.exception("_register_job_legs_mysql failed for job_id=%s error=%s", job_id, str(e))
        return inserted
    return inserted


def get_user_control(
    job_id: str,
    depot: str,
    quantity: float,
    destination: Optional[str] = None,
) -> str:
    """Return user_control for a leg, or 'active' if unknown. Never raises."""
    if not job_id:
        return USER_CONTROL_ACTIVE
    if not _use_sqlite():
        return _get_user_control_mysql(job_id, depot, quantity, destination)
    return _get_user_control_sqlite(job_id, depot, quantity, destination)


def _get_user_control_sqlite(job_id: str, depot: str, quantity: float, destination: Optional[str] = None) -> str:
    """SQLite implementation for get_user_control."""
    if not job_id:
        return USER_CONTROL_ACTIVE
    try:
        init_db()
        leg_id = make_leg_id(job_id, depot, quantity, destination)
        with _LOCK:
            conn = _connect()
            try:
                row = conn.execute(
                    "SELECT user_control FROM live_bids WHERE id = ?",
                    (leg_id,),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return USER_CONTROL_ACTIVE
        val = str(row["user_control"] or USER_CONTROL_ACTIVE).strip().lower()
        if val in (USER_CONTROL_PAUSED, USER_CONTROL_STOPPED):
            return val
        return USER_CONTROL_ACTIVE
    except Exception:
        return USER_CONTROL_ACTIVE


def _get_user_control_mysql(job_id: str, depot: str, quantity: float, destination: Optional[str] = None) -> str:
    """MySQL implementation for get_user_control."""
    if not job_id:
        return USER_CONTROL_ACTIVE
    try:
        init_db()
        leg_id = make_leg_id(job_id, depot, quantity, destination)
        engine = get_engine()
        if engine is None:
            return USER_CONTROL_ACTIVE
        with _LOCK:
            with engine.connect() as conn:
                stmt = select(get_live_bids_table().c.user_control).where(
                    get_live_bids_table().c.id == leg_id
                )
                row = conn.execute(stmt).fetchone()
        if row is None:
            return USER_CONTROL_ACTIVE
        val = str(row.user_control or USER_CONTROL_ACTIVE).strip().lower()
        if val in (USER_CONTROL_PAUSED, USER_CONTROL_STOPPED):
            return val
        return USER_CONTROL_ACTIVE
    except Exception:
        return USER_CONTROL_ACTIVE


def update_live_bid(
    job_id: str,
    depot: str,
    quantity: float,
    destination: Optional[str] = None,
    *,
    status: Optional[str] = None,
    organization_name: Optional[str] = None,
    current_rank: Optional[int] = None,
    won_timestamp: Optional[str] = None,
    user_control: Optional[str] = None,
) -> bool:
    """Update fields for one leg. Never raises."""
    if not job_id:
        return False
    if not _use_sqlite():
        return _update_live_bid_mysql(job_id, depot, quantity, destination, status=status,
                                      organization_name=organization_name, current_rank=current_rank,
                                      won_timestamp=won_timestamp, user_control=user_control)
    return _update_live_bid_sqlite(job_id, depot, quantity, destination, status=status,
                                   organization_name=organization_name, current_rank=current_rank,
                                   won_timestamp=won_timestamp, user_control=user_control)


def _update_live_bid_sqlite(job_id: str, depot: str, quantity: float, destination: Optional[str] = None,
                            *, status: Optional[str] = None, organization_name: Optional[str] = None,
                            current_rank: Optional[int] = None, won_timestamp: Optional[str] = None,
                            user_control: Optional[str] = None) -> bool:
    """SQLite implementation for update_live_bid."""
    if not job_id:
        return False
    try:
        init_db()
        depot_norm = normalize_depot_name(depot) or str(depot or "").strip().upper()
        dest = _normalize_destination(destination)
        leg_id = make_leg_id(job_id, depot_norm, quantity, dest)
        ts = utc_now_iso()
        sets: List[str] = ["updated_at = ?"]
        params: List[Any] = [ts]
        if status is not None:
            sets.append("status = ?")
            params.append(str(status))
        if organization_name is not None:
            sets.append("organization_name = ?")
            params.append(organization_name or None)
        if current_rank is not None:
            sets.append("current_rank = ?")
            params.append(int(current_rank))
        if won_timestamp is not None:
            sets.append("won_timestamp = ?")
            params.append(won_timestamp)
        if user_control is not None:
            sets.append("user_control = ?")
            params.append(str(user_control))
        params.append(leg_id)
        sql = f"UPDATE live_bids SET {', '.join(sets)} WHERE id = ?"
        with _LOCK:
            conn = _connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()
    except Exception:
        return False


def _update_live_bid_mysql(job_id: str, depot: str, quantity: float, destination: Optional[str] = None,
                           *, status: Optional[str] = None, organization_name: Optional[str] = None,
                           current_rank: Optional[int] = None, won_timestamp: Optional[str] = None,
                           user_control: Optional[str] = None) -> bool:
    """MySQL implementation for update_live_bid."""
    if not job_id:
        return False
    try:
        init_db()
        depot_norm = normalize_depot_name(depot) or str(depot or "").strip().upper()
        dest = _normalize_destination(destination)
        leg_id = make_leg_id(job_id, depot_norm, quantity, dest)
        ts = utc_now_iso()
        engine = get_engine()
        if engine is None:
            return False
        with _LOCK:
            with engine.begin() as conn:
                updates = {"updated_at": ts}
                if status is not None:
                    updates["status"] = str(status)
                if organization_name is not None:
                    updates["organization_name"] = organization_name or None
                if current_rank is not None:
                    updates["current_rank"] = int(current_rank)
                if won_timestamp is not None:
                    updates["won_timestamp"] = won_timestamp
                if user_control is not None:
                    updates["user_control"] = str(user_control)
                
                stmt = (
                    update(get_live_bids_table())
                    .where(get_live_bids_table().c.id == leg_id)
                    .values(**updates)
                )
                result = conn.execute(stmt)
                conn.commit()
                return result.rowcount > 0
    except Exception:
        return False


def set_user_control(leg_id: str, control: str) -> bool:
    """Set pause/resume/stop on a leg by id. Never raises."""
    control = str(control or "").strip().lower()
    if control not in (USER_CONTROL_ACTIVE, USER_CONTROL_PAUSED, USER_CONTROL_STOPPED):
        return False
    status_map = {
        USER_CONTROL_ACTIVE: "monitoring",
        USER_CONTROL_PAUSED: "paused",
        USER_CONTROL_STOPPED: "stopped",
    }
    if not _use_sqlite():
        return _set_user_control_mysql(leg_id, control, status_map)
    return _set_user_control_sqlite(leg_id, control, status_map)


def _set_user_control_sqlite(leg_id: str, control: str, status_map: dict) -> bool:
    """SQLite implementation for set_user_control."""
    ts = utc_now_iso()
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                """
                UPDATE live_bids
                SET user_control = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (control, status_map[control], ts, leg_id),
            )
            conn.commit()
            # Log the user_control change
            logger = logging.getLogger("live_bids_store")
            logger.info(
                "USER_CONTROL leg_id=%s control=%s status=%s",
                leg_id,
                control,
                status_map[control],
            )
            return cur.rowcount > 0
        finally:
            conn.close()


def _set_user_control_mysql(leg_id: str, control: str, status_map: dict) -> bool:
    """MySQL implementation for set_user_control."""
    ts = utc_now_iso()
    engine = get_engine()
    if engine is None:
        return False
    with _LOCK:
        with engine.begin() as conn:
            stmt = (
                update(get_live_bids_table())
                .where(get_live_bids_table().c.id == leg_id)
                .values(user_control=control, status=status_map[control], updated_at=ts)
            )
            result = conn.execute(stmt)
            conn.commit()
            logger = logging.getLogger("live_bids_store")
            logger.info(
                "USER_CONTROL leg_id=%s control=%s status=%s",
                leg_id,
                control,
                status_map[control],
            )
            return result.rowcount > 0


def mark_orphaned(job_id: str, depot: str, quantity: float, destination: Optional[str] = None) -> bool:
    """Mark a bid leg as orphaned (browser closed unexpectedly). Never raises."""
    if not job_id:
        return False
    if not _use_sqlite():
        return _mark_orphaned_mysql(job_id, depot, quantity, destination)
    return _mark_orphaned_sqlite(job_id, depot, quantity, destination)


def _mark_orphaned_sqlite(job_id: str, depot: str, quantity: float, destination: Optional[str] = None) -> bool:
    """SQLite implementation for mark_orphaned."""
    if not job_id:
        return False
    try:
        init_db()
        depot_norm = normalize_depot_name(depot) or str(depot or "").strip().upper()
        dest = _normalize_destination(destination)
        leg_id = make_leg_id(job_id, depot_norm, quantity, dest)
        ts = utc_now_iso()
        with _LOCK:
            conn = _connect()
            try:
                cur = conn.execute(
                    """
                    UPDATE live_bids
                    SET status = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    ("orphaned", ts, leg_id),
                )
                conn.commit()
                # Log the orphaned action
                logger = logging.getLogger("live_bids_store")
                logger.info(
                    "ORPHANED job_id=%s depot=%s qty=%s dest=%s leg_id=%s",
                    job_id,
                    depot_norm,
                    quantity,
                    dest,
                    leg_id,
                )
                return cur.rowcount > 0
            finally:
                conn.close()
    except Exception:
        return False


def _mark_orphaned_mysql(job_id: str, depot: str, quantity: float, destination: Optional[str] = None) -> bool:
    """MySQL implementation for mark_orphaned."""
    if not job_id:
        return False
    try:
        init_db()
        depot_norm = normalize_depot_name(depot) or str(depot or "").strip().upper()
        dest = _normalize_destination(destination)
        leg_id = make_leg_id(job_id, depot_norm, quantity, dest)
        ts = utc_now_iso()
        engine = get_engine()
        if engine is None:
            return False
        with _LOCK:
            with engine.begin() as conn:
                stmt = (
                    update(get_live_bids_table())
                    .where(get_live_bids_table().c.id == leg_id)
                    .values(status="orphaned", updated_at=ts)
                )
                result = conn.execute(stmt)
                conn.commit()
                logger = logging.getLogger("live_bids_store")
                logger.info(
                    "ORPHANED job_id=%s depot=%s qty=%s dest=%s leg_id=%s",
                    job_id,
                    depot_norm,
                    quantity,
                    dest,
                    leg_id,
                )
                return result.rowcount > 0
    except Exception:
        return False


def get_live_bid(leg_id: str) -> Optional[Dict[str, Any]]:
    """Fetch one leg by id. Never raises."""
    if not _use_sqlite():
        return _get_live_bid_mysql(leg_id)
    return _get_live_bid_sqlite(leg_id)


def _get_live_bid_sqlite(leg_id: str) -> Optional[Dict[str, Any]]:
    """SQLite implementation for get_live_bid."""
    try:
        init_db()
        with _LOCK:
            conn = _connect()
            try:
                row = conn.execute(
                    "SELECT * FROM live_bids WHERE id = ?", (leg_id,)
                ).fetchone()
            finally:
                conn.close()
        return _row_to_dict(row) if row else None
    except Exception:
        return None


def _get_live_bid_mysql(leg_id: str) -> Optional[Dict[str, Any]]:
    """MySQL implementation for get_live_bid."""
    try:
        init_db()
        engine = get_engine()
        if engine is None:
            return None
        with _LOCK:
            with engine.connect() as conn:
                stmt = select(get_live_bids_table()).where(
                    get_live_bids_table().c.id == leg_id
                )
                row = conn.execute(stmt).fetchone()
        return _row_to_dict_mysql(row) if row else None
    except Exception:
        return None


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "depot": row["depot"],
        "destination": row["destination"],
        "quantity": float(row["quantity"]),
        "organization_name": row["organization_name"],
        "current_rank": int(row["current_rank"]) if row["current_rank"] is not None else None,
        "status": row["status"],
        "won_timestamp": row["won_timestamp"],
        "user_control": row["user_control"],
        "updated_at": row["updated_at"],
    }


def _row_to_dict_mysql(row) -> Dict[str, Any]:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "depot": row.depot,
        "destination": row.destination,
        "quantity": float(row.quantity) if row.quantity is not None else 0.0,
        "organization_name": row.organization_name,
        "current_rank": int(row.current_rank) if row.current_rank is not None else None,
        "status": row.status,
        "won_timestamp": row.won_timestamp,
        "user_control": row.user_control,
        "updated_at": row.updated_at,
    }


def list_live_bids(
    *,
    job_id: Optional[str] = None,
    active_only: bool = False,
) -> Dict[str, Any]:
    """List live bid rows. Optional job_id filter. active_only excludes terminal statuses."""
    if not _use_sqlite():
        return _list_live_bids_mysql(job_id=job_id, active_only=active_only)
    return _list_live_bids_sqlite(job_id=job_id, active_only=active_only)


def _list_live_bids_sqlite(
    *,
    job_id: Optional[str] = None,
    active_only: bool = False,
) -> Dict[str, Any]:
    """SQLite implementation for list_live_bids."""
    clauses: List[str] = []
    params: List[Any] = []
    if job_id:
        clauses.append("job_id = ?")
        params.append(job_id)
    if active_only:
        placeholders = ",".join("?" for _ in TERMINAL_STATUSES)
        clauses.append(f"status NOT IN ({placeholders})")
        params.extend(TERMINAL_STATUSES)
    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        "SELECT id, job_id, depot, destination, quantity, organization_name, "
        f"current_rank, status, won_timestamp, user_control, updated_at "
        f"FROM live_bids{where_sql} "
        "ORDER BY depot ASC, quantity ASC, destination ASC"
    )
    try:
        init_db()
        with _LOCK:
            conn = _connect()
            try:
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        items = [_row_to_dict(r) for r in rows]
        return {"items": items, "total": len(items)}
    except Exception:
        return {"items": [], "total": 0}


def _list_live_bids_mysql(
    *,
    job_id: Optional[str] = None,
    active_only: bool = False,
) -> Dict[str, Any]:
    """MySQL implementation for list_live_bids."""
    engine = get_engine()
    if engine is None:
        return {"items": [], "total": 0}
    
    bids_table = get_live_bids_table()
    clauses = []
    if job_id:
        clauses.append(bids_table.c.job_id == job_id)
    if active_only:
        clauses.append(~bids_table.c.status.in_(TERMINAL_STATUSES))
    
    with _LOCK:
        with engine.connect() as conn:
            cols = [
                bids_table.c.id,
                bids_table.c.job_id,
                bids_table.c.depot,
                bids_table.c.destination,
                bids_table.c.quantity,
                bids_table.c.organization_name,
                bids_table.c.current_rank,
                bids_table.c.status,
                bids_table.c.won_timestamp,
                bids_table.c.user_control,
                bids_table.c.updated_at
            ]
            stmt = select(*cols)
            if clauses:
                from sqlalchemy import and_
                stmt = stmt.where(and_(*clauses))
            stmt = stmt.order_by(
                bids_table.c.depot.asc(),
                bids_table.c.quantity.asc(),
                bids_table.c.destination.asc()
            )
            rows = conn.execute(stmt).fetchall()
    
    items = [_row_to_dict_mysql(r) for r in rows]
    return {"items": items, "total": len(items)}


def get_live_db():
    """Return a database connection for direct SQL operations."""
    if not _use_sqlite():
        return get_engine()
    return _connect()
