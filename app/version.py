"""
Build identity.

Surfaced in the UI header, the report footer, and /healthz so you can confirm
which code is actually live before trusting a run. Deploying and re-running
against a stale container is an easy mistake to make and a hard one to spot —
the report looks plausible either way.

BUMP `BUILD` whenever you ship a change whose effect you need to verify visually.
"""
from __future__ import annotations
import os

# ---- bump this on every deploy you need to confirm -------------------------
BUILD = "2026.08.20-119"
BUILD_NOTES = ("Three from one bad afternoon. A blocked CONSENT run was being offered the crawl capture, whose endpoint scores 322 checkpoints - which is why a consent scan came back as a full audit nobody selected with the consent rows still empty; it now gets the consent capture, and the crawl endpoint refuses a consent run by name instead of answering a different question. A geographic target of US or nationwide expanded to nothing, so the client most exposed to state privacy law got the emptiest legal section - it now means every state in the map. And the install steps stop naming a version that went stale three releases ago")

# Not printed on the dashboard any more — it was three lines of chrome above
# the first number anyone came to read. It stays here, and in /healthz, where
# the audience is whoever is checking what actually shipped.
# ---------------------------------------------------------------------------


def commit() -> str:
    """Render injects RENDER_GIT_COMMIT automatically."""
    c = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or ""
    return c[:7]


def service() -> str:
    return os.getenv("RENDER_SERVICE_NAME", "local")


def label() -> str:
    """Short human-readable build string, e.g. 'build 2026.08.18-4 · a1b2c3d'."""
    parts = [f"build {BUILD}"]
    if commit():
        parts.append(commit())
    return " · ".join(parts)


def info() -> dict:
    return {"build": BUILD, "notes": BUILD_NOTES, "commit": commit(),
            "service": service()}
