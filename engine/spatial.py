"""
InfraWatch Nexus — Spatial Utilities
======================================
Haversine distance, spatial dedup for nearby road issues.
"""

import math


def haversine_m(lat1, lng1, lat2, lng2):
    """Distance between two GPS points in meters."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_nearby_issues(new_issue, existing_issues, threshold_m=200):
    """
    Find existing road issues within threshold distance of a new issue.
    Used for spatial dedup — two reports within 200m are likely the same issue.
    """
    nearby = []
    for ri in existing_issues:
        d = haversine_m(
            new_issue.get("from_lat", 0), new_issue.get("from_lng", 0),
            ri.get("from_lat", 0), ri.get("from_lng", 0),
        )
        if d < threshold_m:
            nearby.append(ri)
    return nearby


def find_nearest_dustbin(lat, lng, dustbins_dict, max_dist_m=500):
    """
    Find the nearest dustbin to a GPS coordinate.
    Returns (dustbin_id, distance_m) or (None, None) if none within max_dist.
    """
    best_id = None
    best_dist = float("inf")

    for did, info in dustbins_dict.items():
        d = haversine_m(lat, lng, info["lat"], info["lng"])
        if d < best_dist:
            best_dist = d
            best_id = did

    if best_dist <= max_dist_m:
        return best_id, round(best_dist, 1)
    return None, None
