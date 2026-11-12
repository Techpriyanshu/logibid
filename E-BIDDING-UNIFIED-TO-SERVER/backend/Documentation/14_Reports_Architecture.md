# 14 — Reports Architecture

> How Reports & Analytics are built from historical outcomes.

Related: [08_Database_Guide](08_Database_Guide.md) · [15_Notifications_Architecture](15_Notifications_Architecture.md)

---

## Why Reports exist

Live Bidding shows **now**.  
Reports show **history**:

- How many executions?
- How many wins/losses?
- Which depots perform better?
- What ranks appear on losses?

---

## Big idea: observers, not the engine

The bidding engine does **not** write report charts directly.

Instead:

```
Automation writes
  live_bids / successful_bids / jobs
        │
        ▼
outcome_store sync (every ~5 seconds)
        │
        ▼
bid_outcomes table (history database)
        │
        ▼
reports_store queries
        │
        ▼
/api/reports/* 
        │
        ▼
Reports.tsx charts + Excel
```

This keeps automation simple and reporting separate.

---

## What is an outcome?

One historical record for a finished leg/job event, with fields like:

- depot, destination, quantity
- rank
- outcome_status (`won`, `lost`, `stopped`, `failed`, …)
- timestamps / duration

Insert-only: observers don’t rewrite old history rows casually.

---

## Report APIs (what each is for)

| API | Shows |
|---|---|
| `/api/reports/summary` | Totals and rates |
| `/api/reports/outcomes` | Detailed rows |
| `/charts/timeline` | Activity over dates |
| `/charts/depot-performance` | Per-depot wins/bids |
| `/charts/rank-distribution` | Loss rank spread |
| `/charts/tonnage-distribution` | By tonnage |
| `/charts/losses-timeline` | Losses over time |

Truck KPI cards on Reports also use `/api/trucks`.

---

## Frontend flow

File: `pages/dashboard/Reports.tsx`

1. User sets date/depot/tonnage filters
2. Hooks call report APIs
3. Recharts draws graphs
4. Tables show unsuccessful rows mapped from outcomes
5. Export button builds Excel from the same real data

---

## KPI examples (conceptual)

- Total executions
- Wins / losses
- Success rate / loss rate
- Stopped / failed counts
- Active trucks / rotation counts (from truck master)

---

## Why live_bids and bid_outcomes both exist

| Table | Job |
|---|---|
| `live_bids` | Current operational scoreboard |
| `bid_outcomes` | Clean history for analytics |

If Reports read live_bids only, history would mix with in-progress noise.

---

## Lifecycle

```
Bid finishes
  → live/successful/jobs updated
  → within seconds, outcome sync inserts history
  → Reports page can show it after refresh/query
```

---

Next: [15_Notifications_Architecture.md](15_Notifications_Architecture.md)
