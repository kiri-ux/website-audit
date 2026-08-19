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

    print("\n" + "=" * 68)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — delete is complete and scoped; grouping is safe")
    print("=" * 68 + "\n")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
