"""
InfraWatch Nexus — Comprehensive Test Suite
=============================================
Tests for state machine, risk engine, spatial utils,
route optimizer, auth, and API endpoints.
"""

import pytest
import sys
import os
import json
import math

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from api.server import app

client = TestClient(app)


# ═══════════════════════════════════════════════════════════════════════════
# API ENDPOINT TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_health_check():
    """Verify health endpoint returns 200 OK and expected fields."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "4.0"
    assert "timestamp" in data
    assert "cache_entries" in data


def test_unauthorized_admin_access():
    """Verify road issue endpoint blocks unauthenticated requests."""
    response = client.post("/api/report/road-issue", json={
        "from_dustbin": "MCD-DL-1000",
        "to_dustbin": "MCD-DL-1001",
        "issue_type": "pothole",
        "severity": 5,
    })
    assert response.status_code == 401


def test_dashboard_endpoint():
    """Verify dashboard returns valid JSON structure."""
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert "dustbin_states" in data
    assert "ward_risks" in data


def test_config_endpoint():
    """Verify config returns wards and dustbins."""
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "wards" in data
    assert "dustbins" in data
    assert "city_center" in data
    assert len(data["wards"]) == 12


def test_dustbins_endpoint():
    """Verify dustbins endpoint returns registry."""
    response = client.get("/api/dustbins")
    assert response.status_code == 200
    data = response.json()
    assert "dustbins" in data


def test_priority_endpoint():
    """Verify priority queue endpoint."""
    response = client.get("/api/priority")
    assert response.status_code == 200
    data = response.json()
    assert "priority_queue" in data


def test_route_optimize_endpoint():
    """Verify VRP route optimization returns valid structure."""
    response = client.get("/api/route/optimize")
    assert response.status_code == 200
    data = response.json()
    assert "routes" in data or "route" in data


def test_route_optimize_ward():
    """Verify per-ward route optimization."""
    response = client.get("/api/route/optimize/W01")
    assert response.status_code == 200
    data = response.json()
    assert "route" in data
    route = data["route"]
    assert "stops" in route
    assert "total_distance_m" in route
    assert "estimated_time_min" in route


def test_route_optimize_invalid_ward():
    """Verify invalid ward returns 400."""
    response = client.get("/api/route/optimize/W99")
    assert response.status_code == 400


def test_invalid_dustbin_report():
    """Verify invalid dustbin ID returns 400."""
    response = client.post("/api/report/dustbin/confirm", json={
        "dustbin_id": "INVALID-ID",
        "overflow_level": 3,
    })
    assert response.status_code == 400
    data = response.json()
    assert "error" in data


# ═══════════════════════════════════════════════════════════════════════════
# STATE MACHINE TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_state_machine_clear():
    """Zero reports = Clear state."""
    from engine.state_machine import compute_dustbin_state
    state = compute_dustbin_state("TEST-001", 0, 0, 0.0)
    assert state == "Clear"


def test_state_machine_reported():
    """1+ reports = Reported state."""
    from engine.state_machine import compute_dustbin_state
    state = compute_dustbin_state("TEST-002", 1, 2, 0.0)
    assert state == "Reported"


def test_state_machine_escalated():
    """3+ reports = Escalated state."""
    from engine.state_machine import compute_dustbin_state
    state = compute_dustbin_state("TEST-003", 3, 2, 0.0)
    assert state == "Escalated"


def test_state_machine_critical():
    """5+ reports = Critical state."""
    from engine.state_machine import compute_dustbin_state
    state = compute_dustbin_state("TEST-004", 5, 5, 0.0)
    assert state == "Critical"


def test_state_machine_van_cleared():
    """Van collection overrides everything."""
    from engine.state_machine import compute_dustbin_state
    state = compute_dustbin_state("TEST-005", 10, 5, 50.0, van_cleared=True)
    assert state == "Cleared"


def test_state_machine_rain_escalation():
    """Heavy rain upgrades Escalated to Critical."""
    from engine.state_machine import compute_dustbin_state
    state = compute_dustbin_state("TEST-006", 3, 4, 15.0)
    assert state == "Critical"


def test_state_machine_overflow_escalation():
    """High overflow (>=4) triggers Escalated."""
    from engine.state_machine import compute_dustbin_state
    state = compute_dustbin_state("TEST-007", 2, 4, 0.0)
    assert state == "Escalated"


# ═══════════════════════════════════════════════════════════════════════════
# RISK ENGINE TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_norm_basic():
    """Normalization clamps to [0, 1]."""
    from engine.risk_engine import norm
    assert norm(0, 10) == 0.0
    assert norm(5, 10) == 0.5
    assert norm(10, 10) == 1.0
    assert norm(20, 10) == 1.0  # Capped
    assert norm(-5, 10) == 0.0  # Floor


def test_norm_zero_threshold():
    """Zero threshold returns 0."""
    from engine.risk_engine import norm
    assert norm(5, 0) == 0.0


def test_classify():
    """Score classification into state bands."""
    from engine.risk_engine import classify
    assert classify(0) == "Normal"
    assert classify(15) == "Normal"
    assert classify(35) == "Elevated"
    assert classify(60) == "Warning"
    assert classify(80) == "Critical"


def test_priority_queue_sorting():
    """Priority queue sorts Critical waste first."""
    from engine.risk_engine import build_priority_queue

    dustbins = [
        {"dustbin_id": "D1", "state": "Reported", "street": "A", "color": "#D97706",
         "ward_id": "W01", "report_count": 1, "ai_verified_count": 0, "ai_avg_confidence": 0},
        {"dustbin_id": "D2", "state": "Critical", "street": "B", "color": "#DC2626",
         "ward_id": "W01", "report_count": 5, "ai_verified_count": 0, "ai_avg_confidence": 0},
    ]
    queue = build_priority_queue(dustbins, [])
    assert len(queue) == 2
    assert queue[0]["id"] == "D2"  # Critical first
    assert queue[0]["risk_score"] > queue[1]["risk_score"]


# ═══════════════════════════════════════════════════════════════════════════
# SPATIAL TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_haversine_zero():
    """Same point = 0 distance."""
    from engine.spatial import haversine_m
    assert haversine_m(28.6, 77.2, 28.6, 77.2) == 0.0


def test_haversine_known_distance():
    """Known Delhi distance: India Gate to Qutub Minar ~15km."""
    from engine.spatial import haversine_m
    d = haversine_m(28.6129, 77.2295, 28.5245, 77.1855)
    assert 10000 < d < 12000  # Roughly 10-12 km


def test_find_nearby():
    """Spatial dedup finds issues within threshold."""
    from engine.spatial import find_nearby_issues
    existing = [
        {"from_lat": 28.6130, "from_lng": 77.2296},
        {"from_lat": 28.7000, "from_lng": 77.3000},
    ]
    new = {"from_lat": 28.6131, "from_lng": 77.2297}
    nearby = find_nearby_issues(new, existing, threshold_m=500)
    assert len(nearby) == 1


# ═══════════════════════════════════════════════════════════════════════════
# AUTH TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_auth_legacy_token():
    """Legacy ADMIN_TOKEN should still work. demotoken123 backdoor removed (security fix #2)."""
    from engine.auth import verify_token
    assert verify_token("INFRAWATCH_ADMIN_2026") is True
    assert verify_token("demotoken123") is False   # Backdoor removed — must reject
    assert verify_token("wrong_token") is False


def test_auth_hmac_roundtrip():
    """Generate + verify HMAC token."""
    from engine.auth import generate_token, verify_token
    token = generate_token("admin")
    assert verify_token(token) is True


def test_auth_invalid_hmac():
    """Tampered HMAC token must fail."""
    from engine.auth import generate_token, verify_token
    token = generate_token("admin")
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    assert verify_token(tampered) is False


def test_auth_empty():
    """Empty/None tokens fail."""
    from engine.auth import verify_token
    assert verify_token("") is False
    assert verify_token(None) is False


# ═══════════════════════════════════════════════════════════════════════════
# ROUTE OPTIMIZER (VRP) TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_vrp_empty():
    """No actionable bins = empty route."""
    from engine.route_optimizer import optimize_route
    dustbins = [
        {"dustbin_id": "D1", "lat": 28.6, "lng": 77.2, "state": "Clear",
         "street": "A", "ward_id": "W01", "report_count": 0},
    ]
    result = optimize_route(dustbins, 28.6, 77.2, ward_id="W01")
    assert result["route"] == []
    assert result["total_distance_m"] == 0


def test_vrp_single_critical():
    """Single critical bin = route with 1 stop."""
    from engine.route_optimizer import optimize_route
    dustbins = [
        {"dustbin_id": "D1", "lat": 28.61, "lng": 77.21, "state": "Critical",
         "street": "A", "ward_id": "W01", "report_count": 5},
    ]
    result = optimize_route(dustbins, 28.6, 77.2, ward_id="W01")
    assert len(result["route"]) == 1
    assert result["route"][0] == "D1"
    assert result["total_distance_m"] > 0
    assert result["estimated_time_min"] > 0


def test_vrp_priority_ordering():
    """Critical bins should be visited before Reported bins."""
    from engine.route_optimizer import optimize_route
    dustbins = [
        {"dustbin_id": "D1", "lat": 28.60, "lng": 77.20, "state": "Reported",
         "street": "A", "ward_id": "W01", "report_count": 1},
        {"dustbin_id": "D2", "lat": 28.61, "lng": 77.21, "state": "Critical",
         "street": "B", "ward_id": "W01", "report_count": 5},
    ]
    result = optimize_route(dustbins, 28.60, 77.20, ward_id="W01")
    assert len(result["route"]) == 2
    # Critical should be first (or at least higher-scored)
    assert result["stops"][0]["state"] == "Critical"


def test_vrp_all_wards():
    """Multi-ward optimization returns dict of ward routes."""
    from engine.route_optimizer import optimize_all_wards
    dustbins = [
        {"dustbin_id": "D1", "lat": 28.73, "lng": 77.12, "state": "Critical",
         "street": "A", "ward_id": "W01", "report_count": 5},
        {"dustbin_id": "D2", "lat": 28.65, "lng": 77.19, "state": "Escalated",
         "street": "B", "ward_id": "W02", "report_count": 3},
    ]
    from config.wards import WARDS
    results = optimize_all_wards(dustbins, WARDS)
    assert isinstance(results, dict)
    # Should have routes for W01 and W02 (the wards with actionable bins)
    assert "W01" in results or "W02" in results


# ═══════════════════════════════════════════════════════════════════════════
# DATABASE TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_db_init():
    """Database initializes without errors."""
    from engine.database import init_db
    init_db()  # Should not raise


def test_db_insert_and_count():
    """Insert event and verify count."""
    from engine.database import init_db, insert_event, get_event_count
    init_db()
    event = {
        "event_id": f"TEST-{os.urandom(4).hex()}",
        "dustbin_id": "MCD-DL-1000",
        "ward_id": "W05",
        "overflow_level": 3,
        "timestamp": "2026-03-14T12:00:00",
    }
    insert_event("waste", event)
    count = get_event_count("waste")
    assert count >= 1
