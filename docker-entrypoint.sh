#!/bin/bash
# Docker-only entrypoint — skips venv/install (already done at build time)
set -e

echo "═══════════════════════════════════════════════"
echo "  InfraWatch Nexus — Docker Start"
echo "═══════════════════════════════════════════════"

# Create data dirs
mkdir -p data/reports/waste data/reports/road data/reports/vans data/reports/weather data/output
echo "  Data directories: OK"

# Start Pathway engine in background — with crash-restart loop
echo "  ▶ Starting Pathway engine (auto-restart on crash)..."
while true; do
    python pathway_engine.py
    echo "  Pathway crashed — restarting in 5s..."
    sleep 5
done &
PATHWAY_LOOP_PID=$!
echo "  Pathway loop PID: $PATHWAY_LOOP_PID"

# Give Pathway 2 seconds to initialize
sleep 2

# Start FastAPI server — bind to Render's $PORT
echo "  ▶ Starting FastAPI server on port ${PORT:-8000}..."

cleanup() {
    echo "  Stopping services..."
    kill $PATHWAY_LOOP_PID 2>/dev/null || true
    pkill -f pathway_engine.py 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

python api/server.py
