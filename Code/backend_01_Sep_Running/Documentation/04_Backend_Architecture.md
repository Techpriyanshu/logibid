# 04 — Backend Architecture

> This page explains the **Python FastAPI backend** in simple words.

Related: [09_API_Guide](09_API_Guide.md) · [08_Database_Guide](08_Database_Guide.md) · [05_Automation_Architecture](05_Automation_Architecture.md)

---

## What is the backend?

The backend is a program that:

1. Listens on `http://127.0.0.1:8000`
2. Receives requests from the React UI
3. Starts automation jobs
4. Reads/writes relational databases (MySQL / SQLite fallback)
5. Returns JSON responses

Main file: **`backend_server.py`**

---

## How FastAPI starts

When you run:

```bash
uvicorn backend_server:app --host 127.0.0.1 --port 8000
```

or:

```bash
python backend_server.py
```

FastAPI creates an `app` object and starts listening for HTTP calls.

---

## Startup event (very important)

On startup, `startup_event()` runs once.

It initializes relational databases (MySQL by default or SQLite fallback) by mapping and preparing the required tables:

1. `successful_bids`
2. `live_bids`
3. `truck_master`
4. `jobs`
5. `fleet_daily_entries` / `fleet_control_requests`
6. `bid_outcomes`
7. `notifications`

Then it starts **two background threads**:

| Thread | Every | Job |
|---|---|---|
| Outcome sync | ~5 seconds | Copy finished bidding results into `bid_outcomes` table |
| Notification sync | ~5 seconds | Create notifications from outcomes/jobs |

These threads keep running while the server is alive.

```
Server starts
   │
   ├─ init all DBs
   ├─ start outcome-sync thread ──► loop forever
   └─ start notification-sync thread ──► loop forever
```

---

## CORS (why frontend can call backend)

Frontend runs on a different port (for example 8080).  
Browsers block cross-origin calls unless the backend allows them.

`backend_server.py` allows localhost origins like:

- `http://localhost:8080`
- `http://127.0.0.1:8080`
- similar for 8081

---

## How APIs are organized

This project does **not** use many separate router files.  
Most endpoints are declared directly in `backend_server.py` with:

- `@app.post(...)`
- `@app.get(...)`
- `@app.put(...)`
- `@app.patch(...)`
- `@app.delete(...)`

Groups:

1. Bidding / jobs
2. Live bids control
3. Successful bids
4. Trucks + documents
5. Fleet daily + fleet requests
6. Notifications
7. Reports
8. Bid outcomes
9. Legacy HTML login pages (old/simple)

---

## Request handling pattern

Almost every API follows this pattern:

```
HTTP request
   │
   ▼
Pydantic body / query params (validate input)
   │
   ▼
Call a store function (src/*_store.py)
   │
   ▼
Store talks to database tables
   │
   ▼
Return JSON
```

Example:

```
GET /api/successful-bids
   → list_successful_bids(...)
   → successful_bids table
   → { items: [...], total: N }
```

---

## Where automation is triggered

Only one API starts the heavy automation:

**`POST /api/start-bid`**

Flow:

```
start_bid()
   │
   ├─ if execution_mode == multiprocess
   │     → trigger_bid(...)
   │         → start_multiprocess_job_async(...)
   │
   └─ else legacy mode
         → background thread or blocking legacy Selenium
```

Default config today: **multiprocess**.

---

## Background observers (simple idea)

Automation writes into:

- `live_bids` table
- `successful_bids` table
- `jobs` table

Observers **watch** those tables (read-only) and fill:

- `bid_outcomes` table (for reports)
- `notifications` table (for alerts)

Why?

> So the bidding engine stays focused on bidding,  
> while reporting/notification logic stays separate.

---

## Logging

`logging_service.py` sets up loggers.

Useful places:

- `logs/execution_phase/` — detailed automation logs
- `logs/jobs/{job_id}.json` — job snapshot after completion
- console output while server runs

---

## Backend call hierarchy (simplified)

```
Frontend
  │
  ▼
backend_server.py
  │
  ├── store modules (CRUD / queries)
  │     └── Database (MySQL / SQLite fallback)
  │
  └── selenium_service.trigger_bid
        └── parallel_orchestrator
              └── selenium_worker
                    └── depot_bidding_engine
                          ├── live_status → live_bids_store
                          └── successful_bids_store
```

---

## What the backend is NOT

- Not a microservice mesh
- Not GraphQL
- Not JWT-authenticated for SPA APIs yet
- Not Dockerized in this codebase copy

It is a **practical monolith API** plus automation.

---

## Fresher checklist

After reading this, you should know:

1. `backend_server.py` is the door
2. Startup creates DBs and observer threads
3. Most business persistence is in `src/*_store.py`
4. Automation starts from `/api/start-bid`
5. Reports/notifications mostly come from observers

Next: [05_Automation_Architecture.md](05_Automation_Architecture.md)
