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
BUILD = "2026.08.20-114"
BUILD_NOTES = ("The consent page is rewritten around one question: what is wrong, and who fixes it. That list opens the page in plain sentences with an owner badge and a folded evidence trail on each row; the nine tables of evidence below it are closed by default and say how much is inside. California is checked against all three of its obligations rather than only the famous one - the sensitive-information link and the notice at collection were never tested - and the state results are one card per state with the law, the citation and the review date. The tooltip left the marker: as a CSS bubble inside a scrolling table wrapper it grew a scrollbar, reflowed the row and flickered several times a second. The vendor-macro flag is gone; [ORDER] and {orderid} are what those tags ship")

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
