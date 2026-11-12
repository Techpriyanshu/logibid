"""
Read-only master data store for Control Panel dropdowns.
Tables: zones, plants, plant_depots, depots, depot_destinations, tonnage_options
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from .db import BASE_DIR, DATABASE_URL, get_engine, init_db
from src.logging_service import get_logger

logger = get_logger("master_store")
SNAPSHOT_FILE = BASE_DIR / "config" / "master_data_snapshot.json"


class MasterDataUnavailable(RuntimeError):
    """Raised when the configured master-data database cannot be reached."""


def _database_unavailable_message(error: object = None) -> str:
    error_text = str(error or "").lower()
    connection_failure = any(
        marker in error_text
        for marker in (
            "2003",
            "10061",
            "connection refused",
            "can't connect",
            "could not connect",
            "timed out",
            "timeout",
        )
    )
    if connection_failure and DATABASE_URL:
        try:
            url = make_url(DATABASE_URL)
            if url.host:
                port = url.port or (3306 if url.drivername.startswith(("mysql", "mariadb")) else None)
                address = f"{url.host}:{port}" if port else url.host
                return (
                    f"Cannot connect to the master data database at {address}. "
                    "Start its database service or configure DATABASE_URL to a reachable database."
                )
        except (TypeError, ValueError):
            logger.exception("Could not parse the configured database address")
    return "Master data database is unavailable. Check database configuration and connectivity."


def _is_connection_failure(error: object) -> bool:
    message = str(error or "").lower()
    return any(
        marker in message
        for marker in (
            "2003",
            "10061",
            "connection refused",
            "can't connect",
            "could not connect",
            "timed out",
            "timeout",
        )
    )


@lru_cache(maxsize=1)
def _load_snapshot() -> Dict[str, Any]:
    if not SNAPSHOT_FILE.is_file():
        raise MasterDataUnavailable(_database_unavailable_message())
    try:
        with SNAPSHOT_FILE.open("r", encoding="utf-8") as snapshot_file:
            snapshot = json.load(snapshot_file)
    except (OSError, json.JSONDecodeError) as e:
        logger.exception("Master-data snapshot could not be loaded")
        raise MasterDataUnavailable(
            "Master data database is unavailable and its local snapshot could not be loaded."
        ) from e

    tables = snapshot.get("tables")
    if not isinstance(tables, dict) or not all(
        isinstance(tables.get(table), list)
        for table in ("zones", "plants", "depots", "plant_depots", "depot_destinations", "tonnage_options")
    ):
        raise MasterDataUnavailable("The local master-data snapshot is incomplete.")
    return snapshot


def _unavailable_result(error: object) -> Dict[str, Any]:
    if not _is_connection_failure(error):
        raise MasterDataUnavailable(_database_unavailable_message(error))
    snapshot = _load_snapshot()
    logger.warning(
        "Serving read-only master data snapshot dated %s because MySQL is unavailable",
        snapshot.get("snapshot_date", "unknown"),
    )
    return {
        "source": "snapshot",
        "snapshot_date": snapshot.get("snapshot_date"),
        "tables": snapshot["tables"],
    }


def _result(items: list, source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {"items": items, "total": len(items), "source": "database"}
    if source:
        result["source"] = source["source"]
        result["snapshot_date"] = source.get("snapshot_date")
    return result


def _database_source(engine) -> Optional[Dict[str, Any]]:
    with engine.connect() as conn:
        if not conn.dialect.has_table(conn, "master_data_status"):
            return None
        status = conn.execute(text(
            "SELECT source, snapshot_date, verified FROM master_data_status WHERE id = 1"
        )).mappings().first()
    if status is None:
        return {"source": "snapshot", "snapshot_date": None}
    if not status["verified"]:
        return {
            "source": "snapshot",
            "snapshot_date": _str(status["snapshot_date"]),
        }
    return None


def _to_dict(row) -> Dict[str, Any]:
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    if hasattr(row, "keys"):
        return dict(zip(row.keys(), tuple(row)))
    return dict(row)


def _str(val) -> str:
    if val is None:
        return ""
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(val)


def _get_engine():
    try:
        eng = get_engine()
    except Exception as e:
        logger.exception("Master data database initialization failed")
        if _is_connection_failure(e):
            return None
        raise MasterDataUnavailable(_database_unavailable_message(e)) from e
    if eng is None:
        error = init_db()
        if _is_connection_failure(error):
            return None
        logger.error("Master data database is unavailable")
        raise MasterDataUnavailable(_database_unavailable_message(error))
    return eng


def require_live_master_data() -> None:
    """Reject bids unless master data is live and explicitly verified."""
    eng = _get_engine()
    if eng is None:
        raise MasterDataUnavailable(
            f"{_database_unavailable_message(init_db())} "
            "Live bidding is disabled while only snapshot master data is available."
        )
    try:
        with eng.begin() as conn:
            if conn.dialect.has_table(conn, "master_data_status"):
                status = conn.execute(text(
                    "SELECT verified, snapshot_date FROM master_data_status WHERE id = 1"
                )).mappings().first()
                if status is None:
                    raise MasterDataUnavailable(
                        "Master-data verification status is missing. Live bidding is disabled."
                    )
                if not status["verified"]:
                    date = _str(status["snapshot_date"]) or "unknown date"
                    raise MasterDataUnavailable(
                        f"Master data is an unverified backup from {date}. "
                        "Verify the mappings before enabling live bidding."
                    )
            for table in (
                "zones",
                "plants",
                "depots",
                "plant_depots",
                "depot_destinations",
                "tonnage_options",
            ):
                count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
                if count < 1:
                    raise MasterDataUnavailable(
                        f"Live master-data table '{table}' is empty. Live bidding is disabled."
                    )
    except OperationalError as e:
        logger.exception("Live master-data readiness check failed")
        raise MasterDataUnavailable(_database_unavailable_message(e)) from e


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

def list_zones() -> Dict[str, Any]:
    try:
        eng = _get_engine()
        if eng is None:
            snapshot = _unavailable_result(init_db())
            items = [
                {"id": str(row["id"]), "code": row["code"], "name": row["name"]}
                for row in snapshot["tables"]["zones"]
                if row.get("is_active", 1)
            ]
            items.sort(key=lambda row: row["name"])
            return _result(items, snapshot)
        with eng.begin() as conn:
            rows = conn.execute(text(
                "SELECT id, code, name, is_active FROM zones WHERE is_active = 1 ORDER BY name ASC"
            )).fetchall()
        items = [{"id": str(_to_dict(r)["id"]), "code": _to_dict(r)["code"], "name": _to_dict(r)["name"]} for r in rows]
        logger.info("list_zones -> total=%d", len(items))
        return _result(items, _database_source(eng))
    except OperationalError as e:
        snapshot = _unavailable_result(e)
        items = [
            {"id": str(row["id"]), "code": row["code"], "name": row["name"]}
            for row in snapshot["tables"]["zones"]
            if row.get("is_active", 1)
        ]
        items.sort(key=lambda row: row["name"])
        return _result(items, snapshot)
    except Exception:
        logger.exception("list_zones -> failed")
        raise


# ---------------------------------------------------------------------------
# Plants
# ---------------------------------------------------------------------------

def list_plants(zone_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        eng = _get_engine()
        if eng is None:
            snapshot = _unavailable_result(init_db())
            zones = {row["id"]: row["name"] for row in snapshot["tables"]["zones"]}
            items = [
                {
                    "id": str(row["id"]),
                    "code": row["code"],
                    "name": row["name"],
                    "zone_id": str(row["zone_id"]),
                    "zone_name": zones.get(row["zone_id"], ""),
                }
                for row in snapshot["tables"]["plants"]
                if row.get("is_active", 1)
                and (not zone_id or str(row["zone_id"]) == str(zone_id))
            ]
            items.sort(key=lambda row: row["name"])
            return _result(items, snapshot)
        params: Dict[str, Any] = {}
        where = "WHERE p.is_active = 1"
        if zone_id:
            where += " AND p.zone_id = :zone_id"
            params["zone_id"] = int(zone_id)
        sql = text(f"""
            SELECT p.id, p.code, p.name, p.zone_id, z.name AS zone_name
            FROM plants p
            JOIN zones z ON z.id = p.zone_id
            {where}
            ORDER BY p.name ASC
        """)
        with eng.begin() as conn:
            rows = conn.execute(sql, params).fetchall()
        items = []
        for r in rows:
            d = _to_dict(r)
            items.append({"id": str(d["id"]), "code": d["code"], "name": d["name"],
                          "zone_id": str(d["zone_id"]), "zone_name": d["zone_name"]})
        logger.info("list_plants -> zone_id=%s total=%d", zone_id, len(items))
        return _result(items, _database_source(eng))
    except OperationalError as e:
        snapshot = _unavailable_result(e)
        zones = {row["id"]: row["name"] for row in snapshot["tables"]["zones"]}
        items = [
            {
                "id": str(row["id"]),
                "code": row["code"],
                "name": row["name"],
                "zone_id": str(row["zone_id"]),
                "zone_name": zones.get(row["zone_id"], ""),
            }
            for row in snapshot["tables"]["plants"]
            if row.get("is_active", 1)
            and (not zone_id or str(row["zone_id"]) == str(zone_id))
        ]
        items.sort(key=lambda row: row["name"])
        return _result(items, snapshot)
    except Exception:
        logger.exception("list_plants -> failed")
        raise


# ---------------------------------------------------------------------------
# Depots for a plant
# ---------------------------------------------------------------------------

def list_depots_for_plant(plant_id: str) -> Dict[str, Any]:
    try:
        eng = _get_engine()
        if eng is None:
            snapshot = _unavailable_result(init_db())
            depots = {row["code"]: row for row in snapshot["tables"]["depots"]}
            mappings = [
                row for row in snapshot["tables"]["plant_depots"]
                if str(row["plant_id"]) == str(plant_id)
            ]
            mappings.sort(key=lambda row: (row.get("sort_order", 0), row["depot_code"]))
            items = []
            for mapping in mappings:
                depot = depots.get(mapping["depot_code"])
                if depot is None:
                    continue
                metadata = depot.get("metadata")
                meta = json.loads(metadata) if isinstance(metadata, str) else (metadata or {})
                items.append({
                    "id": str(depot["id"]),
                    "code": depot["code"],
                    "name": depot.get("name") or depot["code"],
                    "sap_depot_id": mapping.get("sap_depot_id") or "",
                    "quantity_only": bool(meta.get("quantity_only", False)),
                })
            return _result(items, snapshot)
        with eng.begin() as conn:
            rows = conn.execute(text("""
                SELECT d.id, d.code, d.name, pd.sap_depot_id, pd.sort_order,
                       d.metadata
                FROM plant_depots pd
                JOIN depots d ON d.code = pd.depot_code
                WHERE pd.plant_id = :plant_id
                ORDER BY pd.sort_order ASC, d.name ASC
            """), {"plant_id": int(plant_id)}).fetchall()
        items = []
        for r in rows:
            d = _to_dict(r)
            meta = {}
            if d.get("metadata"):
                try:
                    meta = json.loads(d["metadata"]) if isinstance(d["metadata"], str) else d["metadata"]
                except (TypeError, json.JSONDecodeError) as e:
                    logger.exception("Invalid depot metadata for depot %s", d.get("code"))
                    raise ValueError(f"Invalid depot metadata for depot {d.get('code')}") from e
            items.append({
                "id": str(d["id"]),
                "code": d["code"],
                "name": d["name"],
                "sap_depot_id": d.get("sap_depot_id") or "",
                "quantity_only": bool(meta.get("quantity_only", False)),
            })
        logger.info("list_depots_for_plant -> plant_id=%s total=%d", plant_id, len(items))
        return _result(items, _database_source(eng))
    except OperationalError as e:
        snapshot = _unavailable_result(e)
        depots = {row["code"]: row for row in snapshot["tables"]["depots"]}
        mappings = [
            row for row in snapshot["tables"]["plant_depots"]
            if str(row["plant_id"]) == str(plant_id)
        ]
        mappings.sort(key=lambda row: (row.get("sort_order", 0), row["depot_code"]))
        items = []
        for mapping in mappings:
            depot = depots.get(mapping["depot_code"])
            if depot is None:
                continue
            metadata = depot.get("metadata")
            meta = json.loads(metadata) if isinstance(metadata, str) else (metadata or {})
            items.append({
                "id": str(depot["id"]),
                "code": depot["code"],
                "name": depot.get("name") or depot["code"],
                "sap_depot_id": mapping.get("sap_depot_id") or "",
                "quantity_only": bool(meta.get("quantity_only", False)),
            })
        return _result(items, snapshot)
    except Exception:
        logger.exception("list_depots_for_plant -> failed")
        raise


def list_all_depots() -> Dict[str, Any]:
    """List all available depots."""
    try:
        eng = _get_engine()
        if eng is None:
            snapshot = _unavailable_result(init_db())
            items = [
                {"id": str(row["id"]), "code": row["code"], "name": row["name"]}
                for row in snapshot["tables"]["depots"]
            ]
            items.sort(key=lambda row: row["name"])
            return _result(items, snapshot)
        with eng.begin() as conn:
            rows = conn.execute(text("""
                SELECT id, code, name FROM depots
                ORDER BY name ASC
            """)).fetchall()
        items = [
            {"id": str(_to_dict(r)["id"]), "code": _to_dict(r)["code"], "name": _to_dict(r)["name"]}
            for r in rows
        ]
        return _result(items, _database_source(eng))
    except OperationalError as e:
        snapshot = _unavailable_result(e)
        items = [
            {"id": str(row["id"]), "code": row["code"], "name": row["name"]}
            for row in snapshot["tables"]["depots"]
        ]
        items.sort(key=lambda row: row["name"])
        return _result(items, snapshot)
    except Exception:
        logger.exception("list_all_depots -> failed")
        raise


# ---------------------------------------------------------------------------
# Destinations for a depot
# ---------------------------------------------------------------------------

def list_destinations_for_depot(depot_code: str) -> Dict[str, Any]:
    try:
        eng = _get_engine()
        if eng is None:
            snapshot = _unavailable_result(init_db())
            code = depot_code.upper()
            items = [
                row
                for row in snapshot["tables"]["depot_destinations"]
                if row["depot_code"].upper() == code
            ]
            items.sort(key=lambda row: (row.get("sort_order", 0), row["destination"]))
            return _result([row["destination"] for row in items], snapshot)
        with eng.begin() as conn:
            rows = conn.execute(text("""
                SELECT destination FROM depot_destinations
                WHERE depot_code = :code
                ORDER BY sort_order ASC, destination ASC
            """), {"code": depot_code.upper()}).fetchall()
        items = [_to_dict(r)["destination"] for r in rows]
        logger.info("list_destinations_for_depot -> depot=%s total=%d", depot_code, len(items))
        return _result(items, _database_source(eng))
    except OperationalError as e:
        snapshot = _unavailable_result(e)
        code = depot_code.upper()
        items = [
            row
            for row in snapshot["tables"]["depot_destinations"]
            if row["depot_code"].upper() == code
        ]
        items.sort(key=lambda row: (row.get("sort_order", 0), row["destination"]))
        return _result([row["destination"] for row in items], snapshot)
    except Exception:
        logger.exception("list_destinations_for_depot -> failed")
        raise


# ---------------------------------------------------------------------------
# Tonnage options
# ---------------------------------------------------------------------------

def list_tonnage_options() -> Dict[str, Any]:
    try:
        eng = _get_engine()
        if eng is None:
            snapshot = _unavailable_result(init_db())
            items = [
                {"id": str(row["id"]), "value": int(row["value"]), "label": row["label"]}
                for row in snapshot["tables"]["tonnage_options"]
                if row.get("is_active", 1)
            ]
            items.sort(key=lambda row: row["value"])
            return _result(items, snapshot)
        with eng.begin() as conn:
            rows = conn.execute(text(
                "SELECT id, value, label FROM tonnage_options WHERE is_active = 1 ORDER BY sort_order ASC"
            )).fetchall()
        items = [{"id": str(_to_dict(r)["id"]), "value": int(_to_dict(r)["value"]), "label": _to_dict(r)["label"]} for r in rows]
        logger.info("list_tonnage_options -> total=%d", len(items))
        return _result(items, _database_source(eng))
    except OperationalError as e:
        snapshot = _unavailable_result(e)
        items = [
            {"id": str(row["id"]), "value": int(row["value"]), "label": row["label"]}
            for row in snapshot["tables"]["tonnage_options"]
            if row.get("is_active", 1)
        ]
        items.sort(key=lambda row: row["value"])
        return _result(items, snapshot)
    except Exception:
        logger.exception("list_tonnage_options -> failed")
        raise
