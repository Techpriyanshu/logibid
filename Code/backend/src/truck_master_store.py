"""
SQLite persistence for Truck Master (permanent fleet registry).
Isolated from Selenium / bidding engine logic.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config_loader import BASE_DIR

_DB_PATH = BASE_DIR / "data" / "truck_master.db"
_DOCS_DIR = BASE_DIR / "data" / "truck_documents"
_LOCK = threading.Lock()

PHASE1_SEED_TRUCKS: Tuple[Tuple[str, str], ...] = (
    ("UP43AT4492", "SURESH YADAV"),
    ("UP43T4492", "AMAR KUMAR"),
    ("UP42BT3401", "RAHUL KUMAR SINGH"),
    ("UP42BT1728", "VINOD YADAV"),
    ("UP42BT4828", "JAI PRAKASH PANDEY"),
    ("UP42AT1980", "AWDHESH KUMAR YADAV"),
)

VALID_STATUSES = frozenset({"Active", "Non-Active"})
VALID_DOC_TYPES = frozenset(
    {"Insurance", "RC", "Driver License", "Purchase Invoice", "Other"}
)

_TRUCK_COLUMN_MIGRATIONS: Tuple[Tuple[str, str], ...] = (
    ("tonnage", "TEXT NOT NULL DEFAULT '32T'"),
    ("status", "TEXT NOT NULL DEFAULT 'Active'"),
    ("rotation_count", "INTEGER NOT NULL DEFAULT 0"),
    ("plant_id", "TEXT NOT NULL DEFAULT '1'"),
    ("plant_name", "TEXT NOT NULL DEFAULT 'Tanda Cement Plant'"),
    ("depot_id", "TEXT NOT NULL DEFAULT '6601'"),
    ("depot_name", "TEXT NOT NULL DEFAULT 'LUCKNOW'"),
)


def _db_path() -> Path:
    return _DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_truck_number(truck_number: str) -> str:
    return str(truck_number or "").strip().upper()


def make_truck_id(truck_number: str) -> str:
    """Deterministic id from normalized truck number."""
    norm = normalize_truck_number(truck_number)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(r[1]) for r in rows}


def _migrate_trucks_schema(conn: sqlite3.Connection) -> None:
    """Additive column migrations only; never drops or recreates."""
    existing = _existing_columns(conn, "trucks")
    for col_name, col_def in _TRUCK_COLUMN_MIGRATIONS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE trucks ADD COLUMN {col_name} {col_def}")


def init_db() -> None:
    """Create data directory, enable WAL, ensure tables exist, seed phase-1 rows."""
    with _LOCK:
        _db_path().parent.mkdir(parents=True, exist_ok=True)
        _DOCS_DIR.mkdir(parents=True, exist_ok=True)
        conn = _connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trucks (
                    id TEXT PRIMARY KEY,
                    truck_number TEXT NOT NULL UNIQUE,
                    driver_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            _migrate_trucks_schema(conn)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trucks_truck_number
                ON trucks (truck_number)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vehicle_documents (
                    id TEXT PRIMARY KEY,
                    truck_id TEXT NOT NULL,
                    doc_type TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    expiry_date TEXT,
                    uploaded_at TEXT NOT NULL,
                    FOREIGN KEY (truck_id) REFERENCES trucks(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_vehicle_documents_truck_id
                ON vehicle_documents (truck_id)
                """
            )
            ts = utc_now_iso()
            for truck_number, driver_name in PHASE1_SEED_TRUCKS:
                norm = normalize_truck_number(truck_number)
                truck_id = make_truck_id(norm)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO trucks
                        (id, truck_number, driver_name, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (truck_id, norm, str(driver_name).strip(), ts, ts),
                )
            conn.commit()
        finally:
            conn.close()


def _row_to_truck_item(row: sqlite3.Row, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "truck_number": row["truck_number"],
        "driver_name": row["driver_name"],
        "tonnage": row["tonnage"] if "tonnage" in row.keys() else "32T",
        "status": row["status"] if "status" in row.keys() else "Active",
        "rotation_count": int(row["rotation_count"]) if "rotation_count" in row.keys() else 0,
        "plant_id": row["plant_id"] if "plant_id" in row.keys() else "1",
        "plant_name": row["plant_name"] if "plant_name" in row.keys() else "Tanda Cement Plant",
        "depot_id": row["depot_id"] if "depot_id" in row.keys() else "6601",
        "depot_name": row["depot_name"] if "depot_name" in row.keys() else "LUCKNOW",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "documents": documents,
    }


def _fetch_documents_for_truck(conn: sqlite3.Connection, truck_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, truck_id, doc_type, file_name, stored_path, expiry_date, uploaded_at
        FROM vehicle_documents
        WHERE truck_id = ?
        ORDER BY uploaded_at DESC
        """,
        (truck_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "truck_id": r["truck_id"],
            "type": r["doc_type"],
            "file_name": r["file_name"],
            "file_url": f"/api/trucks/{truck_id}/documents/{r['id']}/file",
            "expiry_date": r["expiry_date"],
            "uploaded_at": r["uploaded_at"],
        }
        for r in rows
    ]


def list_trucks() -> Dict[str, Any]:
    """Return all trucks ordered by truck_number, with documents."""
    try:
        init_db()
        with _LOCK:
            conn = _connect()
            try:
                rows = conn.execute(
                    """
                    SELECT id, truck_number, driver_name, tonnage, status,
                           rotation_count, plant_id, plant_name, depot_id, depot_name,
                           created_at, updated_at
                    FROM trucks
                    ORDER BY truck_number ASC
                    """
                ).fetchall()
                items = []
                for r in rows:
                    docs = _fetch_documents_for_truck(conn, r["id"])
                    items.append(_row_to_truck_item(r, docs))
            finally:
                conn.close()
        return {"items": items, "total": len(items)}
    except Exception:
        return {"items": [], "total": 0}


def get_truck(truck_id: str) -> Optional[Dict[str, Any]]:
    try:
        init_db()
        with _LOCK:
            conn = _connect()
            try:
                row = conn.execute(
                    """
                    SELECT id, truck_number, driver_name, tonnage, status,
                           rotation_count, plant_id, plant_name, depot_id, depot_name,
                           created_at, updated_at
                    FROM trucks
                    WHERE id = ?
                    """,
                    (truck_id,),
                ).fetchone()
                if row is None:
                    return None
                docs = _fetch_documents_for_truck(conn, truck_id)
                return _row_to_truck_item(row, docs)
            finally:
                conn.close()
    except Exception:
        return None


def create_truck(
    *,
    truck_number: str,
    driver_name: str,
    tonnage: str = "32T",
    status: str = "Active",
    rotation_count: int = 0,
    plant_id: str = "1",
    plant_name: str = "Tanda Cement Plant",
    depot_id: str = "6601",
    depot_name: str = "LUCKNOW",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    norm = normalize_truck_number(truck_number)
    driver = str(driver_name or "").strip()
    if not norm:
        return None, "truck_number is required"
    if not driver:
        return None, "driver_name is required"
    if status not in VALID_STATUSES:
        return None, f"status must be one of: {', '.join(sorted(VALID_STATUSES))}"
    try:
        init_db()
        truck_id = make_truck_id(norm)
        ts = utc_now_iso()
        with _LOCK:
            conn = _connect()
            try:
                existing = conn.execute(
                    "SELECT id FROM trucks WHERE truck_number = ?",
                    (norm,),
                ).fetchone()
                if existing is not None:
                    return None, "truck_number already exists"
                conn.execute(
                    """
                    INSERT INTO trucks (
                        id, truck_number, driver_name, tonnage, status,
                        rotation_count, plant_id, plant_name, depot_id, depot_name,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        truck_id,
                        norm,
                        driver,
                        str(tonnage or "32T").strip(),
                        status,
                        int(rotation_count),
                        str(plant_id or "1").strip(),
                        str(plant_name or "Tanda Cement Plant").strip(),
                        str(depot_id or "").strip(),
                        str(depot_name or "").strip(),
                        ts,
                        ts,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return get_truck(truck_id), None
    except Exception as e:
        return None, str(e)


def update_truck(
    truck_id: str,
    *,
    driver_name: Optional[str] = None,
    tonnage: Optional[str] = None,
    status: Optional[str] = None,
    rotation_count: Optional[int] = None,
    plant_id: Optional[str] = None,
    plant_name: Optional[str] = None,
    depot_id: Optional[str] = None,
    depot_name: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if status is not None and status not in VALID_STATUSES:
        return None, f"status must be one of: {', '.join(sorted(VALID_STATUSES))}"
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
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if rotation_count is not None:
            sets.append("rotation_count = ?")
            params.append(int(rotation_count))
        if plant_id is not None:
            sets.append("plant_id = ?")
            params.append(str(plant_id).strip())
        if plant_name is not None:
            sets.append("plant_name = ?")
            params.append(str(plant_name).strip())
        if depot_id is not None:
            sets.append("depot_id = ?")
            params.append(str(depot_id).strip())
        if depot_name is not None:
            sets.append("depot_name = ?")
            params.append(str(depot_name).strip())
        if len(sets) == 1:
            return get_truck(truck_id), None
        params.append(truck_id)
        with _LOCK:
            conn = _connect()
            try:
                cur = conn.execute(
                    f"UPDATE trucks SET {', '.join(sets)} WHERE id = ?",
                    params,
                )
                conn.commit()
                if cur.rowcount == 0:
                    return None, "truck not found"
            finally:
                conn.close()
        return get_truck(truck_id), None
    except Exception as e:
        return None, str(e)


def delete_truck(truck_id: str) -> Tuple[bool, Optional[str]]:
    try:
        init_db()
        with _LOCK:
            conn = _connect()
            try:
                row = conn.execute(
                    "SELECT id FROM trucks WHERE id = ?",
                    (truck_id,),
                ).fetchone()
                if row is None:
                    return False, "truck not found"
                doc_rows = conn.execute(
                    "SELECT stored_path FROM vehicle_documents WHERE truck_id = ?",
                    (truck_id,),
                ).fetchall()
                conn.execute("DELETE FROM vehicle_documents WHERE truck_id = ?", (truck_id,))
                conn.execute("DELETE FROM trucks WHERE id = ?", (truck_id,))
                conn.commit()
            finally:
                conn.close()
        for dr in doc_rows:
            try:
                p = Path(dr["stored_path"])
                if p.is_file():
                    p.unlink()
            except Exception:
                pass
        truck_dir = _DOCS_DIR / truck_id
        if truck_dir.exists():
            try:
                shutil.rmtree(truck_dir, ignore_errors=True)
            except Exception:
                pass
        return True, None
    except Exception as e:
        return False, str(e)


def get_document_file_path(truck_id: str, document_id: str) -> Optional[Path]:
    try:
        init_db()
        with _LOCK:
            conn = _connect()
            try:
                row = conn.execute(
                    """
                    SELECT stored_path FROM vehicle_documents
                    WHERE id = ? AND truck_id = ?
                    """,
                    (document_id, truck_id),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return None
        path = Path(row["stored_path"])
        return path if path.is_file() else None
    except Exception:
        return None


def add_vehicle_document(
    truck_id: str,
    *,
    doc_type: str,
    file_name: str,
    file_bytes: bytes,
    expiry_date: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    dtype = str(doc_type or "").strip()
    if dtype not in VALID_DOC_TYPES:
        return None, f"doc_type must be one of: {', '.join(sorted(VALID_DOC_TYPES))}"
    if dtype == "Insurance" and not expiry_date:
        return None, "expiry_date is required for Insurance documents"
    if not file_bytes:
        return None, "file is required"
    try:
        init_db()
        with _LOCK:
            conn = _connect()
            try:
                row = conn.execute(
                    "SELECT id FROM trucks WHERE id = ?",
                    (truck_id,),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return None, "truck not found"
        doc_id = uuid.uuid4().hex[:16]
        safe_name = Path(file_name).name or "document"
        truck_dir = _DOCS_DIR / truck_id
        truck_dir.mkdir(parents=True, exist_ok=True)
        stored_path = truck_dir / f"{doc_id}_{safe_name}"
        stored_path.write_bytes(file_bytes)
        ts = utc_now_iso()
        with _LOCK:
            conn = _connect()
            try:
                conn.execute(
                    """
                    INSERT INTO vehicle_documents
                        (id, truck_id, doc_type, file_name, stored_path, expiry_date, uploaded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        truck_id,
                        dtype,
                        safe_name,
                        str(stored_path),
                        expiry_date,
                        ts,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return {
            "id": doc_id,
            "truck_id": truck_id,
            "type": dtype,
            "file_name": safe_name,
            "file_url": f"/api/trucks/{truck_id}/documents/{doc_id}/file",
            "expiry_date": expiry_date,
            "uploaded_at": ts,
        }, None
    except Exception as e:
        return None, str(e)
