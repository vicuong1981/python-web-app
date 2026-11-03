"""Feature-flag behaviour, using OpenFeature's in-memory provider in place of Flagship."""

import pytest
from fastapi.testclient import TestClient
from openfeature import api
from openfeature.provider.in_memory_provider import InMemoryFlag, InMemoryProvider

from app import flags
from app.main import app

client = TestClient(app)


def set_flags(**values):
    """Serve fixed values for the given flags (keys use _ instead of -)."""
    store = {
        key.replace("_", "-"): InMemoryFlag("v", {"v": value}) for key, value in values.items()
    }
    api.set_provider(InMemoryProvider(store))


@pytest.fixture(autouse=True)
def reset_provider():
    yield
    api.clear_providers()


def test_defaults_when_flagship_not_configured():
    r = client.get("/api/flags")
    assert r.json()["flags"] == flags.DEFAULTS


def test_new_homepage_flag_exposed_to_frontend():
    set_flags(new_homepage=True)
    assert client.get("/api/flags").json()["flags"]["new-homepage"] is True
    set_flags(new_homepage=False)
    assert client.get("/api/flags").json()["flags"]["new-homepage"] is False


def test_notes_kill_switch():
    set_flags(notes_api=False)
    assert client.get("/api/notes").status_code == 503
    assert client.post("/api/notes", json={"text": "hi"}).status_code == 503


def test_max_note_length_flag():
    set_flags(max_note_length=5)
    assert client.post("/api/notes", json={"text": "short"}).status_code == 201
    assert client.post("/api/notes", json={"text": "too long"}).status_code == 422


def test_user_headers_become_context():
    r = client.get("/api/flags", headers={"X-User-Id": "user-42"})
    assert r.json()["user"] == "user-42"


def test_site_banner_text():
    set_flags(site_banner="  Maintenance tonight at 10pm  ")
    assert client.get("/api/flags").json()["flags"]["site-banner"] == "Maintenance tonight at 10pm"


def test_site_banner_off_values_hide_it():
    for value in ("", "off", "None", "false"):
        set_flags(site_banner=value)
        assert client.get("/api/flags").json()["flags"]["site-banner"] == ""


def test_site_banner_is_capped():
    set_flags(site_banner="x" * 1000)
    assert len(client.get("/api/flags").json()["flags"]["site-banner"]) == flags.BANNER_MAX_LEN
