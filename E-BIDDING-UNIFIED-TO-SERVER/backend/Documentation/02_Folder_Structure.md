# 02 — Folder Structure

> This page answers: **Where do files live, and what is each folder for?**

Related: [01_Project_Overview](01_Project_Overview.md) · [06_File_by_File_Explanation](06_File_by_File_Explanation.md)

---

## Two codebases

LogiBid is split into two folders on disk:

```
Desktop
 ├── backend_parallel_code_COPT_EDITS_IMPROVED - Copy_FORTRIAL_SPI - Copy   ← Backend + Automation
└── frontend_latest                                                       ← React UI
```

Think of it like:

- **Backend** = kitchen + robots
- **Frontend** = restaurant menu screens

---

## Backend project map

```
backend_parallel_code_.../
├── backend_server.py      ← Main API server (start here mentally)
├── requirements.txt       ← Python libraries list
├── config/                ← Settings (YAML + credentials template)
├── src/                   ← All important Python modules
├── data/                  ← Uploaded documents (and fallback SQLite files if configured)
├── logs/                  ← Text logs and job snapshots
├── screenshots/           ← Pictures taken when something fails
├── docs/                  ← Older technical notes
├── Documentation/         ← THIS beginner guide (you are here)
├── chromedriver-linux64/  ← ChromeDriver binary for Linux
└── venv/                  ← Python virtual environment (local install)
```

### Why each folder exists

| Folder / File | Why it exists | Responsibility |
|---|---|---|
| `backend_server.py` | One entry point for the API | Receives frontend calls, starts jobs, returns JSON |
| `config/` | Keep secrets and settings outside code | SAP URLs, timers, multiprocess stagger, depot lists |
| `src/` | Keep logic organized | Automation, stores, helpers |
| `data/` | Persist information | Uploaded files (and local SQLite DBs in fallback mode) |
| `logs/` | Debug what happened | Execution logs, job JSON snapshots |
| `screenshots/` | Visual proof of browser state | Login/error screenshots |
| `Documentation/` | Teach new joiners | Learning guides |

---

## Backend `src/` (most important)

```
src/
├── selenium_service.py          ← Chooses legacy vs multiprocess mode
├── parallel_orchestrator.py     ← Creates workers for each depot
├── selenium_worker.py           ← One worker = one Chrome + one depot
├── depot_bidding_engine.py      ← The big bidding brain
├── live_status.py               ← Publishes status updates safely
├── live_bids_store.py           ← Live bid tables read/write
├── successful_bids_store.py     ← Successful bids table writes/reads
├── job_store.py                 ← In-memory job status + write-through
├── jobs_store.py                ← Bidding jobs database persistence
├── truck_master_store.py        ← Trucks registry + document links
├── fleet_admin_store.py         ← Daily fleet availability + requests
├── outcome_store.py             ← Bid outcomes historical table observer
├── reports_store.py             ← Report queries on database
├── notifications_store.py       ← User notifications table management
├── config_loader.py             ← Load YAML + env
├── driver_factory.py            ← Create Chrome WebDriver
├── login_service.py             ← Login to SAP
└── logging_service.py           ← Logging setup
```

### Mental grouping

```
API layer
  └── backend_server.py

Automation core (frozen / careful)
  ├── parallel_orchestrator.py
  ├── selenium_worker.py
  ├── depot_bidding_engine.py
  ├── live_status.py
  ├── live_bids_store.py
  └── successful_bids_store.py

Ops / history stores (safer to extend)
  ├── truck_master_store.py
  ├── fleet_admin_store.py
  ├── jobs_store.py
  ├── outcome_store.py
  ├── reports_store.py
  └── notifications_store.py

Helpers
  ├── config_loader.py
  ├── driver_factory.py
  ├── login_service.py
  └── logging_service.py
```

---

## Backend `config/`

| File | Purpose |
|---|---|
| `application.yaml` | Main settings: SAP URLs, timers, multiprocess mode, login stagger |
| `depots.yaml` | Depot names and destinations |
| `credentials.env` | SAP username/password (local secret — never commit) |
| `*.example` | Templates so new people know what to fill |

---

## Backend Database Layer & `data/` Directory

By default, LogiBid uses a central **MySQL** database server (configured via `DATABASE_URL`). When using MySQL, all records live as tables in the database schema. In **SQLite fallback mode**, these are persisted to a local file system database.

| Table / Directory | Purpose |
|---|---|
| `live_bids` | Current bid legs and status |
| `successful_bids` | Rank-1 wins history |
| `jobs` | Job metadata for polling |
| `truck_master` | Truck registry + document metadata |
| `fleet_admin` | Daily availability + fleet requests |
| `bid_outcomes` | Historical outcomes for reports |
| `notifications` | Notification feed |
| `data/truck_documents/` | Actual uploaded compliance documents |

---

## Frontend project map

```
frontend_latest/
├── package.json          ← npm libraries + scripts
├── vite.config.ts        ← Vite build tool config
├── index.html            ← HTML shell
├── src/
│   ├── main.tsx          ← React app starts here
│   ├── App.tsx           ← Routes (which URL opens which page)
│   ├── api/              ← Functions that call backend URLs
│   ├── hooks/            ← React Query hooks (fetch + poll)
│   ├── pages/            ← Full screens
│   ├── components/       ← Reusable UI pieces
│   ├── store/            ← Zustand client state (login/roles)
│   ├── constants/        ← Depot master list etc.
│   └── utils/            ← Mappers / helpers
└── dist/                 ← Built production files (generated)
```

### Frontend folders explained

| Folder | Why it exists |
|---|---|
| `src/api/` | Keep HTTP calls in one place (`fetch('/api/...')`) |
| `src/hooks/` | Reuse data loading logic (`useLiveBids`, `useReports`) |
| `src/pages/` | One page ≈ one menu item |
| `src/components/` | Buttons, tables, layout, filters |
| `src/store/` | Login/session/mock reference data (some still mock) |
| `src/constants/` | Shared lists like depots |

### Main pages

| Page file | Screen |
|---|---|
| `pages/dashboard/ControlPanel.tsx` | Start bidding |
| `pages/dashboard/LiveBiddingStatus.tsx` | Fleet live view |
| `pages/dashboard/VendorLiveBidding.tsx` | Vendor live + approvals |
| `pages/dashboard/SuccessfulBids.tsx` | Wins |
| `pages/dashboard/Reports.tsx` | Analytics |
| `pages/dashboard/Notifications.tsx` | Alerts |
| `pages/dashboard/TruckMaster.tsx` | Trucks + documents |
| `pages/admin/AdminDashboard.tsx` | Fleet daily availability |
| `pages/admin/AdminLiveBidding.tsx` | Admin live + requests |

---

## How frontend and backend connect

```
Browser (localhost:8080)
   │
   │  fetch("http://127.0.0.1:8000/api/...")
   ▼
FastAPI (backend_server.py on port 8000)
```

CORS is configured so the frontend origin is allowed to call the backend.

---

## What not to confuse

| Looks similar | Difference |
|---|---|
| `job_store.py` vs `jobs_store.py` | `job_store` = memory + write-through; `jobs_store` = Database persistence logic |
| `live_bids` vs `bid_outcomes` | Live = current scoreboard table; Outcomes = history table for reports |
| `docs/` vs `Documentation/` | `docs/` = older notes; `Documentation/` = this fresher guide |

---

Next: [03_Complete_System_Flow.md](03_Complete_System_Flow.md)
