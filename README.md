# Python Web App (FastAPI + Docker + GitHub Actions)

A small FastAPI web app with a homepage, health check and a notes API, packaged as a Docker image and built by GitHub Actions.

## Endpoints

| Path | What it does |
|---|---|
| `/` | Homepage |
| `/health` | Health check (used by Docker and CI) |
| `/api/notes` | `GET` list / `POST {"text": "..."}` create |
| `/api/notes/{id}` | `GET` one / `DELETE` one |
| `/docs` | Interactive API docs |

## Run with Docker

```bash
docker compose up --build
# open http://localhost:8000
```

Or pull the image GitHub Actions publishes:

```bash
docker run -p 8000:8000 ghcr.io/<owner>/<repo>:latest
```

## Run locally without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
pytest
```

## CI/CD (`.github/workflows/ci.yml`)

On every push and pull request to `main`:

1. **Lint & test** – `ruff` and `pytest` on Python 3.12.
2. **Build & smoke-test** – builds the Docker image, starts it, and checks `/health`.
3. **Push** (not on PRs) – publishes to GitHub Container Registry as `ghcr.io/<owner>/<repo>` with tags `latest`, `main`, `sha-<commit>`, and the version for `v*` tags.

No secrets to configure: the workflow uses the built-in `GITHUB_TOKEN`.

To release a version: `git tag v1.0.0 && git push --tags`.
