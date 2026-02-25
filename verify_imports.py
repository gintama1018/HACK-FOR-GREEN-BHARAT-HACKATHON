#!/usr/bin/env python3
"""Quick verification that all imports work in Ubuntu venv."""
import sys
sys.path.insert(0, '/mnt/c/Users/hp/HACK FOR GREEN BHARAT HACKATHON')

import pathway as pw
print(f"Pathway version: {pw.__version__}")

from pathway_engine import compute_dashboard_snapshot, DUSTBIN_IDS, WARD_IDS
snap = compute_dashboard_snapshot()
print(f"Dustbins: {len(snap['dustbin_states'])}")
print(f"Ward risks: {len(snap['ward_risks'])}")
print(f"Priority queue: {len(snap['priority_queue'])}")
print("ALL IMPORTS: OK")
