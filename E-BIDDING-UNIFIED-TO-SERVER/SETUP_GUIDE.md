# Setup Guide - E-BIDDING UNIFIED

This guide explains how to set up and run the unified E-Bidding system.

## Overview

The unified E-Bidding system merges:
1. **Backend**: Python FastAPI server with Selenium automation for SAP e-bidding
2. **Frontend**: React TypeScript application with Vite

## Prerequisites

### System Requirements
- macOS or Linux (for development)
- Python 3.9+
- Node.js 18+
- Chrome/Chromium browser
- At least 4GB RAM

## Directory Structure

```
E-BIDDING-UNIFIED/
├── backend/              # Python FastAPI backend
│   ├── src/              # Backend Python modules
│   ├── config/           # Configuration files
│   ├── backend_server.py
│   ├── requirements.txt
│   └── ...
└── frontend/            # React frontend
    ├── src/             # Frontend source code
    ├── public/          # Static assets
    ├── package.json
    └── ...
```

## Backend Setup

### Step 1: Navigate to backend directory

```bash
cd E-BIDDING-UNIFIED/backend
```

### Step 2: Install Python dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Configure the backend

Copy and configure the required config files:

```bash
# Create credentials file
cp config/credentials.env.example config/credentials.env
```

Edit `config/credentials.env`:

```bash
vim config/credentials.env
```

Add your SAP credentials:

```
SAP_USERNAME=your_username
SAP_PASSWORD=your_password
```

### Step 4: Verify configuration

The backend uses `config/application.yaml` for settings like:
- Selenium browser options
- Depot configurations
- Timer settings
- Timeout values

Review and adjust as needed in `config/application.yaml`.

## Frontend Setup

### Step 1: Navigate to frontend directory

```bash
cd E-BIDDING-UNIFIED/frontend
```

### Step 2: Install Node dependencies

Using npm:
```bash
npm install
```

Or using bun (faster):
```bash
bun install
```

### Step 3: Configure environment variables

The frontend uses `.env` for configuration:

```bash
# Check the .env file exists
ls -la .env

# Default configuration points to backend on port 8000
cat .env
```

Expected content:
```
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Running the Application

### Option 1: Start Backend and Frontend Manually

**Terminal 1 - Backend:**
```bash
cd E-BIDDING-UNIFIED/backend
uvicorn backend_server:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 2 - Frontend:**
```bash
cd E-BIDDING-UNIFIED/frontend
npm run dev
# or
bun run dev
```

### Option 2: Create a Launch Script

Create `launch.sh` in the root directory:

```bash
#!/bin/bash

# Launch Backend
echo "Starting Backend..."
cd backend
uvicorn backend_server:app --host 127.0.0.1 --port 8000 --reload &
BACKEND_PID=$!

# Wait for backend to start
sleep 3

# Launch Frontend
echo "Starting Frontend..."
cd ../frontend
npm run dev &
FRONTEND_PID=$!

echo "Backend PID: $BACKEND_PID"
echo "Frontend PID: $FRONTEND_PID"

# Keep script running
wait
```

Make it executable and run:
```bash
chmod +x launch.sh
./launch.sh
```

### Accessing the Application

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **Backend API Docs**: http://localhost:8000/docs (FastAPI auto-generated)

## Running the Backend Directly

To run the backend without uvicorn (for development):

```bash
cd E-BIDDING-UNIFIED/backend
python backend_server.py
```

## Common Issues

### Backend won't start

1. **Port 8000 already in use**:
```bash
lsof -i :8000
kill -9 <PID>
```

2. **Missing Python dependencies**:
```bash
pip install -r requirements.txt
```

3. **Chrome/Selenium issues**:
```bash
# Check chromedriver is in path
ls -la src/chromedriver-linux64/
```

### Frontend won't start

1. **Port 5173 already in use**:
```bash
lsof -i :5173
kill -9 <PID>
```

2. **Node modules issue**:
```bash
rm -rf node_modules package-lock.json
npm install
```

### Frontend can't connect to backend

1. **Check backend is running**:
```bash
curl http://127.0.0.1:8000/docs
```

2. **Check CORS settings** in `backend_server.py`:
```python
allow_origins=[
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:5173",  # Add this
    "http://127.0.0.1:5173",  # Add this
]
```

## Deployment

### Production Backend

```bash
cd E-BIDDING-UNIFIED/backend
gunicorn -w 4 -k uvicorn.workers.UvicornWorker backend_server:app --bind 0.0.0.0:8000
```

### Production Frontend

```bash
cd E-BIDDING-UNIFIED/frontend
npm run build
# Serve dist/ directory with nginx or similar
```

## Development

### Backend Development

- Source code: `backend/src/`
- API endpoints: `backend/backend_server.py`
- Configuration: `backend/config/`

### Frontend Development

- Source code: `frontend/src/`
- Components: `frontend/src/components/`
- Pages: `frontend/src/pages/`
- API clients: `frontend/src/api/`

## Documentation

- `backend/ARCHITECTURE.md` - Detailed backend architecture
- `backend/README.md` - Backend README
- `frontend/README.md` - Frontend README

## Support

For issues, check the logs:
- Backend: Terminal output or `logs/` directory
- Frontend: Browser console (F12)