"""
InfraWatch Nexus — Risk Scoring Engine
========================================
Ward-level waste and road risk scoring.
Monsoon-adaptive weights. Time-decay for recency.
Priority queue builder.
"""

from datetime import datetime
from config.settings import (
    WASTE_RISK_WEIGHTS, ROAD_RISK_WEIGHTS,
    WASTE_NORM, ROAD_NORM, STATE_BANDS,
    PRIORITY_QUEUE_MAX,
)


# ═══════════════════════════════════════════════════════════════════════════
# NORMALIZATION
# ═══════════════════════════════════════════════════════════════════════════
def norm(val, threshold):
    """Normalize value to 0-1, capped at 1.0."""
    if threshold <= 0:
        return 0.0
    return min(1.0, max(0.0, val / threshold))


def classify(score):
    """Score (0-100) → state label."""
    for band in STATE_BANDS:
        if band["min"] <= score <= band["max"]:
            return band["label"]
    return "Critical" if score > 100 else "Normal"


def state_color(state):
    """State label → color hex."""
    for band in STATE_BANDS:
        if band["label"] == state:
            return band["color"]
    return "#16A34A"


# ═══════════════════════════════════════════════════════════════════════════
# SEASONAL WEIGHTS (monsoon-adaptive)
# ═══════════════════════════════════════════════════════════════════════════
def get_waste_weights():
    """Return risk weights adjusted for monsoon season (June-Sept)."""
    month = datetime.now().month
    if 6 <= month <= 9:
        return {
            "report_freq": 0.25,
            "overflow_severity": 0.25,
            "collection_delay": 0.15,
            "rainfall": 0.35,
        }
    return WASTE_RISK_WEIGHTS


def get_road_weights():
    """Return road risk weights adjusted for monsoon season."""
    month = datetime.now().month
    if 6 <= month <= 9:
        return {
            "report_density": 0.45,
            "severity": 0.20,
            "rainfall": 0.35,
        }
    return ROAD_RISK_WEIGHTS


# ═══════════════════════════════════════════════════════════════════════════
# TIME-DECAY SCORING
# ═══════════════════════════════════════════════════════════════════════════
def time_decay_weight(event_dt, window_start_dt, window_end_dt):
    """
    Events closer to 'now' get higher weight.
    Returns weight in range [0.3, 1.0].
    """
    total = (window_end_dt - window_start_dt).total_seconds()
    if total <= 0:
        return 1.0
    elapsed = (event_dt - window_start_dt).total_seconds()
    recency = max(0.0, min(1.0, elapsed / total))
    return 0.3 + 0.7 * recency


# ═══════════════════════════════════════════════════════════════════════════
# WARD WASTE RISK
# ═══════════════════════════════════════════════════════════════════════════
def compute_ward_waste_risk(ward_id, ward_info, ward_dustbins,
                            latest_van_by_dustbin, dustbin_to_ward,
                            latest_waste_dt, n_rain):
    """Compute waste risk score for a single ward."""
    weights = get_waste_weights()

    total_reports = sum(d["report_count"] for d in ward_dustbins)
    overflow_vals = [d["avg_overflow"] for d in ward_dustbins if d["avg_overflow"] > 0]
    avg_overflow = round(sum(overflow_vals) / len(overflow_vals), 1) if overflow_vals else 0

    # Collection delay
    ward_van_times = [
        latest_van_by_dustbin[did]["dt"]
        for did in latest_van_by_dustbin
        if dustbin_to_ward.get(did) == ward_id
    ]
    if ward_van_times:
        latest_van_dt = max(ward_van_times)
        delay_hr = max(0, round(
            (latest_waste_dt - latest_van_dt).total_seconds() / 3600.0, 1
        ))
    else:
        delay_hr = 6.0

    # Active vans (collected within 2 hours)
    active_vans = sum(
        1 for did in latest_van_by_dustbin
        if dustbin_to_ward.get(did) == ward_id
        and (latest_waste_dt - latest_van_by_dustbin[did]["dt"]).total_seconds() < 7200
    )

    n_reports = norm(total_reports, WASTE_NORM["report_count_2hr"])
    n_overflow = norm(avg_overflow, WASTE_NORM["overflow_level"])
    n_delay = norm(delay_hr, WASTE_NORM["collection_delay_hr"])

    score = (
        n_reports * weights["report_freq"]
        + n_overflow * weights["overflow_severity"]
        + n_delay * weights["collection_delay"]
        + n_rain * weights["rainfall"]
    ) * 100
    score = min(100, max(0, round(score)))
    state = classify(score)

    bins_reported = len([d for d in ward_dustbins if d["state"] not in ("Clear", "Cleared")])

    return {
        "ward_id": ward_id,
        "name": ward_info["name"],
        "zone": ward_info["zone"],
        "lat": ward_info["lat"],
        "lng": ward_info["lng"],
        "bins": ward_info["bins"],
        "risk_score": score,
        "state": state,
        "color": state_color(state),
        "report_count": total_reports,
        "avg_overflow": avg_overflow,
        "collection_delay_hr": delay_hr,
        "active_vans": active_vans,
        "bins_reported": bins_reported,
        "type": "waste",
    }


# ═══════════════════════════════════════════════════════════════════════════
# WARD ROAD RISK
# ═══════════════════════════════════════════════════════════════════════════
def compute_ward_road_risk(ward_id, ward_info, road_by_ward, n_rain):
    """Compute road risk for a single ward."""
    weights = get_road_weights()

    r = road_by_ward.get(ward_id, {})
    report_count = r.get("count", 0)
    avg_severity = round(
        r.get("total_severity", 0) / max(1, report_count), 1
    ) if report_count else 0

    n_reports = norm(report_count, ROAD_NORM["report_count_6hr"])
    n_severity = norm(avg_severity, ROAD_NORM["severity"])

    score = (
        n_reports * weights["report_density"]
        + n_severity * weights["severity"]
        + n_rain * weights["rainfall"]
    ) * 100
    score = min(100, max(0, round(score)))
    state = classify(score)

    return {
        "ward_id": ward_id,
        "name": ward_info["name"],
        "risk_score": score,
        "state": state,
        "color": state_color(state),
        "report_count": report_count,
        "avg_severity": avg_severity,
        "type": "road",
    }


# ═══════════════════════════════════════════════════════════════════════════
# PRIORITY QUEUE
# ═══════════════════════════════════════════════════════════════════════════
def build_priority_queue(dustbin_states, road_issues, max_items=PRIORITY_QUEUE_MAX):
    """Build unified priority queue sorted by risk."""
    from engine.state_machine import get_dustbin_state_score

    priority = []

    for ds in dustbin_states:
        if ds["state"] in ("Reported", "Escalated", "Critical"):
            base_score = get_dustbin_state_score(ds["state"])
            ai_conf = ds.get("ai_avg_confidence", 0.0)
            ai_count = ds.get("ai_verified_count", 0)
            ai_boost = round(min(15, ai_conf * 15)) if ai_count > 0 else 0
            score = min(100, base_score + ai_boost)
            priority.append({
                "id": ds["dustbin_id"],
                "name": f"{ds['street']} ({ds['dustbin_id']})",
                "type": "waste",
                "risk_score": score,
                "state": ds["state"],
                "color": ds["color"],
                "ward_id": ds["ward_id"],
                "report_count": ds["report_count"],
                "ai_verified_count": ai_count,
                "ai_avg_confidence": ai_conf,
            })

    for ri in road_issues:
        score = ri["severity"] * 20
        state = classify(score)
        priority.append({
            "id": ri["event_id"],
            "name": f"{ri['issue_type'].title()}: {ri['from_dustbin']} -> {ri['to_dustbin']}",
            "type": "road",
            "risk_score": score,
            "state": state,
            "color": state_color(state),
            "ward_id": ri["ward_id"],
            "issue_type": ri["issue_type"],
        })

    priority.sort(key=lambda x: (
        0 if x["type"] == "waste" else 1,
        {"Critical": 0, "Escalated": 1, "Warning": 2, "Reported": 3,
         "Elevated": 4, "Normal": 5}.get(x["state"], 5),
        -x["risk_score"],
    ))

    return priority[:max_items]
