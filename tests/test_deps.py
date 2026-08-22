"""
Dependency parity test.

The failure this exists to prevent: code imports a library that happens to be
installed on the developer's machine, is never added to requirements.txt, and
the container dies at startup with ModuleNotFoundError. It looks like a broken
deploy. It is a one-line omission, and it has now happened once (reportlab).

Nothing here needs network or a build. It walks every runtime module, collects
the third-party imports, and asserts each one is declared — so the check runs
in the same second as the rest of the suite.

Run:  python3 -m tests.test_deps
"""
from __future__ import annotations
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Import name -> distribution name, where they differ.
IMPORT_TO_DIST = {
    "bs4": "beautifulsoup4",
    "psycopg2": "psycopg2-binary",
    "yaml": "pyyaml",
    "PIL": "pillow",
    "dateutil": "python-dateutil",
}

# Deliberately undeclared, with the reason. Anything in here must be justified
# in requirements.txt too, so the next reader finds the explanation.
EXEMPT = {
    "playwright": "ships with the Playwright base image; see requirements.txt",
}

RUNTIME_DIRS = ("app", "engine")     # tests are not installed in the image
FAILURES = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)
    return cond


def _declared() -> set:
    names = set()
    with open(os.path.join(ROOT, "requirements.txt")) as f:
        for line in f:
            line = line.split("#")[0].strip()
            if not line:
                continue
            for sep in ("[", ">", "<", "=", "!", "~", ";", " "):
                line = line.split(sep)[0]
            if line:
                names.add(line.strip().lower())
    return names


def _imports(dirs) -> tuple:
    """
    (all, eager) — eager being imports at MODULE TOP LEVEL.

    The distinction is the whole point. A top-level import runs the moment the
    container starts, so the package must exist or nothing boots. An import
    inside a function only runs when that code path is taken, which is exactly
    how the optional production backends (boto3, psycopg2, redis) are wired:
    declared in requirements, installed in the image, but never touched in
    local dev where they are not installed at all.
    """
    std = set(sys.stdlib_module_names)
    local = {"app", "engine", "tests"}
    found, eager = {}, {}

    def note(store, mod, path):
        top = mod.split(".")[0]
        if top and top not in std and top not in local:
            store.setdefault(top, set()).add(os.path.relpath(path, ROOT))

    for base in dirs:
        for root, _, files in os.walk(os.path.join(ROOT, base)):
            if "__pycache__" in root:
                continue
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(root, fn)
                tree = ast.parse(open(path).read())
                for node in ast.walk(tree):
                    mods = []
                    if isinstance(node, ast.Import):
                        mods = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0:
                        mods = [node.module] if node.module else []
                    for m in mods:
                        note(found, m, path)
                for node in tree.body:          # top level only
                    mods = []
                    if isinstance(node, ast.Import):
                        mods = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0:
                        mods = [node.module] if node.module else []
                    for m in mods:
                        note(eager, m, path)
    return found, eager


def main():
    declared = _declared()
    print(f"\nrequirements.txt declares {len(declared)}: {', '.join(sorted(declared))}")

    print("\nEVERY RUNTIME IMPORT IS DECLARED")
    imports, eager = _imports(RUNTIME_DIRS)
    missing = []
    for mod, files in sorted(imports.items()):
        if mod in EXEMPT:
            continue
        dist = IMPORT_TO_DIST.get(mod, mod).lower()
        if dist not in declared:
            missing.append(f"{mod} (needs '{dist}') imported by "
                           f"{sorted(files)[0]}")
    check("no runtime import is missing from requirements.txt", not missing,
          "; ".join(missing) if missing else f"{len(imports)} checked")

    for mod, why in EXEMPT.items():
        if mod in imports:
            print(f"  NOTE  {mod} exempt — {why}")

    print("\nOPTIONAL BACKENDS STAY OUT OF THE STARTUP PATH")
    # If one of these ever migrates to a top-level import, the service stops
    # booting anywhere the driver is absent — including local dev and CI.
    for mod in ("boto3", "psycopg2", "redis"):
        if mod in imports:
            check(f"{mod} is imported lazily, not at module top level",
                  mod not in eager,
                  f"top-level in {sorted(eager.get(mod, []))}" if mod in eager
                  else "function-level only")

    print("\nEAGER IMPORTS RESOLVE IN THIS ENVIRONMENT")
    import importlib
    for mod in sorted(eager):
        if mod in EXEMPT:
            continue
        try:
            importlib.import_module(mod)
            ok, detail = True, ""
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        check(f"import {mod}", ok, detail)

    print("\nTHE APP ITSELF IMPORTS CLEAN (what the container does at startup)")
    # Same check the Dockerfile runs, so a failure surfaces here first.
    for target in ("app.api", "app.worker", "app.schedule"):
        try:
            importlib.import_module(target)
            ok, detail = True, ""
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        check(f"import {target}", ok, detail)

    print("\nAND EVERY SOURCE FILE CAN ACTUALLY REACH A DEPLOY")
    # THE MOST EXPENSIVE BUG IN THIS PROJECT SO FAR.
    #
    # The delta zips were packed from a hand-written file list, and
    # `engine/aivis/providers.py` was never on it. The AI Overview provider
    # learned to speak DataForSEO in build ‑38, was tested, and was written up
    # in three changelogs — and the file never went in a zip, never reached the
    # repo, and never ran on the worker. Thirteen builds of fixes were made
    # against code the deployed worker did not have, and the symptom looked
    # like a missing credential the whole time.
    #
    # A file you forget to list reports no error. `pack.py` generates the list
    # from the filesystem now; this guards its filters, so a future exclusion
    # rule cannot quietly start eating source again.
    import pack as _pack
    import datetime as _dt2
    _since = _dt2.datetime.fromisoformat(_pack.DEFAULT_SINCE).timestamp()
    _packed = set(_pack.tracked(_since))
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _missed = []
    for _base, _dirs, _files in os.walk(_root):
        _dirs[:] = [d for d in _dirs if d not in _pack.SKIP_DIRS]
        for _fn in _files:
            if not _fn.endswith((".py", ".js", ".json")):
                continue
            _rel = os.path.relpath(os.path.join(_base, _fn),
                                   _root).replace(os.sep, "/")
            if _rel.startswith(".") or "/." in _rel:
                continue
            if os.path.getmtime(os.path.join(_base, _fn)) < _since:
                continue
            if _rel not in _packed:
                _missed.append(_rel)
    check("no changed source file is excluded from the delta", not _missed,
          ", ".join(sorted(_missed)[:6]))
    # And the file that started it all, by name, because a general rule that
    # happens to cover a specific past failure is worth naming the failure.
    check("engine/aivis/providers.py is in the delta",
          "engine/aivis/providers.py" in _packed)

    print("\n" + "=" * 68)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — nothing imports a package the image lacks")
    print("=" * 68 + "\n")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
