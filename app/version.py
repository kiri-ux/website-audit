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
BUILD = "2026.08.20-116"
BUILD_NOTES = ("The full audit now renders INSIDE the app frame instead of being a separate document - same rail, topbar, breadcrumb and tabs as every other page, and only one copy of the tab stylesheet, which is how the two had drifted apart. The engine still produces a standalone document for the artifact and for mailing; the app unwraps it. Client PDF and Snapshot carry a download arrow so it is obvious they are files rather than pages, and the work order is three cards to a row with the owner badge above the title")

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
