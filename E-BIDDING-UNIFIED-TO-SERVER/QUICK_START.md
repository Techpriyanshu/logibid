# Quick Start - E-BIDDING UNIFIED

Get the unified E-Bidding system running in under 5 minutes.

## Prerequisites

- Python 3.9+ installed
- Node.js 18+ installed
- Chrome browser installed

## Quick Setup

### 1. Install Backend Dependencies

```bash
cd E-BIDDING-UNIFIED/backend
pip install -r requirements.txt
cp config/credentials.env.example config/credentials.env
# Edit config/credentials.env with your SAP credentials
```

### 2. Install Frontend Dependencies

```bash
cd ../frontend
npm install
# or
bun install
```

### 3. Run Both Services

**Terminal 1 - Backend:**
```bash
cd E-BIDDING-UNIFIED/backend
uvicorn backend_server:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 2 - Frontend:**
```bash
cd E-BIDDING-UNIFIED/frontend
npm run dev
```

### 4. Access Application

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000

## What Was Merged?

This unified directory contains:

| Component | Original Location | New Location |
|-----------|-------------------|--------------|
| Backend | `OLD/BCF/backend_parallel_code.../` | `E-BIDDING-UNIFIED/backend/` |
| Frontend | `FRONTEND_E-BIDDING_111/` | `E-BIDDING-UNIFIED/frontend/` |

## Next Steps

1. Configure SAP credentials in `backend/config/credentials.env`
2. Start both backend and frontend
3. Browse to http://localhost:5173
4. Read `SETUP_GUIDE.md` for detailed instructions