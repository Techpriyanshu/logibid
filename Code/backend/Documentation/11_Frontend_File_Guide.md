# 11 — Frontend File Guide

> Major frontend files and what each one is responsible for.

Path: `C:\Users\DELL\Desktop\frontend_latest\src`

Related: [10_Frontend_Architecture](10_Frontend_Architecture.md)

---

## Entry + routing

| File | Responsibility |
|---|---|
| `main.tsx` | Boots React into the page |
| `App.tsx` | Declares all routes and providers |
| `index.css` | Global styles / Tailwind |

---

## Pages (`src/pages`)

### Dashboard

| File | Responsibility |
|---|---|
| `dashboard/Home.tsx` | Overview cards (partially still mock for bids/rank) |
| `dashboard/ControlPanel.tsx` | Start Bid UI + job polling |
| `dashboard/LiveBiddingStatus.tsx` | Fleet live table (API, read-only) |
| `dashboard/VendorLiveBidding.tsx` | Vendor live + pause/stop + approve requests |
| `dashboard/SuccessfulBids.tsx` | Rank-1 history from API |
| `dashboard/TruckMaster.tsx` | Truck list + document upload/view |
| `dashboard/Reports.tsx` | Charts/KPIs/Excel from reports APIs |
| `dashboard/Notifications.tsx` | Notification cards from API |

### Admin

| File | Responsibility |
|---|---|
| `admin/AdminLogin.tsx` | Admin login screen |
| `admin/AdminDashboard.tsx` | Daily fleet availability CRUD |
| `admin/AdminLiveBidding.tsx` | Admin live view + create/resolve requests |

### Auth / misc

| File | Responsibility |
|---|---|
| `Login.tsx` | Vendor/operator login |
| `NotFound.tsx` | Unknown route page |

---

## API layer (`src/api`)

| File | Talks to |
|---|---|
| `liveBids.ts` | `/api/live-bids`, pause/resume/stop, session job id helpers |
| `successfulBids.ts` | `/api/successful-bids` |
| `trucks.ts` | `/api/trucks` + documents |
| `fleetAdmin.ts` | `/api/fleet-daily`, `/api/fleet-requests` |
| `notifications.ts` | `/api/notifications` |
| `reports.ts` | `/api/reports/...` |
| `bidOutcomes.ts` | `/api/bid-outcomes...` |

These files should stay thin: build URL, `fetch`, parse JSON, throw on errors.

---

## Hooks (`src/hooks`)

| File | Responsibility |
|---|---|
| `useLiveBids.ts` | Poll live bids every 2s + action helpers |
| `useSuccessfulBids.ts` | Load wins |
| `useTrucks.ts` | Load trucks + mutations |
| `useFleetAdmin.ts` | Fleet daily/requests queries + mutations |
| `useNotifications.ts` | Notifications query + mark/delete |
| `useReports.ts` | Bundle report queries |
| `useBidOutcomes.ts` | Outcomes hooks (available even if page uses reports) |
| `useBidFilters.ts` | Depot/destination filter UI logic |
| `useFleetAvailability.ts` | Compute truck availability counts for Home |
| `useBidDiscovery.ts` | Older mock bid-discovery monitor (Home-related) |

---

## Stores (`src/store`)

| File | Responsibility |
|---|---|
| `dataStore.ts` | Zustand: login, roles, plants/zones/tonnage reference, some Home mock paths |
| `adminStore.ts` | Zustand: admin login session |

---

## Components (`src/components`)

| Area | Examples | Responsibility |
|---|---|---|
| Layout | `Sidebar.tsx`, `Header.tsx`, `DashboardLayout.tsx` | Shell, nav, badges |
| Bidding | `BidFilterBar` | Filter controls |
| Fleet | `CurrentTruckAvailability`, `ActionRequestModal` | Fleet dialogs |
| UI | `components/ui/*` | shadcn primitives (button, table, dialog…) |

---

## Constants + utils

| File/Folder | Responsibility |
|---|---|
| `constants/depots.ts` | Master depot list for labels/filters |
| `utils/fleetAdminMappers.ts` | Map API fleet records ↔ UI shapes |
| `utils/reportsMappers.ts` | Build report queries / row mappers |
| `lib/utils.ts` | Small helpers (className merge etc.) |

---

## How a typical feature is wired

Example: Successful Bids

```
SuccessfulBids.tsx
   └── useSuccessfulBids()
         └── fetchSuccessfulBids()
               └── GET /api/successful-bids
                     └── successful_bids table
```

Example: Vendor pause

```
VendorLiveBidding.tsx
   └── useLiveBidActions().pause(bid)
         └── POST /api/live-bids/{id}/pause
               └── live_bids table user_control=paused
```

---

Next: [12_Control_Panel_Flow.md](12_Control_Panel_Flow.md)
