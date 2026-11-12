# E-BIDDING UNIFIED

A comprehensive e-bidding automation system with FastAPI backend and React frontend.

## Quick Start

### Prerequisites
- Python 3.9+
- Node.js 18+
- Chrome/Chromium browser

### One-Command Start

**Linux/macOS:**
```bash
chmod +x start.sh
./start.sh
```

**Windows (PowerShell):**
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

This will:
1. Create or reuse a Windows virtual environment (`.venv-windows`) without modifying a non-Windows `.venv`
2. Install backend dependencies
3. Start the backend on `127.0.0.1:8000`
4. Start the frontend on `127.0.0.1:8080`
5. Stop both services when the PowerShell window is closed with Ctrl+C

## Manual Setup

### Create Virtual Environment

**Linux/macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

**Windows (PowerShell):**
```powershell
python -m venv .venv-windows
.\.venv-windows\Scripts\python.exe -m pip install -r backend\requirements.txt
```

### Backend Setup

```bash
# If not already activated
source .venv/bin/activate  # Linux/macOS
# or
.\.venv\Scripts\Activate.ps1  # Windows

cd backend

# Copy example config files
cp config/application.yaml.example config/application.yaml
cp config/depots.yaml.example config/depots.yaml
cp config/credentials.env.example config/credentials.env

# Edit config/credentials.env with your credentials
# Edit config/application.yaml as needed
```

### Frontend Setup

```bash
cd frontend
npm install
# or
bun install
```

## Running the Application

**Option 1: Using Start Scripts (Recommended)**
```bash
./start.sh          # Linux/macOS
.\start.ps1         # Windows
```

**Option 2: Manual Start**

Terminal 1 - Backend:
```bash
source .venv/bin/activate  # Linux/macOS
cd backend
uvicorn backend_server:app --host 127.0.0.1 --port 8000 --reload
```

Terminal 2 - Frontend:
```bash
cd frontend
npm run dev
# or
bun run dev
```

## WhatsApp Bid Bot

This project now includes a simple WhatsApp bot layer for bid operations. It can reply to inbound WhatsApp messages and process commands such as:

- `BID depot=LUCKNOW qty=25 destination=ABC`
- `STATUS`
- `STOP ALL`
- `STOP <job_id>`
- `HELP`

### Configure it
Add these values to the project root `.env` (or backend `.env` if you use the backend loader):

```bash
WHATSAPP_VERIFY_TOKEN=your_meta_verify_token
WHATSAPP_ACCESS_TOKEN=your_meta_access_token
WHATSAPP_PHONE_NUMBER_ID=your_whatsapp_business_phone_number_id
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
```

Only set the Twilio variables or the Meta variables — the backend automatically uses whichever provider is configured.

### Webhook endpoint
- `GET /api/whatsapp/webhook` — Meta/Twilio verification callback
- `POST /api/whatsapp/webhook` — inbound WhatsApp message webhook
- `POST /api/whatsapp/command` — direct command trigger for automation/testing

Example JSON for direct testing:

```json
{
  "from": "whatsapp:+15551234567",
  "message": "STATUS"
}
```

## Configuration

### Backend Config
- `config/application.yaml` - Main application settings
- `config/depots.yaml` - Depot definitions
- `config/credentials.env` - SAP credentials

### Restore Master Data

If zone, plant, depot, or tonnage requests report that the database is unreachable,
the app serves the dated, read-only `config/master_data_snapshot.json` for dropdown
display. The Control Panel labels this snapshot; bid execution is blocked until the
live MySQL database is reachable, populated, and the master-data mappings have
been explicitly verified. The checked-in local configuration currently points to
`127.0.0.1:3307`.

The existing `ebid.sql` backup includes bid history and other operational tables;
do not import that full dump to restore dropdowns. To prepare a safe master-only
restore file from it, run from the project root:

```powershell
python backend\tools\prepare_master_data_restore.py ..\ebid.sql
```

This writes `backend\config\master_data_restore.sql` and the read-only
`backend\config\master_data_snapshot.json`. The SQL contains only zones,
plants, depots, plant-to-depot mappings, destinations, and tonnage options; it
does not drop tables or replace existing rows. A MySQL administrator can review
and import that file into the configured `ebidding_db` database.

**Important:** the available master-data rows are from an August 2026 snapshot.
They contain four zones but only one plant, so verify the current zones and
plant mappings with the data owner before using the snapshot for live bids. The
restore creates `master_data_status` with `verified=0`; the app continues to label
these rows as snapshot data and blocks bid execution. Only after the data owner
confirms that all mappings are current should an administrator mark them verified:

```sql
UPDATE master_data_status
SET source = 'database', snapshot_date = NULL, verified = 1
WHERE id = 1;
```

Do not run this update just to enable the Start Bidding button.

### Environment Variables
Create a `.env` file in the project root. The database must be reachable and contain the master-data tables used for zone, plant, depot, destination, and tonnage selection.
```
DATABASE_URL=mysql+pymysql://user:pass@host:3306/dbname
E2S_USERNAME=your_sap_username
E2S_PASSWORD=your_sap_password
HEADLESS=false
```

## Project Structure

```
E-BIDDING-UNIFIED/
├── .venv/               # Virtual environment (created by start script)
├── .venv-windows/       # Windows virtual environment (created by Windows start script)
├── backend/             # Python FastAPI backend
│   ├── src/            # Backend Python modules
│   ├── config/         # Configuration files
│   ├── backend_server.py
│   └── requirements.txt
├── frontend/           # React frontend
│   ├── src/
│   └── package.json
├── start.sh            # Linux/macOS start script
├── start.ps1           # Windows start script
└── README.md
```

## API Endpoints

### Master Data
- `GET /api/zones` - List zones
- `GET /api/plants?zone_id={id}` - List plants
- `GET /api/plants/{plant_id}/depots` - List depots for plant
- `GET /api/tonnage-options` - List tonnage options

### Bidding
- `POST /api/start-bid` - Start bidding automation
- `GET /api/bid-job/{job_id}` - Poll job status

### Reports
- `GET /api/successful-bids` - List successful bids
- `GET /api/reports/summary` - Get KPI summary
- `GET /api/bid-outcomes` - List bid outcomes
- `GET /api/live-bids` - List live bids

### Fleet Management
- `GET /api/trucks` - List trucks
- `GET /api/fleet-daily` - List fleet daily entries
- `GET /api/fleet-requests` - List fleet requests

### Notifications
- `GET /api/notifications` - List notifications

## Troubleshooting

### Backend won't start
- Check that `.venv` is activated
- Verify credentials in `config/credentials.env`
- Check logs for database connection issues

### Frontend won't start
- Check Node.js version (18+ required)
- Verify port 8080 is not in use
- Check `npm install` completed successfully

### API endpoints returning 404
- Verify backend is running on port 8000
- Check `DATABASE_URL` is set in `.env`

## Documentation

- `backend/ARCHITECTURE.md` - Backend architecture details
- `backend/README.md` - Backend-specific documentation
- `backend/docs/` - Additional documentation
- `frontend/src/` - Frontend source code