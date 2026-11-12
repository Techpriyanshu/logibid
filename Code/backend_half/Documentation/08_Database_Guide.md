# 08 — Database Guide

> All LogiBid databases explained like notebooks on a shelf.

Related: [14_Reports_Architecture](14_Reports_Architecture.md) · [15_Notifications_Architecture](15_Notifications_Architecture.md)

---

## Where databases live

Folder: `data/`

```
data/
├── live_bids.db
├── successful_bids.db
├── jobs.db
├── truck_master.db
├── fleet_admin.db
├── bid_outcomes.db
├── notifications.db
└── truck_documents/   (files, not a DB)
```

Technology: **SQLite** (a database stored as a normal file).  
No separate database server is required.

---

## Big idea: operational vs historical

| Type | Meaning | Examples |
|---|---|---|
| **Operational** | Needed while work is happening | live_bids, fleet daily/requests |
| **Historical** | Kept for history/reports | successful_bids, bid_outcomes, notifications, jobs |

---

## 1) `live_bids.db`

### Purpose

Track every **live bid leg** for the current jobs: status, rank, pause/stop.

### Main table: `live_bids`

Important fields (conceptually):

- `id` (leg id)
- `job_id`
- `depot`, `destination`, `quantity`
- `status` (monitoring, executing, won, …)
- `current_rank`
- `user_control` (active/paused/stopped)
- `updated_at`

### Who writes

- Orchestrator (`register_job_legs`)
- `live_status` / engine updates
- Pause/resume/stop APIs
- Fleet approve path (`set_user_control`)

### Who reads

- Live Bidding APIs
- Outcome observer
- Frontend Live pages

### Lifecycle

Created when Start Bid runs → updated during automation → remains as record of legs.

### Frontend

Live Bidding (Fleet/Vendor), Sidebar live indicator.

---

## 2) `successful_bids.db`

### Purpose

Permanent trophy list of **Rank 1 wins only**.

### Main table: `successful_bids`

- depot, destination, quantity
- bid_amount
- won_timestamp
- rank (always 1)

### Who writes

Only automation engine after Rank 1 confirmation.

### Who reads

Successful Bids API; outcome sync may use it for amounts.

### Frontend

Successful Bids page.

---

## 3) `jobs.db`

### Purpose

Remember each Start Bid **job**: queued/running/completed/failed.

### Main table: `bid_jobs`

- job_id, status
- depots JSON
- results/errors JSON
- timestamps

### Who writes

`job_store` write-through during orchestration.

### Who reads

`GET /api/bid-job/{id}`, observers.

### Frontend

Control Panel polling.

---

## 4) `truck_master.db`

### Purpose

Master list of trucks + document metadata.

### Tables

- `trucks`
- `vehicle_documents`

Files themselves are stored under `data/truck_documents/`.

### Who writes / reads

Truck APIs; fleet validation may check truck existence.

### Frontend

Truck Master; Reports truck KPIs.

---

## 5) `fleet_admin.db`

### Purpose

Day-to-day fleet operations.

### Tables

- `fleet_daily_entries` — availability for a date
- `fleet_control_requests` — PAUSE/CLOSE requests

### Who writes / reads

Fleet APIs.

### Special link

When a request is **Approved**, code may update `live_bids.user_control`.

### Frontend

Admin Dashboard, Admin/Vendor Live Bidding.

---

## 6) `bid_outcomes.db`

### Purpose

Unified history for analytics (won/lost/stopped/failed…).

### Main table: `bid_outcomes`

Filled by **observer sync** (insert-only).  
Does not drive the bidding engine.

### Who writes

`outcome_store.sync_outcomes_from_sources`

### Who reads

Reports store; notification observers.

### Frontend

Reports page (via `/api/reports/...`).

---

## 7) `notifications.db`

### Purpose

User-facing event feed.

### Main table: `notifications`

Created by:

- Immediate emitters (start bid, fleet events)
- Background observers (outcomes/jobs)

### Frontend

Notifications page + Sidebar unread count.

---

## Relationships (simple)

```
jobs.db ─────────────┐
                     │ job_id
live_bids.db ────────┼──► bid_outcomes.db ──► reports
                     │
successful_bids.db ──┘

fleet_admin.db ──(approve)──► live_bids.user_control

truck_master.db ◄── referenced by fleet daily entries (by truck number)
```

There is **no single foreign-key mega schema** across all files.  
Links are mostly by shared IDs/names (`job_id`, `leg_id`, truck number).

---

## Data flow diagram

```
Automation writes
   ├─ live_bids.db
   ├─ successful_bids.db
   └─ jobs.db
          │
          ▼
   Observer threads
          │
          ├─ bid_outcomes.db ──► Reports UI
          └─ notifications.db ──► Notifications UI
```

---

## Why separate DB files?

1. Safer isolation (one module’s DB issues don’t wipe everything)
2. Clear ownership (who is allowed to write what)
3. Easier to reason about operational vs historical data

(Unified `logibid.db` is a possible future idea, not current.)

---

Next: [09_API_Guide.md](09_API_Guide.md)
