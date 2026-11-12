# 06 — File-by-File Explanation (Backend)

> For each important backend file: **why it exists, who calls it, what it calls, DBs, APIs, UI.**

Related: [02_Folder_Structure](02_Folder_Structure.md) · [07_Function_by_Function_Guide](07_Function_by_Function_Guide.md)

---

## How to read each section

Every file section uses this pattern:

```
Who calls this file?
↓
What does it do?
↓
Which files it calls?
↓
Which DB it reads?
↓
Which DB it writes?
↓
Which API exposes it?
↓
Which frontend page shows the data?
```

---

## `backend_server.py`

**Purpose:** The public door of the system. All UI APIs live here.

| | |
|---|---|
| Who calls it | Frontend browser, Uvicorn |
| What it does | Validate requests, call stores/automation, return JSON |
| Calls | Almost every `src/*` module |
| DB read/write | Indirectly through stores |
| APIs | All `/api/...` endpoints |
| Frontend | All pages |

Also starts DB init + outcome/notification background loops on startup.

---

## `src/selenium_service.py`

**Purpose:** Decide how to run automation (multiprocess vs legacy) and start it.

| | |
|---|---|
| Who calls it | `backend_server.start_bid` |
| What it does | Dispatch to orchestrator or legacy path |
| Calls | `parallel_orchestrator`, legacy helpers |
| DB | Indirect (via orchestrator/job store) |
| API | `/api/start-bid` |
| Frontend | Control Panel |

---

## `src/parallel_orchestrator.py`

**Purpose:** Manager for multiprocess depot workers.

| | |
|---|---|
| Who calls it | `selenium_service.trigger_bid` |
| What it does | Create job, stagger-launch one worker per depot, collect results |
| Calls | `selenium_worker.run_depot_worker`, `job_store`, `live_bids_store.register_job_legs` |
| DB write | `jobs.db` (via job_store), `live_bids.db` (register legs) |
| API | `/api/start-bid`, results visible via `/api/bid-job/{id}` |
| Frontend | Control Panel job polling, Live Bidding |

Key idea: **`login_stagger_seconds = 210`** between launches.

---

## `src/selenium_worker.py`

**Purpose:** One worker process = one Chrome + one depot.

| | |
|---|---|
| Who calls it | Process pool in orchestrator |
| What it does | Create driver, login, run engine for one depot |
| Calls | `driver_factory`, `login_service`, `DepotBiddingEngine` |
| DB | Indirect through engine/live status |
| API | None directly |
| Frontend | Indirect via live bids |

---

## `src/depot_bidding_engine.py`

**Purpose:** The bidding brain (largest automation file).

| | |
|---|---|
| Who calls it | `selenium_worker` |
| What it does | Open app, search, monitor, plan, execute, detect rank |
| Calls | `live_status`, `successful_bids_store`, Selenium APIs |
| DB write | `live_bids.db` (via live_status), `successful_bids.db` on Rank 1 |
| API | None directly |
| Frontend | Live Bidding, Successful Bids |

Treat this file as sensitive.

---

## `src/live_status.py`

**Purpose:** Safe status publisher between engine and DB.

| | |
|---|---|
| Who calls it | `depot_bidding_engine` |
| What it does | Publish monitoring/planning/executing/won/etc; check pause/stop |
| Calls | `live_bids_store.update_live_bid`, `get_user_control` |
| DB read/write | `live_bids.db` |
| API | Indirect (`/api/live-bids`) |
| Frontend | Live Bidding pages |

---

## `src/live_bids_store.py`

**Purpose:** SQLite store for live bid legs.

| | |
|---|---|
| Who calls it | Orchestrator, live_status, backend pause/resume/stop, fleet approve path |
| What it does | Create legs, update status/rank/control, list legs |
| DB | `live_bids.db` |
| API | `/api/live-bids`, pause/resume/stop |
| Frontend | Live Bidding, Sidebar indicators, parts of Home fleet logic |

---

## `src/successful_bids_store.py`

**Purpose:** Permanent Rank-1 win records.

| | |
|---|---|
| Who calls it | `depot_bidding_engine` (write), backend (read) |
| What it does | Insert win; list wins with filters |
| DB | `successful_bids.db` |
| API | `/api/successful-bids` |
| Frontend | Successful Bids page |

---

## `src/job_store.py` and `src/jobs_store.py`

**Purpose:** Track job progress for polling.

| | |
|---|---|
| Who calls them | Orchestrator, backend `/api/bid-job/{id}` |
| What they do | Create/update job status; persist to SQLite |
| DB | `jobs.db` |
| API | `/api/bid-job/{job_id}` |
| Frontend | Control Panel polling |

Difference:

- `job_store.py` = in-memory manager + write-through
- `jobs_store.py` = SQLite helper functions

---

## `src/truck_master_store.py`

**Purpose:** Truck registry and vehicle documents.

| | |
|---|---|
| Who calls it | backend truck APIs; fleet store may validate trucks |
| DB | `truck_master.db` + files in `data/truck_documents/` |
| API | `/api/trucks...` |
| Frontend | Truck Master, Reports truck KPIs |

---

## `src/fleet_admin_store.py`

**Purpose:** Daily truck availability + pause/close requests.

| | |
|---|---|
| Who calls it | backend fleet APIs |
| What it does | CRUD daily entries; create/resolve requests; on approve, set live bid control |
| DB write | `fleet_admin.db`; may write `live_bids.db` control on approve |
| API | `/api/fleet-daily`, `/api/fleet-requests` |
| Frontend | Admin Dashboard, Admin/Vendor Live Bidding |

---

## `src/outcome_store.py`

**Purpose:** Historical outcomes observer (insert-only).

| | |
|---|---|
| Who calls it | Startup background thread; reports/notifications may trigger sync |
| Reads | `live_bids.db`, `successful_bids.db`, `jobs.db` |
| Writes | `bid_outcomes.db` |
| API | `/api/bid-outcomes...` (and used by reports) |
| Frontend | Reports (via reports APIs), notifications indirectly |

---

## `src/reports_store.py`

**Purpose:** Read-only analytics queries on outcomes.

| | |
|---|---|
| Who calls it | backend report endpoints |
| Reads | `bid_outcomes.db` |
| Writes | none |
| API | `/api/reports/...` |
| Frontend | Reports page |

---

## `src/notifications_store.py`

**Purpose:** Notification rows + emitters + observer sync.

| | |
|---|---|
| Who calls it | backend (emit on start-bid / fleet events), sync thread |
| Writes | `notifications.db` |
| Reads | also observes outcomes/jobs for new events |
| API | `/api/notifications...` |
| Frontend | Notifications page, Sidebar unread badge |

---

## Helper files

| File | Simple purpose |
|---|---|
| `config_loader.py` | Load YAML + credentials |
| `driver_factory.py` | Create Chrome WebDriver |
| `login_service.py` | SAP login (with 406 retry logic) |
| `logging_service.py` | Logging setup |
| `depot_normalization.py` | Normalize depot name strings |
| `depot_execution_engine.py` | Smaller/older helper related to execution concepts |
| `parallel_execution_orchestrator.py` | Older thread-pool style orchestrator remnant |
| `driver_manager.py` | Small driver helper |
| `rollback_tile_open_bidding_app.py` | Helper around opening bidding tile/app |

---

## Quick dependency map

```
UI pages
  └── backend_server.py
        ├── *_store.py ──► data/*.db
        └── selenium_service.py
              └── parallel_orchestrator.py
                    └── selenium_worker.py
                          └── depot_bidding_engine.py
                                ├── live_status.py ──► live_bids_store.py
                                └── successful_bids_store.py
```

Next: [07_Function_by_Function_Guide.md](07_Function_by_Function_Guide.md)
