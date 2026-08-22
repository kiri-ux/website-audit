"""
Build the delta zip from the filesystem, not from a list someone maintains.

WHY THIS EXISTS
---------------
The delta zips were packed from a hand-written file list. `engine/aivis/
providers.py` was never on it. So the AI Overview provider learned to speak
DataForSEO in build ‑38, was tested, was written up in three changelogs — and
the file never went in a zip, never reached the repo, and never ran on the
worker. Every downstream fix was made against code the deployed worker did not
have, and the symptom ("AI Overviews measured nothing") looked like a
credential problem for thirteen builds.

A hand-maintained manifest is a silent-failure machine: a file you forget is a
file that reports no error. Every other quiet truncation in this codebase got a
loud replacement; this one gets a generated list.

    python3 pack.py                  -> vici-audit-<BUILD>.zip
    python3 pack.py --since 2026-08-18T00:00
    python3 pack.py --list           -> print what would go in, pack nothing

WHAT IS IN A DELTA
------------------
Every tracked source file whose mtime is newer than the baseline, where
"tracked" means the extensions this project actually deploys. Generated output,
databases, caches and the fixture corpus are excluded by path — they are large,
they are rebuilt, and shipping them over a running deploy is how you overwrite
someone's data.

Over-including is cheap: an unchanged file that lands in the zip is a no-op
commit. Under-including cost thirteen builds.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))

# The baseline every cumulative delta has been measured from.
DEFAULT_SINCE = "2026-08-18T00:00"

KEEP_EXT = {".py", ".js", ".json", ".md", ".csv", ".html", ".txt", ".yaml",
            ".yml", ".svg", ".png", ".ico", ".cfg", ".toml", ".example"}
KEEP_NAMES = {"Dockerfile", ".dockerignore"}

SKIP_DIRS = {"data", "out", "fixture", "__pycache__", ".git", ".pytest_cache",
             "node_modules", ".venv", "venv", "artifacts"}

# Docs images are 700KB of screenshots that no deploy reads. They are still
# repo content, so `--docs` puts them back when a doc change needs them.
DOC_IMAGES = "docs/"


def tracked(since: float, docs: bool = False) -> list[str]:
    out = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            path = os.path.join(base, fn)
            rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
            if rel.startswith(".") or "/." in rel:
                continue
            ext = os.path.splitext(fn)[1]
            if ext not in KEEP_EXT and fn not in KEEP_NAMES:
                continue
            if rel.startswith(DOC_IMAGES) and ext == ".png" and not docs:
                continue
            try:
                if os.path.getmtime(path) < since:
                    continue
            except OSError:
                continue
            out.append(rel)
    return sorted(out)


def build() -> str:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=DEFAULT_SINCE,
                    help=f"baseline timestamp (default {DEFAULT_SINCE})")
    ap.add_argument("--list", action="store_true",
                    help="print the file list and exit")
    ap.add_argument("--docs", action="store_true",
                    help="include docs/*.png screenshots")
    ap.add_argument("--out", default="", help="output zip path")
    a = ap.parse_args()

    since = _dt.datetime.fromisoformat(a.since).timestamp()
    files = tracked(since, a.docs)

    if a.list:
        print("\n".join(files))
        print(f"\n{len(files)} files newer than {a.since}", file=sys.stderr)
        return ""

    sys.path.insert(0, ROOT)
    from app.version import BUILD
    out = a.out or os.path.join(os.path.dirname(ROOT),
                                f"vici-audit-{BUILD}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            z.write(os.path.join(ROOT, rel), rel)
    size = os.path.getsize(out)
    print(f"{out}\n{len(files)} files · {size/1024:.0f} KB · build {BUILD}")
    return out


if __name__ == "__main__":
    build()
