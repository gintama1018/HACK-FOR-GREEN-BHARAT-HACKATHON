# AGENTS.md - InfraWatch Nexus Developer Guide

This file provides guidelines for agentic coding agents working on this codebase.

## Project Overview

**InfraWatch Nexus** is a real-time, AI-driven civic intelligence platform built with:
- **FastAPI** - REST API and WebSocket server
- **Pathway** - Streaming event processing engine
- **Google Gemini 2.5 Flash** - Vision AI for dustbin ID extraction
- **WeatherAPI.com** - Live rainfall data for risk scoring

---

## Build / Lint / Test Commands

### Setup
```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create .env file (copy from .env.example)
cp .env.example .env
```

### Running the Application
```bash
# Full stack (Pathway + FastAPI)
bash start.sh

# Or manually:
python pathway_engine.py &        # Start streaming engine
python -m uvicorn api.server:app  # Start API server
```

### Testing

**Run all tests:**
```bash
pytest tests/
```

**Run a single test:**
```bash
pytest tests/test_api.py::test_health_check
pytest tests/test_api.py::test_unauthorized_admin_access
```

**Run with verbose output:**
```bash
pytest tests/ -v
```

### Linting (CI uses flake8)
```bash
# Strict mode (fails on syntax errors)
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics

# Warnings mode (max line length 127, max complexity 10)
flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics
```

### Smoke Test
```bash
bash smoke_test.sh
```

---

## Code Style Guidelines

### General Principles
- **Separation of concerns**: FastAPI (`api/server.py`) handles transport only; Pathway (`pathway_engine.py`) handles all computation
- **Stateless services**: API reads cached state from Pathway output files; no in-memory computation in API
- **Event-driven architecture**: Write JSON events to watched directories; Pathway processes them

### Imports
- Standard library first, then third-party, then local
- Group by: `os/sys/json` → `requests` → `pathway` → `fastapi` → local imports
- Use absolute imports with `sys.path.insert(0, ...)` pattern for project root

```python
import os
import json
import requests

import pathway as pw
from fastapi import FastAPI

from config.settings import SETTING_NAME
from config.wards import WARDS
```

### Formatting
- **Line length**: Max 127 characters (CI enforced)
- **Indentation**: 4 spaces (no tabs)
- **Section headers**: Use `═` characters for visual separators
```python
# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
```
- **Docstrings**: Use triple quotes for module-level and function documentation

### Types
- Use Python type hints where beneficial
- Prefer explicit typing for function parameters and return values
```python
def get_dustbin(dustbin_id: str) -> Optional[dict]:
```

### Naming Conventions
- **Variables/functions**: `snake_case` (e.g., `dustbin_id`, `get_ward_dustbins`)
- **Classes**: `PascalCase` (e.g., `TestClient`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `MAX_LINE_LENGTH`)
- **Private functions**: Leading underscore (e.g., `_weather_poller`)

### Error Handling
- Use try/except with specific exception types
- Log errors before returning/raising
- Return appropriate HTTP status codes (401 for unauthorized, 422 for validation errors)

```python
try:
    resp = requests.get(url, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
except Exception as e:
    print(f"[Weather] Network error: {e}")
```

### Configuration
- All settings in `config/settings.py`
- Dustbin registry in `config/dustbins.py`
- Ward data in `config/wards.py`
- Environment variables via `python-dotenv` (load in `api/server.py` and `pathway_engine.py`)

### Testing Patterns
- Tests go in `tests/` directory
- Use `pytest` with `fastapi.testclient.TestClient`
- Import app from `api.server import app`
- Add project root to path: `sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))`

```python
import pytest
from fastapi.testclient import TestClient
import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from api.server import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
```

### File Organization
```
HACK-FOR-GREEN-BHARAT-HACKATHON/
├── api/
│   └── server.py          # FastAPI transport layer
├── config/
│   ├── dustbins.py       # Dustbin registry
│   ├── settings.py       # Application settings
│   └── wards.py          # Ward data
├── data/
│   ├── output/           # Pathway dashboard output
│   └── reports/          # Event directories (waste, road, vans, weather)
├── docs/
├── frontend/
├── llm_layer/
├── stream_engine/
├── tests/
│   └── test_api.py       # API tests
├── ingestion/
├── pathway_engine.py     # Pathway streaming engine
├── start.sh              # Startup script
└── requirements.txt      # Python dependencies
```

### API Patterns
- All endpoints return JSON (use `JSONResponse` when needed)
- WebSocket at `/ws` for real-time state broadcasts
- Admin endpoints require Bearer token authentication
- Health check at `/health`

---

## Environment Variables

Required in `.env`:
```
WX_API_KEY=           # WeatherAPI.com key
GEMINI_API_KEY=      # Google Gemini API key
ADMIN_TOKEN=         # Admin portal authentication (default: INFRAWATCH_ADMIN_2026)
```

---

## Key Files

| File | Purpose |
|------|---------|
| `api/server.py` | FastAPI server, routes, WebSocket |
| `pathway_engine.py` | Streaming engine, risk calculation |
| `config/settings.py` | All configurable constants |
| `config/dustbins.py` | Dustbin ID registry |
| `config/wards.py` | Ward boundaries and road segments |

---

## Notes for Agents

- This is a hackathon project; prioritize functionality over polish
- The CI runs flake8 (strict mode for syntax errors, warnings mode for style)
- Tests must pass before merging to main
- For any architectural questions, follow the "transport vs compute" separation strictly
