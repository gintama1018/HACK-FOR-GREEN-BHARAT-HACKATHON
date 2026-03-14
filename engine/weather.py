"""
InfraWatch Nexus — Weather Poller
==================================
Background thread that polls WeatherAPI.com for live rainfall data.
Writes to watched directory for Pathway pickup.
"""

import json
import os
import threading
import time
from datetime import datetime

import requests

from config.settings import WEATHER_API_URL, WEATHER_CITY, WEATHER_POLL_SEC


# Shared state — read by aggregator
_latest_weather = {"rainfall_mm_hr": 0.0, "weather_source": "none", "timestamp": ""}
_lock = threading.Lock()


def get_latest_weather():
    """Thread-safe read of latest weather data."""
    with _lock:
        return dict(_latest_weather)


def _weather_poller(weather_dir):
    """Poll WeatherAPI.com every WEATHER_POLL_SEC. Write to weather directory."""
    global _latest_weather
    api_key = os.getenv("WX_API_KEY", "")
    started_at = datetime.now().isoformat()

    if not api_key:
        print("\n  [Weather] WARNING: WX_API_KEY missing. Polling disabled.\n")

    while True:
        rainfall = 0.0
        source = "weatherapi.com"

        if api_key:
            try:
                resp = requests.get(
                    WEATHER_API_URL,
                    params={"key": api_key, "q": WEATHER_CITY, "aqi": "no"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    rainfall = data.get("current", {}).get("precip_mm", 0.0)
                else:
                    print(f"  [Weather] API error HTTP {resp.status_code}")
            except Exception as e:
                print(f"  [Weather] Network error: {e}")

        now_ts = datetime.now().isoformat()
        weather_event = {
            "rainfall_mm_hr": rainfall,
            "timestamp": now_ts,
            "weather_source": source,
            "engine_started_at": started_at,
        }

        with _lock:
            _latest_weather = weather_event

        # Write to directory for Pathway
        weather_file = os.path.join(weather_dir, "current_weather.json")
        try:
            with open(weather_file, "w") as f:
                json.dump([weather_event], f)
        except Exception as e:
            print(f"  [Weather] Write error: {e}")

        print(f"  [Weather] {source}: {rainfall}mm/hr @ {now_ts}")
        time.sleep(WEATHER_POLL_SEC)


def start_weather_poller(weather_dir):
    """Start the weather poller as a daemon thread."""
    t = threading.Thread(target=_weather_poller, args=(weather_dir,), daemon=True)
    t.start()
    print("  Weather poller started")
    return t
