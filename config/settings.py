"""
InfraWatch Nexus — Settings & Thresholds
=========================================
Locked schema. No simulation parameters.
"""

# ══════════════════════════════════════════════════════════════════════════════
# WASTE RISK WEIGHTS (Primary Focus — 70% of system)
# ══════════════════════════════════════════════════════════════════════════════
WASTE_RISK_WEIGHTS = {
    "report_freq":       0.35,   # Report density in last 2 hours
    "overflow_severity": 0.30,   # Average overflow level (1–5)
    "collection_delay":  0.20,   # Hours since last van collection
    "rainfall":          0.15,   # Rain amplifies overflow risk
}

# ══════════════════════════════════════════════════════════════════════════════
# ROAD RISK WEIGHTS (Secondary Focus — 30% of system)
# ══════════════════════════════════════════════════════════════════════════════
ROAD_RISK_WEIGHTS = {
    "report_density":    0.60,   # Issue report count in last 3 hours
    "severity":          0.25,   # Average issue severity (1–5)
    "rainfall":          0.15,   # Rain worsens road conditions
}

# ══════════════════════════════════════════════════════════════════════════════
# NORMALIZATION THRESHOLDS (value at which factor = 1.0 / max risk)
# ══════════════════════════════════════════════════════════════════════════════
WASTE_NORM = {
    "report_count_2hr":  8,      # 8+ reports in 2 hrs = max
    "overflow_level":    5,      # Level 5 = overflowing
    "collection_delay_hr": 12,   # 12+ hours without collection = max
    "rainfall_mm_hr":    50,     # 50mm/hr = max rainfall stress
}

ROAD_NORM = {
    "report_count_3hr":  6,      # 6+ road reports in 3 hrs = max
    "severity":          5,      # Severity 5 = critical
    "rainfall_mm_hr":    50,     # Same rainfall threshold
}

# ══════════════════════════════════════════════════════════════════════════════
# STATE BANDS (shared by both waste and road)
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
WASTE_WINDOW_HOURS = 2
ROAD_WINDOW_HOURS  = 3

# ══════════════════════════════════════════════════════════════════════════════
# DATA DIRECTORIES (Pathway watches these)
# ══════════════════════════════════════════════════════════════════════════════
DATA_DIR         = "./data"
REPORT_DIR       = "./data/reports"
OUTPUT_DIR       = "./data/output"

# ══════════════════════════════════════════════════════════════════════════════
# WEATHER API
# ══════════════════════════════════════════════════════════════════════════════
WEATHER_API_URL  = "https://api.openweathermap.org/data/2.5/weather"
WEATHER_CITY_ID  = 1273294   # Delhi
WEATHER_POLL_SEC = 600       # 10 minutes

# ══════════════════════════════════════════════════════════════════════════════
# SERVER
# ══════════════════════════════════════════════════════════════════════════════
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8000

# ══════════════════════════════════════════════════════════════════════════════
# LLM
# ══════════════════════════════════════════════════════════════════════════════
LLM_PROVIDER = "gemini"
