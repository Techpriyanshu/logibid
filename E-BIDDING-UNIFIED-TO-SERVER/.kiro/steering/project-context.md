# Project Context - E-Bidding Unified

This steering file provides essential project context that should be loaded first when working with the E-Bidding system.

## Project Structure

```
E-BIDDING-UNIFIED/
├── backend/              # Python FastAPI backend with Selenium automation
├── frontend/             # React TypeScript frontend
└── .kiro/                # Kiro steering and configuration
```

## Backend (Python/FastAPI)

**Location:** `E-BIDDING-UNIFIED/backend/`

**Key Points:**
- FastAPI server running on port 8000
- SQLite databases for all data persistence
- Selenium browser automation for SAP e-bidding
- Parallel execution for multiple depots

**Configuration:**
- `config/application.yaml` - Global settings
- `config/depots.yaml` - Depot definitions
- `config/credentials.env` - SAP credentials

**Main Entry Point:** `backend_server.py` (FastAPI app)

## Frontend (React/TypeScript)

**Location:** `E-BIDDING-UNIFIED/frontend/`

**Key Points:**
- Vite + React + TypeScript
- shadcn/ui component library
- API base URL: http://127.0.0.1:8000
- Port 5173 for dev server

**Main Entry Point:** `src/main.tsx`

## Running

1. **Backend:** `cd backend && uvicorn backend_server:app --host 127.0.0.1 --port 8000 --reload`
2. **Frontend:** `cd frontend && npm run dev`

## Important Notes

- Backend uses multiple SQLite databases (not MySQL/PostgreSQL)
- Selenium automation requires Chrome/Chromium
- CORS enabled for localhost:5173 and localhost:8000
- Frontend .env file at `frontend/.env`
- Backend credentials at `backend/config/credentials.env`