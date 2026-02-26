# InfraWatch Nexus — Complete Project Report

## Table of Contents
1. [The Inspiration (Why We Built This)](#1-the-inspiration)
2. [The Idea (What We Built)](#2-the-idea)
3. [The Plan (How We Designed It)](#3-the-plan)
4. [The Execution (How We Built It)](#4-the-execution)
5. [System Architecture & Working](#5-system-architecture--working)
6. [Tech Stack](#6-tech-stack)
7. [What Makes It Special](#7-what-makes-it-special)
8. [Real-World Readiness](#8-real-world-readiness)
9. [Impact & The Green Bharat Mission](#9-impact--the-green-bharat-mission)

---

## 1. The Inspiration

India is facing a silent urban infrastructure crisis that claims thousands of lives every year.

**The Pothole Crisis:** India loses over 3,500 lives annually to road accidents caused by unrepaired potholes (Ministry of Road Transport). The recent tragic deaths in Delhi — where citizens died because a pothole went unreported or was deprioritized by the municipality — made national headlines and exposed a systemic failure in how cities handle infrastructure complaints.

**The Flood Crisis:** The devastating floods in Punjab and other states in recent months revealed an even deadlier pattern. When monsoons hit, open waste bins become disease vectors, blocked drains amplify flooding, and crumbling roads become death traps. But municipal systems treat all complaints identically — a pothole on a sunny day gets the same priority as a pothole during a torrential downpour.

**The Reporting Gap:** Existing government platforms like the Swachhata-MoHUA app force citizens to download bloated native apps, manually locate themselves on a map, type out descriptions, and select hazard categories. This friction means most people simply don't report. The complaints that do come in are dumped into static databases where admins see thousands of duplicate entries with no way to distinguish critical hazards from minor inconveniences.

> *We asked ourselves: What if civic reporting was as effortless as taking a photo? And what if the system could feel environmental danger before tragedy strikes?*

That question became **InfraWatch Nexus**.

---

## 2. The Idea

InfraWatch Nexus is a **real-time, AI-driven civic intelligence platform** that replaces the traditional complaint-form model with a live, streaming "civic nervous system."

It has two portals:

### The Citizens' Portal (Public)
- **Zero forms.** A citizen simply uploads a photo of a damaged dustbin, pothole, or overflowing waste container.
- **Google Gemini 2.5 Flash Vision AI** instantly scans the photo and extracts the exact Municipal Corporation Asset ID (e.g., `MCD-W12-005`) painted on the dustbin — completely eliminating manual data entry.
- **Live Map Transparency.** The moment a report is submitted, the citizen's map updates in real-time, showing the hazard marker and its current status (Reported → Escalated → Critical → Cleared). Citizens can see their government responding.

### The Admin Command Room (Private)
- **Auto-Triaging Priority Queue.** Instead of a flat list of complaints, the Admin sees a mathematically ranked Priority Dispatch Queue. The most dangerous, weather-amplified, highly-reported hazards appear at the top automatically.
- **Intelligent Deduplication.** If 50 citizens photograph the same overflowing bin, the system doesn't create 50 tasks. It merges them into a single, heavily-escalated civic cluster.
- **Weather-Aware Escalation.** The system continuously polls live weather data. If heavy rain is detected over a ward with open waste reports, the system automatically multiplies the hazard risk score — pushing it to the top of the queue before the rain turns waste into a health epidemic.
- **One-Click Resolution.** When the Admin dispatches a van, the hazard is instantly flushed from the queue and the citizen's map marker turns green — all in real-time via WebSockets.

### Predictive Risk Forecast
- A dedicated **3-Day Risk Forecast** tab combines WeatherAPI forecast data with current report density to predict which wards will become critical before it happens. This moves municipal governance from **reactive** to **predictive**.

---

## 3. The Plan

### Architectural Philosophy: "Stream Everything, Store Nothing"

We made a deliberate architectural decision to abandon traditional databases entirely. Instead of a PostgreSQL/MongoDB CRUD model (Create → Read → Update → Delete), we built a **streaming event-driven architecture** where:

- Every citizen report is an **immutable event** written to a file stream.
- Every weather update is an **immutable event** written to a separate stream.
- Every van dispatch is an **immutable event** written to a third stream.
- The **Pathway Engine** continuously processes all three streams, joins them, calculates risk scores, deduplicates, and outputs a single **atomic JSON state** representing the entire city.
- The frontend portals are **completely stateless** — they simply render whatever state the engine broadcasts.

This design means:
- **Zero database queries.** The dashboard is always pre-computed.
- **Zero stale data.** Every update propagates in milliseconds.
- **Crash recovery.** Restart the engine → it replays all events from files → state is rebuilt automatically.

### Responsibility Matrix

| Layer | Does | Does NOT |
|-------|------|----------|
| **Citizens' Portal** | Accept photo, show confirmation, display state | Compute anything |
| **Admin Portal** | Accept road reports, show priority queue | Compute anything |
| **FastAPI** | Validate, write events, dedup, auth, broadcast | Score, rank, aggregate |
| **Pathway Engine** | Aggregate, score, rank, state transitions, weather join | Serve HTTP, touch frontend |
| **WebSocket** | Broadcast single atomic state to all clients | Compute or filter |

---

## 4. The Execution

### Phase 1: Core Infrastructure
Built the foundational data model — 72 dustbins across 12 wards of Delhi with real GPS coordinates, strict MCD-format Asset IDs (`MCD-W{ward}-{number}`), and a deterministic state machine (Clear → Reported → Escalated → Critical → Cleared).

### Phase 2: The Pathway Streaming Engine (The Brain)
Implemented the core intelligence using the **Pathway Data Engine** — a high-throughput Python streaming framework. The engine:
- Ingests waste events, road events, and van events from the filesystem
- Applies event-time windowing (2-hour windows for waste, 6-hour for roads)
- Calculates per-dustbin risk scores normalized to 0–100
- Applies live rainfall multipliers (capped at normalization threshold)
- Maintains a unified Priority Queue (capped at top 20 items)
- Outputs an atomic JSON dashboard snapshot using temp-file → rename (prevents partial reads)

### Phase 3: FastAPI Transport Layer
Built a strict, transport-only API server:
- `POST /api/report/dustbin/detect` — Sends the citizen's photo to Gemini Vision, extracts Asset ID via strict regex
- `POST /api/report/dustbin/confirm` — Validates against the 72-dustbin registry, applies O(1) dedup, writes event
- `POST /api/report/road-issue` — Admin-only, validates both dustbin IDs, requires Bearer token
- `POST /api/van/collection` — Admin-only, writes clearance event, flushes dedup cache
- `GET /api/forecast` — 3-day predictive risk forecast combining WeatherAPI + report density
- `GET /health` — Production health check for Render monitoring
- `WebSocket /ws` — Single broadcast channel, same atomic state to all connected clients

### Phase 4: Citizens' Portal UI
Dark-mode, mobile-first interface with:
- Drag-and-drop photo upload with live preview
- AI detection confirmation dialog (shows detected Asset ID + street name)
- Live Leaflet.js map with color-coded markers (green = clear, red = critical)
- Real-time WebSocket updates — no page refresh needed

### Phase 5: Admin Command Room UI
Navy-themed command center with:
- Token-based authentication modal
- Live Priority Dispatch Queue with severity badges and risk scores
- Interactive map with dispatch overlays
- Road issue reporting form with severity grid
- Van collection confirmation form
- 🔮 Predictive 3-Day Risk Forecast tab
- 🚨 "Simulate Crisis" demo button for judges

### Phase 6: Deployment
- **Dockerized** the entire application (Pathway + FastAPI in one container)
- Deployed to **Render.com** with dynamic `$PORT` binding
- Configured `wss://` (secure WebSockets) for HTTPS production
- Created a lean `docker-entrypoint.sh` to prevent port-scan timeouts

### Phase 7: Production Hardening
- GitHub Actions CI/CD pipeline (lint + tests on every push)
- `/health` endpoint for platform monitoring
- `SECURITY.md` with auth, CORS, rate limiting, and data protection policies
- Comprehensive `README.md` with Mermaid diagrams, API reference, cost estimates
- Git release tag `v1.0.0`

---

## 5. System Architecture & Working

### High-Level Architecture

```
┌─────────────────┐     ┌─────────────────┐
│  Citizens'      │     │  Admin Command   │
│  Portal (Web)   │     │  Room (Web)      │
└────────┬────────┘     └────────┬─────────┘
         │ wss://                │ wss://
         ▼                      ▼
┌─────────────────────────────────────────┐
│           FastAPI Transport Layer       │
│  • Photo Upload → Gemini Vision AI     │
│  • Event Validation & Dedup (O(1))     │
│  • Bearer Token Auth for Admin         │
│  • WebSocket Broadcast (atomic state)  │
└─────────────────┬───────────────────────┘
                  │ Write JSON events
                  ▼
┌─────────────────────────────────────────┐
│        Pathway Streaming Engine         │
│  • Ingests: Waste + Road + Van events   │
│  • Joins: Live WeatherAPI rainfall      │
│  • Computes: Risk scores (0-100)        │
│  • Outputs: Atomic dashboard.jsonl      │
└─────────────────┬───────────────────────┘
                  │ Polls
                  ▼
┌─────────────────────────────────────────┐
│          External Services              │
│  • Google Gemini 2.5 Flash (Vision AI)  │
│  • WeatherAPI.com (Live rainfall data)  │
└─────────────────────────────────────────┘
```

### Data Flow (Event Lifecycle)

1. **Citizen uploads photo** → FastAPI receives it
2. **FastAPI → Gemini Vision API** → AI extracts the Municipal Asset ID from the image
3. **Citizen confirms** → FastAPI validates against the 72-dustbin registry
4. **Dedup check** → If same dustbin reported within 5 minutes, reports are merged (not duplicated)
5. **Event written** → Immutable JSON file dropped into `data/reports/waste/`
6. **Pathway Engine detects new file** → Recalculates entire city state
7. **Weather multiplier applied** → If raining, waste hazards get boosted priority
8. **Atomic state broadcast** → WebSocket pushes new state to ALL connected clients
9. **Admin sees escalated item** → Clicks "Dispatch Van"
10. **Van event written** → Pathway recalculates → Item removed from queue → Citizen map turns green

**Total latency from citizen photo to admin alert: under 6 seconds.**

### Dustbin State Machine

```
                    1-2 reports
    ┌─────── Clear ──────────► Reported
    │                              │
    │                    ≥3 reports OR
    │                    overflow ≥ 4
    │                              ▼
    │  Van clears         ◄─── Escalated
    │                              │
    │                    ≥5 reports OR
    │                    Escalated + Rain > 10mm/hr
    │                              ▼
    └───── Cleared ◄──────── Critical
```

---

## 6. Tech Stack

| Layer | Technology | Why We Chose It |
|-------|-----------|-----------------|
| **Frontend** | HTML5, CSS3, Vanilla JavaScript | Zero framework overhead, instant load |
| **Maps** | Leaflet.js | Lightweight, open-source map rendering |
| **Real-time Comms** | WebSockets (wss://) | Sub-second bidirectional updates |
| **Backend API** | FastAPI (Python) | Async-native, automatic validation |
| **ASGI Server** | Uvicorn | Production-grade async server |
| **Core Engine** | Pathway (Python) | High-throughput streaming data processing |
| **AI Vision** | Google Gemini 2.5 Flash | State-of-the-art multimodal AI for OCR |
| **Weather Data** | WeatherAPI.com | Real-time rainfall data, free tier |
| **Containerization** | Docker | Reproducible deployment environment |
| **Hosting** | Render.com | Supports WebSockets + background processes |
| **CI/CD** | GitHub Actions | Automated linting and testing on every push |

---

## 7. What Makes It Special

### 1. AI Does the Data Entry (Not the Citizen)
Most civic apps ask citizens to fill 10+ fields. We ask for one photo. Gemini Vision reads the Municipal Asset ID painted on the physical dustbin and auto-fills everything. Reporting time: **under 5 seconds**.

### 2. No Database — Pure Streaming
We didn't just build a CRUD app with a prettier UI. We threw away the database entirely and used a **stream processing engine** (Pathway). This is the same architectural pattern used by financial trading platforms and real-time fraud detection systems. For a civic app, this is unprecedented.

### 3. Weather-Aware Dynamic Prioritization
This is our signature innovation. The system doesn't treat all complaints equally. It continuously polls live weather data and mathematically amplifies hazard scores when environmental conditions make them dangerous. A pothole + monsoon = automatic Critical priority. No other civic platform does this.

### 4. Intelligent Deduplication
When 50 people photograph the same overflowing bin, legacy systems create 50 separate tasks. Our engine merges them into one highly-escalated civic cluster. This alone saves municipal workers hours of manual triage.

### 5. Predictive Risk Forecasting
The `/api/forecast` endpoint doesn't just react to current conditions — it projects forward 3 days using weather forecasts combined with current report density. Admins can see which wards will become critical tomorrow and pre-deploy resources.

### 6. "Simulate Crisis" Demo Mode
A built-in demo button lets judges (or stakeholders) inject a synthetic crisis and watch the system auto-triage it in real-time. This proves the system works under pressure, not just in ideal conditions.

### 7. True Real-Time Synchronization
Both portals (Citizen + Admin) share the same WebSocket connection. When an Admin clears a hazard, the Citizen's map marker turns green simultaneously — zero page refresh, zero polling, zero delay.

---

## 8. Real-World Readiness

### Current Deployment Status
- **Live URL:** [https://infrawatch-nexus-tnlf.onrender.com](https://infrawatch-nexus-tnlf.onrender.com)
- **Admin Access:** `/admin` with Bearer token authentication
- **Uptime:** Maintained by Render.com with automatic container restarts
- **SSL/TLS:** HTTPS enforced, secure WebSockets (wss://)

### Production Readiness Checklist

| Requirement | Status |
|-------------|--------|
| HTTPS / TLS encryption | ✅ Enforced by Render |
| Authentication (Admin) | ✅ Bearer token via env variable |
| Input validation | ✅ Strict regex, registry lookup, type checking |
| Deduplication | ✅ O(1) in-memory with 5-minute window |
| Error handling | ✅ Gemini timeout → manual fallback dropdown |
| CORS policy | ✅ Configured (restrictable for production) |
| Health monitoring | ✅ `/health` endpoint |
| CI/CD pipeline | ✅ GitHub Actions (lint + test) |
| Security docs | ✅ SECURITY.md with full policy |
| Crash recovery | ✅ Pathway replays events from filesystem |
| Docker containerization | ✅ Single-container deployment |
| Dynamic port binding | ✅ `os.environ.get("PORT")` for PaaS compatibility |

### Scalability Path

| Scale | Users | Architecture |
|-------|-------|-------------|
| **Pilot** (1 city) | 10K | Single Render container (current) |
| **Regional** (10 cities) | 100K | Horizontal Pathway workers + Redis pub/sub |
| **National** (100+ cities) | 1M+ | Kubernetes cluster, Kafka event bus, per-city shards |

### Cloud Cost Estimate

| Component | Service | Monthly Cost |
|-----------|---------|-------------|
| Web Server + Engine | Render.com Starter | $7 |
| AI Vision (Gemini) | Google AI Studio Free | $0 |
| Weather Data | WeatherAPI.com Free | $0 |
| CI/CD | GitHub Actions Free | $0 |
| **Total** | | **$7/month** |

A full-city civic intelligence platform for the cost of a single cup of coffee per month.

### Government Integration Path

InfraWatch Nexus is designed to integrate with existing municipal systems:
1. **SCADA-compatible Asset IDs** — Our `MCD-W{ward}-{number}` format mirrors real Municipal Corporation numbering
2. **REST API** — Any existing government dashboard can consume our `/api/dashboard` endpoint
3. **Webhook-ready** — Event files can trigger external notification systems (SMS, email, push)
4. **Ward-level granularity** — Matches India's existing municipal ward administrative structure

---

## 9. Impact & The Green Bharat Mission

InfraWatch Nexus directly addresses the **Swachh Bharat** and **Green India** missions:

### Environmental Impact
- **Reduced Fleet Emissions:** By routing trucks only to verified, severe, deduplicated hotspots instead of blind patrols, municipal fleet fuel consumption drops significantly.
- **Prevented Flood Damage:** Weather-aware escalation ensures open waste and blocked drains are cleared before monsoons amplify their damage.
- **Resource Optimization:** AI-driven triage means fewer trucks doing more effective work — less fuel, less waste, less carbon.

### Public Health Impact
- **Disease Prevention:** Open waste during monsoons is a primary vector for waterborne diseases. Our weather multiplier ensures these hazards are cleared proactively.
- **Road Safety:** Potholes and road damage are escalated before they cause accidents — especially during rain when visibility is low and stopping distances increase.

### Civic Trust Impact
- **Transparency:** Citizens can see their report on the live map instantly. They know it wasn't swallowed by a bureaucratic black hole.
- **Accountability:** Every event is timestamped, immutable, and traceable. Municipal response times become measurable.
- **Participation:** When reporting takes 5 seconds instead of 5 minutes, more citizens participate. More participation = better data = better city.

---

> *"The goal is not to build another complaint box. The goal is to build a civic nervous system that feels danger before tragedy strikes."*

---

**Built with ❤️ for the Hack For Green Bharat Hackathon 2026**

**Live Demo:** [https://infrawatch-nexus-tnlf.onrender.com](https://infrawatch-nexus-tnlf.onrender.com)
**GitHub:** [github.com/gintama1018/HACK-FOR-GREEN-BHARAT-HACKATHON](https://github.com/gintama1018/HACK-FOR-GREEN-BHARAT-HACKATHON)
