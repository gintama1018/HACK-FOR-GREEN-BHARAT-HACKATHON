# 🌿 InfraWatch Nexus — Hack for Green Bharat 2026

![Banner](https://img.shields.io/badge/Status-Finalist_Build-success?style=for-the-badge&color=2ea44f)
![Stack](https://img.shields.io/badge/Stack-Pathway_FastAPI_Leaflet-blue?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-lightgrey?style=for-the-badge)

> **A Real-Time Municipal Intelligence Engine**
> Transforming fragmented civic reports into actionable, prioritized waste & road operations.

---

## 📊 The "Why"

Municipal operations are reactive. We make them **Predictive & Prioritized**.
Instead of a static list of complaints, InfraWatch Nexus uses a **Streaming RISC Engine** to dynamically score and rank every ward in Delhi based on live data.

---

## 🏗 Architecture Infographic

```mermaid
graph TD
    subgraph Sources [Live Data Sources]
        A[UserData: Waste Reports] -->|POST| API
        B[UserData: Road Reports] -->|POST| API
        C[IoT/Fleet: Van Logs] -->|POST| API
        D[OpenWeatherMap: Rainfall] -->|Poll| PW
    end

    subgraph Core [Pathway Intelligence Engine]
        API[FastAPI Intake] -->|Write Unique JSON| FS[File System Watcher]
        FS --> PW[Pathway Streaming Pipeline]
        PW -->|Windowed Risk Compute| Risk[Dynamic Risk Engine]
        Risk -->|Unified Priority Queue| PQ[Priority Output]
    end

    subgraph Viz [Command Dashboard]
        PQ -->|Cache Read| API_READ[FastAPI Reader]
        API_READ -->|WebSocket Push| UI[Live Dashboard]
    end
    
    style Sources fill:#f9f,stroke:#333,stroke-width:2px
    style Core fill:#bbf,stroke:#333,stroke-width:2px
    style Viz fill:#dfd,stroke:#333,stroke-width:2px
```

---

## 🚀 Key Features

### 1. Dual-Risk Scoring Engine
We don't just count reports. We **weigh** them.
- **Waste Risk (70%)**: Overflow Severity × Frequency × Collection Delay
- **Road Risk (30%)**: Severity × Density × Weather Impact
- *Result*: A "Critical" waste situation always outranks a "Warning" road issue.

### 2. Resilient Data Pipeline
- **No Simulators**: Real HTTP intake.
- **Zero Data Loss**: Unique JSON file generation for every event.
- **Offline Capable**: Works even if weather API fails (graceful degradation).

---

## 🛠 Tech Stack

| Component | Technology | Role |
| :--- | :--- | :--- |
| **Streaming Core** | **Pathway** | The brain. Handles windows, joins, and risk math. |
| **API Layer** | **FastAPI** | High-performance async intake & WebSocket push. |
| **Frontend** | **Vanilla JS + Leaflet** | Lightweight, dependency-free dashboard. |
| **Environment** | **WSL + Docker** | Enterprise-grade deployment readiness. |

---

## 📦 Installation

```bash
# 1. Clone
git clone https://github.com/gintama1018/HACK-FOR-GREEN-BHARAT-HACKATHON.git
cd HACK-FOR-GREEN-BHARAT-HACKATHON

# 2. Setup Env
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Configure
echo "OPENWEATHER_API_KEY=your_key" > .env

# 4. Run
# Terminal 1 (Pathway):
wsl -- python3 pathway_engine.py

# Terminal 2 (API):
python -m api.server
```

---

## 📸 Dashboard Preview

*(Add screenshots here)*

---

*Crafted with ❤️ for a Greener Bharat.*
