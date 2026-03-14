"""
InfraWatch Nexus — Dustbin State Machine
==========================================
5-state FSM: Clear → Reported → Escalated → Critical → Cleared
Includes hysteresis buffer to prevent state oscillation.
"""

from config.settings import DUSTBIN_STATE_THRESHOLDS, HYSTERESIS_BUFFER

# ═══════════════════════════════════════════════════════════════════════════
# STATE CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
STATE_ORDER = {"Clear": 0, "Cleared": 0, "Reported": 1, "Escalated": 2, "Critical": 3}
STATE_COLORS = {
    "Clear": "#16A34A",
    "Reported": "#D97706",
    "Escalated": "#EA580C",
    "Critical": "#DC2626",
    "Cleared": "#06B6D4",
}

# Track previous states for hysteresis (persisted to SQLite)
_previous_states = {}
_save_counter = 0  # Only persist every N calls to avoid DB churn


def _load_persisted_states():
    """Load hysteresis states from SQLite on startup."""
    global _previous_states
    try:
        from engine.database import load_hysteresis_states
        _previous_states = load_hysteresis_states()
        if _previous_states:
            print(f"  [FSM] Loaded {len(_previous_states)} persisted hysteresis states")
    except Exception as e:
        print(f"  [FSM] Could not load persisted states: {e}")
        _previous_states = {}


def _persist_states():
    """Save hysteresis states to SQLite (batched, every 10 calls)."""
    global _save_counter
    _save_counter += 1
    if _save_counter % 10 != 0:
        return
    try:
        from engine.database import save_hysteresis_states
        save_hysteresis_states(_previous_states)
    except Exception as e:
        print(f"  [FSM] Persist error: {e}")


# Load on module import
_load_persisted_states()


def compute_dustbin_state(dustbin_id, report_count, max_overflow, rainfall,
                          van_cleared=False):
    """
    Compute dustbin state with hysteresis buffer.

    Hysteresis: once a dustbin reaches a high state (e.g. Critical),
    it won't downgrade until the underlying score drops by
    HYSTERESIS_BUFFER points worth of reports.

    Returns: state string
    """
    thresholds = DUSTBIN_STATE_THRESHOLDS

    # Van collection overrides everything
    if van_cleared:
        _previous_states[dustbin_id] = "Cleared"
        return "Cleared"

    # Raw state from thresholds
    if report_count >= thresholds["Critical"]["min_reports"]:
        raw = "Critical"
    elif (report_count >= thresholds["Escalated"]["min_reports"]
          or max_overflow >= thresholds["Escalated"]["or_overflow_gte"]):
        if rainfall >= thresholds["Critical"]["or_escalated_with_rain_gte"]:
            raw = "Critical"
        else:
            raw = "Escalated"
    elif report_count >= thresholds["Reported"]["min_reports"]:
        raw = "Reported"
    else:
        raw = "Clear"

    # Apply hysteresis: resist downgrading
    prev = _previous_states.get(dustbin_id, "Clear")
    if STATE_ORDER.get(raw, 0) < STATE_ORDER.get(prev, 0):
        # Trying to downgrade — check if drop is large enough
        # Use report count as proxy: need HYSTERESIS_BUFFER fewer reports
        # than the threshold for current state to actually downgrade
        if prev == "Critical" and report_count > (thresholds["Critical"]["min_reports"] - HYSTERESIS_BUFFER):
            raw = prev  # Hold at Critical
        elif prev == "Escalated" and report_count > (thresholds["Escalated"]["min_reports"] - HYSTERESIS_BUFFER):
            raw = prev  # Hold at Escalated

    _previous_states[dustbin_id] = raw
    _persist_states()
    return raw


def get_dustbin_color(state):
    """State label → color hex."""
    return STATE_COLORS.get(state, "#6B7280")


def get_dustbin_state_score(state):
    """Convert dustbin state to numeric score for priority sorting."""
    return {
        "Clear": 0,
        "Reported": 30,
        "Escalated": 60,
        "Critical": 90,
        "Cleared": 0,
    }.get(state, 0)


def reset_state(dustbin_id):
    """Reset tracked state (e.g. after window expiry)."""
    _previous_states.pop(dustbin_id, None)
