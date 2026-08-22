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

# Roboto is the report typeface; without it engine/fonts.py falls back to
# Helvetica and the PDF silently reverts to its 1998 look — no error, just a
# worse document, which is the hardest kind of regression to notice.
#
# DejaVu supplies the symbol glyphs the PDF's definition bubbles use. The
# Playwright base image does not ship it, so the first production build
# rendered every bubble with no icon — the renderer correctly drops a glyph the
# font lacks rather than printing a black box, so the failure was silent.
# The definition badge itself is drawn as vector and never depended on this.
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-roboto \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt .

# Split into two layers so a failure in the (larger, slower) production extras
# doesn't force a rebuild of the core deps, and so the core app can build even
# if an optional driver is unavailable.
RUN python3 -m pip install --upgrade pip \
 && pip install -r requirements.txt

COPY . .

# Import the app AT BUILD TIME. A missing dependency is otherwise invisible
# until the container starts and uvicorn dies on ModuleNotFoundError — which
# looks like a deploy failure rather than a one-line requirements omission,
# and costs a full build cycle to diagnose. This turns it into a build error
# with the same traceback, minutes earlier. It is safe because importing
# app.api has no side effects: no DB connection, no queue, no network.
RUN python3 -c "import app.api, app.worker; print('import check passed')"

# AND CHECK THE BROWSER, which the line above does not.
#
# `import app.worker` succeeds with or without Playwright, because the consent
# scanner imports it lazily and falls back to a basic HTML scan when it cannot.
# That fallback is the right behaviour at runtime and it made a missing module
# invisible at build time: the image built clean, the worker started clean, and
# every consent scan quietly answered four of nine questions instead of nine.
#
# Assert it here, where it costs one line and fails the build instead of
# degrading a client report.
RUN python3 -c "import playwright; from playwright.sync_api import sync_playwright; print('playwright import check passed')"

# Non-root. The base image provides the `pwuser` account.
RUN mkdir -p /srv/data && chown -R pwuser:pwuser /srv
USER pwuser

EXPOSE 8000

# Render provides $PORT. Defaulting to 8000 keeps local `docker run` working.
ENV PORT=8000

# Overridden per service — the API and the worker share this image but run
# different commands. See render.yaml / docker-compose.yml.
CMD ["sh", "-c", "uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
