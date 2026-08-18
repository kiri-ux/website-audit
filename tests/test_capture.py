"""
Browser-capture equivalence test.

The design goal is that a capture from the Chrome extension flows through the
IDENTICAL checkers as a server crawl. So the test is not "does ingest work" —
it is "does a capture of the fixture site produce the SAME findings as a server
crawl of the fixture site". If those ever diverge, you have two audits.

It also asserts the safety net still applies to this path: a capture of an empty
site must be caught by the same degeneracy rules.
"""
import os, sys, json, threading, time, functools, http.server, socketserver, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite:///data/test_capture.db")
os.environ.setdefault("ARTIFACT_STORE", "local://data/test_capture_art")
os.environ.setdefault("SKIP_PSI", "true")

API_PORT, FIXTURE_PORT = 8013, 8099   # 8099 matches the host baked into fixture sitemap.xml
API = f"http://127.0.0.1:{API_PORT}"
FIXTURE = f"http://localhost:{FIXTURE_PORT}/"
FAILURES = []

def check(l, c, d=""):
    print(f"  {'PASS' if c else 'FAIL'}  {l}" + (f"  ({d})" if d else ""))
    if not c: FAILURES.append(l)

def POST(path, payload):
    req = urllib.request.Request(API + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read())

def GET(path):
    with urllib.request.urlopen(API + path, timeout=30) as r:
        return r.status, json.loads(r.read())

def GET_RAW(path):
    with urllib.request.urlopen(API + path, timeout=30) as r:
        return r.status, r.read().decode()


def simulate_extension_capture(art):
    """
    Build the payload the Chrome extension would POST, from a real server crawl
    of the fixture. This exercises the exact wire format content.js emits —
    field names, JSON shapes, list-vs-tuple headings — without needing Chrome.
    """
    pages = []
    for p in art.pages.values():
        if p.error or not (200 <= p.status_code < 300):
            continue
        pages.append({
            "url": p.url, "final_url": p.final_url, "status_code": 200,
            "content_type": p.content_type, "bytes_html": p.bytes_html,
            "title": p.title, "meta_description": p.meta_description,
            "meta_robots": p.meta_robots, "canonical": p.canonical,
            "viewport": p.viewport, "charset": p.charset, "doctype": p.doctype,
            "lang": p.lang, "hreflang": p.hreflang,
            "h1": p.h1,
            "headings": [list(h) for h in p.headings],     # JSON gives lists
            "word_count": p.word_count, "text_html_ratio": p.text_html_ratio,
            "rendered_text": p.rendered_text, "images": p.images,
            "links_internal": p.links_internal, "links_external": p.links_external,
            "scripts": p.scripts, "inline_script_text": p.inline_script_text,
            "schema_types": p.schema_types, "schema_raw": p.schema_raw,
            "capture_method": "browser_extension", "js_rendered": True,
        })
    def fetch(path):
        try:
            with urllib.request.urlopen(FIXTURE.rstrip("/") + path, timeout=10) as r:
                return {"status": r.status, "body": r.read().decode("utf-8", "ignore")}
        except Exception as e:
            return {"status": getattr(e, "code", 0), "body": ""}
    return {"start_url": FIXTURE, "pages": pages,
            "robots": fetch("/robots.txt"), "sitemap": fetch("/sitemap.xml"),
            "llms": fetch("/llms.txt"), "capture_method": "browser_extension"}


def main():
    for p in ("data/test_capture.db", "data/test_capture.db-wal", "data/test_capture.db-shm"):
        if os.path.exists(p): os.remove(p)
    from app import db
    from engine.crawler import Crawler
    from engine import checks

    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "fixture", "site")
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("0.0.0.0", FIXTURE_PORT),
                                   functools.partial(Quiet, directory=root))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    import uvicorn
    db.init_db()
    srv = uvicorn.Server(uvicorn.Config("app.api:app", host="127.0.0.1",
                                        port=API_PORT, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(50):
        try: urllib.request.urlopen(API + "/healthz", timeout=2); break
        except Exception: time.sleep(0.3)

    print("\nBASELINE — server crawl of the fixture")
    art = Crawler(FIXTURE, max_pages=60, delay=0.02, verbose=False).crawl()
    server_findings = checks.run_all(art, {"skip_psi": True})
    check("server crawl succeeded", not art.quality.degenerate,
          f"{len(art.pages)} pages")

    print("\nCAPTURE INGEST")
    st, aud = POST("/api/audits", {"target_url": FIXTURE,
                                   "client_name": "Capture Test",
                                   "vertical": "ecommerce", "skip_psi": True})
    aid = aud["audit_id"]
    payload = simulate_extension_capture(art)
    check("payload carries pages", len(payload["pages"]) >= 16,
          f"{len(payload['pages'])} pages")

    st, res = POST(f"/api/audits/{aid}/capture", payload)
    check("POST /capture returns 200", st == 200, str(st))
    check("ingest reports pages", res.get("pages", 0) >= 16, str(res.get("pages")))
    check("ingest ran the full checker set", res.get("checkpoints", 0) >= 150,
          str(res.get("checkpoints")))

    print("\nEQUIVALENCE — capture must match the server crawl")
    st, f = GET(f"/api/audits/{aid}/findings")
    cap = f["findings"]
    check("same number of checkpoints evaluated",
          len(cap) == len(server_findings),
          f"capture {len(cap)} vs server {len(server_findings)}")

    # Compare statuses on every content-derived checkpoint.
    IGNORE = {  # transport/PSI rows differ by design: server probes them
        "SEC-01","SEC-02","SEC-03","SEC-04","SEC-09","SEC-10","SEC-11","EEAT-19",
        "URL-01","URL-06","URL-15","PERF-01","PERF-06","PERF-16","PERF-04",
        "PERF-15","PERF-17","PERF-10","PERF-11","PERF-12","PERF-13","PERF-14",
        "PERF-19","TECH-07","TECH-02","TECH-06","PERF-03","PERF-08",
    }
    diffs = []
    for cid, sf in server_findings.items():
        if cid in IGNORE: continue
        cf = cap.get(cid)
        if cf and cf["status"] != sf["status"]:
            diffs.append((cid, sf["status"], cf["status"]))
    check("content checkpoint statuses are identical", not diffs,
          "; ".join(f"{c}: server={a} capture={b}" for c, a, b in diffs[:8]))

    # The known fixture defects must survive the browser path unchanged.
    for cid, exp in (("ONP-08", "Fail"), ("ONP-06", "Fail"), ("MOB-01", "Fail"),
                     ("ANA-01", "Pass"), ("SCHEMA-02", "Pass"),
                     ("GEO-04", "Fail"), ("EEAT-12", "Pass")):
        check(f"{cid} matches ground truth via capture", cap[cid]["status"] == exp,
              cap[cid]["status"])

    print("\nREPORT + STATE")
    st, a2 = GET(f"/api/audits/{aid}")
    check("audit marked ready", a2["status"] == "ready", a2["status"])
    check("capture method recorded", a2.get("capture_method") == "browser_extension",
          str(a2.get("capture_method")))
    check("score computed from capture", a2["overall_score"] is not None,
          f"{a2['overall_score']}/100")
    st, html = GET_RAW(f"/audits/{aid}")
    check("report renders from captured data", st == 200 and "<!doctype html>" in html.lower())

    print("\nSAFETY NET STILL APPLIES TO THIS PATH")
    st, aud2 = POST("/api/audits", {"target_url": FIXTURE, "client_name": "Empty",
                                    "skip_psi": True})
    aid2 = aud2["audit_id"]
    empty = {"start_url": FIXTURE, "robots": {"status": 0, "body": ""},
             "sitemap": {"status": 0, "body": ""}, "llms": {"status": 0, "body": ""},
             "pages": [{"url": FIXTURE, "status_code": 200, "bytes_html": 120,
                        "title": None, "h1": [], "links_internal": [],
                        "word_count": 3, "images": [], "headings": [],
                        "scripts": [], "schema_types": []}]}
    st, res2 = POST(f"/api/audits/{aid2}/capture", empty)
    st, f2 = GET(f"/api/audits/{aid2}/findings")
    check("degenerate capture caught by the same gate",
          f2["findings"]["ONP-02"]["status"] == "Need Access",
          f2["findings"]["ONP-02"]["status"])
    st, a3 = GET(f"/api/audits/{aid2}")
    check("degenerate capture flagged on the audit", bool(a3.get("crawl_blocked")))

    print("\n" + "=" * 68)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — browser capture is equivalent to a server crawl")
    print("=" * 68 + "\n")
    httpd.shutdown()
    return 1 if FAILURES else 0

if __name__ == "__main__":
    sys.exit(main())
