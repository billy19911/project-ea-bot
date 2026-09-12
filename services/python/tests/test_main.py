"""Basic tests for the EA Bot Python service."""

from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_health_check():
    """Health endpoint should return ok."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_root_endpoint():
    """Root endpoint should return service info."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "service" in data
    assert data["version"] == "0.1.0"
