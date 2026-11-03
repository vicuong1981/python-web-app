"""The Jekyll-built site is served from SITE_DIR, alongside the API."""

import importlib

from fastapi.testclient import TestClient


def make_client(monkeypatch, site_dir):
    monkeypatch.setenv("SITE_DIR", str(site_dir))
    import app.main

    importlib.reload(app.main)
    return TestClient(app.main.app)


def test_serves_built_site(monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<h1>Jekyll home</h1>")
    (tmp_path / "about").mkdir()
    (tmp_path / "about" / "index.html").write_text("<h1>About</h1>")
    (tmp_path / "404.html").write_text("<h1>Not found</h1>")
    client = make_client(monkeypatch, tmp_path)

    assert "Jekyll home" in client.get("/").text
    assert "About" in client.get("/about/").text
    r = client.get("/no-such-page")
    assert r.status_code == 404 and "Not found" in r.text
    # API routes still win over the static site
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/notes").status_code == 200


def test_fallback_when_site_not_built(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path / "missing")
    r = client.get("/")
    assert r.status_code == 200 and "hasn't been built" in r.text
