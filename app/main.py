"""A small FastAPI web app: a homepage, a health check and a tiny notes API.

Behaviour is controlled by feature flags (see app/flags.py). Callers identify
themselves with optional X-User-Id and X-User-Plan headers, which Flagship uses
for targeting rules and percentage rollouts.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from openfeature.evaluation_context import EvaluationContext
from pydantic import BaseModel, Field

from app import __version__, flags

app = FastAPI(title="Python Web App", version=__version__)
FLAG_PROVIDER = flags.init_flags()


def user_context(
    x_user_id: Annotated[str | None, Header()] = None,
    x_user_plan: Annotated[str | None, Header()] = None,
) -> EvaluationContext:
    return flags.context_for(x_user_id, x_user_plan)


Ctx = Annotated[EvaluationContext, Depends(user_context)]


def notes_enabled(ctx: Ctx) -> EvaluationContext:
    if not flags.is_on(flags.NOTES_API, ctx):
        raise HTTPException(status_code=503, detail="Notes are temporarily unavailable")
    return ctx


NotesCtx = Annotated[EvaluationContext, Depends(notes_enabled)]


class NoteIn(BaseModel):
    # Hard ceiling; the real limit comes from the max-note-length flag.
    text: str = Field(..., min_length=1, max_length=5000)


class Note(NoteIn):
    id: int
    created_at: datetime


_notes: dict[int, Note] = {}
_next_id = 1

_STYLE = """
 body{font-family:system-ui,sans-serif;max-width:640px;margin:3rem auto;padding:0 1rem;color:#1f2933}
 code{background:#f1f5f9;padding:2px 6px;border-radius:4px}
 .hero{background:linear-gradient(135deg,#4f46e5,#06b6d4);color:#fff;padding:2rem;border-radius:12px}
 .hero a{color:#fff}
"""

_LINKS = """
 <ul>
  <li><a href="/health">/health</a> – health check</li>
  <li><a href="/api/notes">/api/notes</a> – notes API</li>
  <li><a href="/api/flags">/api/flags</a> – your current feature flags</li>
  <li><a href="/docs">/docs</a> – interactive API docs</li>
 </ul>"""


@app.get("/", response_class=HTMLResponse)
def home(ctx: Ctx) -> str:
    if flags.is_on(flags.NEW_HOMEPAGE, ctx):
        body = f"""<div class="hero">
 <h1>Python Web App ✨</h1>
 <p>You're seeing the new homepage, switched on by a Cloudflare Flagship feature flag.</p>
 <p>Version <code>{__version__}</code></p>
</div>{_LINKS}"""
    else:
        body = f"""<h1>Python Web App</h1>
 <p>Running in Docker, built and shipped by GitHub Actions. Version <code>{__version__}</code>.</p>
{_LINKS}"""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Python Web App</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{_STYLE}</style></head>
<body>{body}</body></html>"""


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "flags": FLAG_PROVIDER}


@app.get("/api/flags")
def current_flags(ctx: Ctx) -> dict:
    return {"provider": FLAG_PROVIDER, "user": ctx.targeting_key, "flags": flags.snapshot(ctx)}


@app.get("/api/notes", response_model=list[Note])
def list_notes(ctx: NotesCtx) -> list[Note]:
    return list(_notes.values())


@app.post("/api/notes", response_model=Note, status_code=201)
def create_note(payload: NoteIn, ctx: NotesCtx) -> Note:
    global _next_id
    limit = flags.number(flags.MAX_NOTE_LENGTH, ctx)
    if len(payload.text) > limit:
        raise HTTPException(status_code=422, detail=f"Note is longer than {limit} characters")
    note = Note(id=_next_id, text=payload.text, created_at=datetime.now(UTC))
    _notes[note.id] = note
    _next_id += 1
    return note


@app.get("/api/notes/{note_id}", response_model=Note)
def get_note(note_id: int, ctx: NotesCtx) -> Note:
    if note_id not in _notes:
        raise HTTPException(status_code=404, detail="Note not found")
    return _notes[note_id]


@app.delete("/api/notes/{note_id}", status_code=204)
def delete_note(note_id: int, ctx: NotesCtx) -> None:
    if _notes.pop(note_id, None) is None:
        raise HTTPException(status_code=404, detail="Note not found")
