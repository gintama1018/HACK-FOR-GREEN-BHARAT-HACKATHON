"""
InfraWatch Nexus — Project Documentation PDF Generator
=======================================================
Generates a professional PDF documentation for the hackathon submission.
"""

import subprocess, sys

# Ensure fpdf2 is available
try:
    from fpdf import FPDF
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "fpdf2", "-q"])
    from fpdf import FPDF

import os
import textwrap


class DocPDF(FPDF):
    """Custom PDF class with header/footer and styling helpers."""

    def __init__(self):
        super().__init__("P", "mm", "A4")
        self.set_auto_page_break(auto=True, margin=25)
        self.set_margins(20, 20, 20)
        # Register Unicode fonts
        self.add_font('Arial', '', 'C:/Windows/Fonts/arial.ttf')
        self.add_font('Arial', 'B', 'C:/Windows/Fonts/arialbd.ttf')
        self.add_font('Arial', 'I', 'C:/Windows/Fonts/ariali.ttf')
        self.add_font('Arial', 'BI', 'C:/Windows/Fonts/arialbi.ttf')
        self.add_font('Courier', '', 'C:/Windows/Fonts/cour.ttf')
        self.add_font('Courier', 'B', 'C:/Windows/Fonts/courbd.ttf')
        # Color palette
        self.PRIMARY = (30, 41, 59)      # Slate-800
        self.ACCENT = (59, 130, 246)     # Blue-500
        self.SUCCESS = (16, 185, 129)    # Emerald-500
        self.WARNING = (245, 158, 11)    # Amber-500
        self.DANGER = (220, 38, 38)      # Red-600
        self.LIGHT_BG = (241, 245, 249)  # Slate-100
        self.WHITE = (255, 255, 255)
        self.DARK = (15, 23, 42)         # Slate-900
        self.page_number_start = 0

    def header(self):
        if self.page_no() <= 1:
            return
        self.set_font("Arial", "I", 8)
        self.set_text_color(*self.PRIMARY)
        self.cell(0, 8, "InfraWatch Nexus — Project Documentation", align="L")
        self.cell(0, 8, "Hack For Green Bharat 2026", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*self.ACCENT)
        self.set_line_width(0.3)
        self.line(20, self.get_y(), 190, self.get_y())
        self.ln(4)

    def footer(self):
        if self.page_no() <= 1:
            return
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no() - 1}", align="C")

    # ── Styling helpers ──────────────────────────────────────────────────
    def title_page(self, title, subtitle, team, date_str):
        self.add_page()
        self.ln(50)
        # Top accent bar
        self.set_fill_color(*self.ACCENT)
        self.rect(0, 0, 210, 8, "F")
        # Title
        self.set_font("Arial", "B", 36)
        self.set_text_color(*self.DARK)
        self.cell(0, 16, title, align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(3)
        # Subtitle
        self.set_font("Arial", "", 14)
        self.set_text_color(*self.ACCENT)
        self.cell(0, 10, subtitle, align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(20)
        # Info box
        self.set_fill_color(*self.LIGHT_BG)
        self.set_draw_color(*self.ACCENT)
        bx = 40
        bw = 130
        by = self.get_y()
        self.rect(bx, by, bw, 55, "FD")
        self.set_xy(bx + 5, by + 8)
        self.set_font("Arial", "B", 11)
        self.set_text_color(*self.DARK)
        self.cell(bw - 10, 7, "Hackathon: Hack For Green Bharat 2026", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_x(bx + 5)
        self.set_font("Arial", "", 10)
        self.cell(bw - 10, 7, f"Team: {team}", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_x(bx + 5)
        self.cell(bw - 10, 7, f"Date: {date_str}", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_x(bx + 5)
        self.cell(bw - 10, 7, "Theme: Swachh Bharat | Smart City Infrastructure", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_x(bx + 5)
        self.set_text_color(*self.ACCENT)
        self.cell(bw - 10, 7, "Live: https://infrawatch-nexus-tnlf.onrender.com", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(30)
        # Bottom accent bar
        self.set_fill_color(*self.ACCENT)
        self.rect(0, 289, 210, 8, "F")

    def section_title(self, num, title):
        self.ln(6)
        self.set_font("Arial", "B", 18)
        self.set_text_color(*self.ACCENT)
        self.cell(0, 10, f"{num}. {title}", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*self.ACCENT)
        self.set_line_width(0.5)
        self.line(20, self.get_y(), 100, self.get_y())
        self.ln(4)
        self.set_text_color(*self.DARK)

    def sub_title(self, title):
        self.ln(3)
        self.set_font("Arial", "B", 13)
        self.set_text_color(*self.PRIMARY)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)
        self.set_text_color(*self.DARK)

    def body_text(self, text):
        self.set_font("Arial", "", 10)
        self.set_text_color(*self.DARK)
        self.multi_cell(0, 5.5, text)
        self.ln(2)

    def bullet(self, text, bold_prefix=""):
        self.set_font("Arial", "", 10)
        self.set_text_color(*self.DARK)
        x = self.get_x()
        self.cell(6, 5.5, "-")
        if bold_prefix:
            self.set_font("Arial", "B", 10)
            self.cell(self.get_string_width(bold_prefix) + 1, 5.5, bold_prefix)
            self.set_font("Arial", "", 10)
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def table(self, headers, rows, col_widths=None):
        if col_widths is None:
            col_widths = [170 / len(headers)] * len(headers)
        # Header
        self.set_fill_color(*self.PRIMARY)
        self.set_text_color(*self.WHITE)
        self.set_font("Arial", "B", 9)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 7, h, border=1, fill=True, align="C")
        self.ln()
        # Rows
        self.set_text_color(*self.DARK)
        self.set_font("Arial", "", 9)
        fill = False
        for row in rows:
            if fill:
                self.set_fill_color(*self.LIGHT_BG)
            else:
                self.set_fill_color(*self.WHITE)
            for i, cell_text in enumerate(row):
                self.cell(col_widths[i], 6.5, str(cell_text), border=1, fill=True, align="L")
            self.ln()
            fill = not fill
        self.ln(3)

    def info_box(self, text, color=None):
        if color is None:
            color = self.ACCENT
        self.set_fill_color(*self.LIGHT_BG)
        self.set_draw_color(*color)
        self.set_line_width(0.8)
        y0 = self.get_y()
        self.rect(22, y0, 166, 12, "FD")
        self.set_xy(26, y0 + 2)
        self.set_font("Arial", "B", 9)
        self.set_text_color(*color)
        self.multi_cell(158, 4, text)
        self.set_y(y0 + 14)
        self.set_text_color(*self.DARK)
        self.ln(2)


def generate_documentation():
    pdf = DocPDF()

    # ═══════════════════════════════════════════════════════════════════════
    # TITLE PAGE
    # ═══════════════════════════════════════════════════════════════════════
    pdf.title_page(
        title="InfraWatch Nexus",
        subtitle="AI-Powered Real-Time Urban Sanitation & Infrastructure Command Center",
        team="Duality AI",
        date_str="March 2026"
    )

    # ═══════════════════════════════════════════════════════════════════════
    # TABLE OF CONTENTS
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.set_font("Arial", "B", 20)
    pdf.set_text_color(*pdf.DARK)
    pdf.cell(0, 12, "Table of Contents", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    toc_items = [
        ("1", "Abstract & Problem Statement", "3"),
        ("2", "System Architecture", "4"),
        ("3", "Core Features", "5"),
        ("4", "Technology Stack", "7"),
        ("5", "Data Sources & Credibility", "8"),
        ("6", "Risk Scoring Algorithm", "9"),
        ("7", "Dustbin State Machine", "10"),
        ("8", "API Reference", "11"),
        ("9", "Event Lifecycle & Data Flow", "12"),
        ("10", "Deployment Architecture", "13"),
        ("11", "Security", "14"),
        ("12", "Scalability", "14"),
        ("13", "Project Structure", "15"),
        ("14", "Setup & Installation", "15"),
        ("15", "Demo Mode (For Judges)", "16"),
        ("16", "Impact & Social Relevance", "16"),
        ("17", "Future Roadmap", "17"),
        ("18", "Research References", "17"),
    ]
    pdf.set_font("Arial", "", 11)
    for num, title, pg in toc_items:
        pdf.set_text_color(*pdf.DARK)
        dots = "." * (60 - len(f"{num}. {title}"))
        pdf.cell(0, 7, f"  {num}.  {title}  {dots}  {pg}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # ═══════════════════════════════════════════════════════════════════════
    # 1. ABSTRACT & PROBLEM STATEMENT
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("1", "Abstract & Problem Statement")

    pdf.sub_title("1.1 Abstract")
    pdf.body_text(
        "InfraWatch Nexus is a production-grade, real-time AI command center for urban sanitation "
        "and infrastructure management. It connects citizens directly to municipal dispatch operations "
        "through streaming event architecture, computer vision AI, and live weather-aware risk scoring. "
        "The system uses the Pathway streaming engine for real-time event aggregation, Google Gemini 2.5 "
        "Flash for AI-powered waste detection from citizen photos, and live weather data from WeatherAPI.com "
        "to dynamically prioritize infrastructure issues across Delhi's 12 municipal wards."
    )

    pdf.sub_title("1.2 Problem Statement")
    pdf.body_text(
        "Traditional municipal reporting in Indian cities is reactive, fragmented, and blind to "
        "real-time conditions:"
    )

    pdf.table(
        ["Problem", "Impact"],
        [
            ["Citizens fill lengthy complaint forms", "0% transparency, reports lost in bureaucracy"],
            ["Garbage trucks follow static schedules", "Wasted fuel, higher emissions"],
            ["Road hazards not mapped dynamically", "3,500+ deaths/year (MoRTH data)"],
            ["No weather integration", "Blocked drains = epidemic risk during rain"],
        ],
        [85, 85]
    )

    pdf.info_box(
        "InfraWatch Nexus replaces all of this with a single AI-powered, weather-aware, real-time command center."
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 2. SYSTEM ARCHITECTURE
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("2", "System Architecture")

    pdf.body_text(
        "InfraWatch Nexus follows a strict separation-of-concerns architecture with four distinct layers. "
        "Each layer has a single, well-defined responsibility:"
    )

    pdf.table(
        ["Layer", "Does", "Does NOT"],
        [
            ["Citizens' Portal", "Accept photo, show live state", "Compute anything"],
            ["Admin Portal", "Report road issues, dispatch vans", "Compute anything"],
            ["FastAPI Server", "Validate, write events, auth, broadcast", "Score, rank, aggregate"],
            ["Pathway Engine", "Aggregate, score, rank, weather join", "Serve HTTP, touch frontend"],
            ["WebSocket", "Broadcast atomic state to all clients", "Compute or filter"],
        ],
        [35, 68, 67]
    )

    pdf.sub_title("2.1 Architecture Flow")
    pdf.body_text(
        "1. Citizen uploads a photo via the Citizens' Portal (SPA)\n"
        "2. FastAPI sends the image to Gemini 2.5 Flash Vision API for asset ID extraction\n"
        "3. AI returns the exact MCD dustbin ID (e.g., MCD-W04-001)\n"
        "4. Citizen confirms the detection, and FastAPI writes a JSON event to the data directory\n"
        "5. Pathway Streaming Engine watches the data directory and recomputes the dashboard\n"
        "6. Live weather data from WeatherAPI.com is polled every 10 minutes and used as a risk multiplier\n"
        "7. Pathway computes risk scores, state transitions, and priority queue ordering\n"
        "8. The atomic dashboard snapshot is broadcast via WebSocket to all connected portals\n"
        "9. Admin can dispatch vans, clear issues, and manage the priority queue in real-time"
    )

    pdf.sub_title("2.2 Key Design Principles")
    pdf.bullet("Zero computation in FastAPI — ", "Transport-only: ")
    pdf.bullet("All scoring, aggregation, and state management lives in Pathway", "Single brain: ")
    pdf.bullet("Dashboard state written via temp-file + os.replace() — no partial reads", "Atomic writes: ")
    pdf.bullet("Single WebSocket channel broadcasts identical state to all clients", "Event-driven: ")

    # ═══════════════════════════════════════════════════════════════════════
    # 3. CORE FEATURES
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("3", "Core Features")

    pdf.sub_title("3.1 AI-Powered Citizen Reporting")
    pdf.bullet("Citizens upload a single photo — AI (Gemini 2.5 Flash Vision) extracts the exact MCD dustbin ID")
    pdf.bullet("Zero friction: No forms, no dropdowns. One photo = one verified report")
    pdf.bullet("Manual fallback: If AI fails, citizen gets a ward-filtered dropdown for manual selection")
    pdf.bullet("Geolocation-aware: GPS coordinates are captured and stored with each report")

    pdf.sub_title("3.2 Pathway Streaming Engine (The Brain)")
    pdf.bullet("Event-time windowing: 2-hour rolling windows for waste reports, 6-hour for road issues")
    pdf.bullet("Dustbin State Machine: Clear > Reported > Escalated > Critical > Cleared")
    pdf.bullet("Weather-aware risk scoring: Live rainfall acts as a multiplier on risk scores")
    pdf.bullet("Atomic JSON output: Dashboard state written via temp-file + os.replace()")
    pdf.bullet("3-second recompute loop ensures dashboard always reflects latest state")

    pdf.sub_title("3.3 Admin Command Center")
    pdf.bullet("Live Priority Dispatch Queue: Auto-sorted by dynamic risk score (0-100)")
    pdf.bullet("Interactive OSRM-Routed Map: Road hazards rendered as real street-level polylines")
    pdf.bullet("Clear Issues Panel: 1-click resolution of dustbins and road hazards")
    pdf.bullet("Simulate Crisis: Demo button injects severe events for live demonstration")
    pdf.bullet("Predictive Risk Forecasting: ML-powered 3-day risk prediction using weather forecast")

    pdf.sub_title("3.4 Real-Time WebSocket Sync")
    pdf.bullet("Single WebSocket channel broadcasts identical atomic state to all connected portals")
    pdf.bullet("Auto-reconnect with exponential backoff on disconnection")
    pdf.bullet("Citizens' and Admin maps update simultaneously within milliseconds")

    pdf.sub_title("3.5 Security & Auth")
    pdf.bullet("Admin endpoints protected by Bearer token authentication (strict 401 on failure)")
    pdf.bullet("In-memory O(1) dedup prevents duplicate reports within 5-minute windows")
    pdf.bullet("Dustbin ID validation via strict regex (MCD-W\\d{2}-\\d{3}) against the MCD registry")

    # ═══════════════════════════════════════════════════════════════════════
    # 4. TECHNOLOGY STACK
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("4", "Technology Stack")

    pdf.table(
        ["Technology", "Version", "Purpose"],
        [
            ["Python", "3.10+", "Backend runtime"],
            ["FastAPI", ">=0.110.0", "Async web framework & WebSocket server"],
            ["Pathway", ">=0.14.0", "Real-time streaming data engine"],
            ["Gemini 2.5 Flash", "Latest", "Computer vision for waste detection"],
            ["WeatherAPI.com", "v1", "Live rainfall data integration"],
            ["Leaflet.js", "1.9+", "Interactive map rendering"],
            ["OSRM", "Latest", "Open-source road routing engine"],
            ["pdfplumber", "-", "Government PDF data extraction"],
            ["GitHub Actions", "-", "CI/CD pipeline"],
            ["Docker", "Latest", "Containerized deployment"],
            ["Render.com", "-", "Cloud hosting platform"],
            ["Uvicorn", ">=0.29.0", "ASGI server for production"],
        ],
        [40, 30, 100]
    )

    pdf.sub_title("4.1 Why Pathway?")
    pdf.body_text(
        "Pathway is a real-time data processing engine that provides event-time windowing, "
        "incremental computation, and streaming table semantics. Unlike batch-based systems "
        "(e.g., Spark), Pathway reacts to file changes in real-time, making it ideal for our "
        "event-driven architecture where every citizen report triggers an immediate dashboard update. "
        "The engine watches data directories and automatically triggers recomputation when new "
        "events arrive, ensuring sub-second latency from report submission to dashboard update."
    )

    pdf.sub_title("4.2 Why Gemini 2.5 Flash?")
    pdf.body_text(
        "Google's Gemini 2.5 Flash model provides best-in-class vision capabilities at the free tier "
        "(15 requests per minute). The model extracts structured data (MCD asset IDs) from citizen "
        "photos with high accuracy, enabling zero-friction reporting without forms or dropdowns. "
        "The free tier is sufficient for pilot city deployment, and paid tiers scale linearly."
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 5. DATA SOURCES & CREDIBILITY
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("5", "Data Sources & Credibility")

    pdf.info_box("All infrastructure data in this project is sourced from official government records.", pdf.SUCCESS)

    pdf.table(
        ["Data Layer", "Source", "Type"],
        [
            ["Dustbin / Dhalao Locations", "MCD - RO No. 20/DPI/MCD/2024-25", "Official Govt PDF"],
            ["Weather (Rainfall)", "WeatherAPI.com - Live polling 10 min", "Real-time API"],
            ["Citizen Reports", "Live user submissions - Gemini Vision", "Real-time user data"],
            ["Road Hazard Reports", "Admin-submitted - GPS-tagged", "Real-time admin data"],
        ],
        [45, 75, 50]
    )

    pdf.sub_title("5.1 MCD C&D Waste Collection Sites")
    pdf.body_text(
        "The 72-point dustbin registry (config/dustbins.py) is built from the official MCD document "
        "listing 106 designated C&D (Construction & Demolition) waste collection sites across all "
        "Delhi zones. Source: RO No. 20/DPI/MCD/2024-25 published by Municipal Corporation of Delhi "
        "(mcdonline.nic.in). Data was extracted programmatically using pdfplumber and geocoded for "
        "spatial analysis using verified Delhi GPS coordinates."
    )

    pdf.table(
        ["Zone", "Area", "Example Site"],
        [
            ["Rohini", "North Delhi", "JE Store, Sector-5 Rohini"],
            ["Karol Bagh", "Central-West", "MCD JE Store, East Patel Nagar"],
            ["Shahdara South", "East Delhi", "Karkari Mod, Karkardooma"],
            ["South", "South Delhi", "JE Store, Hauz Khas Market"],
            ["Keshav Puram", "North-West", "JE Store, Pitampura"],
            ["Central 1", "Central", "Defence Colony, Sriniwaspuri"],
            ["Civil Lines", "North-Central", "Qutab Road, Burari"],
            ["City SP", "Old Delhi", "Chandni Chowk, Asaf Ali Road"],
            ["South 1", "Far South", "Fatehpur Beri, Khanpur"],
            ["Narela", "Far North", "MPL Store, Nehru Enclave"],
            ["Central", "Central", "Minto Road, Punjabi Bagh"],
            ["Shahdara North", "North-East", "Seelampur, Jafrabad"],
        ],
        [40, 40, 90]
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 6. RISK SCORING ALGORITHM
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("6", "Risk Scoring Algorithm")

    pdf.body_text(
        "InfraWatch Nexus uses a weighted multi-factor risk scoring system to compute dynamic "
        "risk scores (0-100) for each ward. Separate algorithms handle waste risk and road risk."
    )

    pdf.sub_title("6.1 Waste Risk Score")
    pdf.body_text("Formula: waste_risk = SUM(weight_i * normalized_factor_i) * 100")
    pdf.table(
        ["Factor", "Weight", "Normalization Threshold"],
        [
            ["Report Frequency (2hr window)", "0.35 (35%)", "8+ reports = maximum"],
            ["Overflow Severity (1-5)", "0.30 (30%)", "Level 5 = overflowing"],
            ["Collection Delay (hours)", "0.20 (20%)", "12+ hours = maximum"],
            ["Rainfall (mm/hr)", "0.15 (15%)", "50mm/hr = max (capped)"],
        ],
        [55, 35, 80]
    )

    pdf.sub_title("6.2 Road Risk Score")
    pdf.body_text("Formula: road_risk = SUM(weight_i * normalized_factor_i) * 100")
    pdf.table(
        ["Factor", "Weight", "Normalization Threshold"],
        [
            ["Report Density (6hr window)", "0.60 (60%)", "6+ reports = maximum"],
            ["Issue Severity (1-5)", "0.25 (25%)", "Severity 5 = critical"],
            ["Rainfall (mm/hr)", "0.15 (15%)", "50mm/hr = max (capped)"],
        ],
        [55, 35, 80]
    )

    pdf.sub_title("6.3 State Bands")
    pdf.table(
        ["Score Range", "Label", "Color"],
        [
            ["0 - 30", "Normal", "#16A34A (Green)"],
            ["31 - 55", "Elevated", "#D97706 (Amber)"],
            ["56 - 75", "Warning", "#EA580C (Orange)"],
            ["76 - 100", "Critical", "#DC2626 (Red)"],
        ],
        [50, 50, 70]
    )

    pdf.body_text(
        "A hysteresis buffer of 10 points prevents oscillation between states at boundary values."
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 7. DUSTBIN STATE MACHINE
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("7", "Dustbin State Machine")

    pdf.body_text(
        "Each dustbin in the MCD registry follows a finite state machine that transitions "
        "based on report count, overflow severity, rainfall conditions, and van collection events."
    )

    pdf.table(
        ["State", "Trigger", "Visual"],
        [
            ["Clear", "0 reports in rolling window", "Green marker"],
            ["Reported", "1+ report(s) received", "Yellow marker"],
            ["Escalated", "3+ reports OR overflow >= 4", "Orange marker"],
            ["Critical", "5+ reports OR escalated + rain >= 10mm", "Red pulsing marker"],
            ["Cleared", "Van collection event received", "Green marker (reset)"],
        ],
        [30, 80, 60]
    )

    pdf.body_text(
        "Transitions:\n"
        "  Clear -> Reported: First citizen report for this dustbin\n"
        "  Reported -> Escalated: 3+ reports within 2hr window OR overflow >= 4\n"
        "  Escalated -> Critical: 5+ reports OR escalated state + rainfall >= 10mm/hr\n"
        "  Any State -> Cleared: Admin marks van collection (overrides everything)\n"
        "  Cleared -> Clear: After collection, all reports are reset in the next window"
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 8. API REFERENCE
    # ═══════════════════════════════════════════════════════════════════════
    pdf.section_title("8", "API Reference")

    pdf.table(
        ["Method", "Endpoint", "Auth", "Description"],
        [
            ["GET", "/", "-", "Citizens' Portal (SPA)"],
            ["GET", "/admin", "-", "Admin Command Center"],
            ["GET", "/health", "-", "Production health check"],
            ["GET", "/api/config", "-", "Ward & dustbin registry"],
            ["GET", "/api/dashboard", "-", "Full cached Pathway state"],
            ["GET", "/api/dustbins", "-", "Dustbin registry + live status"],
            ["GET", "/api/forecast", "-", "3-day predictive risk forecast"],
            ["POST", "/api/report/dustbin/detect", "-", "Upload photo -> AI extraction"],
            ["POST", "/api/report/dustbin/confirm", "-", "Confirm detected ID"],
            ["POST", "/api/report/road-issue", "Bearer", "Admin: report road hazard"],
            ["POST", "/api/van/collection", "Bearer", "Admin: mark collected"],
            ["POST", "/api/van/clear-road", "Bearer", "Admin: clear road issue"],
            ["POST", "/api/demo/simulate-crisis", "Bearer", "Demo: inject crisis"],
            ["WS", "/ws", "-", "Real-time state broadcast"],
        ],
        [18, 55, 18, 79]
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 9. EVENT LIFECYCLE
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("9", "Event Lifecycle & Data Flow")

    pdf.body_text(
        "The system processes events through a clear pipeline:"
    )

    steps = [
        ("1. Photo Upload", "Citizen captures a photo of a waste issue via the portal"),
        ("2. AI Detection", "FastAPI sends the image to Gemini 2.5 Flash Vision API"),
        ("3. ID Extraction", "AI returns the exact MCD dustbin ID (e.g., MCD-W04-001)"),
        ("4. Confirmation", "Citizen confirms the detection and submits the report"),
        ("5. Event Write", "FastAPI writes a JSON event file to the data/reports/ directory"),
        ("6. Weather Poll", "WeatherAPI.com rainfall data is polled every 10 minutes"),
        ("7. Pathway Process", "Pathway detects the new file and triggers recomputation"),
        ("8. Risk Scoring", "Risk scores are computed using the weighted multi-factor algorithm"),
        ("9. State Machine", "Dustbin states are updated based on report counts and thresholds"),
        ("10. Broadcast", "Atomic dashboard snapshot is broadcast via WebSocket to all clients"),
        ("11. Admin Action", "Admin can dispatch vans, clear issues from the command center"),
        ("12. Resolution", "Van collection events reset dustbin states and remove from queue"),
    ]
    for title, desc in steps:
        pdf.bullet(f"{desc}", f"{title}: ")

    pdf.sub_title("9.1 Rolling Windows")
    pdf.body_text(
        "Waste reports use a 2-hour rolling window — events older than 2 hours are automatically "
        "expired. Road issues use a 6-hour window. This ensures the dashboard always reflects "
        "current conditions. The deduplication window is 5 minutes — same dustbin, same window = "
        "merged report."
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 10. DEPLOYMENT ARCHITECTURE
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("10", "Deployment Architecture")

    pdf.table(
        ["Component", "Service", "Tier"],
        [
            ["Web Server + Pathway Engine", "Render.com Web Service", "Free / Starter ($7/mo)"],
            ["AI Vision (Gemini 2.5 Flash)", "Google AI Studio", "Free tier (15 RPM)"],
            ["Weather Data", "WeatherAPI.com", "Free tier (1M calls/mo)"],
            ["CI/CD", "GitHub Actions", "Free (2000 min/mo)"],
        ],
        [55, 55, 60]
    )

    pdf.info_box("Estimated Monthly Cost (Production): $7-$15/month for a single-city deployment.", pdf.SUCCESS)

    pdf.sub_title("10.1 Docker Deployment")
    pdf.body_text(
        "The application is fully containerized with a Dockerfile. The docker-entrypoint.sh script "
        "starts both the Uvicorn ASGI server and the Pathway streaming engine as background processes. "
        "The container is deployed to Render.com via the render.yaml configuration file."
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 11. SECURITY
    # ═══════════════════════════════════════════════════════════════════════
    pdf.section_title("11", "Security")

    pdf.table(
        ["Layer", "Mechanism"],
        [
            ["Admin Endpoints", "Bearer token authentication (strict 401)"],
            ["Report Dedup", "In-memory O(1) cache, 5-min window"],
            ["Dustbin ID Validation", "Strict regex MCD-W\\d{2}-\\d{3} against registry"],
            ["Data Integrity", "Atomic file writes (temp + rename)"],
            ["CORS", "Configurable origin whitelist"],
        ],
        [45, 125]
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 12. SCALABILITY
    # ═══════════════════════════════════════════════════════════════════════
    pdf.section_title("12", "Scalability Path")

    pdf.table(
        ["Scale", "Users", "Architecture"],
        [
            ["Pilot (1 city)", "10K", "Single Render container (current)"],
            ["Regional (10 cities)", "100K", "Horizontal Pathway workers + Redis pub/sub"],
            ["National (100+ cities)", "1M+", "Kubernetes cluster, Kafka event bus"],
        ],
        [40, 30, 100]
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 13. PROJECT STRUCTURE
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("13", "Project Structure")

    pdf.set_font("Courier", "", 9)
    pdf.set_fill_color(*pdf.LIGHT_BG)
    structure = (
        "HACK-FOR-GREEN-BHARAT-HACKATHON/\n"
        "+-- api/\n"
        "|   +-- server.py              # FastAPI - transport only\n"
        "+-- config/\n"
        "|   +-- dustbins.py            # 72 MCD collection points\n"
        "|   +-- wards.py               # 12 Delhi ward definitions\n"
        "|   +-- settings.py            # Thresholds, windows, weights\n"
        "+-- frontend/\n"
        "|   +-- citizen.html/js/css    # Citizens' Portal (SPA)\n"
        "|   +-- admin.html/js/css      # Admin Command Center\n"
        "+-- llm_layer/                 # Gemini integration module\n"
        "+-- data/\n"
        "|   +-- reports/               # Waste event JSON files\n"
        "|   +-- road/                  # Road issue event files\n"
        "|   +-- vans/                  # Van collection events\n"
        "|   +-- weather/               # Weather polling data\n"
        "|   +-- output/                # Pathway dashboard snapshots\n"
        "+-- pathway_engine.py          # The Brain - all computation\n"
        "+-- start.sh                   # One-shot startup script\n"
        "+-- requirements.txt           # Python dependencies\n"
        "+-- Dockerfile                 # Production container\n"
        "+-- render.yaml                # Render.com deployment config\n"
        "+-- .github/workflows/ci.yml   # CI/CD pipeline"
    )
    pdf.multi_cell(170, 4.5, structure, fill=True)
    pdf.ln(5)

    # ═══════════════════════════════════════════════════════════════════════
    # 14. SETUP & INSTALLATION
    # ═══════════════════════════════════════════════════════════════════════
    pdf.section_title("14", "Setup & Installation")

    pdf.sub_title("14.1 Requirements")
    pdf.bullet("Python 3.10+ (Ubuntu WSL strongly recommended)")
    pdf.bullet("Google Gemini API Key (https://aistudio.google.com/ - free)")
    pdf.bullet("WeatherAPI.com API Key (https://www.weatherapi.com/ - free)")

    pdf.sub_title("14.2 Installation Steps")
    pdf.set_font("Courier", "", 9)
    pdf.set_fill_color(*pdf.LIGHT_BG)
    install_cmds = (
        "git clone https://github.com/gintama1018/HACK-FOR-GREEN-BHARAT-HACKATHON.git\n"
        "cd HACK-FOR-GREEN-BHARAT-HACKATHON\n"
        "python3 -m venv .venv\n"
        "source .venv/bin/activate\n"
        "pip install -r requirements.txt\n"
        "cp .env.example .env  # Add your API keys\n"
        "bash start.sh         # Start the server"
    )
    pdf.multi_cell(170, 4.5, install_cmds, fill=True)
    pdf.ln(3)

    pdf.set_font("Arial", "", 10)
    pdf.table(
        ["Portal", "URL"],
        [
            ["Citizens' Dashboard", "http://localhost:8000/"],
            ["Admin Command Center", "http://localhost:8000/admin"],
        ],
        [55, 115]
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 15. DEMO MODE
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("15", "Demo Mode (For Judges)")

    pdf.body_text(
        "The Admin Command Room includes a built-in 'Simulate Crisis' button. Pressing it injects "
        "6 severe waste reports and a critical waterlogging road issue into Ward 12 (Shahdara North), "
        "triggering the full escalation matrix in real-time."
    )

    pdf.sub_title("What the judges will see:")
    pdf.bullet("Auto-triage the crisis into the Priority Queue")
    pdf.bullet("Escalate dustbin states from Reported to Critical in seconds")
    pdf.bullet("Render OSRM-routed road hazard polylines on the live map")
    pdf.bullet("Apply weather multiplication if rainfall is detected")
    pdf.bullet("Real-time WebSocket updates on both Citizens' and Admin portals simultaneously")

    # ═══════════════════════════════════════════════════════════════════════
    # 16. IMPACT & SOCIAL RELEVANCE
    # ═══════════════════════════════════════════════════════════════════════
    pdf.section_title("16", "Impact & Social Relevance")

    pdf.body_text(
        "India loses over 3,500 lives annually to road accidents caused by potholes (MoRTH). "
        "The devastating floods in Punjab and Delhi exposed how open waste and blocked drainage "
        "amplify natural disasters into public health emergencies."
    )

    pdf.sub_title("How InfraWatch Nexus addresses these crises:")
    pdf.bullet("A single photo replaces a 10-field government form. AI does the data entry. "
               "Citizens report in under 5 seconds.", "Eliminating Reporting Friction: ")
    pdf.bullet("A pothole during monsoon season is mathematically pushed to the top of the "
               "dispatch queue before it becomes fatal.", "Weather-Aware Prioritization: ")
    pdf.bullet("By clustering and deduplicating reports, city fleets target verified hotspots "
               "instead of patrolling blindly - reducing fuel waste and emissions.", "Optimizing Municipal Resources: ")
    pdf.bullet("Real-time map transparency proves to citizens that their government is responsive.",
               "Restoring Civic Trust: ")

    pdf.ln(3)
    pdf.info_box(
        'The goal is not to build another complaint box. The goal is to build a civic nervous system '
        'that feels danger before tragedy strikes.',
        pdf.ACCENT
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 17. FUTURE ROADMAP
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("17", "Future Roadmap")

    pdf.table(
        ["Priority", "Feature", "Impact"],
        [
            ["P0", "Negative sample awareness in AI prompts", "Reduce false positives by 40%"],
            ["P1", "Spatial deduplication (Haversine)", "Clean map, no cluster noise"],
            ["P2", "Auto-resolution of stale road issues", "Self-healing map data"],
            ["P3", "7-category waste classification", "Detailed analytics per ward"],
            ["P4", "Waste composition breakdown per ward", "Policy-actionable insights"],
            ["P5", "Multi-city deployment (Kubernetes)", "National scale platform"],
            ["P6", "Mobile app (Android APK)", "Increased citizen reach"],
        ],
        [20, 72, 78]
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 18. RESEARCH REFERENCES
    # ═══════════════════════════════════════════════════════════════════════
    pdf.section_title("18", "Research References")

    refs = [
        "1. Proenca & Simoes (2020). 'Deep Learning-Based Waste Detection in Natural and Urban "
        "Environments.' detect-waste benchmark, EfficientDet + EfficientNet two-stage framework.",

        "2. Mishra et al. (2025). 'iWatchRoad: Scalable Detection and Geospatial Visualization "
        "of Potholes for Smart Cities.' YOLOv8, OCR-GPS sync, Haversine dedup. arXiv:2508.10945.",

        "3. MDPI Applied Sciences (2024). 'IoT-Assisted Vehicle Route Optimization for Municipal "
        "Solid Waste Collection.' TOPSIS multi-criteria optimization, 14% route efficiency gain.",

        "4. IndiaAI / NITI Aayog (2024). 'AI-powered ward-wise performance reports for MSW management.' "
        "Ward-level analytics, predictive overflow with monsoon pattern integration.",

        "5. MCD Official Document: RO No. 20/DPI/MCD/2024-25. '106 Designated C&D Waste Collection "
        "Sites.' Municipal Corporation of Delhi (mcdonline.nic.in).",

        "6. Ministry of Road Transport & Highways (MoRTH). Road accident statistics and pothole-related "
        "fatalities data (2023-2024).",
    ]

    pdf.set_font("Arial", "", 9)
    for ref in refs:
        pdf.multi_cell(0, 4.5, ref)
        pdf.ln(2)

    # ═══════════════════════════════════════════════════════════════════════
    # SAVE
    # ═══════════════════════════════════════════════════════════════════════
    output_path = os.path.join(
        r"c:\Users\hp\HACK FOR GREEN BHARAT HACKATHON",
        "InfraWatch_Nexus_Project_Documentation.pdf"
    )
    pdf.output(output_path)
    print(f"\n{'='*60}")
    print(f"  PDF GENERATED SUCCESSFULLY!")
    print(f"  Path: {output_path}")
    print(f"  Pages: {pdf.page_no()}")
    print(f"{'='*60}")
    return output_path


if __name__ == "__main__":
    generate_documentation()
