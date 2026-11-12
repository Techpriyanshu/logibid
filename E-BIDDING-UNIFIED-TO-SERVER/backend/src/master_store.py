"""
Read-only master data store for Control Panel dropdowns.
Tables: zones, plants, plant_depots, depots, depot_destinations, tonnage_options
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from sqlalchemy import text
from .db import get_engine
from src.logging_service import get_logger

logger = get_logger("master_store")


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


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

def list_zones() -> Dict[str, Any]:
    from .db import init_db as mysql_init
    mysql_init()  # Ensure database is initialized before checking engine
    eng = get_engine()
    if eng is None:
        logger.warning("list_zones -> no DB engine")
        # Return empty list if database is not configured
        return {"items": [], "total": 0}
    try:
        with eng.begin() as conn:
            rows = conn.execute(text(
                "SELECT id, code, name, is_active FROM zones WHERE is_active = 1 ORDER BY name ASC"
            )).fetchall()
        items = [{"id": str(_to_dict(r)["id"]), "code": _to_dict(r)["code"], "name": _to_dict(r)["name"]} for r in rows]
        logger.info("list_zones -> total=%d", len(items))
        return {"items": items, "total": len(items)}
    except Exception:
        logger.exception("list_zones -> failed")
        return {"items": [], "total": 0}


# ---------------------------------------------------------------------------
# Plants
# ---------------------------------------------------------------------------

def list_plants(zone_id: Optional[str] = None) -> Dict[str, Any]:
    from .db import init_db as mysql_init
    mysql_init()  # Ensure database is initialized before checking engine
    eng = get_engine()
    if eng is None:
        logger.warning("list_plants -> no DB engine")
        return {"items": [], "total": 0}
    try:
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
        return {"items": items, "total": len(items)}
    except Exception:
        logger.exception("list_plants -> failed")
        return {"items": [], "total": 0}


# ---------------------------------------------------------------------------
# Depots for a plant
# ---------------------------------------------------------------------------

def list_depots_for_plant(plant_id: str) -> Dict[str, Any]:
    from .db import init_db as mysql_init
    mysql_init()  # Ensure database is initialized before checking engine
    eng = get_engine()
    if eng is None:
        logger.warning("list_depots_for_plant -> no DB engine")
        return {"items": [], "total": 0}
    try:
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
            import json as _json
            meta = {}
            if d.get("metadata"):
                try:
                    meta = _json.loads(d["metadata"]) if isinstance(d["metadata"], str) else d["metadata"]
                except Exception:
                    pass
            items.append({
                "id": str(d["id"]),
                "code": d["code"],
                "name": d["name"],
                "sap_depot_id": d.get("sap_depot_id") or "",
                "quantity_only": bool(meta.get("quantity_only", False)),
            })
        logger.info("list_depots_for_plant -> plant_id=%s total=%d", plant_id, len(items))
        return {"items": items, "total": len(items)}
    except Exception:
        logger.exception("list_depots_for_plant -> failed")
        return {"items": [], "total": 0}


# ---------------------------------------------------------------------------
# Destinations for a depot
# ---------------------------------------------------------------------------

def list_destinations_for_depot(depot_code: str) -> Dict[str, Any]:
    eng = get_engine()
    if eng is None:
        logger.warning("list_destinations_for_depot -> no DB engine")
        return {"items": [], "total": 0}
    try:
        with eng.begin() as conn:
            rows = conn.execute(text("""
                SELECT destination FROM depot_destinations
                WHERE depot_code = :code
                ORDER BY sort_order ASC, destination ASC
            """), {"code": depot_code.upper()}).fetchall()
        items = [_to_dict(r)["destination"] for r in rows]
        logger.info("list_destinations_for_depot -> depot=%s total=%d", depot_code, len(items))
        return {"items": items, "total": len(items)}
    except Exception:
        logger.exception("list_destinations_for_depot -> failed")
        return {"items": [], "total": 0}


# ---------------------------------------------------------------------------
# Tonnage options
# ---------------------------------------------------------------------------

def list_tonnage_options() -> Dict[str, Any]:
    eng = get_engine()
    if eng is None:
        logger.warning("list_tonnage_options -> no DB engine")
        return {"items": [], "total": 0}
    try:
        with eng.begin() as conn:
            rows = conn.execute(text(
                "SELECT id, value, label FROM tonnage_options WHERE is_active = 1 ORDER BY sort_order ASC"
            )).fetchall()
        items = [{"id": str(_to_dict(r)["id"]), "value": int(_to_dict(r)["value"]), "label": _to_dict(r)["label"]} for r in rows]
        logger.info("list_tonnage_options -> total=%d", len(items))
        return {"items": items, "total": len(items)}
    except Exception:
        logger.exception("list_tonnage_options -> failed")
        return {"items": [], "total": 0}
