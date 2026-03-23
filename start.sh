#!/bin/bash
echo "========================================"
echo "  金融即時偵測系統 Financial Radar"
echo "========================================"
echo ""

# Copy .env if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "[INFO] Created .env from .env.example"
    echo "[WARN] Please edit .env and add your API keys!"
fi

# Start backend
echo "[1/2] Starting backend server..."
cd "$(dirname "$0")"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Wait for backend
sleep 3

# Start frontend
echo "[2/2] Starting frontend dev server..."
cd frontend && npm run dev &
FRONTEND_PID=$!

echo ""
echo "========================================"
echo "  System started!"
echo "  Frontend: http://localhost:5173"
echo "  Backend:  http://localhost:8000"
echo "  API Docs: http://localhost:8000/docs"
echo "========================================"
echo ""
echo "Press Ctrl+C to stop both servers"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM
wait
