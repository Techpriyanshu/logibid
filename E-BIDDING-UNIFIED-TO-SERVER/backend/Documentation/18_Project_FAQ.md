# 18 — Project FAQ

> Common “why?” questions from new joiners.

Related: [05_Automation_Architecture](05_Automation_Architecture.md) · [08_Database_Guide](08_Database_Guide.md)

---

## Why multiple Chrome windows?

Because current mode is **multiprocess**: one depot ⇒ one worker ⇒ one Chrome.

This isolates failures and keeps separate SAP sessions.

---

## Why multiprocessing instead of one browser?

One shared browser fighting many depots is fragile.

Separate processes give:

- isolation
- clearer logs per depot
- ability to keep several sessions alive

---

## Why wait 210 seconds between depots?

Configured as `login_stagger_seconds: 210`.

Purpose: avoid launching many SAP logins at the exact same moment.

Implemented in `parallel_orchestrator._submit_workers_sequential_stagger`.

---

## Why separate databases?

Each module owns its data:

- live operations
- wins
- jobs
- trucks
- fleet
- outcomes
- notifications

This reduces accidental coupling and makes ownership clear.

---

## Why observers?

So the bidding engine can focus on bidding.

Observers copy finished facts into history/alert tables without changing automation timing logic.

---

## Why does the UI poll instead of using WebSockets?

This codebase uses simple HTTP polling with React Query.

It is easier to reason about and enough for 2-second live updates.

---

## Why MySQL?

- **Centralized Data Storage**: Avoids local file locks and permission issues on cloud VM / VPS environments.
- **Concurrent Access**: Supports high volume parallel read/write tasks from multiple browser engine instances simultaneously.
- **Unified Schema**: Integrates all operational and analytical tables (jobs, live bids, fleet management, notifications, outcomes) into a single database server.

*Note: SQLite local file fallback remains supported for simple standalone operations when configured via `DATABASE_URL=sqlite://...`.*

---

## Why both `live_bids` and `bid_outcomes`?

| DB | Role |
|---|---|
| live_bids | Current scoreboard during/after runs |
| bid_outcomes | Clean historical dataset for analytics |

---

## Why is `successful_bids` separate?

It is a dedicated Rank-1 trophy archive written directly by the engine when win is confirmed.

Reports use broader outcomes; Successful Bids page shows wins specifically.

---

## Why can Fleet see live bids but not pause?

Product/role design:

- Fleet observes and may request pause/close
- Vendor/Admin approves and/or presses pause/stop

Fleet Live page is intentionally read-only.

---

## Why do Home dashboard numbers sometimes look wrong?

Some Home cards still rely on older mock/reference paths.

Operational pages like Live Bidding / Successful Bids / Reports / Notifications are API-backed.

---

## Why is auth still simple?

React login currently uses hardcoded store users.

Backend REST APIs are not JWT-protected yet.

SAP login uses real credentials from env for automation.

---

## Why must I not edit `depot_bidding_engine.py` casually?

It contains timing-sensitive portal interaction.

Small changes can break real bidding money outcomes.

---

## Why does Live Bidding look empty in a new tab?

`activeBidJobId` is in **sessionStorage** (per tab/session).

Open the same tab/session where Start Bid was clicked, or set the job id again.

---

## Why are there old files like `parallel_execution_orchestrator.py`?

The project evolved. Some older helpers remain.

Current main multiprocess path uses `parallel_orchestrator.py` + `selenium_worker.py`.

---

## What should a fresher learn first?

1. Project overview + glossary
2. Complete system flow
3. Control Panel flow
4. Live statuses
5. Database guide
6. Then automation internals

---

## Final encouragement

You do not need to understand every Selenium selector on day one.

If you understand:

- Start Bid → Job → Workers → Live status → Wins → Reports/Notifications

…you already understand LogiBid’s backbone.

Welcome to the team.
