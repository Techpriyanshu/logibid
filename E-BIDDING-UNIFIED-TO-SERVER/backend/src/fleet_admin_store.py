"""
Mixed persistence for Fleet Admin daily operations and control requests.
Uses SQLite by default. MySQL is used when DATABASE_URL is set and NOT sqlite://.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, insert, update, and_

from .config_loader import BASE_DIR
from .db import get_engine, DATABASE_URL
from .live_bids_store import USER_CONTROL_PAUSED, USER_CONTROL_STOPPED, set_user_control
from .truck_master_store import make_truck_id, normalize_truck_number

_DB_PATH = BASE_DIR / "data" / "fleet_admin.db"
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

VALID_DAILY_STATUSES = frozenset({"Available", "In Trip", "Non-Active"})
VALID_REQUEST_TYPES = frozenset({"PAUSE", "CLOSE"})
VALID_REQUEST_STATUSES = frozenset({"Pending", "Approved", "Rejected"})


def _db_path() -> Path:
    return _DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_db() -> None:
    with _LOCK:
        _db_path().parent.mkdir(parents=True, exist_ok=True)
        conn = _connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fleet_daily_entries (
                    id TEXT PRIMARY KEY,
                    business_date TEXT NOT NULL,
                    truck_id TEXT,
                    truck_number TEXT NOT NULL,
                    driver_name TEXT NOT NULL DEFAULT '',
                    tonnage TEXT NOT NULL,
                    previous_depot TEXT,
                    current_depot TEXT NOT NULL,
                    destination TEXT,
                    status TEXT NOT NULL,
                    remarks TEXT,
                    available_since TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE (business_date, truck_number)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fleet_daily_date
                ON fleet_daily_entries (business_date)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fleet_control_requests (
                    id TEXT PRIMARY KEY,
                    leg_id TEXT NOT NULL,
                    job_id TEXT,
                    truck_number TEXT,
                    request_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Pending',
                    depot_name TEXT,
                    destination TEXT,
                    tonnage REAL,
                    plant_name TEXT,
                    requested_by TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    resolved_by TEXT,
                    resolved_at TEXT,
                    remarks TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fleet_requests_status
                ON fleet_control_requests (status)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fleet_requests_leg_id
                ON fleet_control_requests (leg_id)
                """
            )
            conn.commit()
        finally:
            conn.close()


def _daily_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "business_date": row["business_date"],
        "truck_id": row["truck_id"],
        "truck_number": row["truck_number"],
        "driver_name": row["driver_name"],
        "tonnage": row["tonnage"],
        "previous_depot": row["previous_depot"],
        "current_depot": row["current_depot"],
        "destination": row["destination"],
        "status": row["status"],
        "remarks": row["remarks"],
        "available_since": row["available_since"],
        "updated_at": row["updated_at"],
    }


def _request_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "leg_id": row["leg_id"],
        "job_id": row["job_id"],
        "truck_number": row["truck_number"],
        "request_type": row["request_type"],
        "status": row["status"],
        "depot_name": row["depot_name"],
        "destination": row["destination"],
        "tonnage": float(row["tonnage"]) if row["tonnage"] is not None else None,
        "plant_name": row["plant_name"],
        "requested_by": row["requested_by"],
        "requested_at": row["requested_at"],
        "resolved_by": row["resolved_by"],
        "resolved_at": row["resolved_at"],
        "remarks": row["remarks"],
        # Frontend-compatible aliases
        "bidId": row["leg_id"],
        "vehicleId": row["leg_id"],
        "requestType": row["request_type"],
        "depotName": row["depot_name"],
        "requestedBy": row["requested_by"],
        "requestedAt": row["requested_at"],
    }


def list_fleet_daily(*, business_date: Optional[str] = None) -> Dict[str, Any]:
    try:
        init_db()
        clauses: List[str] = []
        params: List[Any] = []
        if business_date:
            clauses.append("business_date = ?")
            params.append(str(business_date).strip())
        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with _LOCK:
            conn = _connect()
            try:
                rows = conn.execute(
                    f"""
                    SELECT id, business_date, truck_id, truck_number, driver_name, tonnage,
                           previous_depot, current_depot, destination, status, remarks,
                           available_since, updated_at
                    FROM fleet_daily_entries
                    {where_sql}
                    ORDER BY truck_number ASC
                    """,
                    params,
                ).fetchall()
            finally:
                conn.close()
        items = [_daily_row_to_dict(r) for r in rows]
        return {"items": items, "total": len(items)}
    except Exception:
        return {"items": [], "total": 0}


def get_fleet_daily_entry(entry_id: str) -> Optional[Dict[str, Any]]:
    try:
        init_db()
        with _LOCK:
            conn = _connect()
            try:
                row = conn.execute(
                    """
                    SELECT id, business_date, truck_id, truck_number, driver_name, tonnage,
                           previous_depot, current_depot, destination, status, remarks,
                           available_since, updated_at
                    FROM fleet_daily_entries WHERE id = ?
                    """,
                    (entry_id,),
                ).fetchone()
            finally:
                conn.close()
        return _daily_row_to_dict(row) if row else None
    except Exception:
        return None


def create_fleet_daily_entry(
    *,
    business_date: str,
    truck_number: str,
    driver_name: str = "",
    tonnage: str,
    previous_depot: str = "",
    current_depot: str,
    destination: str = "",
    status: str = "Available",
    remarks: str = "",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    norm = normalize_truck_number(truck_number)
    if not norm:
        return None, "truck_number is required"
    if not str(current_depot or "").strip():
        return None, "current_depot is required"
    if not str(tonnage or "").strip():
        return None, "tonnage is required"
    if status not in VALID_DAILY_STATUSES:
        return None, f"status must be one of: {', '.join(sorted(VALID_DAILY_STATUSES))}"
    try:
        init_db()
        entry_id = uuid.uuid4().hex[:16]
        truck_id = make_truck_id(norm)
        ts = utc_now_iso()
        available_since = ts if status == "Available" else None
        with _LOCK:
            conn = _connect()
            try:
                dup = conn.execute(
                    """
                    SELECT id FROM fleet_daily_entries
                    WHERE business_date = ? AND truck_number = ?
                    """,
                    (business_date, norm),
                ).fetchone()
                if dup is not None:
                    return None, "truck_number already has an entry for this date"
                conn.execute(
                    """
                    INSERT INTO fleet_daily_entries (
                        id, business_date, truck_id, truck_number, driver_name, tonnage,
                        previous_depot, current_depot, destination, status, remarks,
                        available_since, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry_id,
                        business_date,
                        truck_id,
                        norm,
                        str(driver_name or "").strip(),
                        str(tonnage).strip(),
                        str(previous_depot or "").strip() or None,
                        str(current_depot).strip(),
                        str(destination or "").strip() or None,
                        status,
                        str(remarks or "").strip() or None,
                        available_since,
                        ts,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return get_fleet_daily_entry(entry_id), None
    except Exception as e:
        return None, str(e)


def update_fleet_daily_entry(
    entry_id: str,
    *,
    driver_name: Optional[str] = None,
    tonnage: Optional[str] = None,
    previous_depot: Optional[str] = None,
    current_depot: Optional[str] = None,
    destination: Optional[str] = None,
    status: Optional[str] = None,
    remarks: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if status is not None and status not in VALID_DAILY_STATUSES:
        return None, f"status must be one of: {', '.join(sorted(VALID_DAILY_STATUSES))}"
    try:
        init_db()
        ts = utc_now_iso()
        sets: List[str] = ["updated_at = ?"]
        params: List[Any] = [ts]
        if driver_name is not None:
            sets.append("driver_name = ?")
            params.append(str(driver_name).strip())
        if tonnage is not None:
            sets.append("tonnage = ?")
            params.append(str(tonnage).strip())
        if previous_depot is not None:
            sets.append("previous_depot = ?")
            params.append(str(previous_depot).strip() or None)
        if current_depot is not None:
            sets.append("current_depot = ?")
            params.append(str(current_depot).strip())
        if destination is not None:
            sets.append("destination = ?")
            params.append(str(destination).strip() or None)
        if status is not None:
            sets.append("status = ?")
            params.append(status)
            if status == "Available":
                sets.append("available_since = ?")
                params.append(ts)
        if remarks is not None:
            sets.append("remarks = ?")
            params.append(str(remarks).strip() or None)
        params.append(entry_id)
        with _LOCK:
            conn = _connect()
            try:
                cur = conn.execute(
                    f"UPDATE fleet_daily_entries SET {', '.join(sets)} WHERE id = ?",
                    params,
                )
                conn.commit()
                if cur.rowcount == 0:
                    return None, "entry not found"
            finally:
                conn.close()
        return get_fleet_daily_entry(entry_id), None
    except Exception as e:
        return None, str(e)


def delete_fleet_daily_entry(entry_id: str) -> Tuple[bool, Optional[str]]:
    try:
        init_db()
        with _LOCK:
            conn = _connect()
            try:
                cur = conn.execute(
                    "DELETE FROM fleet_daily_entries WHERE id = ?",
                    (entry_id,),
                )
                conn.commit()
                if cur.rowcount == 0:
                    return False, "entry not found"
            finally:
                conn.close()
        return True, None
    except Exception as e:
        return False, str(e)


def list_fleet_requests(*, status: Optional[str] = None) -> Dict[str, Any]:
    try:
        init_db()
        clauses: List[str] = []
        params: List[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(str(status).strip())
        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with _LOCK:
            conn = _connect()
            try:
                rows = conn.execute(
                    f"""
                    SELECT id, leg_id, job_id, truck_number, request_type, status,
                           depot_name, destination, tonnage, plant_name,
                           requested_by, requested_at, resolved_by, resolved_at, remarks
                    FROM fleet_control_requests
                    {where_sql}
                    ORDER BY requested_at DESC
                    """,
                    params,
                ).fetchall()
            finally:
                conn.close()
        items = [_request_row_to_dict(r) for r in rows]
        return {"items": items, "total": len(items)}
    except Exception:
        return {"items": [], "total": 0}


def get_fleet_request(request_id: str) -> Optional[Dict[str, Any]]:
    try:
        init_db()
        with _LOCK:
            conn = _connect()
            try:
                row = conn.execute(
                    """
                    SELECT id, leg_id, job_id, truck_number, request_type, status,
                           depot_name, destination, tonnage, plant_name,
                           requested_by, requested_at, resolved_by, resolved_at, remarks
                    FROM fleet_control_requests WHERE id = ?
                    """,
                    (request_id,),
                ).fetchone()
            finally:
                conn.close()
        return _request_row_to_dict(row) if row else None
    except Exception:
        return None


def create_fleet_request(
    *,
    leg_id: str,
    request_type: str,
    requested_by: str,
    job_id: Optional[str] = None,
    truck_number: Optional[str] = None,
    depot_name: Optional[str] = None,
    destination: Optional[str] = None,
    tonnage: Optional[float] = None,
    plant_name: Optional[str] = None,
    remarks: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    rtype = str(request_type or "").strip().upper()
    if rtype not in VALID_REQUEST_TYPES:
        return None, f"request_type must be one of: {', '.join(sorted(VALID_REQUEST_TYPES))}"
    if not str(leg_id or "").strip():
        return None, "leg_id is required"
    if not str(requested_by or "").strip():
        return None, "requested_by is required"
    try:
        init_db()
        with _LOCK:
            conn = _connect()
            try:
                pending = conn.execute(
                    """
                    SELECT id FROM fleet_control_requests
                    WHERE leg_id = ? AND status = 'Pending'
                    """,
                    (leg_id,),
                ).fetchone()
                if pending is not None:
                    return None, "a pending request already exists for this leg"
            finally:
                conn.close()
        request_id = uuid.uuid4().hex[:16]
        ts = utc_now_iso()
        with _LOCK:
            conn = _connect()
            try:
                conn.execute(
                    """
                    INSERT INTO fleet_control_requests (
                        id, leg_id, job_id, truck_number, request_type, status,
                        depot_name, destination, tonnage, plant_name,
                        requested_by, requested_at, remarks
                    ) VALUES (?, ?, ?, ?, ?, 'Pending', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request_id,
                        leg_id,
                        job_id,
                        truck_number,
                        rtype,
                        depot_name,
                        destination,
                        float(tonnage) if tonnage is not None else None,
                        plant_name,
                        requested_by,
                        ts,
                        remarks,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return get_fleet_request(request_id), None
    except Exception as e:
        return None, str(e)


def update_fleet_request(
    request_id: str,
    *,
    status: str,
    resolved_by: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    st = str(status or "").strip()
    if st not in VALID_REQUEST_STATUSES:
        return None, f"status must be one of: {', '.join(sorted(VALID_REQUEST_STATUSES))}"
    if st == "Pending":
        return None, "cannot set status back to Pending"
    try:
        init_db()
        with _LOCK:
            conn = _connect()
            try:
                row = conn.execute(
                    "SELECT * FROM fleet_control_requests WHERE id = ?",
                    (request_id,),
                ).fetchone()
                if row is None:
                    return None, "request not found"
                if str(row["status"]) != "Pending":
                    return None, "request is no longer pending"
                ts = utc_now_iso()
                conn.execute(
                    """
                    UPDATE fleet_control_requests
                    SET status = ?, resolved_by = ?, resolved_at = ?
                    WHERE id = ?
                    """,
                    (st, str(resolved_by).strip(), ts, request_id),
                )
                conn.commit()
                leg_id = str(row["leg_id"])
                request_type = str(row["request_type"])
            finally:
                conn.close()
        if st == "Approved":
            if request_type == "PAUSE":
                set_user_control(leg_id, USER_CONTROL_PAUSED)
            elif request_type == "CLOSE":
                set_user_control(leg_id, USER_CONTROL_STOPPED)
        return get_fleet_request(request_id), None
    except Exception as e:
        return None, str(e)


def delete_fleet_request(request_id: str) -> Tuple[bool, Optional[str]]:
    try:
        init_db()
        with _LOCK:
            conn = _connect()
            try:
                cur = conn.execute(
                    "DELETE FROM fleet_control_requests WHERE id = ?",
                    (request_id,),
                )
                conn.commit()
                if cur.rowcount == 0:
                    return False, "request not found"
            finally:
                conn.close()
        return True, None
    except Exception as e:
        return False, str(e)
