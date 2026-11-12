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
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
.\start.ps1
```

This will:
1. Create a virtual environment (`.venv`)
2. Install backend dependencies
3. Start the backend on port 8000
4. Start the frontend on port 8080

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
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
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

## Configuration

### Backend Config
- `config/application.yaml` - Main application settings
- `config/depots.yaml` - Depot definitions
- `config/credentials.env` - SAP credentials

### Environment Variables
Create a `.env` file in the project root:
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