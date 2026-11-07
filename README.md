# My Notes Application (FastAPI + Jekyll + Docker + GitHub Actions)

A small FastAPI web app with a homepage, health check and a notes API, packaged as a Docker image and built by GitHub Actions.


## Features

- **Notes** with a live character limit (set by the `max-note-length` flag)
- **Tags:** add comma-separated tags to a note (`work, ideas`); click a tag to filter by it
- **Categories:** create and delete categories, and put each note in one; deleting a category keeps its notes
- **Search and filters:** by text, category and tag, in any combination
- **Edit** any note in place
- **Multi-select:** tick notes (or *Select all*) to add or remove tags, move them to a category, share them or delete them in one go
- **Share by email:** opens your email app with the selected notes filled in (subject, text, category and tags), or copies the text; no mail server needed

> Notes and categories are kept in memory, so they reset when the app restarts. On Render's free tier that happens after about 15 minutes without visitors.

## Endpoints

| Path | What it does |
|---|---|
| `/` | Homepage |
| `/health` | Health check (used by Docker and CI) |
| `/api/notes` | `GET` list (filters: `tag`, `category_id`, `q`) / `POST {"text": "...", "tags": [...], "category_id": 1}` create |
| `/api/notes/{id}` | `GET` one / `DELETE` one |
| `/api/notes/{id}` (`PATCH`) | Edit text, tags or category |
| `/api/notes/bulk` | Bulk `delete`, `add_tags`, `remove_tags` or `set_category` |
| `/api/notes/share` | Build an email (subject, body, `mailto:` link) for chosen notes |
| `/api/categories` | `GET` list / `POST {"name": "..."}` create; `DELETE /api/categories/{id}` |
| `/api/tags` | Tags in use, with counts |
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
| `site-banner` | string | `off` | Text shown in a banner at the top of every page. `off`, `none` or empty hides it; up to 300 characters. Visitors can dismiss a message, and a new message shows again. |
| `sidebar-ad` | string | `house` | Ad slot on the right of the page (below the content on phones). `off` hides it, `house` shows the built-in banner (text and link in `frontend/_config.yml` under `house_ad`), and an [Elfsight](https://elfsight.com/banner-widget/) widget ID shows that Elfsight banner. |

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

## Observability (Sentry + OpenTelemetry)

`app/observability.py` adds two free, optional integrations. Each is off until its settings are present, so local runs and tests send nothing. `/health` shows which are on.

| | What you get | Settings |
|---|---|---|
| **Sentry** | Every unhandled error with its stack trace and request, plus sampled performance traces | `SENTRY_DSN`; optional `SENTRY_TRACES_SAMPLE_RATE` (default `0.1`) |
| **OpenTelemetry** | A trace for every request (except `/health`), plus request count and latency metrics, sent over OTLP/HTTP, for example to Grafana Cloud | `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS`; optional `OTEL_SERVICE_NAME` |

**Set up**

1. **Sentry:** create a free account at [sentry.io](https://sentry.io), make a **FastAPI** project, and copy its DSN.
2. **Grafana Cloud:** create a free account at [grafana.com](https://grafana.com), then in your stack open **OpenTelemetry → Configure** and generate a token. Copy the endpoint and the `OTEL_EXPORTER_OTLP_HEADERS` value it shows.
3. Add the values in Render under **python-web-app → Environment** (or in `.env` locally). Render redeploys automatically.

To check Sentry, set `ENABLE_DEBUG_ENDPOINTS=true`, open `/api/debug/error` once, then set it back to `false`. The error appears in Sentry within a minute. Traces appear in Grafana under **Explore → Tempo**, filtered by service `python-web-app`.

## Jira

The repo is linked to Jira (`vicuong.atlassian.net`) through the GitHub for Jira app. Put a work item key, such as `KAN-1`, in a branch name, commit message or pull request title, and Jira shows that work on the item:

- **Development panel:** branches, commits and pull requests.
- **Builds:** the GitHub Actions runs for those commits, with pass or fail.
- **Deployments:** each release from `main` is recorded as a deployment to the `production` GitHub environment (the last job in `ci.yml`), and appears in Jira under **Production** (`.jira/config.yml` maps the names). A deployment covers every work item key in the commits since the last successful deployment.

## Editing the site without code (Pages CMS)

The site's wording, colours and built-in ad are kept in simple files that [Pages CMS](https://pagescms.org) shows as forms:

| In Pages CMS | File | What you can change |
|---|---|---|
| **Site settings** | `frontend/_data/settings.yml` | Site name, tagline, footer text, built-in sidebar banner |
| **Homepage text** | `frontend/_data/homepage.yml` | Headings, placeholders and hints on the Notes page |
| **Colours** | `frontend/_data/theme.yml` | Main and second colour, text, backgrounds, borders, corner roundness |
| **About page** | `frontend/about.md` | Title and Markdown content |

To edit: go to [app.pagescms.org](https://app.pagescms.org), sign in with GitHub, open this repo, change a field and click **Save**. Saving commits to `main`, so CI runs and Render redeploys the site in a few minutes. The forms are defined in `.pages.yml`; colour fields only accept 6-digit hex codes, so a typo can't break the styles.

Live switches (banner notice, sidebar ad, rollouts) stay in Cloudflare Flagship, since they change instantly without a deploy.

## Guardrails

Two layers check every pull request into `main`.

**Jira ticket check** (`.github/workflows/jira-check.yml`, runs now): fails unless the PR title, branch name or description contains a key from `KAN` or `SAM1` (e.g. `KAN-12: Add login` or branch `KAN-12-add-login`). With the `JIRA_EMAIL` and `JIRA_API_TOKEN` repository secrets set, it also asks Jira that the item exists and shows its summary and status. Without them it only checks the key's format. Change the projects with a `JIRA_PROJECTS` repository variable.

**gitStream guardrails** (`.cm/gitstream.cm`, once gitStream runs on this repo): each one requests changes until fixed, and each has a label to override it on purpose.

| Guardrail | Triggers when | Override label |
|---|---|---|
| Jira key | No `KAN-`/`SAM1-` key in title, branch or description (also comments a link to the item) | none |
| Missing tests | `app/` changed but nothing in `tests/` | `tests-not-needed` |
| Delivery files | Workflows, `.cm/`, `.jira/`, `Dockerfile`, `docker-compose.yml`, `render.yaml` or `.pages.yml` changed | `deploy-reviewed` |
| Large PR | Estimated review time over 30 minutes | `large-pr-ok` |
| Possible secret | An added line looks like a key, token, password or DSN | `not-a-secret` |

To make these block merging, require the **Jira ticket linked** and **gitStream** checks on `main` with a GitHub ruleset, letting Pages CMS bypass it so content edits still save directly.
