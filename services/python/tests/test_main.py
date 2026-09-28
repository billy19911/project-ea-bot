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


def test_sltp_seed_reads_real_settings_attrs():
    """The startup SLTP seeding must reference settings fields that EXIST.

    Regression: a settings field rename (``sltp_progressive_enabled`` →
    ``sltp_tp1_lock_enabled``) left `main.py` reading a non-existent attribute,
    so the whole runtime-settings seed/apply block raised AttributeError and was
    silently swallowed — meaning caps/SLTP were never applied at startup.
    """
    from src.config import settings
    from src.system.settings_store import get_settings_store

    # This mirrors main.py's lifespan seed exactly; it must not raise.
    seeded = {
        "sltp_management_enabled": (
            1.0 if getattr(settings, "sltp_management_enabled", False) else 0.0
        ),
        "sltp_breakeven_enabled": (
            1.0 if getattr(settings, "sltp_breakeven_enabled", True) else 0.0
        ),
        "sltp_progressive_enabled": (
            1.0 if getattr(settings, "sltp_tp1_lock_enabled", True) else 0.0
        ),
        "sltp_trailing_enabled": (1.0 if getattr(settings, "sltp_trailing_enabled", True) else 0.0),
    }
    # Every referenced attribute exists (no MISSING sentinel).
    assert hasattr(settings, "sltp_tp1_lock_enabled")
    assert not hasattr(settings, "sltp_progressive_enabled")

    store = get_settings_store()
    store.seed_missing(seeded)  # must not raise
    values = store.snapshot().values
    assert "sltp_progressive_enabled" in values
