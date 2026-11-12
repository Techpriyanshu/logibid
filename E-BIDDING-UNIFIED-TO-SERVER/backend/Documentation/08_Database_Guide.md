# 08 — Database Guide

> All LogiBid databases explained like notebooks on a shelf.

Related: [14_Reports_Architecture](14_Reports_Architecture.md) · [15_Notifications_Architecture](15_Notifications_Architecture.md)

---

## Where databases live

LogiBid uses a relational database layer mapped via **SQLAlchemy** in [db.py](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/backend/src/db.py).

### 1) MySQL (Primary Mode)
By default, the backend connects to a **MySQL** server configured via the `DATABASE_URL` environment variable. All tables reside inside the same schema.

### 2) SQLite (Fallback Mode)
If `DATABASE_URL` is explicitly configured with a `sqlite://` scheme, the backend falls back to using SQLite. When configured, tables are persisted to a local file database (the folder `data/` is otherwise only used for compliance documents under `truck_documents/`).

### Tables Schema
The database contains the following tables:
1. `jobs` — Queued and running bidding jobs progress
2. `job_artifacts` — Performance CSV and screen recording paths
3. `live_bids` — Real-time active bid legs scoreboard
4. `fleet_daily_entries` — Day-to-day truck availability entries
5. `fleet_control_requests` — Pause/close requests from fleet users
6. `notifications` — Event alerts feed
7. `bid_outcomes` — Historical results archive for reporting
8. `successful_bids` — Permanent Rank-1 won trips log

---

## Big idea: operational vs historical

| Type | Meaning | Examples |
|---|---|---|
| **Operational** | Needed while work is happening | live_bids, fleet daily/requests |
| **Historical** | Kept for history/reports | successful_bids, bid_outcomes, notifications, jobs |

---

## 1) `live_bids` table

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

## 2) `successful_bids` table

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

## 3) `jobs` table

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

## 4) `truck_master` tables

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

## 5) `fleet_admin` tables

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

## 6) `bid_outcomes` table

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

## 7) `notifications` table

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
jobs ────────────────┐
                     │ job_id
live_bids ───────────┼──► bid_outcomes ──► reports
                     │
successful_bids ─────┘

fleet_control_requests ──(approve)──► live_bids.user_control

trucks ◄── referenced by fleet daily entries (by truck number)
```

There is **no hard foreign-key mega schema** binding these tables together.
Links are maintained logically via shared IDs/names (`job_id`, `leg_id`, truck number).

---

## Data flow diagram

```
Automation writes
   ├─ live_bids table
   ├─ successful_bids table
   └─ jobs table
          │
          ▼
   Observer threads
          │
          ├─ bid_outcomes table ──► Reports UI
          └─ notifications table ──► Notifications UI
```

---

## Why separate tables / modules?

1. **Safer isolation**: Issues or schema migrations for one table do not affect unrelated components.
2. **Clear ownership**: Clear boundaries for which modules are allowed to write/read.
3. **Decoupled reporting**: Read-intensive reports fetch from `bid_outcomes` without blocking the core bidding table (`live_bids`).

---

Next: [09_API_Guide.md](09_API_Guide.md)
