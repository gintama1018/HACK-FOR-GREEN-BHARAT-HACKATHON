#!/bin/bash
# Smoke test: start server, hit /api/config, then stop
set -e
PROJECT="/mnt/c/Users/hp/HACK FOR GREEN BHARAT HACKATHON"
cd "$PROJECT"

mkdir -p data/reports/waste data/reports/road data/reports/vans data/reports/weather data/output

# Start server in background
.venv/bin/python -m uvicorn api.server:app --host 0.0.0.0 --port 8000 > /tmp/server.log 2>&1 &
SERVER_PID=$!
echo "Server PID: $SERVER_PID"

# Wait for startup
sleep 5

# Test /api/config
echo "Testing /api/config..."
curl -sf http://localhost:8000/api/config | .venv/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
print('Wards:', len(d['wards']))
print('Dustbins:', len(d['dustbins']))
print('City center:', d['city_center'])
print('CONFIG: OK')
"

# Test /api/dashboard
echo "Testing /api/dashboard..."
curl -sf http://localhost:8000/api/dashboard | .venv/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
print('Dashboard keys:', list(d.keys())[:5])
print('DASHBOARD: OK')
"

# Test /api/weather
echo "Testing /api/weather..."
curl -sf http://localhost:8000/api/weather | .venv/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
print('Weather:', d)
print('WEATHER: OK')
"

# Stop server
kill $SERVER_PID 2>/dev/null || true
echo "SMOKE TEST: PASSED"
