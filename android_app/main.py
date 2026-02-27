#!/usr/bin/env python3
"""
InfraWatch Nexus Mobile App - Python Backend
Starts FastAPI server and Pathway engine for mobile use
"""
import os
import sys
import threading
import time
import json

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, "..", ".env"))

os.makedirs(os.path.join(PROJECT_ROOT, "data", "reports", "waste"), exist_ok=True)
os.makedirs(os.path.join(PROJECT_ROOT, "data", "reports", "road"), exist_ok=True)
os.makedirs(os.path.join(PROJECT_ROOT, "data", "reports", "vans"), exist_ok=True)
os.makedirs(os.path.join(PROJECT_ROOT, "data", "reports", "weather"), exist_ok=True)
os.makedirs(os.path.join(PROJECT_ROOT, "data", "output"), exist_ok=True)

def start_pathway():
    """Start Pathway engine in background thread"""
    try:
        import pathway_engine
        pathway_engine.run()
    except Exception as e:
        print(f"[Pathway] Error: {e}")

def start_fastapi():
    """Start FastAPI server"""
    try:
        import uvicorn
        from api.server import app
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
    except Exception as e:
        print(f"[FastAPI] Error: {e}")

def create_static_files():
    """Create simple static file server HTML"""
    html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>InfraWatch Nexus</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #fff;
        }
        .loading {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100vh;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        }
        .spinner {
            width: 50px;
            height: 50px;
            border: 4px solid #334155;
            border-top: 4px solid #10b981;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .text { margin-top: 20px; font-size: 18px; color: #94a3b8; }
        .sub { margin-top: 8px; font-size: 14px; color: #64748b; }
    </style>
    <script>
        function checkServer() {
            fetch('http://127.0.0.1:8000/health', { 
                mode: 'no-cors',
                cache: 'no-store'
            })
            .then(() => {
                window.location.href = 'http://127.0.0.1:8000/';
            })
            .catch(() => {
                setTimeout(checkServer, 1000);
            });
        }
        setTimeout(checkServer, 2000);
    </script>
</head>
<body>
    <div class="loading">
        <div class="spinner"></div>
        <div class="text">InfraWatch Nexus</div>
        <div class="sub">Connecting to server...</div>
    </div>
</body>
</html>"""
    
    with open(os.path.join(PROJECT_ROOT, "app", "src", "main", "assets", "index.html"), "w") as f:
        f.write(html)

if __name__ == "__main__":
    print("=" * 50)
    print("  InfraWatch Nexus Mobile App")
    print("=" * 50)
    
    create_static_files()
    print("[+] Static files created")
    
    pathway_thread = threading.Thread(target=start_pathway, daemon=True)
    pathway_thread.start()
    print("[+] Pathway engine started")
    
    time.sleep(3)
    
    fastapi_thread = threading.Thread(target=start_fastapi, daemon=True)
    fastapi_thread.start()
    print("[+] FastAPI server started on http://127.0.0.1:8000")
    
    print("=" * 50)
    print("  App ready! Open in WebView.")
    print("=" * 50)
    
    while True:
        time.sleep(1)
