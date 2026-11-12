"""
Read-only Reports & Analytics queries against bid_outcomes.db only.
Does not import automation modules or trigger outcome sync.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config_loader import BASE_DIR
from .depot_normalization import normalize_depot_name

_OUTCOMES_DB = BASE_DIR / "data" / "bid_outcomes.db"
_LOCK = threading.Lock()

VALID_OUTCOME_STATUSES = frozenset({"won", "lost", "stopped", "paused", "failed"})


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_OUTCOMES_DB), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_outcome(row: sqlite3.Row) -> Dict[str, Any]:
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


def _build_filters(
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    depot: Optional[str] = None,
    tonnage: Optional[float] = None,
    destination: Optional[str] = None,
    rank: Optional[int] = None,
    outcome_status: Optional[str] = None,
) -> Tuple[str, List[Any]]:
    clauses: List[str] = []
    params: List[Any] = []

    if from_date:
        clauses.append("substr(completed_at, 1, 10) >= ?")
        params.append(str(from_date).strip())
    if to_date:
        clauses.append("substr(completed_at, 1, 10) <= ?")
        params.append(str(to_date).strip())
    if depot:
        depot_norm = normalize_depot_name(depot) or str(depot).strip().upper()
        if depot_norm:
            clauses.append("depot = ?")
            params.append(depot_norm)
    if tonnage is not None:
        clauses.append("ABS(quantity - ?) < 0.01")
        params.append(float(tonnage))
    if destination:
        dest = str(destination).strip()
        if dest:
            clauses.append("UPPER(COALESCE(destination, '')) = ?")
            params.append(dest.upper())
    if rank is not None:
        clauses.append("rank = ?")
        params.append(int(rank))
    if outcome_status:
        st = str(outcome_status).strip().lower()
        if st in VALID_OUTCOME_STATUSES:
            clauses.append("outcome_status = ?")
            params.append(st)

    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where_sql, params


def get_reports_summary(
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    depot: Optional[str] = None,
    tonnage: Optional[float] = None,
    destination: Optional[str] = None,
    rank: Optional[int] = None,
    outcome_status: Optional[str] = None,
) -> Dict[str, Any]:
    """KPI summary from bid_outcomes.db."""
    if not _OUTCOMES_DB.exists():
        return _empty_summary()
    where_sql, params = _build_filters(
        from_date=from_date,
        to_date=to_date,
        depot=depot,
        tonnage=tonnage,
        destination=destination,
        rank=rank,
        outcome_status=outcome_status,
    )
    try:
        with _LOCK:
            conn = _connect()
            try:
                status_rows = conn.execute(
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
                rank_where = f"{where_sql} AND rank IS NOT NULL" if where_sql else " WHERE rank IS NOT NULL"
                avg_rank_row = conn.execute(
                    f"SELECT AVG(rank) AS avg_rank FROM bid_outcomes{rank_where}",
                    params,
                ).fetchone()
            finally:
                conn.close()

        by_status = {str(r["outcome_status"]): int(r["cnt"]) for r in status_rows}
        total = int(total_row["cnt"]) if total_row else 0
        won = by_status.get("won", 0)
        lost = by_status.get("lost", 0)
        stopped = by_status.get("stopped", 0)
        paused = by_status.get("paused", 0)
        failed = by_status.get("failed", 0)
        decided = won + lost
        avg_rank = float(avg_rank_row["avg_rank"]) if avg_rank_row and avg_rank_row["avg_rank"] is not None else None

        return {
            "total_executions": total,
            "total_wins": won,
            "total_losses": lost,
            "total_stopped": stopped,
            "total_paused": paused,
            "total_failed": failed,
            "success_rate": round(won / decided, 4) if decided > 0 else None,
            "loss_rate": round(lost / decided, 4) if decided > 0 else None,
            "average_rank": round(avg_rank, 2) if avg_rank is not None else None,
            "by_status": by_status,
        }
    except Exception:
        return _empty_summary()


def _empty_summary() -> Dict[str, Any]:
    return {
        "total_executions": 0,
        "total_wins": 0,
        "total_losses": 0,
        "total_stopped": 0,
        "total_paused": 0,
        "total_failed": 0,
        "success_rate": None,
        "loss_rate": None,
        "average_rank": None,
        "by_status": {},
    }


def list_report_outcomes(
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    depot: Optional[str] = None,
    tonnage: Optional[float] = None,
    destination: Optional[str] = None,
    rank: Optional[int] = None,
    outcome_status: Optional[str] = None,
    limit: Optional[int] = 5000,
) -> Dict[str, Any]:
    """List outcome rows for tables and export."""
    if not _OUTCOMES_DB.exists():
        return {"items": [], "total": 0}
    where_sql, params = _build_filters(
        from_date=from_date,
        to_date=to_date,
        depot=depot,
        tonnage=tonnage,
        destination=destination,
        rank=rank,
        outcome_status=outcome_status,
    )
    limit_sql = ""
    if limit is not None and int(limit) > 0:
        limit_sql = " LIMIT ?"
        params = [*params, int(limit)]
    sql = (
        "SELECT outcome_id, leg_id, job_id, depot, destination, quantity, "
        "organization_name, bid_amount, rank, outcome_status, "
        "started_at, completed_at, duration_ms, created_at "
        f"FROM bid_outcomes{where_sql} "
        f"ORDER BY completed_at DESC, created_at DESC{limit_sql}"
    )
    try:
        with _LOCK:
            conn = _connect()
            try:
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        items = [_row_to_outcome(r) for r in rows]
        return {"items": items, "total": len(items)}
    except Exception:
        return {"items": [], "total": 0}


def get_timeline_chart(
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    depot: Optional[str] = None,
    tonnage: Optional[float] = None,
    destination: Optional[str] = None,
    rank: Optional[int] = None,
    outcome_status: Optional[str] = None,
) -> Dict[str, Any]:
    """Daily executions, wins, and losses."""
    if not _OUTCOMES_DB.exists():
        return {"items": [], "total": 0}
    where_sql, params = _build_filters(
        from_date=from_date,
        to_date=to_date,
        depot=depot,
        tonnage=tonnage,
        destination=destination,
        rank=rank,
        outcome_status=outcome_status,
    )
    try:
        with _LOCK:
            conn = _connect()
            try:
                rows = conn.execute(
                    f"""
                    SELECT
                        substr(completed_at, 1, 10) AS day,
                        COUNT(*) AS executions,
                        SUM(CASE WHEN outcome_status = 'won' THEN 1 ELSE 0 END) AS wins,
                        SUM(CASE WHEN outcome_status = 'lost' THEN 1 ELSE 0 END) AS losses
                    FROM bid_outcomes{where_sql}
                    GROUP BY substr(completed_at, 1, 10)
                    ORDER BY day ASC
                    """,
                    params,
                ).fetchall()
            finally:
                conn.close()
        items = [
            {
                "date": r["day"],
                "executions": int(r["executions"]),
                "wins": int(r["wins"]),
                "losses": int(r["losses"]),
                "bids": int(r["executions"]),
            }
            for r in rows
            if r["day"]
        ]
        return {"items": items, "total": len(items)}
    except Exception:
        return {"items": [], "total": 0}


def get_depot_performance_chart(
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    depot: Optional[str] = None,
    tonnage: Optional[float] = None,
    destination: Optional[str] = None,
    rank: Optional[int] = None,
    outcome_status: Optional[str] = None,
) -> Dict[str, Any]:
    """Per-depot executions and wins."""
    if not _OUTCOMES_DB.exists():
        return {"items": [], "total": 0}
    where_sql, params = _build_filters(
        from_date=from_date,
        to_date=to_date,
        depot=depot,
        tonnage=tonnage,
        destination=destination,
        rank=rank,
        outcome_status=outcome_status,
    )
    try:
        with _LOCK:
            conn = _connect()
            try:
                rows = conn.execute(
                    f"""
                    SELECT
                        depot,
                        COUNT(*) AS bids,
                        SUM(CASE WHEN outcome_status = 'won' THEN 1 ELSE 0 END) AS wins,
                        SUM(CASE WHEN outcome_status = 'lost' THEN 1 ELSE 0 END) AS losses
                    FROM bid_outcomes{where_sql}
                    GROUP BY depot
                    ORDER BY bids DESC
                    """,
                    params,
                ).fetchall()
            finally:
                conn.close()
        items = []
        for r in rows:
            bids = int(r["bids"])
            wins = int(r["wins"])
            items.append({
                "name": r["depot"],
                "depot": r["depot"],
                "bids": bids,
                "wins": wins,
                "losses": int(r["losses"]),
                "success_rate": round(wins / bids * 100) if bids > 0 else 0,
            })
        return {"items": items, "total": len(items)}
    except Exception:
        return {"items": [], "total": 0}


def get_rank_distribution_chart(
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    depot: Optional[str] = None,
    tonnage: Optional[float] = None,
    destination: Optional[str] = None,
    outcome_status: Optional[str] = None,
) -> Dict[str, Any]:
    """Rank buckets for lost outcomes."""
    if not _OUTCOMES_DB.exists():
        return {"items": [], "total": 0}
    lost_filter = outcome_status or "lost"
    if lost_filter != "lost":
        # Rank distribution only meaningful for losses
        if outcome_status and outcome_status != "lost":
            return {"items": [], "total": 0}
    where_sql, params = _build_filters(
        from_date=from_date,
        to_date=to_date,
        depot=depot,
        tonnage=tonnage,
        destination=destination,
        outcome_status="lost",
    )
    try:
        with _LOCK:
            conn = _connect()
            try:
                rows = conn.execute(
                    f"""
                    SELECT rank, COUNT(*) AS cnt
                    FROM bid_outcomes{where_sql}
                    GROUP BY rank
                    ORDER BY rank ASC
                    """,
                    params,
                ).fetchall()
            finally:
                conn.close()
        bucket: Dict[str, int] = {}
        for r in rows:
            if r["rank"] is None:
                continue
            rk = int(r["rank"])
            label = "Rank 4+" if rk >= 4 else f"Rank {rk}"
            bucket[label] = bucket.get(label, 0) + int(r["cnt"])
        colors = {
            "Rank 2": "hsl(var(--warning))",
            "Rank 3": "hsl(var(--destructive))",
            "Rank 4+": "hsl(var(--muted-foreground))",
        }
        items = [
            {"name": name, "value": value, "fill": colors.get(name, "hsl(var(--muted))")}
            for name, value in sorted(bucket.items(), key=lambda x: x[0])
        ]
        return {"items": items, "total": sum(bucket.values())}
    except Exception:
        return {"items": [], "total": 0}


def get_tonnage_distribution_chart(
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    depot: Optional[str] = None,
    tonnage: Optional[float] = None,
    destination: Optional[str] = None,
    rank: Optional[int] = None,
) -> Dict[str, Any]:
    """Stacked rank breakdown by tonnage for lost outcomes."""
    if not _OUTCOMES_DB.exists():
        return {"items": [], "total": 0}
    where_sql, params = _build_filters(
        from_date=from_date,
        to_date=to_date,
        depot=depot,
        tonnage=tonnage,
        destination=destination,
        rank=rank,
        outcome_status="lost",
    )
    try:
        with _LOCK:
            conn = _connect()
            try:
                rows = conn.execute(
                    f"""
                    SELECT quantity, rank, COUNT(*) AS cnt
                    FROM bid_outcomes{where_sql}
                    GROUP BY quantity, rank
                    ORDER BY quantity ASC
                    """,
                    params,
                ).fetchall()
            finally:
                conn.close()
        stats: Dict[float, Dict[str, int]] = {}
        for r in rows:
            qty = float(r["quantity"])
            if qty not in stats:
                stats[qty] = {"total": 0, "rank2": 0, "rank3": 0, "rank4plus": 0}
            cnt = int(r["cnt"])
            stats[qty]["total"] += cnt
            rk = int(r["rank"]) if r["rank"] is not None else None
            if rk == 2:
                stats[qty]["rank2"] += cnt
            elif rk == 3:
                stats[qty]["rank3"] += cnt
            elif rk is not None and rk >= 4:
                stats[qty]["rank4plus"] += cnt
        items = [
            {
                "name": f"{int(qty) if qty == int(qty) else qty}T",
                "tonnage": qty,
                "rank2": s["rank2"],
                "rank3": s["rank3"],
                "rank4plus": s["rank4plus"],
                "total": s["total"],
            }
            for qty, s in sorted(stats.items(), key=lambda x: x[0])
        ]
        return {"items": items, "total": len(items)}
    except Exception:
        return {"items": [], "total": 0}


def get_losses_timeline_chart(
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    depot: Optional[str] = None,
    tonnage: Optional[float] = None,
    destination: Optional[str] = None,
) -> Dict[str, Any]:
    """Daily loss counts for unsuccessful analysis tab."""
    if not _OUTCOMES_DB.exists():
        return {"items": [], "total": 0}
    where_sql, params = _build_filters(
        from_date=from_date,
        to_date=to_date,
        depot=depot,
        tonnage=tonnage,
        destination=destination,
        outcome_status="lost",
    )
    try:
        with _LOCK:
            conn = _connect()
            try:
                rows = conn.execute(
                    f"""
                    SELECT substr(completed_at, 1, 10) AS day, COUNT(*) AS losses
                    FROM bid_outcomes{where_sql}
                    GROUP BY substr(completed_at, 1, 10)
                    ORDER BY day ASC
                    """,
                    params,
                ).fetchall()
            finally:
                conn.close()
        items = [{"date": r["day"], "losses": int(r["losses"])} for r in rows if r["day"]]
        return {"items": items, "total": len(items)}
    except Exception:
        return {"items": [], "total": 0}
