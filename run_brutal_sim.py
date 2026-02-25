import os
import json
import time
import random
from datetime import datetime, timezone

# Use absolute paths to the same dirs the server uses
PROJECT = os.path.dirname(os.path.abspath(__file__))
WASTE_DIR = os.path.join(PROJECT, "data", "reports", "waste")
ROAD_DIR = os.path.join(PROJECT, "data", "reports", "road")

# Create dirs if missing
os.makedirs(WASTE_DIR, exist_ok=True)
os.makedirs(ROAD_DIR, exist_ok=True)

DUSTBIN_IDS = [f"MCD-W{str(w).zfill(2)}-{str(d).zfill(3)}" for w in range(1, 13) for d in range(1, 7)]

print("🔥 STARTING BRUTAL LOAD SIMULATION...")
print(f"Target dirs:\n  {WASTE_DIR}\n  {ROAD_DIR}")

# Generate 20 rapid events (15 waste, 5 road)
for i in range(20):
    now = datetime.now(timezone.utc).isoformat()
    if i < 15:
        did = random.choice(DUSTBIN_IDS)
        data = {"dustbin_id": did, "overflow_level": random.randint(1, 4), "timestamp": now}
        fpath = os.path.join(WASTE_DIR, f"sim_waste_{i}_{int(time.time()*1000)}.json")
    else:
        did1 = random.choice(DUSTBIN_IDS)
        did2 = random.choice(DUSTBIN_IDS)
        data = {"event_id": f"sim_r_{i}", "from_dustbin": did1, "to_dustbin": did2, "ward_id": "W05", "issue_type": "pothole", "severity": 3, "timestamp": now}
        fpath = os.path.join(ROAD_DIR, f"sim_road_{i}_{int(time.time()*1000)}.json")
    
    with open(fpath, "w") as f:
        json.dump([data], f)
    print(f"  Wrote event {i+1}/20")
    time.sleep(0.05) # Tiny 50ms gaps to simulate heavy concurrent load

print("✅ 20 events written rapidly.")
