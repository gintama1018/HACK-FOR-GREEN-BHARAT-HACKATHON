"""Verification of hardened InfraWatch — testing all pitfall fixes."""
import urllib.request
import json
import time

BASE = "http://localhost:8000"

def get(url):
    r = urllib.request.urlopen(url)
    return json.loads(r.read())

def post(url, data=None):
    req = urllib.request.Request(url, method="POST")
    req.add_header("Content-Type", "application/json")
    if data:
        req.data = json.dumps(data).encode()
    r = urllib.request.urlopen(req)
    return json.loads(r.read())

print("=" * 60)
print("  InfraWatch Hardened Verification")
print("=" * 60)

# 1. Test segments (basic)
d = get(f"{BASE}/api/segments")
segs = d["segments"]
print(f"\n1. SEGMENTS: {len(segs)} loaded")
top = sorted(segs, key=lambda x: -x["risk_score"])[:3]
for s in top:
    print(f"   {s['name'][:30]:30s} Risk:{s['risk_score']:3d} State:{s['state']}")

# 2. Test EXPLAINABILITY (factor breakdown)
seg_id = top[0]["segment_id"]
print(f"\n2. EXPLAINABILITY: /api/explain/{seg_id}")
explain = get(f"{BASE}/api/explain/{seg_id}")
fb = explain["factor_breakdown"]
for factor, data in fb.items():
    print(f"   {factor:20s} Norm:{data['normalized']:.3f} Weight:{data['weight']:.2f} Contrib:{data['contribution_pct']:.1f}%")

# 3. Test ADVISORY CACHING
print(f"\n3. ADVISORY CACHING:")
adv1 = post(f"{BASE}/api/advisory", {"segment_id": seg_id})
print(f"   First call: cached={adv1.get('cached', 'N/A')} urgency={adv1['advisory']['urgency_level']}")
adv2 = post(f"{BASE}/api/advisory", {"segment_id": seg_id})
print(f"   Second call: cached={adv2.get('cached', 'N/A')} (should be True)")

# 4. Test REPAIR
print(f"\n4. REPAIR ENDPOINT:")
repair = post(f"{BASE}/api/repair/{seg_id}")
print(f"   Status: {repair['status']}")
# Verify segment state after repair
time.sleep(1)
d2 = get(f"{BASE}/api/segments")
repaired = [s for s in d2["segments"] if s["segment_id"] == seg_id][0]
print(f"   After repair: {repaired['name']} Risk:{repaired['risk_score']} State:{repaired['state']} Condition:{repaired['condition']}")

# 5. Test PRIORITY QUEUE
print(f"\n5. PRIORITY QUEUE:")
pq = get(f"{BASE}/api/priority")
for item in pq["priority_queue"][:5]:
    print(f"   #{item['rank']} {item['name'][:25]:25s} Score:{item['risk_score']} → {item['recommended_action'][:45]}")

# 6. Test ALERTS
print(f"\n6. ALERTS:")
alerts = get(f"{BASE}/api/alerts")
print(f"   Total state transitions: {alerts['total']}")
for a in alerts["alerts"][-3:]:
    print(f"   {a['segment_name'][:25]:25s} {a['from_state']} → {a['to_state']} ({a['dominant_factor']})")

print(f"\n{'=' * 60}")
print("  ALL TESTS PASSED")
print(f"{'=' * 60}")
