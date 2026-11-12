# 12 — Control Panel Flow

> Exactly what happens after the user presses **Start Bid**.

Related: [03_Complete_System_Flow](03_Complete_System_Flow.md) · [05_Automation_Architecture](05_Automation_Architecture.md)

---

## Why this page matters

Control Panel is the **ignition key**.  
Almost every live Chrome session begins here.

---

## What the user does

1. Select zone / plant
2. Add depot cards (Ayodhya, Gonda, …)
3. Choose tonnages (and maybe destinations)
4. Click **Start Bid**

---

## Sequence diagram

```
User                ControlPanel.tsx           backend_server          orchestrator           worker
 │                        │                         │                      │                   │
 │  click Start Bid       │                         │                      │                   │
 │───────────────────────>│                         │                      │                   │
 │                        │ POST /api/start-bid     │                      │                   │
 │                        │────────────────────────>│                      │                   │
 │                        │                         │ create job + legs    │                   │
 │                        │                         │ start async thread   │                   │
 │                        │                         │─────────────────────>│                   │
 │                        │  { job_id, queued }     │                      │                   │
 │                        │<────────────────────────│                      │                   │
 │                        │ save job_id session     │                      │                   │
 │                        │                         │                      │ submit depot A    │
 │                        │                         │                      │──────────────────>│
 │                        │                         │                      │ sleep 210s        │
 │                        │                         │                      │ submit depot B    │
 │                        │                         │                      │──────────────────>│
 │                        │ poll /api/bid-job/{id}  │                      │                   │
 │                        │────────────────────────>│                      │                   │
 │                        │  status running/...     │                      │                   │
 │                        │<────────────────────────│                      │                   │
 │  toast finished        │                         │                      │                   │
 │<───────────────────────│                         │                      │                   │
```

---

## Frontend steps (detailed)

File: `src/pages/dashboard/ControlPanel.tsx`

1. Collect selected depots into `depots[]`
2. Expand each tonnage into `desired_bids[]` objects
3. `fetch POST /api/start-bid`
4. On success, `setActiveBidJobId(job_id)` (sessionStorage)
5. If mode is `multiprocess` or `legacy_async`, poll `GET /api/bid-job/{job_id}` every 2 seconds until terminal status
6. Show toast + results panel

---

## Backend steps (detailed)

File: `backend_server.py` → `start_bid`

1. Validate desired_bids not empty
2. Normalize depot names
3. Read `automation.execution_mode`
4. For multiprocess:
   - call `trigger_bid(...)`
   - emit `automation_started` notification (best effort)
   - return job_id to UI

File: `selenium_service.py` → `trigger_bid`

- Calls `start_multiprocess_job_async(...)` when sync=false

File: `parallel_orchestrator.py`

1. `create_job`
2. `register_job_legs` (creates live_bids rows)
3. Background thread opens `ProcessPoolExecutor`
4. `_submit_workers_sequential_stagger`:
   - launch first depot immediately
   - wait **210 seconds**
   - launch next depot
   - repeat

---

## What exists right after Start Bid returns

| Artifact | Where |
|---|---|
| `job_id` | API response + browser sessionStorage |
| Job row | `jobs` table |
| Live legs | `live_bids` table |
| Notification | `notifications` table (automation_started) |
| Worker Chromes | Start appearing on stagger schedule |

---

## Parallel vs staggered (again)

- **Launch**: staggered (210s)
- **Running**: parallel (multiple Chromes can be alive together)

---

## After execution ends

1. Job status becomes completed / failed / partial_failed
2. Control Panel polling stops
3. Live legs may show won/completed/stopped
4. Observers fill outcomes + more notifications
5. Successful Bids / Reports pages show history

---

## Common fresher mistakes

1. Thinking all Chromes start at second 0 → they don’t (210s stagger)
2. Forgetting job_id is in sessionStorage → Live pages may look empty in a new browser tab
3. Editing Control Panel reference lists expecting SAP to change → those lists are mostly UI helpers

---

Next: [13_Live_Bidding_Flow.md](13_Live_Bidding_Flow.md)
