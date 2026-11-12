# backend_server.py

import os
import threading
import time
from fastapi import FastAPI, HTTPException, Form, Query, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from pydantic import BaseModel

from src.logging_service import get_logger
from src.selenium_service import trigger_bid, trigger_bid_legacy
from src.job_store import job_store
from src.depot_normalization import normalize_depot_name
from src.config_loader import get_app_config
from src.successful_bids_store import init_db as init_successful_bids_db, list_successful_bids
from src.live_bids_store import (
    USER_CONTROL_ACTIVE,
    USER_CONTROL_PAUSED,
    USER_CONTROL_RUNNING,
    USER_CONTROL_STOPPED,
    get_live_bid,
    get_live_db,
    init_db as init_live_bids_db,
    list_live_bids,
    register_job_legs,
    set_user_control,
)
from src.truck_master_store import (
    init_db as init_truck_master_db,
    list_trucks,
    get_truck,
    create_truck,
    update_truck,
    delete_truck,
    add_vehicle_document,
    get_document_file_path,
)
from src.jobs_store import init_db as init_jobs_db
from src.fleet_admin_store import (
    init_db as init_fleet_admin_db,
    list_fleet_daily,
    get_fleet_daily_entry,
    create_fleet_daily_entry,
    update_fleet_daily_entry,
    delete_fleet_daily_entry,
    list_fleet_requests,
    get_fleet_request,
    create_fleet_request,
    update_fleet_request,
    delete_fleet_request,
)
from src.outcome_store import (
    init_db as init_outcomes_db,
    list_bid_outcomes,
    get_outcomes_summary,
    list_outcomes_for_job,
    sync_outcomes_from_sources,
)
from src.notifications_store import (
    init_db as init_notifications_db,
    list_notifications,
    mark_notification_read,
    mark_all_notifications_read,
    delete_notification,
    emit_automation_started,
    emit_fleet_request_created,
    emit_fleet_request_resolved,
    sync_notifications_from_observers,
)
from src.reports_store import (
    get_reports_summary,
    list_report_outcomes,
    get_timeline_chart,
    get_depot_performance_chart,
    get_rank_distribution_chart,
    get_tonnage_distribution_chart,
    get_losses_timeline_chart,
)
from src.master_store import (
    list_zones,
    list_plants,
    list_depots_for_plant,
    list_tonnage_options,
)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:8081",
        "http://127.0.0.1:8081",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger = get_logger("backend_api")

# -----------------------
# API MODELS
# -----------------------

class DesiredBidItem(BaseModel):
    """One desired bid: quantity (and optional destination)."""
    quantity: float
    destination: str | None = None
    depot: str | None = None


class BidRequest(BaseModel):
    depot: str | None = None
    depots: list[str] | None = None  # optional override list for multi-depot
    desired_bids: list[DesiredBidItem] = []  # e.g. [{"quantity": 25}, {"quantity": 50}]
    headless: bool | None = None  # Override for browser headless mode
    record_on_bid_start: bool | None = None  # Override for screen recording


class TruckCreateRequest(BaseModel):
    truck_number: str
    driver_name: str
    tonnage: str = "32T"
    status: str = "Active"
    rotation_count: int = 0
    plant_id: str = "1"
    plant_name: str = "Tanda Cement Plant"
    depot_id: str = "6601"
    depot_name: str = "LUCKNOW"


class TruckUpdateRequest(BaseModel):
    driver_name: str | None = None
    tonnage: str | None = None
    status: str | None = None
    rotation_count: int | None = None
    plant_id: str | None = None
    plant_name: str | None = None
    depot_id: str | None = None
    depot_name: str | None = None


class FleetDailyCreateRequest(BaseModel):
    business_date: str
    truck_number: str
    driver_name: str = ""
    tonnage: str
    previous_depot: str = ""
    current_depot: str
    destination: str = ""
    status: str = "Available"
    remarks: str = ""


class FleetDailyUpdateRequest(BaseModel):
    driver_name: str | None = None
    tonnage: str | None = None
    previous_depot: str | None = None
    current_depot: str | None = None
    destination: str | None = None
    status: str | None = None
    remarks: str | None = None


class FleetRequestCreateBody(BaseModel):
    leg_id: str
    request_type: str
    requested_by: str
    job_id: str | None = None
    truck_number: str | None = None
    depot_name: str | None = None
    destination: str | None = None
    tonnage: float | None = None
    plant_name: str | None = None
    remarks: str | None = None


class FleetRequestUpdateBody(BaseModel):
    status: str
    resolved_by: str


# -----------------------
# STARTUP LOGGING
# -----------------------

@app.on_event("startup")
def startup_event():
    logger.info("[API] Backend API starting...")
    logger.info(f"[API] USER = {os.getenv('USER')}")
    logger.info(f"[API] PATH = {os.getenv('PATH')}")
    init_successful_bids_db()
    logger.info("[API] Successful bids database initialized")
    init_live_bids_db()
    logger.info("[API] Live bids database initialized")
    init_truck_master_db()
    logger.info("[API] Truck master database initialized")
    init_jobs_db()
    logger.info("[API] Jobs database initialized")
    init_fleet_admin_db()
    logger.info("[API] Fleet admin database initialized")
    init_outcomes_db()
    logger.info("[API] Bid outcomes database initialized")
    init_notifications_db()
    logger.info("[API] Notifications database initialized")
    threading.Thread(target=_outcome_sync_loop, daemon=True, name="outcome-sync").start()
    logger.info("[API] Bid outcomes background sync started")
    threading.Thread(target=_notification_sync_loop, daemon=True, name="notification-sync").start()
    logger.info("[API] Notifications background sync started")
    logger.info("[API] API environment initialized")


_OUTCOME_SYNC_INTERVAL_SEC = 5
_NOTIFICATION_SYNC_INTERVAL_SEC = 5


def _notification_sync_loop() -> None:
    """Read-only observer: emit notifications from bid_outcomes.db and jobs.db."""
    while True:
        try:
            sync_outcomes_from_sources()
            inserted = sync_notifications_from_observers()
            if any(inserted.values()):
                logger.debug("[API] Notifications sync inserted: %s", inserted)
        except Exception as e:
            logger.warning("[API] Notifications sync error: %s", e)
        time.sleep(_NOTIFICATION_SYNC_INTERVAL_SEC)


def _outcome_sync_loop() -> None:
    """Read-only observer: mirror terminal states into bid_outcomes.db."""
    while True:
        try:
            inserted = sync_outcomes_from_sources()
            if any(inserted.values()):
                logger.debug("[API] Bid outcomes sync inserted: %s", inserted)
        except Exception as e:
            logger.warning("[API] Bid outcomes sync error: %s", e)
        time.sleep(_OUTCOME_SYNC_INTERVAL_SEC)


# -----------------------
# API ENDPOINT
# -----------------------

def _try_emit_automation_started(
    job_id: str | None,
    depots: list[str] | None,
    desired_bids: list[dict],
) -> None:
    """Best-effort notification; never affects start-bid response."""
    if not job_id:
        return
    try:
        emit_automation_started(
            job_id=job_id,
            depots=depots,
            desired_bids_count=len(desired_bids),
        )
    except Exception as e:
        logger.warning("[API] automation_started notification failed: %s", e)


@app.post("/api/start-bid")
def start_bid(data: BidRequest, sync: bool = False, legacy_blocking: bool = False):
    """
    Start SAP bidding automation.
    Body: optional depot, depots[], desired_bids.

    Query sync:
    - multiprocess: sync=false queues a job (job_id); sync=true blocks until all depot processes finish.

    Query legacy_blocking:
    - When execution_mode is legacy: false (default) runs Selenium in a background thread and returns job_id immediately.
    - Set legacy_blocking=true to block until legacy Selenium finishes (debug / scripts only).
    """
    try:
        raw_depot = data.depot
        raw_depots = list(data.depots) if data.depots else None
        
        desired_bids = []
        for b in data.desired_bids:
            if float(b.quantity) <= 0:
                continue
            _bd = normalize_depot_name(b.depot)
            entry = {
                "quantity": float(b.quantity),
                "destination": b.destination,
                "depot": _bd if _bd else None,
            }
            desired_bids.append(entry)
        if not desired_bids:
            raise HTTPException(status_code=400, detail="desired_bids must not be empty")
        
        # Extract depot from desired_bids if not explicitly provided
        _dn = normalize_depot_name(data.depot)
        depot = _dn if _dn else None
        depots = (
            [normalize_depot_name(d) for d in data.depots if str(d).strip()]
            if data.depots
            else None
        )
        if depots is not None:
            depots = [d for d in depots if d]
            if not depots:
                depots = None
        
        # Fallback: extract depot from first desired_bid if no explicit depot/depots
        if not depot and not depots and desired_bids:
            first_bid_depot = desired_bids[0].get("depot")
            if first_bid_depot:
                depot = normalize_depot_name(first_bid_depot)
                depots = [depot]
        
        logger.info("[API] Received desired_bids=%s", desired_bids)
        logger.info(
            "[API] API depot normalization: depot_raw=%r depots_raw=%r -> depot=%r depots=%r",
            raw_depot,
            raw_depots,
            depot,
            depots,
        )
        logger.info("[API] API: start-bid depot=%s depots=%s desired_bids=%s sync=%s legacy_blocking=%s", depot, depots, desired_bids, sync, legacy_blocking)

        cfg_mode = str((get_app_config().get("automation") or {}).get("execution_mode", "legacy")).strip().lower()
        logger.info("[API] API: execution_mode=%s", cfg_mode)

        if cfg_mode == "multiprocess":
            result = trigger_bid(
                depot=depot,
                depots=depots,
                desired_bids=desired_bids,
                sync=sync,
                headless=data.headless,
                record_on_bid_start=data.record_on_bid_start,
            )

            if result.get("execution_mode") == "multiprocess" and result.get("job_id"):
                mp_job_id = str(result.get("job_id"))
                _try_emit_automation_started(
                    mp_job_id,
                    result.get("depots") or depots,
                    desired_bids,
                )
                return {
                    "status": result.get("status", "queued"),
                    "job_id": result.get("job_id"),
                    "depots": result.get("depots"),
                    "execution_mode": "multiprocess",
                    "multiprocess_max_workers": result.get("multiprocess_max_workers"),
                    "message": result.get("message", ""),
                    "poll_path": result.get("poll_path"),
                    "sync": sync,
                }

            return {
                "status": result.get("status", "unknown"),
                "depot": result.get("depot"),
                "depots_processed": result.get("depots_processed", []),
                "results": result.get("results", {}),
                "rows_found": result.get("rows_found", 0),
                "bids_submitted": result.get("bids_submitted", 0),
                "execution_time": result.get("execution_time", ""),
                "message": result.get("message", ""),
                "error": result.get("error", None),
                "screenshot": result.get("screenshot", {}),
                "execution_mode": result.get("execution_mode", "multiprocess"),
                "multiprocess_max_workers": result.get("multiprocess_max_workers"),
                "sync": sync,
            }

        if not legacy_blocking:
            truck = str(depot or (depots[0] if depots else "AUTO"))
            depots_list = list(depots) if depots else ([depot] if depot else [])
            payload = [
                {
                    "quantity": b.get("quantity", 0),
                    "destination": b.get("destination"),
                    "depot": b.get("depot"),
                }
                for b in desired_bids
            ]
            logger.info("[API] Creating legacy_async job for depots=%s desired_bids=%s", depots_list, desired_bids)
            job_id = job_store.create_job(
                truck, depots_list, desired_bids,
                payload=payload,
                headless=data.headless,
                record_on_bid_start=data.record_on_bid_start,
                execution_mode="legacy_async"
            )
            logger.info("[API] Job created job_id=%s", job_id)
            register_job_legs(job_id, desired_bids)

            def _legacy_runner() -> None:
                job_store.mark_running(job_id)
                try:
                    r = trigger_bid_legacy(
                        truck, depot, depots, desired_bids,
                        headless=data.headless,
                        record_on_bid_start=data.record_on_bid_start,
                    )
                    job_store.record_depot_result(job_id, "legacy", r)
                    st = str(r.get("status") or "completed")
                    overall = "failed" if st == "failed" else "completed"
                    job_store.finalize(
                        job_id,
                        overall,
                        summary=str(r.get("message") or r.get("error") or ""),
                    )
                except Exception as e:
                    logger.exception("[API] Legacy async bidding failed")
                    job_store.record_depot_error(job_id, "legacy", str(e))
                    job_store.finalize(job_id, "failed", summary=str(e))

            threading.Thread(
                target=_legacy_runner,
                daemon=True,
                name=f"legacy-{job_id[:8]}",
            ).start()
            _try_emit_automation_started(job_id, depots_list, desired_bids)
            return {
                "status": "queued",
                "job_id": job_id,
                "depots": depots_list,
                "execution_mode": "legacy_async",
                "message": "Legacy bidding started in background; poll GET /api/bid-job/{job_id}",
                "poll_path": f"/api/bid-job/{job_id}",
                "sync": sync,
            }

        result = trigger_bid_legacy(
            str(depot or (depots[0] if depots else "AUTO")),
            depot,
            depots,
            desired_bids,
            headless=data.headless,
            record_on_bid_start=data.record_on_bid_start,
        )
        return {
            "status": result.get("status", "unknown"),
            "depot": result.get("depot"),
            "depots_processed": result.get("depots_processed", []),
            "results": result.get("results", {}),
            "rows_found": result.get("rows_found", 0),
            "bids_submitted": result.get("bids_submitted", 0),
            "execution_time": result.get("execution_time", ""),
            "message": result.get("message", ""),
            "error": result.get("error", None),
            "screenshot": result.get("screenshot", {}),
            "execution_mode": result.get("execution_mode", "legacy"),
            "multiprocess_max_workers": result.get("multiprocess_max_workers"),
            "sync": sync,
        }
    except Exception as e:
        logger.exception("[API] API error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bid-job/{job_id}")
def get_bid_job(job_id: str):
    """Poll multiprocess job status (queued | running | completed | failed)."""
    logger.info("[API] GET /api/bid-job/%s called", job_id)
    rec = job_store.get_job(job_id)
    if not rec:
        logger.warning("[API] GET /api/bid-job/%s - job not found", job_id)
        raise HTTPException(status_code=404, detail="job not found")
    logger.info("[API] GET /api/bid-job/%s - found status=%s", job_id, rec.get("status"))
    return rec


@app.get("/api/successful-bids")
def get_successful_bids(
    month: str | None = Query(None, description="Filter by month YYYY-MM"),
    from_date: str | None = Query(None, alias="from", description="Start date YYYY-MM-DD (inclusive)"),
    to_date: str | None = Query(None, alias="to", description="End date YYYY-MM-DD (inclusive)"),
    depot: str | None = Query(None, description="Filter by depot name, e.g. AYODHYA"),
):
    """List Rank-1 successful bids stored in SQLite."""
    try:
        return list_successful_bids(
            month=month,
            from_date=from_date,
            to_date=to_date,
            depot=depot,
        )
    except Exception as e:
        logger.exception("[API] GET /api/successful-bids failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/trucks")
def get_trucks():
    """List Truck Master fleet registry rows with documents."""
    logger.info("[API] GET /api/trucks called")
    try:
        return list_trucks()
    except Exception as e:
        logger.exception("[API] GET /api/trucks failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/trucks/{truck_id}")
def get_truck_by_id(truck_id: str):
    """Get one truck by id."""
    logger.info("[API] GET /api/trucks/%s called", truck_id)
    try:
        rec = get_truck(truck_id)
        if not rec:
            logger.warning("[API] GET /api/trucks/%s - truck not found", truck_id)
            raise HTTPException(status_code=404, detail="truck not found")
        return rec
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[API] GET /api/trucks/%s failed", truck_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/trucks")
def post_truck(data: TruckCreateRequest):
    """Create a new truck in Truck Master."""
    try:
        rec, err = create_truck(
            truck_number=data.truck_number,
            driver_name=data.driver_name,
            tonnage=data.tonnage,
            status=data.status,
            rotation_count=data.rotation_count,
            plant_id=data.plant_id,
            plant_name=data.plant_name,
            depot_id=data.depot_id,
            depot_name=data.depot_name,
        )
        if err:
            raise HTTPException(status_code=400, detail=err)
        return rec
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[API] POST /api/trucks failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.put("/api/trucks/{truck_id}")
def put_truck(truck_id: str, data: TruckUpdateRequest):
    """Update an existing truck."""
    try:
        rec, err = update_truck(
            truck_id,
            driver_name=data.driver_name,
            tonnage=data.tonnage,
            status=data.status,
            rotation_count=data.rotation_count,
            plant_id=data.plant_id,
            plant_name=data.plant_name,
            depot_id=data.depot_id,
            depot_name=data.depot_name,
        )
        if err == "truck not found":
            raise HTTPException(status_code=404, detail=err)
        if err:
            raise HTTPException(status_code=400, detail=err)
        return rec
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[API] PUT /api/trucks/%s failed", truck_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.delete("/api/trucks/{truck_id}")
def remove_truck(truck_id: str):
    """Delete a truck and its documents."""
    try:
        ok, err = delete_truck(truck_id)
        if err == "truck not found":
            raise HTTPException(status_code=404, detail=err)
        if not ok:
            raise HTTPException(status_code=500, detail=err or "failed to delete truck")
        return {"status": "ok", "id": truck_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[API] DELETE /api/trucks/%s failed", truck_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/trucks/{truck_id}/documents")
async def post_truck_document(
    truck_id: str,
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    expiry_date: str | None = Form(None),
):
    """Upload a vehicle document for a truck."""
    try:
        content = await file.read()
        rec, err = add_vehicle_document(
            truck_id,
            doc_type=doc_type,
            file_name=file.filename or "document",
            file_bytes=content,
            expiry_date=expiry_date,
        )
        if err == "truck not found":
            raise HTTPException(status_code=404, detail=err)
        if err:
            raise HTTPException(status_code=400, detail=err)
        return rec
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[API] POST /api/trucks/%s/documents failed", truck_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/trucks/{truck_id}/documents/{document_id}/file")
def get_truck_document_file(truck_id: str, document_id: str):
    """Serve a stored vehicle document file."""
    try:
        path = get_document_file_path(truck_id, document_id)
        if not path:
            raise HTTPException(status_code=404, detail="document not found")
        return FileResponse(path, filename=path.name.split("_", 1)[-1])
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "[API] GET /api/trucks/%s/documents/%s/file failed",
            truck_id,
            document_id,
        )
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/fleet-daily")
def get_fleet_daily(
    date: str | None = Query(None, description="Business date YYYY-MM-DD"),
):
    """List fleet daily availability entries."""
    try:
        return list_fleet_daily(business_date=date)
    except Exception as e:
        logger.exception("[API] GET /api/fleet-daily failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/fleet-daily")
def post_fleet_daily(data: FleetDailyCreateRequest):
    """Create a fleet daily availability entry."""
    try:
        rec, err = create_fleet_daily_entry(
            business_date=data.business_date,
            truck_number=data.truck_number,
            driver_name=data.driver_name,
            tonnage=data.tonnage,
            previous_depot=data.previous_depot,
            current_depot=data.current_depot,
            destination=data.destination,
            status=data.status,
            remarks=data.remarks,
        )
        if err:
            raise HTTPException(status_code=400, detail=err)
        return rec
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[API] POST /api/fleet-daily failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.put("/api/fleet-daily/{entry_id}")
def put_fleet_daily(entry_id: str, data: FleetDailyUpdateRequest):
    """Update a fleet daily availability entry."""
    try:
        rec, err = update_fleet_daily_entry(
            entry_id,
            driver_name=data.driver_name,
            tonnage=data.tonnage,
            previous_depot=data.previous_depot,
            current_depot=data.current_depot,
            destination=data.destination,
            status=data.status,
            remarks=data.remarks,
        )
        if err == "entry not found":
            raise HTTPException(status_code=404, detail=err)
        if err:
            raise HTTPException(status_code=400, detail=err)
        return rec
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[API] PUT /api/fleet-daily/%s failed", entry_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.delete("/api/fleet-daily/{entry_id}")
def remove_fleet_daily(entry_id: str):
    """Delete a fleet daily availability entry."""
    try:
        ok, err = delete_fleet_daily_entry(entry_id)
        if err == "entry not found":
            raise HTTPException(status_code=404, detail=err)
        if not ok:
            raise HTTPException(status_code=500, detail=err or "failed to delete entry")
        return {"status": "ok", "id": entry_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[API] DELETE /api/fleet-daily/%s failed", entry_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/fleet-requests")
def get_fleet_requests(
    status: str | None = Query(None, description="Filter by Pending|Approved|Rejected"),
):
    """List fleet control requests."""
    try:
        return list_fleet_requests(status=status)
    except Exception as e:
        logger.exception("[API] GET /api/fleet-requests failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/fleet-requests")
def post_fleet_request(data: FleetRequestCreateBody):
    """Create a fleet pause/close request for vendor approval."""
    try:
        rec, err = create_fleet_request(
            leg_id=data.leg_id,
            request_type=data.request_type,
            requested_by=data.requested_by,
            job_id=data.job_id,
            truck_number=data.truck_number,
            depot_name=data.depot_name,
            destination=data.destination,
            tonnage=data.tonnage,
            plant_name=data.plant_name,
            remarks=data.remarks,
        )
        if err:
            raise HTTPException(status_code=400, detail=err)
        try:
            emit_fleet_request_created(rec)
        except Exception as e:
            logger.warning("[API] fleet_request_created notification failed: %s", e)
        return rec
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[API] POST /api/fleet-requests failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.put("/api/fleet-requests/{request_id}")
def put_fleet_request(request_id: str, data: FleetRequestUpdateBody):
    """Approve or reject a fleet control request."""
    try:
        rec, err = update_fleet_request(
            request_id,
            status=data.status,
            resolved_by=data.resolved_by,
        )
        if err == "request not found":
            raise HTTPException(status_code=404, detail=err)
        if err:
            raise HTTPException(status_code=400, detail=err)
        try:
            approved = str(data.status).strip().lower() == "approved"
            emit_fleet_request_resolved(rec, approved=approved)
        except Exception as e:
            logger.warning("[API] fleet_request_resolved notification failed: %s", e)
        return rec
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[API] PUT /api/fleet-requests/%s failed", request_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.delete("/api/fleet-requests/{request_id}")
def remove_fleet_request(request_id: str):
    """Delete a fleet control request."""
    try:
        ok, err = delete_fleet_request(request_id)
        if err == "request not found":
            raise HTTPException(status_code=404, detail=err)
        if not ok:
            raise HTTPException(status_code=500, detail=err or "failed to delete request")
        return {"status": "ok", "id": request_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[API] DELETE /api/fleet-requests/%s failed", request_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/notifications")
def get_notifications(
    unread_only: bool = Query(False, description="Only unread notifications"),
    limit: int = Query(100, ge=1, le=500, description="Max rows"),
):
    """List persisted notifications (newest first)."""
    try:
        sync_notifications_from_observers()
        return list_notifications(unread_only=unread_only, limit=limit)
    except Exception as e:
        logger.exception("[API] GET /api/notifications failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.patch("/api/notifications/read-all")
def patch_notifications_read_all():
    """Mark all notifications as read."""
    try:
        count = mark_all_notifications_read()
        return {"status": "ok", "marked_read": count}
    except Exception as e:
        logger.exception("[API] PATCH /api/notifications/read-all failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.patch("/api/notifications/{notification_id}/read")
def patch_notification_read(notification_id: str):
    """Mark one notification as read."""
    try:
        ok, err = mark_notification_read(notification_id)
        if err == "notification not found":
            raise HTTPException(status_code=404, detail=err)
        if not ok:
            raise HTTPException(status_code=400, detail=err or "failed to mark read")
        return {"status": "ok", "id": notification_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[API] PATCH /api/notifications/%s/read failed", notification_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.delete("/api/notifications/{notification_id}")
def remove_notification(notification_id: str):
    """Delete one notification."""
    try:
        ok, err = delete_notification(notification_id)
        if err == "notification not found":
            raise HTTPException(status_code=404, detail=err)
        if not ok:
            raise HTTPException(status_code=500, detail=err or "failed to delete")
        return {"status": "ok", "id": notification_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[API] DELETE /api/notifications/%s failed", notification_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


def _reports_filter_kwargs(
    from_date: str | None,
    to_date: str | None,
    depot: str | None,
    tonnage: float | None,
    destination: str | None,
    rank: int | None,
    outcome_status: str | None,
) -> dict:
    return {
        "from_date": from_date,
        "to_date": to_date,
        "depot": depot,
        "tonnage": tonnage,
        "destination": destination,
        "rank": rank,
        "outcome_status": outcome_status,
    }


@app.get("/api/reports/summary")
def get_reports_summary_api(
    from_date: str | None = Query(None, description="Completed on/after YYYY-MM-DD"),
    to_date: str | None = Query(None, description="Completed on/before YYYY-MM-DD"),
    depot: str | None = Query(None, description="Filter by depot name"),
    tonnage: float | None = Query(None, description="Filter by tonnage quantity"),
    destination: str | None = Query(None, description="Filter by destination"),
    rank: int | None = Query(None, description="Filter by final rank"),
    outcome_status: str | None = Query(None, description="won|lost|stopped|paused|failed"),
):
    """KPI summary from bid_outcomes.db (read-only)."""
    try:
        return get_reports_summary(
            **_reports_filter_kwargs(
                from_date, to_date, depot, tonnage, destination, rank, outcome_status
            )
        )
    except Exception as e:
        logger.exception("[API] GET /api/reports/summary failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/reports/outcomes")
def get_reports_outcomes_api(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    depot: str | None = Query(None),
    tonnage: float | None = Query(None),
    destination: str | None = Query(None),
    rank: int | None = Query(None),
    outcome_status: str | None = Query(None),
    limit: int = Query(5000, ge=1, le=5000),
):
    """List bid outcomes for reports tables and export."""
    try:
        return list_report_outcomes(
            **_reports_filter_kwargs(
                from_date, to_date, depot, tonnage, destination, rank, outcome_status
            ),
            limit=limit,
        )
    except Exception as e:
        logger.exception("[API] GET /api/reports/outcomes failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/reports/charts/timeline")
def get_reports_timeline_chart(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    depot: str | None = Query(None),
    tonnage: float | None = Query(None),
    destination: str | None = Query(None),
    rank: int | None = Query(None),
    outcome_status: str | None = Query(None),
):
    """Daily execution timeline from bid_outcomes.db."""
    try:
        return get_timeline_chart(
            **_reports_filter_kwargs(
                from_date, to_date, depot, tonnage, destination, rank, outcome_status
            )
        )
    except Exception as e:
        logger.exception("[API] GET /api/reports/charts/timeline failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/reports/charts/depot-performance")
def get_reports_depot_performance_chart(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    depot: str | None = Query(None),
    tonnage: float | None = Query(None),
    destination: str | None = Query(None),
    rank: int | None = Query(None),
    outcome_status: str | None = Query(None),
):
    """Per-depot performance from bid_outcomes.db."""
    try:
        return get_depot_performance_chart(
            **_reports_filter_kwargs(
                from_date, to_date, depot, tonnage, destination, rank, outcome_status
            )
        )
    except Exception as e:
        logger.exception("[API] GET /api/reports/charts/depot-performance failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/reports/charts/rank-distribution")
def get_reports_rank_distribution_chart(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    depot: str | None = Query(None),
    tonnage: float | None = Query(None),
    destination: str | None = Query(None),
    outcome_status: str | None = Query(None),
):
    """Rank distribution for lost outcomes."""
    try:
        return get_rank_distribution_chart(
            from_date=from_date,
            to_date=to_date,
            depot=depot,
            tonnage=tonnage,
            destination=destination,
            outcome_status=outcome_status,
        )
    except Exception as e:
        logger.exception("[API] GET /api/reports/charts/rank-distribution failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/reports/charts/tonnage-distribution")
def get_reports_tonnage_distribution_chart(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    depot: str | None = Query(None),
    tonnage: float | None = Query(None),
    destination: str | None = Query(None),
    rank: int | None = Query(None),
):
    """Tonnage-wise loss breakdown from bid_outcomes.db."""
    try:
        return get_tonnage_distribution_chart(
            from_date=from_date,
            to_date=to_date,
            depot=depot,
            tonnage=tonnage,
            destination=destination,
            rank=rank,
        )
    except Exception as e:
        logger.exception("[API] GET /api/reports/charts/tonnage-distribution failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/reports/charts/losses-timeline")
def get_reports_losses_timeline_chart(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    depot: str | None = Query(None),
    tonnage: float | None = Query(None),
    destination: str | None = Query(None),
):
    """Daily losses timeline for unsuccessful analysis."""
    try:
        return get_losses_timeline_chart(
            from_date=from_date,
            to_date=to_date,
            depot=depot,
            tonnage=tonnage,
            destination=destination,
        )
    except Exception as e:
        logger.exception("[API] GET /api/reports/charts/losses-timeline failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/bid-outcomes")
def get_bid_outcomes(
    job_id: str | None = Query(None, description="Filter by job id"),
    outcome_status: str | None = Query(
        None, description="Filter: won|lost|stopped|paused|failed"
    ),
    depot: str | None = Query(None, description="Filter by depot name"),
    from_date: str | None = Query(None, description="Completed on/after YYYY-MM-DD"),
    to_date: str | None = Query(None, description="Completed on/before YYYY-MM-DD"),
    limit: int | None = Query(None, ge=1, le=5000, description="Max rows"),
):
    """List immutable historical bid outcomes (Reports read-only)."""
    try:
        return list_bid_outcomes(
            job_id=job_id,
            outcome_status=outcome_status,
            depot=depot,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
        )
    except Exception as e:
        logger.exception("[API] GET /api/bid-outcomes failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/bid-outcomes/summary")
def get_bid_outcomes_summary(
    depot: str | None = Query(None, description="Filter by depot name"),
    from_date: str | None = Query(None, description="Completed on/after YYYY-MM-DD"),
    to_date: str | None = Query(None, description="Completed on/before YYYY-MM-DD"),
):
    """Aggregate bid outcome counts for Reports."""
    try:
        return get_outcomes_summary(
            depot=depot,
            from_date=from_date,
            to_date=to_date,
        )
    except Exception as e:
        logger.exception("[API] GET /api/bid-outcomes/summary failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/bid-outcomes/{job_id}")
def get_bid_outcomes_by_job(job_id: str):
    """Historical outcomes for one bidding job."""
    try:
        return list_outcomes_for_job(job_id)
    except Exception as e:
        logger.exception("[API] GET /api/bid-outcomes/%s failed", job_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/live-bids")
def get_live_bids(
    job_id: str | None = Query(None, description="Filter by bidding job id"),
    active_only: bool = Query(False, description="Exclude won/completed/stopped legs"),
):
    """List live bid rows for the real-time dashboard."""
    try:
        return list_live_bids(job_id=job_id, active_only=active_only)
    except Exception as e:
        logger.exception("[API] GET /api/live-bids failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/live-bids/{leg_id}/pause")
def pause_live_bid(leg_id: str):
    """Cooperatively pause one desired bid leg (monitoring continues)."""
    rec = get_live_bid(leg_id)
    if not rec:
        raise HTTPException(status_code=404, detail="live bid not found")
    job_id = rec.get("job_id", "")
    depot = rec.get("depot", "")
    quantity = rec.get("quantity", 0)
    destination = rec.get("destination")
    
    if not set_user_control(leg_id, USER_CONTROL_PAUSED):
        raise HTTPException(status_code=500, detail="failed to pause live bid")
    
    # Log the pause action with execution marker
    logger.info(
        "[API] PAUSE job_id=%s depot=%s qty=%s dest=%s leg_id=%s",
        job_id,
        depot,
        quantity,
        destination,
        leg_id,
    )
    
    return {"status": "ok", "id": leg_id, "user_control": USER_CONTROL_PAUSED}


@app.post("/api/live-bids/{leg_id}/resume")
def resume_live_bid(leg_id: str):
    """Resume a paused desired bid leg."""
    rec = get_live_bid(leg_id)
    if not rec:
        raise HTTPException(status_code=404, detail="live bid not found")
    job_id = rec.get("job_id", "")
    depot = rec.get("depot", "")
    quantity = rec.get("quantity", 0)
    destination = rec.get("destination")
    
    if not set_user_control(leg_id, USER_CONTROL_ACTIVE):
        raise HTTPException(status_code=500, detail="failed to resume live bid")
    
    # Log the resume action with execution marker
    logger.info(
        "[API] RESUME job_id=%s depot=%s qty=%s dest=%s leg_id=%s",
        job_id,
        depot,
        quantity,
        destination,
        leg_id,
    )
    
    return {"status": "ok", "id": leg_id, "user_control": USER_CONTROL_ACTIVE}


@app.post("/api/live-bids/{leg_id}/stop")
def stop_live_bid(leg_id: str):
    """Stop a bid leg and kill the associated browser process."""
    rec = get_live_bid(leg_id)
    if not rec:
        raise HTTPException(status_code=404, detail="live bid not found")
    job_id = rec.get("job_id", "")
    depot = rec.get("depot", "")
    quantity = rec.get("quantity", 0)
    destination = rec.get("destination")
    
    if not set_user_control(leg_id, USER_CONTROL_STOPPED):
        raise HTTPException(status_code=500, detail="failed to stop live bid")
    
    # Kill the worker process running the browser for this bid
    process_killed = False
    try:
        from src.worker_registry import kill_worker_for_leg, get_worker_pid
        worker_pid = get_worker_pid(leg_id)
        logger.info("[API] STOP: leg_id=%s worker_pid=%s - attempting kill", leg_id, worker_pid)
        process_killed = kill_worker_for_leg(leg_id)
        logger.info("[API] STOP: leg_id=%s process_killed=%s", leg_id, process_killed)
    except Exception as e:
        logger.warning("[API] Failed to kill worker process for leg_id=%s: %s", leg_id, e)
    
    # Log the stop action with execution marker
    logger.info(
        "[API] STOP job_id=%s depot=%s qty=%s dest=%s leg_id=%s process_killed=%s",
        job_id,
        depot,
        quantity,
        destination,
        leg_id,
        process_killed,
    )
    
    return {"status": "ok", "id": leg_id, "user_control": USER_CONTROL_STOPPED, "process_killed": process_killed}


@app.post("/api/live-bids/{leg_id}/restart")
def restart_live_bid(leg_id: str, show_browser: bool = Query(default=True)):
    """Restart an orphaned or stopped live bid."""
    rec = get_live_bid(leg_id)
    if not rec:
        raise HTTPException(status_code=404, detail="live bid not found")
    
    job_id = rec["job_id"]
    leg_id_str = rec["id"]
    depot = rec.get("depot", "")
    quantity = rec.get("quantity", 0)
    destination = rec.get("destination")
    
    # Log the restart action with execution marker
    logger.info(
        "[API] RESTART job_id=%s depot=%s qty=%s dest=%s leg_id=%s show_browser=%s",
        job_id,
        depot,
        quantity,
        destination,
        leg_id,
        show_browser,
    )
    
    # Get the job to retrieve the payload
    job = get_bid_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    
    # Extract headless and record_on_bid_start from job (top-level fields)
    # In multiprocess mode, payload is a list, not a dict
    headless = job.get("headless", False)
    record_on_bid_start = job.get("record_on_bid_start", False)
    
    # Override headless with show_browser parameter from frontend
    # show_browser=True means NOT headless (headless=False)
    # show_browser=False means headless (headless=True)
    final_headless = not show_browser
    
    logger.info(f"[API] Restarting bid leg {leg_id} with show_browser={show_browser}, headless={final_headless}")
    
    # Re-trigger the bid with the same parameters
    try:
        # Reset user_control to allow restart
        db_live = get_live_db()
        db_live.execute(
            "UPDATE live_bids SET user_control = ? WHERE id = ?",
            (USER_CONTROL_RUNNING, leg_id_str)
        )
        db_live.commit()
        
        # Trigger the bid - need to use trigger_bid or trigger_bid_legacy
        execution_mode = job.get("execution_mode", "legacy")
        
        # Get desired_bids from job for restart
        desired_bids = job.get("desired_bids", [])
        
        if execution_mode == "multiprocess":
            # For multiprocess jobs, re-run with the new headless override
            result = trigger_bid(
                truck_id=job.get("truck_id"),
                depot=None,  # Will use first depot from desired_bids
                depots=job.get("depots"),
                desired_bids=desired_bids,
                job_id=job_id,
                headless=final_headless,
                record_on_bid_start=record_on_bid_start,
            )
        else:
            # Legacy mode
            result = trigger_bid_legacy(
                truck_id=job.get("truck_id"),
                depot=None,  # Will use first depot from desired_bids
                depots=job.get("depots"),
                desired_bids=desired_bids,
                job_id=job_id,
                headless=final_headless,
                record_on_bid_start=record_on_bid_start,
            )
        
        # Return the new job_id if trigger_bid returns one, otherwise use the original job_id
        new_job_id = result.get("job_id") if isinstance(result, dict) else job_id
        return {"status": "restarting", "id": leg_id_str, "job_id": job_id, "new_job_id": new_job_id, "result": result}
    except Exception as e:
        logger.exception(f"[API] Failed to restart live bid {leg_id}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ============================================================
# ================== MASTER DATA ENDPOINTS ====================
# ============================================================

@app.get("/api/zones")
def get_zones():
    """List all zones from database."""
    try:
        result = list_zones()
        return {"zones": result.get("items", []), "total": result.get("total", 0)}
    except Exception as e:
        logger.exception("[API] GET /api/zones failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/plants")
def get_plants(zone_id: str | None = Query(None)):
    """List plants, optionally filtered by zone."""
    try:
        result = list_plants(zone_id)
        return {"plants": result.get("items", []), "total": result.get("total", 0)}
    except Exception as e:
        logger.exception("[API] GET /api/plants failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/plants/{plant_id}/depots")
def get_depots_for_plant(plant_id: str):
    """List depots for a plant."""
    try:
        result = list_depots_for_plant(plant_id)
        return {"depots": result.get("items", []), "total": result.get("total", 0)}
    except Exception as e:
        logger.exception(f"[API] GET /api/plants/{plant_id}/depots failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/tonnage-options")
def get_tonnage_options():
    """List tonnage options from database."""
    try:
        result = list_tonnage_options()
        return {"tonnage_options": result.get("items", []), "total": result.get("total", 0)}
    except Exception as e:
        logger.exception("[API] GET /api/tonnage-options failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ============================================================
# ================== SELENIUM UI SECTION ======================
# ============================================================

# -----------------------
# LOGIN PAGE (HTML)
# -----------------------

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Selenium Login</title>
        <style>
            body {
                font-family: Arial;
                background: #f2f2f2;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
            }
            .box {
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 0 10px rgba(0,0,0,0.1);
                width: 300px;
            }
            input, button {
                width: 100%;
                padding: 10px;
                margin-top: 10px;
            }
            button {
                background: #4CAF50;
                color: white;
                border: none;
                cursor: pointer;
            }
        </style>
    </head>
    <body>
        <div class="box">
            <h3>Login</h3>
            <form method="post" action="/do-login">
                <input id="username" name="username" placeholder="Username" required />
                <input id="password" name="password" type="password" placeholder="Password" required />
                <button id="loginBtn" type="submit">Login</button>
            </form>
        </div>
    </body>
    </html>
    """


# -----------------------
# LOGIN HANDLER
# -----------------------

@app.post("/do-login")
def do_login(username: str = Form(...), password: str = Form(...)):
    logger.info(f"[API] Login attempt: {username}")

    # Dummy auth (replace later with real logic)
    if username == "admin" and password == "admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    else:
        return HTMLResponse("""
            <h3>Login Failed</h3>
            <a href="/login">Try again</a>
        """)


# -----------------------
# DASHBOARD PAGE
# -----------------------

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return """
    <html>
    <body>
        <h2>Login Successful ✅</h2>
        <p>Welcome to Selenium Automation Dashboard</p>
    </body>
    </html>
    """
# -----------------------
# DEBUG LOG ENDPOINT
# -----------------------

class DebugLogRequest(BaseModel):
    message: str
    level: str = "INFO"
    job_id: str | None = None


@app.post("/api/debug-log")
def post_debug_log(data: DebugLogRequest):
    """Write a debug log message."""
    try:
        level = getattr(logging, data.level.upper(), logging.INFO)
        if data.job_id:
            logger.log(level, "[job=%s] %s", data.job_id, data.message)
        else:
            logger.log(level, data.message)
        return {"status": "ok", "level": data.level, "message": data.message}
    except Exception as e:
        logger.exception("[API] POST /api/debug-log failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


# -----------------------
# LIVE BIDS RESTART ENDPOINT
# -----------------------

class RestartBidRequest(BaseModel):
    show_browser: bool | None = None


@app.post("/api/live-bids/{job_id}/restart")
def restart_bid(job_id: str, data: RestartBidRequest | None = None):
    """Restart a live bid job."""
    from src.live_bid_store import get_live_bid_by_job_id
    
    try:
        # Get the existing bid record
        bid = get_live_bid_by_job_id(job_id)
        if not bid:
            raise HTTPException(status_code=404, detail="job not found")
        
        # Restart the job with new headless setting if provided
        show_browser = data.show_browser if data else None
        headless = False if show_browser else None  # show_browser=true -> headless=False
        
        # Re-trigger the bid
        result = trigger_bid(
            truck_id=bid.truck_id,
            depot=bid.depot,
            depots=None,
            desired_bids=[],
            headless=headless,
        )
        return {
            "status": "ok",
            "job_id": job_id,
            "message": f"Restarted job {job_id}",
            "result": result,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[API] POST /api/live-bids/%s/restart failed", job_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


# -----------------------
# RUN SERVER
# -----------------------

if __name__ == "__main__":
    import uvicorn

# -----------------------
# RUN SERVER
# -----------------------
import atexit
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src import bid_logging as blog


def cleanup_on_exit() -> None:
    try:
        archived = blog.archive_logs(days=1)
        if archived:
            print(f"Archived {len(archived)} log files")
        deleted = blog.cleanup_logs(days=30)
        if deleted:
            print(f"Deleted {len(deleted)} old log archives")
    except Exception as e:
        print(f"Cleanup error: {e}")


if __name__ == "__main__":
    # Register cleanup function
    atexit.register(cleanup_on_exit)
    
    import uvicorn
    uvicorn.run(
        "backend_server:app",
        host="127.0.0.1",
        port=8000,
        reload=False
    )
