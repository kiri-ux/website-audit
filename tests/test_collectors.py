"""
Contract test for the credential-gated collectors and the judgment layer.

The rule every one of them must honor: with no credentials configured, return
Need Access at confidence 0 — NEVER a Fail. "The client hasn't granted access"
and "your backlink profile is weak" are different sentences, and only one of
them is true when there's no API key.

Also asserts the PDF renders and the executive summary is derived from scored
findings rather than invented.
"""
import os, sys, threading, functools, http.server, socketserver, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AHREFS_API_KEY",
          "SEMRUSH_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
          "GOOGLE_TOKENS", "DFS_LOGIN", "DFS_PASSWORD"):
    os.environ.pop(k, None)
os.environ.setdefault("DATABASE_URL", "sqlite:///data/test_collectors.db")

from engine.crawler import Crawler
from engine import checks, scoring
from engine.judgment import run_judgment, CHECKPOINT_IDS
from engine.collectors import collect_gsc, collect_ga4, collect_backlinks, \
    collect_rankings, collect_lighthouse, capture_screenshot, dataforseo, \
    GSC_IDS, GA4_IDS, OFF_IDS
from engine.summarise import build_summary
from engine.pdf_report import build_pdf
from engine.report import render_html

PORT = 8092
FAILURES = []
def check(l, c, d=""):
    print(f"  {'PASS' if c else 'FAIL'}  {l}" + (f"  ({d})" if d else ""))
    if not c: FAILURES.append(l)


def _analytics_misconfig_checks():
    """
    The three ways Search Console / GA4 come back empty must be tellable apart.

    Only ONE of them is the client's to fix. The other two are ours, and the
    message used to blame the client for both: with GOOGLE_TOKENS set but no
    client id/secret on the worker, every row read "no Vici login has access to
    this property" — which would have been read out loud on a client call.
    """
    import os
    from engine.collectors import analytics as A
    saved = {k: os.environ.get(k) for k in
             ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_TOKENS")}
    try:
        for k in saved:
            os.environ.pop(k, None)
        r = A.collect_gsc("https://x.test/")
        check("nothing configured reads as not configured",
              r["GSC-01"]["source"] == "gsc"
              and "not configured" in r["GSC-01"]["evidence"],
              r["GSC-01"]["evidence"][:70])

        os.environ["GOOGLE_TOKENS"] = '{"reporting-zone":"1//fake"}'
        r = A.collect_gsc("https://x.test/")
        check("tokens without client credentials is named as OUR mistake",
              r["GSC-01"]["source"] == "gsc_misconfigured", r["GSC-01"]["source"])
        check("and does not accuse the client of a missing grant",
              "add a Vici login" not in r["GSC-01"]["evidence"])
        check("GA4 says the same thing rather than something different",
              A.collect_ga4(None, None, site_url="https://x.test/"
                            )["GA4-01"]["source"] == "ga4_misconfigured")

        os.environ["GOOGLE_CLIENT_ID"] = "cid"
        os.environ["GOOGLE_CLIENT_SECRET"] = "sec"
        r = A.collect_gsc("https://x.test/")
        check("fully configured but unauthorised IS the client's grant",
              r["GSC-01"]["source"] == "gsc"
              and "add a Vici login" in r["GSC-01"]["evidence"],
              r["GSC-01"]["evidence"][:70])
        check("and it names which logins were tried",
              "reporting-zone" in r["GSC-01"]["evidence"])
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def main():
    print("\nSEARCH CONSOLE / GA4 FAILURE STATES ARE DISTINGUISHABLE")
    _analytics_misconfig_checks()
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "fixture", "site")
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("0.0.0.0", PORT),
                                   functools.partial(Quiet, directory=root))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.6)

    art = Crawler(f"http://localhost:{PORT}/", max_pages=40, delay=0.01,
                  verbose=False).crawl()
    F = checks.run_all(art, {"skip_psi": True})
    base = len(F)

    print("\nDEGRADATION CONTRACT — no credentials configured")
    j = run_judgment(art, "ecommerce", "Test Client")
    g = collect_gsc("https://example.com/", None)
    a4 = collect_ga4(None, None)
    b = collect_backlinks("example.com")

    # SEARCH CONSOLE OWES TWO ROWS UNDER ANOTHER PREFIX.
    #
    # TECH-29 (sitemap submitted) and TECH-35 (index coverage) are answered
    # ONLY by this collector - they have no check of their own - so on a run
    # with no Search Console connection nobody wrote them at all. A checkpoint
    # with no row has no evidence to quote, so the internal panel fell back to
    # its generic "produced no result for this run" and filed two rows under
    # "ours to fix" on an audit whose operator had already connected Search
    # Console successfully. Unanswered has to be SAID, not left blank.
    from engine.collectors.analytics import _GSC_UNANSWERED_IDS
    gsc_expected = list(GSC_IDS) + list(_GSC_UNANSWERED_IDS)

    for name, block, ids in (("judgment layer", j, CHECKPOINT_IDS),
                             ("Search Console", g, gsc_expected),
                             ("GA4", a4, GA4_IDS),
                             ("backlinks", b, OFF_IDS)):
        check(f"{name} returns all {len(ids)} checkpoints", len(block) == len(ids),
              f"{len(block)}")
        fails = [c for c, f in block.items() if f["status"] == "Fail"]
        check(f"{name} emits ZERO Fail findings without credentials",
              not fails, str(fails[:5]))
        check(f"{name} uses Need Access", 
              all(f["status"] == "Need Access" for f in block.values()),
              str({f["status"] for f in block.values()}))
        check(f"{name} carries confidence 0",
              all(f["confidence"] == 0.0 for f in block.values()))
        check(f"{name} states what is needed",
              all(f["recommendation"] or f["evidence"] for f in block.values()))

    F.update(j); F.update(g); F.update(a4); F.update(b)
    cat = scoring.load_catalog("seed/checkpoints.csv")
    print("\nCOVERAGE")
    # 113 = 44 judgment (E-E-A-T, AI Search, on-page) + 22 GSC + 2 GSC rows
    # that live under TECH + 16 GA4 + 29 backlinks. This is asserted exactly,
    # and on purpose: the number only moves when a collector's row set changes,
    # and that is precisely the change worth being made to look at. It moved
    # from 111 when the two TECH rows stopped being silently omitted - see the
    # note on gsc_expected above.
    check("coverage grew by 113 checkpoints", len(F) == base + 113,
          f"{base} -> {len(F)}")
    check("coverage is over 80% of the template", len(F) / len(cat) > 0.8,
          f"{len(F)}/{len(cat)} = {100*len(F)//len(cat)}%")

    print("\nSCORING NOT DISTORTED BY UNCONFIGURED COLLECTORS")
    sc = scoring.score(F, cat, "ecommerce")
    for sec in ("GSC", "GA4", "OFF"):
        v = sc["sections"].get(sec, {})
        check(f"{sec} section is Not Assessed, not scored low",
              v.get("score") is None, f"score={v.get('score')}")

    print("\nEXECUTIVE SUMMARY")
    meta = {"client": "Test Client", "vertical": "ecommerce",
            "pages_crawled": len(art.pages), "url": f"http://localhost:{PORT}/",
            "coverage": f"{len(F)}/{len(cat)}", "generated": "2026-08-18 14:00"}
    s = build_summary(F, sc, cat, meta)
    check("summary has an overview", bool(s["overview"]))
    check("summary lists priority issues", len(s["issues"]) > 0, str(len(s["issues"])))
    check("summary builds a phased roadmap", len(s["roadmap"]) > 0,
          str([p["phase"] for p in s["roadmap"]]))
    check("summary is deterministic without an LLM key",
          s["generated_by"] == "deterministic", s["generated_by"])
    check("no acronym mangling in section names",
          "E-e-a-t" not in str(s) and "Https" not in str(s))
    # every issue in the summary must exist in the findings
    ids_in_cat = {cat[c]["checkpoint"] for c in F if c in cat}
    orphaned = [i for i in s["issues"]
                if not any(i.startswith(n) for n in ids_in_cat)]
    check("every summary issue traces to a real checkpoint", not orphaned,
          str(orphaned[:2]))

    print("\nDATAFORSEO — UNCONFIGURED DEGRADATION")
    check("dataforseo reports itself unconfigured", not dataforseo.configured())
    lh = collect_lighthouse("https://example.com/")
    check("Lighthouse returns Need Access, never Fail",
          all(f["status"] == "Need Access" for f in lh.values()),
          str({f["status"] for f in lh.values()}))
    check("Lighthouse rows carry confidence 0",
          all(f["confidence"] == 0.0 for f in lh.values()))
    rk_off = collect_rankings("example.com")
    check("rankings report unavailable rather than an empty table",
          rk_off["available"] is False and rk_off["rows"] == [],
          rk_off.get("reason", ""))
    check("screenshot returns None without credentials",
          capture_screenshot("https://example.com/") is None)
    check("backlinks fall back to the Ahrefs/Semrush adapter when DFS is absent",
          all(f["status"] == "Need Access" for f in collect_backlinks("example.com").values()))

    print("\nPROPERTY MATCHING — SCHEME, WWW AND DISPLAY NAMES")
    # Both of these shipped and both produced the same false statement: "no
    # Vici login has access to this property" about properties we could read.
    from engine.collectors.analytics import _candidates, _squash, _host
    cands = _candidates("http://ootenlawfirm.com/")
    check("an http audit URL matches the https property that holds the data",
          "https://ootenlawfirm.com" in cands, str(sorted(cands)))
    check("www and non-www are the same site for this purpose",
          "https://www.ootenlawfirm.com" in cands)
    check("a domain property matches too",
          "sc-domain:ootenlawfirm.com" in cands)
    check("a different site does NOT match",
          "https://junkbeegone.biz" not in cands)
    # The GA4 ordering heuristic compared a domain slug against a display name
    # with spaces in it, so nothing was ever "likely" and the scan cap decided
    # the outcome on a login holding hundreds of properties.
    slug = _squash(_host("http://ootenlawfirm.com/").split(".")[0])
    check("a display name with spaces matches its domain slug",
          slug in _squash("Ooten Law Firm"), f"{slug} vs ooten law firm")
    check("an unrelated client is not dragged in",
          slug not in _squash("Orme's Gym, LLC"))

    print("\nA MEASUREMENT IS NOT A PASS")
    # Off-Page scored 94/100 EXCELLENT for a firm with 131 referring domains,
    # because thirteen retrieved numbers were each recorded as Pass. There is
    # no number of backlinks that is correct; a count cannot pass or fail.
    from engine import scoring as _sc
    check("Info is excluded from scoring, like N/A",
          "Info" in _sc.EXCLUDED, str(sorted(_sc.EXCLUDED)))
    cat_off = {f"OFF-{i:02d}": {"prefix": "OFF", "checkpoint": f"c{i}"}
               for i in range(1, 30)}
    def _row(st):
        return {"status": st, "severity": "Low", "value": {}, "evidence": "n",
                "affected_pages": [], "recommendation": "", "confidence": 1.0,
                "source": "dataforseo"}
    only_counts = {c: _row("Info") for c in list(cat_off)[:13]}
    only_counts.update({c: _row("Need Access") for c in list(cat_off)[13:]})
    v = _sc.score(only_counts, cat_off)["sections"]["OFF"]
    check("a section of pure measurements is Not Assessed, never Excellent",
          v["score"] is None, f"{v['score']} {v['rating']}")

    print("\nWRONG DATA UNDER A CONFIDENT LABEL IS THE WORST OUTCOME")
    # "Lost backlinks" printed the nofollow percentage and "New backlinks"
    # printed a count of broken OUTBOUND pages. Both looked authoritative.
    src_txt = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "engine", "collectors",
        "dataforseo.py")).read()
    for cid in ("OFF-10", "OFF-11", "OFF-19", "OFF-20"):
        check(f"{cid} is declared unmapped rather than given a stand-in",
              f'unmapped("{cid}"' in src_txt)

    print("\nAN OPERATOR-CHOSEN PROPERTY OVERRIDES THE MATCHER")
    # The whole point of the dropdown is the case the matcher gets wrong, so a
    # hand-picked property must not be quietly re-derived from the domain.
    import inspect
    from engine.collectors import analytics as _A
    check("collect_gsc accepts a chosen property",
          "property_url" in inspect.signature(_A.collect_gsc).parameters)
    check("collect_ga4 accepts a chosen property id",
          "property_id" in inspect.signature(_A.collect_ga4).parameters)
    check("listing properties never raises without credentials",
          isinstance(_A.list_properties(max_age=0), dict))
    lp = _A.list_properties(max_age=0)
    check("an unconfigured list is empty rather than an error",
          lp["gsc"] == [] and lp["ga4"] == [], str(lp)[:80])

    print("\nMULTI-LOGIN TOKEN INDEX")
    os.environ["GOOGLE_TOKENS"] = '{"vici-1":"x","vici-2":"y"}'
    # Client credentials too: without them the collector now (correctly) reports
    # OUR misconfiguration instead of walking the logins, which is a different
    # code path from the one this block is about.
    os.environ["GOOGLE_CLIENT_ID"] = "cid"
    os.environ["GOOGLE_CLIENT_SECRET"] = "sec"
    g2 = collect_gsc("https://example.com/", None)
    a42 = collect_ga4(None, None, site_url="https://example.com/")
    check("GSC still degrades to Need Access when no login can see the property",
          all(f["status"] == "Need Access" for f in g2.values()))
    check("GSC says how many logins were tried, so the failure is actionable",
          "tried 2 login(s)" in g2["GSC-01"]["evidence"], g2["GSC-01"]["evidence"][:90])
    check("GA4 degrades to Need Access and names the bounded scan",
          all(f["status"] == "Need Access" for f in a42.values())
          and "properties per login" in a42["GA4-01"]["evidence"],
          a42["GA4-01"]["evidence"][:90])
    for _k in ("GOOGLE_TOKENS", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        os.environ.pop(_k, None)

    print("\nKEYWORD RANKINGS SECTION")
    meta_rk = dict(meta)
    meta_rk["extras"] = {"rankings": {
        "available": True, "total": 3, "top10": 2, "location": "United States",
        "rows": [{"keyword": "grand furniture roanoke", "search_volume": 2400,
                  "difficulty": 12, "position": 1,
                  "url": "https://example.com/roanoke"},
                 {"keyword": "sofas near me", "search_volume": 18100,
                  "difficulty": 61, "position": 7, "url": "https://example.com/sofas"},
                 {"keyword": "cheap mattress", "search_volume": None,
                  "difficulty": None, "position": 34, "url": ""}]}}
    html_rk = render_html(meta_rk, sc, F, cat, s)
    check("HTML report renders the rankings table",
          "Keyword rankings" in html_rk and "grand furniture roanoke" in html_rk)
    check("rows with missing volume/difficulty still render all five cells",
          "cheap mattress" in html_rk)
    check("page-one positions are emphasized", "<b>1</b>" in html_rk)
    html_no = render_html(meta, sc, F, cat, s)
    check("no rankings data -> section omitted entirely, not shown empty",
          "Keyword rankings" not in html_no)
    meta_un = dict(meta)
    meta_un["extras"] = {"rankings": {"available": False, "reason": "not configured",
                                      "rows": []}}
    html_un = render_html(meta_un, sc, F, cat, s)
    check("unavailable rankings say why rather than estimating",
          "omitted rather than estimated" in html_un)
    pdf_rk = build_pdf(meta_rk, sc, F, cat, s)
    check("PDF renders with the rankings section", pdf_rk[:4] == b"%PDF",
          f"{len(pdf_rk)//1024}KB")

    print("\nPDF DELIVERABLE")
    pdf = build_pdf(meta, sc, F, cat, s)
    check("PDF renders", pdf[:4] == b"%PDF", f"{len(pdf)//1024}KB")
    try:
        from pypdf import PdfReader
        import io
        n = len(PdfReader(io.BytesIO(pdf)).pages)
        check("PDF is multi-page", n >= 5, f"{n} pages")
    except Exception as e:
        check("PDF parseable", False, str(e))

    print("\nA SLOW PHASE IS NOT A DEAD WORKER")
    # THE BUG THE STATUS PAGE SURFACED: the collectors stamped one progress
    # line before them and the next one after ALL of them. URL Inspection is
    # up to 25 calls at a 45-second timeout, so a Search Console pass working
    # perfectly could run fifteen minutes in silence — and the status page,
    # which calls a run dead when the heartbeat is ten minutes old, told the
    # operator their worker had been recycled. On a run that was fine.
    #
    # A stall detector is only as good as the heartbeat it watches.
    import time as _t2
    import engine.collectors.analytics as _A
    _real_api, _real_budget = _A._api, _A.GSC_INSPECT_BUDGET_S
    _A.GSC_INSPECT_BUDGET_S = 1
    _beats = []

    def _slow(url, tok, payload=None, timeout=60):
        _t2.sleep(0.35)
        return {"inspectionResult": {"indexStatusResult": {
            "verdict": "PASS", "coverageState": "Submitted and indexed"}}}

    _A._api = _slow
    try:
        _urls = [f"https://x.test/{i}" for i in range(10)]
        _blocks, _failed, _skipped = _A._inspect(
            "https://x.test/", "tok", _urls,
            progress=lambda d, t: _beats.append((d, t)))
    finally:
        _A._api, _A.GSC_INSPECT_BUDGET_S = _real_api, _real_budget
    check("the inspection loop reports progress per URL",
          len(_beats) == len(_blocks) and _beats[0] == (0, 10), str(_beats[:2]))
    check("and the worker is wired to that callback",
          "progress=_beat" in __import__("inspect").getsource(
              __import__("app.worker", fromlist=["x"])._after_crawl))

    print("\nAND A CAPPED SAMPLE SAYS WHAT IT DROPPED")
    # Stopping early is right — these rows are a SAMPLE, and twelve answers
    # the same question as twenty-five. Stopping early while implying the
    # sample was complete is the failure this codebase keeps finding.
    check("the budget stops the loop", _skipped > 0 and len(_blocks) < 10,
          f"{len(_blocks)} done, {_skipped} skipped")
    _rows = _A._coverage_rows(_blocks, _failed, 118, _skipped)
    check("and the checkpoint says how many were not reached",
          "not reached before the inspection time budget" in
          _rows["GSC-05"]["evidence"], _rows["GSC-05"]["evidence"][-70:])
    check("with the count, not just the fact",
          f"{_skipped} more" in _rows["GSC-05"]["evidence"])

    print("\nA GOOGLE REDIRECT WRAPPER IS NOT THE CLIENT'S URL")
    # Google serves some result links as google.com/goto/... wrappers. Our
    # vendor resolves them for essentially all organic results, but the one
    # place we read a result URL counts SLASHES in it to decide whether a
    # ranking sits on an interior page — and a wrapper has plenty of slashes
    # belonging to Google. It would not fail loudly; it would quietly inflate
    # a percentage in a checkpoint.
    from engine.collectors.dataforseo import _is_goto, _serp_feature_rows
    check("a goto wrapper is recognized",
          _is_goto("https://www.google.com/goto/aHR0cHM6Ly9l/x"))
    check("so is the older /url? redirect",
          _is_goto("https://www.google.com/url?q=https://x.com"))
    check("a real destination URL is not",
          not _is_goto("https://belmontpark.com/tickets/season-passes"))
    check("and a missing URL is not an error", not _is_goto(None))
    _lt = [{"keyword": "a b c d", "position": 3, "search_volume": 10,
            "url": "https://x.com/a/b/c", "serp_type": "organic"},
           {"keyword": "e f g h", "position": 4, "search_volume": 10,
            "url": "https://www.google.com/goto/xyz/1/2",
            "serp_type": "organic"},
           {"keyword": "i j k l", "position": 5, "search_volume": 10,
            "url": "https://x.com/", "serp_type": "organic"}]
    _v = _serp_feature_rows(_lt)["GEO-25"]["value"]
    check("an unresolved wrapper leaves the numerator",
          _v["on_deep_pages"] == 1, str(_v))
    check("AND the denominator — it is unreadable, not shallow",
          _v["longtail_ranked"] == 2, str(_v))
    check("so the percentage is over rows we could actually classify",
          _v["pct"] == 50.0, str(_v["pct"]))

    print("\nWE READ NONE OF THE FIELDS DATAFORSEO IS REMOVING")
    # The six legacy booleans go away on 2027-01-20. Asserted rather than
    # remembered, because the day one of them gets used is the day this
    # becomes a deadline.
    import pathlib as _pl
    _GONE = ("is_image", "is_video", "is_featured_snippet", "is_malicious",
             "is_web_story", "amp_version")
    _hits = []
    for _f2 in _pl.Path(".").glob("engine/**/*.py"):
        _txt = _f2.read_text()
        _hits += [f"{_f2}:{_k}" for _k in _GONE if f'"{_k}"' in _txt
                  or f"'{_k}'" in _txt]
    for _f2 in _pl.Path(".").glob("app/*.py"):
        _txt = _f2.read_text()
        _hits += [f"{_f2}:{_k}" for _k in _GONE if f'"{_k}"' in _txt
                  or f"'{_k}'" in _txt]
    check("no removed boolean is read anywhere in the engine or app",
          not _hits, "; ".join(_hits))

    print("\n" + "=" * 68)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — collectors degrade honestly; PDF ships")
    print("=" * 68 + "\n")
    httpd.shutdown()
    return 1 if FAILURES else 0

if __name__ == "__main__":
    sys.exit(main())
