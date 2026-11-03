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

## LinearB integration

This repo is wired up for [LinearB](https://linearb.io):

- **gitStream** (`.cm/gitstream.cm` + `.github/workflows/gitstream.yml`) – on each PR: LinearB AI code review, an AI-written PR description, an estimated-review-time label, and `missing-tests` / `ci-cd-change` / `docs-only` labels. Requires the [gitStream GitHub app](https://github.com/marketplace/gitstream-by-linearb) installed on this repo.
- **Deployment reporting** (`linearb-deployment` job in `ci.yml`) – every image published from `main` is reported to LinearB's Deployment API so deployment frequency, lead time and cycle-time deploy stage are measured. Requires a repository secret `LINEARB_API_TOKEN`; without it the job skips with a warning.
- **Git metrics** (PRs, cycle time, coding/pickup/review time) come from connecting this repo in LinearB's GitHub integration – no files needed.

> Tip: run `pytest -q` before opening a pull request.
> Tip: `docker compose up --build` runs the app locally in Docker.
