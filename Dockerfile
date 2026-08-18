# Playwright's own image ships Chromium and every system library it needs.
# Installing Chromium onto a plain python:slim base is possible but brittle —
# it breaks on every upstream libc/font change. Start from the image that is
# tested against the browser version you're pinning.
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # PyPI's CDN returns intermittent 502s. Without these, a single transient
    # blip fails the entire build — which is exactly what happened on the first
    # deploy attempt. Retry with backoff instead.
    PIP_RETRIES=10 \
    PIP_TIMEOUT=60 \
    PIP_DEFAULT_TIMEOUT=60 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /srv

COPY requirements.txt .

# Split into two layers so a failure in the (larger, slower) production extras
# doesn't force a rebuild of the core deps, and so the core app can build even
# if an optional driver is unavailable.
RUN python3 -m pip install --upgrade pip \
 && pip install -r requirements.txt

COPY . .

# Non-root. The base image provides the `pwuser` account.
RUN mkdir -p /srv/data && chown -R pwuser:pwuser /srv
USER pwuser

EXPOSE 8000

# Render provides $PORT. Defaulting to 8000 keeps local `docker run` working.
ENV PORT=8000

# Overridden per service — the API and the worker share this image but run
# different commands. See render.yaml / docker-compose.yml.
CMD ["sh", "-c", "uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
