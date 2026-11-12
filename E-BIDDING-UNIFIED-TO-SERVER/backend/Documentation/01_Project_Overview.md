# 01 — Project Overview

> Read this first. It answers: **What is this project, and why does it exist?**

Related docs: [02_Folder_Structure](02_Folder_Structure.md) · [03_Complete_System_Flow](03_Complete_System_Flow.md) · [16_Project_Glossary](16_Project_Glossary.md)

---

## What is LogiBid?

**LogiBid** is software that helps a cement logistics / transport business join **e-Bidding** on a company portal (SAP Fiori / Eye2Serve).

In simple words:

> People used to sit in front of a browser, wait for bids to appear, type amounts quickly, and check ranks.  
> LogiBid opens Chrome automatically, watches for bids, fills amounts, and saves results — then shows everything in a web dashboard.

---

## What problem does it solve?

Without LogiBid, a vendor might need to:

1. Open the SAP bidding website
2. Login
3. Choose a **depot** (like Ayodhya, Lucknow, Sitapur)
4. Wait for matching loads (tonnage / destination)
5. Enter a bid amount very quickly when the timer starts
6. Check if they got Rank 1
7. Repeat this for **many depots at once**

That is stressful, slow, and easy to miss.

**LogiBid solves this by:**

- Starting many depots together (with careful timing)
- Watching each depot automatically
- Entering bids when the moment is right
- Showing live status on a screen
- Saving wins and history for reports

---

## What is e-Bidding?

**e-Bidding** means:

- A cement plant publishes transport opportunities (loads)
- Vendors compete by offering a price (bid amount)
- Usually **Rank 1** means “best / winning” for that row
- Timing matters — bids open for a short period (“Start In” / “Expires In”)

Think of it like an online auction for truck loads.

---

## Who uses this software?

| Role | What they do |
|---|---|
| **Vendor / Operator** | Starts bidding from Control Panel, watches live status, can pause/stop, approves fleet requests |
| **Fleet user** | Sees live status (mostly view), may send pause/close requests |
| **Fleet Admin** | Updates daily truck availability, manages fleet requests |
| **Management** | Looks at Successful Bids, Reports, Notifications |

---

## Big picture architecture

There are **4 main parts**:

```
┌────────────────────┐
│  Frontend (React)  │  ← screens people click
│  LogiBid UI        │
└─────────┬──────────┘
          │  HTTP APIs (REST)
          ▼
┌────────────────────┐
│  Backend (FastAPI) │  ← receives requests, saves data
│  backend_server.py │
└─────────┬──────────┘
          │  starts jobs
          ▼
┌────────────────────┐
│ Automation Engine  │  ← opens Chrome, does bidding
│ Selenium workers   │
└─────────┬──────────┘
          │  reads/writes
          ▼
┌────────────────────┐
│Relational Database │  ← stores history & live state (MySQL/SQLAlchemy)
│MySQL / SQLite      │
└────────────────────┘
```

### 1) Frontend

- Built with **React + TypeScript**
- Folder: `C:\Users\DELL\Desktop\frontend_latest`
- Pages like Control Panel, Live Bidding, Successful Bids, Reports

### 2) Backend

- Built with **Python FastAPI**
- Main file: `backend_server.py`
- Talks to the UI through URLs like `/api/start-bid`

### 3) Automation Engine

- Uses **Selenium** to control Google Chrome
- Logs into SAP, opens e-Bidding, monitors depots
- One Chrome per depot (in multiprocess mode)

### 4) Relational Database (MySQL / SQLite Fallback)

- Default database engine is **MySQL** configured via `DATABASE_URL` in the environment
- Fallback database is **SQLite** (a local file database) if explicitly configured
- Standard database schema contains tables for `live_bids`, `successful_bids`, `jobs`, etc.

---

## Overall request flow (very short version)

```
User clicks "Start Bid"
        │
        ▼
Frontend sends POST /api/start-bid
        │
        ▼
Backend creates a Job + Live Bid rows
        │
        ▼
Orchestrator starts one worker per depot
        │
        ▼
Each worker opens Chrome → Login → Monitor depot
        │
        ▼
When bid appears → Plan → Execute → Check Rank
        │
        ▼
If Rank 1 → save Successful Bid
        │
        ▼
Observers copy results into Outcomes + Notifications
        │
        ▼
Frontend polls APIs and refreshes screens
```

---

## Why the system feels “alive”

The UI does not wait forever for one huge response.

Instead:

1. Backend starts work and returns a **job id** quickly
2. Automation keeps running in the background
3. Frontend **polls** (asks again and again every few seconds):
   - “Any live bids?”
   - “Did the job finish?”
   - “Any new notifications?”

That is why Live Bidding updates without refreshing the whole page by hand.

---

## What you should remember from this page

1. LogiBid = **UI + API + Browser Automation + Databases**
2. The hard part is automation (Chrome + SAP timing)
3. The UI is the control room
4. Databases store live state and history
5. One Start Bid can control **many depots**

---

Next: [02_Folder_Structure.md](02_Folder_Structure.md)
