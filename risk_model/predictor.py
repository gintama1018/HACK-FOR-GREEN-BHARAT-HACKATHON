"""
InfraWatch — Degradation Predictor
Projects risk delta using rainfall forecast × drainage × traffic.
Not rule-based — uses multiplicative modeling.
"""
from config.settings import RAINFALL_FORECAST
from config.segments import DRAINAGE_MULTIPLIER


def predict_degradation(segment, current_score, current_state, rainfall_intensity, drainage_mult):
    """
    Compute projected risk delta.
    
    Projected Risk Delta = 
        rainfall_intensity * drainage_multiplier * traffic_load_factor * condition_factor
    
    Returns prediction dict with projected_score and time_to_upgrade.
    """
    # Condition factor: lower condition = more vulnerable to degradation
    condition_factor = max(0.1, (100 - segment["base_condition"]) / 100)
    
    # Traffic load factor by road type
    traffic_factor = {
        "Highway": 1.0,
        "Arterial": 0.7,
        "Residential": 0.4,
    }.get(segment["road_type"], 0.5)
    
    # Maintenance history: low history = faster degradation
    maintenance_factor = max(0.1, (100 - segment["maintenance_history_score"]) / 100)
    
    # Projected risk delta (per hour, normalized to 0-30 range)
    if rainfall_intensity > 0:
        delta = (
            rainfall_intensity * drainage_mult * traffic_factor * condition_factor * maintenance_factor
        ) / 10  # Scale down to reasonable increment
        delta = min(30, round(delta, 1))  # Cap at 30 points/hr
    else:
        delta = 0
    
    projected_score = min(100, current_score + delta)
    
    # Estimate time to next state upgrade
    state_thresholds = {"Normal": 31, "Elevated": 56, "Warning": 76, "Critical": 101}
    next_threshold = state_thresholds.get(current_state, 101)
    
    if delta > 0 and projected_score >= next_threshold:
        hours_to_upgrade = max(0.5, (next_threshold - current_score) / delta)
        upgrade_label = {
            "Normal": "Elevated",
            "Elevated": "Warning",
            "Warning": "Critical",
        }.get(current_state, None)
    else:
        hours_to_upgrade = None
        upgrade_label = None
    
    return {
        "risk_delta_per_hr": delta,
        "projected_score": projected_score,
        "hours_to_upgrade": round(hours_to_upgrade, 1) if hours_to_upgrade else None,
        "projected_state": upgrade_label,
        "factors": {
            "rainfall": round(rainfall_intensity, 1),
            "drainage": round(drainage_mult, 2),
            "condition": round(condition_factor, 2),
            "maintenance": round(maintenance_factor, 2),
            "traffic": round(traffic_factor, 2),
        }
    }
