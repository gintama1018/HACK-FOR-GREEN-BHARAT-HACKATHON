#!/usr/bin/env python3
"""Simple server to test the mobile UI without full backend"""
import os
import sys
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

app = FastAPI()

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
async def citizen_portal(request: Request):
    with open(os.path.join(FRONTEND_DIR, "citizen.html"), "r") as f:
        return f.read()

@app.get("/admin", response_class=HTMLResponse)
async def admin_portal(request: Request):
    with open(os.path.join(FRONTEND_DIR, "admin.html"), "r") as f:
        return f.read()

@app.get("/health")
async def health():
    return {"status": "ok", "mode": "ui-test"}

if __name__ == "__main__":
    import uvicorn
    print("=" * 50)
    print("  Mobile UI Test Server")
    print("  Open http://127.0.0.1:8000 in your browser")
    print("=" * 50)
    uvicorn.run(app, host="127.0.0.1", port=8000)
