"""A small FastAPI web app: a homepage, a health check and a tiny notes API."""

from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app import __version__

app = FastAPI(title="Python Web App", version=__version__)


class NoteIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)


class Note(NoteIn):
    id: int
    created_at: datetime


_notes: dict[int, Note] = {}
_next_id = 1


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Python Web App</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body{{font-family:system-ui,sans-serif;max-width:640px;margin:3rem auto;padding:0 1rem;color:#1f2933}}
 code{{background:#f1f5f9;padding:2px 6px;border-radius:4px}}
</style></head>
<body>
 <h1>Python Web App</h1>
 <p>Running in Docker, built and shipped by GitHub Actions. Version <code>{__version__}</code>.</p>
 <ul>
  <li><a href="/health">/health</a> – health check</li>
  <li><a href="/api/notes">/api/notes</a> – notes API</li>
  <li><a href="/docs">/docs</a> – interactive API docs</li>
 </ul>
</body></html>"""


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/api/notes", response_model=list[Note])
def list_notes() -> list[Note]:
    return list(_notes.values())


@app.post("/api/notes", response_model=Note, status_code=201)
def create_note(payload: NoteIn) -> Note:
    global _next_id
    note = Note(id=_next_id, text=payload.text, created_at=datetime.now(UTC))
    _notes[note.id] = note
    _next_id += 1
    return note


@app.get("/api/notes/{note_id}", response_model=Note)
def get_note(note_id: int) -> Note:
    if note_id not in _notes:
        raise HTTPException(status_code=404, detail="Note not found")
    return _notes[note_id]


@app.delete("/api/notes/{note_id}", status_code=204)
def delete_note(note_id: int) -> None:
    if _notes.pop(note_id, None) is None:
        raise HTTPException(status_code=404, detail="Note not found")
