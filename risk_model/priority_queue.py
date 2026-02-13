"""
InfraWatch — Priority Queue
Ranks segments by risk score for municipal action prioritization.
"""

ACTIONS = {
    "Civic Reports": "Deploy inspection team for damage assessment",
    "Rainfall": "Activate drainage clearing crew, deploy water pumps",
    "Traffic": "Install temporary speed breakers, deploy traffic marshals",
    "Accidents": "Emergency barricading + divert traffic immediately",
    "Permit Gap": "Issue emergency repair permit, escalate to ward office",
}


def build_priority_queue(segments, top_n=10):
    """
    Rank segments by risk score (descending).
    Returns top-N with recommended action.
    """
    # Sort by risk score descending
    ranked = sorted(segments, key=lambda s: s["risk_score"], reverse=True)
    
    queue = []
    for rank, seg in enumerate(ranked[:top_n], 1):
        action = ACTIONS.get(seg["dominant_factor"], "General inspection required")
        queue.append({
            "rank": rank,
            "segment_id": seg["segment_id"],
            "name": seg["name"],
            "zone": seg["zone"],
            "risk_score": seg["risk_score"],
            "state": seg["state"],
            "dominant_factor": seg["dominant_factor"],
            "recommended_action": action,
            "condition": seg["condition"],
        })
    
    return queue
