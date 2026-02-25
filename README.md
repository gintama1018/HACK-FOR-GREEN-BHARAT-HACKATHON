# InfraWatch Nexus 🏙️

**InfraWatch Nexus** is a real-time, AI-driven civic intelligence platform designed to seamlessly connect citizens with municipal dispatch operations. Built for the Hack For Green Bharat Hackathon, it bridges the gap between public reporting and tactical municipal response using cutting-edge streaming event architecture.

---

## 🚀 The Vision

Traditional municipal reporting systems are static forms that vanish into black-box databases, leaving citizens out of the loop and admins overwhelmed by unprioritized, duplicate data.

**InfraWatch Nexus changes the paradigm:**
1. **Citizens** are empowered with an immediate, transparent map of municipal conditions, using **Gemini 2.5 Flash Vision AI** to report issues with one photo upload.
2. **Administrators** operate a live, unified Command Room where every incoming event is instantly triaged by severity and weather conditions via a **Pathway Streaming Engine**.

## 🏗️ Technical Architecture

The system is built on an event-driven, decoupled architecture entirely replacing traditional CRUD loops.

```mermaid
graph TD
    %% Define Styles
    classDef portal fill:#121826,stroke:#3B82F6,stroke-width:2px,color:#fff
    classDef ai fill:#1E293B,stroke:#10B981,stroke-width:2px,color:#fff
    classDef engine fill:#1C2433,stroke:#F59E0B,stroke-width:2px,color:#fff
    classDef state fill:#0F172A,stroke:#64748B,stroke-width:2px,stroke-dasharray: 4 4,color:#fff

    subgraph "Public Interfaces"
        citizen["👤 Citizens' Portal<br>(Stateless Web UI)"]:::portal
    end

    subgraph "Municipal Operations"
        admin["⚙️ Admin Control Room<br>(Stateless Web UI)"]:::portal
    end

    subgraph "Ingestion & AI Edge (FastAPI)"
        api["FastAPI Server"]:::ai
        gemini["Gemini 2.5 Flash Vision API"]:::ai
        weather["WeatherAPI.com Live Data"]:::ai
    end

    subgraph "Core Nervous System (Pathway)"
        pathway["Pathway Streaming Engine"]:::engine
        state_db[("In-Memory State<br>& Priority Triage")]:::state
    end

    %% Flow
    citizen --"Uploads Photo"--> api
    api --"Direct REST Call"--> gemini
    gemini --"Extracts MCD Asset ID"--> api
    api --"Appends Event"--> pathway
    
    weather --"Live Rainfall Impact"--> pathway
    
    pathway --"Calculates Risk"--> state_db
    state_db --"Atomic State Broadcasts"--> admin
    state_db --"Atomic State Broadcasts"--> citizen
    
    admin --"Dispatch Van (Clears Status)"--> api
```

## ✨ Core Workflows (Live E2E Verified)

### 1. The Citizen Experience (Civic Transparency)
Citizens access a unified dark-mode tracking interface showing the real-time condition of all municipal assets.
*   **Drag-and-Drop Reporting:** Citizens drag a photo of an overflowing dustbin. **Gemini 2.5 Flash** instantly extracts the specific Municipal Corporation ID (e.g., `MCD-W12-005`), completely eliminating manual form entry.
*   **Instant Confirmation:** Once confirmed, the payload is fired.

![Citizens' Portal UI](docs/assets/citizen_ui.png)

### 2. The Admin Command Room (Tactical Triage)
The moment a report is fired, the Pathway engine recalculates the entire city's state. 
*   **Live Priority Dispatch Queue:** The dustbin instantly appears at the top of the Admin's queue, marked **ESCALATED** with an exact dynamic risk score (out of 100).
*   **Weather Multiplication:** Live `rainfall_mm_hr` data is polled. If it is raining, open waste infrastructure becomes an immediate health hazard, and the engine automatically boosts the item's priority.

![Admin Portal UI](docs/assets/admin_ui.png)

### 3. Resolution & State Flush
The Admin reviews the Live Map, notes the Escalated status, and dispatches a van.
*   **Instant Flush:** By hitting "Mark as Cleared", the clearance event is appended.
*   **Result:** Pathway instantly drops the dustbin out of the Priority Dispatch Queue and restores the map marker to a healthy "Green" state on all live screens concurrently.

*(Below: The priority queue instantly escalates a reported bin, and completely removes it once cleared by the truck).*

![Priority Triage Flow - Escalated](docs/assets/admin_escalated.png)
![Priority Triage Flow - Cleared](docs/assets/admin_cleared.png)

## 🛠️ How to Run Locally

### Requirements
*   Python 3.10+ (Ubuntu WSL strongly recommended)
*   Google Gemini API Key
*   WeatherAPI.com API Key

### Setup
1. Clone the repository and navigate into it.
2. Initialize the Python virtual environment and install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Populate your `.env` file with your API keys:
   ```env
   WX_API_KEY=your_weatherapi_key
   GEMINI_API_KEY=your_google_ai_studio_key
   ADMIN_TOKEN=INFRAWATCH_ADMIN_2026
   ```

### Execution
Run the convenient startup script which boots both the Pathway Engine and FastAPI server:
```bash
./start.sh
```

**Accessing the Portals:**
*   Citizens' Dashboard: `http://localhost:8000/`
*   Admin Live Command: `http://localhost:8000/admin` *(Uses default token `INFRAWATCH_ADMIN_2026` or whatever you set in `.env`)*
