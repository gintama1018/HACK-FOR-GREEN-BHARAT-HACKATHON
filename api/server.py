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
from fastapi.responses import HTMLResponse, JSONResponse, Response
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

ADMIN_TOKEN          = os.getenv("ADMIN_TOKEN", "INFRAWATCH_ADMIN_2026")
GEMINI_KEY           = os.getenv("GEMINI_API_KEY", "")
ELEVENLABS_KEY       = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID  = os.getenv("ELEVENLABS_VOICE_ID", "56k72tYpS6hbRADdszYg")
VULTR_ACCESS_KEY     = os.getenv("VULTR_ACCESS_KEY", "")
VULTR_SECRET_KEY     = os.getenv("VULTR_SECRET_KEY", "")
VULTR_BUCKET         = os.getenv("VULTR_BUCKET", "infrawatch-evidence")
VULTR_ENDPOINT       = os.getenv("VULTR_ENDPOINT", "https://ewr1.vultrobjects.com")
AUTH0_DOMAIN         = os.getenv("AUTH0_DOMAIN", "")
AUTH0_CLIENT_ID      = os.getenv("AUTH0_CLIENT_ID", "")
AUTH0_AUDIENCE       = os.getenv("AUTH0_AUDIENCE", "https://infrawatch-nexus-api")
AUTH0_ALGORITHMS     = ["RS256"]

DUSTBIN_PATTERN = re.compile(r"MCD-W\d{2}-\d{3}")

for d in [WASTE_REPORT_DIR, ROAD_REPORT_DIR, VAN_LOG_DIR, WEATHER_DIR, PW_OUTPUT_DIR]:
    os.makedirs(d, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════════
# AUTH0 JWT VALIDATION
# ═══════════════════════════════════════════════════════════════════════════
_jwks_cache: Optional[dict] = None
_jwks_fetched_at: float = 0.0


def _get_jwks() -> dict:
    """Fetch Auth0 JWKS (public keys). Cached for 10 minutes."""
    global _jwks_cache, _jwks_fetched_at
    import requests as _req
    if _jwks_cache and (time.time() - _jwks_fetched_at) < 600:
        return _jwks_cache
    if not AUTH0_DOMAIN:
        return {}
    try:
        resp = _req.get(f"https://{AUTH0_DOMAIN}/.well-known/jwks.json", timeout=8)
        _jwks_cache = resp.json()
        _jwks_fetched_at = time.time()
        return _jwks_cache
    except Exception as e:
        print(f"[Auth0] JWKS fetch error: {e}")
        return _jwks_cache or {}


def verify_auth0_token(token: str) -> Optional[dict]:
    """Validate an Auth0 JWT. Returns decoded payload or None if invalid."""
    if not AUTH0_DOMAIN or not token:
        return None
    try:
        from jose import jwt as jose_jwt, JWTError
        jwks = _get_jwks()
        if not jwks:
            return None
        unverified_header = jose_jwt.get_unverified_header(token)
        rsa_key = {}
        for key in jwks.get("keys", []):
            if key["kid"] == unverified_header.get("kid"):
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n":   key["n"],
                    "e":   key["e"],
                }
                break
        if not rsa_key:
            return None
        payload = jose_jwt.decode(
            token, rsa_key,
            algorithms=AUTH0_ALGORITHMS,
            audience=AUTH0_AUDIENCE,
            issuer=f"https://{AUTH0_DOMAIN}/",
        )
        return payload
    except Exception as e:
        print(f"[Auth0] Token invalid: {e}")
        return None


def _extract_user_id(authorization: Optional[str]) -> Optional[str]:
    """Extract user_id (sub claim) from Bearer token, or None if missing/invalid."""
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        return None
    payload = verify_auth0_token(token)
    return payload.get("sub") if payload else None

# ═══════════════════════════════════════════════════════════════════════════
# USER REPORTS INDEX  — rebuilt from flat files; updated on each new report
# ═══════════════════════════════════════════════════════════════════════════
# user_reports[user_id] = [ {event_id, dustbin_id, overflow_level, timestamp, status}, ... ]
user_reports: dict = {}


def _add_to_user_reports(user_id: str, event: dict):
    """Append an event to in-memory user_reports index."""
    user_reports.setdefault(user_id, []).append({
        "event_id":      event.get("event_id", ""),
        "dustbin_id":    event.get("dustbin_id", ""),
        "overflow_level": event.get("overflow_level", 0),
        "timestamp":     event.get("timestamp", ""),
        "status":        "Pending",
    })


# ── Vultr Object Storage ──────────────────────────────────────────────────
def _upload_to_vultr(image_bytes: bytes, content_type: str, filename: str) -> Optional[str]:
    """Upload evidence photo to Vultr Object Storage. Returns public URL or None."""
    if not VULTR_ACCESS_KEY or not VULTR_SECRET_KEY:
        return None
    try:
        import boto3
        from botocore.client import Config
        s3 = boto3.client(
            's3',
            endpoint_url=VULTR_ENDPOINT,
            aws_access_key_id=VULTR_ACCESS_KEY,
            aws_secret_access_key=VULTR_SECRET_KEY,
            config=Config(signature_version='s3v4'),
        )
        s3.put_object(
            Bucket=VULTR_BUCKET,
            Key=f"evidence/{filename}",
            Body=image_bytes,
            ContentType=content_type,
            ACL='public-read',
        )
        url = f"{VULTR_ENDPOINT}/{VULTR_BUCKET}/evidence/{filename}"
        print(f"[Vultr] Uploaded: {url}")
        return url
    except Exception as e:
        print(f"[Vultr] Upload failed: {e}")
        return None


def _rebuild_user_reports():
    """On startup, scan waste report files and rebuild user_reports index."""
    try:
        for fname in sorted(os.listdir(WASTE_REPORT_DIR)):
            fpath = os.path.join(WASTE_REPORT_DIR, fname)
            try:
                with open(fpath, "r") as f:
                    events = json.load(f)
                if isinstance(events, list):
                    for e in events:
                        uid = e.get("user_id")
                        if uid:
                            _add_to_user_reports(uid, e)
            except Exception:
                continue
    except FileNotFoundError:
        pass


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
    photo_url: Optional[str] = None  # Vultr Object Storage URL from detect step

class RoadIssueReport(BaseModel):
    from_dustbin: str
    to_dustbin: str
    issue_type: str   # pothole / waterlogging / crack / construction
    severity: int     # 1–5

class VanCollectionReport(BaseModel):
    dustbin_id: str

class RoadClearReport(BaseModel):
    event_id: str

class ChatRequest(BaseModel):
    message: str
    history: list = []

class TTSRequest(BaseModel):
    text: str


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
    """Strict admin token check. Allows demotoken123 for demo purposes."""
    if not authorization:
        return False
    token = authorization.replace("Bearer ", "").strip()
    return token in [ADMIN_TOKEN, "demotoken123"]


# ═══════════════════════════════════════════════════════════════════════════
# CITIZEN ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/report/dustbin/detect")
async def detect_dustbin_from_photo(file: UploadFile = File(...), authorization: Optional[str] = Header(None)):
    """
    Step 1 of citizen flow: Upload photo → Gemini Vision → extract dustbin ID.
    Also uploads evidence photo to Vultr Object Storage (if configured).
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
                # Upload evidence photo to Vultr Object Storage
                user_id = _extract_user_id(authorization)
                uid_tag = user_id.split('|')[-1][:8] if user_id else "anon"
                photo_filename = f"{candidate}_{uuid.uuid4().hex[:8]}_{uid_tag}.jpg"
                photo_url = _upload_to_vultr(image_bytes, file.content_type or "image/jpeg", photo_filename)
                return JSONResponse(content={
                    "detected_id": candidate,
                    "fallback": False,
                    "street": dustbin["street"],
                    "ward_id": dustbin["ward_id"],
                    "photo_url": photo_url,
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
async def confirm_dustbin_report(report: DustbinConfirmReport, authorization: Optional[str] = Header(None)):
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

    # Extract user identity early (needed for both merged and accepted paths)
    dustbin = get_dustbin(report.dustbin_id)
    user_id = _extract_user_id(authorization)
    print(f"[Report] dustbin={report.dustbin_id} auth_header={bool(authorization)} user_id={user_id}")

    # Dedup check
    if _is_duplicate(report.dustbin_id, overflow):
        # Still credit the user even if the event is merged
        if user_id:
            merged_event = {
                "event_id": f"WR-merged-{uuid.uuid4().hex[:6]}",
                "dustbin_id": report.dustbin_id,
                "ward_id": dustbin["ward_id"],
                "overflow_level": overflow,
                "timestamp": datetime.now().isoformat(),
                "source": "citizen",
                "user_id": user_id,
            }
            _add_to_user_reports(user_id, merged_event)
        return JSONResponse(content={
            "status": "merged",
            "dustbin_id": report.dustbin_id,
            "message": f"Report merged with recent submission for {report.dustbin_id}.",
        })

    # Build strict event
    event = {
        "event_id": f"WR-{uuid.uuid4().hex[:8]}",
        "dustbin_id": report.dustbin_id,
        "ward_id": dustbin["ward_id"],
        "overflow_level": overflow,
        "timestamp": datetime.now().isoformat(),
        "source": "citizen",
    }
    if user_id:
        event["user_id"] = user_id
    if report.photo_url:
        event["photo_url"] = report.photo_url

    filename = _write_event(WASTE_REPORT_DIR, "waste", event)

    # Update in-memory user index
    if user_id:
        _add_to_user_reports(user_id, event)

    return JSONResponse(content={
        "status": "accepted",
        "event_id": event["event_id"],
        "dustbin_id": report.dustbin_id,
        "street": dustbin["street"],
        "file": filename,
        "photo_url": report.photo_url,
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
    
    # Target Ward W12 specifically to create a localized heat cluster
    # Find active dustbins in W12
    w12_bins = [k for k, v in DUSTBINS.items() if v["ward_id"] == "W12"]
    if len(w12_bins) < 2:
        # Fallback to whatever exists
        w12_bins = list(DUSTBINS.keys())[:2]
        
    target_bin_1 = w12_bins[0]
    target_bin_2 = w12_bins[1]
    target_ward = DUSTBINS[target_bin_1]["ward_id"]
    
    demo_events = []
    
    # Generate 6 rapid reports for dustbin 1 (Triggers 'Escalated' or 'Critical')
    for _ in range(6):
        event = {
            "event_id": f"WR-DEMO-{uuid.uuid4().hex[:6]}",
            "dustbin_id": target_bin_1,
            "ward_id": target_ward,
            "overflow_level": 5,
            "timestamp": datetime.now().isoformat(),
            "source": "demo_bot"
        }
        _write_event(WASTE_REPORT_DIR, "waste", event)
        demo_events.append(event)
        
    # Generate a massive road issue nearby
    road_event = {
        "event_id": f"RI-DEMO-{uuid.uuid4().hex[:6]}",
        "from_dustbin": target_bin_1,
        "to_dustbin": target_bin_2,
        "ward_id": target_ward,
        "issue_type": "waterlogging",
        "severity": 5,
        "timestamp": datetime.now().isoformat(),
        "source": "demo_bot"
    }
    _write_event(ROAD_REPORT_DIR, "road", road_event)
    
    return JSONResponse(content={
        "status": "success",
        "message": f"🚨 CRISIS SIMULATION INJECTED at {target_bin_1} ({target_ward})."
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


@app.post("/api/van/clear-road")
async def report_road_cleared(
    report: RoadClearReport,
    authorization: Optional[str] = Header(None),
):
    """Admin: Mark a road issue as cleared. Requires auth token."""
    if not _check_admin_token(authorization):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    event = {
        "event_id": report.event_id,
        "timestamp": datetime.now().isoformat(),
        "source": "admin",
        "event_type": "road_cleared",
    }

    # Write a clearing event to the road logs
    _write_event(ROAD_REPORT_DIR, "road", event)

    return JSONResponse(content={
        "status": "success",
        "message": f"Road issue {report.event_id} marked as cleared."
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
# AI CITIZEN CHAT — Gemini + ElevenLabs Hindi TTS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/auth0-config")
async def get_auth0_config():
    """Return Auth0 public config for frontend SDK initialization."""
    return JSONResponse(content={
        "domain":   AUTH0_DOMAIN,
        "clientId": os.getenv("AUTH0_CLIENT_ID", ""),
        "audience": AUTH0_AUDIENCE,
    })


@app.get("/api/debug-auth")
async def debug_auth(authorization: Optional[str] = Header(None)):
    """Debug: show what user_id the server sees from the Bearer token."""
    user_id = _extract_user_id(authorization)
    has_token = bool(authorization and authorization.startswith("Bearer "))
    return JSONResponse(content={
        "has_token": has_token,
        "user_id": user_id,
        "reports_count": len(user_reports.get(user_id, [])) if user_id else 0,
        "all_users_in_index": list(user_reports.keys()),
    })


@app.get("/api/my-reports")
async def get_my_reports(authorization: Optional[str] = Header(None)):
    """Return this user's complaint history (requires Auth0 Bearer token)."""
    user_id = _extract_user_id(authorization)
    if not user_id:
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)
    reports = user_reports.get(user_id, [])
    return JSONResponse(content={"user_id": user_id, "reports": reports, "count": len(reports)})


@app.post("/api/chat")
async def ai_chat(payload: ChatRequest, authorization: Optional[str] = Header(None)):
    """Citizen AI chatbot: Gemini 2.5 Flash with live civic data context. Responds in Hindi."""
    user_id = _extract_user_id(authorization)
    if not GEMINI_KEY:
        return JSONResponse(content={"reply": "AI सहायक अभी उपलब्ध नहीं है। कृपया बाद में प्रयास करें।"})

    import requests as req

    # ── Build user-specific context if logged in ──────────────────────────
    my_reports_context = ""
    if user_id:
        my_reps = user_reports.get(user_id, [])
        if my_reps:
            rep_lines = []
            for r in my_reps[-5:]:  # last 5 reports
                ts = r.get("timestamp", "")[:16].replace("T", " ")
                did = r.get("dustbin_id", "?")
                street = DUSTBINS.get(did, {}).get("street", did)
                ovf = r.get("overflow_level", "?")
                eid = r.get("event_id", "?")
                rep_lines.append(f"  - {eid}: {street} (ओवरफ्लो {ovf}/5) — {ts}")
            my_reports_context = (
                f"\nइस नागरिक की अपनी शिकायतें ({len(my_reps)} कुल, अंतिम 5):\n"
                + "\n".join(rep_lines)
                + "\n"
            )
        else:
            my_reports_context = "\nइस नागरिक ने अभी तक कोई शिकायत दर्ज नहीं की है।\n"

    # ── Build live data context from Pathway cached state ──────────────────
    ward_risks      = cached_state.get("ward_risks", [])
    dustbin_states  = cached_state.get("dustbin_states", [])
    road_issues     = cached_state.get("road_issues", [])
    priority_queue  = cached_state.get("priority_queue", [])
    rainfall        = cached_state.get("rainfall_mm_hr", 0.0)
    waste_index     = cached_state.get("city_waste_index", 0.0)

    critical_bins = [d for d in dustbin_states if d.get("state") in ("Critical", "Escalated")]
    top_wards     = sorted(ward_risks, key=lambda w: w.get("risk_score", 0), reverse=True)[:5]
    active_roads  = [r for r in road_issues if r.get("status") != "cleared"][:5]

    def ward_name(wid):
        return WARDS.get(wid, {}).get("name", wid)

    bins_summary = "\n".join(
        f"  - {b.get('dustbin_id','?')} ({b.get('state','')}) — {DUSTBINS.get(b.get('dustbin_id',''), {}).get('street', 'Ward '+b.get('ward_id',''))}"  # noqa: E501
        for b in critical_bins[:6]
    ) or "  कोई क्रिटिकल डस्टबिन नहीं"

    wards_summary = ", ".join(
        f"{ward_name(w.get('ward_id',''))} (जोखिम: {w.get('risk_score', 0):.0%})"
        for w in top_wards[:4]
    ) or "सभी वार्ड सामान्य"

    roads_summary = "\n".join(
        f"  - {r.get('issue_type','?')} गंभीरता {r.get('severity',0)}/5, {ward_name(r.get('ward_id',''))}"
        for r in active_roads[:4]
    ) or "  कोई सक्रिय सड़क समस्या नहीं"

    live_context = (
        f"LIVE DATA ({datetime.now().strftime('%d %b %Y, %H:%M IST')}):\n"
        f"- शहर का कचरा सूचकांक: {waste_index:.0%}\n"
        f"- वर्तमान वर्षा: {rainfall:.1f} mm/hr\n"
        f"- क्रिटिकल/एस्केलेटेड डस्टबिन ({len(critical_bins)}): \n{bins_summary}\n"
        f"- शीर्ष जोखिम वार्ड: {wards_summary}\n"
        f"- सक्रिय सड़क समस्याएं ({len(active_roads)}):\n{roads_summary}\n"
        f"- प्राथमिकता कतार में: {len(priority_queue)} कार्य लंबित"
    )

    # ── Conversation history handling ─────────────────────────────────────
    history_text = ""
    for msg in payload.history[-6:]:
        speaker = "नागरिक" if msg.get("role") == "user" else "NEXUS"
        history_text += f"\n{speaker}: {msg.get('text', '')}"

    # ── System prompt ──────────────────────────────────────────────────────
    logged_in_note = "(यह नागरिक लॉग इन है — आप उनकी व्यक्तिगत शिकायतों का उत्तर दे सकते हैं)" if user_id else "(यह नागरिक लॉग इन नहीं है — केवल सामान्य जानकारी दें)"
    full_prompt = (
        "आप NEXUS हैं — दिल्ली नगर निगम के स्मार्ट अपशिष्ट प्रबंधन सिस्टम (NUWMS) के AI नागरिक सहायक।\n"
        "आप नागरिकों को कचरा संग्रह की स्थिति, डस्टबिन की स्थिति, सड़क की समस्याओं और वार्ड जोखिम के बारे में \n"
        "सटीक, उपयोगी जानकारी देते हैं। हमेशा हिंदी में उत्तर दें। संक्षिप्त रहें (2-4 वाक्य)।\n"
        f"{logged_in_note}\n"
        "तकनीकी IDs (जैसे MCD-W06-003) को आम भाषा में समझाएं।\n"
        "'मेरी शिकायत' या 'मेरी रिपोर्ट' जैसे प्रश्नों का उत्तर नीचे दी गई व्यक्तिगत शिकायत सूची से दें।\n\n"
        f"{live_context}"
        f"{my_reports_context}\n"
        f"पिछली बातचीत:{history_text}\n\n"
        f"नागरिक का प्रश्न: {payload.message}"
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    body = {"contents": [{"parts": [{"text": full_prompt}]}]}

    try:
        resp = req.post(url, headers={"Content-Type": "application/json"}, json=body, timeout=20)
        resp.raise_for_status()
        reply = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        return JSONResponse(content={"reply": reply})
    except Exception as e:
        print(f"[AI Chat] Gemini error: {e}")
        return JSONResponse(content={"reply": "माफ़ करें, AI सेवा में अस्थायी समस्या है। कृपया फिर से कोशिश करें।"})


@app.post("/api/tts")
async def text_to_speech(payload: TTSRequest):
    """ElevenLabs Hindi TTS proxy. Returns audio/mpeg stream."""
    from fastapi.responses import Response as FastAPIResponse

    # Sanitise input
    text = payload.text.strip()[:800]   # cap at 800 chars to avoid cost spikes
    if not text:
        return JSONResponse(content={"error": "Empty text"}, status_code=400)

    if not ELEVENLABS_KEY:
        return JSONResponse(content={"error": "TTS not configured"}, status_code=503)

    import requests as req
    try:
        resp = req.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
            headers={
                "xi-api-key": ELEVENLABS_KEY,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.55, "similarity_boost": 0.75},
            },
            timeout=25,
        )
        if resp.status_code == 200:
            return FastAPIResponse(content=resp.content, media_type="audio/mpeg")
        print(f"[TTS] ElevenLabs error {resp.status_code}: {resp.text[:200]}")
        return JSONResponse(content={"error": "TTS provider error"}, status_code=502)
    except Exception as e:
        print(f"[TTS] Request failed: {e}")
        return JSONResponse(content={"error": "TTS request failed"}, status_code=500)


@app.get("/api/tts-stream")
async def tts_stream_get(text: str):
    """Streaming TTS GET — browser starts playing as first audio chunk arrives (low latency)."""
    from fastapi.responses import StreamingResponse
    import requests as req

    clean = text.strip()[:600]
    if not clean or not ELEVENLABS_KEY:
        from fastapi.responses import Response as _R
        return _R(status_code=204)  # no TTS key — silently skip, browser audio.onerror handles it

    def _gen():
        try:
            resp = req.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream",
                headers={"xi-api-key": ELEVENLABS_KEY, "Content-Type": "application/json"},
                json={
                    "text": clean,
                    "model_id": "eleven_turbo_v2_5",   # ultra-low latency multilingual
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
                stream=True,
                timeout=30,
            )
            if resp.status_code == 200:
                for chunk in resp.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
            else:
                print(f"[TTS Stream] ElevenLabs {resp.status_code}")
        except Exception as e:
            print(f"[TTS Stream] Error: {e}")

    return StreamingResponse(
        _gen(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Return inline SVG favicon — eliminates 404 noise in server logs."""
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><text y="26" font-size="28">🌱</text></svg>'
    return Response(content=svg.encode(), media_type="image/svg+xml")


@app.get("/")
async def serve_citizen_portal():
    """Serve Citizens\' Portal."""
    filepath = os.path.join(FRONTEND_DIR, "citizen.html")
    with open(filepath, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/report")
async def serve_qr_report(bin: Optional[str] = None):
    """
    QR-code landing page — /report?bin=MCD-DL-1000
    Serves the citizen portal with a ?bin= param that JS reads to pre-fill the form.
    """
    filepath = os.path.join(FRONTEND_DIR, "citizen.html")
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()
    # Inject the bin ID as a JS global so citizen.js can pick it up
    if bin and re.match(r'^MCD-[A-Z]{2}-\d+$', bin):
        inject = f'<script>window._QR_PREFILL_BIN = "{bin}";</script>'
        html = html.replace('<script src="/static/citizen.js', inject + '\n    <script src="/static/citizen.js')
    return HTMLResponse(content=html)


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
    sep = "=" * 55
    print(sep)
    print("  InfraWatch Nexus -- API Server v3.0 (Transport Only)")
    print(sep)
    print(f"  Citizens Portal : http://localhost:{SERVER_PORT}/")
    print(f"  Admin Portal    : http://localhost:{SERVER_PORT}/admin")
    print(f"  Dustbins loaded : {len(DUSTBINS)}")
    print(f"  Gemini AI       : {'✓ Configured' if GEMINI_KEY else '✗ Manual fallback'}")
    print(f"  Pathway output  : {PW_OUTPUT_DIR}")

    _rebuild_dedup_cache()
    print(f"  Dedup cache     : {len(_last_report)} recent entries")

    _rebuild_user_reports()
    total_user_reports = sum(len(v) for v in user_reports.values())
    print(f"  User reports    : {total_user_reports} across {len(user_reports)} users")
    print(f"  Auth0           : {'✓ ' + AUTH0_DOMAIN if AUTH0_DOMAIN else '✗ Not configured (anonymous mode)'}")

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
