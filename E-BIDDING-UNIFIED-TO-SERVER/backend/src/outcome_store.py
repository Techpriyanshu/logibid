"""
Mixed persistence for bid outcome persistence for Reports & Analytics.

Read-only observer: syncs from existing live_bids.db, successful_bids.db, and jobs.db.
Does NOT import or modify automation engine logic.
Never updates existing rows — insert only.

Uses MySQL when DATABASE_URL is available for bid_outcomes table,
falls back to SQLite for bid_outcomes.db.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from .config_loader import BASE_DIR
from .db import get_engine, DATABASE_URL
from .depot_normalization import normalize_depot_name

_DB_PATH = BASE_DIR / "data" / "bid_outcomes.db"
_LIVE_BIDS_DB = BASE_DIR / "data" / "live_bids.db"
_SUCCESSFUL_BIDS_DB = BASE_DIR / "data" / "successful_bids.db"
_JOBS_DB = BASE_DIR / "data" / "jobs.db"
_LOCK = threading.Lock()

# Check if MySQL is configured for bid_outcomes table (lazy evaluation)
_USE_SQLITE = None


def _use_sqlite() -> bool:
    """Lazy check if MySQL is configured. Avoids DB init at module import."""
    global _USE_SQLITE
    if _USE_SQLITE is None:
        from .db import init_db as mysql_init
        mysql_init()  # Call init_db to ensure DATABASE_URL is set
        _USE_SQLITE = bool(DATABASE_URL and DATABASE_URL.startswith("sqlite://"))
    return _USE_SQLITE

VALID_OUTCOME_STATUSES = frozenset({"won", "lost", "stopped", "paused", "failed"})
TERMINAL_LIVE_STATUSES = frozenset({"won", "completed", "stopped"})
JOB_TERMINAL_STATUSES = frozenset({"completed", "failed", "partial_failed"})


def _db_path() -> Path:
    return _DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso_ms(ts: Optional[str]) -> Optional[int]:
    if not ts:
        return None
    try:
        s = str(ts).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


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
                CREATE TABLE IF NOT EXISTS bid_outcomes (
                    outcome_id TEXT PRIMARY KEY,
                    leg_id TEXT NOT NULL UNIQUE,
                    job_id TEXT NOT NULL,
                    depot TEXT NOT NULL,
                    destination TEXT,
                    quantity REAL NOT NULL,
                    organization_name TEXT,
                    bid_amount INTEGER,
                    rank INTEGER,
                    outcome_status TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    duration_ms INTEGER,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bid_outcomes_job_id
                ON bid_outcomes (job_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bid_outcomes_status
                ON bid_outcomes (outcome_status)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bid_outcomes_completed_at
                ON bid_outcomes (completed_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bid_outcomes_depot
                ON bid_outcomes (depot)
                """
            )
            conn.commit()
        finally:
            conn.close()


def _init_db_mysql() -> None:
    """MySQL implementation for init_db."""
    engine = get_engine()
    if engine is None:
        return
    from .db import init_db as mysql_init
    mysql_init()  # This creates all tables including bid_outcomes


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert row to dict - works for both sqlite3.Row and MySQL row."""
    if hasattr(row, "__class__") and "sqlite3.Row" in str(row.__class__):
        # SQLite row
        return {
            "outcome_id": row["outcome_id"],
            "leg_id": row["leg_id"],
            "job_id": row["job_id"],
            "depot": row["depot"],
            "destination": row["destination"],
            "quantity": float(row["quantity"]),
            "organization_name": row["organization_name"],
            "bid_amount": int(row["bid_amount"]) if row["bid_amount"] is not None else None,
            "rank": int(row["rank"]) if row["rank"] is not None else None,
            "outcome_status": row["outcome_status"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "duration_ms": int(row["duration_ms"]) if row["duration_ms"] is not None else None,
            "created_at": row["created_at"],
        }
    else:
        # MySQL row
        return {
            "outcome_id": row.outcome_id,
            "leg_id": row.leg_id,
            "job_id": row.job_id,
            "depot": row.depot,
            "destination": row.destination,
            "quantity": float(row.quantity),
            "organization_name": row.organization_name,
            "bid_amount": int(row.bid_amount) if row.bid_amount is not None else None,
            "rank": int(row.rank) if row.rank is not None else None,
            "outcome_status": row.outcome_status,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
            "duration_ms": int(row.duration_ms) if row.duration_ms is not None else None,
            "created_at": row.created_at,
        }


def insert_outcome(
    *,
    leg_id: str,
    job_id: str,
    depot: str,
    destination: Optional[str],
    quantity: float,
    organization_name: Optional[str] = None,
    bid_amount: Optional[int] = None,
    rank: Optional[int] = None,
    outcome_status: str,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> Optional[str]:
    """
    Insert one immutable outcome row (INSERT OR IGNORE on leg_id).
    Returns outcome_id if inserted, None if duplicate or invalid. Never raises.
    """
    status = str(outcome_status or "").strip().lower()
    if status not in VALID_OUTCOME_STATUSES:
        return None
    if not str(leg_id or "").strip() or not str(job_id or "").strip():
        return None
    depot_norm = normalize_depot_name(depot) or str(depot or "").strip().upper()
    if not depot_norm:
        return None
    try:
        init_db()
        outcome_id = uuid.uuid4().hex[:16]
        ts = utc_now_iso()
        if duration_ms is None and started_at and completed_at:
            s_ms = _parse_iso_ms(started_at)
            c_ms = _parse_iso_ms(completed_at)
            if s_ms is not None and c_ms is not None and c_ms >= s_ms:
                duration_ms = c_ms - s_ms
        
        if not _use_sqlite():
            return _insert_outcome_mysql(
                outcome_id, leg_id, job_id, depot_norm,
                destination, quantity, organization_name,
                bid_amount, rank, status, started_at,
                completed_at, duration_ms, ts
            )
        return _insert_outcome_sqlite(
            outcome_id, leg_id, job_id, depot_norm,
            destination, quantity, organization_name,
            bid_amount, rank, status, started_at,
            completed_at, duration_ms, ts
        )
    except Exception:
        return None


def _insert_outcome_sqlite(
    outcome_id: str, leg_id: str, job_id: str, depot: str, destination: Optional[str],
    quantity: float, organization_name: Optional[str], bid_amount: Optional[int],
    rank: Optional[int], status: str, started_at: Optional[str], completed_at: Optional[str],
    duration_ms: Optional[int], ts: str
) -> Optional[str]:
    """SQLite implementation for insert_outcome."""
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO bid_outcomes (
                    outcome_id, leg_id, job_id, depot, destination, quantity,
                    organization_name, bid_amount, rank, outcome_status,
                    started_at, completed_at, duration_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome_id, leg_id, job_id, depot,
                    (destination or "").strip() or None,
                    float(quantity), organization_name,
                    int(bid_amount) if bid_amount is not None else None,
                    int(rank) if rank is not None else None,
                    status, started_at, completed_at, duration_ms, ts,
                ),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
            return outcome_id
        finally:
            conn.close()


def _insert_outcome_mysql(
    outcome_id: str, leg_id: str, job_id: str, depot: str, destination: Optional[str],
    quantity: float, organization_name: Optional[str], bid_amount: Optional[int],
    rank: Optional[int], status: str, started_at: Optional[str], completed_at: Optional[str],
    duration_ms: Optional[int], ts: str
) -> Optional[str]:
    """MySQL implementation for insert_outcome."""
    outcomes_table = get_bid_outcomes_table()
    if outcomes_table is None:
        return None
    
    engine = get_engine()
    if engine is None:
        return None
    
    with _LOCK:
        with engine.begin() as conn:
            from sqlalchemy import insert
            stmt = insert(outcomes_table).values(
                outcome_id=outcome_id,
                leg_id=leg_id,
                job_id=job_id,
                depot=depot,
                destination=(destination or "").strip() or None,
                quantity=float(quantity),
                organization_name=organization_name,
                bid_amount=int(bid_amount) if bid_amount is not None else None,
                rank=int(rank) if rank is not None else None,
                outcome_status=status,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                created_at=ts,
            )
            try:
                conn.execute(stmt)
                conn.commit()
                return outcome_id
            except Exception:
                # Row already exists
                return None


def _existing_leg_ids() -> set[str]:
    try:
        init_db()
        if not _use_sqlite():
            return _existing_leg_ids_mysql()
        return _existing_leg_ids_sqlite()
    except Exception:
        return set()


def _existing_leg_ids_sqlite() -> set[str]:
    """SQLite implementation for _existing_leg_ids."""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute("SELECT leg_id FROM bid_outcomes").fetchall()
        finally:
            conn.close()
    return {str(r["leg_id"]) for r in rows}


def _existing_leg_ids_mysql() -> set[str]:
    """MySQL implementation for _existing_leg_ids."""
    outcomes_table = get_bid_outcomes_table()
    if outcomes_table is None:
        return set()
    
    engine = get_engine()
    if engine is None:
        return set()
    
    with _LOCK:
        with engine.connect() as conn:
            stmt = select(outcomes_table.c.leg_id)
            rows = conn.execute(stmt).fetchall()
    return {str(r.leg_id) for r in rows}


def _read_live_bids() -> List[Dict[str, Any]]:
    if not _LIVE_BIDS_DB.exists():
        return []
    try:
        # Check if live_bids uses MySQL
        live_bids_engine = get_engine()
        
        if live_bids_engine is not None:
            # MySQL
            return _read_live_bids_mysql(live_bids_engine)
        else:
            # SQLite
            return _read_live_bids_sqlite()
    except Exception:
        return []


def _read_live_bids_sqlite() -> List[Dict[str, Any]]:
    """SQLite implementation for _read_live_bids."""
    try:
        conn = _connect(_LIVE_BIDS_DB)
        try:
            rows = conn.execute(
                """
                SELECT id, job_id, depot, destination, quantity, organization_name,
                       current_rank, status, won_timestamp, user_control, updated_at
                FROM live_bids
                """
            ).fetchall()
        finally:
            conn.close()
        return [
            {
                "id": r["id"],
                "job_id": r["job_id"],
                "depot": r["depot"],
                "destination": r["destination"],
                "quantity": float(r["quantity"]),
                "organization_name": r["organization_name"],
                "current_rank": int(r["current_rank"]) if r["current_rank"] is not None else None,
                "status": r["status"],
                "won_timestamp": r["won_timestamp"],
                "user_control": r["user_control"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
    except Exception:
        return []


def _read_live_bids_mysql(engine) -> List[Dict[str, Any]]:
    """MySQL implementation for _read_live_bids."""
    try:
        from .db import get_live_bids_table
        live_bids_table = get_live_bids_table()
        if live_bids_table is None:
            return []
        
        with engine.connect() as conn:
            cols = [
                live_bids_table.c.id,
                live_bids_table.c.job_id,
                live_bids_table.c.depot,
                live_bids_table.c.destination,
                live_bids_table.c.quantity,
                live_bids_table.c.organization_name,
                live_bids_table.c.current_rank,
                live_bids_table.c.status,
                live_bids_table.c.won_timestamp,
                live_bids_table.c.user_control,
                live_bids_table.c.updated_at,
            ]
            stmt = select(*cols)
            rows = conn.execute(stmt).fetchall()
        
        return [
            {
                "id": r.id,
                "job_id": r.job_id,
                "depot": r.depot,
                "destination": r.destination,
                "quantity": float(r.quantity) if r.quantity is not None else 0.0,
                "organization_name": r.organization_name,
                "current_rank": int(r.current_rank) if r.current_rank is not None else None,
                "status": r.status,
                "won_timestamp": r.won_timestamp,
                "user_control": r.user_control,
                "updated_at": r.updated_at,
            }
            for r in rows
        ]
    except Exception:
        return []


def _read_successful_bids() -> List[Dict[str, Any]]:
    if not _SUCCESSFUL_BIDS_DB.exists():
        return []
    try:
        # Check if successful_bids uses MySQL
        successful_bids_engine = get_engine()
        
        if successful_bids_engine is not None:
            # MySQL
            return _read_successful_bids_mysql(successful_bids_engine)
        else:
            # SQLite
            return _read_successful_bids_sqlite()
    except Exception:
        return []


def _read_successful_bids_sqlite() -> List[Dict[str, Any]]:
    """SQLite implementation for _read_successful_bids."""
    try:
        conn = _connect(_SUCCESSFUL_BIDS_DB)
        try:
            rows = conn.execute(
                """
                SELECT depot, destination, quantity, bid_amount, won_timestamp, rank
                FROM successful_bids
                ORDER BY won_timestamp DESC
                """
            ).fetchall()
        finally:
            conn.close()
        return [
            {
                "depot": r["depot"],
                "destination": r["destination"],
                "quantity": float(r["quantity"]),
                "bid_amount": int(r["bid_amount"]),
                "won_timestamp": r["won_timestamp"],
                "rank": int(r["rank"]),
            }
            for r in rows
        ]
    except Exception:
        return []


def _read_successful_bids_mysql(engine) -> List[Dict[str, Any]]:
    """MySQL implementation for _read_successful_bids."""
    try:
        from .db import get_successful_bids_table
        successful_bids_table = get_successful_bids_table()
        if successful_bids_table is None:
            return []
        
        with engine.connect() as conn:
            cols = [
                successful_bids_table.c.depot,
                successful_bids_table.c.destination,
                successful_bids_table.c.quantity,
                successful_bids_table.c.bid_amount,
                successful_bids_table.c.won_timestamp,
                successful_bids_table.c.rank,
            ]
            stmt = select(*cols).order_by(successful_bids_table.c.won_timestamp.desc())
            rows = conn.execute(stmt).fetchall()
        
        return [
            {
                "depot": r.depot,
                "destination": r.destination,
                "quantity": float(r.quantity) if r.quantity is not None else 0.0,
                "bid_amount": int(r.bid_amount),
                "won_timestamp": r.won_timestamp,
                "rank": int(r.rank),
            }
            for r in rows
        ]
    except Exception:
        return []


def _read_jobs() -> Dict[str, Dict[str, Any]]:
    if not _JOBS_DB.exists():
        return {}
    try:
        # Check if jobs uses MySQL
        jobs_engine = get_engine()
        
        if jobs_engine is not None:
            # MySQL
            return _read_jobs_mysql(jobs_engine)
        else:
            # SQLite
            return _read_jobs_sqlite()
    except Exception:
        return {}


def _read_jobs_sqlite() -> Dict[str, Dict[str, Any]]:
    """SQLite implementation for _read_jobs."""
    try:
        conn = _connect(_JOBS_DB)
        try:
            rows = conn.execute(
                """
                SELECT job_id, status, started_at, completed_at, results_json, errors_json
                FROM bid_jobs
                """
            ).fetchall()
        finally:
            conn.close()
        out: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            results = json.loads(r["results_json"] or "{}")
            errors = json.loads(r["errors_json"] or "{}")
            started_iso = None
            completed_iso = None
            if r["started_at"] is not None:
                started_iso = datetime.fromtimestamp(
                    float(r["started_at"]), tz=timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            if r["completed_at"] is not None:
                completed_iso = datetime.fromtimestamp(
                    float(r["completed_at"]), tz=timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            out[str(r["job_id"])] = {
                "status": str(r["status"]),
                "started_at": started_iso,
                "completed_at": completed_iso,
                "results": results if isinstance(results, dict) else {},
                "errors": errors if isinstance(errors, dict) else {},
            }
        return out
    except Exception:
        return {}


def _read_jobs_mysql(engine) -> Dict[str, Dict[str, Any]]:
    """MySQL implementation for _read_jobs."""
    try:
        from .db import get_tables
        metadata, jobs_table, _ = get_tables()
        if jobs_table is None:
            return {}
        
        with engine.connect() as conn:
            cols = [
                jobs_table.c.job_id,
                jobs_table.c.status,
                jobs_table.c.started_at,
                jobs_table.c.completed_at,
                jobs_table.c.results,
                jobs_table.c.errors,
            ]
            stmt = select(*cols)
            rows = conn.execute(stmt).fetchall()
        
        out: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            try:
                results = json.loads(r.results or "{}")
            except Exception:
                results = {}
            try:
                errors = json.loads(r.errors or "{}")
            except Exception:
                errors = {}
            
            started_iso = None
            completed_iso = None
            if r.started_at is not None:
                started_iso = datetime.fromtimestamp(
                    float(r.started_at), tz=timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            if r.completed_at is not None:
                completed_iso = datetime.fromtimestamp(
                    float(r.completed_at), tz=timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            out[str(r.job_id)] = {
                "status": str(r.status),
                "started_at": started_iso,
                "completed_at": completed_iso,
                "results": results if isinstance(results, dict) else {},
                "errors": errors if isinstance(errors, dict) else {},
            }
        return out
    except Exception:
        return {}


def _match_bid_amount(
    successful: List[Dict[str, Any]],
    *,
    depot: str,
    destination: Optional[str],
    quantity: float,
    won_timestamp: Optional[str],
) -> Optional[int]:
    dest_norm = (destination or "").strip().upper()
    won_ms = _parse_iso_ms(won_timestamp)
    best: Optional[Tuple[int, int]] = None
    for sb in successful:
        if sb["depot"] != depot:
            continue
        sb_dest = (sb.get("destination") or "").strip().upper()
        if dest_norm and sb_dest and sb_dest != dest_norm:
            continue
        if abs(float(sb["quantity"]) - float(quantity)) >= 0.01:
            continue
        sb_ms = _parse_iso_ms(sb.get("won_timestamp"))
        if won_ms is not None and sb_ms is not None:
            delta = abs(won_ms - sb_ms)
            if best is None or delta < best[1]:
                best = (int(sb["bid_amount"]), delta)
        elif best is None:
            best = (int(sb["bid_amount"]), 999999999)
    return best[0] if best else None


def _map_live_to_outcome(live_status: str) -> Optional[str]:
    s = str(live_status or "").strip().lower()
    if s == "won":
        return "won"
    if s == "completed":
        return "lost"
    if s == "stopped":
        return "stopped"
    if s == "paused":
        return "paused"
    return None


def _depot_failed_in_job(job: Dict[str, Any], depot: str) -> bool:
    if str(job.get("status") or "").lower() == "failed":
        return True
    results = job.get("results") or {}
    for _key, val in results.items():
        if not isinstance(val, dict):
            continue
        val_depot = normalize_depot_name(str(val.get("depot") or _key)) or str(_key).upper()
        if val_depot == depot and str(val.get("status") or "").lower() == "failed":
            return True
    return False


def sync_outcomes_from_sources() -> Dict[str, int]:
    """
    Observe existing persistence stores and insert missing outcomes.
    Does not modify live_bids, successful_bids, or jobs databases.
    Returns counts of newly inserted rows by outcome_status.
    """
    counts: Dict[str, int] = {s: 0 for s in VALID_OUTCOME_STATUSES}
    try:
        init_db()
        existing = _existing_leg_ids()
        live_rows = _read_live_bids()
        successful = _read_successful_bids()
        jobs = _read_jobs()

        legs_by_job: Dict[str, List[Dict[str, Any]]] = {}
        for leg in live_rows:
            legs_by_job.setdefault(str(leg["job_id"]), []).append(leg)

        for leg in live_rows:
            leg_id = str(leg["id"])
            if leg_id in existing:
                continue
            live_status = str(leg.get("status") or "")
            if live_status not in TERMINAL_LIVE_STATUSES:
                continue
            outcome_status = _map_live_to_outcome(live_status)
            if not outcome_status:
                continue
            job = jobs.get(str(leg["job_id"]), {})
            started_at = job.get("started_at") or leg.get("updated_at")
            completed_at = leg.get("won_timestamp") or leg.get("updated_at")
            rank = leg.get("current_rank")
            if outcome_status == "won":
                rank = rank or 1
            bid_amount = None
            if outcome_status == "won":
                bid_amount = _match_bid_amount(
                    successful,
                    depot=str(leg["depot"]),
                    destination=leg.get("destination"),
                    quantity=float(leg["quantity"]),
                    won_timestamp=leg.get("won_timestamp"),
                )
            oid = insert_outcome(
                leg_id=leg_id,
                job_id=str(leg["job_id"]),
                depot=str(leg["depot"]),
                destination=leg.get("destination"),
                quantity=float(leg["quantity"]),
                organization_name=leg.get("organization_name"),
                bid_amount=bid_amount,
                rank=rank,
                outcome_status=outcome_status,
                started_at=started_at,
                completed_at=completed_at,
            )
            if oid:
                existing.add(leg_id)
                counts[outcome_status] = counts.get(outcome_status, 0) + 1

        for job_id, job in jobs.items():
            if str(job.get("status") or "") not in JOB_TERMINAL_STATUSES:
                continue
            for leg in legs_by_job.get(job_id, []):
                leg_id = str(leg["id"])
                if leg_id in existing:
                    continue
                live_status = str(leg.get("status") or "").lower()
                if live_status in TERMINAL_LIVE_STATUSES:
                    continue
                started_at = job.get("started_at") or leg.get("updated_at")
                completed_at = job.get("completed_at") or leg.get("updated_at")

                if live_status == "paused":
                    oid = insert_outcome(
                        leg_id=leg_id,
                        job_id=job_id,
                        depot=str(leg["depot"]),
                        destination=leg.get("destination"),
                        quantity=float(leg["quantity"]),
                        organization_name=leg.get("organization_name"),
                        rank=leg.get("current_rank"),
                        outcome_status="paused",
                        started_at=started_at,
                        completed_at=completed_at,
                    )
                    if oid:
                        existing.add(leg_id)
                        counts["paused"] = counts.get("paused", 0) + 1
                    continue

                if _depot_failed_in_job(job, str(leg["depot"])):
                    oid = insert_outcome(
                        leg_id=leg_id,
                        job_id=job_id,
                        depot=str(leg["depot"]),
                        destination=leg.get("destination"),
                        quantity=float(leg["quantity"]),
                        organization_name=leg.get("organization_name"),
                        outcome_status="failed",
                        started_at=started_at,
                        completed_at=completed_at,
                    )
                    if oid:
                        existing.add(leg_id)
                        counts["failed"] = counts.get("failed", 0) + 1
    except Exception:
        pass
    return counts


def list_bid_outcomes(
    *,
    job_id: Optional[str] = None,
    outcome_status: Optional[str] = None,
    depot: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Query historical outcomes. Triggers a sync before read."""
    sync_outcomes_from_sources()
    if not _use_sqlite():
        return _list_bid_outcomes_mysql(
            job_id=job_id,
            outcome_status=outcome_status,
            depot=depot,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
        )
    return _list_bid_outcomes_sqlite(
        job_id=job_id,
        outcome_status=outcome_status,
        depot=depot,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )


def _list_bid_outcomes_sqlite(
    *,
    job_id: Optional[str] = None,
    outcome_status: Optional[str] = None,
    depot: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """SQLite implementation for list_bid_outcomes."""
    clauses: List[str] = []
    params: List[Any] = []
    if job_id:
        clauses.append("job_id = ?")
        params.append(str(job_id).strip())
    if outcome_status:
        st = str(outcome_status).strip().lower()
        if st in VALID_OUTCOME_STATUSES:
            clauses.append("outcome_status = ?")
            params.append(st)
    if depot:
        depot_norm = normalize_depot_name(depot) or str(depot).strip().upper()
        if depot_norm:
            clauses.append("depot = ?")
            params.append(depot_norm)
    if from_date:
        clauses.append("substr(completed_at, 1, 10) >= ?")
        params.append(str(from_date).strip())
    if to_date:
        clauses.append("substr(completed_at, 1, 10) <= ?")
        params.append(str(to_date).strip())
    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    limit_sql = ""
    if limit is not None and int(limit) > 0:
        limit_sql = " LIMIT ?"
        params.append(int(limit))
    sql = (
        "SELECT outcome_id, leg_id, job_id, depot, destination, quantity, "
        "organization_name, bid_amount, rank, outcome_status, "
        "started_at, completed_at, duration_ms, created_at "
        f"FROM bid_outcomes{where_sql} "
        f"ORDER BY completed_at DESC, created_at DESC{limit_sql}"
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


def _list_bid_outcomes_mysql(
    *,
    job_id: Optional[str] = None,
    outcome_status: Optional[str] = None,
    depot: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """MySQL implementation for list_bid_outcomes."""
    outcomes_table = get_bid_outcomes_table()
    if outcomes_table is None:
        return {"items": [], "total": 0}
    
    engine = get_engine()
    if engine is None:
        return {"items": [], "total": 0}
    
    clauses = []
    
    if job_id:
        clauses.append(outcomes_table.c.job_id == str(job_id).strip())
    if outcome_status:
        st = str(outcome_status).strip().lower()
        if st in VALID_OUTCOME_STATUSES:
            clauses.append(outcomes_table.c.outcome_status == st)
    if depot:
        depot_norm = normalize_depot_name(depot) or str(depot).strip().upper()
        if depot_norm:
            clauses.append(outcomes_table.c.depot == depot_norm)
    if from_date:
        clauses.append("SUBSTRING(completed_at, 1, 10) >= :from_date")
    if to_date:
        clauses.append("SUBSTRING(completed_at, 1, 10) <= :to_date")
    
    with _LOCK:
        with engine.connect() as conn:
            cols = [
                outcomes_table.c.outcome_id,
                outcomes_table.c.leg_id,
                outcomes_table.c.job_id,
                outcomes_table.c.depot,
                outcomes_table.c.destination,
                outcomes_table.c.quantity,
                outcomes_table.c.organization_name,
                outcomes_table.c.bid_amount,
                outcomes_table.c.rank,
                outcomes_table.c.outcome_status,
                outcomes_table.c.started_at,
                outcomes_table.c.completed_at,
                outcomes_table.c.duration_ms,
                outcomes_table.c.created_at,
            ]
            stmt = select(*cols)
            if clauses:
                from sqlalchemy import and_
                stmt = stmt.where(and_(*clauses))
            stmt = stmt.order_by(
                outcomes_table.c.completed_at.desc(),
                outcomes_table.c.created_at.desc()
            )
            if limit is not None and int(limit) > 0:
                stmt = stmt.limit(int(limit))
            
            params = {}
            if job_id:
                params["job_id"] = str(job_id).strip()
            if outcome_status:
                params["outcome_status"] = outcome_status
            if depot:
                params["depot"] = depot_norm
            if from_date:
                params["from_date"] = str(from_date).strip()
            if to_date:
                params["to_date"] = str(to_date).strip()
            rows = conn.execute(stmt, params).fetchall()
    
    items = [_row_to_dict(r) for r in rows]
    return {"items": items, "total": len(items)}


def get_outcomes_summary(
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    depot: Optional[str] = None,
) -> Dict[str, Any]:
    """Aggregate counts for Reports. Triggers sync before read."""
    sync_outcomes_from_sources()
    if not _use_sqlite():
        return _get_outcomes_summary_mysql(
            from_date=from_date,
            to_date=to_date,
            depot=depot,
        )
    return _get_outcomes_summary_sqlite(
        from_date=from_date,
        to_date=to_date,
        depot=depot,
    )


def _get_outcomes_summary_sqlite(
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    depot: Optional[str] = None,
) -> Dict[str, Any]:
    """SQLite implementation for get_outcomes_summary."""
    clauses: List[str] = []
    params: List[Any] = []
    if depot:
        depot_norm = normalize_depot_name(depot) or str(depot).strip().upper()
        if depot_norm:
            clauses.append("depot = ?")
            params.append(depot_norm)
    if from_date:
        clauses.append("substr(completed_at, 1, 10) >= ?")
        params.append(str(from_date).strip())
    if to_date:
        clauses.append("substr(completed_at, 1, 10) <= ?")
        params.append(str(to_date).strip())
    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    try:
        init_db()
        with _LOCK:
            conn = _connect()
            try:
                rows = conn.execute(
                    f"""
                    SELECT outcome_status, COUNT(*) AS cnt
                    FROM bid_outcomes{where_sql}
                    GROUP BY outcome_status
                    """,
                    params,
                ).fetchall()
                total_row = conn.execute(
                    f"SELECT COUNT(*) AS cnt FROM bid_outcomes{where_sql}",
                    params,
                ).fetchone()
            finally:
                conn.close()
        by_status = {str(r["outcome_status"]): int(r["cnt"]) for r in rows}
        total = int(total_row["cnt"]) if total_row else 0
        won = by_status.get("won", 0)
        lost = by_status.get("lost", 0)
        decided = won + lost
        return {
            "total": total,
            "by_status": by_status,
            "won": won,
            "lost": lost,
            "stopped": by_status.get("stopped", 0),
            "paused": by_status.get("paused", 0),
            "failed": by_status.get("failed", 0),
            "win_rate": round(won / decided, 4) if decided > 0 else None,
        }
    except Exception:
        return {
            "total": 0,
            "by_status": {},
            "won": 0,
            "lost": 0,
            "stopped": 0,
            "paused": 0,
            "failed": 0,
            "win_rate": None,
        }


def _get_outcomes_summary_mysql(
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    depot: Optional[str] = None,
) -> Dict[str, Any]:
    """MySQL implementation for get_outcomes_summary."""
    outcomes_table = get_bid_outcomes_table()
    if outcomes_table is None:
        return {
            "total": 0,
            "by_status": {},
            "won": 0,
            "lost": 0,
            "stopped": 0,
            "paused": 0,
            "failed": 0,
            "win_rate": None,
        }
    
    engine = get_engine()
    if engine is None:
        return {
            "total": 0,
            "by_status": {},
            "won": 0,
            "lost": 0,
            "stopped": 0,
            "paused": 0,
            "failed": 0,
            "win_rate": None,
        }
    
    clauses = []
    params = {}
    
    if depot:
        depot_norm = normalize_depot_name(depot) or str(depot).strip().upper()
        if depot_norm:
            clauses.append(outcomes_table.c.depot == depot_norm)
            params["depot"] = depot_norm
    if from_date:
        clauses.append("SUBSTRING(completed_at, 1, 10) >= :from_date")
        params["from_date"] = str(from_date).strip()
    if to_date:
        clauses.append("SUBSTRING(completed_at, 1, 10) <= :to_date")
        params["to_date"] = str(to_date).strip()
    
    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    
    try:
        init_db()
        with _LOCK:
            with engine.connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT outcome_status, COUNT(*) AS cnt
                    FROM bid_outcomes{where_sql}
                    GROUP BY outcome_status
                    """,
                    params,
                ).fetchall()
                total_row = conn.execute(
                    f"SELECT COUNT(*) AS cnt FROM bid_outcomes{where_sql}",
                    params,
                ).fetchone()
        
        by_status = {str(r.outcome_status): int(r.cnt) for r in rows}
        total = int(total_row.cnt) if total_row else 0
        won = by_status.get("won", 0)
        lost = by_status.get("lost", 0)
        decided = won + lost
        return {
            "total": total,
            "by_status": by_status,
            "won": won,
            "lost": lost,
            "stopped": by_status.get("stopped", 0),
            "paused": by_status.get("paused", 0),
            "failed": by_status.get("failed", 0),
            "win_rate": round(won / decided, 4) if decided > 0 else None,
        }
    except Exception:
        return {
            "total": 0,
            "by_status": {},
            "won": 0,
            "lost": 0,
            "stopped": 0,
            "paused": 0,
            "failed": 0,
            "win_rate": None,
        }


def list_outcomes_for_job(job_id: str) -> Dict[str, Any]:
    """All outcomes for one job. Triggers sync before read."""
    if not str(job_id or "").strip():
        return {"items": [], "total": 0, "job_id": job_id}
    data = list_bid_outcomes(job_id=job_id)
    data["job_id"] = job_id
    return data
