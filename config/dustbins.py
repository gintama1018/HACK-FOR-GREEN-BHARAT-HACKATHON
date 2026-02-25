"""
InfraWatch Nexus — Dustbin Registry
====================================
72 dustbins across 12 Delhi wards (6 per ward).
Real coordinates. MCD-style IDs.
This is the backbone — both portals reference these IDs.
"""

DUSTBINS = {
    # ── W01: Rohini Zone-II (North) ──────────────────────────────────────
    "MCD-W01-001": {"ward_id": "W01", "lat": 28.7340, "lng": 77.1150, "street": "Sector 3 Main Road", "capacity_liters": 240},
    "MCD-W01-002": {"ward_id": "W01", "lat": 28.7360, "lng": 77.1180, "street": "Sector 5 Market", "capacity_liters": 240},
    "MCD-W01-003": {"ward_id": "W01", "lat": 28.7310, "lng": 77.1210, "street": "Sector 7 Park Gate", "capacity_liters": 360},
    "MCD-W01-004": {"ward_id": "W01", "lat": 28.7290, "lng": 77.1160, "street": "Sector 8 Hospital Road", "capacity_liters": 240},
    "MCD-W01-005": {"ward_id": "W01", "lat": 28.7375, "lng": 77.1200, "street": "Sector 11 Bus Stand", "capacity_liters": 360},
    "MCD-W01-006": {"ward_id": "W01", "lat": 28.7320, "lng": 77.1130, "street": "Sector 15 School Lane", "capacity_liters": 240},

    # ── W02: Karol Bagh (Central) ────────────────────────────────────────
    "MCD-W02-001": {"ward_id": "W02", "lat": 28.6530, "lng": 77.1880, "street": "Ajmal Khan Road", "capacity_liters": 360},
    "MCD-W02-002": {"ward_id": "W02", "lat": 28.6510, "lng": 77.1920, "street": "Pusa Road Junction", "capacity_liters": 240},
    "MCD-W02-003": {"ward_id": "W02", "lat": 28.6545, "lng": 77.1895, "street": "Gaffar Market Gate", "capacity_liters": 240},
    "MCD-W02-004": {"ward_id": "W02", "lat": 28.6500, "lng": 77.1940, "street": "Dev Nagar Crossing", "capacity_liters": 360},
    "MCD-W02-005": {"ward_id": "W02", "lat": 28.6555, "lng": 77.1870, "street": "Bank Street", "capacity_liters": 240},
    "MCD-W02-006": {"ward_id": "W02", "lat": 28.6520, "lng": 77.1910, "street": "Arya Samaj Road", "capacity_liters": 240},

    # ── W03: Shahdara South (East) ───────────────────────────────────────
    "MCD-W03-001": {"ward_id": "W03", "lat": 28.6745, "lng": 77.2870, "street": "Shahdara Main Bazar", "capacity_liters": 240},
    "MCD-W03-002": {"ward_id": "W03", "lat": 28.6720, "lng": 77.2910, "street": "Mansarovar Park Road", "capacity_liters": 240},
    "MCD-W03-003": {"ward_id": "W03", "lat": 28.6760, "lng": 77.2885, "street": "GT Road Shahdara", "capacity_liters": 360},
    "MCD-W03-004": {"ward_id": "W03", "lat": 28.6710, "lng": 77.2930, "street": "Vivek Vihar Main", "capacity_liters": 240},
    "MCD-W03-005": {"ward_id": "W03", "lat": 28.6740, "lng": 77.2850, "street": "Geeta Colony Chowk", "capacity_liters": 360},
    "MCD-W03-006": {"ward_id": "W03", "lat": 28.6700, "lng": 77.2900, "street": "Jheel Chowk", "capacity_liters": 240},

    # ── W04: Saket (South) ───────────────────────────────────────────────
    "MCD-W04-001": {"ward_id": "W04", "lat": 28.5260, "lng": 77.2040, "street": "Saket Metro Gate 1", "capacity_liters": 360},
    "MCD-W04-002": {"ward_id": "W04", "lat": 28.5235, "lng": 77.2080, "street": "Press Enclave Road", "capacity_liters": 240},
    "MCD-W04-003": {"ward_id": "W04", "lat": 28.5270, "lng": 77.2055, "street": "Khirki Extension Main", "capacity_liters": 240},
    "MCD-W04-004": {"ward_id": "W04", "lat": 28.5220, "lng": 77.2100, "street": "Malviya Nagar Market", "capacity_liters": 360},
    "MCD-W04-005": {"ward_id": "W04", "lat": 28.5250, "lng": 77.2030, "street": "Select City Walk Rd", "capacity_liters": 240},
    "MCD-W04-006": {"ward_id": "W04", "lat": 28.5280, "lng": 77.2070, "street": "Saket District Centre", "capacity_liters": 240},

    # ── W05: Dwarka (West) ───────────────────────────────────────────────
    "MCD-W05-001": {"ward_id": "W05", "lat": 28.5935, "lng": 77.0440, "street": "Sector 6 Market", "capacity_liters": 240},
    "MCD-W05-002": {"ward_id": "W05", "lat": 28.5910, "lng": 77.0480, "street": "Sector 10 Main Road", "capacity_liters": 240},
    "MCD-W05-003": {"ward_id": "W05", "lat": 28.5950, "lng": 77.0450, "street": "Sector 12 Park", "capacity_liters": 360},
    "MCD-W05-004": {"ward_id": "W05", "lat": 28.5890, "lng": 77.0500, "street": "Sector 14 Bus Stop", "capacity_liters": 240},
    "MCD-W05-005": {"ward_id": "W05", "lat": 28.5960, "lng": 77.0420, "street": "Sector 21 Crossing", "capacity_liters": 360},
    "MCD-W05-006": {"ward_id": "W05", "lat": 28.5920, "lng": 77.0470, "street": "Sector 23 School", "capacity_liters": 240},

    # ── W06: Chandni Chowk (Central) ─────────────────────────────────────
    "MCD-W06-001": {"ward_id": "W06", "lat": 28.6575, "lng": 77.2280, "street": "Khari Baoli Road", "capacity_liters": 360},
    "MCD-W06-002": {"ward_id": "W06", "lat": 28.6555, "lng": 77.2310, "street": "Nai Sarak", "capacity_liters": 240},
    "MCD-W06-003": {"ward_id": "W06", "lat": 28.6590, "lng": 77.2295, "street": "Fatehpuri Chowk", "capacity_liters": 240},
    "MCD-W06-004": {"ward_id": "W06", "lat": 28.6540, "lng": 77.2330, "street": "Dariba Kalan", "capacity_liters": 360},
    "MCD-W06-005": {"ward_id": "W06", "lat": 28.6600, "lng": 77.2270, "street": "Chandni Chowk Main", "capacity_liters": 360},
    "MCD-W06-006": {"ward_id": "W06", "lat": 28.6560, "lng": 77.2320, "street": "Kinari Bazaar Gate", "capacity_liters": 240},

    # ── W07: Najafgarh (West) ────────────────────────────────────────────
    "MCD-W07-001": {"ward_id": "W07", "lat": 28.6105, "lng": 76.9780, "street": "Najafgarh Bus Stand", "capacity_liters": 240},
    "MCD-W07-002": {"ward_id": "W07", "lat": 28.6080, "lng": 76.9810, "street": "Main Bazaar Najafgarh", "capacity_liters": 240},
    "MCD-W07-003": {"ward_id": "W07", "lat": 28.6120, "lng": 76.9790, "street": "Dhansa Road Junction", "capacity_liters": 360},
    "MCD-W07-004": {"ward_id": "W07", "lat": 28.6065, "lng": 76.9830, "street": "Goyla Dairy Road", "capacity_liters": 240},
    "MCD-W07-005": {"ward_id": "W07", "lat": 28.6130, "lng": 76.9770, "street": "Kair Village Crossing", "capacity_liters": 240},
    "MCD-W07-006": {"ward_id": "W07", "lat": 28.6090, "lng": 76.9800, "street": "NH-48 Service Road", "capacity_liters": 360},

    # ── W08: Shahdara North (East) ───────────────────────────────────────
    "MCD-W08-001": {"ward_id": "W08", "lat": 28.7055, "lng": 77.2790, "street": "Seelampur Main", "capacity_liters": 360},
    "MCD-W08-002": {"ward_id": "W08", "lat": 28.7030, "lng": 77.2820, "street": "Jafrabad Road", "capacity_liters": 240},
    "MCD-W08-003": {"ward_id": "W08", "lat": 28.7070, "lng": 77.2800, "street": "Welcome Metro Gate", "capacity_liters": 240},
    "MCD-W08-004": {"ward_id": "W08", "lat": 28.7015, "lng": 77.2840, "street": "Maujpur Chowk", "capacity_liters": 360},
    "MCD-W08-005": {"ward_id": "W08", "lat": 28.7080, "lng": 77.2780, "street": "Yamuna Vihar Road", "capacity_liters": 240},
    "MCD-W08-006": {"ward_id": "W08", "lat": 28.7040, "lng": 77.2810, "street": "Bhajanpura Crossing", "capacity_liters": 240},

    # ── W09: Mehrauli (South) ────────────────────────────────────────────
    "MCD-W09-001": {"ward_id": "W09", "lat": 28.5140, "lng": 77.1710, "street": "Mehrauli Bus Terminal", "capacity_liters": 240},
    "MCD-W09-002": {"ward_id": "W09", "lat": 28.5115, "lng": 77.1740, "street": "Qutub Minar Road", "capacity_liters": 360},
    "MCD-W09-003": {"ward_id": "W09", "lat": 28.5155, "lng": 77.1720, "street": "Andheria Modh", "capacity_liters": 240},
    "MCD-W09-004": {"ward_id": "W09", "lat": 28.5100, "lng": 77.1760, "street": "Lado Sarai Main", "capacity_liters": 240},
    "MCD-W09-005": {"ward_id": "W09", "lat": 28.5160, "lng": 77.1700, "street": "Sultanpur Road", "capacity_liters": 360},
    "MCD-W09-006": {"ward_id": "W09", "lat": 28.5130, "lng": 77.1735, "street": "Chattarpur Temple Rd", "capacity_liters": 240},

    # ── W10: Civil Lines (North) ─────────────────────────────────────────
    "MCD-W10-001": {"ward_id": "W10", "lat": 28.6828, "lng": 77.2210, "street": "Mall Road Civil Lines", "capacity_liters": 360},
    "MCD-W10-002": {"ward_id": "W10", "lat": 28.6800, "lng": 77.2240, "street": "Rajpur Road", "capacity_liters": 240},
    "MCD-W10-003": {"ward_id": "W10", "lat": 28.6840, "lng": 77.2220, "street": "Ludlow Castle Rd", "capacity_liters": 240},
    "MCD-W10-004": {"ward_id": "W10", "lat": 28.6785, "lng": 77.2260, "street": "Nicholson Road", "capacity_liters": 360},
    "MCD-W10-005": {"ward_id": "W10", "lat": 28.6850, "lng": 77.2200, "street": "Qudsia Garden Gate", "capacity_liters": 240},
    "MCD-W10-006": {"ward_id": "W10", "lat": 28.6810, "lng": 77.2230, "street": "Magazine Road", "capacity_liters": 240},

    # ── W11: Okhla Industrial (South) ────────────────────────────────────
    "MCD-W11-001": {"ward_id": "W11", "lat": 28.5325, "lng": 77.2695, "street": "Okhla Phase 1 Gate", "capacity_liters": 360},
    "MCD-W11-002": {"ward_id": "W11", "lat": 28.5300, "lng": 77.2725, "street": "Jamia Nagar Main", "capacity_liters": 240},
    "MCD-W11-003": {"ward_id": "W11", "lat": 28.5340, "lng": 77.2705, "street": "Okhla Phase 2 Road", "capacity_liters": 240},
    "MCD-W11-004": {"ward_id": "W11", "lat": 28.5285, "lng": 77.2745, "street": "Batla House Chowk", "capacity_liters": 360},
    "MCD-W11-005": {"ward_id": "W11", "lat": 28.5350, "lng": 77.2680, "street": "Mathura Road Jctn", "capacity_liters": 240},
    "MCD-W11-006": {"ward_id": "W11", "lat": 28.5310, "lng": 77.2715, "street": "Jogabai Extension", "capacity_liters": 240},

    # ── W12: Pitampura (North) ───────────────────────────────────────────
    "MCD-W12-001": {"ward_id": "W12", "lat": 28.7035, "lng": 77.1300, "street": "Kohat Enclave Main", "capacity_liters": 240},
    "MCD-W12-002": {"ward_id": "W12", "lat": 28.7010, "lng": 77.1330, "street": "Pitampura TV Tower Rd", "capacity_liters": 360},
    "MCD-W12-003": {"ward_id": "W12", "lat": 28.7050, "lng": 77.1310, "street": "Rani Bagh Main Road", "capacity_liters": 240},
    "MCD-W12-004": {"ward_id": "W12", "lat": 28.6995, "lng": 77.1350, "street": "Saraswati Vihar Mkt", "capacity_liters": 240},
    "MCD-W12-005": {"ward_id": "W12", "lat": 28.7060, "lng": 77.1290, "street": "Madhuban Chowk", "capacity_liters": 360},
    "MCD-W12-006": {"ward_id": "W12", "lat": 28.7020, "lng": 77.1320, "street": "Ashok Vihar Phase 3", "capacity_liters": 240},
}


def get_dustbin(dustbin_id: str) -> dict | None:
    """Lookup a dustbin by ID. Returns None if not found."""
    return DUSTBINS.get(dustbin_id)


def get_ward_dustbins(ward_id: str) -> dict:
    """Get all dustbins for a ward."""
    return {k: v for k, v in DUSTBINS.items() if v["ward_id"] == ward_id}


def validate_dustbin_id(dustbin_id: str) -> bool:
    """Strict validation: ID must exist in registry."""
    return dustbin_id in DUSTBINS
