# 09 — API Guide (Plain English)

> This is **not** a Swagger dump.  
> It explains what each API is for, who uses it, and which DB it touches.

Base URL used by frontend: `http://127.0.0.1:8000`

Related: [10_Frontend_Architecture](10_Frontend_Architecture.md) · [04_Backend_Architecture](04_Backend_Architecture.md)

---

## How APIs fit in

```
React page
  → src/api/*.ts  (fetch helper)
  → FastAPI endpoint in backend_server.py
  → store function
  → SQLite file
  → JSON response
  → UI updates
```

---

## Bidding & jobs

### `POST /api/start-bid`

| | |
|---|---|
| Purpose | Start automation for selected depots |
| Request | `{ depots: [...], desired_bids: [...] }` |
| Response | `job_id`, `execution_mode`, status |
| DB | jobs.db, live_bids.db, notifications emit |
| Backend | `start_bid` → `trigger_bid` |
| Frontend | Control Panel |

### `GET /api/bid-job/{job_id}`

| | |
|---|---|
| Purpose | Poll whether job finished |
| DB | jobs.db |
| Frontend | Control Panel polling loop |

---

## Live bids

### `GET /api/live-bids`

| | |
|---|---|
| Purpose | List live legs (optional job_id filter) |
| DB | live_bids.db |
| Frontend | Live Bidding pages, Sidebar |

### `POST /api/live-bids/{leg_id}/pause|resume|stop`

| | |
|---|---|
| Purpose | Change user_control for one leg |
| DB write | live_bids.db |
| Frontend | Vendor Live Bidding / Admin Live (not fleet read-only page) |

---

## Successful bids

### `GET /api/successful-bids`

| | |
|---|---|
| Purpose | List Rank-1 wins |
| Query filters | month / from / to / depot |
| DB | successful_bids.db |
| Frontend | Successful Bids |

---

## Trucks

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/trucks` | List trucks |
| GET | `/api/trucks/{id}` | One truck |
| POST | `/api/trucks` | Create |
| PUT | `/api/trucks/{id}` | Update |
| DELETE | `/api/trucks/{id}` | Delete |
| POST | `/api/trucks/{id}/documents` | Upload document |
| GET | `/api/trucks/{id}/documents/{doc_id}/file` | Download file |

DB: `truck_master.db` + `truck_documents` files  
Frontend: Truck Master

---

## Fleet Admin

| Area | Paths | DB | Frontend |
|---|---|---|---|
| Daily availability | `/api/fleet-daily` CRUD | fleet_admin.db | Admin Dashboard |
| Control requests | `/api/fleet-requests` CRUD | fleet_admin.db (+ maybe live_bids on approve) | Admin/Vendor Live |

---

## Notifications

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/notifications` | List + unread_count |
| PATCH | `/api/notifications/read-all` | Mark all read |
| PATCH | `/api/notifications/{id}/read` | Mark one read |
| DELETE | `/api/notifications/{id}` | Delete |

DB: `notifications.db`  
Frontend: Notifications page, Sidebar badge

---

## Reports

| Path | Purpose |
|---|---|
| `/api/reports/summary` | KPI totals |
| `/api/reports/outcomes` | Outcome rows |
| `/api/reports/charts/timeline` | Bids/wins over time |
| `/api/reports/charts/depot-performance` | Per depot |
| `/api/reports/charts/rank-distribution` | Loss ranks |
| `/api/reports/charts/tonnage-distribution` | By tonnage |
| `/api/reports/charts/losses-timeline` | Losses over time |

DB: `bid_outcomes.db`  
Frontend: Reports page

---

## Bid outcomes APIs

`/api/bid-outcomes`, `/summary`, `/{job_id}` — backed by `bid_outcomes.db`  
(Frontend reports mainly use `/api/reports/*`.)

---

## Legacy HTML endpoints

`GET /login`, `POST /do-login`, `GET /dashboard` — old HTML login, not main React auth.

---

## Frontend API files map

| Frontend file | Backend area |
|---|---|
| `liveBids.ts` | live-bids + session job id |
| `successfulBids.ts` | successful-bids |
| `trucks.ts` | trucks |
| `fleetAdmin.ts` | fleet-daily + fleet-requests |
| `notifications.ts` | notifications |
| `reports.ts` | reports |
| `bidOutcomes.ts` | bid-outcomes |

Next: [10_Frontend_Architecture.md](10_Frontend_Architecture.md)
