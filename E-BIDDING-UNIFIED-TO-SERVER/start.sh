#!/bin/bash

# E-Bidding Unified - Start Script for Linux/macOS
# This script creates and uses a virtual environment, then starts both backend and frontend servers

set -e

echo "Starting E-Bidding Unified..."

# Get script directory (project root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# Function to check if a command exists
command_exists() {
    command -v "$1" &> /dev/null
}

# Check Python availability
if ! command_exists python3; then
    echo "Error: python3 is not installed or not in PATH"
    exit 1
fi

# Check Node.js availability
if ! command_exists node; then
    echo "Error: Node.js is not installed or not in PATH"
    exit 1
fi

# Check npm availability
if ! command_exists npm; then
    echo "Error: npm is not installed or not in PATH"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "Installing backend requirements..."
    "$VENV_DIR/bin/python" -m pip install --upgrade pip
    "$VENV_DIR/bin/python" -m pip install -r "$SCRIPT_DIR/backend/requirements.txt"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Start backend
echo "Starting backend server..."
cd "$SCRIPT_DIR/backend"
uvicorn backend_server:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

# Wait for backend to start
sleep 5

# Verify backend is running
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo "Error: Backend failed to start. Check logs above."
    exit 1
fi

echo "✓ Backend started: http://127.0.0.1:8000"

# Start frontend using wrapper script
echo "Starting frontend server..."
cd "$SCRIPT_DIR/frontend"
./start-frontend.sh &
FRONTEND_PID=$!

# Wait for frontend to start
sleep 5

# Verify frontend is running
if ! kill -0 $FRONTEND_PID 2>/dev/null; then
    echo "Error: Frontend failed to start"
    kill $BACKEND_PID 2>/dev/null || true
    exit 1
fi

echo "✓ Frontend started: http://localhost:8080 (or 8081 if 8080 is in use)"
echo ""
echo "Both servers are running!"
echo "  • Backend:  http://127.0.0.1:8000"
echo "  • Frontend: http://localhost:8080"
echo ""
echo "Press Ctrl+C to stop all servers"

# Cleanup function
cleanup() {
    echo ""
    echo "Stopping servers..."
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    wait 2>/dev/null || true
    echo "All servers stopped."
}

# Set up trap for clean exit
trap cleanup SIGINT SIGTERM

# Wait for both processes
wait
