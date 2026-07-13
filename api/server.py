"""
InfraWatch Nexus -- API Server (Transport Layer) v4.0
======================================================
FastAPI transport layer. ZERO computation.
  - Validates inputs against dustbin registry
  - Writes strict event JSONs -> Pathway watches
  - Persists events to SQLite (Phase 4)
  - Reads Pathway atomic dashboard output -> caches in memory
  - WebSocket broadcasts with content-hash diffing (Phase 5)
  - HMAC token auth + rate limiting (Phase 6)
  - VRP route optimization endpoint (Phase 8)
  - Admin auth via HMAC-signed bearer token
"""
import asyncio
import base64
import csv
import hashlib
import httpx
import io
import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import SERVER_HOST, SERVER_PORT, OUTPUT_DIR, REPORT_DIR, DEDUP_WINDOW_MINUTES
from config.wards import WARDS, ROAD_SEGMENTS, CITY_CENTER
from config.dustbins import DUSTBINS, get_dustbin, get_ward_dustbins, validate_dustbin_id
from engine.auth import verify_token, generate_token
from engine.database import (
    init_db, insert_event, get_event_count,
    insert_pending_reward, resolve_rewards_for_dustbin,
    get_user_reward_summary, get_leaderboard, export_pending_rewards,
    get_user_reports,
)
from engine.snapshot import read_dashboard_snapshot
from engine.route_optimizer import optimize_route, optimize_all_wards
from llm_layer.advisor import answer_citizen_query

# ═══════════════════════════════════════════════════════════════════════════
# APP SETUP
# ═══════════════════════════════════════════════════════════════════════════
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="InfraWatch Nexus", version="4.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
_cors_default = "https://infrawatch-nexus-tnlf.onrender.com,http://localhost:8000,http://127.0.0.1:8000"
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", _cors_default).split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    import logging
    logging.error(f"422 Error! URL: {request.url}")
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

DUSTBIN_PATTERN = re.compile(r"MCD-DL-\d{4}")

for d in [WASTE_REPORT_DIR, ROAD_REPORT_DIR, VAN_LOG_DIR, WEATHER_DIR, PW_OUTPUT_DIR]:
    os.makedirs(d, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════════
# GLOBAL STATE -- cached from Pathway atomic output (NOT computed here)
# ═══════════════════════════════════════════════════════════════════════════
cached_state = {
    "dustbin_states": [],
    "ward_risks": [],
    "road_issues": [],
    "priority_queue": [],
    "city_waste_index": 0,
    "city_road_index": 0,
    "rainfall_mm_hr": 0.0,
    "optimized_routes": {},
    "timestamp": None,
}
SERVER_STARTED_AT = datetime.now().isoformat()
ws_clients = set()

# WebSocket diff hashing
_last_broadcast_hash = ""

# ═══════════════════════════════════════════════════════════════════════════
# IN-MEMORY DEDUP (O(1) per request)
# ═══════════════════════════════════════════════════════════════════════════
_last_report = {}


def _is_duplicate(dustbin_id, overflow_level):
    """Check if same dustbin was reported within DEDUP_WINDOW_MINUTES."""
    now = datetime.now(timezone.utc)
    if dustbin_id in _last_report:
        last = _last_report[dustbin_id]
        try:
            last_ts = datetime.fromisoformat(last["timestamp"].replace("Z", "+00:00"))
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            if (now - last_ts).total_seconds() < DEDUP_WINDOW_MINUTES * 60:
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
# REQUEST MODELS
# ═══════════════════════════════════════════════════════════════════════════
class DustbinConfirmReport(BaseModel):
    dustbin_id: str
    overflow_level: int        # 1-5
    reporter_upi: str = ""    # optional e.g. "user@upi" for reward disbursement
    reporter_name: str = ""   # optional display name for leaderboard


class RoadIssueReport(BaseModel):
    from_dustbin: str
    to_dustbin: str
    issue_type: str   # pothole / waterlogging / crack / construction
    severity: int     # 1-5


class VanCollectionReport(BaseModel):
    dustbin_id: str


class RoadClearReport(BaseModel):
    event_id: str


class ChatRequest(BaseModel):
    message: str
    user_sub: str = ""   # optional — anonymous if omitted



# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def _write_event(directory, prefix, data):
    """Write a single event as a unique JSON file. Strict schema."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    uid = uuid.uuid4().hex[:8]
    filename = f"{prefix}_{ts}_{uid}.json"
    filepath = os.path.join(directory, filename)
    with open(filepath, "w") as f:
        json.dump([data], f)
    return filename


def _check_admin_token(authorization):
    """Check admin token using HMAC-signed auth module."""
    if not authorization:
        return False
    return verify_token(authorization)


def _decode_jwt_sub(authorization):
    """
    Extract user_sub from Auth0 Bearer JWT.
    Decodes the payload section (middle part) without signature verification.
    Auth0 front-end has already verified the token; we just read the sub claim.
    Returns empty string on any failure.
    """
    try:
        if not authorization:
            return ""
        token = authorization.replace("Bearer ", "").strip()
        parts = token.split(".")
        if len(parts) != 3:
            return ""
        # Add padding for base64
        padded = parts[1] + "==" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.b64decode(padded).decode("utf-8"))
        return payload.get("sub", "")
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════════════════
# CITIZEN ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/report/dustbin/confirm")
@limiter.limit("10/minute")
async def confirm_dustbin_report(
    request: Request,
    report: DustbinConfirmReport,
    authorization: Optional[str] = Header(None),
):
    """
    Citizen reports dustbin overflow (after QR scan pre-fills ID).
    Validates against registry. Dedup check. Writes event. Issues pending reward.
    """
    if not validate_dustbin_id(report.dustbin_id):
        return JSONResponse(
            content={"error": f"Invalid dustbin ID: {report.dustbin_id}"},
            status_code=400,
        )

    overflow = min(5, max(1, report.overflow_level))

    if _is_duplicate(report.dustbin_id, overflow):
        return JSONResponse(content={
            "status": "merged",
            "dustbin_id": report.dustbin_id,
            "message": f"Report merged with recent submission for {report.dustbin_id}.",
        })

    dustbin = get_dustbin(report.dustbin_id)
    now_iso = datetime.now().isoformat()

    # Extract Auth0 user_sub from JWT if present
    user_sub = _decode_jwt_sub(authorization)

    event = {
        "event_id": f"WR-{uuid.uuid4().hex[:8]}",
        "dustbin_id": report.dustbin_id,
        "ward_id": dustbin["ward_id"],
        "overflow_level": overflow,
        "timestamp": now_iso,
        "source": "citizen",
        "user_sub": user_sub,
        "reporter_name": report.reporter_name or "Anonymous",
        "reporter_upi": report.reporter_upi or "",
    }

    # Dual write: file (for Pathway) + DB (for persistence)
    filename = _write_event(WASTE_REPORT_DIR, "waste", event)
    print(f"[API] Confirmed waste report: {filename}")
    try:
        insert_event("waste", event)
    except Exception as e:
        print(f"[DB] Waste event write failed: {e}")

    # Issue pending reward for ALL users (anonymous grouped as 'Selfie Heroes')
    reward_points = 0
    reward_user_sub = user_sub or "anonymous_selfie_hero"
    reward_name = report.reporter_name or ("Anonymous" if user_sub else "Selfie Heroes")

    try:
        reward = insert_pending_reward(
            event_id=event["event_id"],
            user_sub=reward_user_sub,
            reporter_name=reward_name,
            reporter_upi=report.reporter_upi or "",
            ward_id=dustbin["ward_id"],
            dustbin_id=report.dustbin_id,
            overflow_level=overflow,
            reported_at=now_iso,
        )
        reward_points = reward["points"]
    except Exception as e:
        print(f"[Rewards] Failed to insert pending reward: {e}")

    return JSONResponse(content={
        "status": "accepted",
        "event_id": event["event_id"],
        "dustbin_id": report.dustbin_id,
        "street": dustbin["street"],
        "file": filename,
        "overflow_level": overflow,
        "reward_points": reward_points,
        "message": f"Report for {report.dustbin_id} ({dustbin['street']}) accepted.",
    })


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN ENDPOINTS (require HMAC token)
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/report/road-issue")
@limiter.limit("20/minute")
async def report_road_issue(
    request: Request,
    report: RoadIssueReport,
    authorization: Optional[str] = Header(None),
):
    """Admin: Report road issue between two dustbins."""
    if not _check_admin_token(authorization):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

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
    try:
        insert_event("road", event)
    except Exception as e:
        print(f"[DB] Road event write failed: {e}")

    return JSONResponse(content={
        "status": "accepted",
        "event_id": event["event_id"],
        "from_dustbin": report.from_dustbin,
        "to_dustbin": report.to_dustbin,
        "file": filename,
        "message": f"Road issue ({report.issue_type}) reported.",
    })


@app.post("/api/demo/simulate-crisis")
@limiter.limit("3/minute")
async def simulate_crisis(request: Request, authorization: Optional[str] = Header(None)):
    """Demo Mode: Injects synthetic reports to trigger escalation."""
    if not _check_admin_token(authorization):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    w12_bins = [k for k, v in DUSTBINS.items() if v["ward_id"] == "W12"]
    if len(w12_bins) < 2:
        w12_bins = list(DUSTBINS.keys())[:2]

    target_bin_1 = w12_bins[0]
    target_bin_2 = w12_bins[1] if len(w12_bins) > 1 else w12_bins[0]
    target_ward = DUSTBINS[target_bin_1]["ward_id"]

    for _ in range(6):
        event = {
            "event_id": f"WR-DEMO-{uuid.uuid4().hex[:6]}",
            "dustbin_id": target_bin_1,
            "ward_id": target_ward,
            "overflow_level": 5,
            "timestamp": datetime.now().isoformat(),
            "source": "demo_bot",
        }
        _write_event(WASTE_REPORT_DIR, "waste", event)
        try:
            insert_event("waste", event)
        except Exception as e:
            print(f"[DB] Demo waste event write failed: {e}")

    road_event = {
        "event_id": f"RI-DEMO-{uuid.uuid4().hex[:6]}",
        "from_dustbin": target_bin_1,
        "to_dustbin": target_bin_2,
        "ward_id": target_ward,
        "issue_type": "waterlogging",
        "severity": 5,
        "timestamp": datetime.now().isoformat(),
        "source": "demo_bot",
    }
    _write_event(ROAD_REPORT_DIR, "road", road_event)
    try:
        insert_event("road", road_event)
    except Exception as e:
        print(f"[DB] Demo road event write failed: {e}")

    return JSONResponse(content={
        "status": "success",
        "message": f"CRISIS SIMULATION INJECTED at {target_bin_1} ({target_ward}).",
    })


@app.post("/api/van/collection")
@limiter.limit("30/minute")
async def report_van_collection(
    request: Request,
    report: VanCollectionReport,
    authorization: Optional[str] = Header(None),
):
    """Admin: Van confirmed collection at a dustbin."""
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
    try:
        insert_event("van", event)
    except Exception as e:
        print(f"[DB] Van event write failed: {e}")

    _last_report.pop(report.dustbin_id, None)

    # Resolve pending citizen rewards for this dustbin
    try:
        resolved = resolve_rewards_for_dustbin(report.dustbin_id)
        if resolved:
            print(f"  [Rewards] Resolved {resolved} pending reward(s) for {report.dustbin_id}")
    except Exception as e:
        print(f"[Rewards] resolve failed: {e}")

    return JSONResponse(content={
        "status": "accepted",
        "event_id": event["event_id"],
        "dustbin_id": report.dustbin_id,
        "file": filename,
        "message": f"Collection at {report.dustbin_id} ({dustbin['street']}) confirmed.",
    })


@app.get("/api/whatsapp-escalate/{dustbin_id}")
@limiter.limit("10/minute")
async def whatsapp_escalate(
    request: Request,
    dustbin_id: str,
    authorization: Optional[str] = Header(None),
):
    """Admin: Generate a WhatsApp escalation link for a dustbin."""
    if not _check_admin_token(authorization):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    if not validate_dustbin_id(dustbin_id):
        return JSONResponse(
            content={"error": f"Invalid dustbin ID: {dustbin_id}"},
            status_code=400,
        )

    dustbin = get_dustbin(dustbin_id)
    live_states = {ds.get("dustbin_id", ""): ds for ds in cached_state.get("dustbin_states", [])}
    live = live_states.get(dustbin_id, {})
    state = live.get("state", "Unknown")
    report_count = live.get("report_count", 0)

    message = (
        f"\U0001f6a8 InfraWatch Alert\n"
        f"Dustbin: {dustbin_id}\n"
        f"Location: {dustbin.get('street', 'Unknown')}\n"
        f"Ward: {dustbin.get('ward_id', 'Unknown')}\n"
        f"State: {state} | Reports: {report_count}\n"
        f"Action required immediately."
    )

    import urllib.parse
    wa_link = f"https://wa.me/?text={urllib.parse.quote(message)}"

    return JSONResponse(content={
        "wa_link": wa_link,
        "dustbin_id": dustbin_id,
        "state": state,
        "message": "WhatsApp escalation link generated.",
    })


@app.post("/api/van/clear-road")
@limiter.limit("20/minute")
async def report_road_cleared(
    request: Request,
    report: RoadClearReport,
    authorization: Optional[str] = Header(None),
):
    """Admin: Mark a road issue as cleared."""
    if not _check_admin_token(authorization):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    event = {
        "event_id": report.event_id,
        "timestamp": datetime.now().isoformat(),
        "source": "admin",
        "event_type": "road_cleared",
    }
    _write_event(ROAD_REPORT_DIR, "road", event)
    try:
        insert_event("road_cleared", event)
    except Exception as e:
        print(f"[DB] Road clear event write failed: {e}")

    return JSONResponse(content={
        "status": "success",
        "message": f"Road issue {report.event_id} marked as cleared.",
    })


# ═══════════════════════════════════════════════════════════════════════════
# ROUTE OPTIMIZATION ENDPOINT (VRP)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/route/optimize")
async def get_optimized_routes(ward_id: Optional[str] = None):
    """
    Vehicle Routing Problem solver.
    Returns optimal garbage truck collection routes based on current priority.

    Query params:
        ward_id (optional): Optimize for specific ward only
    """
    dustbin_states = cached_state.get("dustbin_states", [])

    if ward_id:
        if ward_id not in WARDS:
            return JSONResponse(
                content={"error": f"Unknown ward: {ward_id}"},
                status_code=400,
            )
        winfo = WARDS[ward_id]
        result = optimize_route(
            dustbin_states=dustbin_states,
            depot_lat=winfo["lat"],
            depot_lng=winfo["lng"],
            ward_id=ward_id,
        )
        result["ward_id"] = ward_id
        result["ward_name"] = winfo["name"]
        return JSONResponse(content={"route": result})

    # Optimize all wards
    results = optimize_all_wards(dustbin_states, WARDS)
    return JSONResponse(content={
        "routes": results,
        "total_wards": len(results),
        "timestamp": datetime.now().isoformat(),
    })


@app.get("/api/route/optimize/{ward_id}")
async def get_ward_route(ward_id: str):
    """Get optimized collection route for a specific ward."""
    if ward_id not in WARDS:
        return JSONResponse(
            content={"error": f"Unknown ward: {ward_id}"},
            status_code=400,
        )

    dustbin_states = cached_state.get("dustbin_states", [])
    winfo = WARDS[ward_id]
    result = optimize_route(
        dustbin_states=dustbin_states,
        depot_lat=winfo["lat"],
        depot_lng=winfo["lng"],
        ward_id=ward_id,
    )
    result["ward_id"] = ward_id
    result["ward_name"] = winfo["name"]
    return JSONResponse(content={"route": result})


# ═══════════════════════════════════════════════════════════════════════════
# AUTH TOKEN ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/auth/token")
@limiter.limit("5/minute")
async def get_auth_token(request: Request, authorization: Optional[str] = Header(None)):
    """Generate HMAC-signed auth token (requires legacy token for initial auth)."""
    if not _check_admin_token(authorization):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    token = generate_token("admin")
    return JSONResponse(content={
        "token": token,
        "expires_in": 86400,
        "message": "Use this token in Authorization: Bearer <token> header.",
    })


# ═══════════════════════════════════════════════════════════════════════════
# READ-ONLY ENDPOINTS (serve cached Pathway output -- NO computation)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health_check():
    """Production health check."""
    return JSONResponse(content={
        "status": "healthy",
        "version": "4.0",
        "timestamp": datetime.now().isoformat(),
        "engine": "active",
        "cache_entries": len(_last_report),
    })


@app.get("/api/forecast")
async def get_risk_forecast():
    """Predictive Risk Forecast: 3-day ward-level risk projection."""
    wx_key = os.getenv("WX_API_KEY", "")
    forecast_data = []

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "http://api.weatherapi.com/v1/forecast.json",
                params={"key": wx_key, "q": "Delhi", "days": 3, "aqi": "no"},
                timeout=8,
            )
            resp.raise_for_status()
            days = resp.json().get("forecast", {}).get("forecastday", [])
    except Exception:
        days = []

    ward_report_counts = {}
    for ds in cached_state.get("dustbin_states", []):
        wid = ds.get("ward_id", "")
        ward_report_counts[wid] = ward_report_counts.get(wid, 0) + ds.get("report_count", 0)

    for day_data in days:
        date = day_data.get("date", "")
        day_info = day_data.get("day", {})
        total_precip_mm = day_info.get("totalprecip_mm", 0)
        max_wind_kph = day_info.get("maxwind_kph", 0)
        condition = day_info.get("condition", {}).get("text", "Clear")

        rain_factor = min(1.0, total_precip_mm / 50.0)
        wind_factor = min(1.0, max_wind_kph / 80.0)
        weather_severity = round((rain_factor * 0.7 + wind_factor * 0.3), 2)

        ward_forecasts = []
        for wid, winfo in WARDS.items():
            current_reports = ward_report_counts.get(wid, 0)
            base_risk = min(1.0, current_reports / 10.0)
            predicted_risk = round(min(1.0, base_risk + weather_severity * 0.6), 2)
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
    """Full dashboard state -- cached from Pathway."""
    return JSONResponse(content=cached_state)


@app.get("/api/dustbins")
async def get_dustbins():
    """Return dustbin registry with live states."""
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
async def get_config(authorization: Optional[str] = Header(None)):
    """Ward and dustbin config for frontend map setup. Returns elevenlabs keys for authed users."""
    resp = {
        "wards": {k: {**v} for k, v in WARDS.items()},
        "dustbins": {k: {**v} for k, v in DUSTBINS.items()},
        "city_center": CITY_CENTER,
        "auth0": {
            "domain": os.getenv("AUTH0_DOMAIN", "dev-kklommsgij3qgkij.us.auth0.com"),
            "clientId": os.getenv("AUTH0_CLIENT_ID", "JUpaLQX0981B0A1FL4yQA7dFUHImqbPU"),
            "audience": os.getenv("AUTH0_AUDIENCE", "https://infrawatch-nexus-api"),
        },
    }
    # Return ElevenLabs keys for both guest and authenticated users
    resp["elevenlabs_key"] = os.getenv("ELEVENLABS_API_KEY", "")
    resp["elevenlabs_voice_id"] = os.getenv("ELEVENLABS_VOICE_ID", "")
    return JSONResponse(content=resp)


@app.get("/api/priority")
async def get_priority():
    """Priority queue -- from Pathway output."""
    return JSONResponse(content={
        "priority_queue": cached_state.get("priority_queue", []),
        "timestamp": cached_state.get("timestamp"),
    })


@app.get("/api/weather")
async def get_weather():
    """Current weather -- from Pathway output."""
    return JSONResponse(content={
        "rainfall_mm_hr": cached_state.get("rainfall_mm_hr", 0),
        "timestamp": cached_state.get("timestamp"),
    })


# ═══════════════════════════════════════════════════════════════════════════
# CIVIC REWARD SYSTEM ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/leaderboard")
async def get_leaderboard_endpoint(month: Optional[str] = None):
    """Public leaderboard: top 10 reporters this month by points. No UPI/sub exposed."""
    try:
        leaders = get_leaderboard(month)
    except Exception as e:
        leaders = []
    if not leaders:
        return JSONResponse(content={
            "leaderboard": [],
            "month": month or datetime.now().strftime("%Y-%m"),
            "message": "No resolved reports this month yet",
        })
    return JSONResponse(content={
        "leaderboard": leaders,
        "month": month or datetime.now().strftime("%Y-%m"),
        "total": len(leaders),
    })


@app.get("/api/rewards/my")
@limiter.limit("30/minute")
async def get_my_rewards(request: Request, authorization: Optional[str] = Header(None)):
    """Auth0: Personal reward summary and history for authenticated citizen."""
    user_sub = _decode_jwt_sub(authorization)
    if not user_sub:
        return JSONResponse(content={"error": "Authentication required"}, status_code=401)
    try:
        summary = get_user_reward_summary(user_sub)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    return JSONResponse(content=summary)


@app.post("/api/rewards/export")
@limiter.limit("5/minute")
async def export_rewards_csv(request: Request, authorization: Optional[str] = Header(None)):
    """Admin: Export all resolved rewards as CSV and mark as exported (payment queue)."""
    if not _check_admin_token(authorization):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)
    try:
        rows = export_pending_rewards()
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

    if not rows:
        return JSONResponse(content={"message": "No pending rewards to export", "count": 0})

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["reporter_name", "reporter_upi", "total_rupees", "report_count", "ward_id", "generated_at"]
    )
    writer.writeheader()
    writer.writerows(rows)
    csv_str = output.getvalue()

    from fastapi.responses import Response
    return Response(
        content=csv_str,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=infrawatch_rewards_export.csv"},
    )


# ═══════════════════════════════════════════════════════════════════════════
# AI CHATBOT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/chat")
@limiter.limit("10/minute")
async def chat_with_ai(
    request: Request,
    body: ChatRequest,
    authorization: Optional[str] = Header(None),
):
    """
    AI Chatbot: citizen queries answered by Gemini using personal report history
    and live Pathway cached_state. Anonymous users get city-level answers only.
    """
    # Prefer user_sub from JWT over body field (body allows frontend to send it directly)
    user_sub = _decode_jwt_sub(authorization) or body.user_sub

    user_reports = []
    if user_sub:
        try:
            user_reports = get_user_reports(user_sub, limit=20)
        except Exception:
            user_reports = []

    try:
        result = answer_citizen_query(
            message=body.message,
            user_reports=user_reports,
            cached_state=cached_state,
        )
    except Exception as e:
        result = {
            "answer": f"I'm having trouble processing your request. City waste index: {cached_state.get('city_waste_index', 0)}/100.",
            "speak": "अभी जवाब देने में समस्या हो रही है। कृपया दोबारा कोशिश करें।",
        }

    # Map the AI advisor 'answer' natively to frontend's expected 'reply' payload
    return JSONResponse(content={
        "reply": result.get("answer", "No reply generated."),
        "speak": result.get("speak", "")
    })


@app.get("/api/my-reports")
@limiter.limit("30/minute")
async def get_my_reports(request: Request, authorization: Optional[str] = Header(None)):
    """Auth0: Get last 20 reports by this user, enriched with live dustbin state."""
    user_sub = _decode_jwt_sub(authorization)
    if not user_sub:
        return JSONResponse(content={"error": "Authentication required"}, status_code=401)

    try:
        reports = get_user_reports(user_sub, limit=20)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

    # Enrich with live state from Pathway
    live_states = {ds.get("dustbin_id", ""): ds for ds in cached_state.get("dustbin_states", [])}
    enriched = []
    for r in reports:
        did = r.get("dustbin_id", "")
        live = live_states.get(did, {})
        enriched.append({
            **r,
            "current_state": live.get("state", "Unknown"),
            "current_report_count": live.get("report_count", 0),
        })

    return JSONResponse(content={
        "reports": enriched,
        "total": len(enriched),
        "user_sub": user_sub,
    })




# ═══════════════════════════════════════════════════════════════════════════
# PATHWAY OUTPUT READER (background thread)
# ═══════════════════════════════════════════════════════════════════════════

def _cache_updater():
    """Background thread: re-read Pathway atomic output every 3 seconds."""
    global cached_state
    while True:
        try:
            snapshot = read_dashboard_snapshot(PW_OUTPUT_DIR)
            if snapshot:
                cached_state = snapshot
        except Exception as e:
            print(f"[Cache] Error: {e}")
        time.sleep(3)


# ═══════════════════════════════════════════════════════════════════════════
# WEBSOCKET (content-hash diffing -- Phase 5)
# ═══════════════════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_stream(websocket: WebSocket):
    """
    Push state to connected clients. Full state on connect, then diffs.
    Accepts optional token via query param: /ws?token=<admin_token>
    Unauthenticated clients get read-only access (no admin data).
    """
    # Optional token auth via query params
    token = websocket.query_params.get("token", "")
    is_admin = bool(token and verify_token(token))

    await websocket.accept()
    ws_clients.add(websocket)
    try:
        # Send full state immediately on connect
        state_to_send = dict(cached_state)
        state_to_send["ws_authenticated"] = is_admin
        await websocket.send_json(state_to_send)
        while True:
            # Keep connection alive -- actual updates via broadcast loop
            await asyncio.wait_for(websocket.receive_text(), timeout=30)
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception:
        pass
    finally:
        ws_clients.discard(websocket)


async def _broadcast_if_changed():
    """Only broadcast when state actually changes."""
    global _last_broadcast_hash
    state_json = json.dumps(cached_state, sort_keys=True)
    current_hash = hashlib.md5(state_json.encode()).hexdigest()

    if current_hash == _last_broadcast_hash:
        return

    _last_broadcast_hash = current_hash

    dead = set()
    for ws in ws_clients.copy():
        try:
            await ws.send_json(cached_state)
        except Exception:
            dead.add(ws)
    ws_clients.difference_update(dead)


async def _ws_broadcast_loop():
    """Single loop: checks for state changes and broadcasts to all."""
    while True:
        try:
            await _broadcast_if_changed()
        except Exception:
            pass
        await asyncio.sleep(2)


# ═══════════════════════════════════════════════════════════════════════════
# STATIC FILES & PAGE SERVING
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/")
async def serve_citizen_portal():
    """Serve Citizens' Portal."""
    filepath = os.path.join(FRONTEND_DIR, "citizen.html")
    with open(filepath, "r", encoding="utf-8") as f:
        return HTMLResponse(
            content=f.read(),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )


@app.get("/report")
async def serve_citizen_portal_report(bin: Optional[str] = None):
    """Serve Citizens' Portal with QR pre-fill injected."""
    filepath = os.path.join(FRONTEND_DIR, "citizen.html")
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()
    
    # Inject the bin ID as a global JS variable so the frontend skips to the Report UI
    if bin:
        # Sanitize bin input slightly to prevent XSS breakout
        safe_bin = "".join(c for c in bin if c.isalnum() or c in "-_")
        injection = f'<script>window._QR_PREFILL_BIN = "{safe_bin}";</script>'
        html = html.replace("</head>", f"{injection}\n</head>")

    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/admin")
async def serve_admin_portal():
    """Serve Admin Portal."""
    filepath = os.path.join(FRONTEND_DIR, "admin.html")
    with open(filepath, "r", encoding="utf-8") as f:
        return HTMLResponse(
            content=f.read(),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Silence browser 404s for favicon"""
    return Response(status_code=204)


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ═══════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    print("=" * 55)
    print("  InfraWatch Nexus -- API Server v4.0 (Transport Only)")
    print("=" * 55)
    print(f"  Citizens Portal : http://localhost:{SERVER_PORT}/")
    print(f"  Admin Portal    : http://localhost:{SERVER_PORT}/admin")
    print(f"  Dustbins loaded : {len(DUSTBINS)}")
    print(f"  Route optimizer : /api/route/optimize")
    print(f"  Rate limiting   : Active (slowapi)")
    print(f"  Auth            : HMAC-SHA256 tokens")
    print(f"  Pathway output  : {PW_OUTPUT_DIR}")

    # Init database
    try:
        init_db()
        print("  SQLite DB       : Initialized (WAL mode)")
    except Exception as e:
        print(f"  SQLite DB       : Error: {e}")

    _rebuild_dedup_cache()
    print(f"  Dedup cache     : {len(_last_report)} recent entries")

    # Start background cache updater
    t = threading.Thread(target=_cache_updater, daemon=True)
    t.start()
    print("  Cache updater   : Started (3s interval)")

    # Start WebSocket broadcast loop
    asyncio.create_task(_ws_broadcast_loop())
    print("  WS broadcast    : Started (hash-diff mode)")

    # Start keep-alive self-ping
    def _keep_alive():
        import requests as req
        port = int(os.environ.get("PORT", 8000))
        url = f"http://localhost:{port}/health"
        while True:
            time.sleep(780)
            try:
                req.get(url, timeout=5)
            except Exception:
                pass

    ka = threading.Thread(target=_keep_alive, daemon=True)
    ka.start()
    print("  Keep-alive      : Started (13min interval)")

    # Start event file cleanup thread (hourly, deletes >48h old)
    def _event_file_cleanup():
        from engine.database import cleanup_old_events
        while True:
            time.sleep(3600)  # Every hour
            try:
                # Cleanup DB events
                deleted_db = cleanup_old_events(hours=48)
                # Cleanup old event files
                deleted_files = 0
                cutoff = time.time() - (48 * 3600)
                for report_dir in [WASTE_REPORT_DIR, ROAD_REPORT_DIR, VAN_LOG_DIR]:
                    try:
                        for fname in os.listdir(report_dir):
                            fpath = os.path.join(report_dir, fname)
                            if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                                os.remove(fpath)
                                deleted_files += 1
                    except Exception:
                        continue
                if deleted_db or deleted_files:
                    print(f"  [Cleanup] Removed {deleted_db} DB rows, {deleted_files} files")
            except Exception as e:
                print(f"  [Cleanup] Error: {e}")

    cleanup = threading.Thread(target=_event_file_cleanup, daemon=True)
    cleanup.start()
    print("  Event cleanup   : Started (hourly, 48h expiry)")


# ═══════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("api.server:app", host="0.0.0.0", port=port, reload=False)
