"""
Lightweight live-bid status publishing for DepotBiddingEngine.
Never raises; never blocks bidding.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .live_bids_store import (
    USER_CONTROL_ACTIVE,
    USER_CONTROL_PAUSED,
    USER_CONTROL_STOPPED,
    get_user_control,
    update_live_bid,
    utc_now_iso,
)
from . import execution_logging as elog
from .logging_service import get_logger

if TYPE_CHECKING:
    from .depot_bidding_engine import DepotBiddingEngine, DesiredBid, RowSnapshot

logger = get_logger("live_status")


def _job_id(engine: DepotBiddingEngine) -> Optional[str]:
    return getattr(engine, "job_id", None) or None


def _emit(
    engine: DepotBiddingEngine,
    desired: DesiredBid,
    status: str,
    **kwargs: Any,
) -> bool:
    jid = _job_id(engine)
    if not jid:
        return False
    depot = engine.depot_name or ""
    try:
        ok = update_live_bid(
            jid,
            depot,
            float(desired.quantity),
            desired.destination,
            status=status,
            **kwargs,
        )
        if not ok:
            logger.debug(
                "live_status: no row updated job=%s depot=%s qty=%s status=%s",
                jid[:8],
                depot,
                desired.quantity,
                status,
            )
            return False
        else:
            elog.log_event(
                phase="API",
                component="live_status",
                action="PUBLISH",
                status="ok",
                message=f"Live status published status={status}",
                job_id=jid,
                depot=depot,
                qty=float(desired.quantity),
                destination=desired.destination,
                live_status=status,
            )
            return True
    except Exception as e:
        logger.warning("live_status: publish failed status=%s: %s", status, e)
        elog.log_error(
            phase="API",
            component="live_status",
            action="PUBLISH_FAIL",
            message=f"Live status publish failed status={status}",
            exc=e,
            recovery="ignore",
            job_id=jid,
            depot=depot,
        )
        return False


def is_leg_active(
    engine: DepotBiddingEngine,
    desired: DesiredBid,
) -> bool:
    """True when leg may participate in planning/execution."""
    jid = _job_id(engine)
    if not jid:
        return True
    control = get_user_control(
        jid,
        engine.depot_name or "",
        float(desired.quantity),
        desired.destination,
    )
    return control == USER_CONTROL_ACTIVE


def desired_bids_for_planning(engine: DepotBiddingEngine) -> List[DesiredBid]:
    """Desired bids excluding paused/stopped legs."""
    return [d for d in engine.desired_bids if is_leg_active(engine, d)]


def publish_monitoring_cycle(engine: DepotBiddingEngine) -> None:
    """Emit per-leg monitoring / paused / stopped at each monitor cycle."""
    jid = _job_id(engine)
    if not jid:
        return
    for d in engine.desired_bids:
        control = get_user_control(
            jid,
            engine.depot_name or "",
            float(d.quantity),
            d.destination,
        )
        if control == USER_CONTROL_STOPPED:
            _emit(engine, d, "stopped", user_control=USER_CONTROL_STOPPED)
        elif control == USER_CONTROL_PAUSED:
            _emit(engine, d, "paused", user_control=USER_CONTROL_PAUSED)
        else:
            _emit(engine, d, "monitoring", user_control=USER_CONTROL_ACTIVE)


def publish_bid_appeared(engine: DepotBiddingEngine) -> None:
    for d in desired_bids_for_planning(engine):
        _emit(engine, d, "bid_appeared")


def publish_planning(
    engine: DepotBiddingEngine,
    planned: List[Dict[str, Any]],
    snapshots: List[RowSnapshot],
) -> None:
    """Emit planning status with organization name when a leg matched SAP rows."""
    if not planned:
        return
    row_by_index = {s.row_index: s for s in snapshots}
    planned_rows = {int(p["row_index"]) for p in planned if p.get("row_index") is not None}
    for d in desired_bids_for_planning(engine):
        org: Optional[str] = None
        d_dest = (d.destination or "").strip().upper()
        for s in snapshots:
            if s.row_index not in planned_rows:
                continue
            if d_dest and (s.destination or "").strip().upper() != d_dest:
                continue
            if abs(float(s.quantity) - float(d.quantity)) < 0.01 or s.row_index in planned_rows:
                if s.company and str(s.company).strip():
                    org = str(s.company).strip()
                    break
        if org is None:
            for ri in planned_rows:
                snap = row_by_index.get(ri)
                if snap and snap.company:
                    org = str(snap.company).strip()
                    break
        _emit(engine, d, "planning", organization_name=org)


def publish_ready(engine: DepotBiddingEngine) -> None:
    for d in desired_bids_for_planning(engine):
        _emit(engine, d, "ready")


def publish_executing(engine: DepotBiddingEngine) -> None:
    for d in desired_bids_for_planning(engine):
        _emit(engine, d, "executing")


def publish_waiting_rank(engine: DepotBiddingEngine) -> None:
    for d in desired_bids_for_planning(engine):
        _emit(engine, d, "waiting_rank")


def publish_rank_for_desired(
    engine: DepotBiddingEngine,
    desired: DesiredBid,
    rank_int: int,
) -> bool:
    """Update rank and terminal status for one desired leg."""
    if rank_int == 1:
        return _emit(
            engine,
            desired,
            "won",
            current_rank=1,
            won_timestamp=utc_now_iso(),
        )
    else:
        return _emit(
            engine,
            desired,
            "completed",
            current_rank=rank_int,
        )


def publish_rank_for_row(
    engine: DepotBiddingEngine,
    planned: List[Dict[str, Any]],
    row_index: int,
    rank_int: int,
) -> bool:
    """Update rank for the desired leg that best matches the executed plan row."""
    plan_row = None
    for p in planned:
        if int(p.get("row_index", -1)) == int(row_index):
            plan_row = p
            break
    dest_from_plan = (
        str(plan_row.get("destination") or "").strip() if plan_row else ""
    )
    ctx_qty: Optional[float] = None
    try:
        ctx = engine._successful_bid_context_for_row(planned, row_index)
        if ctx:
            ctx_qty = float(ctx["quantity"])
    except Exception:
        ctx_qty = None

    candidates: List[DesiredBid] = []
    for d in engine.desired_bids:
        d_dest = (d.destination or "").strip().upper()
        if dest_from_plan and d_dest and d_dest != dest_from_plan.upper():
            continue
        if ctx_qty is not None and abs(float(d.quantity) - ctx_qty) >= 0.01:
            continue
        candidates.append(d)

    if not candidates and engine.desired_bids:
        candidates = [engine.desired_bids[0]]

    saved = False
    for d in candidates:
        saved = publish_rank_for_desired(engine, d, rank_int) or saved
    return saved


def should_skip_execution(engine: DepotBiddingEngine) -> bool:
    """True when no active legs remain (all paused/stopped)."""
    return len(desired_bids_for_planning(engine)) == 0
