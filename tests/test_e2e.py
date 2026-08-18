"""
End-to-end integration test.

Boots the fixture site, the API and a worker in one process, submits an audit
through the HTTP API exactly as a client would, and asserts the whole pipeline:

    POST /api/audits  ->  queue  ->  worker  ->  crawl  ->  checks  ->  scoring
                      ->  DB     ->  GET /api/audits/{id}  ->  report HTML

Run:  python3 -m tests.test_e2e
"""
from __future__ import annotations
import json
import os
import sys
import threading
import time
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite:///data/test_e2e.db")
os.environ.setdefault("ARTIFACT_STORE", "local://data/test_artifacts")
os.environ.setdefault("SKIP_PSI", "true")

API_PORT, FIXTURE_PORT = 8010, 8090
API = f"http://127.0.0.1:{API_PORT}"
FIXTURE = f"http://localhost:{FIXTURE_PORT}/"   # fixture is port-corrected

FAILURES = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)
    return cond


def GET(path):
    with urllib.request.urlopen(API + path, timeout=15) as r:
        return r.status, json.loads(r.read())


def GET_RAW(path):
    with urllib.request.urlopen(API + path, timeout=30) as r:
        return r.status, r.read().decode()


def POST(path, payload):
    req = urllib.request.Request(
        API + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, json.loads(r.read())


def wait_for(url, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def main():
    # fresh DB so the run is deterministic
    for p in ("data/test_e2e.db", "data/test_e2e.db-wal", "data/test_e2e.db-shm"):
        if os.path.exists(p):
            os.remove(p)

    from app import db, worker
    from app.config import cfg

    # ---------- boot fixture site ----------
    # Served from a port-corrected COPY so sitemap URLs match the port this test
    # owns; otherwise sitemap seeding is silently skipped and the crawl covers
    # only nav-linked pages.
    from tests._fixture import serve, stop as stop_server
    httpd, root = serve(FIXTURE_PORT)

    # ---------- boot API ----------
    import uvicorn
    db.init_db()
    server = uvicorn.Server(uvicorn.Config("app.api:app", host="127.0.0.1",
                                           port=API_PORT, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()

    # ---------- boot worker ----------
    threading.Thread(target=worker.main, daemon=True).start()

    print(f"\nCONFIG: {cfg.summary()}\n")
    print("BOOT")
    check("fixture site reachable", wait_for(FIXTURE))
    check("API reachable", wait_for(API + "/healthz"))

    st, h = GET("/healthz")
    check("GET /healthz returns ok", st == 200 and h["ok"], f"mode={h['mode']}")

    # ---------- submit ----------
    print("\nSUBMIT")
    st, resp = POST("/api/audits", {
        "target_url": FIXTURE, "client_name": "Grand Home Furnishings",
        "vertical": "ecommerce", "max_pages": 60, "skip_psi": True})
    check("POST /api/audits returns 202 (does NOT block on the crawl)", st == 202,
          f"status={st}")
    aid = resp.get("audit_id")
    check("response carries an audit_id", bool(aid), aid or "")

    st, a = GET(f"/api/audits/{aid}")
    check("audit starts in a pre-ready state", a["status"] in
          ("queued", "crawling", "checking", "scoring"), a["status"])

    # ---------- worker processes it ----------
    print("\nPROCESS")
    t0, seen = time.time(), []
    while time.time() - t0 < 120:
        st, a = GET(f"/api/audits/{aid}")
        if a["status"] not in seen:
            seen.append(a["status"])
            print(f"    t+{time.time()-t0:5.1f}s  {a['status']:<9} {a.get('progress') or ''}")
        if a["status"] in ("ready", "failed"):
            break
        time.sleep(1)

    check("audit reached ready", a["status"] == "ready",
          a.get("error") or a["status"])
    check("status advanced through the pipeline", len(seen) >= 2, " -> ".join(seen))
    check("pages were crawled", (a.get("pages_crawled") or 0) >= 16,
          f"{a.get('pages_crawled')} pages")
    check("overall score computed", a.get("overall_score") is not None,
          f"{a.get('overall_score')}/100 {a.get('overall_rating')}")

    # ---------- findings persisted ----------
    print("\nPERSISTENCE")
    st, f = GET(f"/api/audits/{aid}/findings")
    fs = f["findings"]
    check("findings persisted to DB", len(fs) >= 150, f"{len(fs)} checkpoints")
    check("findings carry provenance", all(
        "source" in v and "confidence" in v for v in fs.values()))
    check("section scores persisted", len(a.get("scores", {}).get("sections", {})) >= 12,
          f"{len(a.get('scores',{}).get('sections',{}))} sections")

    # a couple of known fixture defects must survive the round-trip through the DB
    check("GEO-04 detected AI-crawler blocking", fs["GEO-04"]["status"] == "Fail",
          str(fs["GEO-04"]["value"].get("blocked")))
    check("ONP-08 detected duplicate H1s", fs["ONP-08"]["status"] == "Fail",
          f"count={fs['ONP-08']['value'].get('count')}")
    check("ANA-01 detected GTM", fs["ANA-01"]["status"] == "Pass")
    check("Need Access rows excluded from scoring, not zeroed",
          all(s["score"] is None or s["score"] >= 0
              for s in a["scores"]["sections"].values()))

    # ---------- artifact ----------
    st, raw = GET_RAW(f"/api/audits/{aid}/artifact")
    check("crawl artifact stored and retrievable", st == 200 and len(raw) > 1000,
          f"{len(raw)//1024}KB")

    # ---------- report ----------
    print("\nREPORT")
    st, html = GET_RAW(f"/audits/{aid}")
    check("report renders HTML", st == 200 and "<!doctype html>" in html.lower(),
          f"{len(html)//1024}KB")
    check("report contains the score", str(a["overall_score"]) in html)
    check("report lists findings", html.count("<tr>") > 100,
          f"{html.count('<tr>')} rows")

    # ---------- dashboard ----------
    st, dash = GET_RAW("/")
    check("dashboard renders", st == 200 and "Grand Home Furnishings" in dash)

    # ---------- tenancy ----------
    print("\nTENANCY")
    st, lst = GET("/api/audits")
    check("audit is listed for the internal principal", any(
        x["id"] == aid for x in lst["audits"]))
    check("audit row carries a partner_id (multi-tenancy seam present)",
          bool(GET(f"/api/audits/{aid}")[1].get("partner_id")),
          GET(f"/api/audits/{aid}")[1].get("partner_id"))

    # ---------- idempotency ----------
    print("\nIDEMPOTENCY")
    before = len(fs)
    worker.run_audit_job(aid)          # simulate at-least-once redelivery
    st, f2 = GET(f"/api/audits/{aid}/findings")
    check("re-running the job does not duplicate findings",
          len(f2["findings"]) == before, f"{before} -> {len(f2['findings'])}")

    print("\n" + "=" * 66)
    if FAILURES:
        print(f"  {len(FAILURES)} FAILED: {', '.join(FAILURES)}")
    else:
        print("  ALL CHECKS PASSED — full pipeline verified end to end")
    print("=" * 66 + "\n")
    stop_server(httpd)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
