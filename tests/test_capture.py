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

API_PORT, FIXTURE_PORT = 8013, 8091   # own port; fixture is port-corrected
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

    from tests._fixture import serve, stop as stop_server
    httpd, root = serve(FIXTURE_PORT)

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
    # The capture path also runs the judgment layer and external collectors, so
    # it is a SUPERSET. Equivalence is about the crawler-derived rows agreeing.
    check("capture is a superset of the server crawl",
          set(server_findings) <= set(cap),
          f"capture {len(cap)} vs server {len(server_findings)}")
    check("every server checkpoint also appears in the capture",
          not (set(server_findings) - set(cap)),
          str(sorted(set(server_findings) - set(cap))[:6]))

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

    print("\nA SHOT THAT PROMISES A RED MARK HAS TO CARRY ONE")
    # THE BUG, REPLAYED - THREE TIMES.
    #
    # The caption says "the thing each check flagged outlined in red". Three
    # separate DOM checks were added to keep that true: does the selector
    # match, is the element visible, is its rectangle in the viewport. All
    # three passed and the picture still came back with no red on it, because
    # a clip, a sticky header or a transform is invisible to the DOM.
    #
    # The picture is the deliverable, so the picture is what gets checked.
    from engine.screenshots import has_mark, MARK_RGB, _rows
    import struct as _st, zlib as _zl

    def _png(w, h, rgb):
        def _chunk(tag, data):
            c = tag + data
            return _st.pack(">I", len(data)) + c + _st.pack(">I",
                                                            _zl.crc32(c))
        raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
        return (b"\x89PNG\r\n\x1a\n"
                + _chunk(b"IHDR", _st.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + _chunk(b"IDAT", _zl.compress(raw))
                + _chunk(b"IEND", b""))

    check("a picture painted in the mark colour is recognised",
          has_mark(_png(40, 40, MARK_RGB)))
    check("a picture with none of it is not",
          not has_mark(_png(40, 40, (255, 255, 255))))
    check("nor is one in a different red",
          not has_mark(_png(40, 40, (255, 0, 0))))
    check("an undecodable blob is not thrown away",
          has_mark(b"not a png"))
    check("the decoder reads what Chromium emits",
          (_rows(_png(8, 4, MARK_RGB)) or [None])[0] == 8)

    # ---------- a long phase has to keep talking ----------
    #
    # The screenshot block launched a browser four times behind ONE heartbeat.
    # That single omission is three separate faults, because in this worker
    # the heartbeat, the progress message and the cancel checkpoint are all
    # the same call:
    #
    #   * the operator sees a message that cannot change for the length of the
    #     phase, and reasonably asks whether the thing is broken;
    #   * Stop has no checkpoint to land on;
    #   * and the stall detector reads a working run as a dead container.
    #
    # So: a step per capture, a cancel that lands mid-phase, and a wall-clock
    # budget that makes good on "a browser that hangs costs us a picture
    # rather than the report" - which was a comment, not a mechanism.
    print("\nTHE CHECKS THAT FAIL HAVE SOMETHING TO PHOTOGRAPH")
    # AN EMPTY CANDIDATE LIST IS NOT A CAPTURE FAILURE.
    #
    # A real audit came back with no evidence shots at all, and the capture
    # code was never reached: the selector map covered images, headings and
    # footers, while the audit's top finding was "the practice-area pages
    # carry only a nav menu and a short blurb" - ONP-10 and ONP-13, neither of
    # which had a selector or a page-level entry. Nothing was eligible, so
    # nothing was tried, so the section omitted itself.
    from engine.screenshots import SELECTORS as _SEL, PAGE_LEVEL as _PL
    import csv as _csv
    _cat_ids = set()
    with open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "seed", "checkpoints.csv")) as fh:
        for row in _csv.reader(fh):
            if row and row[0] and "-" in row[0]:
                _cat_ids.add(row[0].strip())
    _bogus = [c for c in list(_SEL) + list(_PL) if c not in _cat_ids]
    check("every selector points at a checkpoint that exists",
          not _bogus, str(_bogus))
    # The content-thin family is the one that actually fails on the sites this
    # tool is pointed at, so it is named explicitly rather than counted.
    for _cid in ("ONP-10", "ONP-13"):
        check(f"{_cid} (thin content) can be photographed",
              _cid in _SEL or _cid in _PL)
    check("the eligible set is not a handful",
          len(set(_SEL) | set(_PL)) >= 20,
          str(len(set(_SEL) | set(_PL))))

    print("\nA LONG PHASE KEEPS TALKING")
    import types
    from app import worker as _w

    _beats, _captured = [], []

    class _Art:
        start_url = f"http://localhost:{FIXTURE_PORT}/"
        quality = types.SimpleNamespace(degenerate=False, likely_cause="",
                                        signals=[])
        truncated = False
        pages = {}

        def to_json(self):
            return "{}"

    def _fake_capture(url, sel=None):
        _captured.append(url)
        return _png(20, 20, MARK_RGB)

    _real = {"cap": _w.screenshots.capture, "ok": _w.screenshots.available,
             "pick": _w.screenshots.pick_targets, "put": _w.put_artifact,
             "save": _w.db.save_findings, "cat": _w.db.catalog,
             "upd": _w.db.update_audit}
    try:
        _w.screenshots.capture = _fake_capture
        _w.screenshots.available = lambda: True
        _w.screenshots.pick_targets = lambda *a, **k: [
            (f"TECH-0{i}", f"http://localhost:{FIXTURE_PORT}/", ".x", "c")
            for i in (1, 2, 3)]
        _w.put_artifact = lambda *a, **k: None
        _w.db.save_findings = lambda *a, **k: None
        _w.db.catalog = lambda *a, **k: {}
        _w.db.update_audit = lambda *a, **k: None

        def _step(status, progress):
            _beats.append(progress)

        _ex = {}
        _w._score_and_save({"id": "T1", "target_url": _Art.start_url,
                            "client_name": "T"},
                           {"skip_collectors": True, "skip_judgment": True},
                           "T1", _Art(), {}, _ex, _step)
        check("every capture stamps its own heartbeat", len(_beats) >= 4,
              f"{len(_beats)} beat(s): {_beats[:5]}")
        check("and the message actually changes",
              len(set(_beats)) >= 4, str(set(_beats)))
        check("all four shots still taken", len(_captured) == 4,
              str(len(_captured)))

        # Stop, landing mid-phase rather than at the end of it.
        _beats.clear(); _captured.clear()
        _n = {"i": 0}

        def _stepc(status, progress):
            _beats.append(progress)
            _n["i"] += 1
            if _n["i"] == 3:
                raise _w.Cancelled()

        try:
            _w._score_and_save({"id": "T2", "target_url": _Art.start_url,
                                "client_name": "T"},
                               {"skip_collectors": True, "skip_judgment": True},
                               "T2", _Art(), {}, {}, _stepc)
            check("Stop lands inside the screenshot phase", False, "not raised")
        except _w.Cancelled:
            check("Stop lands inside the screenshot phase", True)
            check("and it stops early, not after every shot",
                  len(_captured) < 4, f"{len(_captured)} captured")

        # The budget: a capture that hangs must cost pictures, not the report.
        _captured.clear()
        os.environ["SHOT_BUDGET_S"] = "0.4"

        def _slow(url, sel=None):
            _captured.append(url)
            time.sleep(0.5)
            return _png(20, 20, MARK_RGB)

        _w.screenshots.capture = _slow
        _ex2 = {}
        _w._score_and_save({"id": "T3", "target_url": _Art.start_url,
                            "client_name": "T"},
                           {"skip_collectors": True, "skip_judgment": True},
                           "T3", _Art(), {}, _ex2, lambda s, p: None)
        check("a slow browser costs pictures, not the run",
              len(_captured) < 4, f"{len(_captured)} captured before the budget")
        check("and whatever was captured is kept",
              len(_ex2.get("screenshots") or []) >= 1,
              str(len(_ex2.get("screenshots") or [])))
    finally:
        os.environ.pop("SHOT_BUDGET_S", None)
        _w.screenshots.capture = _real["cap"]
        _w.screenshots.available = _real["ok"]
        _w.screenshots.pick_targets = _real["pick"]
        _w.put_artifact = _real["put"]
        _w.db.save_findings = _real["save"]
        _w.db.catalog = _real["cat"]
        _w.db.update_audit = _real["upd"]

    print("\n" + "=" * 68)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — browser capture is equivalent to a server crawl")
    print("=" * 68 + "\n")
    stop_server(httpd)
    return 1 if FAILURES else 0

if __name__ == "__main__":
    sys.exit(main())
