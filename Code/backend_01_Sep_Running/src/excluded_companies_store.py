"""
Store for depot-wise excluded companies (MySQL backed with application.yaml auto-seed).
Table: excluded_companies_by_depot
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import select, insert, update, delete, text
from .db import get_engine, get_excluded_companies_table
from .config_loader import normalize_company_name, normalize_depot_name, get_app_config
from .logging_service import get_logger

logger = get_logger("excluded_companies_store")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _to_dict(row) -> Dict[str, Any]:
    if hasattr(row, "_mapping"):
        d = dict(row._mapping)
    elif hasattr(row, "keys"):
        d = dict(zip(row.keys(), tuple(row)))
    else:
        d = dict(row)
    return {
        "id": int(d.get("id", 0)),
        "depot_code": str(d.get("depot_code") or "").upper(),
        "company_name": str(d.get("company_name") or ""),
        "reason": str(d.get("reason") or "") if d.get("reason") is not None else None,
        "is_active": bool(d.get("is_active", 1)),
        "created_at": str(d.get("created_at") or ""),
        "updated_at": str(d.get("updated_at") or ""),
    }


def seed_from_yaml_if_empty() -> int:
    """
    If the database table has 0 rows, auto-seed it with the excluded_companies_by_depot
    from application.yaml so existing rules are preserved seamlessly.
    """
    table = get_excluded_companies_table()
    eng = get_engine()
    if eng is None or table is None:
        return 0

    try:
        with eng.begin() as conn:
            cnt = conn.execute(select(table.c.id).limit(1)).fetchone()
            if cnt is not None:
                return 0  # Already has data

            cfg = get_app_config()
            raw = cfg.get("excluded_companies_by_depot") or {}
            if not isinstance(raw, dict):
                return 0

            seeded_count = 0
            now = _now_iso()
            for depot_raw, companies in raw.items():
                depot = normalize_depot_name(str(depot_raw))
                if not depot or not companies:
                    continue
                co_list = companies if isinstance(companies, (list, tuple, set)) else [companies]
                for c in co_list:
                    c_name = str(c or "").strip()
                    if not c_name:
                        continue
                    conn.execute(
                        insert(table).values(
                            depot_code=depot,
                            company_name=c_name,
                            reason="Seeded from configuration",
                            is_active=1,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    seeded_count += 1

            if seeded_count > 0:
                logger.info("Auto-seeded %d excluded companies into excluded_companies_by_depot", seeded_count)
            return seeded_count
    except Exception as e:
        logger.warning("seed_from_yaml_if_empty error (non-fatal): %s", e)
        return 0


def list_excluded_companies(
    depot_code: Optional[str] = None,
    search: Optional[str] = None,
    active_only: bool = False,
) -> Dict[str, Any]:
    """
    List excluded companies with optional filters.
    """
    seed_from_yaml_if_empty()
    table = get_excluded_companies_table()
    eng = get_engine()
    if eng is None or table is None:
        return {"items": [], "total": 0}

    stmt = select(table)
    if depot_code:
        norm_depot = normalize_depot_name(depot_code)
        if norm_depot:
            stmt = stmt.where(table.c.depot_code == norm_depot)

    if active_only:
        stmt = stmt.where(table.c.is_active == 1)

    if search:
        term = f"%{search.strip().lower()}%"
        from sqlalchemy import or_, func
        stmt = stmt.where(
            or_(
                func.lower(table.c.company_name).like(term),
                func.lower(table.c.depot_code).like(term),
                func.lower(table.c.reason).like(term),
            )
        )

    stmt = stmt.order_by(table.c.depot_code.asc(), table.c.company_name.asc())

    try:
        with eng.begin() as conn:
            rows = conn.execute(stmt).fetchall()
        items = [_to_dict(r) for r in rows]
        return {"items": items, "total": len(items)}
    except Exception as e:
        logger.exception("list_excluded_companies failed: %s", e)
        return {"items": [], "total": 0}


def get_excluded_company(item_id: int) -> Optional[Dict[str, Any]]:
    table = get_excluded_companies_table()
    eng = get_engine()
    if eng is None or table is None:
        return None

    try:
        with eng.begin() as conn:
            row = conn.execute(select(table).where(table.c.id == int(item_id))).fetchone()
        return _to_dict(row) if row else None
    except Exception as e:
        logger.exception("get_excluded_company failed for id=%s: %s", item_id, e)
        return None


def create_excluded_company(
    depot_code: str,
    company_name: str,
    reason: Optional[str] = None,
    is_active: bool = True,
) -> Dict[str, Any]:
    """
    Add a new excluded company for a depot.
    """
    depot = normalize_depot_name(depot_code)
    company = " ".join(str(company_name or "").strip().split())

    if not depot:
        raise ValueError("depot_code is required")
    if not company:
        raise ValueError("company_name is required")

    table = get_excluded_companies_table()
    eng = get_engine()
    if eng is None or table is None:
        raise RuntimeError("Database engine not available")

    now = _now_iso()
    try:
        with eng.begin() as conn:
            # Check duplicate (casefold comparison)
            from sqlalchemy import func
            existing = conn.execute(
                select(table.c.id).where(
                    table.c.depot_code == depot,
                    func.lower(table.c.company_name) == company.lower(),
                )
            ).fetchone()
            if existing:
                raise ValueError(f"Company '{company}' is already excluded for depot '{depot}'")

            result = conn.execute(
                insert(table).values(
                    depot_code=depot,
                    company_name=company,
                    reason=reason.strip() if reason else None,
                    is_active=1 if is_active else 0,
                    created_at=now,
                    updated_at=now,
                )
            )
            new_id = result.inserted_primary_key[0] if result.inserted_primary_key else None
            row = conn.execute(select(table).where(table.c.id == new_id)).fetchone()
            logger.info("[EXCLUDED_COMPANIES] Created id=%s depot=%s company=%r", new_id, depot, company)
            return _to_dict(row) if row else {
                "id": new_id,
                "depot_code": depot,
                "company_name": company,
                "reason": reason,
                "is_active": is_active,
                "created_at": now,
                "updated_at": now,
            }
    except ValueError:
        raise
    except Exception as e:
        logger.exception("create_excluded_company failed: %s", e)
        raise RuntimeError(str(e)) from e


def update_excluded_company(
    item_id: int,
    depot_code: Optional[str] = None,
    company_name: Optional[str] = None,
    reason: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """
    Modify an existing excluded company entry.
    """
    table = get_excluded_companies_table()
    eng = get_engine()
    if eng is None or table is None:
        raise RuntimeError("Database engine not available")

    values: Dict[str, Any] = {"updated_at": _now_iso()}
    if depot_code is not None:
        norm_d = normalize_depot_name(depot_code)
        if not norm_d:
            raise ValueError("depot_code cannot be empty")
        values["depot_code"] = norm_d

    if company_name is not None:
        c_clean = " ".join(str(company_name or "").strip().split())
        if not c_clean:
            raise ValueError("company_name cannot be empty")
        values["company_name"] = c_clean

    if reason is not None:
        values["reason"] = reason.strip() if reason else None

    if is_active is not None:
        values["is_active"] = 1 if is_active else 0

    try:
        with eng.begin() as conn:
            existing = conn.execute(select(table).where(table.c.id == int(item_id))).fetchone()
            if not existing:
                return None

            # Check if changing depot or company clashes with another entry
            if "depot_code" in values or "company_name" in values:
                check_depot = values.get("depot_code", _to_dict(existing)["depot_code"])
                check_company = values.get("company_name", _to_dict(existing)["company_name"])
                from sqlalchemy import func
                clash = conn.execute(
                    select(table.c.id).where(
                        table.c.id != int(item_id),
                        table.c.depot_code == check_depot,
                        func.lower(table.c.company_name) == check_company.lower(),
                    )
                ).fetchone()
                if clash:
                    raise ValueError(f"Another record for depot '{check_depot}' and company '{check_company}' already exists")

            conn.execute(
                update(table).where(table.c.id == int(item_id)).values(**values)
            )
            updated_row = conn.execute(select(table).where(table.c.id == int(item_id))).fetchone()
            logger.info("[EXCLUDED_COMPANIES] Updated id=%s values=%s", item_id, values)
            return _to_dict(updated_row) if updated_row else None
    except ValueError:
        raise
    except Exception as e:
        logger.exception("update_excluded_company failed for id=%s: %s", item_id, e)
        raise RuntimeError(str(e)) from e


def delete_excluded_company(item_id: int) -> bool:
    """
    Delete an excluded company entry.
    """
    table = get_excluded_companies_table()
    eng = get_engine()
    if eng is None or table is None:
        raise RuntimeError("Database engine not available")

    try:
        with eng.begin() as conn:
            row = conn.execute(select(table.c.id).where(table.c.id == int(item_id))).fetchone()
            if not row:
                return False
            conn.execute(delete(table).where(table.c.id == int(item_id)))
            logger.info("[EXCLUDED_COMPANIES] Deleted id=%s", item_id)
            return True
    except Exception as e:
        logger.exception("delete_excluded_company failed for id=%s: %s", item_id, e)
        raise RuntimeError(str(e)) from e


def get_excluded_companies_for_depot(depot_name: str) -> Set[str]:
    """
    Returns normalized company names set for active exclusions in the given depot.
    Used by the planner in depot_bidding_engine for live bid filtering.
    """
    depot = normalize_depot_name(depot_name)
    if not depot:
        return set()

    table = get_excluded_companies_table()
    eng = get_engine()
    if eng is None or table is None:
        return set()

    try:
        with eng.begin() as conn:
            rows = conn.execute(
                select(table.c.company_name).where(
                    table.c.depot_code == depot,
                    table.c.is_active == 1,
                )
            ).fetchall()
        result: Set[str] = set()
        for r in rows:
            raw_co = r[0] if isinstance(r, (tuple, list)) else getattr(r, "company_name", None)
            norm = normalize_company_name(raw_co)
            if norm:
                result.add(norm)
        return result
    except Exception as e:
        logger.debug("get_excluded_companies_for_depot error (falling back): %s", e)
        return set()
