# 03 — Complete System Flow

> This page is the **full story** of LogiBid, from a button click to reports.

Related: [12_Control_Panel_Flow](12_Control_Panel_Flow.md) · [13_Live_Bidding_Flow](13_Live_Bidding_Flow.md) · [05_Automation_Architecture](05_Automation_Architecture.md)

---

## The big lifecycle (one picture)

```
Vendor opens UI
      │
      ▼
Control Panel (choose depots + tonnage)
      │
      ▼
POST /api/start-bid
      │
      ▼
Backend creates Job + Live Bid legs
      │
      ▼
Parallel Orchestrator starts workers
      │   (with 210 second stagger between launches)
      ▼
Each worker: Chrome → SAP Login → Open E-Bidding
      │
      ▼
Monitoring starts for that depot
      │
      ▼
Bid appears → Planning → Ready → Executing
      │
      ▼
Waiting Rank → Rank check
      │
      ├─ Rank 1 → Successful Bid saved
      └─ Other ranks → Completed / Lost path
      │
      ▼
Observers copy into Outcomes + Notifications
      │
      ▼
Frontend polls Live Bids / Reports / Notifications
```

---

## Step-by-step explanation

### Step 1 — Vendor opens UI

User opens the React app and logs in (currently simple frontend login).

They go to **Control Panel**.

### Step 2 — Control Panel choices

User selects:

- Zone / Plant (reference lists)
- One or more **depots** (Ayodhya, Gonda, …)
- For each depot: tonnage (and maybe destination)

Then clicks **Start Bid**.

### Step 3 — API call

Frontend sends JSON like:

```json
{
  "depots": ["AYODHYA", "GONDA"],
  "desired_bids": [
    { "quantity": 25, "depot": "AYODHYA", "destination": "Rudoli" }
  ]
}
```

To: `POST http://127.0.0.1:8000/api/start-bid`

### Step 4 — Backend receives request

`backend_server.py`:

1. Validates quantities
2. Normalizes depot names
3. Checks `execution_mode` (currently **multiprocess**)
4. Calls `trigger_bid(...)`

### Step 5 — Job created

In multiprocess async mode:

- `job_store.create_job(...)` creates a **job_id**
- Job is also saved into `jobs.db`
- `register_job_legs(...)` creates rows in `live_bids.db` (one row per desired bid “leg”)

Frontend stores `job_id` in sessionStorage as `activeBidJobId`.

### Step 6 — Parallel orchestrator

`parallel_orchestrator.py`:

1. Builds the depot list
2. Opens a process pool
3. Launches **one worker per depot**
4. Waits **210 seconds** between launching Depot A and Depot B (login stagger)

### Step 7 — Workers created

Each `run_depot_worker(...)` runs in its **own OS process**.

That means:

- Separate memory
- Separate Chrome
- One depot only

### Step 8 — Browser launches

Inside each worker:

1. `create_driver()` starts Chrome
2. Opens SAP URL
3. `login()` with credentials from config
4. Opens E-Bidding app

### Step 9 — Depot opens + monitoring

`DepotBiddingEngine.process_single_depot(depot)`:

- Fills plant + depot filters
- Searches
- Keeps checking for matching rows

Status published: `monitoring`

### Step 10 — Bid appears

When matching rows are found:

Status moves toward: `bid_appeared` → `planning`

### Step 11 — Planning

Engine decides:

- Which rows match desired quantity/destination
- What bid amount to prepare (business rules)

Status: `planning` → `ready`

### Step 12 — Execution

When the portal timer says it is time:

- Bid amounts are typed into the page
- Save/confirm dialogs are handled

Status: `executing` → `waiting_rank`

### Step 13 — Rank detection

Engine reads the bid rank from the page.

- Rank **1** → status `won` + write to `successful_bids.db`
- Other ranks → status `completed` (not a win)

### Step 14 — Databases update

| Event | Database |
|---|---|
| Live status changes | `live_bids.db` |
| Rank 1 win | `successful_bids.db` |
| Job progress | `jobs.db` |
| Later sync | `bid_outcomes.db`, `notifications.db` |

### Step 15 — Reports & Notifications

Background threads (every ~5 seconds):

- Copy finished results into `bid_outcomes.db`
- Create notification rows

### Step 16 — Frontend refresh

Pages poll APIs:

| Page | Asks |
|---|---|
| Live Bidding | `GET /api/live-bids` every 2 seconds |
| Successful Bids | `GET /api/successful-bids` |
| Reports | `GET /api/reports/...` |
| Notifications | `GET /api/notifications` |

---

## Sequence diagram (high level)

```
Vendor UI          FastAPI           Orchestrator        Worker Chrome
   │                  │                    │                  │
   │  start-bid       │                    │                  │
   │─────────────────>│                    │                  │
   │  job_id          │                    │                  │
   │<─────────────────│                    │                  │
   │                  │  start thread      │                  │
   │                  │───────────────────>│                  │
   │                  │                    │ submit worker A  │
   │                  │                    │─────────────────>│
   │                  │                    │ wait 210s        │
   │                  │                    │ submit worker B  │
   │                  │                    │─────────────────>│
   │  poll live-bids  │                    │                  │
   │─────────────────>│ read live_bids.db  │                  │
   │  statuses        │                    │                  │
   │<─────────────────│                    │                  │
```

---

## Two clocks in your mind

1. **Launch clock** — when each Chrome starts (staggered by 210 seconds)
2. **Bid clock** — SAP “Start In / Expires In” timer inside each depot page

They are different. Stagger controls Chrome start. SAP timer controls bid typing.

---

## Where to go next

- Want deeper “Start Bid” detail? → [12_Control_Panel_Flow.md](12_Control_Panel_Flow.md)
- Want status meanings? → [13_Live_Bidding_Flow.md](13_Live_Bidding_Flow.md)
- Want automation internals? → [05_Automation_Architecture.md](05_Automation_Architecture.md)
