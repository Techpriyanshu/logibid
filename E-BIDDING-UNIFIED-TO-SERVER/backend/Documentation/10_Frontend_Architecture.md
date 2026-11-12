# 10 — Frontend Architecture

> How the React LogiBid UI is organized and how it stays updated.

Frontend path: `C:\Users\DELL\Desktop\frontend_latest`

Related: [11_Frontend_File_Guide](11_Frontend_File_Guide.md) · [09_API_Guide](09_API_Guide.md)

---

## What the frontend is

A **Single Page Application (SPA)**:

- One HTML page
- React changes screens without full browser reloads
- Built with **Vite + React + TypeScript + Tailwind + shadcn/ui**

---

## Layers (simple)

```
Pages (screens)
   │
   ▼
Hooks (useLiveBids, useReports, ...)
   │
   ▼
API helpers (src/api/*.ts)
   │
   ▼
Backend FastAPI
```

Plus:

- **Zustand stores** for login/session/some reference data
- **Components** for tables, layout, filters

---

## Routing (`App.tsx`)

Important routes:

| URL | Page |
|---|---|
| `/login` | Vendor login |
| `/dashboard/home` | Home |
| `/dashboard/control-panel` | Control Panel |
| `/dashboard/live-status` | Fleet Live Bidding |
| `/dashboard/vendor-live-status` | Vendor Live Bidding |
| `/dashboard/successful-bids` | Successful Bids |
| `/dashboard/truck-master` | Truck Master |
| `/dashboard/reports` | Reports |
| `/dashboard/notifications` | Notifications |
| `/admin/login` | Admin login |
| `/admin/dashboard` | Fleet daily admin |
| `/admin/live-bidding` | Admin live + requests |

`QueryClientProvider` wraps the app so React Query works everywhere.

---

## React Query (why UI feels live)

React Query:

1. Calls an API
2. Caches the result
3. Can **refetch on an interval**

Example: Live bids poll every **2 seconds**.

```
useLiveBids(jobId)
  → fetchLiveBids(jobId)
  → GET /api/live-bids?job_id=...
  → table re-renders with new statuses
```

---

## State management split

| Tool | Used for |
|---|---|
| **React Query** | Server data (live bids, trucks, reports, notifications) |
| **Zustand (`dataStore` / `adminStore`)** | Login session, roles, some reference lists |

Important honesty for freshers:

- Many operational screens are now **API-backed**
- Some areas still use mock/reference data (Home cards, auth users, Control Panel zone/plant lists)

---

## How each major screen gets data

| Screen | Main data source |
|---|---|
| Control Panel | POST start-bid + poll bid-job; depot lists from store/constants |
| Live Bidding Fleet | `useLiveBids` only (read-only UI) |
| Live Bidding Vendor | `useLiveBids` + `useFleetRequests` |
| Successful Bids | `useSuccessfulBids` |
| Reports | `useReports` + trucks hook |
| Notifications | `useNotifications` |
| Truck Master | `useTrucks` + document upload |
| Admin Dashboard | `useFleetDaily` |
| Sidebar badges | live-bids + pending requests + unread notifications |

---

## Rendering + polling flow

```
Page mounts
   │
   ▼
Hook starts query
   │
   ▼
Loading spinner / empty state
   │
   ▼
Data arrives → table/charts render
   │
   ▼
Interval refetch (for live pages)
   │
   ▼
UI updates automatically
```

---

## Control Panel special behavior

1. Builds payload from selected depot cards
2. Calls `/api/start-bid`
3. Saves `job_id` into `sessionStorage` (`activeBidJobId`)
4. Polls `/api/bid-job/{id}` until completed/failed

Other pages read that same `job_id` to show the active job’s live legs.

---

## Role-based menu

Sidebar checks `currentUser.role`:

- Fleet users see fleet live page
- Vendor/admin/operator see Control Panel + vendor live page

This is **frontend navigation control**, not hard backend API auth.

---

## Excel export

Reports page can export analytics to `.xlsx` using the `xlsx` library, from real report/outcome data.

---

## Mental model for freshers

> Pages should preferably show **server truth**.  
> Hooks + API files are the bridge.  
> Stores are for client session / leftover reference data.

Next: [11_Frontend_File_Guide.md](11_Frontend_File_Guide.md)
