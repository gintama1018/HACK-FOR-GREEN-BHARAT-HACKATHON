"""
InfraWatch Nexus — Pathway Streaming Engine
=============================================
ALL computation lives here. Nothing in FastAPI.

Responsibilities:
  - Watch event directories (waste, road, vans, weather)
  - Aggregate per-dustbin (with event-time rolling windows)
  - Compute dustbin states (Clear/Reported/Escalated/Critical/Cleared)
  - Compute ward-level risk scores
  - Process road issues (with expiry)
  - Build unified priority queue
  - Output atomic dashboard JSON snapshot
  - Poll WeatherAPI.com for live rainfall
"""

import json
import os
import sys
import tempfile
import threading
import time
import requests
from datetime import datetime, timedelta

import pathway as pw

# Project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import (
    WASTE_RISK_WEIGHTS, ROAD_RISK_WEIGHTS,
    WASTE_NORM, ROAD_NORM, STATE_BANDS,
    DUSTBIN_STATE_THRESHOLDS,
    WASTE_REPORT_WINDOW_HOURS, ROAD_ISSUE_WINDOW_HOURS,
    WEATHER_API_URL, WEATHER_CITY, WEATHER_POLL_SEC,
    PRIORITY_QUEUE_MAX,
)
from config.wards import WARDS, CITY_CENTER
from config.dustbins import DUSTBINS

from dotenv import load_dotenv
load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════
# DIRECTORIES
# ═══════════════════════════════════════════════════════════════════════════
BASE       = os.path.dirname(os.path.abspath(__file__))
WASTE_DIR  = os.path.join(BASE, "data", "reports", "waste")
ROAD_DIR   = os.path.join(BASE, "data", "reports", "road")
VAN_DIR    = os.path.join(BASE, "data", "reports", "vans")
WEATHER_DIR= os.path.join(BASE, "data", "reports", "weather")
OUTPUT_DIR = os.path.join(BASE, "data", "output")

for d in [WASTE_DIR, ROAD_DIR, VAN_DIR, WEATHER_DIR, OUTPUT_DIR]:
    os.makedirs(d, exist_ok=True)

# Ward and dustbin ID lists
WARD_IDS    = list(WARDS.keys())
DUSTBIN_IDS = list(DUSTBINS.keys())
DUSTBIN_TO_WARD = {did: info["ward_id"] for did, info in DUSTBINS.items()}

# ═══════════════════════════════════════════════════════════════════════════
# WEATHER POLLER (background thread, writes to watched directory)
# ═══════════════════════════════════════════════════════════════════════════
_latest_weather = {"rainfall_mm_hr": 0.0, "weather_source": "none", "timestamp": ""}

def _weather_poller():
    """Poll WeatherAPI.com every WEATHER_POLL_SEC. Write to weather directory."""
    global _latest_weather
    api_key = os.getenv("WX_API_KEY", "")
    started_at = datetime.now().isoformat()

    while True:
        rainfall = 0.0
        source = "fallback"

        if api_key:
            try:
                resp = requests.get(
                    WEATHER_API_URL,
                    params={"key": api_key, "q": WEATHER_CITY, "aqi": "no"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    rainfall = data.get("current", {}).get("precip_mm", 0.0)
                    source = "weatherapi.com"
            except Exception as e:
                print(f"[Weather] API error: {e}")

        now_ts = datetime.now().isoformat()
        weather_event = {
            "rainfall_mm_hr": rainfall,
            "timestamp": now_ts,
            "weather_source": source,
            "engine_started_at": started_at,
        }

        _latest_weather = weather_event

        # Write to weather directory for Pathway to pick up
        weather_file = os.path.join(WEATHER_DIR, "current_weather.json")
        try:
            with open(weather_file, "w") as f:
                json.dump([weather_event], f)
        except Exception as e:
            print(f"[Weather] Write error: {e}")

        print(f"[Weather] {source}: {rainfall}mm/hr @ {now_ts}")
        time.sleep(WEATHER_POLL_SEC)


# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS (used inside pw.apply)
# ═══════════════════════════════════════════════════════════════════════════
def _norm(val, threshold):
    """Normalize to 0-1, capped at 1.0."""
    if threshold <= 0:
        return 0.0
    return min(1.0, max(0.0, val / threshold))


def _classify(score):
    """Score → state label."""
    for band in STATE_BANDS:
        if band["min"] <= score <= band["max"]:
            return band["label"]
    return "Critical" if score > 100 else "Normal"


def _color(state):
    """State label → color hex."""
    for band in STATE_BANDS:
        if band["label"] == state:
            return band["color"]
    return "#16A34A"


from datetime import timezone

def _parse_ts(ts_str):
    """Safely parse ISO string to timezone-aware datetime."""
    if not ts_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        # Handle JS 'Z' suffix and parse
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            # Assume local time if naive, but force to a standard for comparison
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


# ═══════════════════════════════════════════════════════════════════════════
# FILE READERS — reads all event files from a directory
# ═══════════════════════════════════════════════════════════════════════════
def _read_all_events(directory: str) -> list:
    """Read all JSON event files from a directory. Returns flat event list."""
    events = []
    if not os.path.exists(directory):
        return events
    for fname in sorted(os.listdir(directory)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(directory, fname)
        try:
            with open(fpath, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                events.extend(data)
            elif isinstance(data, dict):
                events.append(data)
        except Exception:
            continue
    return events


# ═══════════════════════════════════════════════════════════════════════════
# CORE COMPUTATION — EVERYTHING LIVES HERE
# ═══════════════════════════════════════════════════════════════════════════
def compute_dashboard_snapshot() -> dict:
    """
    Read all event files → compute complete dashboard state.
    Uses EVENT-TIME windowing (not wall-clock).
    Returns atomic JSON snapshot.
    """
    # ── Read all events ─────────────────────────────────────────────────
    waste_events = _read_all_events(WASTE_DIR)
    van_events   = _read_all_events(VAN_DIR)
    road_events  = _read_all_events(ROAD_DIR)

    # ── Weather (from poller) ───────────────────────────────────────────
    rainfall = _latest_weather.get("rainfall_mm_hr", 0.0)
    # CAP rainfall at normalization threshold
    rainfall_capped = min(rainfall, WASTE_NORM["rainfall_mm_hr"])
    n_rain = _norm(rainfall_capped, WASTE_NORM["rainfall_mm_hr"])

    # ── Event-Time Window Start ─────────────────────────────────────────
    # Parse all timestamps to tz-aware datetimes for safe comparison
    waste_dts = [_parse_ts(e.get("timestamp", "")) for e in waste_events if e.get("timestamp")]
    latest_waste_dt = max(waste_dts) if waste_dts else datetime.now(timezone.utc)
    waste_window_start_dt = latest_waste_dt - timedelta(hours=WASTE_REPORT_WINDOW_HOURS)

    # Road event window
    road_dts = [_parse_ts(e.get("timestamp", "")) for e in road_events if e.get("timestamp")]
    latest_road_dt = max(road_dts) if road_dts else datetime.now(timezone.utc)
    road_window_start_dt = latest_road_dt - timedelta(hours=ROAD_ISSUE_WINDOW_HOURS)

    # ── Van collection events (latest per dustbin) ──────────────────────
    latest_van_by_dustbin = {}
    for e in van_events:
        if e.get("event_type") == "collection_confirmed":
            did = e.get("dustbin_id", "")
            ts_str = e.get("timestamp", "")
            if not did or not ts_str:
                continue
            ts_dt = _parse_ts(ts_str)
            if did not in latest_van_by_dustbin or ts_dt > latest_van_by_dustbin[did]["dt"]:
                latest_van_by_dustbin[did] = {"ts": ts_str, "dt": ts_dt}

    # ── Dustbin-level aggregation (windowed) ────────────────────────────
    dustbin_agg = {}  # dustbin_id → {report_count, max_overflow, latest_ts}

    for e in waste_events:
        ts_str = e.get("timestamp", "")
        ts_dt = _parse_ts(ts_str)
        if ts_dt < waste_window_start_dt:
            continue  # Outside window — skip

        did = e.get("dustbin_id", "")
        if not did or did not in DUSTBINS:
            continue

        if did not in dustbin_agg:
            dustbin_agg[did] = {
                "report_count": 0,
                "max_overflow": 0,
                "total_overflow": 0,
                "latest_ts": "",
                "latest_dt": _parse_ts(""),
            }
        dustbin_agg[did]["report_count"] += 1
        overflow = e.get("overflow_level", 1)
        dustbin_agg[did]["max_overflow"] = max(dustbin_agg[did]["max_overflow"], overflow)
        dustbin_agg[did]["total_overflow"] += overflow
        if ts_dt > dustbin_agg[did]["latest_dt"]:
            dustbin_agg[did]["latest_ts"] = ts_str
            dustbin_agg[did]["latest_dt"] = ts_dt

    # ── Dustbin States ──────────────────────────────────────────────────
    thresholds = DUSTBIN_STATE_THRESHOLDS
    dustbin_states = []

    for did in DUSTBIN_IDS:
        agg = dustbin_agg.get(did, {})
        report_count = agg.get("report_count", 0)
        max_overflow = agg.get("max_overflow", 0)
        avg_overflow = round(agg.get("total_overflow", 0) / max(1, report_count), 1) if report_count else 0

        # Check van-cleared override
        van_data = latest_van_by_dustbin.get(did, {})
        van_ts = van_data.get("ts", "")
        van_dt = van_data.get("dt", None)
        latest_report_dt = agg.get("latest_dt", None)

        if van_dt and (not latest_report_dt or van_dt > latest_report_dt):
            state = "Cleared"
        elif report_count >= thresholds["Critical"]["min_reports"]:
            state = "Critical"
        elif report_count >= thresholds["Escalated"]["min_reports"] or max_overflow >= thresholds["Escalated"]["or_overflow_gte"]:
            # Check if Escalated + rain → Critical
            if rainfall >= thresholds["Critical"]["or_escalated_with_rain_gte"]:
                state = "Critical"
            else:
                state = "Escalated"
        elif report_count >= thresholds["Reported"]["min_reports"]:
            state = "Reported"
        else:
            state = "Clear"

        info = DUSTBINS[did]
        dustbin_states.append({
            "dustbin_id": did,
            "ward_id": info["ward_id"],
            "lat": info["lat"],
            "lng": info["lng"],
            "street": info["street"],
            "state": state,
            "report_count": report_count,
            "max_overflow": max_overflow,
            "avg_overflow": avg_overflow,
            "latest_report_ts": agg.get("latest_ts", ""),
            "van_cleared_ts": van_ts or None,
            "color": _dustbin_color(state),
        })

    # ── Ward-Level Risk Scores ──────────────────────────────────────────
    ward_risks = []
    for wid, ward_info in WARDS.items():
        # Aggregate dustbin data for this ward
        ward_dustbins = [d for d in dustbin_states if d["ward_id"] == wid]
        total_reports = sum(d["report_count"] for d in ward_dustbins)
        avg_overflow = 0
        overflow_vals = [d["avg_overflow"] for d in ward_dustbins if d["avg_overflow"] > 0]
        if overflow_vals:
            avg_overflow = round(sum(overflow_vals) / len(overflow_vals), 1)

        # Collection delay: hours since last van event in this ward
        ward_van_times = [latest_van_by_dustbin[did]["dt"] for did in latest_van_by_dustbin
                          if DUSTBIN_TO_WARD.get(did) == wid]
        if ward_van_times:
            latest_van_dt_val = max(ward_van_times)
            delay_hr = (latest_waste_dt - latest_van_dt_val).total_seconds() / 3600.0
            delay_hr = max(0, round(delay_hr, 1))
        else:
            delay_hr = 6.0  # Default if no van data

        # Active vans: count vans that collected within last 2 hours
        active_vans = 0
        for did in [d for d in latest_van_by_dustbin if DUSTBIN_TO_WARD.get(d) == wid]:
            vt = latest_van_by_dustbin[did]["dt"]
            if (latest_waste_dt - vt).total_seconds() < 7200:
                active_vans += 1

        # Risk score
        n_reports  = _norm(total_reports, WASTE_NORM["report_count_2hr"])
        n_overflow = _norm(avg_overflow, WASTE_NORM["overflow_level"])
        n_delay    = _norm(delay_hr, WASTE_NORM["collection_delay_hr"])

        score = (
            n_reports  * WASTE_RISK_WEIGHTS["report_freq"]
            + n_overflow * WASTE_RISK_WEIGHTS["overflow_severity"]
            + n_delay    * WASTE_RISK_WEIGHTS["collection_delay"]
            + n_rain     * WASTE_RISK_WEIGHTS["rainfall"]
        ) * 100
        score = min(100, max(0, round(score)))
        state = _classify(score)

        # Count dustbins in non-clear states
        bins_reported = len([d for d in ward_dustbins if d["state"] not in ("Clear", "Cleared")])

        ward_risks.append({
            "ward_id": wid,
            "name": ward_info["name"],
            "zone": ward_info["zone"],
            "lat": ward_info["lat"],
            "lng": ward_info["lng"],
            "bins": ward_info["bins"],
            "risk_score": score,
            "state": state,
            "color": _color(state),
            "report_count": total_reports,
            "avg_overflow": avg_overflow,
            "collection_delay_hr": delay_hr,
            "active_vans": active_vans,
            "bins_reported": bins_reported,
            "type": "waste",
        })

    # ── Road Issues (windowed) ──────────────────────────────────────────
    road_issues = []
    road_by_ward = {}  # ward_id → {report_count, total_severity}

    for e in road_events:
        ts_str = e.get("timestamp", "")
        ts_dt = _parse_ts(ts_str)
        if ts_dt < road_window_start_dt:
            continue  # Expired

        from_bin = e.get("from_dustbin", "")
        to_bin = e.get("to_dustbin", "")
        ward_id = e.get("ward_id", "")

        if not from_bin or not to_bin:
            continue

        from_info = DUSTBINS.get(from_bin, {})
        to_info = DUSTBINS.get(to_bin, {})

        road_issues.append({
            "event_id": e.get("event_id", ""),
            "from_dustbin": from_bin,
            "to_dustbin": to_bin,
            "from_lat": from_info.get("lat", 0),
            "from_lng": from_info.get("lng", 0),
            "to_lat": to_info.get("lat", 0),
            "to_lng": to_info.get("lng", 0),
            "ward_id": ward_id,
            "issue_type": e.get("issue_type", ""),
            "severity": e.get("severity", 1),
            "timestamp": ts_str,
        })

        # Aggregate road issues per ward for scoring
        if ward_id not in road_by_ward:
            road_by_ward[ward_id] = {"count": 0, "total_severity": 0}
        road_by_ward[ward_id]["count"] += 1
        road_by_ward[ward_id]["total_severity"] += e.get("severity", 1)

    # ── Road Risk per Ward ──────────────────────────────────────────────
    road_ward_risks = []
    for wid, ward_info in WARDS.items():
        r = road_by_ward.get(wid, {})
        report_count = r.get("count", 0)
        avg_severity = round(r.get("total_severity", 0) / max(1, report_count), 1) if report_count else 0

        n_reports  = _norm(report_count, ROAD_NORM["report_count_6hr"])
        n_severity = _norm(avg_severity, ROAD_NORM["severity"])

        score = (
            n_reports  * ROAD_RISK_WEIGHTS["report_density"]
            + n_severity * ROAD_RISK_WEIGHTS["severity"]
            + n_rain     * ROAD_RISK_WEIGHTS["rainfall"]
        ) * 100
        score = min(100, max(0, round(score)))
        state = _classify(score)

        road_ward_risks.append({
            "ward_id": wid,
            "name": ward_info["name"],
            "risk_score": score,
            "state": state,
            "color": _color(state),
            "report_count": report_count,
            "avg_severity": avg_severity,
            "type": "road",
        })

    # ── Unified Priority Queue ──────────────────────────────────────────
    STATE_PRIORITY = {"Critical": 0, "Warning": 1, "Elevated": 2, "Normal": 3}

    priority = []

    # Dustbins in non-clear states
    for ds in dustbin_states:
        if ds["state"] in ("Reported", "Escalated", "Critical"):
            priority.append({
                "id": ds["dustbin_id"],
                "name": f"{ds['street']} ({ds['dustbin_id']})",
                "type": "waste",
                "risk_score": _dustbin_state_score(ds["state"]),
                "state": ds["state"],
                "color": ds["color"],
                "ward_id": ds["ward_id"],
                "report_count": ds["report_count"],
            })

    # Road issues by severity
    for ri in road_issues:
        priority.append({
            "id": ri["event_id"],
            "name": f"{ri['issue_type'].title()}: {ri['from_dustbin']} → {ri['to_dustbin']}",
            "type": "road",
            "risk_score": ri["severity"] * 20,
            "state": _classify(ri["severity"] * 20),
            "color": _color(_classify(ri["severity"] * 20)),
            "ward_id": ri["ward_id"],
            "issue_type": ri["issue_type"],
        })

    # Sort: Critical waste first, then by score
    priority.sort(key=lambda x: (
        0 if x["type"] == "waste" else 1,
        {"Critical": 0, "Escalated": 1, "Warning": 2, "Reported": 3, "Elevated": 4, "Normal": 5}.get(x["state"], 5),
        -x["risk_score"],
    ))
    priority = priority[:PRIORITY_QUEUE_MAX]

    # ── City-Level Indices ──────────────────────────────────────────────
    city_waste = round(sum(w["risk_score"] for w in ward_risks) / max(1, len(ward_risks)), 1)
    city_road  = round(sum(r["risk_score"] for r in road_ward_risks) / max(1, len(road_ward_risks)), 1)

    # ── Atomic Snapshot ─────────────────────────────────────────────────
    snapshot = {
        "dustbin_states": dustbin_states,
        "ward_risks": ward_risks,
        "road_ward_risks": road_ward_risks,
        "road_issues": road_issues,
        "priority_queue": priority,
        "city_waste_index": city_waste,
        "city_road_index": city_road,
        "rainfall_mm_hr": rainfall,
        "weather_source": _latest_weather.get("weather_source", "none"),
        "timestamp": datetime.now().isoformat(),
    }

    return snapshot


def _dustbin_color(state):
    """Dustbin state → color."""
    return {
        "Clear": "#16A34A",     # Green
        "Reported": "#D97706",  # Amber
        "Escalated": "#EA580C", # Orange
        "Critical": "#DC2626",  # Red
        "Cleared": "#06B6D4",   # Cyan (confirmed cleared)
    }.get(state, "#6B7280")


def _dustbin_state_score(state):
    """Convert dustbin state to numeric score for priority sorting."""
    return {
        "Clear": 0,
        "Reported": 30,
        "Escalated": 60,
        "Critical": 90,
        "Cleared": 0,
    }.get(state, 0)


# ═══════════════════════════════════════════════════════════════════════════
# PATHWAY PIPELINE — watches directories, triggers recomputation
# ═══════════════════════════════════════════════════════════════════════════
def _read_dir(label, path):
    """Read a watched directory as Pathway table."""
    os.makedirs(path, exist_ok=True)
    print(f"  [Pathway] Watching: {path} ({label})")
    return pw.io.fs.read(
        path,
        format="binary",
        mode="streaming",
        with_metadata=True,
    )


def _on_change_recompute(data: bytes) -> str:
    """
    Called by Pathway on every file change.
    Triggers full dashboard recomputation.
    Writes atomic snapshot to output.
    """
    try:
        snapshot = compute_dashboard_snapshot()
        _write_atomic_snapshot(snapshot)
        return json.dumps({"status": "ok", "timestamp": snapshot["timestamp"]})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def _write_atomic_snapshot(snapshot: dict):
    """Write dashboard snapshot atomically (temp file + rename)."""
    dashboard_path = os.path.join(OUTPUT_DIR, "dashboard.jsonl")
    try:
        # Write to temp file first
        fd, tmp_path = tempfile.mkstemp(dir=OUTPUT_DIR, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as tmp:
                tmp.write(json.dumps(snapshot) + "\n")
                tmp.flush()
        except Exception:
            os.close(fd)
            raise
        # Atomic rename
        os.replace(tmp_path, dashboard_path)
    except Exception as e:
        print(f"[Snapshot] Write error: {e}")
        # Fallback: direct write
        try:
            with open(dashboard_path, "w") as f:
                f.write(json.dumps(snapshot) + "\n")
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# STANDALONE RECOMPUTATION LOOP (runs alongside Pathway)
# ═══════════════════════════════════════════════════════════════════════════
def _recompute_loop():
    """
    Background thread: recompute dashboard every 3 seconds.
    This ensures updates even when Pathway's incremental triggers miss files.
    """
    while True:
        try:
            snapshot = compute_dashboard_snapshot()
            _write_atomic_snapshot(snapshot)
        except Exception as e:
            print(f"[Recompute] Error: {e}")
        time.sleep(3)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════
def main():
    print("═" * 60)
    print("  InfraWatch Nexus — Pathway Streaming Engine v3.0")
    print(f"  Pathway {pw.__version__}")
    print(f"  Dustbins: {len(DUSTBINS)}")
    print(f"  Wards: {len(WARDS)}")
    print("═" * 60)

    # Start weather poller
    weather_thread = threading.Thread(target=_weather_poller, daemon=True)
    weather_thread.start()
    print("  Weather poller started")

    # Start recomputation loop
    recompute_thread = threading.Thread(target=_recompute_loop, daemon=True)
    recompute_thread.start()
    print("  Recompute loop started (3s interval)")

    # Initial snapshot
    try:
        snapshot = compute_dashboard_snapshot()
        _write_atomic_snapshot(snapshot)
        print(f"  Initial snapshot written")
    except Exception as e:
        print(f"  Initial snapshot error: {e}")

    # ── Pathway: watch all directories for changes ─────────────────────
    waste_raw   = _read_dir("waste",   WASTE_DIR)
    road_raw    = _read_dir("road",    ROAD_DIR)
    van_raw     = _read_dir("vans",    VAN_DIR)
    weather_raw = _read_dir("weather", WEATHER_DIR)

    # When any file changes → trigger recomputation
    waste_result = waste_raw.select(
        result=pw.apply(_on_change_recompute, pw.this.data)
    )
    road_result = road_raw.select(
        result=pw.apply(_on_change_recompute, pw.this.data)
    )
    van_result = van_raw.select(
        result=pw.apply(_on_change_recompute, pw.this.data)
    )
    weather_result = weather_raw.select(
        result=pw.apply(_on_change_recompute, pw.this.data)
    )

    # Write Pathway processing log
    pw.io.jsonlines.write(waste_result, os.path.join(OUTPUT_DIR, "pw_waste_log.jsonl"))
    pw.io.jsonlines.write(road_result, os.path.join(OUTPUT_DIR, "pw_road_log.jsonl"))
    pw.io.jsonlines.write(van_result, os.path.join(OUTPUT_DIR, "pw_van_log.jsonl"))

    print("\n  ▶ Pathway pipeline running. Watching for events...\n")
    pw.run()


if __name__ == "__main__":
    main()
