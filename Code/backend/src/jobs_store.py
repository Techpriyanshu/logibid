"""
Mixed persistence for bid job metadata (Control Panel polling).
Uses MySQL when DATABASE_URL is available, falls back to SQLite.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .config_loader import BASE_DIR
from .db import get_engine, get_tables, DATABASE_URL
from .logging_service import get_logger

logger = get_logger("jobs_store")

if TYPE_CHECKING:
    from .job_store import JobRecord

_DB_PATH = BASE_DIR / "data" / "jobs.db"
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


def _db_path() -> Path:
    return _DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def init_db() -> None:
    """Initialize database - create tables if MySQL, or ensure SQLite exists."""
    if not _use_sqlite():
        # If MySQL is configured but engine is None, initialize DB first
        if get_engine() is None:
            from .db import init_db as mysql_init
            mysql_init()
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
                CREATE TABLE IF NOT EXISTS bid_jobs (
                    job_id TEXT PRIMARY KEY,
                    truck_id TEXT NOT NULL,
                    depots_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    completed_at REAL,
                    desired_bids_count INTEGER NOT NULL DEFAULT 0,
                    results_json TEXT NOT NULL DEFAULT '{}',
                    errors_json TEXT NOT NULL DEFAULT '{}',
                    summary TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bid_jobs_status
                ON bid_jobs (status)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bid_jobs_created_at
                ON bid_jobs (created_at)
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
    mysql_init()  # This creates all tables including jobs


def _record_to_api_dict(
    *,
    job_id: str,
    truck_id: str,
    depots: List[str],
    status: str,
    created_at: float,
    started_at: Optional[float],
    completed_at: Optional[float],
    desired_bids_count: int,
    results: Dict[str, Any],
    errors: Dict[str, str],
    summary: Optional[str],
) -> Dict[str, Any]:
    """Match job_store.JobStore._serialize() response shape."""
    d: Dict[str, Any] = {
        "job_id": job_id,
        "truck_id": truck_id,
        "depots": depots,
        "status": status,
        "created_at": created_at,
        "started_at": started_at,
        "completed_at": completed_at,
        "desired_bids_count": desired_bids_count,
        "results": results,
        "errors": errors,
        "summary": summary,
    }
    d["created_at_iso"] = _iso(created_at)
    if started_at is not None:
        d["started_at_iso"] = _iso(started_at)
    if completed_at is not None:
        d["completed_at_iso"] = _iso(completed_at)
    return d


def upsert_job_record(record: "JobRecord") -> bool:
    """
    Insert or update one job row from an in-memory JobRecord.
    Never raises.
    """
    try:
        init_db()
        logger.info("upsert_job_record: job_id=%s status=%s desired_bids_count=%s", record.job_id, record.status, record.desired_bids_count)
        ts = utc_now_iso()
        if not _use_sqlite():
            return _upsert_job_record_mysql(record, ts)
        return _upsert_job_record_sqlite(record, ts)
    except Exception as e:
        logger.exception("upsert_job_record failed for job_id=%s error=%s", record.job_id, str(e))
        return False


def _upsert_job_record_sqlite(record: "JobRecord", ts: str) -> bool:
    """SQLite implementation for upsert_job_record."""
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO bid_jobs (
                    job_id,
                    truck_id,
                    depots_json,
                    status,
                    created_at,
                    started_at,
                    completed_at,
                    desired_bids_count,
                    results_json,
                    errors_json,
                    summary,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    truck_id = excluded.truck_id,
                    depots_json = excluded.depots_json,
                    status = excluded.status,
                    created_at = excluded.created_at,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at,
                    desired_bids_count = excluded.desired_bids_count,
                    results_json = excluded.results_json,
                    errors_json = excluded.errors_json,
                    summary = excluded.summary,
                    updated_at = excluded.updated_at
                """,
                (
                    record.job_id,
                    record.truck_id,
                    json.dumps(list(record.depots), default=str),
                    record.status,
                    float(record.created_at),
                    float(record.started_at) if record.started_at is not None else None,
                    float(record.completed_at) if record.completed_at is not None else None,
                    int(record.desired_bids_count),
                    json.dumps(dict(record.results), default=str),
                    json.dumps(dict(record.errors), default=str),
                    record.summary,
                    ts,
                ),
            )
            conn.commit()
            return True
        finally:
            conn.close()


def _upsert_job_record_mysql(record: "JobRecord", ts: str) -> bool:
    """MySQL implementation for upsert_job_record."""
    engine = get_engine()
    if engine is None:
        logger.error("_upsert_job_record_mysql: engine is None, cannot proceed")
        return False
    
    metadata, jobs_table, _ = get_tables()
    if jobs_table is None:
        logger.error("_upsert_job_record_mysql: jobs_table is None")
        return False
    
    logger.debug("_upsert_job_record_mysql: inserting job_id=%s status=%s", record.job_id, record.status)
    
    with _LOCK:
        with engine.begin() as conn:
            try:
                # Try to insert
                conn.execute(
                    jobs_table.insert().values(
                        job_id=record.job_id,
                        truck_id=record.truck_id,
                        depots=json.dumps(list(record.depots), default=str),
                        status=record.status,
                        created_at=float(record.created_at),
                        started_at=float(record.started_at) if record.started_at is not None else None,
                        completed_at=float(record.completed_at) if record.completed_at is not None else None,
                        desired_bids_count=int(record.desired_bids_count),
                        results=json.dumps(dict(record.results), default=str),
                        errors=json.dumps(dict(record.errors), default=str),
                        summary=record.summary,
                        desired_bids=json.dumps(record.payload, default=str) if isinstance(record.payload, list) else json.dumps(list(record.payload.get("desired_bids", [])), default=str),
                    )
                )
                logger.info("_upsert_job_record_mysql: INSERT succeeded for job_id=%s", record.job_id)
            except Exception as insert_err:
                # Row exists, update instead
                logger.debug("_upsert_job_record_mysql: INSERT failed, trying UPDATE for job_id=%s error=%s", record.job_id, str(insert_err))
                from sqlalchemy import update
                stmt = (
                    update(jobs_table)
                    .where(jobs_table.c.job_id == record.job_id)
                    .values(
                        truck_id=record.truck_id,
                        depots=json.dumps(list(record.depots), default=str),
                        status=record.status,
                        created_at=float(record.created_at),
                        started_at=float(record.started_at) if record.started_at is not None else None,
                        completed_at=float(record.completed_at) if record.completed_at is not None else None,
                        desired_bids_count=int(record.desired_bids_count),
                        results=json.dumps(dict(record.results), default=str),
                        errors=json.dumps(dict(record.errors), default=str),
                        summary=record.summary,
                        desired_bids=json.dumps(record.payload, default=str) if isinstance(record.payload, list) else json.dumps(list(record.payload.get("desired_bids", [])), default=str),
                    )
                )
                conn.execute(stmt)
                logger.info("_upsert_job_record_mysql: UPDATE succeeded for job_id=%s", record.job_id)
            conn.commit()
    logger.info("_upsert_job_record_mysql: Completed for job_id=%s status=%s", record.job_id, record.status)
    return True


def load_job_dict(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Load one job by id and return the same dict shape as job_store.get_job().
    Never raises.
    """
    if not job_id:
        logger.debug("load_job_dict: empty job_id")
        return None
    try:
        init_db()
        logger.debug("load_job_dict: loading job_id=%s", job_id)
        if not _use_sqlite():
            return _load_job_dict_mysql(job_id)
        return _load_job_dict_sqlite(job_id)
    except Exception as e:
        logger.exception("load_job_dict failed for job_id=%s error=%s", job_id, str(e))
        return None


def _load_job_dict_sqlite(job_id: str) -> Optional[Dict[str, Any]]:
    """SQLite implementation for load_job_dict."""
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT
                    job_id,
                    truck_id,
                    depots_json,
                    status,
                    created_at,
                    started_at,
                    completed_at,
                    desired_bids_count,
                    results_json,
                    errors_json,
                    summary
                FROM bid_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        finally:
            conn.close()
    if row is None:
        return None
    depots = json.loads(row["depots_json"] or "[]")
    results = json.loads(row["results_json"] or "{}")
    errors = json.loads(row["errors_json"] or "{}")
    return _record_to_api_dict(
        job_id=str(row["job_id"]),
        truck_id=str(row["truck_id"]),
        depots=depots if isinstance(depots, list) else [],
        status=str(row["status"]),
        created_at=float(row["created_at"]),
        started_at=float(row["started_at"]) if row["started_at"] is not None else None,
        completed_at=float(row["completed_at"]) if row["completed_at"] is not None else None,
        desired_bids_count=int(row["desired_bids_count"]),
        results=results if isinstance(results, dict) else {},
        errors=errors if isinstance(errors, dict) else {},
        summary=row["summary"],
    )


def _load_job_dict_mysql(job_id: str) -> Optional[Dict[str, Any]]:
    """MySQL implementation for load_job_dict."""
    engine = get_engine()
    if engine is None:
        return None
    
    metadata, jobs_table, _ = get_tables()
    if jobs_table is None:
        return None
    
    with _LOCK:
        with engine.connect() as conn:
            from sqlalchemy import select
            stmt = select(jobs_table).where(jobs_table.c.job_id == job_id)
            row = conn.execute(stmt).fetchone()
    
    if row is None:
        return None
    
    depots = json.loads(row.depots or "[]")
    results = json.loads(row.results or "{}")
    errors = json.loads(row.errors or "{}")
    
    return _record_to_api_dict(
        job_id=str(row.job_id),
        truck_id=str(row.truck_id),
        depots=depots if isinstance(depots, list) else [],
        status=str(row.status),
        created_at=float(row.created_at),
        started_at=float(row.started_at) if row.started_at is not None else None,
        completed_at=float(row.completed_at) if row.completed_at is not None else None,
        desired_bids_count=int(row.desired_bids_count),
        results=results if isinstance(results, dict) else {},
        errors=errors if isinstance(errors, dict) else {},
        summary=row.summary,
    )


def finalize_job_from_live_legs(job_id: str) -> bool:
    """Finalize a job only after every configured leg has a terminal rank/control state."""
    if not job_id:
        return False
    try:
        job = load_job_dict(job_id)
        if not job:
            return False
        from .live_bids_store import list_live_bids

        items = list_live_bids(job_id=job_id).get("items", [])
        expected = int(job.get("desired_bids_count") or 0)
        terminal_statuses = {"won", "completed", "stopped"}
        if expected <= 0 or not items:
            return False
        if any(str(item.get("status") or "").lower() not in terminal_statuses for item in items):
            return False

        missing_count = max(0, expected - len(items))
        all_stopped = all(
            str(item.get("status") or "").lower() == "stopped" for item in items
        )
        overall_status = (
            "stopped"
            if all_stopped or any(str(item.get("status") or "").lower() == "stopped" for item in items)
            else "failed"
            if missing_count
            else "completed"
        )
        results: Dict[str, Any] = {}
        for item in items:
            depot = str(item.get("depot") or "")
            if not depot:
                continue
            depot_result = results.setdefault(
                depot,
                {"depot": depot, "status": "completed", "legs": []},
            )
            leg_status = str(item.get("status") or "").lower()
            if leg_status == "stopped":
                depot_result["status"] = "stopped"
            depot_result["legs"].append(
                {
                    "leg_id": item.get("id"),
                    "quantity": item.get("quantity"),
                    "destination": item.get("destination"),
                    "status": leg_status,
                    "final_rank": item.get("current_rank"),
                }
            )

        completed_at = time.time()
        summary = f"terminal_live_legs={len(items)}/{expected}"
        if missing_count:
            summary += f" missing_live_legs={missing_count}"
        if not _use_sqlite():
            engine = get_engine()
            if engine is None:
                return False
            _, jobs_table, _ = get_tables()
            if jobs_table is None:
                return False
            statement = (
                jobs_table.update()
                .where(jobs_table.c.job_id == job_id)
                .where(jobs_table.c.status.in_(("queued", "running")))
                .values(
                    status=overall_status,
                    completed_at=completed_at,
                    results=json.dumps(results, default=str),
                    summary=summary,
                )
            )
            with engine.begin() as connection:
                updated = connection.execute(statement).rowcount
        else:
            with _LOCK:
                connection = _connect()
                try:
                    cursor = connection.execute(
                        """
                        UPDATE bid_jobs
                        SET status = ?, completed_at = ?, results_json = ?, summary = ?, updated_at = ?
                        WHERE job_id = ? AND status IN ('queued', 'running')
                        """,
                        (
                            overall_status,
                            completed_at,
                            json.dumps(results, default=str),
                            summary,
                            utc_now_iso(),
                            job_id,
                        ),
                    )
                    connection.commit()
                    updated = cursor.rowcount
                finally:
                    connection.close()

        if not updated:
            return False
        for item in items:
            depot = str(item.get("depot") or "UNKNOWN")
            try:
                tonnage = f"{float(item.get('quantity')):g}T"
            except (TypeError, ValueError):
                tonnage = "UNKNOWN"
            logger.info(
                "[CONTROL_PANEL][%s][%s] COMPLETED job_id=%s status=%s final_rank=%s",
                depot,
                tonnage,
                job_id,
                item.get("status"),
                item.get("current_rank"),
            )
        return True
    except Exception:
        logger.exception("finalize_job_from_live_legs failed job_id=%s", job_id)
        return False
