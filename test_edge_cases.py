import os
import json
import shutil
from datetime import datetime, timedelta, timezone

# Override directories for testing
os.environ["WX_API_KEY"] = "" # Disable actual api
import pathway_engine
import api.server

# Mock directories
TEST_DIR = os.path.join(os.path.dirname(__file__), "test_data")
for d in ["waste", "road", "vans", "weather"]:
    os.makedirs(os.path.join(TEST_DIR, d), exist_ok=True)

pathway_engine.WASTE_DIR = os.path.join(TEST_DIR, "waste")
pathway_engine.ROAD_DIR = os.path.join(TEST_DIR, "road")
pathway_engine.VAN_DIR = os.path.join(TEST_DIR, "vans")
pathway_engine.WEATHER_DIR = os.path.join(TEST_DIR, "weather")

api.server.WASTE_REPORT_DIR = os.path.join(TEST_DIR, "waste")
api.server.ROAD_REPORT_DIR = os.path.join(TEST_DIR, "road")
api.server.VAN_LOG_DIR = os.path.join(TEST_DIR, "vans")

def clear_test_data():
    for d in ["waste", "road", "vans", "weather"]:
        dpath = os.path.join(TEST_DIR, d)
        for f in os.listdir(dpath):
            os.remove(os.path.join(dpath, f))

def write_event(dir_path, data):
    with open(os.path.join(dir_path, f"{datetime.now().timestamp()}.json"), "w") as f:
        json.dump([data], f)

def write_weather(rain):
    pathway_engine._latest_weather = {"rainfall_mm_hr": rain, "timestamp": datetime.now(timezone.utc).isoformat()}

def run_tests():
    print("Running Edge Case Tests...")
    now = datetime.now(timezone.utc)
    did = pathway_engine.DUSTBIN_IDS[0] # Test dustbin
    
    # ── TEST 1: Escalation Logic ──
    print("Test 1: Escalation Logic")
    clear_test_data()
    write_weather(0.0)
    for i in range(1): write_event(pathway_engine.WASTE_DIR, {"dustbin_id": did, "overflow_level": 1, "timestamp": now.isoformat()})
    snap = pathway_engine.compute_dashboard_snapshot()
    bin_state = next(d for d in snap["dustbin_states"] if d["dustbin_id"] == did)["state"]
    assert bin_state == "Reported", f"Expected Reported, got {bin_state}"
    
    for i in range(2): write_event(pathway_engine.WASTE_DIR, {"dustbin_id": did, "overflow_level": 1, "timestamp": now.isoformat()})
    snap = pathway_engine.compute_dashboard_snapshot()
    bin_state = next(d for d in snap["dustbin_states"] if d["dustbin_id"] == did)["state"]
    assert bin_state == "Escalated", f"Expected Escalated, got {bin_state}"

    for i in range(2): write_event(pathway_engine.WASTE_DIR, {"dustbin_id": did, "overflow_level": 1, "timestamp": now.isoformat()})
    snap = pathway_engine.compute_dashboard_snapshot()
    bin_state = next(d for d in snap["dustbin_states"] if d["dustbin_id"] == did)["state"]
    assert bin_state == "Critical", f"Expected Critical, got {bin_state}"
    print("  ✅ Passed")

    # ── TEST 2: Expiry Logic ──
    print("Test 2: Expiry Logic")
    clear_test_data()
    old_ts = (now - timedelta(hours=3)).isoformat() # 3 hours old, window is 2 hours
    for i in range(5): write_event(pathway_engine.WASTE_DIR, {"dustbin_id": did, "overflow_level": 1, "timestamp": old_ts})
    
    # ADVANCE EVENT-TIME: Write a current event for a different dustbin
    write_event(pathway_engine.WASTE_DIR, {"dustbin_id": pathway_engine.DUSTBIN_IDS[1], "overflow_level": 1, "timestamp": now.isoformat()})
    
    snap = pathway_engine.compute_dashboard_snapshot()
    bin_state = next(d for d in snap["dustbin_states"] if d["dustbin_id"] == did)["state"]
    assert bin_state == "Clear", f"Expected Clear, got {bin_state} (reports should have expired)"
    print("  ✅ Passed")

    # ── TEST 3 & 5: Van Override AND Rain Resurrection check ──
    print("Test 3 & 5: Van Override & Rain Check")
    clear_test_data()
    write_weather(0.0)
    # 5 reports -> Critical
    for i in range(5): write_event(pathway_engine.WASTE_DIR, {"dustbin_id": did, "overflow_level": 1, "timestamp": (now - timedelta(minutes=30)).isoformat()})
    snap = pathway_engine.compute_dashboard_snapshot()
    bin_state = next(d for d in snap["dustbin_states"] if d["dustbin_id"] == did)["state"]
    assert bin_state == "Critical", "Should be Critical"
    
    # Van clears it
    write_event(pathway_engine.VAN_DIR, {"event_type": "collection_confirmed", "dustbin_id": did, "timestamp": (now - timedelta(minutes=15)).isoformat()})
    snap = pathway_engine.compute_dashboard_snapshot()
    bin_state = next(d for d in snap["dustbin_states"] if d["dustbin_id"] == did)["state"]
    assert bin_state == "Cleared", f"Expected Cleared, got {bin_state}"
    
    # Rain increases! Should STILL be Cleared, not resurrected.
    write_weather(15.0)
    snap = pathway_engine.compute_dashboard_snapshot()
    bin_state = next(d for d in snap["dustbin_states"] if d["dustbin_id"] == did)["state"]
    assert bin_state == "Cleared", f"Rain resurrected bin! UI bug. State = {bin_state}"
    print("  ✅ Passed")

    # ── TEST 6: Road Expiry ──
    print("Test 6: Road Expiry")
    clear_test_data()
    # Expired road issue
    old_road_ts = (now - timedelta(hours=7)).isoformat()
    write_event(pathway_engine.ROAD_DIR, {"event_id":"r1", "from_dustbin": did, "to_dustbin": pathway_engine.DUSTBIN_IDS[1], "ward_id":"W01", "issue_type":"pothole", "timestamp": old_road_ts})
    
    # ADVANCE ROAD EVENT-TIME: Write a current road event
    write_event(pathway_engine.ROAD_DIR, {"event_id":"r2", "from_dustbin": did, "to_dustbin": pathway_engine.DUSTBIN_IDS[1], "ward_id":"W01", "issue_type":"pothole", "timestamp": now.isoformat()})
    
    snap = pathway_engine.compute_dashboard_snapshot()
    issues = [r.get("event_id") for r in snap["road_issues"]]
    assert "r1" not in issues, "Road issue r1 should have expired"
    print("  ✅ Passed")

    # ── TEST 4: Dedup Restart Logic ──
    print("Test 4: Dedup Restart Logic (FastAPI)")
    clear_test_data()
    # Write a report to waste dir that is explicitly within dedup window
    api.server._last_report.clear()
    write_event(api.server.WASTE_REPORT_DIR, {"dustbin_id": did, "overflow_level": 3, "timestamp": now.isoformat()})
    # Rebuild cache as if server just restarted
    api.server._rebuild_dedup_cache()
    # Check if duplicate is blocked
    is_dup = api.server._is_duplicate(did, 3)
    assert is_dup is True, "Rebuild failed to cache recent file, so duplication wasn't blocked"
    print("  ✅ Passed")

    print("ALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()
