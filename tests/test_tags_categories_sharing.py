"""Tags, categories, editing, filtering, bulk actions and email sharing."""

from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def empty_store():
    main._notes.clear()
    main._categories.clear()
    yield


def note(text, **kw):
    r = client.post("/api/notes", json={"text": text, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def category(name):
    r = client.post("/api/categories", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def test_tags_are_cleaned():
    n = note("hi", tags=["#Work", " urgent ", "work", ""])
    assert n["tags"] == ["work", "urgent"]


def test_too_many_tags_rejected():
    r = client.post("/api/notes", json={"text": "hi", "tags": [f"t{i}" for i in range(11)]})
    assert r.status_code == 422


def test_category_crud_and_counts():
    work = category("Work")
    assert client.post("/api/categories", json={"name": "work"}).status_code == 409
    note("a", category_id=work["id"])
    assert client.get("/api/categories").json()[0]["note_count"] == 1
    assert client.post("/api/notes", json={"text": "b", "category_id": 999}).status_code == 422

    # Deleting a category keeps its notes, uncategorised.
    assert client.delete(f"/api/categories/{work['id']}").status_code == 204
    assert client.get("/api/notes").json()[0]["category_id"] is None


def test_filters():
    work = category("Work")
    note("Plan QBR", tags=["q4"], category_id=work["id"])
    note("Buy milk", tags=["home"])
    assert [n["text"] for n in client.get("/api/notes?tag=Q4").json()] == ["Plan QBR"]
    assert [n["text"] for n in client.get(f"/api/notes?category_id={work['id']}").json()] == [
        "Plan QBR"
    ]
    assert [n["text"] for n in client.get("/api/notes?q=milk").json()] == ["Buy milk"]
    assert client.get("/api/tags").json() == [
        {"tag": "home", "count": 1},
        {"tag": "q4", "count": 1},
    ]


def test_edit_note():
    work = category("Work")
    n = note("old", tags=["a"])
    r = client.patch(f"/api/notes/{n['id']}", json={"text": "new", "category_id": work["id"]})
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "new" and body["category_id"] == work["id"] and body["tags"] == ["a"]
    # Clearing the category
    assert (
        client.patch(f"/api/notes/{n['id']}", json={"category_id": None}).json()["category_id"]
        is None
    )
    assert client.patch("/api/notes/999", json={"text": "x"}).status_code == 404


def test_bulk_actions():
    work = category("Work")
    a, b, c = note("a", tags=["x"]), note("b"), note("c")
    ids = [a["id"], b["id"]]

    r = client.post("/api/notes/bulk", json={"ids": ids, "action": "add_tags", "tags": ["shared"]})
    assert r.json()["count"] == 2
    assert {n["text"] for n in client.get("/api/notes?tag=shared").json()} == {"a", "b"}

    client.post("/api/notes/bulk", json={"ids": ids, "action": "remove_tags", "tags": ["x"]})
    assert client.get(f"/api/notes/{a['id']}").json()["tags"] == ["shared"]

    client.post(
        "/api/notes/bulk", json={"ids": ids, "action": "set_category", "category_id": work["id"]}
    )
    assert len(client.get(f"/api/notes?category_id={work['id']}").json()) == 2

    r = client.post("/api/notes/bulk", json={"ids": ids, "action": "delete"})
    assert r.json()["count"] == 2
    assert [n["id"] for n in client.get("/api/notes").json()] == [c["id"]]


def test_bulk_validation():
    a = note("a")
    assert (
        client.post("/api/notes/bulk", json={"ids": [a["id"]], "action": "add_tags"}).status_code
        == 422
    )
    assert (
        client.post("/api/notes/bulk", json={"ids": [a["id"], 999], "action": "delete"}).status_code
        == 404
    )
    # A failed bulk delete changes nothing
    assert len(client.get("/api/notes").json()) == 1


def test_share_by_email():
    work = category("Work")
    a = note("Plan QBR", tags=["q4"], category_id=work["id"])
    b = note("Buy milk")
    r = client.post(
        "/api/notes/share", json={"ids": [a["id"], b["id"]], "to": "friend@example.com"}
    )
    share = r.json()
    assert share["subject"] == "2 notes from My Notes Application"
    assert (
        "Plan QBR" in share["body"] and "Category: Work" in share["body"] and "#q4" in share["body"]
    )
    assert share["mailto"].startswith("mailto:friend@example.com?subject=")
    assert "Buy milk" in unquote(share["mailto"])


def test_share_without_recipient():
    a = note("hello")
    share = client.post("/api/notes/share", json={"ids": [a["id"]]}).json()
    assert share["subject"] == "A note from My Notes Application"
    assert share["mailto"].startswith("mailto:?subject=")
