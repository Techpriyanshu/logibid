# 17 — Debugging Guide

> How to investigate problems safely without guessing.

Related: [18_Project_FAQ](18_Project_FAQ.md) · [08_Database_Guide](08_Database_Guide.md)

---

## Golden rules

1. Prefer reading logs/DBs before changing code
2. Do not casually edit automation core files
3. Reproduce with one depot first when possible
4. Note the `job_id`

---

## Where logs appear

| Location | What you find |
|---|---|
| Terminal running Uvicorn | API + orchestrator messages |
| `logs/execution_phase/` | Detailed automation logs |
| `logs/jobs/{job_id}.json` | Job snapshot after finalize |
| `screenshots/` | Browser pictures on failures |
| Browser DevTools Network tab | Frontend API calls/responses |

---

## Trace one Start Bid (checklist)

1. In Control Panel, click Start Bid
2. Copy `job_id` from toast/console/network response
3. Confirm sessionStorage has `activeBidJobId`
4. Watch Live Bidding for legs of that job
5. Check orchestrator logs for:
   - `login_stagger waiting 210.0s`
   - `Launched depot=...`
6. For each depot worker, confirm Chrome opened and login progressed
7. When finished, open `logs/jobs/{job_id}.json`
8. Check Successful Bids if Rank 1 expected
9. Wait a few seconds, then check Reports/Notifications

---

## Trace one live leg

1. Get leg `id` from Live Bidding table / API JSON
2. Inspect `live_bids` table row for that id
3. Watch `status` and `user_control` change over time
4. If paused unexpectedly, check fleet requests for Approved PAUSE/CLOSE

---

## Inspect databases (simple)

For MySQL, you can use any database management tool (such as DBeaver, TablePlus, or command line client) using the credentials configured in `DATABASE_URL`. Or in Python:

```python
from sqlalchemy import create_engine
import os

engine = create_engine(os.getenv("DATABASE_URL"))
with engine.connect() as conn:
    res = conn.execute("SELECT id, depot, quantity, status, user_control FROM live_bids ORDER BY updated_at DESC LIMIT 20")
    for row in res:
        print(row)
```

In SQLite fallback mode:

```python
import sqlite3
# SQLite fallback URL connection
conn = sqlite3.connect(r"data\logibid.db") 
for row in conn.execute("SELECT id, depot, quantity, status, user_control FROM live_bids ORDER BY updated_at DESC LIMIT 20"):
    print(row)
```

Useful checks:

| Question | Database Table |
|---|---|
| Did legs get created? | live_bids |
| Did job finish? | jobs |
| Did we win? | successful_bids |
| Why empty reports? | bid_outcomes |
| Why no alerts? | notifications |

---

## Common symptoms → likely place

| Symptom | Look at |
|---|---|
| UI says job queued forever | `/api/bid-job/{id}`, jobs table, orchestrator logs |
| Live page empty | session job id missing; live_bids table empty |
| Only first depot Chrome appears for a long time | Expected: 210s stagger |
| Login fails on VPS/headless | login_service 406 logs, screenshots |
| Pause does nothing | user_control in DB; engine must be in active cycle |
| Reports empty but wins exist | outcome sync thread; bid_outcomes table |
| Notifications missing | emitters + sync loop; notifications table |

---

## Useful commands (examples)

Backend (from backend folder, with venv active):

```bash
uvicorn backend_server:app --host 127.0.0.1 --port 8000
```

Frontend (from frontend folder):

```bash
npm run dev
```

Quick API checks:

```bash
curl http://127.0.0.1:8000/api/live-bids
curl http://127.0.0.1:8000/api/successful-bids
curl http://127.0.0.1:8000/api/notifications
```

---

## Config knobs people often check

File: `config/application.yaml`

- `automation.execution_mode`
- `automation.multiprocess.login_stagger_seconds` (210)
- `live_monitor_poll_seconds`
- SAP URL / plant field ids

Credentials: `config/credentials.env` (never commit secrets)

---

## What “good debugging” looks like

```
Observe UI
  → capture job_id
  → check API JSON
  → check DB rows
  → check logs/screenshots
  → only then consider code changes
```

Next: [18_Project_FAQ.md](18_Project_FAQ.md)
