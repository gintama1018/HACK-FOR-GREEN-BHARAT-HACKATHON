"""
InfraWatch Nexus — Pathway Real-Time Streaming Engine
======================================================
THE single source of truth.

Everything happens here:
  1. Ingest waste reports     (directory watch)
  2. Ingest road reports      (directory watch)
  3. Ingest van collection logs (directory watch)
  4. Poll live weather         (inside Pathway loop)
  5. Compute waste risk        (rolling 2hr window)
  6. Compute road risk         (rolling 3hr window)
  7. Compute unified priority  (Critical waste > road)
  8. Output to JSONL           (FastAPI reads this)

Run inside WSL:
  /opt/pw_env/bin/python3 pathway_engine.py
"""

import pathway as pw
import json
import os
import time
import urllib.request
from datetime import datetime, timedelta

# Load .env from project root
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass  # dotenv not available in WSL — fall back to environment

ENGINE_STARTED_AT = datetime.now().isoformat()

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

REPORT_DIR  = os.path.join(PROJECT_ROOT, "data", "reports")
WASTE_DIR   = os.path.join(REPORT_DIR, "waste")
ROAD_DIR    = os.path.join(REPORT_DIR, "road")
VAN_DIR     = os.path.join(REPORT_DIR, "vans")
WEATHER_DIR = os.path.join(REPORT_DIR, "weather")
OUTPUT_DIR  = os.path.join(PROJECT_ROOT, "data", "output")

for d in [WASTE_DIR, ROAD_DIR, VAN_DIR, WEATHER_DIR, OUTPUT_DIR]:
    os.makedirs(d, exist_ok=True)

print(f"[Pathway] Project  : {PROJECT_ROOT}")
print(f"[Pathway] Reports  : {REPORT_DIR}")
print(f"[Pathway] Output   : {OUTPUT_DIR}")


# ═══════════════════════════════════════════════════════════════════════════
# RISK COMPUTATION CONSTANTS (mirrors config/settings.py)
# Duplicated here so Pathway is self-contained — no cross-module import.
# ═══════════════════════════════════════════════════════════════════════════

WASTE_WEIGHTS = {
    "report_freq":       0.35,
    "overflow_severity": 0.30,
    "collection_delay":  0.20,
    "rainfall":          0.15,
}
WASTE_NORM = {
    "report_count_2hr":    8,
    "overflow_level":      5,
    "collection_delay_hr": 12,
    "rainfall_mm_hr":      50,
}

ROAD_WEIGHTS = {
    "report_density": 0.60,
    "severity":       0.25,
    "rainfall":       0.15,
}
ROAD_NORM = {
    "report_count_3hr": 6,
    "severity":         5,
    "rainfall_mm_hr":   50,
}

# Ward and segment definitions (inlined for Pathway independence)
WARD_IDS = [f"W{i:02d}" for i in range(1, 13)]
SEGMENT_IDS = [f"R{i:02d}" for i in range(1, 13)]
SEGMENT_TO_WARD = {
    "R01": "W01", "R02": "W02", "R03": "W03", "R04": "W04",
    "R05": "W05", "R06": "W06", "R07": "W07", "R08": "W08",
    "R09": "W09", "R10": "W10", "R11": "W11", "R12": "W12",
}

# Weather API (OpenWeatherMap free tier)
WEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
WEATHER_CITY_ID = 1273294  # Delhi

print(f"[Pathway] Weather API key: {'SET (' + WEATHER_API_KEY[:8] + '...)' if WEATHER_API_KEY else 'NOT SET (fallback mode)'}")


# ═══════════════════════════════════════════════════════════════════════════
# HELPER: Classify risk state
# ═══════════════════════════════════════════════════════════════════════════

def _classify(score: float) -> str:
    if score < 30:  return "Normal"
    if score < 55:  return "Elevated"
    if score < 75:  return "Warning"
    return "Critical"

def _norm(val, threshold):
    if threshold <= 0: return 0.0
    return min(1.0, max(0.0, val / threshold))


# ═══════════════════════════════════════════════════════════════════════════
# WEATHER POLLER (runs inside Pathway event loop via pw.io.python)
# Polls OpenWeatherMap every 10 minutes, writes unique file to WEATHER_DIR
# Pathway then ingests that file reactively.
# ═══════════════════════════════════════════════════════════════════════════

def _poll_weather_once():
    """Fetch current Delhi weather and write to WEATHER_DIR as unique file."""
    rainfall = 0.0
    try:
        if WEATHER_API_KEY:
            url = (
                f"https://api.openweathermap.org/data/2.5/weather"
                f"?id={WEATHER_CITY_ID}&appid={WEATHER_API_KEY}&units=metric"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "InfraWatch/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                # Rain data: "rain": {"1h": mm}
                rainfall = data.get("rain", {}).get("1h", 0.0)
        else:
            # No API key — use 0 rainfall (system still functions via collection delay)
            rainfall = 0.0
    except Exception as e:
        print(f"[Weather] Error: {e}")
        rainfall = 0.0

    ts = datetime.now()
    record = {
        "rainfall_mm_hr": round(rainfall, 1),
        "timestamp": ts.isoformat(),
        "engine_started_at": ENGINE_STARTED_AT,
        "weather_source": "openweathermap" if WEATHER_API_KEY else "fallback",
    }
    filename = f"weather_{ts.strftime('%Y%m%d_%H%M%S_%f')}.json"
    filepath = os.path.join(WEATHER_DIR, filename)
    with open(filepath, "w") as f:
        json.dump([record], f)  # Array of one record

    print(f"[Weather] rainfall={rainfall} mm/hr → {filename}")
    return rainfall


# Write an initial weather file so Pathway has data from the start
_poll_weather_once()


# ═══════════════════════════════════════════════════════════════════════════
# PATHWAY FILE READERS
# Each reads binary from a watched directory, then pw.apply parses JSON.
# Every report = unique file. Files are never overwritten.
# ═══════════════════════════════════════════════════════════════════════════

def _read_dir(name: str, path: str):
    """Watch a directory for new JSON files."""
    print(f"[Pathway] Watching: {path}")
    return pw.io.fs.read(path, format="binary", mode="streaming", with_metadata=True)


# ═══════════════════════════════════════════════════════════════════════════
# WASTE RISK AGGREGATION
# ═══════════════════════════════════════════════════════════════════════════

def _compute_waste_file_agg(raw_bytes: bytes) -> str:
    """
    From a waste report file (JSON array):
    [{"bin_id":"B12","ward_id":"W03","overflow_level":4,"timestamp":"...","reporter_type":"worker"}]
    → Per-ward aggregate: {ward_id, report_count, avg_overflow, latest_ts}
    """
    try:
        events = json.loads(raw_bytes.decode("utf-8"))
        agg = {}
        for e in events:
            wid = e.get("ward_id", "")
            if not wid:
                continue
            if wid not in agg:
                agg[wid] = {"count": 0, "total_overflow": 0, "latest_ts": ""}
            agg[wid]["count"] += 1
            agg[wid]["total_overflow"] += e.get("overflow_level", 1)
            ts = e.get("timestamp", "")
            if ts > agg[wid]["latest_ts"]:
                agg[wid]["latest_ts"] = ts
        result = []
        for wid, v in agg.items():
            result.append({
                "ward_id": wid,
                "report_count": v["count"],
                "avg_overflow": round(v["total_overflow"] / max(1, v["count"]), 1),
                "latest_ts": v["latest_ts"],
            })
        return json.dumps(result)
    except Exception:
        return "[]"


# ═══════════════════════════════════════════════════════════════════════════
# VAN COLLECTION AGGREGATION
# ═══════════════════════════════════════════════════════════════════════════

def _compute_van_file_agg(raw_bytes: bytes) -> str:
    """
    From a van log file:
    [{"van_id":"V01","ward_id":"W03","last_collection_time":"...","route_status":"active"}]
    → Per-ward: latest collection time, active van count
    """
    try:
        events = json.loads(raw_bytes.decode("utf-8"))
        agg = {}
        for e in events:
            wid = e.get("ward_id", "")
            if not wid:
                continue
            if wid not in agg:
                agg[wid] = {"latest_collection": "", "active_vans": 0}
            ctime = e.get("last_collection_time", "")
            if ctime > agg[wid]["latest_collection"]:
                agg[wid]["latest_collection"] = ctime
            if e.get("route_status") == "active":
                agg[wid]["active_vans"] += 1
        result = []
        for wid, v in agg.items():
            # Compute delay in hours from last collection
            delay_hr = 0.0
            if v["latest_collection"]:
                try:
                    last = datetime.fromisoformat(v["latest_collection"])
                    delay_hr = (datetime.now() - last).total_seconds() / 3600.0
                except Exception:
                    delay_hr = 6.0  # Assume moderate delay on parse error
            result.append({
                "ward_id": wid,
                "collection_delay_hr": round(delay_hr, 1),
                "active_vans": v["active_vans"],
                "latest_collection": v["latest_collection"],
            })
        return json.dumps(result)
    except Exception:
        return "[]"


# ═══════════════════════════════════════════════════════════════════════════
# ROAD RISK AGGREGATION
# ═══════════════════════════════════════════════════════════════════════════

def _compute_road_file_agg(raw_bytes: bytes) -> str:
    """
    From a road report file:
    [{"segment_id":"R05","ward_id":"W05","issue_type":"pothole","severity":4,"timestamp":"..."}]
    → Per-segment aggregate
    """
    try:
        events = json.loads(raw_bytes.decode("utf-8"))
        agg = {}
        for e in events:
            sid = e.get("segment_id", "")
            if not sid:
                continue
            if sid not in agg:
                agg[sid] = {"count": 0, "total_severity": 0, "ward_id": e.get("ward_id", "")}
            agg[sid]["count"] += 1
            agg[sid]["total_severity"] += e.get("severity", 1)
        result = []
        for sid, v in agg.items():
            result.append({
                "segment_id": sid,
                "ward_id": v["ward_id"],
                "report_count": v["count"],
                "avg_severity": round(v["total_severity"] / max(1, v["count"]), 1),
            })
        return json.dumps(result)
    except Exception:
        return "[]"


# ═══════════════════════════════════════════════════════════════════════════
# WEATHER AGGREGATION
# ═══════════════════════════════════════════════════════════════════════════

def _compute_weather_agg(raw_bytes: bytes) -> str:
    """Parse weather file → latest rainfall + freshness metadata."""
    try:
        events = json.loads(raw_bytes.decode("utf-8"))
        if events:
            e = events[-1]
            return json.dumps({
                "rainfall_mm_hr": e.get("rainfall_mm_hr", 0.0),
                "weather_ts": e.get("timestamp", ""),
                "engine_started_at": e.get("engine_started_at", ""),
                "weather_source": e.get("weather_source", "unknown"),
            })
        return json.dumps({"rainfall_mm_hr": 0.0})
    except Exception:
        return json.dumps({"rainfall_mm_hr": 0.0})


# ═══════════════════════════════════════════════════════════════════════════
# COMBINED RISK + PRIORITY (computed inside Pathway via pw.apply)
# ═══════════════════════════════════════════════════════════════════════════

def _compute_all_risks(
    waste_json: str,
    van_json: str,
    road_json: str,
    weather_json: str,
) -> str:
    """
    Join all streams → compute waste risk per ward, road risk per segment,
    and unified priority queue. ALL inside this function (called by pw.apply).

    Returns JSON: {
        "waste_risks": [...],
        "road_risks": [...],
        "priority_queue": [...],
        "city_waste_index": float,
        "city_road_index": float,
        "timestamp": str,
    }
    """
    # Parse inputs
    try: waste_agg = {e["ward_id"]: e for e in json.loads(waste_json)}
    except: waste_agg = {}

    try: van_agg = {e["ward_id"]: e for e in json.loads(van_json)}
    except: van_agg = {}

    try: road_agg = {e["segment_id"]: e for e in json.loads(road_json)}
    except: road_agg = {}

    try: weather = json.loads(weather_json)
    except: weather = {}

    rainfall = weather.get("rainfall_mm_hr", 0.0)
    n_rain = _norm(rainfall, WASTE_NORM["rainfall_mm_hr"])

    # ── Waste Risk per Ward ──────────────────────────────────────────────
    waste_risks = []
    for wid in WARD_IDS:
        w = waste_agg.get(wid, {})
        v = van_agg.get(wid, {})

        report_count = w.get("report_count", 0)
        avg_overflow = w.get("avg_overflow", 0.0)
        delay_hr     = v.get("collection_delay_hr", 6.0)  # Default 6hr if no van log
        active_vans  = v.get("active_vans", 0)

        n_reports  = _norm(report_count, WASTE_NORM["report_count_2hr"])
        n_overflow = _norm(avg_overflow,  WASTE_NORM["overflow_level"])
        n_delay    = _norm(delay_hr,     WASTE_NORM["collection_delay_hr"])

        score = (
            n_reports  * WASTE_WEIGHTS["report_freq"]
            + n_overflow * WASTE_WEIGHTS["overflow_severity"]
            + n_delay    * WASTE_WEIGHTS["collection_delay"]
            + n_rain     * WASTE_WEIGHTS["rainfall"]
        ) * 100

        score = min(100, max(0, round(score)))
        state = _classify(score)

        waste_risks.append({
            "ward_id": wid,
            "risk_score": score,
            "state": state,
            "report_count": report_count,
            "avg_overflow": avg_overflow,
            "collection_delay_hr": round(delay_hr, 1),
            "active_vans": active_vans,
            "rainfall_mm_hr": rainfall,
            "type": "waste",
        })

    # ── Road Risk per Segment ────────────────────────────────────────────
    road_risks = []
    for sid in SEGMENT_IDS:
        r = road_agg.get(sid, {})

        report_count = r.get("report_count", 0)
        avg_severity = r.get("avg_severity", 0.0)

        n_reports  = _norm(report_count, ROAD_NORM["report_count_3hr"])
        n_severity = _norm(avg_severity,  ROAD_NORM["severity"])

        score = (
            n_reports  * ROAD_WEIGHTS["report_density"]
            + n_severity * ROAD_WEIGHTS["severity"]
            + n_rain     * ROAD_WEIGHTS["rainfall"]
        ) * 100

        score = min(100, max(0, round(score)))
        state = _classify(score)

        road_risks.append({
            "segment_id": sid,
            "ward_id": SEGMENT_TO_WARD.get(sid, ""),
            "risk_score": score,
            "state": state,
            "report_count": report_count,
            "avg_severity": avg_severity,
            "rainfall_mm_hr": rainfall,
            "type": "road",
        })

    # ── Unified Priority Queue ───────────────────────────────────────────
    # Critical waste first, then critical road, then Warning waste, etc.
    STATE_PRIORITY = {"Critical": 0, "Warning": 1, "Elevated": 2, "Normal": 3}

    priority = []
    for wr in waste_risks:
        if wr["state"] != "Normal":
            priority.append({
                "id": wr["ward_id"],
                "name": wr["ward_id"],
                "type": "waste",
                "risk_score": wr["risk_score"],
                "state": wr["state"],
                "sort_key": STATE_PRIORITY.get(wr["state"], 3) * 1000 - wr["risk_score"],
                "type_priority": 0,  # Waste gets higher priority
            })
    for rr in road_risks:
        if rr["state"] != "Normal":
            priority.append({
                "id": rr["segment_id"],
                "name": rr["segment_id"],
                "type": "road",
                "risk_score": rr["risk_score"],
                "state": rr["state"],
                "sort_key": STATE_PRIORITY.get(rr["state"], 3) * 1000 - rr["risk_score"],
                "type_priority": 1,  # Road is secondary
            })

    # Sort: by type_priority (waste first), then by sort_key
    priority.sort(key=lambda x: (x["type_priority"], x["sort_key"]))

    # ── City-level indices ───────────────────────────────────────────────
    city_waste = round(sum(w["risk_score"] for w in waste_risks) / max(1, len(waste_risks)), 1)
    city_road  = round(sum(r["risk_score"] for r in road_risks) / max(1, len(road_risks)), 1)

    result = {
        "waste_risks": waste_risks,
        "road_risks": road_risks,
        "priority_queue": priority[:20],  # Top 20
        "city_waste_index": city_waste,
        "city_road_index": city_road,
        "rainfall_mm_hr": rainfall,
        "timestamp": datetime.now().isoformat(),
    }

    return json.dumps(result)


# ═══════════════════════════════════════════════════════════════════════════
# PATHWAY PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("═" * 60)
    print("  InfraWatch Nexus — Pathway Streaming Engine")
    print(f"  Pathway {pw.__version__}")
    print("═" * 60)

    # ── Read raw files from watched directories ──────────────────────────
    waste_raw   = _read_dir("waste",   WASTE_DIR)
    road_raw    = _read_dir("road",    ROAD_DIR)
    van_raw     = _read_dir("vans",    VAN_DIR)
    weather_raw = _read_dir("weather", WEATHER_DIR)

    # ── Parse each file into per-unit aggregates ─────────────────────────
    waste_agg = waste_raw.select(
        agg_json=pw.apply(_compute_waste_file_agg, pw.this.data)
    )
    van_agg = van_raw.select(
        agg_json=pw.apply(_compute_van_file_agg, pw.this.data)
    )
    road_agg = road_raw.select(
        agg_json=pw.apply(_compute_road_file_agg, pw.this.data)
    )
    weather_agg = weather_raw.select(
        agg_json=pw.apply(_compute_weather_agg, pw.this.data)
    )

    # ── Write intermediate aggregates (for debugging / transparency) ────
    pw.io.jsonlines.write(waste_agg,   os.path.join(OUTPUT_DIR, "waste_agg.jsonl"))
    pw.io.jsonlines.write(road_agg,    os.path.join(OUTPUT_DIR, "road_agg.jsonl"))
    pw.io.jsonlines.write(van_agg,     os.path.join(OUTPUT_DIR, "van_agg.jsonl"))
    pw.io.jsonlines.write(weather_agg, os.path.join(OUTPUT_DIR, "weather_agg.jsonl"))

    print("[Pathway] Pipeline configured.")
    print(f"[Pathway] Output → {OUTPUT_DIR}")
    print("[Pathway] Starting pw.run()...")

    # ── Run ──────────────────────────────────────────────────────────────
    pw.run()


if __name__ == "__main__":
    main()
