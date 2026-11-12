# 13 — Live Bidding Flow

> How live statuses change from monitoring to won/completed.

Related: [05_Automation_Architecture](05_Automation_Architecture.md) · [12_Control_Panel_Flow](12_Control_Panel_Flow.md)

---

## What “Live Bidding” means

While automation is running, each desired bid line (a **leg**) has a status.

The Live Bidding screens show those legs and refresh about every **2 seconds**.

---

## Main statuses (and what they mean)

| Status | Simple meaning |
|---|---|
| `monitoring` | Watching depot page for matching bids |
| `bid_appeared` | Matching opportunity detected |
| `planning` | Calculating which rows/amounts to use |
| `ready` | Prepared, waiting for timer moment |
| `executing` | Typing/saving bid amounts now |
| `waiting_rank` | Bid submitted; waiting to read rank |
| `won` | Rank 1 achieved |
| `completed` | Finished without Rank 1 (or finished with other rank) |
| `paused` | User/fleet paused this leg |
| `stopped` | User/fleet stopped this leg |
| `failed` | (Often at job/depot result level) something went wrong |

Exact labels in UI are prettified (for example “Waiting Rank”).

---

## Happy-path state machine

```
monitoring
   │
   ▼
bid_appeared
   │
   ▼
planning
   │
   ▼
ready
   │
   ▼
executing
   │
   ▼
waiting_rank
   │
   ├──────────────► won          (Rank 1)
   │
   └──────────────► completed    (not Rank 1)
```

---

## Pause / resume / stop transitions

```
active leg (monitoring/planning/...)
   │
   ├─ pause  ──► paused   (skipped in planning/execution)
   │               │
   │               └─ resume ──► back to active flow
   │
   └─ stop   ──► stopped  (terminal-ish for that leg)
```

Where control is stored: `live_bids.user_control`

Who can change it:

- Vendor/Admin via pause/resume/stop buttons
- Fleet request **Approved** (PAUSE → paused, CLOSE → stopped)

Fleet Live page is read-only (no buttons).

---

## Who publishes statuses?

```
DepotBiddingEngine
   └── live_status.publish_*
         └── live_bids_store.update_live_bid
               └── live_bids table
                     └── GET /api/live-bids
                           └── Live Bidding UI
```

---

## How UI updates

1. Page calls `useLiveBids(jobId)`
2. React Query refetches every 2 seconds
3. Table re-renders badges/ranks
4. Sidebar can show a “live” indicator if non-terminal legs exist

`jobId` usually comes from sessionStorage key `activeBidJobId`.

---

## Rank display

- During `waiting_rank`, rank may appear as it becomes known
- On `won`, rank is 1 and winning time may show
- On `completed`, rank may be 2/3/etc.

Rank 1 also writes a row into `successful_bids` table.

---

## Failed / stopped / completed differences

| Word | Typical meaning |
|---|---|
| completed | Leg finished; not a Rank-1 win |
| won | Leg finished as Rank 1 |
| stopped | Intentionally halted by control |
| failed | Depot/job error path (login failure, exception, etc.) |

---

## Mental picture

> Live Bidding is a **scoreboard** fed by Chrome workers.  
> Automation plays the match.  
> The UI only watches and (for vendor) can pause/stop.

Next: [14_Reports_Architecture.md](14_Reports_Architecture.md)
