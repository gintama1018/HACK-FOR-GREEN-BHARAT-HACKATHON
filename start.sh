#!/bin/bash
# InfraWatch Nexus — One-shot startup for Ubuntu WSL
# Run this from the project root: bash start.sh

set -e
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "═══════════════════════════════════════════════"
echo "  InfraWatch Nexus — Startup"
echo "═══════════════════════════════════════════════"

# ── 1. Venv ─────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "  Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate
echo "  Venv: $VIRTUAL_ENV"

# ── 2. Install deps ──────────────────────────────────
echo "  Installing dependencies..."
pip install -q -r requirements.txt
echo "  Dependencies: OK"

# ── 3. Check .env ────────────────────────────────────
if [ ! -f ".env" ]; then
    echo "  WARNING: .env not found. Generating secure defaults..."
    # Generate a cryptographically random admin token — not a known default!
    ADMIN_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > .env << EOF
WX_API_KEY=
GEMINI_API_KEY=
ADMIN_TOKEN=${ADMIN_TOKEN}
EOF
    echo ""
    echo "  ┌────────────────────────────────────────────────────────────────┐"
    echo "  │  IMPORTANT: Your auto-generated admin token is:               │"
    echo "  │  ${ADMIN_TOKEN}  │"
    echo "  │  Save this — it is NOT stored anywhere else.                  │"
    echo "  └────────────────────────────────────────────────────────────────┘"
    echo ""
fi

# ── 4. Create data dirs ──────────────────────────────
mkdir -p data/reports/waste data/reports/road data/reports/vans data/reports/weather data/output
echo "  Data directories: OK"

# ── 5. Start Pathway engine (with crash-restart loop) ─
echo ""
echo "  ▶ Starting Pathway engine (auto-restart on crash)..."
while true; do
    python3 pathway_engine.py
    echo "  Pathway crashed — restarting in 5s..."
    sleep 5
done &
PATHWAY_LOOP_PID=$!
echo "  Pathway loop PID: $PATHWAY_LOOP_PID"

# Give Pathway 3 seconds to write initial snapshot
sleep 3

# ── 6. Start FastAPI server ──────────────────────────
echo ""
echo "  ▶ Starting FastAPI server..."
echo "  Citizens' Portal: http://localhost:8000/"
echo "  Admin Portal:     http://localhost:8000/admin"
echo "  WebSocket:        ws://localhost:8000/ws"
echo ""
echo "  Press Ctrl+C to stop both services."
echo "═══════════════════════════════════════════════"

# Trap Ctrl+C to kill both
cleanup() {
    echo ""
    echo "  Stopping services..."
    kill $PATHWAY_LOOP_PID 2>/dev/null || true
    # Kill any child python pathway_engine.py processes too
    pkill -f pathway_engine.py 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

python3 api/server.py
