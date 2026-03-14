"""
InfraWatch Nexus — Pathway Streaming Engine (Orchestrator)
===========================================================
Thin orchestrator. All computation lives in engine/ package.

Responsibilities:
  - Initialize database
  - Start weather poller
  - Start recomputation loop
  - Wire Pathway file watchers to trigger recomputation
  - Write atomic dashboard snapshots
"""

import json
import os
import sys
import threading
import time

import pathway as pw

# Project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from config.wards import WARDS
from config.dustbins import DUSTBINS
from engine.aggregator import compute_dashboard_snapshot
from engine.weather import start_weather_poller
from engine.snapshot import write_atomic_snapshot
from engine.database import init_db, save_daily_snapshot
from engine.route_optimizer import optimize_all_wards

# ═══════════════════════════════════════════════════════════════════════════
# DIRECTORIES
# ═══════════════════════════════════════════════════════════════════════════
BASE       = os.path.dirname(os.path.abspath(__file__))
WASTE_DIR  = os.path.join(BASE, "data", "reports", "waste")
ROAD_DIR   = os.path.join(BASE, "data", "reports", "road")
VAN_DIR    = os.path.join(BASE, "data", "reports", "vans")
WEATHER_DIR = os.path.join(BASE, "data", "reports", "weather")
OUTPUT_DIR = os.path.join(BASE, "data", "output")

for d in [WASTE_DIR, ROAD_DIR, VAN_DIR, WEATHER_DIR, OUTPUT_DIR]:
    os.makedirs(d, exist_ok=True)

# Track last daily snapshot date
_last_daily_snapshot_date = ""


# ═══════════════════════════════════════════════════════════════════════════
# RECOMPUTE + DAILY SNAPSHOT
# ═══════════════════════════════════════════════════════════════════════════
def _do_recompute():
    """Run one recomputation cycle. Returns snapshot dict."""
    global _last_daily_snapshot_date
    snapshot = compute_dashboard_snapshot(WASTE_DIR, ROAD_DIR, VAN_DIR)

    # Add optimized routes to snapshot
    try:
        routes = optimize_all_wards(snapshot.get("dustbin_states", []), WARDS)
        snapshot["optimized_routes"] = routes
    except Exception as e:
        print(f"  [VRP] Route optimization error: {e}")
        snapshot["optimized_routes"] = {}

    write_atomic_snapshot(snapshot, OUTPUT_DIR)

    # Save daily snapshot (once per day)
    today = time.strftime("%Y-%m-%d")
    if today != _last_daily_snapshot_date:
        try:
            save_daily_snapshot(snapshot)
            _last_daily_snapshot_date = today
            print(f"  [DB] Daily snapshot saved for {today}")
        except Exception as e:
            print(f"  [DB] Daily snapshot error: {e}")

    return snapshot


def _on_change_recompute(data: bytes) -> str:
    """Called by Pathway on every file change."""
    try:
        snapshot = _do_recompute()
        return json.dumps({"status": "ok", "timestamp": snapshot["timestamp"]})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def _recompute_loop():
    """Background thread: recompute dashboard every 3 seconds."""
    while True:
        try:
            _do_recompute()
        except Exception as e:
            print(f"  [Recompute] Error: {e}")
        time.sleep(3)


# ═══════════════════════════════════════════════════════════════════════════
# PATHWAY PIPELINE
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


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("  InfraWatch Nexus -- Pathway Streaming Engine v4.0")
    print(f"  Pathway {pw.__version__}")
    print(f"  Dustbins: {len(DUSTBINS)}")
    print(f"  Wards: {len(WARDS)}")
    print(f"  Modules: engine/ (9 modules)")
    print("=" * 60)

    # Initialize database
    try:
        init_db()
        print("  SQLite DB initialized (WAL mode)")
    except Exception as e:
        print(f"  SQLite init error: {e}")

    # Start weather poller
    start_weather_poller(WEATHER_DIR)

    # Start recomputation loop
    recompute_thread = threading.Thread(target=_recompute_loop, daemon=True)
    recompute_thread.start()
    print("  Recompute loop started (3s interval)")

    # Initial snapshot
    try:
        snapshot = _do_recompute()
        routes = snapshot.get("optimized_routes", {})
        active_routes = len([r for r in routes.values() if r.get("route")])
        print(f"  Initial snapshot written (VRP: {active_routes} active routes)")
    except Exception as e:
        print(f"  Initial snapshot error: {e}")

    # Pathway: watch all directories
    waste_raw = _read_dir("waste", WASTE_DIR)
    road_raw = _read_dir("road", ROAD_DIR)
    van_raw = _read_dir("vans", VAN_DIR)
    weather_raw = _read_dir("weather", WEATHER_DIR)

    # When any file changes -> trigger recomputation
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

    print("\n  Pathway pipeline running. Watching for events...\n")
    pw.run()


if __name__ == "__main__":
    main()
