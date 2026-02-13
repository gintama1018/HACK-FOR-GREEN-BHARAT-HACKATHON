"""
InfraWatch — State Machine
Manages segment state transitions with hysteresis to prevent flapping.
States: Normal → Elevated → Warning → Critical
"""
from config.settings import STATE_BANDS, HYSTERESIS_BUFFER


def get_state_for_score(score):
    """Determine state label from raw score without hysteresis."""
    for band in STATE_BANDS:
        if band["min"] <= score <= band["max"]:
            return band["label"]
    return "Critical"


def get_state_color(state_label):
    """Get color for a state label."""
    for band in STATE_BANDS:
        if band["label"] == state_label:
            return band["color"]
    return "#94A3B8"


STATE_ORDER = ["Normal", "Elevated", "Warning", "Critical"]


class StateMachine:
    """
    Manages per-segment state with hysteresis.
    Upgrade: score crosses threshold upward.
    Downgrade: score must drop HYSTERESIS_BUFFER points below threshold.
    """
    
    def __init__(self):
        self._states = {}  # segment_id -> current state label
        self._state_log = []
    
    def get_state(self, segment_id):
        return self._states.get(segment_id, "Normal")
    
    def transition(self, segment_id, risk_score):
        """
        Evaluate state transition for a segment.
        Returns (new_state, state_changed).
        """
        current = self._states.get(segment_id, "Normal")
        raw_new = get_state_for_score(risk_score)
        
        current_idx = STATE_ORDER.index(current)
        raw_idx = STATE_ORDER.index(raw_new)
        
        if raw_idx > current_idx:
            # Upgrade: immediate
            self._states[segment_id] = raw_new
            return raw_new, True
        elif raw_idx < current_idx:
            # Downgrade: requires hysteresis buffer
            # Check if score is sufficiently below the lower boundary of current state
            current_band = STATE_BANDS[current_idx]
            if risk_score < (current_band["min"] - HYSTERESIS_BUFFER):
                self._states[segment_id] = raw_new
                return raw_new, True
            else:
                # Stay in current state (hysteresis hold)
                return current, False
        else:
            # Same state
            return current, False
