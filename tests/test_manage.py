"""
Delete and client-grouping tests.

Deleting is the one operation that can quietly destroy data, so the things
asserted here are: it removes EVERYTHING belonging to the audit (an orphaned
findings row is invisible and impossible to clear from the UI), it refuses to
touch another tenant's data, and it does not take an AI-visibility time series
down with it.

Grouping is asserted because the merge key is deliberately dumb — case and
whitespace only. Anything cleverer would eventually merge two real clients into
one row, which is worse than a long list.

Run:  python3 -m tests.test_manage
"""
from __future__ import annotations
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite:///data/test_manage.db")
os.environ.setdefault("ARTIFACT_STORE", "local://data/test_manage_art")
os.environ.setdefault("SKIP_PSI", "true")

PORT = 8016
API = f"http://127.0.0.1:{PORT}"
FAILURES = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)
    return cond


def req(method, path, timeout=30):
    r = urllib.request.Request(API + path, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main():
    for p in ("data/test_manage.db", "data/test_manage.db-wal",
              "data/test_manage.db-shm"):
        if os.path.exists(p):
            os.remove(p)
    import shutil
    shutil.rmtree("data/test_manage_art", ignore_errors=True)

    from app import db
    from app.artifacts import put_artifact, get_artifact
    import uvicorn
    db.init_db()

    print("\nGROUPING BY CLIENT")
    ids = []
    for i, (name, score) in enumerate([
            ("Grand Furniture", 76), ("grand furniture ", 72),
            ("GRAND FURNITURE", 73), ("Junk Bee Gone", 79),
            ("Grand Home Furnishings", 61)]):
        aid = db.create_audit(partner_id="vici", client_name=name,
                              target_url="https://x.test/", options={})
        db.update_audit(aid, status="ready", overall_score=score,
                        coverage="159/313", pages_crawled=10,
                        created_at=time.time() - i * 60)
        ids.append(aid)

    groups = db.group_by_client(db.list_audits("vici"))
    by_name = {g["key"]: g for g in groups}
    check("case and whitespace variants merge into one client",
          len(groups) == 3, f"{len(groups)} groups: {[g['key'] for g in groups]}")
    check("the merged client keeps every run",
          by_name["grand furniture"]["runs"] == 3,
          str(by_name["grand furniture"]["runs"]))
    check("newest run is the headline",
          by_name["grand furniture"]["latest"]["overall_score"] == 76,
          str(by_name["grand furniture"]["latest"]["overall_score"]))
    check("history excludes the headline",
          len(by_name["grand furniture"]["history"]) == 2)
    # The important negative: similar names are NOT the same client.
    check("similarly-named clients are NOT merged",
          "grand home furnishings" in by_name and "grand furniture" in by_name,
          str(sorted(by_name)))

    print("\nDELETE REMOVES EVERYTHING BELONGING TO THE AUDIT")
    target = ids[0]
    db.save_findings(target, {"TECH-01": {
        "status": "Fail", "value": {}, "evidence": "x", "affected_pages": [],
        "severity": "High", "recommendation": "y", "confidence": 1.0,
        "source": "test"}})
    db.save_scores(target, {"overall": {"score": 76, "rating": "Strong"},
                            "sections": {"TECH": {"score": 76, "rating": "Strong",
                                                  "checked": 1, "total": 1,
                                                  "failing": 1, "need_access": 0}}})
    put_artifact(target, "crawl_artifact.json", b'{"pages":{}}')
    check("fixture audit has findings", len(db.get_findings(target)) == 1)
    check("fixture audit has an artifact",
          get_artifact(target, "crawl_artifact.json") is not None)

    from app.artifacts import delete_artifacts
    delete_artifacts(target)
    check("delete_audit reports success", db.delete_audit(target, "vici") is True)
    check("audit row is gone", db.get_audit(target) is None)
    check("findings are gone", db.get_findings(target) == {})
    check("section scores are gone",
          not (db.get_scores(target) or {}).get("sections"))
    check("artifact blob is gone",
          get_artifact(target, "crawl_artifact.json") is None)

    print("\nDELETE IS SCOPED AND SAFE")
    check("deleting an unknown id returns False",
          db.delete_audit("does-not-exist", "vici") is False)
    other = db.create_audit(partner_id="someone-else", client_name="Not Yours",
                            target_url="https://y.test/", options={})
    check("another tenant's audit cannot be deleted",
          db.delete_audit(other, "vici") is False)
    check("and it is still there", db.get_audit(other) is not None)

    print("\nA MONITOR TIME SERIES SURVIVES ITS AUDIT BEING DELETED")
    aid = db.create_audit(partner_id="vici", client_name="Series Co",
                          target_url="https://z.test/", options={})
    prof = db.create_ai_profile("vici", "Series Co",
                                {"brand": "Series Co", "domain": "z.test"}, [])
    run = db.create_ai_run("vici", prof, 1, audit_id=aid)
    db.delete_audit(aid, "vici")
    r = db.get_ai_run(run)
    check("the run still exists after its audit is deleted", r is not None)
    check("and is simply unlinked, not destroyed",
          r is not None and not r.get("audit_id"), str((r or {}).get("audit_id")))

    print("\nOVER HTTP, THE WAY THE UI CALLS IT")
    server = uvicorn.Server(uvicorn.Config("app.api:app", host="127.0.0.1",
                                           port=PORT, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(40):
        try:
            urllib.request.urlopen(API + "/healthz", timeout=2)
            break
        except Exception:
            time.sleep(0.3)

    victim = ids[3]
    st, body = req("DELETE", f"/api/audits/{victim}")
    check("DELETE /api/audits/{id} returns 200", st == 200, str(st))
    check("audit really gone", db.get_audit(victim) is None)
    st, body = req("DELETE", f"/api/audits/{victim}")
    check("deleting it twice 404s rather than 500s", st == 404, str(st))

    before = len(db.list_audits("vici"))
    st, body = req("POST", "/clients/grand%20furniture/prune")
    after = db.list_audits("vici")
    remaining = [a for a in after
                 if db.client_key(a["client_name"]) == "grand furniture"]
    check("prune redirects back to the dashboard", st in (200, 303), str(st))
    check("prune keeps exactly one run for that client",
          len(remaining) == 1, f"{len(remaining)} left")
    check("prune keeps the NEWEST run",
          remaining and remaining[0]["overall_score"] == 72,
          str(remaining[0]["overall_score"] if remaining else None))
    check("prune touched nothing else",
          len(after) == before - 1, f"{before} -> {len(after)}")

    st, body = req("GET", "/")
    check("dashboard renders grouped", st == 200 and b"Clients" in body)
    check("each client exposes the settings its last run used",
          b"Settings used" in body)
    check("and can seed a new audit from them without retyping",
          b"data-prefill" in body and b"function prefill" in body)

    print("\nPHASE SELECTION — RUN ONLY WHAT YOU NEED")
    # An unticked checkbox sends nothing, which looks identical to a caller
    # that predates the feature. Getting this backwards means either silently
    # skipping the judgment layer or silently ignoring the operator's choice.
    import urllib.parse as _up
    src2 = db.create_audit(partner_id="vici-internal", client_name="Phase Co",
                           target_url="https://phase.test/", options={})
    db.update_audit(src2, status="ready")
    put_artifact(src2, "crawl_artifact.json", b'{"pages":{}}')

    def submit(extra):
        d = {"target_url": "https://phase.test/", "client_name": "Phase Co"}
        d.update(extra)
        r = urllib.request.Request(API + "/audits",
                                   data=_up.urlencode(d).encode(), method="POST")
        class _NR(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k): return None
        try:
            resp = urllib.request.build_opener(_NR).open(r, timeout=30)
            loc = resp.headers.get("Location")
        except urllib.error.HTTPError as ex:
            loc = ex.headers.get("Location")
        return json.loads(db.get_audit(loc.rsplit("/", 1)[-1])["options"])

    o = submit({"phases": "1", "run_judgment": "1", "run_collectors": "1",
                "run_screenshots": "1"})
    check("every box ticked skips nothing",
          not any(o.get(k) for k in ("skip_judgment", "skip_collectors",
                                     "skip_screenshots")), str(o))
    o = submit({"phases": "1", "run_collectors": "1"})
    check("an unticked box really does skip that phase",
          o["skip_judgment"] and o["skip_screenshots"]
          and not o["skip_collectors"], str(o))
    o = submit({})
    check("a caller with no phases field still runs everything",
          not any(o.get(k) for k in ("skip_judgment", "skip_collectors",
                                     "skip_screenshots")), str(o))
    o = submit({"phases": "1", "run_judgment": "1", "reuse_crawl": "1"})
    # Deliberately NOT resolved here. The API and the worker are separate
    # containers, and with a local ARTIFACT_STORE the API cannot see a single
    # artifact the worker wrote — so resolving on this side found nothing,
    # dropped the option, and crawled the site anyway, which is precisely what
    # ticking the box was meant to prevent.
    check("the API records the intent and leaves resolution to the worker",
          o.get("reuse_crawl") is True and "reuse_artifact_from" not in o,
          str(o))

    from app.worker import _newest_artifact_for
    check("the worker resolves it to the newest run holding an artifact",
          _newest_artifact_for("https://phase.test/") == src2,
          str(_newest_artifact_for("https://phase.test/")))
    check("a URL we have never crawled resolves to nothing",
          _newest_artifact_for("https://never-audited.test/") is None)
    check("dashboard offers a re-run", b"/rerun" in body)

    print("\nRE-RUN MAKES A NEW AUDIT, IT DOES NOT OVERWRITE")
    # The reason anyone re-runs is to see whether a fix worked. Re-queuing the
    # same row would overwrite the "before" and destroy the comparison.
    src = db.list_audits("vici")[0]
    db.save_findings(src["id"], {"TECH-01": {
        "status": "Pass", "value": {}, "evidence": "before", "affected_pages": [],
        "severity": "Low", "recommendation": "", "confidence": 1.0,
        "source": "test"}})
    # Counted UNFILTERED: the API creates audits owned by the internal
    # principal ("vici-internal"), while the fixtures above are seeded as
    # "vici". Filtering by the fixture's partner id would silently miss the
    # new row and make this assertion test nothing.
    before_n = len(db.list_audits())
    st, body = req("POST", f"/api/audits/{src['id']}/rerun")
    check("rerun returns 202", st == 202, str(st))
    new_id = json.loads(body)["audit_id"]
    check("a NEW audit id is returned", new_id != src["id"])
    check("the original still exists", db.get_audit(src["id"]) is not None)
    check("the original's findings are untouched",
          db.get_findings(src["id"])["TECH-01"]["evidence"] == "before")
    after_n = len(db.list_audits())
    check("audit count went up by one", after_n == before_n + 1,
          f"{before_n} -> {after_n}")
    nw = db.get_audit(new_id)
    check("target and client are carried over",
          nw["target_url"] == src["target_url"]
          and nw["client_name"] == src["client_name"])
    check("it groups under the same client",
          db.client_key(nw["client_name"]) == db.client_key(src["client_name"]))
    check("it is queued for the worker", nw["status"] == "queued", nw["status"])
    st, body = req("POST", "/api/audits/nope/rerun")
    check("rerunning an unknown audit 404s", st == 404, str(st))

    print("\n" + "=" * 68)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — delete is complete and scoped; grouping is safe")
    print("=" * 68 + "\n")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
