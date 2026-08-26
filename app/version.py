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
BUILD = "2026.08.20-113"
BUILD_NOTES = ("Run again now replays the whole run, not most of it: the two job checkboxes are restored so a consent-only re-run stops arriving with Full audit ticked, and the hand-picked Search Console, GA4 and Tag Manager properties are actually re-applied - they had been stashed and read by nothing. A Tag Manager account we could not read is reported as ours to re-check rather than as the client withholding access, a container held under the client's name is named as a near miss, and every access miss says WHICH Vici login the client has to add. The progress page quotes this run's timing instead of a 150-page crawl's")

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
