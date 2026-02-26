"""
InfraWatch Nexus — API Server (Transport Layer)
=================================================
FastAPI transport layer. ZERO computation.
  - Validates inputs against dustbin registry
  - Writes strict event JSONs → Pathway watches
  - Reads Pathway atomic dashboard output → caches in memory
  - WebSocket broadcasts same state to both portals
  - Gemini Vision for dustbin photo extraction
  - Admin auth via bearer token
"""
import asyncio
import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, File, UploadFile, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import SERVER_HOST, SERVER_PORT, OUTPUT_DIR, REPORT_DIR, DEDUP_WINDOW_MINUTES
from config.wards import WARDS, ROAD_SEGMENTS, CITY_CENTER
from config.dustbins import DUSTBINS, get_dustbin, get_ward_dustbins, validate_dustbin_id

app = FastAPI(title="InfraWatch Nexus", version="3.0")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    import logging
    logging.error(f"422 Error! URL: {request.url}")
    logging.error(f"Headers: {request.headers}")
    logging.error(f"Body: {exc.body}")
    logging.error(f"Errors: {exc.errors()}")
    return JSONResponse(status_code=422, content={"detail": exc.errors(), "body": exc.body})

# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
PROJECT_ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WASTE_REPORT_DIR = os.path.join(PROJECT_ROOT, "data", "reports", "waste")
ROAD_REPORT_DIR  = os.path.join(PROJECT_ROOT, "data", "reports", "road")
VAN_LOG_DIR      = os.path.join(PROJECT_ROOT, "data", "reports", "vans")
WEATHER_DIR      = os.path.join(PROJECT_ROOT, "data", "reports", "weather")
PW_OUTPUT_DIR    = os.path.join(PROJECT_ROOT, "data", "output")
FRONTEND_DIR     = os.path.join(PROJECT_ROOT, "frontend")

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "INFRAWATCH_ADMIN_2026")
GEMINI_KEY  = os.getenv("GEMINI_API_KEY", "")

DUSTBIN_PATTERN = re.compile(r"MCD-W\d{2}-\d{3}")

for d in [WASTE_REPORT_DIR, ROAD_REPORT_DIR, VAN_LOG_DIR, WEATHER_DIR, PW_OUTPUT_DIR]:
    os.makedirs(d, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════════
# GLOBAL STATE — cached from Pathway atomic output (NOT computed here)
# ═══════════════════════════════════════════════════════════════════════════
cached_state = {
    "dustbin_states": [],
    "ward_risks": [],
    "road_issues": [],
    "priority_queue": [],
    "city_waste_index": 0,
    "city_road_index": 0,
    "rainfall_mm_hr": 0.0,
    "timestamp": None,
}
SERVER_STARTED_AT = datetime.now().isoformat()
ws_clients = set()

# ═══════════════════════════════════════════════════════════════════════════
# IN-MEMORY DEDUP (O(1) per request, rebuilt on restart)
# ═══════════════════════════════════════════════════════════════════════════
_last_report: dict = {}  # dustbin_id → {"timestamp": str, "overflow": int}


from datetime import timezone

def _is_duplicate(dustbin_id: str, overflow_level: int) -> bool:
    """Check if same dustbin was reported within DEDUP_WINDOW_MINUTES."""
    now = datetime.now(timezone.utc)
    if dustbin_id in _last_report:
        last = _last_report[dustbin_id]
        try:
            last_ts = datetime.fromisoformat(last["timestamp"].replace("Z", "+00:00"))
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            if (now - last_ts).total_seconds() < DEDUP_WINDOW_MINUTES * 60:
                # Merge: keep max overflow
                _last_report[dustbin_id] = {
                    "timestamp": now.isoformat(),
                    "overflow": max(last["overflow"], overflow_level),
                }
                return True
        except (ValueError, KeyError, TypeError):
            pass
    _last_report[dustbin_id] = {
        "timestamp": now.isoformat(),
        "overflow": overflow_level,
    }
    return False


def _rebuild_dedup_cache():
    """On restart, rebuild dedup cache from recent waste event files."""
    cutoff = datetime.now() - timedelta(minutes=DEDUP_WINDOW_MINUTES)
    try:
        for fname in os.listdir(WASTE_REPORT_DIR):
            fpath = os.path.join(WASTE_REPORT_DIR, fname)
            # Only check files modified within dedup window
            if os.path.getmtime(fpath) < cutoff.timestamp():
                continue
            try:
                with open(fpath, "r") as f:
                    events = json.load(f)
                if isinstance(events, list):
                    for e in events:
                        did = e.get("dustbin_id", "")
                        if did:
                            _last_report[did] = {
                                "timestamp": e.get("timestamp", ""),
                                "overflow": e.get("overflow_level", 1),
                            }
            except Exception:
                continue
    except FileNotFoundError:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# REQUEST MODELS (strict)
# ═══════════════════════════════════════════════════════════════════════════
class DustbinConfirmReport(BaseModel):
    dustbin_id: str
    overflow_level: int  # 1–5

class RoadIssueReport(BaseModel):
    from_dustbin: str
    to_dustbin: str
    issue_type: str   # pothole / waterlogging / crack / construction
    severity: int     # 1–5

class VanCollectionReport(BaseModel):
    dustbin_id: str


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS — write strict event files
# ═══════════════════════════════════════════════════════════════════════════
def _write_event(directory: str, prefix: str, data: dict) -> str:
    """Write a single event as a unique JSON file. Strict schema."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    uid = uuid.uuid4().hex[:8]
    filename = f"{prefix}_{ts}_{uid}.json"
    filepath = os.path.join(directory, filename)
    with open(filepath, "w") as f:
        json.dump([data], f)  # Array format for Pathway
    return filename


def _check_admin_token(authorization: Optional[str]) -> bool:
    """Strict admin token check."""
    if not authorization:
        return False
    return authorization == f"Bearer {ADMIN_TOKEN}"


# ═══════════════════════════════════════════════════════════════════════════
# CITIZEN ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/report/dustbin/detect")
async def detect_dustbin_from_photo(file: UploadFile = File(...)):
    """
    Step 1 of citizen flow: Upload photo → Gemini Vision → extract dustbin ID.
    Returns detected ID for user confirmation. Does NOT create event.
    """
    if not GEMINI_KEY:
        return JSONResponse(content={
            "detected_id": None,
            "fallback": True,
            "message": "AI not configured. Please select dustbin manually.",
            "dustbins": {k: {"street": v["street"], "ward_id": v["ward_id"]}
                         for k, v in DUSTBINS.items()},
        })

    try:
        import requests
        import base64
        
        image_bytes = await file.read()
        img_data = base64.b64encode(image_bytes).decode('utf-8')
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
        headers = {'Content-Type': 'application/json'}
        payload = {
            "contents": [{
                "parts": [
                    {"text": "Look at this image of a dustbin/waste bin. Extract the dustbin identification number or label visible on it. The format should be like MCD-W06-003. Return ONLY the ID string, nothing else."},
                    {"inline_data": {"mime_type": file.content_type or "image/jpeg", "data": img_data}}
                ]
            }]
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        resp_json = response.json()
        
        try:
            raw_text = resp_json['candidates'][0]['content']['parts'][0]['text'].strip()
        except (KeyError, IndexError):
            raw_text = ""

        # Strict regex extraction
        match = DUSTBIN_PATTERN.search(raw_text)
        if match:
            candidate = match.group(0)
            if validate_dustbin_id(candidate):
                dustbin = get_dustbin(candidate)
                return JSONResponse(content={
                    "detected_id": candidate,
                    "fallback": False,
                    "street": dustbin["street"],
                    "ward_id": dustbin["ward_id"],
                    "message": f"Detected: {candidate} — {dustbin['street']}. Please confirm.",
                })

        # No valid ID found → fallback
        return JSONResponse(content={
            "detected_id": None,
            "fallback": True,
            "message": "Could not detect dustbin ID. Please select manually.",
            "dustbins": {k: {"street": v["street"], "ward_id": v["ward_id"]}
                         for k, v in DUSTBINS.items()},
        })

    except Exception as e:
        return JSONResponse(content={
            "detected_id": None,
            "fallback": True,
            "message": f"AI detection failed. Please select manually.",
            "dustbins": {k: {"street": v["street"], "ward_id": v["ward_id"]}
                         for k, v in DUSTBINS.items()},
        })


@app.post("/api/report/dustbin/confirm")
async def confirm_dustbin_report(report: DustbinConfirmReport):
    """
    Step 2 of citizen flow: User confirmed dustbin ID → write waste event.
    Validates against registry. Dedup check.
    """
    # Validate dustbin exists
    if not validate_dustbin_id(report.dustbin_id):
        return JSONResponse(
            content={"error": f"Invalid dustbin ID: {report.dustbin_id}"},
            status_code=400,
        )

    # Validate overflow level
    overflow = min(5, max(1, report.overflow_level))

    # Dedup check
    if _is_duplicate(report.dustbin_id, overflow):
        return JSONResponse(content={
            "status": "merged",
            "dustbin_id": report.dustbin_id,
            "message": f"Report merged with recent submission for {report.dustbin_id}.",
        })

    # Build strict event
    dustbin = get_dustbin(report.dustbin_id)
    event = {
        "event_id": f"WR-{uuid.uuid4().hex[:8]}",
        "dustbin_id": report.dustbin_id,
        "ward_id": dustbin["ward_id"],
        "overflow_level": overflow,
        "timestamp": datetime.now().isoformat(),
        "source": "citizen",
    }

    filename = _write_event(WASTE_REPORT_DIR, "waste", event)
    return JSONResponse(content={
        "status": "accepted",
        "event_id": event["event_id"],
        "dustbin_id": report.dustbin_id,
        "street": dustbin["street"],
        "file": filename,
        "message": f"Report for {report.dustbin_id} ({dustbin['street']}) accepted.",
    })


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN ENDPOINTS (require token)
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/report/road-issue")
async def report_road_issue(
    report: RoadIssueReport,
    authorization: Optional[str] = Header(None),
):
    """Admin: Report road issue between two dustbins. Requires auth token."""
    if not _check_admin_token(authorization):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    # Validate both dustbin IDs
    if not validate_dustbin_id(report.from_dustbin):
        return JSONResponse(
            content={"error": f"Invalid dustbin ID: {report.from_dustbin}"},
            status_code=400,
        )
    if not validate_dustbin_id(report.to_dustbin):
        return JSONResponse(
            content={"error": f"Invalid dustbin ID: {report.to_dustbin}"},
            status_code=400,
        )

    from_bin = get_dustbin(report.from_dustbin)
    to_bin = get_dustbin(report.to_dustbin)

    # Validate same ward
    if from_bin["ward_id"] != to_bin["ward_id"]:
        return JSONResponse(
            content={"error": "Dustbins must be in the same ward for road issue reporting."},
            status_code=400,
        )

    # Validate issue type
    valid_types = {"pothole", "waterlogging", "crack", "construction", "debris"}
    if report.issue_type not in valid_types:
        return JSONResponse(
            content={"error": f"Invalid issue_type. Must be one of: {valid_types}"},
            status_code=400,
        )

    severity = min(5, max(1, report.severity))

    event = {
        "event_id": f"RI-{uuid.uuid4().hex[:8]}",
        "from_dustbin": report.from_dustbin,
        "to_dustbin": report.to_dustbin,
        "ward_id": from_bin["ward_id"],
        "issue_type": report.issue_type,
        "severity": severity,
        "timestamp": datetime.now().isoformat(),
        "source": "driver",
    }

    filename = _write_event(ROAD_REPORT_DIR, "road", event)
    return JSONResponse(content={
        "status": "accepted",
        "event_id": event["event_id"],
        "from_dustbin": report.from_dustbin,
        "to_dustbin": report.to_dustbin,
        "file": filename,
        "message": f"Road issue ({report.issue_type}) between {report.from_dustbin} and {report.to_dustbin} reported.",
    })


@app.post("/api/demo/simulate-crisis")
async def simulate_crisis(authorization: Optional[str] = Header(None)):
    """Demo Mode: Injects a burst of synthetic reports to trigger the Escalation/Critical matrix."""
    if not _check_admin_token(authorization):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)
    
    # Target Ward 12 specifically to create a localized heat cluster
    demo_events = []
    
    # Generate 6 rapid reports for dustbin 1 (Triggers 'Escalated' or 'Critical')
    for _ in range(6):
        event = {
            "event_id": f"WR-DEMO-{uuid.uuid4().hex[:6]}",
            "dustbin_id": "MCD-W12-001",
            "ward_id": "W12",
            "overflow_level": 5,
            "timestamp": datetime.now().isoformat(),
            "source": "demo_bot"
        }
        _write_event(WASTE_REPORT_DIR, "waste", event)
        demo_events.append(event)
        
    # Generate a massive road issue nearby
    road_event = {
        "event_id": f"RI-DEMO-{uuid.uuid4().hex[:6]}",
        "from_dustbin": "MCD-W12-001",
        "to_dustbin": "MCD-W12-002",
        "ward_id": "W12",
        "issue_type": "waterlogging",
        "severity": 5,
        "timestamp": datetime.now().isoformat(),
        "source": "demo_bot"
    }
    _write_event(ROAD_REPORT_DIR, "road", road_event)
    
    return JSONResponse(content={
        "status": "success",
        "message": "🚨 CRISIS SIMULATION INJECTED. Watch the Admin Queue automatically prioritize Ward 12."
    })


@app.post("/api/van/collection")
async def report_van_collection(
    report: VanCollectionReport,
    authorization: Optional[str] = Header(None),
):
    """Admin: Van confirmed collection at a dustbin. Requires auth token."""
    if not _check_admin_token(authorization):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    if not validate_dustbin_id(report.dustbin_id):
        return JSONResponse(
            content={"error": f"Invalid dustbin ID: {report.dustbin_id}"},
            status_code=400,
        )

    dustbin = get_dustbin(report.dustbin_id)
    event = {
        "event_id": f"VC-{uuid.uuid4().hex[:8]}",
        "dustbin_id": report.dustbin_id,
        "ward_id": dustbin["ward_id"],
        "timestamp": datetime.now().isoformat(),
        "source": "driver",
        "event_type": "collection_confirmed",
    }

    filename = _write_event(VAN_LOG_DIR, "van", event)

    # Clear dedup cache for this dustbin
    _last_report.pop(report.dustbin_id, None)

    return JSONResponse(content={
        "status": "accepted",
        "event_id": event["event_id"],
        "dustbin_id": report.dustbin_id,
        "file": filename,
        "message": f"Collection at {report.dustbin_id} ({dustbin['street']}) confirmed.",
    })


# ═══════════════════════════════════════════════════════════════════════════
# READ-ONLY ENDPOINTS (serve cached Pathway output — NO computation)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health_check():
    """Production health check for Render/Vercel/Railway."""
    return JSONResponse(content={
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "engine": "active",
        "cache_entries": len(_last_report)
    })


@app.get("/api/forecast")
async def get_risk_forecast():
    """
    Predictive Risk Forecast: 3-day ward-level risk projection.
    Combines WeatherAPI forecast with current report density to predict
    which wards will become critical before it happens.
    """
    import requests as req
    wx_key = os.getenv("WX_API_KEY", "")
    forecast_data = []

    # Fetch 3-day forecast from WeatherAPI
    try:
        resp = req.get(
            "http://api.weatherapi.com/v1/forecast.json",
            params={"key": wx_key, "q": "Delhi", "days": 3, "aqi": "no"},
            timeout=8,
        )
        resp.raise_for_status()
        days = resp.json().get("forecast", {}).get("forecastday", [])
    except Exception:
        days = []

    # Current report counts per ward from cached Pathway state
    ward_report_counts = {}
    for ds in cached_state.get("dustbin_states", []):
        wid = ds.get("ward_id", "")
        ward_report_counts[wid] = ward_report_counts.get(wid, 0) + ds.get("report_count", 0)

    # Build per-ward, per-day predictive risk
    for day_data in days:
        date = day_data.get("date", "")
        day_info = day_data.get("day", {})
        total_precip_mm = day_info.get("totalprecip_mm", 0)
        max_wind_kph = day_info.get("maxwind_kph", 0)
        condition = day_info.get("condition", {}).get("text", "Clear")

        # Weather severity multiplier (0.0 to 1.0)
        rain_factor = min(1.0, total_precip_mm / 50.0)  # 50mm = max severity
        wind_factor = min(1.0, max_wind_kph / 80.0)
        weather_severity = round((rain_factor * 0.7 + wind_factor * 0.3), 2)

        ward_forecasts = []
        for wid, winfo in WARDS.items():
            current_reports = ward_report_counts.get(wid, 0)
            # Base risk = current report density (0-1 scale, 10 reports = max)
            base_risk = min(1.0, current_reports / 10.0)
            # Predicted risk = base risk amplified by weather forecast
            predicted_risk = round(min(1.0, base_risk + weather_severity * 0.6), 2)
            # Risk level label
            if predicted_risk >= 0.7:
                level = "CRITICAL"
            elif predicted_risk >= 0.4:
                level = "ELEVATED"
            else:
                level = "LOW"

            ward_forecasts.append({
                "ward_id": wid,
                "ward_name": winfo["name"],
                "current_reports": current_reports,
                "predicted_risk": predicted_risk,
                "risk_level": level,
            })

        # Sort by predicted risk descending
        ward_forecasts.sort(key=lambda w: w["predicted_risk"], reverse=True)

        forecast_data.append({
            "date": date,
            "condition": condition,
            "total_precip_mm": total_precip_mm,
            "max_wind_kph": max_wind_kph,
            "weather_severity": weather_severity,
            "wards": ward_forecasts,
        })

    return JSONResponse(content={
        "forecast": forecast_data,
        "generated_at": datetime.now().isoformat(),
    })


@app.get("/api/dashboard")
async def get_dashboard():
    """Full dashboard state — cached from Pathway atomic output. No computation here."""
    return JSONResponse(content=cached_state)


@app.get("/api/dustbins")
async def get_dustbins():
    """Return dustbin registry with live states from Pathway output."""
    # Merge static registry with live states
    live_states = {}
    for ds in cached_state.get("dustbin_states", []):
        live_states[ds.get("dustbin_id", "")] = ds

    result = {}
    for did, info in DUSTBINS.items():
        live = live_states.get(did, {})
        result[did] = {
            **info,
            "state": live.get("state", "Clear"),
            "report_count": live.get("report_count", 0),
            "overflow_level": live.get("overflow_level", 0),
        }

    return JSONResponse(content={"dustbins": result})


@app.get("/api/config")
async def get_config():
    """Ward and dustbin config for frontend map setup."""
    return JSONResponse(content={
        "wards": {k: {**v} for k, v in WARDS.items()},
        "dustbins": {k: {**v} for k, v in DUSTBINS.items()},
        "city_center": CITY_CENTER,
    })


@app.get("/api/priority")
async def get_priority():
    """Priority queue — served from Pathway output."""
    return JSONResponse(content={
        "priority_queue": cached_state.get("priority_queue", []),
        "timestamp": cached_state.get("timestamp"),
    })


@app.get("/api/weather")
async def get_weather():
    """Current weather — from Pathway output."""
    return JSONResponse(content={
        "rainfall_mm_hr": cached_state.get("rainfall_mm_hr", 0),
        "timestamp": cached_state.get("timestamp"),
    })


# ═══════════════════════════════════════════════════════════════════════════
# PATHWAY OUTPUT READER (background thread — reads atomic snapshot)
# ═══════════════════════════════════════════════════════════════════════════

def _read_dashboard_snapshot():
    """Read last complete line from Pathway's atomic dashboard.jsonl."""
    filepath = os.path.join(PW_OUTPUT_DIR, "dashboard.jsonl")
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r") as f:
            lines = f.readlines()
        if not lines:
            return None
        # Read last non-empty line (atomic snapshot)
        for line in reversed(lines):
            line = line.strip()
            if line:
                return json.loads(line)
        return None
    except Exception:
        return None


def _cache_updater():
    """Background thread: re-read Pathway atomic output every 3 seconds."""
    global cached_state
    while True:
        try:
            snapshot = _read_dashboard_snapshot()
            if snapshot:
                cached_state = snapshot
        except Exception as e:
            print(f"[Cache] Error: {e}")
        time.sleep(3)


# ═══════════════════════════════════════════════════════════════════════════
# WEBSOCKET (same state → both portals)
# ═══════════════════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_stream(websocket: WebSocket):
    """Push same dashboard state to ALL connected clients every 4 seconds."""
    await websocket.accept()
    ws_clients.add(websocket)
    try:
        while True:
            await websocket.send_json(cached_state)
            await asyncio.sleep(4)
    except WebSocketDisconnect:
        ws_clients.discard(websocket)
    except Exception:
        ws_clients.discard(websocket)


# ═══════════════════════════════════════════════════════════════════════════
# STATIC FILES & PAGE SERVING
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/")
async def serve_citizen_portal():
    """Serve Citizens' Portal."""
    filepath = os.path.join(FRONTEND_DIR, "citizen.html")
    with open(filepath, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/admin")
async def serve_admin_portal():
    """Serve Admin Portal."""
    filepath = os.path.join(FRONTEND_DIR, "admin.html")
    with open(filepath, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ═══════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    print("═" * 55)
    print("  InfraWatch Nexus — API Server v3.0 (Transport Only)")
    print("═" * 55)
    print(f"  Citizens Portal : http://localhost:{SERVER_PORT}/")
    print(f"  Admin Portal    : http://localhost:{SERVER_PORT}/admin")
    print(f"  Dustbins loaded : {len(DUSTBINS)}")
    print(f"  Gemini AI       : {'✓ Configured' if GEMINI_KEY else '✗ Manual fallback'}")
    print(f"  Pathway output  : {PW_OUTPUT_DIR}")

    _rebuild_dedup_cache()
    print(f"  Dedup cache     : {len(_last_report)} recent entries")

    # Start background cache updater
    t = threading.Thread(target=_cache_updater, daemon=True)
    t.start()
    print("  Cache updater started (3s interval)")

    # Start keep-alive self-ping (prevents Render free-tier spin-down)
    def _keep_alive():
        """Ping our own /health endpoint every 13 minutes to prevent Render sleep."""
        import requests as req
        port = int(os.environ.get("PORT", 8000))
        url = f"http://localhost:{port}/health"
        while True:
            time.sleep(780)  # 13 minutes
            try:
                req.get(url, timeout=5)
                print("  [keep-alive] Self-ping OK")
            except Exception:
                print("  [keep-alive] Self-ping failed (non-critical)")

    ka = threading.Thread(target=_keep_alive, daemon=True)
    ka.start()
    print("  Keep-alive ping started (13min interval)")


# ═══════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    # Render provides PORT in the environment. Bind to it securely.
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("api.server:app", host="0.0.0.0", port=port, reload=False)
