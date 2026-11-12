# 07 — Function-by-Function Guide

> Important functions explained in plain English.  
> Not every tiny helper — the ones you will meet while debugging.

Related: [06_File_by_File_Explanation](06_File_by_File_Explanation.md) · [05_Automation_Architecture](05_Automation_Architecture.md)

---

## How to read one function card

For each function:

- **Purpose** — why it exists  
- **Input / Output**  
- **Who calls it**  
- **What it changes**  
- **DB read/write**  
- **When it runs**

---

## Bidding start path

### `backend_server.start_bid`

| | |
|---|---|
| Purpose | Accept Start Bid request from UI |
| Input | JSON depots + desired_bids |
| Output | job_id / status JSON |
| Who calls | Control Panel |
| Changes | Creates job + starts automation |
| DB | jobs, live_bids (via stores), notifications emit |
| When | User clicks Start Bid |

### `selenium_service.trigger_bid`

| | |
|---|---|
| Purpose | Choose multiprocess or legacy and start |
| Input | depot(s), desired_bids, sync flag |
| Output | Result dict with execution_mode |
| Who calls | `start_bid` |
| When | Immediately after API validation |

### `parallel_orchestrator.start_multiprocess_job_async`

| | |
|---|---|
| Purpose | Create job and launch orchestrator thread |
| Input | truck_id, depots, desired_bids |
| Output | `{ job_id, status: queued, ... }` |
| DB write | jobs.db, live_bids legs |
| When | Multiprocess + sync=false (normal UI path) |

### `parallel_orchestrator._submit_workers_sequential_stagger`

| | |
|---|---|
| Purpose | Submit one worker per depot with delay |
| Input | process pool, depot list, stagger seconds |
| Output | map of Future → depot name |
| Changes | Starts worker processes |
| Special | `time.sleep(login_stagger_seconds)` between launches (default **210**) |
| When | Inside sync/async multiprocess run |

### `selenium_worker.run_depot_worker`

| | |
|---|---|
| Purpose | Full worker lifecycle for one depot |
| Input | payload with depot_name, desired_bids, job_id |
| Output | result dict (status, rows, errors, pid…) |
| Changes | Opens Chrome, runs bidding |
| DB | Indirect via engine |
| When | Process pool executes the submitted task |

---

## Browser + login

### `driver_factory.create_driver`

| | |
|---|---|
| Purpose | Create a Chrome WebDriver |
| Output | Selenium driver object |
| Who calls | `run_depot_worker` |
| When | Start of each worker attempt |

### `login_service.login`

| | |
|---|---|
| Purpose | Login to SAP portal |
| Input | driver |
| Output | none (raises on hard failure) |
| Reads | credentials from env/config |
| When | After opening SAP URL |
| Note | Retries on 406 block pages |

---

## Engine core

### `DepotBiddingEngine.process_single_depot`

| | |
|---|---|
| Purpose | Run full workflow for one depot |
| Input | depot name |
| Output | result dictionary |
| Who calls | `run_depot_worker` |
| Changes | Page actions + status publishes + maybe successful bid |
| When | After login and opening bidding app |

### `live_status.publish_monitoring_cycle` / `publish_planning` / `publish_executing` / `publish_waiting_rank` / `publish_rank_for_desired`

| | |
|---|---|
| Purpose | Write current stage into live_bids |
| Who calls | Engine at each stage |
| DB write | live_bids.db |
| Special | Designed not to crash bidding if publish fails |

### `live_status.is_leg_active` / `desired_bids_for_planning`

| | |
|---|---|
| Purpose | Skip paused/stopped legs |
| DB read | live_bids user_control |
| When | Before planning/execution decisions |

### `DepotBiddingEngine._persist_successful_bid_after_rank_one`

| | |
|---|---|
| Purpose | Save Rank-1 win permanently |
| DB write | successful_bids.db |
| When | After rank confirmed as 1 |

---

## Live bids store

### `live_bids_store.register_job_legs`

| | |
|---|---|
| Purpose | Create live rows when job starts |
| DB write | live_bids.db |
| Who calls | Orchestrator / start path |
| When | Right after job creation |

### `live_bids_store.update_live_bid`

| | |
|---|---|
| Purpose | Update status/rank/org/control fields |
| Who calls | live_status |
| DB write | live_bids.db |

### `live_bids_store.set_user_control`

| | |
|---|---|
| Purpose | Pause/resume/stop a leg |
| Who calls | backend live-bid APIs; fleet approve path |
| DB write | live_bids.db |

### `live_bids_store.list_live_bids`

| | |
|---|---|
| Purpose | Return legs for UI |
| DB read | live_bids.db |
| API | GET `/api/live-bids` |

---

## Jobs

### `job_store.create_job` / `mark_running` / `record_depot_result` / `finalize` / `get_job`

| | |
|---|---|
| Purpose | Track job lifecycle for polling |
| DB | write-through to jobs.db |
| API | GET `/api/bid-job/{job_id}` |
| Frontend | Control Panel waits for completion |

---

## Successful bids / trucks / fleet

### `successful_bids_store.list_successful_bids`

| | |
|---|---|
| Purpose | List wins with optional date/depot filters |
| DB read | successful_bids.db |
| API | GET `/api/successful-bids` |

### Truck master CRUD + document functions

| | |
|---|---|
| Purpose | Manage trucks and uploaded documents |
| DB | truck_master.db + files |
| API | `/api/trucks...` |

### Fleet daily + request functions

| | |
|---|---|
| Purpose | Daily availability and pause/close requests |
| DB | fleet_admin.db |
| Side effect | Approve may call `set_user_control` |
| API | `/api/fleet-daily`, `/api/fleet-requests` |

---

## Observers

### `outcome_store.sync_outcomes_from_sources`

| | |
|---|---|
| Purpose | Mirror finished states into bid_outcomes |
| Reads | live_bids, successful_bids, jobs |
| Writes | bid_outcomes (insert only) |
| When | Every ~5s background loop / before some reads |

### `notifications_store.emit_automation_started` / fleet emitters

| | |
|---|---|
| Purpose | Create notification immediately on events |
| Writes | notifications.db |
| When | start-bid / fleet request create/resolve |

### `notifications_store.sync_notifications_from_observers`

| | |
|---|---|
| Purpose | Create notifications from outcomes/jobs |
| When | Notification sync loop |

### Reports store getters

| | |
|---|---|
| Purpose | Summary + chart datasets |
| Reads | bid_outcomes.db |
| API | `/api/reports/...` |

---

## Execution order cheat sheet (Start Bid)

```
1. start_bid
2. trigger_bid
3. start_multiprocess_job_async
4. create_job + register_job_legs
5. _async_job_thread
6. _submit_workers_sequential_stagger
7. run_depot_worker (per depot)
8. create_driver + login
9. process_single_depot
10. live_status publishes...
11. maybe insert_successful_bid
12. observers sync outcomes/notifications
13. UI polls APIs
```

Next: [08_Database_Guide.md](08_Database_Guide.md)
