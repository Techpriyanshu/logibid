"""
MySQL persistence for live bidding session state (one row per desired bid leg).
Cross-process safe via database locking. Isolated from Selenium / bidding engine logic.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, update, insert, select, text

from .config_loader import BASE_DIR
from .db import get_engine, get_live_bids_table
from .depot_normalization import normalize_depot_name

_LOCK = threading.Lock()

USER_CONTROL_ACTIVE = "active"
USER_CONTROL_PAUSED = "paused"
USER_CONTROL_STOPPED = "stopped"
USER_CONTROL_RUNNING = "active"

TERMINAL_STATUSES = frozenset({"won", "completed", "stopped", "orphaned"})


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


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_db() -> None:
    """Initialize MySQL connection if not already done."""
    engine = get_engine()
    if engine is None:
        from .db import init_db
        init_db()


def _row_to_dict(row) -> Dict[str, Any]:
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


def mark_stopped(job_id: str, depot: str, quantity: float, destination: Optional[str] = None) -> bool:
    """Mark a bid leg as stopped (user clicked Stop). Never raises."""
    if not job_id:
        return False
    try:
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
    except Exception:
        return False


def register_job_legs(job_id: str, desired_bids: List[dict]) -> int:
    """Insert one row per desired bid at job start. Returns count of newly inserted rows. Never raises."""
    if not job_id or not desired_bids:
        return 0
    inserted = 0
    try:
        init_db()
        ts = utc_now_iso()
        engine = get_engine()
        if engine is None:
            return inserted
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
                    except Exception:
                        pass  # Row already exists, ignore
                conn.commit()
    except Exception:
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
    try:
        init_db()
        ts = utc_now_iso()
        engine = get_engine()
        if engine is None:
            return False
        with _LOCK:
            with engine.begin() as conn:
                stmt = (
                    update(get_live_bids_table())
                    .where(get_live_bids_table().c.id == leg_id)
                    .values(
                        user_control=control,
                        status=status_map[control],
                        updated_at=ts
                    )
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
    except Exception:
        return False


def mark_orphaned(job_id: str, depot: str, quantity: float, destination: Optional[str] = None) -> bool:
    """Mark a bid leg as orphaned (browser closed unexpectedly). Never raises."""
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
        return _row_to_dict(row) if row else None
    except Exception:
        return None


def list_live_bids(
    *,
    job_id: Optional[str] = None,
    active_only: bool = False,
) -> Dict[str, Any]:
    """List live bid rows. Optional job_id filter. active_only excludes terminal statuses."""
    engine = get_engine()
    if engine is None:
        return {"items": [], "total": 0}
    
    clauses = []
    if job_id:
        clauses.append(get_live_bids_table().c.job_id == job_id)
    if active_only:
        clauses.append(~get_live_bids_table().c.status.in_(TERMINAL_STATUSES))
    
    with _LOCK:
        with engine.connect() as conn:
            stmt = select(
                get_live_bids_table().c.id,
                get_live_bids_table().c.job_id,
                get_live_bids_table().c.depot,
                get_live_bids_table().c.destination,
                get_live_bids_table().c.quantity,
                get_live_bids_table().c.organization_name,
                get_live_bids_table().c.current_rank,
                get_live_bids_table().c.status,
                get_live_bids_table().c.won_timestamp,
                get_live_bids_table().c.user_control,
                get_live_bids_table().c.updated_at
            )
            if clauses:
                stmt = stmt.where(and_(*clauses))
            stmt = stmt.order_by(
                get_live_bids_table().c.depot.asc(),
                get_live_bids_table().c.quantity.asc(),
                get_live_bids_table().c.destination.asc()
            )
            rows = conn.execute(stmt).fetchall()
    
    items = [_row_to_dict(r) for r in rows]
    return {"items": items, "total": len(items)}


def get_live_db():
    """Return a database connection for direct SQL operations."""
    return get_engine()
