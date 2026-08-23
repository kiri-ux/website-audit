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


def manifest(files) -> dict:
    """path -> sha256 of the bytes we are about to ship."""
    import hashlib
    out = {}
    for rel in files:
        h = hashlib.sha256()
        with open(os.path.join(ROOT, rel), "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        out[rel] = h.hexdigest()
    return out


def _newest_manifest(out_dir: str):
    """The most recent manifest we wrote beside a delivered zip."""
    import glob
    import json
    best, best_t = None, -1.0
    for f in glob.glob(os.path.join(out_dir, "vici-audit-*.manifest.json")):
        t = os.path.getmtime(f)
        if t > best_t:
            best, best_t = f, t
    if not best:
        return None, None
    try:
        with open(best) as fh:
            return json.load(fh), best
    except Exception:  # noqa: BLE001
        return None, None


def build() -> str:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=DEFAULT_SINCE,
                    help=f"baseline timestamp (default {DEFAULT_SINCE})")
    ap.add_argument("--list", action="store_true",
                    help="print the file list and exit")
    ap.add_argument("--docs", action="store_true",
                    help="include docs/*.png screenshots")
    ap.add_argument("--out", default="", help="output zip path")
    # GITHUB'S WEB UPLOADER TAKES 100 FILES AT A TIME.
    #
    # The cumulative-since-baseline zip crossed that, which makes it
    # undeliverable to someone who uploads through github.com rather than a
    # clone. So the default is now incremental: only files whose CONTENT
    # differs from the last zip we shipped, proved by hash rather than by
    # mtime, which over-includes every file a test run happened to touch.
    ap.add_argument("--full", action="store_true",
                    help="ignore the last manifest and ship everything since "
                         "the baseline")
    a = ap.parse_args()

    since = _dt.datetime.fromisoformat(a.since).timestamp()
    files = tracked(since, a.docs)

    if a.list:
        print("\n".join(files))
        print(f"\n{len(files)} files newer than {a.since}", file=sys.stderr)
        return ""

    sys.path.insert(0, ROOT)
    import json
    from app.version import BUILD
    out = a.out or os.path.join(os.path.dirname(ROOT),
                                f"vici-audit-{BUILD}.zip")
    out_dir = os.path.dirname(os.path.abspath(out))

    now = manifest(files)
    prev, prev_path = (None, None) if a.full else _newest_manifest(out_dir)
    ship = files
    dropped = 0
    if prev:
        ship = [f for f in files if prev.get(f) != now[f]]
        dropped = len(files) - len(ship)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in ship:
            z.write(os.path.join(ROOT, rel), rel)
    # The manifest records EVERY tracked file, not only the ones shipped, so
    # the next delta is measured against the full known state rather than
    # against the last slice of it.
    with open(out[:-4] + ".manifest.json", "w") as fh:
        json.dump(now, fh, indent=0, sort_keys=True)

    size = os.path.getsize(out)
    kind = "full" if not prev else f"incremental vs {os.path.basename(prev_path)}"
    print(f"{out}\n{len(ship)} files · {size/1024:.0f} KB · build {BUILD} "
          f"· {kind}")
    if dropped:
        print(f"  {dropped} tracked file(s) unchanged and not included")
    if len(ship) > 100:
        print(f"  WARNING: {len(ship)} files exceeds GitHub's 100-file web "
              f"upload limit — split it or use --full deliberately")
    return out


if __name__ == "__main__":
    build()
