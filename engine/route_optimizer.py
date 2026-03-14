"""
InfraWatch Nexus — Vehicle Routing Problem (VRP) Solver
========================================================
Optimizes garbage truck collection routes based on:
  - Dustbin priority (Critical > Escalated > Reported)
  - Haversine distance between stops
  - Truck capacity constraints

Uses a priority-weighted nearest-neighbor heuristic:
  1. Start from depot (ward center)
  2. Pick the highest-priority unvisited dustbin within reach
  3. If multiple dustbins have the same priority tier, pick nearest
  4. When truck is "full" (max stops), return to depot

This is a greedy approximation. For exact VRP, you'd need
OR-Tools or branch-and-bound, but this is O(n^2) and runs in <1ms
for typical ward sizes (6-12 dustbins).

After greedy construction, applies 2-opt local search to
improve route distance by swapping edge pairs.
"""

import math
from engine.spatial import haversine_m


# ═══════════════════════════════════════════════════════════════════════════
# PRIORITY WEIGHTS (higher = collect first)
# ═══════════════════════════════════════════════════════════════════════════
STATE_PRIORITY = {
    "Critical": 100,
    "Escalated": 70,
    "Reported": 40,
    "Clear": 0,
    "Cleared": 0,
}

# Maximum stops per truck before returning to depot
DEFAULT_MAX_STOPS = 15


def _priority_distance_score(dustbin, current_lat, current_lng, max_dist_m=5000):
    """
    Combined score: high priority + short distance = best next stop.
    Returns a score where HIGHER is better.
    """
    priority = STATE_PRIORITY.get(dustbin["state"], 0)
    if priority == 0:
        return -1  # Skip Clear/Cleared dustbins

    dist = haversine_m(current_lat, current_lng, dustbin["lat"], dustbin["lng"])

    # Normalize distance to 0-1 (closer = higher score)
    dist_score = max(0, 1.0 - (dist / max_dist_m))

    # Combined: 70% priority, 30% proximity
    return priority * 0.7 + dist_score * 100 * 0.3


def _two_opt_improve(stops, depot_lat, depot_lng, max_iterations=100):
    """
    2-opt local search: iteratively swap edge pairs to reduce total distance.
    Runs in O(n^2) per iteration, with early exit when no improvement found.
    Typically improves greedy routes by 10-20%.
    """
    if len(stops) < 3:
        return stops  # Nothing to improve

    def route_distance(s):
        """Total tour distance: depot -> s[0] -> ... -> s[-1] -> depot"""
        d = haversine_m(depot_lat, depot_lng, s[0]["lat"], s[0]["lng"])
        for i in range(len(s) - 1):
            d += haversine_m(s[i]["lat"], s[i]["lng"], s[i + 1]["lat"], s[i + 1]["lng"])
        d += haversine_m(s[-1]["lat"], s[-1]["lng"], depot_lat, depot_lng)
        return d

    best_distance = route_distance(stops)
    improved = True
    iteration = 0

    while improved and iteration < max_iterations:
        improved = False
        iteration += 1
        for i in range(len(stops) - 1):
            for j in range(i + 1, len(stops)):
                # Reverse the segment between i and j
                new_stops = stops[:i] + stops[i:j + 1][::-1] + stops[j + 1:]
                new_distance = route_distance(new_stops)
                if new_distance < best_distance - 0.01:  # Avoid floating point noise
                    stops = new_stops
                    best_distance = new_distance
                    improved = True
                    break  # Restart inner loop with improved route
            if improved:
                break

    return stops


def optimize_route(dustbin_states, depot_lat, depot_lng,
                   max_stops=DEFAULT_MAX_STOPS, ward_id=None):
    """
    Solve VRP for a single truck using priority-weighted nearest-neighbor.

    Args:
        dustbin_states: list of dustbin state dicts (from dashboard)
        depot_lat, depot_lng: truck starting position (usually ward center)
        max_stops: maximum collection stops before returning to depot
        ward_id: if set, only consider dustbins in this ward

    Returns:
        {
            "route": [ordered list of dustbin_ids to visit],
            "stops": [ordered list of {dustbin_id, lat, lng, state, street, distance_m}],
            "total_distance_m": float,
            "estimated_time_min": float,
            "depot": {"lat": float, "lng": float},
            "dustbins_skipped": int  (Clear/Cleared bins not needing collection)
        }
    """
    # Filter to actionable dustbins
    candidates = []
    for ds in dustbin_states:
        if ward_id and ds.get("ward_id") != ward_id:
            continue
        if ds["state"] in ("Clear", "Cleared"):
            continue
        candidates.append(ds)

    if not candidates:
        return {
            "route": [],
            "stops": [],
            "total_distance_m": 0,
            "estimated_time_min": 0,
            "depot": {"lat": depot_lat, "lng": depot_lng},
            "dustbins_skipped": len(dustbin_states) - len(candidates),
        }

    # Greedy nearest-neighbor with priority weighting
    visited = []
    unvisited = list(candidates)
    current_lat, current_lng = depot_lat, depot_lng
    total_distance = 0

    while unvisited and len(visited) < max_stops:
        # Score all unvisited dustbins
        best_idx = -1
        best_score = -1

        for i, ds in enumerate(unvisited):
            score = _priority_distance_score(ds, current_lat, current_lng)
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx < 0:
            break

        # Move to best next stop
        chosen = unvisited.pop(best_idx)
        dist = haversine_m(current_lat, current_lng, chosen["lat"], chosen["lng"])
        total_distance += dist

        visited.append({
            "dustbin_id": chosen["dustbin_id"],
            "lat": chosen["lat"],
            "lng": chosen["lng"],
            "state": chosen["state"],
            "street": chosen.get("street", ""),
            "ward_id": chosen.get("ward_id", ""),
            "report_count": chosen.get("report_count", 0),
            "distance_from_prev_m": round(dist, 1),
        })

        current_lat, current_lng = chosen["lat"], chosen["lng"]

    # Phase 2: 2-opt improvement (swap edges to reduce total distance)
    if len(visited) >= 3:
        visited = _two_opt_improve(visited, depot_lat, depot_lng)
        # Recalculate distances after 2-opt reordering
        total_distance = 0
        prev_lat, prev_lng = depot_lat, depot_lng
        for stop in visited:
            d = haversine_m(prev_lat, prev_lng, stop["lat"], stop["lng"])
            stop["distance_from_prev_m"] = round(d, 1)
            total_distance += d
            prev_lat, prev_lng = stop["lat"], stop["lng"]

    # Add return-to-depot distance
    if visited:
        return_dist = haversine_m(visited[-1]["lat"], visited[-1]["lng"],
                                  depot_lat, depot_lng)
        total_distance += return_dist

    # Estimate time: assume 20 km/h average speed + 3 min per stop
    speed_ms = 20 * 1000 / 3600  # ~5.56 m/s
    travel_time_min = (total_distance / speed_ms) / 60 if speed_ms > 0 else 0
    stop_time_min = len(visited) * 3  # 3 minutes per collection stop
    total_time_min = round(travel_time_min + stop_time_min, 1)

    return {
        "route": [s["dustbin_id"] for s in visited],
        "stops": visited,
        "total_distance_m": round(total_distance, 1),
        "estimated_time_min": total_time_min,
        "depot": {"lat": depot_lat, "lng": depot_lng},
        "dustbins_skipped": len(dustbin_states) - len(candidates),
    }


def optimize_all_wards(dustbin_states, wards):
    """
    Optimize routes for all wards. Returns dict of ward_id -> route.
    Each ward uses its center as the depot.
    """
    results = {}
    for wid, winfo in wards.items():
        ward_bins = [ds for ds in dustbin_states if ds.get("ward_id") == wid]
        # Only optimize if there are actionable bins
        actionable = [b for b in ward_bins if b["state"] not in ("Clear", "Cleared")]
        if not actionable:
            continue

        results[wid] = optimize_route(
            dustbin_states=ward_bins,
            depot_lat=winfo["lat"],
            depot_lng=winfo["lng"],
            ward_id=wid,
        )
        results[wid]["ward_name"] = winfo["name"]

    return results
