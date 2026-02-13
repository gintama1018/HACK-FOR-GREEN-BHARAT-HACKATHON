"""
InfraWatch Nexus — Ward & Road Segment Definitions
====================================================
Real Delhi Municipal Corporation ward structure.
Wards are the primary operational unit for waste management.
Road segments are secondary, mapped to their parent ward.
"""

# ── Municipal Wards (Primary Unit — Waste Management) ──────────────────────
WARDS = {
    "W01": {
        "name": "Rohini Zone-II",
        "zone": "North",
        "lat": 28.7325, "lng": 77.1187,
        "bins": 48, "vans": 3,
        "population_density": "High",
    },
    "W02": {
        "name": "Karol Bagh",
        "zone": "Central",
        "lat": 28.6519, "lng": 77.1905,
        "bins": 62, "vans": 4,
        "population_density": "Very High",
    },
    "W03": {
        "name": "Shahdara South",
        "zone": "East",
        "lat": 28.6731, "lng": 77.2894,
        "bins": 55, "vans": 3,
        "population_density": "High",
    },
    "W04": {
        "name": "Saket",
        "zone": "South",
        "lat": 28.5244, "lng": 77.2066,
        "bins": 40, "vans": 3,
        "population_density": "Medium",
    },
    "W05": {
        "name": "Dwarka",
        "zone": "West",
        "lat": 28.5921, "lng": 77.0460,
        "bins": 52, "vans": 4,
        "population_density": "Medium",
    },
    "W06": {
        "name": "Chandni Chowk",
        "zone": "Central",
        "lat": 28.6562, "lng": 77.2300,
        "bins": 70, "vans": 5,
        "population_density": "Very High",
    },
    "W07": {
        "name": "Najafgarh",
        "zone": "West",
        "lat": 28.6092, "lng": 76.9798,
        "bins": 35, "vans": 2,
        "population_density": "Low",
    },
    "W08": {
        "name": "Shahdara North",
        "zone": "East",
        "lat": 28.7041, "lng": 77.2807,
        "bins": 50, "vans": 3,
        "population_density": "High",
    },
    "W09": {
        "name": "Mehrauli",
        "zone": "South",
        "lat": 28.5126, "lng": 77.1728,
        "bins": 38, "vans": 2,
        "population_density": "Medium",
    },
    "W10": {
        "name": "Civil Lines",
        "zone": "North",
        "lat": 28.6814, "lng": 77.2226,
        "bins": 42, "vans": 3,
        "population_density": "Medium",
    },
    "W11": {
        "name": "Okhla Industrial",
        "zone": "South",
        "lat": 28.5310, "lng": 77.2713,
        "bins": 58, "vans": 4,
        "population_density": "High",
    },
    "W12": {
        "name": "Pitampura",
        "zone": "North",
        "lat": 28.7019, "lng": 77.1315,
        "bins": 45, "vans": 3,
        "population_density": "High",
    },
}

# ── Road Segments (Secondary — Road Issues) ────────────────────────────────
ROAD_SEGMENTS = {
    "R01": {
        "name": "GT Karnal Road",
        "ward_id": "W01",
        "type": "Arterial",
        "lat": 28.7340, "lng": 77.1200,
        "length_km": 3.8,
    },
    "R02": {
        "name": "Karol Bagh Main Road",
        "ward_id": "W02",
        "type": "Residential",
        "lat": 28.6525, "lng": 77.1910,
        "length_km": 1.5,
    },
    "R03": {
        "name": "Vikas Marg",
        "ward_id": "W03",
        "type": "Arterial",
        "lat": 28.6740, "lng": 77.2900,
        "length_km": 4.0,
    },
    "R04": {
        "name": "Mehrauli-Badarpur Road",
        "ward_id": "W04",
        "type": "Arterial",
        "lat": 28.5250, "lng": 77.2070,
        "length_km": 5.1,
    },
    "R05": {
        "name": "Dwarka Expressway Link",
        "ward_id": "W05",
        "type": "Highway",
        "lat": 28.5930, "lng": 77.0470,
        "length_km": 4.0,
    },
    "R06": {
        "name": "Chandni Chowk Road",
        "ward_id": "W06",
        "type": "Residential",
        "lat": 28.6570, "lng": 77.2310,
        "length_km": 1.2,
    },
    "R07": {
        "name": "Najafgarh Road",
        "ward_id": "W07",
        "type": "Arterial",
        "lat": 28.6100, "lng": 76.9810,
        "length_km": 5.5,
    },
    "R08": {
        "name": "Wazirabad Bridge Approach",
        "ward_id": "W08",
        "type": "Highway",
        "lat": 28.7050, "lng": 77.2815,
        "length_km": 1.8,
    },
    "R09": {
        "name": "Chattarpur Road",
        "ward_id": "W09",
        "type": "Residential",
        "lat": 28.5130, "lng": 77.1735,
        "length_km": 2.0,
    },
    "R10": {
        "name": "Mall Road",
        "ward_id": "W10",
        "type": "Arterial",
        "lat": 28.6820, "lng": 77.2235,
        "length_km": 2.5,
    },
    "R11": {
        "name": "Mathura Road (Okhla stretch)",
        "ward_id": "W11",
        "type": "Highway",
        "lat": 28.5320, "lng": 77.2720,
        "length_km": 6.3,
    },
    "R12": {
        "name": "Pitampura Main Road",
        "ward_id": "W12",
        "type": "Arterial",
        "lat": 28.7025, "lng": 77.1320,
        "length_km": 2.5,
    },
}

# Delhi center coordinates for map
CITY_CENTER = {"lat": 28.6139, "lng": 77.2090}
