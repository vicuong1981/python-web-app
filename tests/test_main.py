from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_home():
    r = client.get("/")
    assert r.status_code == 200
    assert "Python Web App" in r.text


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_notes_crud():
    r = client.post("/api/notes", json={"text": "hello"})
    assert r.status_code == 201
    note_id = r.json()["id"]

    assert client.get(f"/api/notes/{note_id}").json()["text"] == "hello"
    assert any(n["id"] == note_id for n in client.get("/api/notes").json())

    assert client.delete(f"/api/notes/{note_id}").status_code == 204
    assert client.get(f"/api/notes/{note_id}").status_code == 404


def test_note_validation():
    assert client.post("/api/notes", json={"text": ""}).status_code == 422
