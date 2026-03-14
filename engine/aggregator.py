"""
InfraWatch Nexus — Dashboard Aggregator
=========================================
Reads event sources, computes dustbin states, ward risks, and full dashboard.
Uses extracted modules for state machine, risk scoring, and weather.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from config.settings import (
    WASTE_NORM, WASTE_REPORT_WINDOW_HOURS, ROAD_ISSUE_WINDOW_HOURS, ROAD_NORM,
)
from config.wards import WARDS
from config.dustbins import DUSTBINS

from engine.state_machine import compute_dustbin_state, get_dustbin_color
from engine.risk_engine import (
    norm, compute_ward_waste_risk, compute_ward_road_risk,
    build_priority_queue,
)
from engine.weather import get_latest_weather


# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
DUSTBIN_IDS = list(DUSTBINS.keys())
DUSTBIN_TO_WARD = {did: info["ward_id"] for did, info in DUSTBINS.items()}


# ═══════════════════════════════════════════════════════════════════════════
# TIMESTAMP PARSING
# ═══════════════════════════════════════════════════════════════════════════
def _parse_ts(ts_str):
    """Safely parse ISO string to timezone-aware datetime."""
    if not ts_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


# ═══════════════════════════════════════════════════════════════════════════
# FILE READERS
# ═══════════════════════════════════════════════════════════════════════════
def _read_all_events(directory):
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
# CORE COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════
def compute_dashboard_snapshot(waste_dir, road_dir, van_dir):
    """
    Read all event files and compute complete dashboard state.
    Uses event-time windowing and extracted engine modules.
    """
    waste_events = _read_all_events(waste_dir)
    van_events = _read_all_events(van_dir)
    road_events = _read_all_events(road_dir)

    # Weather
    weather = get_latest_weather()
    rainfall = weather.get("rainfall_mm_hr", 0.0)
    rainfall_capped = min(rainfall, WASTE_NORM["rainfall_mm_hr"])
    n_rain = norm(rainfall_capped, WASTE_NORM["rainfall_mm_hr"])

    # Event-time windows
    waste_dts = [_parse_ts(e.get("timestamp", "")) for e in waste_events
                 if e.get("timestamp")]
    latest_waste_dt = max(waste_dts) if waste_dts else datetime.now(timezone.utc)
    waste_window_start = latest_waste_dt - timedelta(hours=WASTE_REPORT_WINDOW_HOURS)

    road_dts = [_parse_ts(e.get("timestamp", "")) for e in road_events
                if e.get("timestamp")]
    latest_road_dt = max(road_dts) if road_dts else datetime.now(timezone.utc)
    road_window_start = latest_road_dt - timedelta(hours=ROAD_ISSUE_WINDOW_HOURS)

    # Van collection (latest per dustbin)
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

    # ── Dustbin aggregation ──────────────────────────────────────────
    dustbin_agg = {}
    for e in waste_events:
        ts_dt = _parse_ts(e.get("timestamp", ""))
        if ts_dt < waste_window_start:
            continue
        did = e.get("dustbin_id", "")
        if not did or did not in DUSTBINS:
            continue
        if did not in dustbin_agg:
            dustbin_agg[did] = {
                "report_count": 0, "max_overflow": 0,
                "total_overflow": 0, "latest_ts": "", "latest_dt": _parse_ts(""),
                "ai_verified_count": 0, "ai_confidence_sum": 0.0,
            }
        agg = dustbin_agg[did]
        agg["report_count"] += 1
        overflow = e.get("overflow_level", 1)
        agg["max_overflow"] = max(agg["max_overflow"], overflow)
        agg["total_overflow"] += overflow
        if e.get("ai_verified"):
            agg["ai_verified_count"] += 1
            agg["ai_confidence_sum"] += float(e.get("yolo_confidence") or 0.0)
        if ts_dt > agg["latest_dt"]:
            agg["latest_ts"] = e.get("timestamp", "")
            agg["latest_dt"] = ts_dt

    # ── Dustbin states (uses state_machine module) ───────────────────
    dustbin_states = []
    for did in DUSTBIN_IDS:
        agg = dustbin_agg.get(did, {})
        report_count = agg.get("report_count", 0)
        max_overflow = agg.get("max_overflow", 0)
        avg_overflow = (round(agg.get("total_overflow", 0) / max(1, report_count), 1)
                        if report_count else 0)

        # Van-cleared check
        van_data = latest_van_by_dustbin.get(did, {})
        van_ts = van_data.get("ts", "")
        van_dt = van_data.get("dt", None)
        latest_report_dt = agg.get("latest_dt", None)
        van_cleared = bool(van_dt and (not latest_report_dt or van_dt > latest_report_dt))

        state = compute_dustbin_state(
            did, report_count, max_overflow, rainfall, van_cleared=van_cleared
        )

        info = DUSTBINS[did]
        ai_v = agg.get("ai_verified_count", 0)
        ai_conf = round(agg.get("ai_confidence_sum", 0.0) / max(1, ai_v), 2) if ai_v else 0.0

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
            "color": get_dustbin_color(state),
            "ai_verified_count": ai_v,
            "ai_avg_confidence": ai_conf,
        })

    # ── Ward waste risks (uses risk_engine module) ───────────────────
    ward_risks = []
    for wid, winfo in WARDS.items():
        ward_dustbins = [d for d in dustbin_states if d["ward_id"] == wid]
        risk = compute_ward_waste_risk(
            wid, winfo, ward_dustbins,
            latest_van_by_dustbin, DUSTBIN_TO_WARD,
            latest_waste_dt, n_rain,
        )
        ward_risks.append(risk)

    # ── Road issues (windowed) ───────────────────────────────────────
    road_issues = []
    road_by_ward = {}
    cleared_ids = {e.get("event_id", "") for e in road_events
                   if e.get("event_type") == "road_cleared"}

    for e in road_events:
        if e.get("event_type") == "road_cleared":
            continue
        eid = e.get("event_id", "")
        if eid in cleared_ids:
            continue
        ts_dt = _parse_ts(e.get("timestamp", ""))
        if ts_dt < road_window_start:
            continue

        from_bin = e.get("from_dustbin", "")
        to_bin = e.get("to_dustbin", "")
        ward_id = e.get("ward_id", "")
        if not from_bin or not to_bin:
            continue

        from_info = DUSTBINS.get(from_bin, {})
        to_info = DUSTBINS.get(to_bin, {})

        road_issues.append({
            "event_id": eid,
            "from_dustbin": from_bin,
            "to_dustbin": to_bin,
            "from_lat": from_info.get("lat", 0),
            "from_lng": from_info.get("lng", 0),
            "to_lat": to_info.get("lat", 0),
            "to_lng": to_info.get("lng", 0),
            "ward_id": ward_id,
            "issue_type": e.get("issue_type", ""),
            "severity": e.get("severity", 1),
            "timestamp": e.get("timestamp", ""),
        })

        if ward_id not in road_by_ward:
            road_by_ward[ward_id] = {"count": 0, "total_severity": 0}
        road_by_ward[ward_id]["count"] += 1
        road_by_ward[ward_id]["total_severity"] += e.get("severity", 1)

    # ── Road ward risks ──────────────────────────────────────────────
    road_ward_risks = []
    for wid, winfo in WARDS.items():
        risk = compute_ward_road_risk(wid, winfo, road_by_ward, n_rain)
        road_ward_risks.append(risk)

    # ── Priority queue ───────────────────────────────────────────────
    priority = build_priority_queue(dustbin_states, road_issues)

    # ── City indices ─────────────────────────────────────────────────
    city_waste = round(
        sum(w["risk_score"] for w in ward_risks) / max(1, len(ward_risks)), 1
    )
    city_road = round(
        sum(r["risk_score"] for r in road_ward_risks) / max(1, len(road_ward_risks)), 1
    )

    return {
        "dustbin_states": dustbin_states,
        "ward_risks": ward_risks,
        "road_ward_risks": road_ward_risks,
        "road_issues": road_issues,
        "priority_queue": priority,
        "city_waste_index": city_waste,
        "city_road_index": city_road,
        "rainfall_mm_hr": rainfall,
        "weather_source": weather.get("weather_source", "none"),
        "timestamp": datetime.now().isoformat(),
    }
