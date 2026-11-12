"""
Mixed persistence for Rank-1 successful bids.
Uses SQLite by default. MySQL is used when DATABASE_URL is set and NOT sqlite://.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import insert, select

from .config_loader import BASE_DIR
from .db import get_engine, DATABASE_URL, get_successful_bids_table
from .depot_normalization import normalize_depot_name

_DB_PATH = BASE_DIR / "data" / "successful_bids.db"
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
                CREATE TABLE IF NOT EXISTS successful_bids (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    depot TEXT NOT NULL,
                    destination TEXT,
                    quantity REAL NOT NULL,
                    bid_amount INTEGER NOT NULL,
                    won_timestamp TEXT NOT NULL,
                    rank INTEGER NOT NULL DEFAULT 1 CHECK (rank = 1)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_successful_bids_won_timestamp
                ON successful_bids (won_timestamp)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_successful_bids_depot
                ON successful_bids (depot)
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
    mysql_init()  # This creates all tables including successful_bids


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def insert_successful_bid(
    *,
    depot: str,
    destination: Optional[str],
    quantity: float,
    bid_amount: int,
    won_timestamp: Optional[str] = None,
    rank: int = 1,
) -> Optional[int]:
    """
    Insert one Rank-1 win. Every call creates a new row (no deduplication).
    Returns new row id, or None on failure. Never raises.
    """
    if int(rank) != 1:
        return None
    depot_norm = normalize_depot_name(depot) or str(depot or "").strip().upper()
    if not depot_norm:
        return None
    dest_val = (destination or "").strip() or None
    ts = won_timestamp or utc_now_iso()
    try:
        init_db()
        if not _use_sqlite():
            return _insert_successful_bid_mysql(depot_norm, dest_val, float(quantity), int(bid_amount), ts, rank)
        return _insert_successful_bid_sqlite(depot_norm, dest_val, float(quantity), int(bid_amount), ts, rank)
    except Exception:
        return None


def _insert_successful_bid_sqlite(
    depot: str,
    dest_val: Optional[str],
    quantity: float,
    bid_amount: int,
    ts: str,
    rank: int,
) -> Optional[int]:
    """SQLite implementation for insert_successful_bid."""
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO successful_bids
                    (depot, destination, quantity, bid_amount, won_timestamp, rank)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (depot, dest_val, quantity, bid_amount, ts, 1),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def _insert_successful_bid_mysql(
    depot: str,
    dest_val: Optional[str],
    quantity: float,
    bid_amount: int,
    ts: str,
    rank: int,
) -> Optional[int]:
    """MySQL implementation for insert_successful_bid."""
    engine = get_engine()
    if engine is None:
        return None
    
    bids_table = get_successful_bids_table()
    if bids_table is None:
        return None
    
    with _LOCK:
        with engine.begin() as conn:
            from sqlalchemy import insert
            stmt = insert(bids_table).values(
                depot=depot,
                destination=dest_val,
                quantity=quantity,
                bid_amount=bid_amount,
                won_timestamp=ts,
                rank=rank,
            )
            result = conn.execute(stmt)
            if result.inserted_primary_key:
                return int(result.inserted_primary_key[0])
            return int(result.lastrowid or 0)


def list_successful_bids(
    *,
    month: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    depot: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Query successful bids with optional filters (applied in SQL).
    month: YYYY-MM
    from_date / to_date: YYYY-MM-DD (inclusive, UTC date part of won_timestamp)
    depot: normalized depot name
    """
    if not _use_sqlite():
        return _list_successful_bids_mysql(month=month, from_date=from_date, to_date=to_date, depot=depot)
    return _list_successful_bids_sqlite(month=month, from_date=from_date, to_date=to_date, depot=depot)


def _list_successful_bids_sqlite(
    *,
    month: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    depot: Optional[str] = None,
) -> Dict[str, Any]:
    """SQLite implementation for list_successful_bids."""
    clauses: List[str] = []
    params: List[Any] = []

    if month:
        month = str(month).strip()
        if len(month) == 7 and month[4] == "-":
            clauses.append("substr(won_timestamp, 1, 7) = ?")
            params.append(month)

    if from_date:
        from_date = str(from_date).strip()
        clauses.append("substr(won_timestamp, 1, 10) >= ?")
        params.append(from_date)

    if to_date:
        to_date = str(to_date).strip()
        clauses.append("substr(won_timestamp, 1, 10) <= ?")
        params.append(to_date)

    if depot:
        depot_norm = normalize_depot_name(depot) or str(depot).strip().upper()
        if depot_norm:
            clauses.append("depot = ?")
            params.append(depot_norm)

    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        "SELECT id, depot, destination, quantity, bid_amount, won_timestamp, rank "
        f"FROM successful_bids{where_sql} "
        "ORDER BY won_timestamp DESC, id DESC"
    )

    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    items = [
        {
            "id": int(r["id"]),
            "depot": r["depot"],
            "destination": r["destination"],
            "quantity": float(r["quantity"]),
            "bid_amount": int(r["bid_amount"]),
            "won_timestamp": r["won_timestamp"],
            "rank": int(r["rank"]),
        }
        for r in rows
    ]
    return {"items": items, "total": len(items)}


def _list_successful_bids_mysql(
    *,
    month: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    depot: Optional[str] = None,
) -> Dict[str, Any]:
    """MySQL implementation for list_successful_bids."""
    engine = get_engine()
    if engine is None:
        return {"items": [], "total": 0}
    
    bids_table = get_successful_bids_table()
    if bids_table is None:
        return {"items": [], "total": 0}
    
    conditions = []
    
    if month:
        month = str(month).strip()
        if len(month) == 7 and month[4] == "-":
            from sqlalchemy import func
            conditions.append(func.substring(bids_table.c.won_timestamp, 1, 7) == month)
    
    if from_date:
        from_date = str(from_date).strip()
        from sqlalchemy import func
        conditions.append(func.substring(bids_table.c.won_timestamp, 1, 10) >= from_date)
    
    if to_date:
        to_date = str(to_date).strip()
        from sqlalchemy import func
        conditions.append(func.substring(bids_table.c.won_timestamp, 1, 10) <= to_date)
    
    if depot:
        depot_norm = normalize_depot_name(depot) or str(depot).strip().upper()
        if depot_norm:
            conditions.append(bids_table.c.depot == depot_norm)
    
    with _LOCK:
        with engine.connect() as conn:
            cols = [
                bids_table.c.id,
                bids_table.c.depot,
                bids_table.c.destination,
                bids_table.c.quantity,
                bids_table.c.bid_amount,
                bids_table.c.won_timestamp,
                bids_table.c.rank,
            ]
            stmt = select(*cols)
            if conditions:
                from sqlalchemy import and_
                stmt = stmt.where(and_(*conditions))
            stmt = stmt.order_by(
                bids_table.c.won_timestamp.desc(),
                bids_table.c.id.desc()
            )
            rows = conn.execute(stmt).fetchall()
    
    items = [
        {
            "id": int(r.id),
            "depot": r.depot,
            "destination": r.destination,
            "quantity": float(r.quantity) if r.quantity is not None else 0.0,
            "bid_amount": int(r.bid_amount),
            "won_timestamp": r.won_timestamp,
            "rank": int(r.rank),
        }
        for r in rows
    ]
    return {"items": items, "total": len(items)}
