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

## Feature flags (Cloudflare Flagship)

Flags are evaluated by [Cloudflare Flagship](https://developers.cloudflare.com/flagship/) through its official Python SDK (`cloudflare-flagship`, built on OpenFeature). Definitions live in `app/flags.py`.

| Flag | Type | Default | What it does |
|---|---|---|---|
| `new-homepage` | boolean | off | Shows the redesigned homepage. Created with a 25% rollout, sticky per user. |
| `notes-api` | boolean | on | Kill switch: when off, the notes API returns `503`. |
| `max-note-length` | number | 500 | Max characters per note; 2000 for users on the `pro` plan. |

Callers can identify themselves with `X-User-Id` and `X-User-Plan` headers, which Flagship uses for targeting and rollouts. `GET /api/flags` shows the values the current caller gets.

**Set up**

The flags already exist in Cloudflare (Flagship app `python-web-app`), and the Docker image has the app ID and account ID built in. The only thing to supply is the API token:

1. In Cloudflare, create an account API token with the **Flagship Evaluate** permission.
2. **Running the app:** with Docker Compose, copy `.env.example` to `.env` and set `FLAGSHIP_API_TOKEN`; with `docker run`, pass `-e FLAGSHIP_API_TOKEN=...`.
3. **CI:** add the same token as a repository secret named `FLAGSHIP_API_TOKEN`. The pipeline then checks that the built container gets live values from Flagship.

To recreate the flags in another Cloudflare account, use `./scripts/create_flags.sh` and override `FLAGSHIP_APP_ID` and `CLOUDFLARE_ACCOUNT_ID`.

Without the token, or if Flagship can't be reached, every flag returns its default and the app keeps working. Change rollouts and toggles in the Cloudflare dashboard, with no redeploy needed.

## Frontend (Jekyll)

The web pages are a [Jekyll](https://jekyllrb.com/) site in `frontend/`. Jekyll turns the layouts, includes, Markdown and Sass there into static files, which FastAPI serves at `/`; the JSON API stays under `/api`.

| Path | What it is |
|---|---|
| `frontend/_config.yml` | Site title, description, version and navigation |
| `frontend/_layouts/default.html` | Page template shared by every page |
| `frontend/_includes/` | Header and footer |
| `frontend/index.html` | Notes page: add, list and delete notes |
| `frontend/about.md` | About page, written in Markdown |
| `frontend/_sass/`, `frontend/assets/css/main.scss` | Styles |
| `frontend/assets/js/app.js` | Calls the API and applies the feature flags (new homepage, note length, notes kill switch) |

The Docker build runs Jekyll automatically, so `docker compose up --build` gives you the full app. To work on the pages locally:

```bash
cd frontend && bundle install && bundle exec jekyll build --watch   # rebuilds on save
uvicorn app.main:app --reload                                        # in another terminal
```

FastAPI serves the built site from `frontend/_site` (override with `SITE_DIR`).

## Public deployment (Render)

`render.yaml` deploys the app to [Render](https://render.com)'s free tier straight from this repo: in Render, choose **New → Blueprint**, pick this repo, and enter your `FLAGSHIP_API_TOKEN` when asked. Render rebuilds and redeploys on every push to `main`. Free services sleep after about 15 minutes without visitors, so the first request after that takes up to a minute.
