"""My Notes Application: a JSON notes API plus the Jekyll-built frontend in frontend/.

Notes have tags and an optional category, can be filtered, edited, changed in
bulk, and shared by email.

Behaviour is controlled by feature flags (see app/flags.py). Callers identify
themselves with optional X-User-Id and X-User-Plan headers, which Flagship uses
for targeting rules and percentage rollouts.
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from openfeature.evaluation_context import EvaluationContext
from pydantic import BaseModel, Field, field_validator

from app import __version__, flags, observability

# Sentry must start before the FastAPI app is created so it can hook into it.
SENTRY_ON = observability.init_sentry()
app = FastAPI(title="My Notes Application", version=__version__)
OTEL_ON = observability.init_otel(app)
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


MAX_TAGS = 10
TAG_MAX_LEN = 30


def clean_tags(tags: list[str]) -> list[str]:
    """Lower-case, trim, drop leading '#', remove blanks and duplicates (keeps order)."""
    out: list[str] = []
    for tag in tags:
        t = tag.strip().lstrip("#").strip().lower()[:TAG_MAX_LEN]
        if t and t not in out:
            out.append(t)
    if len(out) > MAX_TAGS:
        raise ValueError(f"A note can have at most {MAX_TAGS} tags")
    return out


class NoteIn(BaseModel):
    # Hard ceiling; the real limit comes from the max-note-length flag.
    text: str = Field(..., min_length=1, max_length=5000)
    tags: list[str] = Field(default_factory=list)
    category_id: int | None = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return clean_tags(v)


class NoteUpdate(BaseModel):
    """Partial update: only the fields you send are changed."""

    text: str | None = Field(None, min_length=1, max_length=5000)
    tags: list[str] | None = None
    category_id: int | None = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, v):
        return None if v is None else clean_tags(v)


class Note(NoteIn):
    id: int
    created_at: datetime
    updated_at: datetime


class CategoryIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Category name can't be blank")
        return v


class Category(CategoryIn):
    id: int
    note_count: int = 0


class BulkAction(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=500)
    action: Literal["delete", "add_tags", "remove_tags", "set_category"]
    tags: list[str] = Field(default_factory=list)
    category_id: int | None = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return clean_tags(v)


class ShareRequest(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=100)
    to: str | None = Field(None, max_length=320, description="Optional recipient email address")


_notes: dict[int, Note] = {}
_categories: dict[int, Category] = {}
_next_id = 1
_next_category_id = 1


def _check_category(category_id: int | None) -> None:
    if category_id is not None and category_id not in _categories:
        raise HTTPException(status_code=422, detail="Category not found")


def _check_length(text: str, ctx: EvaluationContext) -> None:
    limit = flags.number(flags.MAX_NOTE_LENGTH, ctx)
    if len(text) > limit:
        raise HTTPException(status_code=422, detail=f"Note is longer than {limit} characters")


def _get(note_id: int) -> Note:
    if note_id not in _notes:
        raise HTTPException(status_code=404, detail="Note not found")
    return _notes[note_id]


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "flags": FLAG_PROVIDER,
        "observability": {"sentry": SENTRY_ON, "opentelemetry": OTEL_ON},
    }


@app.get("/api/debug/error", include_in_schema=False)
def debug_error() -> None:
    """Deliberate crash, to check errors reach Sentry. Off unless enabled."""
    if os.getenv("ENABLE_DEBUG_ENDPOINTS") != "true":
        raise HTTPException(status_code=404, detail="Not Found")
    raise RuntimeError("Test error from python-web-app (this is expected)")


@app.get("/api/flags")
def current_flags(ctx: Ctx) -> dict:
    return {"provider": FLAG_PROVIDER, "user": ctx.targeting_key, "flags": flags.snapshot(ctx)}


@app.get("/api/notes", response_model=list[Note])
def list_notes(
    ctx: NotesCtx,
    tag: str | None = None,
    category_id: int | None = None,
    q: str | None = None,
) -> list[Note]:
    """List notes, newest first. Filter by tag, category and/or text search."""
    notes = list(_notes.values())
    if tag:
        wanted = tag.strip().lstrip("#").lower()
        notes = [n for n in notes if wanted in n.tags]
    if category_id is not None:
        notes = [n for n in notes if n.category_id == category_id]
    if q:
        notes = [n for n in notes if q.lower() in n.text.lower()]
    return sorted(notes, key=lambda n: n.created_at, reverse=True)


@app.post("/api/notes", response_model=Note, status_code=201)
def create_note(payload: NoteIn, ctx: NotesCtx) -> Note:
    global _next_id
    _check_length(payload.text, ctx)
    _check_category(payload.category_id)
    now = datetime.now(UTC)
    note = Note(id=_next_id, created_at=now, updated_at=now, **payload.model_dump())
    _notes[note.id] = note
    _next_id += 1
    return note


@app.post("/api/notes/bulk")
def bulk_update(payload: BulkAction, ctx: NotesCtx) -> dict:
    """Apply one action to several notes at once (used by multi-select)."""
    notes = [_get(i) for i in dict.fromkeys(payload.ids)]
    if payload.action == "delete":
        for n in notes:
            del _notes[n.id]
        return {"action": "delete", "count": len(notes)}

    if payload.action in ("add_tags", "remove_tags") and not payload.tags:
        raise HTTPException(status_code=422, detail="Give at least one tag")
    if payload.action == "set_category":
        _check_category(payload.category_id)

    now = datetime.now(UTC)
    for n in notes:
        if payload.action == "add_tags":
            n.tags = clean_tags(n.tags + payload.tags)
        elif payload.action == "remove_tags":
            n.tags = [t for t in n.tags if t not in payload.tags]
        else:
            n.category_id = payload.category_id
        n.updated_at = now
    return {"action": payload.action, "count": len(notes), "notes": notes}


@app.post("/api/notes/share")
def share_notes(payload: ShareRequest, ctx: NotesCtx) -> dict:
    """Build an email (subject, body and a mailto: link) for the chosen notes.

    The email is sent from your own mail app, so no mail server is needed.
    """
    notes = [_get(i) for i in dict.fromkeys(payload.ids)]
    subject = "A note from My Notes Application" if len(notes) == 1 else f"{len(notes)} notes from My Notes Application"
    parts = []
    for n in notes:
        meta = []
        if n.category_id in _categories:
            meta.append(f"Category: {_categories[n.category_id].name}")
        if n.tags:
            meta.append("Tags: " + ", ".join(f"#{t}" for t in n.tags))
        parts.append(n.text + ("\n" + " | ".join(meta) if meta else ""))
    body = "\n\n---\n\n".join(parts)
    to = quote(payload.to.strip(), safe="@") if payload.to else ""
    mailto = f"mailto:{to}?subject={quote(subject)}&body={quote(body)}"
    return {"subject": subject, "body": body, "mailto": mailto}


@app.get("/api/notes/{note_id}", response_model=Note)
def get_note(note_id: int, ctx: NotesCtx) -> Note:
    return _get(note_id)


@app.patch("/api/notes/{note_id}", response_model=Note)
def update_note(note_id: int, payload: NoteUpdate, ctx: NotesCtx) -> Note:
    note = _get(note_id)
    changes = payload.model_dump(exclude_unset=True)
    if "text" in changes:
        if changes["text"] is None:
            raise HTTPException(status_code=422, detail="Text can't be empty")
        _check_length(changes["text"], ctx)
    if "category_id" in changes:
        _check_category(changes["category_id"])
    if "tags" in changes and changes["tags"] is None:
        changes["tags"] = []
    for field, value in changes.items():
        setattr(note, field, value)
    note.updated_at = datetime.now(UTC)
    return note


@app.delete("/api/notes/{note_id}", status_code=204)
def delete_note(note_id: int, ctx: NotesCtx) -> None:
    _notes.pop(_get(note_id).id)


@app.get("/api/tags")
def list_tags(ctx: NotesCtx) -> list[dict]:
    """Every tag in use, with how many notes have it (most used first)."""
    counts: dict[str, int] = {}
    for n in _notes.values():
        for t in n.tags:
            counts[t] = counts.get(t, 0) + 1
    return [{"tag": t, "count": c} for t, c in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]


@app.get("/api/categories", response_model=list[Category])
def list_categories(ctx: NotesCtx) -> list[Category]:
    for c in _categories.values():
        c.note_count = sum(1 for n in _notes.values() if n.category_id == c.id)
    return sorted(_categories.values(), key=lambda c: c.name.lower())


@app.post("/api/categories", response_model=Category, status_code=201)
def create_category(payload: CategoryIn, ctx: NotesCtx) -> Category:
    global _next_category_id
    if any(c.name.lower() == payload.name.lower() for c in _categories.values()):
        raise HTTPException(status_code=409, detail="A category with that name already exists")
    cat = Category(id=_next_category_id, name=payload.name)
    _categories[cat.id] = cat
    _next_category_id += 1
    return cat


@app.delete("/api/categories/{category_id}", status_code=204)
def delete_category(category_id: int, ctx: NotesCtx) -> None:
    """Delete a category. Its notes are kept and become uncategorised."""
    if _categories.pop(category_id, None) is None:
        raise HTTPException(status_code=404, detail="Category not found")
    for n in _notes.values():
        if n.category_id == category_id:
            n.category_id = None


# ---- Frontend: static pages generated by Jekyll (frontend/ -> frontend/_site) ----


class NoCacheStaticFiles(StaticFiles):
    """Static files that browsers must re-check on every load.

    "no-cache" still lets browsers keep a copy, but they ask the server first
    (a cheap 304 Not Modified via the ETag), so a new deploy is picked up
    immediately instead of a stale page or script being served from cache.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response

SITE_DIR = Path(os.getenv("SITE_DIR", Path(__file__).resolve().parent.parent / "frontend" / "_site"))

if SITE_DIR.is_dir():
    # Mounted last so /api, /health and /docs take priority. html=True serves
    # index.html for folders and Jekyll's 404.html for unknown paths.
    app.mount("/", NoCacheStaticFiles(directory=SITE_DIR, html=True), name="site")
else:

    @app.get("/", response_class=HTMLResponse)
    def site_not_built() -> str:
        return (
            "<h1>My Notes Application</h1><p>The frontend hasn't been built. Run "
            "<code>cd frontend && bundle exec jekyll build</code>, or use Docker.</p>"
            '<p>The API is running: see <a href="/docs">/docs</a>.</p>'
        )
