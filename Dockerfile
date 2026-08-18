# Playwright's own image ships Chromium and every system library it needs.
# Installing Chromium onto a plain python:slim base is possible but brittle —
# it breaks on every upstream libc/font change. Start from the image that is
# tested against the browser version you're pinning.
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root. The base image provides the `pwuser` account.
RUN mkdir -p /srv/data && chown -R pwuser:pwuser /srv
USER pwuser

EXPOSE 8000

# Overridden per service — the API and the worker share this image but run
# different commands. See render.yaml / docker-compose.yml.
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
