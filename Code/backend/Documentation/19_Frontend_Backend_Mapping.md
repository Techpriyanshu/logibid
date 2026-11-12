# Document Mirror: Frontend-Backend API & Logging Mapping

> [!NOTE]
> This document is part of the LogiBid Documentation suite. It mirrors the root-level mapping reference.
> The primary source of truth is located at [FRONTEND_BACKEND_MAPPING.md](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/FRONTEND_BACKEND_MAPPING.md).

---

# Frontend-Backend API & Logging Mapping

This document serves as the **source of truth** mapping all React frontend pages and user actions to their respective FastAPI backend API endpoints, database operations, prerequisites, and generated log structures.

---

## Centralized Logging Context

The backend uses a structured logging pattern via [logging_service.py](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/backend/src/logging_service.py).
All generic backend API calls write to the unified log file:
- `logs/All_logs/All_logs.log` (All backend API activities are logged with the marker prefix `[API]`).

Bidding execution actions (Selenium browser orchestration logs) write to:
- `logs/execution_phase/app_pid<PID>_<TIMESTAMP>.log` (or depot-specific file names).

---

## 1. Authentication

### User Login
* **File Location**: [Login.tsx](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/frontend/src/pages/Login.tsx)
* **Prerequisites**: Access to network URL.
* **User Action**: Enters Username/Password and submits.
* **API Endpoint**: *Local validation* (Uses local store verification).
* **Action taken in code**: Verifies inputs against mock records inside `users` state in [dataStore.ts](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/frontend/src/store/dataStore.ts).
* **Post-Action Status**: Sets `currentUser` state, flags `isAuthenticated = true`, and redirects vendor users to `/dashboard/home` or fleet users to `/dashboard/live-status`.
* **Logs Generated**: None (handled purely on client).

### Admin Login
* **File Location**: [AdminLogin.tsx](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/frontend/src/pages/admin/AdminLogin.tsx)
* **Prerequisites**: Credentials (`fleetadmin` / `fleet@123` or other admin accounts).
* **User Action**: Clicks "Sign In".
* **API Endpoint**: *Local validation* (Uses local admin store verification).
* **Action taken in code**: Validates via `adminLogin()` in [adminStore.ts](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/frontend/src/store/adminStore.ts).
* **Post-Action Status**: Flags `isAdminAuthenticated = true`, sets `adminUser`, and redirects to `/admin/dashboard`.
* **Logs Generated**: None (handled purely on client).

---

## 2. Dashboard Home

### Overview Page Load
* **File Location**: [Home.tsx](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/frontend/src/pages/dashboard/Home.tsx)
* **Prerequisites**: Valid authenticated session.
* **Action Taken**: Renders Plant, Truck, and Competition summaries.
* **API Endpoint**:
  1. `GET /api/fleet-daily` (loads active, available, in-trip, and non-active fleet stats).
  2. `GET /api/live-bids` (fetches active bidding competition legs).
* **Action taken in code**: Calls API hooks `useFleetAvailability()` and `useLiveBids()` to fetch operational counts.
* **Post-Action Status**: Populates Overview Cards ("Active Plants", "Trucks", "Active Vehicle Bids", "Rank 1 Vehicles").
* **Logs Generated**:
  ```text
  [API] GET /api/fleet-daily
  [API] GET /api/live-bids
  ```

### Manual Refresh Active Bids
* **Prerequisites**: Bidding started (Active context).
* **User Action**: Clicks "Refresh" inside "Active Vehicle Bids" card.
* **API Endpoint**: Evaluated via `refreshBidOpportunities()` in the data store client (network fetch simulation).
* **Post-Action Status**: Displays toast indicating how many matching opportunities exist in the yard.
* **Logs Generated**: None.

---

## 3. Control Panel

### Configuration Load
* **File Location**: [ControlPanel.tsx](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/frontend/src/pages/dashboard/ControlPanel.tsx)
* **Prerequisites**: Authenticated as Vendor, Operator, or Admin.
* **Action Taken**: Renders dropdown selections.
* **API Endpoints**:
  1. `GET /api/zones` - Fetches geographical regions.
  2. `GET /api/plants?zone_id={zoneId}` - Fetches factories tie-up in zone.
  3. `GET /api/plants/{plantId}/depots` - Fetches SAP depot points under plant.
  4. `GET /api/tonnage-options` - Fetches valid vehicle capacities (e.g. 18T, 25T, 32T).
* **Action taken in code**: Invokes master data hooks `useZones`, `usePlants`, `useDepotsForPlant`, and `useTonnageOptions` defined in [masterData.ts](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/frontend/src/api/masterData.ts).
* **Post-Action Status**: Populates setup filters.
* **Logs Generated**:
  ```text
  [API] Fetching: /api/zones
  [API] Fetching: /api/plants
  [API] Fetching: /api/plants/{plantId}/depots
  [API] Fetching: /api/tonnage-options
  ```

### Start Bidding Request
* **Prerequisites**: Zone/Plant selected; configuration cards filled with tonnage and destination.
* **User Action**: Clicks "Start Bidding" rocket button.
* **API Endpoint**: `POST /api/start-bid`
* **Payload Structure**:
  ```json
  {
    "depots": ["LUCKNOW", "AYODHYA"],
    "desired_bids": [
      {
        "quantity": 32.0,
        "destination": "Kanpur",
        "depot": "LUCKNOW"
      }
    ],
    "record_on_bid_start": false,
    "headless": true
  }
  ```
* **Response Structure**:
  ```json
  {
    "status": "queued",
    "job_id": "job_e7c8b211a7a...",
    "depots": ["LUCKNOW"],
    "execution_mode": "legacy_async",
    "message": "Legacy bidding started in background; poll GET /api/bid-job/{job_id}",
    "poll_path": "/api/bid-job/job_e7c8b211a7a...",
    "sync": false
  }
  ```
* **Action taken in code**:
  1. Validates selected payload configuration.
  2. Submits POST request to backend server.
  3. Receives unique `job_id` and saves it to browser `sessionStorage` (`activeBidJobId`).
  4. Initiates a background polling thread for `GET /api/bid-job/{job_id}` until status becomes terminal.
  5. Triggers selenium worker script to log into SAP portal and search matching bid slots.
* **Post-Action Status**: Spawns live bid entries in database, initializes browser worker windows.
* **Logs Generated**:
  ```text
  INFO - [backend_server.py:316] - [API] Received desired_bids=[{'quantity': 32.0, 'destination': 'Kanpur', 'depot': 'LUCKNOW'}]
  INFO - [backend_server.py:317] - [API] API depot normalization: depot_raw='LUCKNOW' -> depot='LUCKNOW'
  INFO - [backend_server.py:324] - [API] API: start-bid depot='LUCKNOW' depots=['LUCKNOW'] desired_bids=[...] sync=False legacy_blocking=False
  INFO - [backend_server.py:384] - [API] Creating legacy_async job for depots=['LUCKNOW'] desired_bids=[...]
  INFO - [backend_server.py:392] - [API] Job created job_id=job_e7c8b211a7a...
  ```

---

## 4. Live Bidding Status & Controls

### Live Status Refresh
* **File Location**: [LiveBiddingStatus.tsx](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/frontend/src/pages/dashboard/LiveBiddingStatus.tsx), [VendorLiveBidding.tsx](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/frontend/src/pages/dashboard/VendorLiveBidding.tsx), [AdminLiveBidding.tsx](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/frontend/src/pages/admin/AdminLiveBidding.tsx)
* **Prerequisites**: Active `job_id` in browser session or active entries in database.
* **Action Taken**: Automatically polls every 2 seconds.
* **API Endpoint**: `GET /api/live-bids?job_id={jobId}`
* **Post-Action Status**: Renders live rows showing depot, destination, tonnage, organization, rank, status, and control indicators.
* **Logs Generated**:
  ```text
  [API] GET /api/live-bids called
  ```
  *(Also posts telemetry data to `/api/debug-log` on rendering).*

### Pause Leg
* **Prerequisites**: Bidding status is active, control is running/active.
* **User Action**: Clicks "Pause" button.
* **API Endpoint**: `POST /api/live-bids/{leg_id}/pause`
* **Post-Action Status**: Sets `user_control = 'paused'` in `live_bids` DB table. The automation worker halts bidding adjustments on SAP for this leg but maintains browser window.
* **Logs Generated**:
  ```text
  INFO - [backend_server.py:1123] - [API] PAUSE job_id=job_123 depot=LUCKNOW qty=32.0 dest=Kanpur leg_id=leg_456
  ```

### Resume Leg
* **Prerequisites**: Bidding status is paused.
* **User Action**: Clicks "Resume" button.
* **API Endpoint**: `POST /api/live-bids/{leg_id}/resume`
* **Post-Action Status**: Resets `user_control = 'active'` in the DB. Browser worker resumes bidding.
* **Logs Generated**:
  ```text
  INFO - [backend_server.py:1150] - [API] RESUME job_id=job_123 depot=LUCKNOW qty=32.0 dest=Kanpur leg_id=leg_456
  ```

### Stop Leg
* **Prerequisites**: Any non-stopped leg.
* **User Action**: Clicks "Stop" button.
* **API Endpoint**: `POST /api/live-bids/{leg_id}/stop`
* **Post-Action Status**: Sets `user_control = 'stopped'` and updates status to `stopped` in the DB. The worker closes the browser session for this leg.
* **Logs Generated**:
  ```text
  INFO - [backend_server.py:1177] - [API] STOP job_id=job_123 depot=LUCKNOW qty=32.0 dest=Kanpur leg_id=leg_456
  ```

### Restart Leg (Recovery)
* **Prerequisites**: Bidding status is `orphaned` (crashed worker) or `stopped`.
* **User Action**: Clicks "Restart" or "Restart Bid".
* **API Endpoint**: `POST /api/live-bids/{leg_id}/restart?show_browser=true|false`
* **Post-Action Status**: Sets `user_control = 'running'`, creates a new background async job, updates session storage to the new `job_id`, and boots selenium instance.
* **Logs Generated**:
  ```text
  INFO - [backend_server.py:1203] - [API] RESTART job_id=job_123 depot=LUCKNOW qty=32.0 dest=Kanpur leg_id=leg_456 show_browser=True
  INFO - [backend_server.py:1228] - [API] Restarting bid leg leg_456 with show_browser=True, headless=False
  ```

### Create Action Request (Fleet -> Vendor)
* **Prerequisites**: Authenticated as `fleetadmin` or Operator.
* **User Action**: Fleet admin clicks "Send Request" to Pause or Close a running leg.
* **API Endpoint**: `POST /api/fleet-requests`
* **Payload Structure**:
  ```json
  {
    "leg_id": "leg_456",
    "request_type": "PAUSE",
    "requested_by": "fleetadmin",
    "job_id": "job_123",
    "depot_name": "LUCKNOW",
    "destination": "Kanpur",
    "tonnage": 32.0,
    "plant_name": "Tanda Cement Plant",
    "remarks": "Over-capacity warning"
  }
  ```
* **Post-Action Status**: Adds pending request record to database. Generates a real-time notification alert showing on the Vendor UI.
* **Logs Generated**:
  ```text
  [API] POST /api/fleet-requests called
  [API] fleet_request_created notification emitted
  ```

### Resolve Action Request (Approve/Reject)
* **Prerequisites**: Pending action request exists in the widget box.
* **User Action**: Vendor clicks "Approve" or "Reject".
* **API Endpoint**: `PUT /api/fleet-requests/{request_id}`
* **Payload Structure**:
  ```json
  {
    "status": "Approved" | "Rejected",
    "resolved_by": "vendor"
  }
  ```
* **Post-Action Status**: Updates request row status. If approved, automatically routes to `/api/live-bids/{leg_id}/pause` or `/api/live-bids/{leg_id}/stop` endpoint based on request parameter. Triggers resolution toast on fleet dashboard.
* **Logs Generated**:
  ```text
  [API] PUT /api/fleet-requests/{request_id} called
  [API] fleet_request_resolved notification emitted
  ```

---

## 5. Truck Master

### List Master Fleet
* **File Location**: [TruckMaster.tsx](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/frontend/src/pages/dashboard/TruckMaster.tsx)
* **Prerequisites**: Authenticated.
* **Action Taken**: Page loading.
* **API Endpoint**: `GET /api/trucks`
* **Post-Action Status**: Loads permanent list of vehicles, mapping rotation history, driver contact details, and compliance documents.
* **Logs Generated**:
  ```text
  [API] GET /api/trucks called
  ```

### Upload Compliance File
* **Prerequisites**: PDF or Image chosen. Expiry date mandatory if document type is `'Insurance'`.
* **User Action**: Selects type, inputs date, chooses file, and clicks "Upload".
* **API Endpoint**: `POST /api/trucks/{truck_id}/documents` (multipart/form-data)
* **Post-Action Status**: File uploaded to backend storage folder, record inserted, updates safety warning badges (Valid / Expiring soon / Expired) dynamically.
* **Logs Generated**:
  ```text
  [API] POST /api/trucks/{truck_id}/documents called
  ```

---

## 6. Successful Bids History

### Fetch Wins Archive
* **File Location**: [SuccessfulBids.tsx](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/frontend/src/pages/dashboard/SuccessfulBids.tsx)
* **Prerequisites**: Authenticated.
* **Action Taken**: Loading table / applying filters.
* **API Endpoint**: `GET /api/successful-bids?depot={depot}&from={from_date}&to={to_date}`
* **Post-Action Status**: Renders database records for won trips (Rank 1 bids) matching filter queries.
* **Logs Generated**: None.

---

## 7. Notifications Hub

### Fetch Alerts
* **File Location**: [Notifications.tsx](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/frontend/src/pages/dashboard/Notifications.tsx)
* **Prerequisites**: Authenticated.
* **Action Taken**: Automatic synchronization in data store.
* **API Endpoint**: `GET /api/notifications`
* **Post-Action Status**: Populates notifications feed.
* **Logs Generated**: None.

---

## 8. Reports & Analytics

### Metrics & Charts Load
* **File Location**: [Reports.tsx](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/frontend/src/pages/dashboard/Reports.tsx)
* **Prerequisites**: Authenticated.
* **Action Taken**: Loads charts tab or applies date range filters.
* **API Endpoints**:
  1. `GET /api/reports/summary` (Calculates win ratios, total trips, and operational tonnage totals).
  2. `GET /api/reports/outcomes` (Fetches historical records list).
  3. `GET /api/reports/charts/timeline` (Daily trends).
  4. `GET /api/reports/charts/depot-performance` (Per-depot stats).
  5. `GET /api/reports/charts/rank-distribution` (Loss details).
  6. `GET /api/reports/charts/tonnage-distribution` (Tonnage limits).
  7. `GET /api/reports/charts/losses-timeline` (Unsuccessful count timeline).
* **Post-Action Status**: Feeds chart widgets to draw visual analytics.
* **Logs Generated**: None.

---

## 9. Fleet Admin Control Room

### Load Daily Availability Registry
* **File Location**: [AdminDashboard.tsx](file:///Users/kunjan/Documents/Sushil/EBidding/shubh-main/E-BIDDING-UNIFIED/frontend/src/pages/admin/AdminDashboard.tsx)
* **Prerequisites**: Authenticated as `fleetadmin` or `operator`.
* **Action Taken**: Loading board for a selected business date (default = Today).
* **API Endpoint**: `GET /api/fleet-daily?date={YYYY-MM-DD}`
* **Post-Action Status**: Loads registry table with options to modify assignments.
* **Logs Generated**: None.

### Add Truck Daily Availability
* **Prerequisites**: Business date = today, valid truck identity inputs.
* **User Action**: Enters registry form and clicks "Add Entry".
* **API Endpoint**: `POST /api/fleet-daily`
* **Payload Structure**:
  ```json
  {
    "business_date": "2026-08-27",
    "truck_number": "UP32-AB-9999",
    "driver_name": "Rajesh Kumar",
    "tonnage": "32T",
    "previous_depot": "LUCKNOW",
    "current_depot": "AYODHYA",
    "destination": "Rudoli",
    "status": "Available",
    "remarks": "Regular driver"
  }
  ```
* **Post-Action Status**: Adds availability row to DB, syncing to vendor dashboard immediately.
* **Logs Generated**: None.

### Update Daily Availability
* **User Action**: Edits Status or current Depot dropdown.
* **API Endpoint**: `PUT /api/fleet-daily/{entry_id}`
* **Payload Structure**:
  ```json
  {
    "status": "In Trip",
    "current_depot": "LUCKNOW"
  }
  ```
* **Post-Action Status**: Entry status updated in database.
* **Logs Generated**: None.

### Delete Daily Availability
* **User Action**: Clicks trash icon.
* **API Endpoint**: `DELETE /api/fleet-daily/{entry_id}`
* **Post-Action Status**: Deletes record row from DB.
* **Logs Generated**: None.
