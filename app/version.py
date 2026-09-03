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
BUILD = "2026.08.20-120"
BUILD_NOTES = ("Fixes a break I shipped in 119: the national market was given the state code US and then looked up in a table of real states, which threw - and because every pill is built inside one map() the exception took the whole geo box down. No pills for any market, nothing in the console. National is its own branch now, tagged ALL, and every state-table read is guarded so an unknown code can cost its own pill a label and nothing else. Guarded by a test that drives the real form in a browser, because this failure is invisible from Python: the page rendered perfectly and the script was dead")

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
