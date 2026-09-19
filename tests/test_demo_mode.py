"""The public demo.

A public URL means anyone can call any endpoint. These tests pin the promises the
deployment makes: nothing that spends a key, nothing that edits shared
configuration, and only the bundled synthetic companies can be run.
"""

import pytest
from fastapi.testclient import TestClient

from app import demo
from app.config import settings
from app.llm import clients
from app.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    # A key being present must not matter in demo mode.
    monkeypatch.setattr(settings, "nvidia_api_key", "nvapi-test-not-real")
    return TestClient(app)


def test_models_are_off_even_when_a_key_is_present(client):
    assert settings.has_nvidia_key is True
    assert clients.available() is False


def test_editing_the_rules_is_refused(client):
    r = client.put("/api/rules/raw", json={"yaml": "bands: {}\nrules: []"})
    assert r.status_code == 403
    assert "read-only" in r.json()["detail"]


def test_launching_the_eval_is_refused(client):
    assert client.post("/api/eval", json={}).status_code == 403


def test_watchlist_cannot_be_changed(client):
    assert client.post("/api/watchlist", json={"name": "Anyone"}).status_code == 403
    assert client.delete("/api/watchlist/Northwind Logistics").status_code == 403


def test_only_bundled_companies_can_be_run(client):
    r = client.post("/api/runs", json={"name": "Some Real Company Ltd"})
    assert r.status_code == 400
    assert "Northwind Logistics" in r.json()["detail"]


def test_reading_still_works(client):
    for path in ("/api/health", "/api/rules", "/api/pipeline", "/api/intents", "/api/eval"):
        assert client.get(path).status_code == 200, path


def test_health_reports_demo_mode(client):
    assert client.get("/api/health").json()["demo_mode"] is True


def test_owner_field_is_length_capped(client):
    r = client.put("/api/leads/northwind-logistics/owner", json={"owner": "x" * 500})
    assert len(r.json()["owner"]) == demo.MAX_OWNER_LENGTH


def test_outside_demo_mode_nothing_is_locked(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    client = TestClient(app)
    monkeypatch.setattr("app.main.settings", settings)
    r = client.put("/api/rules/raw", json={"yaml": "not: valid: rules"})
    assert r.status_code == 400          # rejected as invalid, not as read-only
