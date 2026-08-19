"""
Route-shape tests.

Written after the PDF link on every finished report returned
{"detail":"audit not found"} in production. The cause was not the PDF code —
it was route registration order. Starlette matches routes in the order they are
declared and a path parameter matches any character except "/", so

    @app.get("/audits/{audit_id}")        # declared first
    @app.get("/audits/{audit_id}.pdf")    # declared second, never reached

means /audits/abc123.pdf binds audit_id="abc123.pdf" and 404s. Every test in
the suite passed, because every test fetched the PDF by calling build_pdf()
directly rather than over HTTP.

So this file exercises the URLs a browser actually requests.

Run:  python3 -m tests.test_routes
"""
from __future__ import annotations
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite:///data/test_routes.db")
os.environ.setdefault("ARTIFACT_STORE", "local://data/test_routes_art")
os.environ.setdefault("SKIP_PSI", "true")

PORT = 8014
API = f"http://127.0.0.1:{PORT}"
FAILURES = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)
    return cond


def GET(path, timeout=60):
    try:
        with urllib.request.urlopen(API + path, timeout=timeout) as r:
            return r.status, r.headers.get("content-type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read()


def main():
    for p in ("data/test_routes.db", "data/test_routes.db-wal",
              "data/test_routes.db-shm"):
        if os.path.exists(p):
            os.remove(p)

    from app import db
    import uvicorn
    db.init_db()

    # A ready audit with real findings, so the PDF renderer has something to do.
    aid = db.create_audit(partner_id="vici", client_name="Junk Bee Gone",
                          target_url="https://junkbeegone.test/",
                          vertical="local_service", options={"max_pages": 50})
    db.update_audit(aid, status="ready", overall_score=79, overall_rating="Strong",
                    coverage="159/313", pages_crawled=9,
                    extras=json.dumps({"context": {"brand": "Junk Bee Gone"}}))
    cat = db.catalog()
    some = list(cat)[:12]
    db.save_findings(aid, {
        cid: {"status": "Fail" if i % 3 == 0 else "Pass",
              "value": {}, "evidence": "example evidence", "affected_pages": [],
              "severity": "High" if i % 3 == 0 else "Low",
              "recommendation": "do the thing", "confidence": 1.0,
              "source": "test"}
        for i, cid in enumerate(some)})
    db.save_scores(aid, {"overall": {"score": 79, "rating": "Strong"},
                         "sections": {}})

    server = uvicorn.Server(uvicorn.Config("app.api:app", host="127.0.0.1",
                                           port=PORT, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(40):
        try:
            urllib.request.urlopen(API + "/healthz", timeout=2)
            break
        except Exception:
            time.sleep(0.3)

    print("\nTHE URLS A BROWSER ACTUALLY REQUESTS")
    st, ct, body = GET(f"/audits/{aid}")
    check("report page renders HTML", st == 200 and "html" in ct, f"{st} {ct}")

    st, ct, body = GET(f"/audits/{aid}.pdf")
    check("PDF link returns 200, not 'audit not found'", st == 200,
          f"{st} {body[:60]!r}")
    check("PDF link returns a real PDF", body[:4] == b"%PDF",
          f"{ct} {len(body)//1024}KB")
    check("PDF is served as application/pdf", "application/pdf" in ct, ct)

    print("\nTHE .PDF SUFFIX IS NOT SWALLOWED BY THE GENERIC ROUTE")
    # The exact failure mode: the id must not arrive with ".pdf" attached.
    st, ct, body = GET(f"/audits/{aid}.pdf")
    check("suffix is stripped before the DB lookup",
          b"audit not found" not in body)

    print("\nBRAND ASSETS ARE SERVED")
    # Three failure modes worth a test: the files not being copied into the
    # image, the routes being shadowed the way the PDF route was, and — the one
    # that actually shipped — a 200 carrying an SVG that no browser will parse.
    st, ct, body = GET("/favicon.svg")
    check("favicon.svg is served", st == 200 and b"<svg" in body, f"{st} {ct}")
    check("favicon uses the Vici field color", b"#002D58" in body)
    check("favicon carries the gold accent", b"#F1B434" in body)

    # THE IMPORTANT ONE. SVG is XML and browsers parse a standalone SVG
    # document strictly: a bare `&` in an attribute kills the whole file
    # silently. Asserting "contains <svg" passed happily while the tab stayed
    # blank for three builds. Assert it PARSES.
    import xml.etree.ElementTree as _ET
    try:
        _ET.fromstring(body)
        parses, why = True, ""
    except Exception as exc:  # noqa: BLE001
        parses, why = False, str(exc)
    check("the served favicon is well-formed XML (a browser can render it)",
          parses, why)

    # And the inlined copy must be the same well-formed bytes — it is built
    # from the file, so a broken file would poison the data URI too.
    import base64 as _b64
    _, _, dash = GET("/")
    m = re.search(rb"data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)", dash)
    check("the head carries an inline data-URI icon", m is not None)
    if m:
        try:
            _ET.fromstring(_b64.b64decode(m.group(1)))
            inline_ok, why = True, ""
        except Exception as exc:  # noqa: BLE001
            inline_ok, why = False, str(exc)
        check("the inlined data-URI icon is well-formed too", inline_ok, why)

    st, ct, body = GET("/favicon.ico")
    check("/favicon.ico does not 404 (browsers ask unprompted)", st == 200, str(st))
    st, ct, body = GET("/apple-touch-icon.png")
    check("apple touch icon is a real PNG",
          st == 200 and body[:8] == b"\x89PNG\r\n\x1a\n", f"{st} {len(body)}B")
    check("dashboard links the icon", b"/favicon.svg" in dash)
    _, _, rep = GET(f"/audits/{aid}")
    check("the report page links it too", b"/favicon.svg" in rep)

    print("\nNEIGHBOURING ROUTES STILL BEHAVE")
    st, ct, body = GET("/audits/does-not-exist")
    check("unknown audit still 404s", st == 404, str(st))
    st, ct, body = GET("/audits/does-not-exist.pdf")
    check("unknown audit .pdf also 404s (not 500)", st == 404, str(st))
    st, ct, body = GET("/")
    check("dashboard renders", st == 200 and b"Junk Bee Gone" in body)
    st, ct, body = GET(f"/api/audits/{aid}")
    check("JSON API unaffected", st == 200 and json.loads(body)["id"] == aid)

    print("\nEVERY LINK THE REPORT PAGE ADVERTISES RESOLVES")
    _, _, html = GET(f"/audits/{aid}")
    hrefs = set(re.findall(rb'href=[\'"](/[^\'" >]+)', html))
    for h in sorted(hrefs):
        path = h.decode()
        if path.startswith("/visibility"):
            continue                      # needs a monitor profile; covered elsewhere
        st, _, _ = GET(path)
        check(f"link {path} resolves", st < 400, str(st))

    print("\n" + "=" * 68)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — the PDF link works over HTTP, not just in code")
    print("=" * 68 + "\n")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
