# 15 — Notifications Architecture

> How alerts appear in the Notifications page and Sidebar.

Related: [14_Reports_Architecture](14_Reports_Architecture.md) · [08_Database_Guide](08_Database_Guide.md)

---

## Why notifications exist

Users cannot stare at logs all day.

Notifications answer:

- Did bidding start?
- Did we win Rank 1?
- Did a job fail?
- Did fleet request pause/close?

---

## Two ways notifications are created

### 1) Immediate emitters

Called from backend when an event happens:

| Event | Emitter idea |
|---|---|
| Start Bid accepted | `automation_started` |
| Fleet request created | `fleet_request_created` |
| Fleet request approved/rejected | `fleet_request_approved` / `rejected` |

### 2) Background observers

Every ~5 seconds, sync looks at:

- `bid_outcomes.db`
- `jobs.db`

and inserts notifications for new finished events (win/loss/job completed/failed, etc.).

```
Event happens
   │
   ├─ emitter ──────────────┐
   │                        ▼
   └─ later observer sync ─► notifications.db
                              │
                              ▼
                         GET /api/notifications
                              │
                              ▼
                    Notifications page + Sidebar badge
```

---

## Database

File: `notifications.db`  
Table: `notifications`

Typical fields conceptually:

- title, message
- event_type
- is_read / read_at
- optional depot/destination/quantity/rank/job_id
- created_at

---

## Frontend behavior

File: `Notifications.tsx`

- Loads with `useNotifications({ limit: 100 })`
- Shows cards with icons by event type
- Click can mark one as read
- Button marks all read
- Trash deletes one

Sidebar:

- Reads unread_count
- Shows badge number

---

## Polling

Notifications are refreshed by React Query (and Sidebar queries).  
They are not WebSockets in this codebase.

---

## Important for freshers

- Notifications page uses **API data**, not old seeded welcome mock rows
- Duplicate protection exists in store logic (same event should not spam endlessly)
- Notification creation failures should not break Start Bid (emitters are best-effort)

---

Next: [16_Project_Glossary.md](16_Project_Glossary.md)
