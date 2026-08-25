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


def POST(path, data=b"", timeout=60):
    req = urllib.request.Request(API + path, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("content-type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read()


class _FakeReq:
    """Just enough of a Starlette Request for _redirect_uri()."""

    def __init__(self, base):
        self.base_url = base


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

    print("\nACCESS PREFLIGHT ANSWERS BEFORE THE AUDIT RUNS")
    # The point of this endpoint is to be trusted, so it must never 500 and
    # must never claim a client grant is missing when the truth is that THIS
    # service has no credentials. Both states are reachable in the test env.
    st, _, body = GET("/api/access-check?target_url=https://example.com/")
    check("preflight returns 200 even with nothing configured", st == 200, str(st))
    d = json.loads(body)
    check("it reports all three grants", {"gsc", "ga4", "gtm"} <= set(d),
          str(list(d)))
    check("an unconfigured service says so, and marks it as OURS",
          d["gsc"].get("ours") is True and "not set" in d["gsc"]["detail"],
          d["gsc"].get("detail", "")[:60])
    check("it does not claim the client failed to grant anything",
          "add a Vici login" not in json.dumps(d))
    st, _, _b = GET("/api/access-check?target_url=example.com")
    check("a URL without a scheme is refused rather than guessed at",
          st == 400, str(st))
    _, _, dash2 = GET("/")
    # Assert the WIRING and the coverage, not the button's copy. This pinned
    # the literal string "Check GA4", so renaming the button to "Check Google
    # access" — because it covers three services now, not two — failed a test
    # about whether the check is reachable.
    check("the dashboard offers the check next to the URL field",
          b"/api/access-check" in dash2 and b"checkAccess()" in dash2)
    check("and the check covers all three Google grants",
          all(x in dash2 for x in (b"gscsel", b"ga4sel", b"gtmsel")))

    print("\nTHE EXTENSION IS DOWNLOADABLE FROM THE APP")
    # "Ask someone for the folder" is not a step that survives a Tuesday, and
    # an unpacked extension vanishes whenever its folder moves.
    st, ct, z = GET("/extension.zip")
    check("extension.zip is served", st == 200 and z[:2] == b"PK", f"{st} {ct}")
    import io as _io, zipfile as _zf
    names = set(_zf.ZipFile(_io.BytesIO(z)).namelist())
    check("and it is a loadable extension, manifest included",
          {"manifest.json", "background.js", "content.js"} <= names, str(sorted(names)))

    print("\nPROPERTY PICKERS — A MISS IS CHECKABLE, NOT FINAL")
    st, _, body = GET("/api/properties")
    check("property list returns 200 with nothing configured", st == 200, str(st))
    pl = json.loads(body)
    check("it always returns both lists, even empty",
          isinstance(pl.get("gsc"), list) and isinstance(pl.get("ga4"), list),
          str(list(pl)))
    check("and surfaces per-login errors rather than hiding them",
          "errors" in pl and isinstance(pl["errors"], list))
    _, _, dash3 = GET("/")
    check("the form carries both dropdowns",
          b"gsc_property" in dash3 and b"ga4_property_id" in dash3)
    check("with a filter, because a login can hold hundreds",
          b"filterSel" in dash3)

    print("\nTHE GOOGLE OAUTH SETUP SURFACE ONLY EXISTS WHEN YOU OPEN IT")
    # These two routes mint a refresh token that inherits everything a Vici
    # login can see across every client's Search Console and Analytics. That is
    # the most valuable credential this service touches, so the default state is
    # "the route does not exist" rather than "the route exists and checks".
    import app.api as _api
    st, _, _b = GET("/oauth/google/start?t=anything&label=x")
    check("start 404s while OAUTH_SETUP_TOKEN is unset", st == 404, str(st))
    st, _, _b = GET("/oauth/google/callback?code=c&state=x|anything")
    check("callback 404s while OAUTH_SETUP_TOKEN is unset", st == 404, str(st))

    st, _, hz = GET("/healthz")
    check("healthz reports the setup surface as closed",
          json.loads(hz).get("oauth_setup") is False, hz[:120].decode())

    os.environ["OAUTH_SETUP_TOKEN"] = "s3cret"
    try:
        # The two ways start can 404 — old build, or token unset/mistyped —
        # are indistinguishable from a browser. healthz tells them apart.
        st, _, hz = GET("/healthz")
        check("healthz reports the setup surface as open once it is",
              json.loads(hz).get("oauth_setup") is True, hz[:120].decode())
        check("healthz never echoes the token itself",
              b"s3cret" not in hz, hz[:200].decode())
        st, _, _b = GET("/oauth/google/start?t=wrong&label=x")
        check("a wrong setup token still 404s, it does not 401", st == 404, str(st))
        st, _, _b = GET("/oauth/google/callback?code=c&state=x|wrong")
        check("callback rejects a mismatched state token", st == 404, str(st))
        st, _, _b = GET("/oauth/google/start?t=s3cret")
        check("a missing label is refused before Google is involved",
              st == 400, str(st))
        # No GOOGLE_CLIENT_ID in the test environment: the route must say so
        # rather than redirecting to a malformed consent URL.
        st, _, _b = GET("/oauth/google/start?t=s3cret&label=seo-main")
        check("without GOOGLE_CLIENT_ID it explains rather than redirecting",
              st == 400, str(st))
        check("the redirect URI is forced to https for Google",
              _api._redirect_uri(_FakeReq("http://audit.example.com/"))
              == "https://audit.example.com/oauth/google/callback",
              _api._redirect_uri(_FakeReq("http://audit.example.com/")))
        check("localhost stays http so local setup works",
              _api._redirect_uri(_FakeReq("http://127.0.0.1:8000/"))
              == "http://127.0.0.1:8000/oauth/google/callback")
    finally:
        os.environ.pop("OAUTH_SETUP_TOKEN", None)
    st, _, _b = GET("/oauth/google/start?t=s3cret&label=seo-main")
    check("and it is gone again once the variable is removed", st == 404, str(st))
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

    print("\nTHE CONSENT DETAIL PAGE, OVER HTTP")
    # The report advertises this link on every audit that ran a consent scan,
    # so it has to resolve for real — a dead link there reads as a broken
    # feature rather than a phase nobody ticked.
    from app.artifacts import put_artifact as _put
    _put(aid, "consent_scan.json", json.dumps({
        "scan": {"mode": "full", "verdict": "no_cmp", "cmps": [],
                 "gtm": {"found": True, "container_ids": ["GTM-TEST123"]},
                 "consent_mode_default": False, "reject_tested": False,
                 "gpc_tested": False, "states": ["TN"],
                 "pre_consent": [{"vendor": "Meta Pixel", "severity": "ungated",
                                  "url": "https://facebook.com/tr?id=9"}]},
        "pages": [{"url": "https://junkbeegone.test/", "role": "homepage",
                   "scan": {"mode": "full", "pre_consent": []}}],
        "requested": {"states": ["TN"]}}).encode())
    _ex = json.loads(db.get_audit(aid).get("extras") or "{}")
    _ex["consent"] = {"mode": "full", "verdict": "no_cmp", "has_detail": True}
    db.update_audit(aid, extras=json.dumps(_ex))

    st, ct, body = GET(f"/audits/{aid}/consent")
    check("the consent page renders", st == 200 and b"GTM-TEST123" in body,
          f"{st} {len(body)}B")
    check("and names the ungated pixel", b"Meta Pixel" in body)
    st, ct, body = GET(f"/api/audits/{aid}/consent")
    check("the JSON route serves the stored scan",
          st == 200 and json.loads(body)["scan"]["verdict"] == "no_cmp",
          str(st))
    _, _, _rep = GET(f"/audits/{aid}")
    check("and the report page links to it",
          f"/audits/{aid}/consent".encode() in _rep)
    # An audit with no stored detail must still answer, because the link is
    # drawn from extras and an older audit has extras but no artifact.
    st, _, body = GET("/audits/doesnotexist/consent")
    check("an unknown audit is still a 404", st == 404, str(st))

    print("\nA RUN CAN BE STOPPED WHILE IT IS RUNNING")
    # STOP IS COOPERATIVE, so what this asserts is the contract between the
    # two processes: the API marks the row, the worker's checkpoint raises,
    # and a stop is never reported as a failure or put back on the queue.
    import time as _t
    from app import db as _db, worker as _w
    rid = _db.create_audit(partner_id="vici", client_name="Stoppable",
                           target_url="https://stopme.test/",
                           vertical="local_service", options={})
    _db.update_audit(rid, status="crawling", heartbeat_at=_t.time())
    st, _, body = POST(f"/api/audits/{rid}/stop")
    check("the stop endpoint answers", st == 200, str(st))
    check("and it records the request", json.loads(body)["stopping"] is True,
          body[:120])
    row = _db.get_audit(rid)
    check("the row is flagged, not force-failed", bool(row.get("cancel_at"))
          and row["status"] == "crawling", str(row["status"]))
    try:
        _w._stop_if_cancelled(rid)
        check("the worker's checkpoint raises", False, "no raise")
    except _w.Cancelled:
        check("the worker's checkpoint raises", True)
    # A queued run has no worker to notice, so the API closes it itself.
    qid = _db.create_audit(partner_id="vici", client_name="Queued",
                           target_url="https://queued.test/",
                           vertical="local_service", options={})
    POST(f"/api/audits/{qid}/stop")
    check("a queued run is stopped outright, not left 'stopping'",
          _db.get_audit(qid)["status"] == "canceled",
          _db.get_audit(qid)["status"])
    # And a finished run has nothing to stop.
    st, _, body = POST(f"/api/audits/{aid}/stop")
    check("stopping a finished run is a no-op with an explanation",
          st == 200 and json.loads(body)["stopping"] is False, body[:120])
    _, _, page = GET(f"/audits/{rid}")
    check("the running page offers the button",
          b"/stop" in page, str(page[:0]))
    # A RUN THAT WAS INTERRUPTED HAS NOBODY LEFT TO NOTICE.
    #
    # Deploying mid-scan takes the process with it. Stop on that row used to
    # write the flag and wait for a reader that was never coming, so the page
    # sat at "stopping" until the stall detector reported it as a fault - for
    # something the person deliberately did.
    from app.ui import STALE_AFTER_S as _STALE
    gid = _db.create_audit(partner_id="vici", client_name="Interrupted",
                           target_url="https://gone.test/",
                           vertical="local_service", options={})
    _db.update_audit(gid, status="checking",
                     heartbeat_at=_t.time() - _STALE - 60)
    POST(f"/api/audits/{gid}/stop")
    row = _db.get_audit(gid)
    check("an interrupted run closes out immediately",
          row["status"] == "canceled", row["status"])
    check("and says why, without blaming the site",
          "interrupted" in (row.get("progress") or ""), row.get("progress"))

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
    print("\nTHE TAB INDICATOR HAS TO RUN AFTER THE PAGE IT DECORATES")
    # It was injected above both <title> and the brand favicon and ran at
    # parse time, so it read an empty title and set an icon the brand's own
    # link then replaced. Correct code, two lines too early - the pulse never
    # appeared once in three builds.
    from app.ui import _tab as _tabjs
    _js = _tabjs("running")
    check("the pulse waits for the document to be parsed",
          "DOMContentLoaded" in _js, _js[:80])
    check("it does not read the title before the title exists",
          "var mode=" in _js and "base=''" in _js.replace(" ", ""),
          _js[_js.find("var mode="):_js.find("var mode=") + 60])
    check("it takes the icon over instead of sharing it",
          "removeChild" in _js)
    check("a page that is not running gets no script", _tabjs(None) == "")

    print("\nTHE SNAPSHOT IS THE SAME REPORT, SHORTER")
    # A three-page summary assembled from its own private copy of the score
    # would disagree with the full audit in front of a client within two
    # builds. It is built from the SAME findings by the SAME functions, and
    # what it drops is the evidence - the appendix, the per-section tables,
    # the methodology - not the arithmetic.
    st_s, _ct_s, body_s = GET(f"/audits/{aid}.snapshot.pdf")
    check("the snapshot route is registered before the .pdf one", st_s == 200,
          str(st_s))
    check("and returns a PDF", body_s[:4] == b"%PDF", str(body_s[:12]))
    st_f, _ct_f, body_f = GET(f"/audits/{aid}.pdf")
    check("the full report still works", st_f == 200 and body_f[:4] == b"%PDF")
    check("and the snapshot is genuinely shorter",
          len(body_s) < len(body_f),
          f"{len(body_s)} vs {len(body_f)} bytes")
    try:
        import io as _io8, pdfplumber as _pp8
        with _pp8.open(_io8.BytesIO(body_s)) as _d8:
            _n8 = len(_d8.pages)
            _t8 = "\n".join((_pg.extract_text() or "") for _pg in _d8.pages)
            _blank_pages = [i + 1 for i, _pg in enumerate(_d8.pages)
                            if len(_pg.extract_words()) <= 12]
        check("the snapshot is a handful of pages", _n8 <= 6, f"{_n8} pages")
        check("it is the snapshot, and it names the client",
              "Snapshot" in _t8 and "Junk Bee Gone" in _t8, _t8[:90])
        check("it points the reader at the full audit",
              "full audit" in _t8.lower(), _t8[-140:])
        check("and drops the appendix", "Appendix" not in _t8)
        # NO BLANK PAGES.
        #
        # A Spacer is a flowable with height, so a trailing one at the foot of
        # a full page wraps onto the NEXT page and a PageBreak right after it
        # ends that page with nothing on it. That is how the snapshot grew a
        # blank page 2. Every section here ends with a spacer, so this is one
        # layout change away from happening again in a different place.
        check("no page is blank but for its footer", not _blank_pages,
              f"blank page(s): {_blank_pages}")
    except ImportError:
        print("  SKIP  pdfplumber not installed")

    print("=" * 68 + "\n")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
