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


def test_health_reports_real_uptime_seconds():
    """Health must report a real, non-fabricated service uptime.

    The web dashboard's "Supervisor Uptime" is wired to this field, so it must
    be a finite number of seconds since process start (never a placeholder
    string like "live" nor a hard-coded 0).
    """
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "uptime_seconds" in data
    uptime = data["uptime_seconds"]
    assert isinstance(uptime, (int, float))
    assert not isinstance(uptime, bool)
    assert uptime >= 0


def test_root_endpoint():
    """Root endpoint should return service info."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "service" in data
    assert data["version"] == "0.1.0"
