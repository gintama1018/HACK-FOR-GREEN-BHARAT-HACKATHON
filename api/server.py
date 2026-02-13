"""
InfraWatch Nexus — API Server
==============================
FastAPI intake layer.
  - Receives waste / road / van reports via POST
  - Writes each report as unique JSONL file → Pathway watches
  - Reads Pathway output → caches in memory → serves to dashboard
  - WebSocket for real-time push
"""
import asyncio
import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import SERVER_HOST, SERVER_PORT, OUTPUT_DIR, REPORT_DIR
from config.wards import WARDS, ROAD_SEGMENTS, CITY_CENTER

app = FastAPI(title="InfraWatch Nexus", version="2.0")

# ═══════════════════════════════════════════════════════════════════════════
# DATA DIRECTORIES
# ═══════════════════════════════════════════════════════════════════════════
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WASTE_REPORT_DIR = os.path.join(PROJECT_ROOT, "data", "reports", "waste")
ROAD_REPORT_DIR  = os.path.join(PROJECT_ROOT, "data", "reports", "road")
VAN_LOG_DIR      = os.path.join(PROJECT_ROOT, "data", "reports", "vans")
PW_OUTPUT_DIR    = os.path.join(PROJECT_ROOT, "data", "output")

for d in [WASTE_REPORT_DIR, ROAD_REPORT_DIR, VAN_LOG_DIR, PW_OUTPUT_DIR]:
    os.makedirs(d, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# GLOBAL STATE (cached from Pathway output)
# ═══════════════════════════════════════════════════════════════════════════
cached_state = {
    "waste_risks": [],
    "road_risks": [],
    "priority_queue": [],
    "city_waste_index": 0,
    "city_road_index": 0,
    "rainfall_mm_hr": 0.0,
    "timestamp": None,
    # Data freshness metadata
    "freshness": {
        "weather_last_update": None,
        "weather_source": "unknown",
        "engine_started_at": None,
        "last_report_ts": None,
        "pathway_status": "waiting",
    },
}
SERVER_STARTED_AT = datetime.now().isoformat()
ws_clients = set()


# ═══════════════════════════════════════════════════════════════════════════
# REQUEST MODELS
# ═══════════════════════════════════════════════════════════════════════════

class WasteReport(BaseModel):
    bin_id: str
    ward_id: str
    overflow_level: int  # 1–5
    reporter_type: str = "citizen"  # worker / citizen

class RoadReport(BaseModel):
    segment_id: str
    ward_id: str
    issue_type: str  # pothole / waterlogging / crack
    severity: int    # 1–5

class VanUpdate(BaseModel):
    van_id: str
    ward_id: str
    route_status: str = "active"  # active / completed

class AdvisoryRequest(BaseModel):
    target_id: str       # ward_id or segment_id
    target_type: str     # "waste" or "road"
    question: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# REPORT INTAKE ENDPOINTS (write unique files → Pathway watches)
# ═══════════════════════════════════════════════════════════════════════════

def _write_report(directory: str, prefix: str, data: dict):
    """Write a single report as a unique JSON file. One report per file."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    uid = uuid.uuid4().hex[:8]
    filename = f"{prefix}_{ts}_{uid}.json"
    filepath = os.path.join(directory, filename)
    with open(filepath, "w") as f:
        json.dump([data], f)  # Always as array (Pathway expects list)
    return filename


@app.post("/api/report/waste")
async def submit_waste_report(report: WasteReport):
    """Submit a waste bin overflow report."""
    data = {
        "report_id": f"WR-{uuid.uuid4().hex[:8]}",
        "bin_id": report.bin_id,
        "ward_id": report.ward_id,
        "overflow_level": min(5, max(1, report.overflow_level)),
        "timestamp": datetime.now().isoformat(),
        "reporter_type": report.reporter_type,
    }
    filename = _write_report(WASTE_REPORT_DIR, "waste", data)
    return JSONResponse(content={
        "status": "accepted",
        "report_id": data["report_id"],
        "file": filename,
        "message": f"Waste report for ward {report.ward_id} accepted.",
    })


@app.post("/api/report/road")
async def submit_road_report(report: RoadReport):
    """Submit a road issue report."""
    data = {
        "report_id": f"RR-{uuid.uuid4().hex[:8]}",
        "segment_id": report.segment_id,
        "ward_id": report.ward_id,
        "issue_type": report.issue_type,
        "severity": min(5, max(1, report.severity)),
        "timestamp": datetime.now().isoformat(),
    }
    filename = _write_report(ROAD_REPORT_DIR, "road", data)
    return JSONResponse(content={
        "status": "accepted",
        "report_id": data["report_id"],
        "file": filename,
        "message": f"Road report for segment {report.segment_id} accepted.",
    })


@app.post("/api/van/update")
async def submit_van_update(update: VanUpdate):
    """Log a van collection event."""
    data = {
        "van_id": update.van_id,
        "ward_id": update.ward_id,
        "last_collection_time": datetime.now().isoformat(),
        "route_status": update.route_status,
    }
    filename = _write_report(VAN_LOG_DIR, "van", data)
    return JSONResponse(content={
        "status": "accepted",
        "van_id": update.van_id,
        "file": filename,
        "message": f"Van {update.van_id} update for ward {update.ward_id} logged.",
    })


# ═══════════════════════════════════════════════════════════════════════════
# PATHWAY OUTPUT READER (background thread — caches in memory)
# ═══════════════════════════════════════════════════════════════════════════

def _read_latest_agg(filename: str) -> str:
    """Read the last line of a Pathway JSONL output file."""
    filepath = os.path.join(PW_OUTPUT_DIR, filename)
    if not os.path.exists(filepath):
        return "[]"
    try:
        with open(filepath, "r") as f:
            lines = f.readlines()
        if not lines:
            return "[]"
        last = json.loads(lines[-1])
        return last.get("agg_json", "[]")
    except Exception:
        return "[]"


def _compute_dashboard_state():
    """
    Read all Pathway outputs, compute combined risk + priority.
    Mirrors the logic in pathway_engine._compute_all_risks but runs server-side
    so we can enrich with ward/segment names from config.
    """
    from config.settings import (
        WASTE_RISK_WEIGHTS, ROAD_RISK_WEIGHTS,
        WASTE_NORM, ROAD_NORM, STATE_BANDS,
    )

    def _norm(val, threshold):
        if threshold <= 0: return 0.0
        return min(1.0, max(0.0, val / threshold))

    def _classify(score):
        for band in STATE_BANDS:
            if band["min"] <= score <= band["max"]:
                return band["label"]
        return "Normal"

    def _color(state):
        for band in STATE_BANDS:
            if band["label"] == state:
                return band["color"]
        return "#16A34A"

    # Read Pathway aggregates
    try: waste_data = {e["ward_id"]: e for e in json.loads(_read_latest_agg("waste_agg.jsonl"))}
    except: waste_data = {}

    try: van_data = {e["ward_id"]: e for e in json.loads(_read_latest_agg("van_agg.jsonl"))}
    except: van_data = {}

    try: road_data = {e["segment_id"]: e for e in json.loads(_read_latest_agg("road_agg.jsonl"))}
    except: road_data = {}

    try: weather = json.loads(_read_latest_agg("weather_agg.jsonl"))
    except: weather = {}

    rainfall = weather.get("rainfall_mm_hr", 0.0) if isinstance(weather, dict) else 0.0
    n_rain = _norm(rainfall, WASTE_NORM["rainfall_mm_hr"])

    # Freshness metadata from Pathway weather output
    weather_ts = weather.get("weather_ts", "") if isinstance(weather, dict) else ""
    engine_started = weather.get("engine_started_at", "") if isinstance(weather, dict) else ""
    weather_source = weather.get("weather_source", "unknown") if isinstance(weather, dict) else "unknown"

    # Track latest report timestamp across all streams
    latest_report_ts = ""
    for w in waste_data.values():
        t = w.get("latest_ts", "")
        if t > latest_report_ts:
            latest_report_ts = t

    # ── Waste Risks ──
    waste_risks = []
    for wid, ward in WARDS.items():
        w = waste_data.get(wid, {})
        v = van_data.get(wid, {})

        report_count = w.get("report_count", 0)
        avg_overflow = w.get("avg_overflow", 0.0)
        delay_hr = v.get("collection_delay_hr", 6.0)
        active_vans = v.get("active_vans", 0)

        n_reports  = _norm(report_count, WASTE_NORM["report_count_2hr"])
        n_overflow = _norm(avg_overflow,  WASTE_NORM["overflow_level"])
        n_delay    = _norm(delay_hr,     WASTE_NORM["collection_delay_hr"])

        score = (
            n_reports  * WASTE_RISK_WEIGHTS["report_freq"]
            + n_overflow * WASTE_RISK_WEIGHTS["overflow_severity"]
            + n_delay    * WASTE_RISK_WEIGHTS["collection_delay"]
            + n_rain     * WASTE_RISK_WEIGHTS["rainfall"]
        ) * 100
        score = min(100, max(0, round(score)))
        state = _classify(score)

        waste_risks.append({
            "ward_id": wid,
            "name": ward["name"],
            "zone": ward["zone"],
            "lat": ward["lat"],
            "lng": ward["lng"],
            "bins": ward["bins"],
            "risk_score": score,
            "state": state,
            "color": _color(state),
            "report_count": report_count,
            "avg_overflow": avg_overflow,
            "collection_delay_hr": round(delay_hr, 1),
            "active_vans": active_vans,
            "type": "waste",
        })

    # ── Road Risks ──
    road_risks = []
    for sid, seg in ROAD_SEGMENTS.items():
        r = road_data.get(sid, {})

        report_count = r.get("report_count", 0)
        avg_severity = r.get("avg_severity", 0.0)

        n_reports  = _norm(report_count, ROAD_NORM["report_count_3hr"])
        n_severity = _norm(avg_severity,  ROAD_NORM["severity"])

        score = (
            n_reports  * ROAD_RISK_WEIGHTS["report_density"]
            + n_severity * ROAD_RISK_WEIGHTS["severity"]
            + n_rain     * ROAD_RISK_WEIGHTS["rainfall"]
        ) * 100
        score = min(100, max(0, round(score)))
        state = _classify(score)

        road_risks.append({
            "segment_id": sid,
            "name": seg["name"],
            "ward_id": seg["ward_id"],
            "type_road": seg["type"],
            "lat": seg["lat"],
            "lng": seg["lng"],
            "risk_score": score,
            "state": state,
            "color": _color(state),
            "report_count": report_count,
            "avg_severity": avg_severity,
            "type": "road",
        })

    # ── Priority Queue (Critical waste first, then road) ──
    STATE_PRIORITY = {"Critical": 0, "Warning": 1, "Elevated": 2, "Normal": 3}
    priority = []
    for wr in waste_risks:
        if wr["state"] != "Normal":
            priority.append({
                "id": wr["ward_id"],
                "name": wr["name"],
                "type": "waste",
                "risk_score": wr["risk_score"],
                "state": wr["state"],
                "color": wr["color"],
                "sort_key": STATE_PRIORITY[wr["state"]] * 1000 - wr["risk_score"],
                "type_priority": 0,
            })
    for rr in road_risks:
        if rr["state"] != "Normal":
            priority.append({
                "id": rr["segment_id"],
                "name": rr["name"],
                "type": "road",
                "risk_score": rr["risk_score"],
                "state": rr["state"],
                "color": rr["color"],
                "sort_key": STATE_PRIORITY[rr["state"]] * 1000 - rr["risk_score"],
                "type_priority": 1,
            })
    priority.sort(key=lambda x: (x["type_priority"], x["sort_key"]))

    city_waste = round(sum(w["risk_score"] for w in waste_risks) / max(1, len(waste_risks)), 1)
    city_road  = round(sum(r["risk_score"] for r in road_risks) / max(1, len(road_risks)), 1)

    return {
        "waste_risks": waste_risks,
        "road_risks": road_risks,
        "priority_queue": priority[:20],
        "city_waste_index": city_waste,
        "city_road_index": city_road,
        "rainfall_mm_hr": rainfall,
        "timestamp": datetime.now().isoformat(),
        "freshness": {
            "weather_last_update": weather_ts,
            "weather_source": weather_source,
            "engine_started_at": engine_started,
            "last_report_ts": latest_report_ts or None,
            "pathway_status": "streaming" if engine_started else "waiting",
            "server_started_at": SERVER_STARTED_AT,
        },
    }


def _cache_updater():
    """Background thread: re-read Pathway outputs every 3 seconds."""
    global cached_state
    while True:
        try:
            cached_state = _compute_dashboard_state()
        except Exception as e:
            print(f"[Cache] Error: {e}")
        time.sleep(3)


# ═══════════════════════════════════════════════════════════════════════════
# REST ENDPOINTS (read from cache — fast)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/dashboard")
async def get_dashboard():
    """Full dashboard state — cached from Pathway output."""
    return JSONResponse(content=cached_state)

@app.get("/api/wards")
async def get_wards():
    """Ward risk summaries."""
    return JSONResponse(content={
        "wards": cached_state.get("waste_risks", []),
        "city_waste_index": cached_state.get("city_waste_index", 0),
        "timestamp": cached_state.get("timestamp"),
    })

@app.get("/api/segments")
async def get_segments():
    """Road segment risk summaries."""
    return JSONResponse(content={
        "segments": cached_state.get("road_risks", []),
        "city_road_index": cached_state.get("city_road_index", 0),
        "timestamp": cached_state.get("timestamp"),
    })

@app.get("/api/priority")
async def get_priority():
    """Unified priority queue."""
    return JSONResponse(content={
        "priority_queue": cached_state.get("priority_queue", []),
        "timestamp": cached_state.get("timestamp"),
    })

@app.get("/api/config")
async def get_config():
    """Ward and segment config for frontend map."""
    return JSONResponse(content={
        "wards": {k: {**v} for k, v in WARDS.items()},
        "segments": {k: {**v} for k, v in ROAD_SEGMENTS.items()},
        "city_center": CITY_CENTER,
    })

@app.get("/api/weather")
async def get_weather():
    """Current weather data."""
    return JSONResponse(content={
        "rainfall_mm_hr": cached_state.get("rainfall_mm_hr", 0),
        "timestamp": cached_state.get("timestamp"),
    })


# ═══════════════════════════════════════════════════════════════════════════
# LLM ADVISORY (optional — template fallback)
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/ask")
async def get_advisory(req: AdvisoryRequest):
    """Generate structured advisory for a ward or segment."""
    # Find the target
    target = None
    if req.target_type == "waste":
        target = next((w for w in cached_state.get("waste_risks", []) if w["ward_id"] == req.target_id), None)
    else:
        target = next((r for r in cached_state.get("road_risks", []) if r["segment_id"] == req.target_id), None)

    if not target:
        return JSONResponse(content={"error": "Target not found"}, status_code=404)

    # Structured advisory (no hallucination — deterministic logic)
    if req.target_type == "waste":
        advisory = {
            "target": target.get("name", req.target_id),
            "type": "Waste Management",
            "risk_level": target["state"],
            "risk_score": target["risk_score"],
            "urgency": _urgency(target["state"]),
            "primary_factor": _waste_cause(target),
            "action": _waste_action(target),
            "justification": _waste_justification(target),
            "metrics": {
                "report_count": target.get("report_count", 0),
                "avg_overflow": target.get("avg_overflow", 0),
                "collection_delay_hr": target.get("collection_delay_hr", 0),
                "active_vans": target.get("active_vans", 0),
            },
        }
    else:
        advisory = {
            "target": target.get("name", req.target_id),
            "type": "Road Maintenance",
            "risk_level": target["state"],
            "risk_score": target["risk_score"],
            "urgency": _urgency(target["state"]),
            "primary_factor": _road_cause(target),
            "action": _road_action(target),
            "justification": _road_justification(target),
            "metrics": {
                "report_count": target.get("report_count", 0),
                "avg_severity": target.get("avg_severity", 0),
            },
        }

    return JSONResponse(content={"advisory": advisory})


def _urgency(state):
    return {"Critical": "Immediate", "Warning": "High", "Elevated": "Moderate", "Normal": "Low"}.get(state, "Low")

def _waste_cause(t):
    causes = []
    if t.get("collection_delay_hr", 0) >= 8:
        causes.append(f"{t['collection_delay_hr']}hr collection delay")
    if t.get("avg_overflow", 0) >= 3:
        causes.append(f"overflow severity avg {t['avg_overflow']}")
    if t.get("report_count", 0) >= 5:
        causes.append(f"{t['report_count']} reports in window")
    return causes[0] if causes else "Baseline monitoring — no significant triggers"

def _waste_justification(t):
    parts = []
    if t.get("collection_delay_hr", 0) >= 6:
        parts.append(f"Collection delay of {t['collection_delay_hr']}hr exceeds 6hr threshold.")
    if t.get("avg_overflow", 0) >= 3:
        parts.append(f"Average overflow level {t['avg_overflow']}/5 indicates bins nearing capacity.")
    if t.get("report_count", 0) >= 3:
        parts.append(f"{t['report_count']} reports in rolling window show active issue.")
    if t.get("active_vans", 0) == 0:
        parts.append("No active vans in ward — response capacity at zero.")
    return " ".join(parts) if parts else "Risk within normal parameters."

def _waste_action(t):
    if t["state"] == "Critical":
        return f"Dispatch {max(2, t.get('active_vans', 0) + 1)} vans immediately. Clear overflow bins within 1 hour."
    if t["state"] == "Warning":
        return "Schedule additional collection run within 2 hours."
    if t["state"] == "Elevated":
        return "Monitor. Consider rescheduling next collection earlier."
    return "No action required."

def _road_cause(t):
    causes = []
    if t.get("avg_severity", 0) >= 3:
        causes.append(f"avg severity {t['avg_severity']}/5")
    if t.get("report_count", 0) >= 3:
        causes.append(f"{t['report_count']} reports in window")
    return causes[0] if causes else "Baseline monitoring — no significant triggers"

def _road_justification(t):
    parts = []
    if t.get("avg_severity", 0) >= 3:
        parts.append(f"Average severity {t['avg_severity']}/5 indicates structural concern.")
    if t.get("report_count", 0) >= 3:
        parts.append(f"{t['report_count']} reports in rolling window — repeat issue.")
    return " ".join(parts) if parts else "Risk within normal parameters."

def _road_action(t):
    if t["state"] == "Critical":
        return "Deploy maintenance crew immediately. Mark for emergency repair."
    if t["state"] == "Warning":
        return "Schedule inspection within 24 hours."
    if t["state"] == "Elevated":
        return "Add to weekly maintenance schedule."
    return "No action required."


# ═══════════════════════════════════════════════════════════════════════════
# WEBSOCKET (real-time push)
# ═══════════════════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_stream(websocket: WebSocket):
    """Push dashboard state to connected clients every 4 seconds."""
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
# STATIC FILES & DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

@app.get("/")
async def serve_dashboard():
    with open(os.path.join(FRONTEND_DIR, "index.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ═══════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    print("═" * 50)
    print("  InfraWatch Nexus — API Server v2.0")
    print("═" * 50)
    print(f"  Reports in  : {REPORT_DIR}")
    print(f"  Pathway out : {PW_OUTPUT_DIR}")
    print(f"  Dashboard   : http://localhost:{SERVER_PORT}")

    # Start background cache updater
    t = threading.Thread(target=_cache_updater, daemon=True)
    t.start()
    print("  Cache updater started (3s interval)")


# ═══════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host=SERVER_HOST, port=SERVER_PORT, reload=False)
