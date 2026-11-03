# ---- frontend stage: build the static site with Jekyll ----
FROM ruby:3.3-slim AS site
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /site
COPY frontend/Gemfile ./
RUN bundle install
COPY frontend/ ./
RUN JEKYLL_ENV=production bundle exec jekyll build --destination /site/_site

# ---- build stage: install dependencies into a virtualenv ----
FROM python:3.12-slim AS builder
WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- runtime stage: small image, non-root user ----
# FLAGSHIP_APP_ID / CLOUDFLARE_ACCOUNT_ID identify this project's Cloudflare
# Flagship app (not secret). Live flags switch on when FLAGSHIP_API_TOKEN is
# also passed in at runtime; without it the flag defaults are used.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000 \
    FLAGSHIP_APP_ID=7963d44f-e68d-49ed-b2cf-326e600a0c81 \
    CLOUDFLARE_ACCOUNT_ID=02c1d544208e0932299ea9f8a85545d3
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY --from=site /site/_site ./frontend/_site
RUN useradd --create-home appuser
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health')" || exit 1
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
