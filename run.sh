#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Check if docker compose is available
if command -v docker &> /dev/null && docker compose version &> /dev/null; then
    echo "Starting with Docker Compose..."
    cd "$SCRIPT_DIR"
    docker compose up --build
else
    echo "Docker not found. Starting locally..."

    # Set API_BASE for local dev (frontend on :3000 needs to reach backend on :8000)
    echo "window.API_BASE = 'http://localhost:8000';" > "$SCRIPT_DIR/frontend/config.js"

    cd "$SCRIPT_DIR/backend"
    source venv/bin/activate
    python -m uvicorn app.main:app --reload --port 8000 &
    BACKEND_PID=$!

    cd "$SCRIPT_DIR/frontend"
    python -m http.server 3000 &
    FRONTEND_PID=$!

    echo ""
    echo "Backend:  http://localhost:8000"
    echo "Frontend: http://localhost:3000"
    echo "API docs: http://localhost:8000/docs"
    echo ""
    echo "Press Ctrl+C to stop"

    trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo \"window.API_BASE = '';\" > \"$SCRIPT_DIR/frontend/config.js\"" EXIT
    wait
fi
