# 05 — Automation Architecture (Most Important)

> This page explains **how Chrome bidding actually runs**.  
> Read slowly. This is the heart of LogiBid.

Related: [03_Complete_System_Flow](03_Complete_System_Flow.md) · [12_Control_Panel_Flow](12_Control_Panel_Flow.md) · [13_Live_Bidding_Flow](13_Live_Bidding_Flow.md)

---

## Why automation exists

The SAP e-Bidding portal is a normal website.

A human would:

1. Open Chrome
2. Login
3. Open E-Bidding
4. Choose depot
5. Wait
6. Type bid amounts quickly
7. Check rank

Automation does the same steps using **Selenium** (a tool that controls Chrome).

---

## The main cast (who does what)

| File | Role (simple) |
|---|---|
| `selenium_service.py` | Chooses mode and starts the job |
| `parallel_orchestrator.py` | Manager: creates one worker per depot |
| `selenium_worker.py` | Worker: one process, one Chrome, one depot |
| `depot_bidding_engine.py` | Brain: monitor, plan, execute, rank |
| `live_status.py` | Messenger: publish status without crashing bidding |
| `live_bids_store.py` | Notebook for live statuses |
| `successful_bids_store.py` | Trophy cabinet for Rank-1 wins |

### Who calls whom

```
backend_server.py
   └── selenium_service.trigger_bid
         └── parallel_orchestrator.start_multiprocess_job_async
               └── (background thread)
                     └── ProcessPoolExecutor
                           └── selenium_worker.run_depot_worker   [one per depot]
                                 ├── driver_factory.create_driver
                                 ├── login_service.login
                                 └── DepotBiddingEngine.process_single_depot
                                       ├── live_status.publish_*  → live_bids_store
                                       └── insert_successful_bid  → successful_bids_store
```

---

## Execution mode today

In `config/application.yaml`:

```yaml
automation:
  execution_mode: multiprocess
```

That means:

- **Not** one shared browser for everything
- **Yes** one OS process + one Chrome **per depot**

There is also a `legacy` mode (older single-driver / tabs style), but current config uses multiprocess.

---

## Multiprocessing in plain English

Imagine 5 depots selected.

The orchestrator opens a pool that can hold 5 workers.

Then it launches them like this:

```
t=0s     Launch Ayodhya worker  → Chrome A starts
t=210s   Launch Gonda worker    → Chrome B starts
t=420s   Launch Gorakhpur ...
...
```

Configured delay:

```yaml
login_stagger_seconds: 210
```

Implemented in:

- File: `parallel_orchestrator.py`
- Function: `_submit_workers_sequential_stagger`
- Call: `time.sleep(login_stagger_seconds)`

### Why stagger?

Starting many SAP logins at the exact same second can cause login conflicts.  
So the system waits **210 seconds** between launching workers.

### Important detail

After launch, workers run **at the same time** (parallel execution).  
Only the **start** is staggered.

---

## Worker lifecycle (one depot)

```
Worker process starts
   │
   ▼
Create Chrome (create_driver)
   │
   ▼
Open SAP URL
   │
   ▼
Login
   │
   ▼
Create DepotBiddingEngine(depot=Ayodhya, desired_bids=...)
   │
   ▼
Open E-Bidding app
   │
   ▼
process_single_depot(...)
   │
   ├─ Monitor loop
   ├─ Plan matching rows
   ├─ Wait for timer
   ├─ Enter bids
   ├─ Read ranks
   └─ Save win if Rank 1
   │
   ▼
Optional: keep browser open (keepalive)
```

---

## Browser lifecycle

| Moment | What happens |
|---|---|
| Worker starts | Chrome created |
| During bidding | Browser stays open and is controlled by Selenium |
| After success | Often kept open (`keep_browser_open: true`) for session visibility |
| On hard failure | Browser may close after retries |

How many Chromes?

> **One Chrome instance per depot worker** currently running.

5 depots launched ⇒ up to 5 Chromes.

---

## How one depot is isolated

Each worker payload contains only one depot:

```python
{
  "depot_name": "AYODHYA",
  "desired_bids": [ ... filtered for this depot ... ],
  "job_id": "...."
}
```

So:

- Ayodhya worker never searches Gonda
- Crash in one worker should not kill other processes
- Each has its own login session

---

## Desired bids

A **desired bid** means: “I want this tonnage (and maybe destination) for this depot.”

Example:

```json
{ "quantity": 25, "depot": "AYODHYA", "destination": "Rudoli" }
```

In the database/UI this becomes a **leg** (one live row).

---

## Monitoring (waiting for opportunity)

While waiting, engine repeatedly searches the page.

Statuses you may see:

- `monitoring`
- `paused` / `stopped` (if user control says so)

Config examples:

- `live_monitor_poll_seconds` — delay between searches
- `live_monitor_total_seconds` — 0 means keep monitoring without timeout

---

## Planning

When matching rows appear:

1. Parse table rows
2. Match against desired quantity / destination rules
3. Prepare bid amounts (business formula)

Status path includes: `bid_appeared` → `planning` → `ready`

---

## Execution

When SAP timer text indicates it is time:

1. Fill bid amount fields
2. Save
3. Confirm dialogs

Status: `executing` → `waiting_rank`

Inside one depot, filling multiple inputs can use a thread pool for speed.  
That is **inside one Chrome**, not launching new depots.

---

## Pause / Resume / Stop

User (or approved fleet request) can change `user_control` in `live_bids.db`:

| Control | Meaning |
|---|---|
| `active` | Normal |
| `paused` | Skip this leg in planning/execution |
| `stopped` | Stop this leg |

`live_status.py` checks control each cycle:

- If paused/stopped → publish that status
- Active legs continue

API endpoints:

- `POST /api/live-bids/{leg_id}/pause`
- `POST /api/live-bids/{leg_id}/resume`
- `POST /api/live-bids/{leg_id}/stop`

---

## Rank detection and success

After execute, engine reads rank from the page.

```
Rank == 1
   → live status = won
   → insert_successful_bid(...) into successful_bids.db

Rank != 1
   → live status = completed (with rank number)
```

---

## live_status.py — why it exists

Bidding is fragile. If status writing crashes, bidding should still continue.

So `live_status.py`:

- Wraps updates carefully
- Never raises into the engine
- Translates engine moments into DB statuses

---

## Job vs Worker vs Leg

| Word | Meaning |
|---|---|
| **Job** | One Start Bid action (may include many depots) |
| **Worker** | One process for one depot |
| **Leg** | One desired bid line (depot + quantity + destination) |

Example:

- 1 job
- 3 depots ⇒ 3 workers
- 5 desired bids ⇒ 5 live legs

---

## Data flow during automation

```
Engine event
   │
   ▼
live_status.publish_*
   │
   ▼
live_bids_store.update_live_bid
   │
   ▼
live_bids.db
   │
   ▼
Frontend polls GET /api/live-bids
   │
   ▼
Live Bidding screen updates
```

Win path:

```
Rank 1 confirmed
   │
   ▼
successful_bids_store.insert_successful_bid
   │
   ▼
successful_bids.db
   │
   ▼
GET /api/successful-bids → Successful Bids page
```

---

## Safety reminder for freshers

Do not casually edit:

- `depot_bidding_engine.py`
- `parallel_orchestrator.py`
- `selenium_worker.py`
- `live_status.py`
- `live_bids_store.py`
- `successful_bids_store.py`

Small timing changes can break real bidding.

---

## What you should remember

1. Multiprocess = one Chrome per depot
2. Launch is staggered by **210 seconds**
3. Engine does monitor → plan → execute → rank
4. Live status is written continuously
5. Rank 1 is saved separately as a successful bid

Next: [06_File_by_File_Explanation.md](06_File_by_File_Explanation.md)
