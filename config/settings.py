"""
InfraWatch Nexus — Settings & Thresholds
=========================================
Locked schema. No simulation parameters.
All numeric thresholds hardcoded. No ambiguity.
"""

# ══════════════════════════════════════════════════════════════════════════════
# DUSTBIN STATE THRESHOLDS (report-based, rolling window)
# ══════════════════════════════════════════════════════════════════════════════
DUSTBIN_STATE_THRESHOLDS = {
    "Reported":  {"min_reports": 1},
    "Escalated": {"min_reports": 3, "or_overflow_gte": 4},
    "Critical":  {"min_reports": 5, "or_escalated_with_rain_gte": 10},
    # Clear = 0 reports in window (default)
    # Cleared = van collection event overrides everything
}

# ══════════════════════════════════════════════════════════════════════════════
# WASTE RISK WEIGHTS (Ward-Level Scoring)
# ══════════════════════════════════════════════════════════════════════════════
WASTE_RISK_WEIGHTS = {
    "report_freq":       0.35,   # Report density in rolling window
    "overflow_severity": 0.30,   # Average overflow level (1–5)
    "collection_delay":  0.20,   # Hours since last van collection
    "rainfall":          0.15,   # Rain amplifies overflow risk
}

# ══════════════════════════════════════════════════════════════════════════════
# ROAD RISK WEIGHTS (Ward-Level Road Scoring)
# ══════════════════════════════════════════════════════════════════════════════
ROAD_RISK_WEIGHTS = {
    "report_density":    0.60,   # Issue report count in rolling window
    "severity":          0.25,   # Average issue severity (1–5)
    "rainfall":          0.15,   # Rain worsens road conditions
}

# ══════════════════════════════════════════════════════════════════════════════
# NORMALIZATION THRESHOLDS (value at which factor = 1.0 / max risk)
# ══════════════════════════════════════════════════════════════════════════════
WASTE_NORM = {
    "report_count_2hr":    8,      # 8+ reports in 2 hrs = max
    "overflow_level":      5,      # Level 5 = overflowing
    "collection_delay_hr": 12,     # 12+ hours without collection = max
    "rainfall_mm_hr":      50,     # 50mm/hr = max rainfall stress (CAPPED)
}

ROAD_NORM = {
    "report_count_6hr":    6,      # 6+ road reports in 6 hrs = max
    "severity":            5,      # Severity 5 = critical
    "rainfall_mm_hr":      50,     # Same rainfall threshold (CAPPED)
}

# ══════════════════════════════════════════════════════════════════════════════
# STATE BANDS (shared by both waste-ward and road scoring)
# ══════════════════════════════════════════════════════════════════════════════
STATE_BANDS = [
    {"min": 0,  "max": 30,  "label": "Normal",   "color": "#16A34A"},
    {"min": 31, "max": 55,  "label": "Elevated",  "color": "#D97706"},
    {"min": 56, "max": 75,  "label": "Warning",   "color": "#EA580C"},
    {"min": 76, "max": 100, "label": "Critical",  "color": "#DC2626"},
]

HYSTERESIS_BUFFER = 10

# ══════════════════════════════════════════════════════════════════════════════
# ROLLING WINDOW DURATIONS
# ══════════════════════════════════════════════════════════════════════════════
WASTE_REPORT_WINDOW_HOURS = 2     # Waste reports expire after 2 hours
ROAD_ISSUE_WINDOW_HOURS = 6       # Road issues expire after 6 hours

# ══════════════════════════════════════════════════════════════════════════════
# DEDUPLICATION
# ══════════════════════════════════════════════════════════════════════════════
DEDUP_WINDOW_MINUTES = 5          # Same dustbin, same 5 min = merge

# ══════════════════════════════════════════════════════════════════════════════
# DATA DIRECTORIES (Pathway watches these)
# ══════════════════════════════════════════════════════════════════════════════
DATA_DIR         = "./data"
REPORT_DIR       = "./data/reports"
OUTPUT_DIR       = "./data/output"

# ══════════════════════════════════════════════════════════════════════════════
# WEATHER API (WeatherAPI.com — single source)
# ══════════════════════════════════════════════════════════════════════════════
WEATHER_API_URL  = "http://api.weatherapi.com/v1/current.json"
WEATHER_CITY     = "Delhi"
WEATHER_POLL_SEC = 600       # 10 minutes

# ══════════════════════════════════════════════════════════════════════════════
# SERVER
# ══════════════════════════════════════════════════════════════════════════════
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8000

# ══════════════════════════════════════════════════════════════════════════════
# PRIORITY QUEUE
# ══════════════════════════════════════════════════════════════════════════════
PRIORITY_QUEUE_MAX = 20
