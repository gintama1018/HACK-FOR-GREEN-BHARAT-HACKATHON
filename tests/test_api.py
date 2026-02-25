import pytest
from fastapi.testclient import TestClient
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from api.server import app

client = TestClient(app)

def test_health_check():
    """Verify the production health endpoint returns 200 OK and expected JSON."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert "cache_entries" in data

def test_unauthorized_admin_access():
    """Verify the road issue endpoint correctly blocks unauthenticated requests."""
    response = client.post("/api/report/road-issue", json={
        "from_dustbin": "MCD-W12-005",
        "to_dustbin": "MCD-W12-006",
        "ward_id": "W12",
        "issue_type": "pothole",
        "severity": 5
    })
    # Should be 401 Unauthorized without Bearer token
    assert response.status_code == 401
