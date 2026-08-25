"""
The consent scanner, folded into the audit.

WHY IT IS VENDORED RATHER THAN REIMPLEMENTED
--------------------------------------------
The hard part of consent scanning is not the idea. It is fourteen CMP
signatures, an accept-click that survives iframe banners, and knowing that a
Google endpoint carrying a denied-state `gcs=` parameter before consent is an
expected cookieless ping rather than a violation. That knowledge accumulated in
one codebase over many versions. A second implementation would be a second thing
to keep correct, and the two would drift on exactly the cases that matter.

So `engine/consent/` is the standalone scanner with its imports made relative,
and `checks.py` is the only new code: an adapter that turns one scan result into
nine checkpoints and states what it says.

WHAT THIS FILE GUARDS
---------------------
  1. A basic scan — raw HTML, no browser — must NOT pass the rows it cannot
     see. "No tracking before consent: Pass" off an HTML fetch would be a clean
     bill of health for a question nobody asked.
  2. A scan that fails leaves nine rows honestly unanswered and the audit
     otherwise intact.
  3. The scanner's own severity classification is respected: it already
     separates a real pre-consent fire from an expected denied-state ping, and
     the adapter must not re-decide that by counting rows.
  4. A consent failure is a LEGAL exposure. The severities are higher than an
     SEO reader expects, and that is correct.
"""
from __future__ import annotations
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILED: list[str] = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILED.append(label)


FULL_CLEAN = {
    "mode": "full", "ok": True, "error": None,
    "cmps": [{"name": "OneTrust", "gtm_event": "OneTrustGroupsUpdated"}],
    "gtm": {"found": True, "container_ids": ["GTM-ABC123"]},
    "banner_visible": True,
    "consent_mode_default": True,
    "consent_defaults": {"ad_storage": "denied", "analytics_storage": "denied"},
    "pre_consent": [],
    "reject_tested": True, "post_reject": [],
    "gpc_tested": True, "gpc_fires": [],
    "optout_link": "Do Not Sell or Share My Personal Information",
    "state_checks": [{"state": "CA", "check": "Opt-out link", "status": "pass"}],
}


def main():
    from engine.consent.checks import findings_from_scan, CONS_IDS

    print("A CLEAN FULL SCAN ANSWERS ALL NINE")
    ok = findings_from_scan(FULL_CLEAN)
    check("nine checkpoints, no more and no fewer",
          sorted(ok) == sorted(CONS_IDS), str(len(ok)))
    unanswered = [k for k, v in ok.items() if v["status"] == "Need Access"]
    check("nothing is left unanswered", not unanswered, str(unanswered))
    check("the CMP is named", "OneTrust" in ok["CONS-01"]["evidence"])
    check("the GTM trigger event is named, because that is what you gate on",
          "OneTrustGroupsUpdated" in ok["CONS-09"]["evidence"])

    print("\nA BASIC SCAN MUST NOT PASS WHAT IT CANNOT SEE")
    # This is the whole reason the adapter reads `mode`. Raw HTML detects most
    # CMPs and nothing else — it cannot see the banner, Consent Mode, or what
    # fired. Passing those rows would be a clean bill of health for a question
    # that was never asked.
    basic = dict(FULL_CLEAN, mode="basic")
    b = findings_from_scan(basic)
    for cid in ("CONS-02", "CONS-03", "CONS-04", "CONS-05", "CONS-06"):
        check(f"{cid} is unanswered in basic mode",
              b[cid]["status"] == "Need Access", b[cid]["status"])
    check("and says why, in terms of the mode",
          "no browser" in b["CONS-02"]["evidence"])
    # The rows that ARE answerable from HTML must still answer.
    check("the CMP is still detected without a browser",
          b["CONS-01"]["status"] == "Pass")
    check("so is the opt-out link", b["CONS-07"]["status"] == "Pass")

    print("\nTHE SCANNER'S OWN CLASSIFICATION IS RESPECTED")
    # A Google request before consent carrying a denied gcs= flag is expected,
    # not a violation, and the scanner already marks it informational. Counting
    # rows instead of reading severity would report every Consent Mode site as
    # failing.
    pings = dict(FULL_CLEAN, pre_consent=[
        {"vendor": "Google", "url": "https://google.com/x?gcs=G100",
         "severity": "info"}])
    check("expected cookieless pings are not a failure",
          findings_from_scan(pings)["CONS-04"]["status"] == "Pass")
    real = dict(FULL_CLEAN, pre_consent=[
        {"vendor": "Meta Pixel", "url": "https://facebook.com/tr",
         "severity": "high"},
        {"vendor": "Google", "url": "https://google.com/x?gcs=G100",
         "severity": "info"}])
    r = findings_from_scan(real)
    check("a real pre-consent fire is a Critical failure",
          r["CONS-04"]["status"] == "Fail"
          and r["CONS-04"]["severity"] == "Critical")
    check("and it counts only the real ones",
          r["CONS-04"]["value"]["pre_consent"] == 1,
          str(r["CONS-04"]["value"]))
    # THE NAME IS OURS, NOT THE CLIENT'S. Printing "Beeswax, DoubleClick /
    # Floodlight, The Trade Desk, Yahoo, xAd/GroundTruth" in a client PDF
    # hands over the buying platforms we use. The count is the finding; the
    # names stay in `value` for the internal panel and the consent dashboard.
    check("the vendor names are kept as structured evidence",
          "Meta Pixel" in (r["CONS-04"]["value"].get("vendors") or []),
          str(r["CONS-04"]["value"].get("vendors")))
    check("but the client-facing sentence does not list them",
          "Meta Pixel" not in r["CONS-04"]["evidence"],
          r["CONS-04"]["evidence"])
    check("it says how many marketing pixels fired instead",
          "marketing pixel" in r["CONS-04"]["evidence"],
          r["CONS-04"]["evidence"])

    print("\nTHE SEVERITIES MATCH THE STAKES")
    # These are legal exposures, not ranking ones. An installed banner that
    # never appears, a reject button that changes nothing, and a GPC signal
    # ignored are each worse than anything in the SEO half of this report.
    for cid, scan in (
        ("CONS-02", dict(FULL_CLEAN, banner_visible=False)),
        ("CONS-05", dict(FULL_CLEAN, post_reject=[{"vendor": "Meta Pixel"}])),
        ("CONS-06", dict(FULL_CLEAN, gpc_fires=[{"vendor": "The Trade Desk"}])),
    ):
        f = findings_from_scan(scan)[cid]
        check(f"{cid} failing is Critical",
              f["status"] == "Fail" and f["severity"] == "Critical",
              f"{f['status']}/{f['severity']}")
    check("a reject button that changes nothing is called out as worse than none",
          "worse than none" in
          findings_from_scan(dict(FULL_CLEAN,
                                  post_reject=[{"vendor": "x"}]))["CONS-05"]["recommendation"])

    print("\nA SCAN THAT DID NOT COMPLETE LEAVES THE AUDIT INTACT")
    for scan, why in ((None, "the phase did not run"),
                      ({"error": "Chromium crashed"}, "the scan errored")):
        rows = findings_from_scan(scan)
        check(f"nine rows when {why}", sorted(rows) == sorted(CONS_IDS))
        check(f"none of them is a Fail when {why}",
              not [k for k, v in rows.items() if v["status"] == "Fail"])
        check(f"and confidence is zero when {why}",
              all(v["confidence"] == 0.0 for v in rows.values()))
    check("the error text is carried through, not swallowed",
          "Chromium crashed" in
          findings_from_scan({"error": "Chromium crashed"})["CONS-01"]["evidence"])

    print("\nNO CMP IS A WARNING, NOT A VERDICT")
    # A custom-built banner with no known signature lands here too, which is why
    # this asks someone to look rather than declaring the site non-compliant.
    none = findings_from_scan(dict(FULL_CLEAN, cmps=[]))
    check("no recognized CMP is a Warning", none["CONS-01"]["status"] == "Warning")
    check("and it says a custom banner would look the same",
          "custom-built" in none["CONS-01"]["evidence"])

    print("\nTHE ROWS ARE WIRED INTO THE AUDIT")
    from engine.access import blocked_on
    from engine.report import SECTION_NAMES, ORDER
    from engine import scoring
    cat = scoring.load_catalog("seed/checkpoints.csv")
    check("all nine are in the catalog",
          all(c in cat for c in CONS_IDS),
          str([c for c in CONS_IDS if c not in cat]))
    check("the section has a name", SECTION_NAMES.get("CONS") == "Consent & Privacy")
    check("and a place in the order", "CONS" in ORDER)
    # An unanswered consent row is ours — a phase we did not run or a browser we
    # did not have. It must never read as the client's homework.
    check("an unanswered consent row is ours, not the client's",
          all(blocked_on(c) == "vendor" for c in CONS_IDS))

    print("\nTHE EXTENSION PATH USES THE SAME CLASSIFIER")
    # Two classifiers would eventually disagree about the same site with no way
    # to tell which was right. The extension records; the server classifies,
    # with the tables the Playwright path uses.
    from engine.consent.from_capture import result_from_capture
    cap = {
        "url": "https://x.com",
        "html": ('<html><script src="https://cdn.cookielaw.org/otSDKStub.js">'
                 '</script><script src="https://www.googletagmanager.com/'
                 'gtm.js?id=GTM-ABC123"></script>'
                 '<a href="/p">Do Not Sell My Personal Information</a></html>'),
        "scripts": ["https://cdn.cookielaw.org/otSDKStub.js"],
        "pre_requests": ["https://www.facebook.com/tr?id=1",
                         "https://www.google-analytics.com/g/collect?gcs=G100"],
        "post_requests": ["https://www.facebook.com/tr?id=1",
                          "https://analytics.twitter.com/i/adsct"],
        "reject_requests": ["https://www.google-analytics.com/g/collect?gcs=G100"],
        "gpc_requests": [],
        "banner_visible": True, "consent_defaults": {"ad_storage": "denied"},
        "consent_defaults_read": True,
        "accept_clicked": True, "reject_clicked": True,
    }
    cr = result_from_capture(cap)
    check("a browser capture reports as a full scan, not a basic one",
          cr["mode"] == "full", cr["mode"])
    check("the CMP is found from the same signature table",
          [c["name"] for c in cr["cmps"]] == ["OneTrust"])
    check("and the GTM container", cr["gtm"]["container_ids"] == ["GTM-ABC123"])
    # The gcs= rule has to hold on this path too, or every Consent Mode site
    # captured by extension reports as failing.
    sev = {f["vendor"]: f["severity"] for f in cr["pre_consent"]}
    check("a denied-state Google ping is informational here as well",
          sev.get("Google Analytics 4") == "info", str(sev))
    check("and a Meta Pixel before consent is not",
          sev.get("Meta Pixel") == "high", str(sev))
    check("a cookieless ping after Reject is not counted as a violation",
          cr["post_reject"] == [], str(cr["post_reject"]))
    check("vendors that fired only after Accept are recorded as gated",
          cr["post_consent"] == ["X / Twitter Pixel"], str(cr["post_consent"]))

    ext = findings_from_scan(cr)
    check("and the nine rows come out the same shape",
          sorted(ext) == sorted(CONS_IDS))
    check("with the browser-only rows answered",
          all(ext[c]["status"] != "Need Access"
              for c in ("CONS-02", "CONS-03", "CONS-04", "CONS-05")),
          str({c: ext[c]["status"] for c in ("CONS-02", "CONS-03", "CONS-04",
                                             "CONS-05")}))

    from app.ui_consent import consent_html as _ch
    print("\nONE FAILED GOOGLE CALL TAKES OUT NINE ROWS — AND HAS A BUTTON")
    # Nine checkpoints read one Lighthouse report. When PageSpeed refuses the
    # server the whole section comes back Need Access, and the fix used to be
    # "run the audit again and hope". The browser reaches the same endpoint.
    from engine.checks.perf import findings_from_psi, PSI_CHECK_IDS
    _lh = {"lighthouseResult": {"audits": {
        "largest-contentful-paint": {"numericValue": 3100, "displayValue": "3.1 s"},
        "cumulative-layout-shift": {"numericValue": 0.04, "displayValue": "0.04"},
        "server-response-time": {"numericValue": 420, "displayValue": "420 ms"},
        "uses-text-compression": {"score": 1, "details": {"items": []}},
        "unminified-javascript": {"score": 1, "details": {"items": []}},
        "unminified-css": {"score": 1, "details": {"items": []}},
        "total-byte-weight": {"numericValue": 1500000, "details": {"items": []}},
        "interactive": {"numericValue": 4200, "displayValue": "4.2 s"},
        "resource-summary": {"details": {"items": []}}},
        "categories": {"performance": {"score": 0.62}}}}
    _pf = findings_from_psi("https://x.com/", _lh)
    check("a browser-fetched report answers every row that reads it",
          set(_pf) == set(PSI_CHECK_IDS), str(sorted(set(PSI_CHECK_IDS) - set(_pf))))
    check("and none of them is left as Need Access",
          not [c for c, f in _pf.items() if f["status"] == "Need Access"],
          str([c for c, f in _pf.items() if f["status"] == "Need Access"]))
    check("the browser grades nothing — the server does",
          _pf["PERF-11"]["status"] == "Warning", _pf["PERF-11"]["status"])
    check("a reply with no report fills nothing rather than guessing",
          findings_from_psi("https://x.com/", {"error": "429"}) == {})

    # The panel that lists the nine must offer the fix, not just name it.
    from engine.report import _todo_panel, extension_link
    _cat = {c: {"section": "PERF", "title": c} for c in PSI_CHECK_IDS}
    _nf = {c: {"status": "Need Access", "confidence": 0.0, "source": "perf",
               "evidence": "the speed-testing service did not respond",
               "value": {"internal": True}} for c in PSI_CHECK_IDS}
    _panel = "".join(_todo_panel(_nf, _cat,
                                 {"audit_id": "abc123", "url": "https://x.com/",
                                  "extras": {}}))
    check("the internal panel offers the speed test", "vici-fix" in _panel)
    check("and links straight into the extension when the button is missing",
          "chrome-extension://" in _panel)
    check("the extension id is pinned, or no link could exist",
          "key" in json.load(open("extension/manifest.json")))
    check("and the popup is reachable from a page",
          any("popup.html" in (r.get("resources") or [])
              for r in json.load(open("extension/manifest.json"))
              .get("web_accessible_resources", [])))

    from app import db as _db, api as _api          # noqa: F811
    from app.artifacts import get_artifact as _ga    # noqa: F811
    import json as _json                             # noqa: F811
    print("\nA CAPTURE THAT SKIPS THE THANK-YOU PAGE REPORTS DEAD PIXELS")
    # CONVERSION PIXELS FIRE ON CONVERSION PAGES.
    #
    # The capture did the start URL only, so it came back saying every bought
    # product was "configured, never fired" about a client whose pixels the
    # server had watched fire forty minutes earlier. A false all-clear in the
    # one table that costs money, produced by a coverage gap rather than a
    # matching bug — which is why it looked so convincing.
    _home = {"url": "https://x.com/", "role": "homepage",
             "html": "<html>" + "x" * 3000 + "</html>",
             "scripts": ["https://www.googletagmanager.com/gtm.js?id=GTM-AB1"],
             "pre_requests": ["https://www.google-analytics.com/g/collect?v=2"],
             "banner_visible": False, "consent_defaults": {},
             "consent_defaults_read": True, "accept_clicked": False,
             "reject_clicked": False}
    _thanks = {"url": "https://x.com/thank-you/", "role": "conversion",
               "html": "<html>" + "y" * 3000 + "</html>", "scripts": [],
               "pre_requests": [
                   "https://cnv.event.prod.bidr.io/log/cnv?tag_id=1",
                   "https://segment.prod.bidr.io/associate-segment?buzz_key=d",
                   "https://sp.analytics.yahoo.com/spp.pl?a=1",
                   "https://ad.doubleclick.net/ddm/activity/src=163",
                   "https://insight.adsrvr.org/track/pxl/?adv=61c"],
               "banner_visible": False, "consent_defaults": {},
               "consent_defaults_read": True, "accept_clicked": False,
               "reject_clicked": False}
    _aid2 = _db.create_audit("default", "X", "https://x.com/", None, None,
                             {"consent_products": ["BARCK+"],
                              "conversion_urls": ["https://x.com/thank-you/"]})
    _one = _api.ingest_consent_capture(_aid2, {**_home, "pages": [_home]}, None)
    _d1 = _json.loads(_ga(_aid2, "consent_scan.json").decode())
    _p1 = next((p for p in _d1["scan"]["products"]
                if p["product"] == "BARCK+"), {})
    check("the homepage alone reports the bought pixels as never firing",
          _p1.get("fired") == 0, str(_p1.get("fired")))

    _api.ingest_consent_capture(
        _aid2, {"url": _home["url"], "pages": [_home, _thanks], **_home}, None)
    _d2 = _json.loads(_ga(_aid2, "consent_scan.json").decode())
    _p2 = next((p for p in _d2["scan"]["products"]
                if p["product"] == "BARCK+"), {})
    check("adding the conversion page finds every one of them",
          _p2.get("fired") == 5, str(_p2.get("fired")))
    check("and the record says it covered two pages",
          _d2["scan"].get("pages_scanned") == 2)

    # THE PAGES BELONG TO THIS RUN, NOT THE LAST ONE.
    #
    # The ingest kept the previous scan's page list, so the page rendered one
    # run's tiles above another run's per-page tracker table — two dates on
    # one screen, contradicting each other, under a header claiming both were
    # captured in the browser.
    check("a one-page capture stores one page, not the last run's two",
          len(_json.loads(_ga(_aid2, "consent_scan.json").decode())["pages"]) == 2)
    _api.ingest_consent_capture(_aid2, {**_home, "pages": [_home]}, None)
    _d3 = _json.loads(_ga(_aid2, "consent_scan.json").decode())
    check("and a later one-page capture does not inherit them",
          len(_d3["pages"]) == 1, str([p["url"] for p in _d3["pages"]]))

    # A failed page is part of the record, not dropped.
    _api.ingest_consent_capture(_aid2, {"url": _home["url"], **_home, "pages": [
        _home, {"url": "https://x.com/gone/", "role": "conversion",
                "error": "TimeoutError"}]}, None)
    _d4 = _json.loads(_ga(_aid2, "consent_scan.json").decode())
    check("a page that failed is listed with its error",
          any(p.get("error") for p in _d4["pages"]),
          str([p.get("role") for p in _d4["pages"]]))

    # And the extension has to be told which extra pages to visit.
    _pg_urls = _ch({"id": "zz9", "client_name": "C",
                    "target_url": "https://x.com"},
                   {"scan": {"mode": "basic", "cmps": [], "gtm": {},
                             "pre_consent": [], "post_reject": [],
                             "gpc_fires": [], "products": [],
                             "state_checks": []},
                    "pages": [],
                    "requested": {"conversion_urls":
                                  ["https://x.com/thank-you/"]}})
    check("the page hands the conversion URLs to the extension",
          "data-urls" in _pg_urls and "thank-you" in _pg_urls)
    check("and the extension reads them",
          "el.dataset.urls" in open("extension/content.js", encoding="utf-8").read())
    check("passing them into the run",
          "consentRun(msg.url, msg.urls)"
          in open("extension/background.js", encoding="utf-8").read())

    import time as _t                                # noqa: F811
    print("\nA CAPTURE THAT WATCHED NOTHING IS NOT A CLEAN SITE")
    # Zero requests is not a quiet result, it is an impossible one — a real
    # page load fetches its own stylesheet. It rendered as "Nothing fired",
    # "0 fired before consent" and every bought pixel "configured, not
    # firing": four confident statements derived from a recorder that never
    # attached.
    _silent = result_from_capture({
        "url": "https://x.com/", "html": "<html>" + "z" * 3000 + "</html>",
        "scripts": ["https://www.googletagmanager.com/gtm.js?id=GTM-AB1"],
        "pre_requests": [], "banner_visible": False,
        "consent_defaults_read": True})
    check("a capture with no requests at all is flagged",
          _silent.get("no_requests_recorded") is True)
    check("and the whole result is inconclusive, not clean",
          _silent.get("inconclusive") is True, _silent.get("verdict"))
    check("saying the recorder did not attach",
          "recorder did not attach" in (_silent.get("verdict_detail") or ""))
    check("the count travels with the capture so the page can show it",
          _silent.get("capture_counts", {}).get("pre") == 0)
    _loud = result_from_capture({
        "url": "https://x.com/", "html": "<html>" + "z" * 3000 + "</html>",
        "scripts": [], "pre_requests": ["https://facebook.com/tr?id=1"],
        "banner_visible": False, "consent_defaults_read": True})
    check("a capture that saw traffic is not flagged",
          not _loud.get("no_requests_recorded"))
    _cs2 = open("extension/content.js", encoding="utf-8").read()
    check("and the extension retries the page before accepting a zero",
          "re-arming and reloading"
          in open("extension/background.js", encoding="utf-8").read())
    check("the page says so rather than reporting nothing fired",
          "watched no traffic" in _ch(
              {"id": "z", "client_name": "C", "target_url": "https://x.com"},
              {"scan": _silent, "pages": [], "requested": {}}))

    # RECORDED BUT NOT CLASSIFIED IS ITS OWN FAILURE.
    #
    # A capture came back with 105 requests and zero recognized trackers on a
    # site running a Tag Manager container. "105 recorded" proved the recorder
    # attached and told us nothing else, and the URLs — the one thing that
    # would answer it — were discarded at classification time.
    _odd = result_from_capture({
        "url": "https://x.com/", "html": "<html>" + "z" * 3000 + "</html>",
        "scripts": ["https://www.googletagmanager.com/gtm.js?id=GTM-AB1"],
        "pre_requests": ["https://x.com/style.css", "https://x.com/a.png",
                         "https://fonts.gstatic.com/f.woff2"],
        "banner_visible": False, "consent_defaults_read": True})
    check("traffic with nothing recognized keeps a sample of the URLs",
          len(_odd.get("unmatched_sample") or []) == 2,
          str(_odd.get("unmatched_sample")))
    check("one per host, so a hundred images do not fill it",
          len(result_from_capture({
              "url": "https://x.com/", "html": "<html>" + "z" * 3000 + "</html>",
              "scripts": [], "banner_visible": False,
              "consent_defaults_read": True,
              "pre_requests": [f"https://x.com/img{i}.png" for i in range(60)]
          }).get("unmatched_sample") or []) == 1)
    check("a capture that DID recognize something keeps no sample",
          not _loud.get("unmatched_sample"))
    _oddpage = _ch({"id": "z", "client_name": "C", "target_url": "https://x.com"},
                   {"scan": _odd, "pages": [], "requested": {}})
    check("and the page says traffic was recorded and not recognized",
          "none of it was recognized" in _oddpage)
    check("showing what it saw",
          "fonts.gstatic.com" in _oddpage)
    check("with the per-pass split, not one ambiguous total",
          "pre-consent 3" in _oddpage, str(_odd.get("capture_counts")))

    print("\nDO NOT ASK FOR A RE-RUN OF SOMETHING WE ALREADY HAVE")
    # The GPC pass is a whole extra page load and does not always get set.
    # When it did not, the page said "some of this was never tested" and
    # offered a capture — about a signal an earlier capture had already sent
    # and watched. Same complaint as the nine PageSpeed rows, one layer down.
    _aid3 = _db.create_audit("default", "C", "https://gpc.example/", None, None,
                             {"consent_products": []})
    _base = {"url": "https://gpc.example/",
             "html": "<html>" + "q" * 3000 + "</html>", "scripts": [],
             "pre_requests": ["https://facebook.com/tr?id=9"],
             "banner_visible": False, "consent_defaults_read": True,
             "accept_clicked": False, "reject_clicked": False}
    _api.ingest_consent_capture(_aid3, {**_base, "gpc_requests": []}, None)
    _d = _json.loads(_ga(_aid3, "consent_scan.json").decode())
    check("the first capture tests GPC", _d["scan"]["gpc_tested"] is True)
    # Now one that could not set the signal at all — no gpc_requests key.
    _api.ingest_consent_capture(_aid3, dict(_base), None)
    _d2 = _json.loads(_ga(_aid3, "consent_scan.json").decode())
    check("a later capture that could not set GPC keeps the earlier answer",
          _d2["scan"]["gpc_tested"] is True)
    check("stamped with where it came from, never as this run's work",
          bool(_d2["scan"].get("gpc_carried_at")))
    _pg3 = _ch(_db.get_audit(_aid3), _d2)
    check("so the page stops offering a capture for it",
          "vici-consent" not in _pg3)
    check("and the tick says which run it came from", "from 20" in _pg3)

    print("\nA FIX LINE THAT NAMES A NUMBER CAN SET IT")
    from engine.report import _todo_panel as _tp2
    _covcat = {c: {"section": "ONP", "title": c}
               for c in ("ONP-15", "ONP-48", "TECH-25", "TECH-36")}
    _covf = {c: {"status": "Need Access", "confidence": 0.0,
                 "source": "crawler_checks",
                 "evidence": "Not assessed - this check needs full-site "
                             "coverage, but only 1 of 9 known URLs were "
                             "crawled (11%).",
                 "recommendation": "Re-run with max_pages >= 9 for a "
                                   "definitive answer.",
                 "value": {"pages_crawled": 1, "sitemap_urls": 9,
                           "needs_pages": 9}} for c in _covcat}
    _covp = "".join(_tp2(_covf, _covcat, {"audit_id": "abc123",
                                          "url": "http://x.com/",
                                          "extras": {}}))
    check("the coverage gap carries a re-crawl button",
          "name='max_pages'" in _covp)
    check("pre-filled with the number the fix line names",
          "value='9'" in _covp, _covp[_covp.find("max_pages") - 40:][:90])
    import inspect as _ins2
    check("and the server honors it",
          "max_pages" in _ins2.signature(_api.rerun_audit).parameters)
    check("without reusing the crawl that was too small",
          'opts.pop("reuse_crawl"' in _ins2.getsource(_api.rerun_audit))

    print("\nA CONSENT-ONLY RUN OPENS ON THE CONSENT PAGE")
    check("a run with only consent ticked is recognized as such",
          _api._consent_only({"options": _json.dumps({"run_consent": True})}))
    check("but a run with another phase on is not",
          not _api._consent_only({"options": _json.dumps(
              {"run_consent": True, "run_aivis": True})}))
    check("and neither is a run without consent",
          not _api._consent_only({"options": _json.dumps({"run_aivis": True})}))

    print("\nA VENDOR OUTAGE IS NOT A FACT ABOUT THE SITE")
    # Nine rows read one Google call. A consent-only re-run does not touch
    # performance and was never asked to — but it re-ran the checks anyway,
    # PageSpeed refused, and nine good measurements from a successful full
    # audit were REPLACED with nine gaps. The re-run measured the site less
    # well than not running at all.
    from engine.checks.perf import _need_access as _pna
    _row = _pna("TimeoutError", "Largest Contentful Paint (LCP)")
    check("a PageSpeed gap marks itself retryable",
          (_row.get("value") or {}).get("retryable") is True)
    check("and still says nothing about the site caused it",
          "Nothing about the site caused this" in _row["evidence"])
    from app import worker as _w
    _u = "https://carry.example/"
    _old = _db.create_audit("default", "C", _u, None, None, {})
    _db.save_findings(_old, {"PERF-11": {
        "status": "Warning", "confidence": 1.0, "source": "perf",
        "evidence": "LCP: 3.1 s", "value": {"value": 3100}}})
    _db.update_audit(_old, status="ready", completed_at=_t.time() - 3600)
    _new = _db.create_audit("default", "C", _u, None, None, {"run_consent": True})
    _now_f = {"PERF-11": {
        "status": "Need Access", "confidence": 0.0, "source": "perf",
        "evidence": "could not be measured on this run",
        "value": {"internal": True, "retryable": True}}}
    _carried = _w._carry_forward(_db.get_audit(_new), {"run_consent": True},
                                 _new, _now_f)
    check("a consent-only re-run keeps the last real speed measurement",
          _carried.get("PERF-11", {}).get("status") == "Warning",
          str(_carried.get("PERF-11", {}).get("status")))
    check("stamped with where it came from",
          bool((_carried.get("PERF-11", {}).get("value") or {}).get("carried_at")))
    # A row that this run DID answer must never be overwritten by an old one.
    _fresh = {"PERF-11": {"status": "Pass", "confidence": 1.0, "source": "perf",
                          "evidence": "LCP: 1.1 s", "value": {}}}
    check("but a row this run answered is left alone",
          "PERF-11" not in _w._carry_forward(
              _db.get_audit(_new), {"run_consent": True}, _new, _fresh))

    print("\nAN ABSENT GPC PASS IS UNTESTED, NEVER CLEAN")
    # "Field present" is what marks GPC as tested, so an extension that could
    # not set the signal must send NO field rather than an empty list. An empty
    # list would report a clean GPC result on a site that was never sent the
    # signal — a false clean bill in the section about legal obligations.
    _nogpc = result_from_capture({k: v for k, v in cap.items()
                                  if k != "gpc_requests"})
    check("no gpc_requests field means the pass never ran",
          _nogpc["gpc_tested"] is False)
    check("and an empty one means it ran and nothing fired",
          result_from_capture({**cap, "gpc_requests": []})["gpc_tested"] is True)

    # The extension is the only thing that can fill that field, and it has to
    # send BOTH halves of the signal: the Sec-GPC header a server-side
    # implementation checks, and navigator.globalPrivacyControl a client-side
    # CMP reads. One without the other makes a site look like it ignored GPC
    # when it never saw the half it was listening for.
    _bg = open("extension/background.js", encoding="utf-8").read()
    _mf = open("extension/manifest.json", encoding="utf-8").read()
    check("the extension sends the Sec-GPC header", "Sec-GPC" in _bg)
    check("and defines navigator.globalPrivacyControl",
          "globalPrivacyControl" in
          open("extension/gpc.js", encoding="utf-8").read())
    check("declaring the permission the header needs",
          "declarativeNetRequest" in _mf)
    check("and it only sends gpc_requests when the signal was set",
          "if (gp.header || gp.prop)" in _bg)
    check("the consent page is wired to launch it",
          "VICI_CONSENT_FOR" in _bg
          and "VICI_CONSENT_FOR" in open("extension/content.js",
                                         encoding="utf-8").read())

    print("\nTHE PAGE OFFERS THE CAPTURE WHERE THE BROWSER HALF IS MISSING")
    # A graceful degradation needs something loud somewhere else, or it is just
    # a silent failure with good manners. "Not tested" was the end of the page.
    _basic_page = _ch({"id": "zz9", "client_name": "C",
                       "target_url": "https://x.com"},
                      {"scan": {"mode": "basic", "cmps": [], "gtm": {},
                                "pre_consent": [], "post_reject": [],
                                "gpc_fires": [], "products": [],
                                "state_checks": []},
                       "pages": [], "requested": {}})
    check("a basic scan offers the browser capture", "vici-consent" in _basic_page)
    check("with the audit id ready to paste", "zz9" in _basic_page)
    check("an audit with no stored detail offers it too",
          "vici-consent" in _ch({"id": "zz9", "client_name": "C",
                                 "target_url": "https://x.com"}, None))
    _full_page = _ch({"id": "zz9", "client_name": "C",
                      "target_url": "https://x.com"},
                     {"scan": {"mode": "full", "cmps": [{"name": "OneTrust"}],
                               "gtm": {}, "banner_visible": True,
                               "reject_tested": True, "gpc_tested": True,
                               "pre_consent": [], "post_reject": [],
                               "gpc_fires": [], "products": [],
                               "state_checks": []},
                      "pages": [], "requested": {}})
    check("but a scan that tested everything is not nagged",
          "vici-consent" not in _full_page)
    # A SITE WITH NO BANNER HAS NO REJECT BUTTON, EVER.
    #
    # This offered the capture whenever Reject was untested — so a capture
    # that had just run perfectly from the operator's own Chrome ended with a
    # panel telling them to run it again, and running it again produced the
    # identical page. "No Reject control on a site with no CMP" is a finding,
    # not a gap.
    _nocmp = _ch({"id": "zz9", "client_name": "C", "target_url": "https://x.com"},
                 {"scan": {"mode": "full", "source": "extension", "cmps": [],
                           "gtm": {}, "banner_visible": False,
                           "reject_tested": False, "gpc_tested": True,
                           "pre_consent": [], "post_reject": [],
                           "gpc_fires": [], "products": [],
                           "state_checks": []},
                  "pages": [], "requested": {}})
    check("no CMP means no re-run is offered for the Reject test",
          "vici-consent" not in _nocmp)
    check("and the tile says why rather than saying not tested",
          "no reject button" in _nocmp)

    # THE TILE AND THE TABLE MUST COUNT THE SAME ROWS.
    _two_pages = _ch({"id": "zz9", "client_name": "C", "target_url": "https://x.com"},
                     {"scan": {"mode": "full", "cmps": [{"name": "OneTrust"}],
                               "gtm": {}, "banner_visible": True,
                               "reject_tested": True, "gpc_tested": True,
                               "pre_consent": [{"vendor": "Meta Pixel",
                                                "severity": "high",
                                                "url": "https://facebook.com/tr"}],
                               "post_reject": [], "gpc_fires": [],
                               "products": [], "state_checks": []},
                      "pages": [{"url": "https://x.com/", "role": "homepage",
                                 "scan": {"mode": "full", "pre_consent": [
                                     {"vendor": "Meta Pixel", "severity": "high",
                                      "url": "https://facebook.com/tr"}]}},
                                {"url": "https://x.com/thanks/", "role": "conversion",
                                 "scan": {"mode": "full", "pre_consent": []}}],
                      "requested": {}})
    import re as _re
    _tilenum = _re.search(r"<div class='n'>(\d+)</div>\s*<div class='k'>"
                          r"[^<]*<b[^>]*></b>fired before consent", _two_pages)
    _tilenum = _tilenum or _re.search(
        r"<div class='n'>(\d+)</div>(?:(?!</div>).)*?fired before consent",
        _two_pages, _re.S)
    _rowcount = _two_pages.count("facebook.com/tr")
    check("the headline count is the number of rows printed under it",
          _tilenum and int(_tilenum.group(1)) == 1,
          f"tile={_tilenum.group(1) if _tilenum else '?'} rows={_rowcount}")

    # The button must not promise a popup a web page cannot open.
    _cs = open("extension/content.js", encoding="utf-8").read()
    # The comment explaining the old behavior is allowed to mention it; a
    # line that SETS button text is not.
    check("no button claims a popup will open",
          not [l for l in _cs.splitlines()
               if "textContent" in l and "popup" in l])
    check("progress is polled onto the page instead",
          "VICI_GET_STATE" in _cs and "vici-log" in _cs)
    check("and the page reloads itself when the run finishes",
          "location.reload()" in _cs)

    print("\nA CAPTURE THAT COULD NOT READ THE DATALAYER SAYS SO")
    # "No Consent Mode defaults" and "we could not look" are opposite findings.
    blind = result_from_capture(dict(cap, consent_defaults={},
                                     consent_defaults_read=False))
    check("unknown is not reported as absent",
          blind["consent_mode_default"] == "unknown")
    check("so the row is unanswered rather than failed",
          findings_from_scan(blind)["CONS-03"]["status"] == "Need Access")

    print("\nTHE ENDPOINT WORKS OVER HTTP, NOT ONLY IN CODE")
    from app.ui_consent import consent_html as _ch
    import json as _json
    import tempfile
    import threading
    import urllib.request
    import uvicorn
    os.environ.setdefault("SQLITE_PATH",
                          os.path.join(tempfile.mkdtemp(), "t.db"))
    from app import db as _db, api as _api
    _db.init_db()
    aid = _db.create_audit("default", "Ooten", "https://x.com", None, None, {})
    srv = uvicorn.Server(uvicorn.Config(_api.app, host="127.0.0.1", port=8807,
                                        log_level="error"))
    t = threading.Thread(target=srv.run, daemon=True); t.start()
    import time as _t
    for _ in range(80):
        _t.sleep(0.05)
        if getattr(srv, "started", False):
            break
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:8807/api/audits/{aid}/consent-capture",
            data=_json.dumps(cap).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as r:
            body = _json.loads(r.read())
        check("the capture is accepted", r.status == 200, str(r.status))
        check("and it says how many rows it answered",
              body.get("answered", 0) >= 7, str(body))
        check("naming the CMP it found", body.get("cmps") == ["OneTrust"])
        stored = _db.get_findings(aid)
        check("the findings are stored against the audit",
              all(c in stored for c in CONS_IDS))
        check("and the score was recomputed to include them",
              "CONS" in (_db.get_scores(aid) or {}).get("sections", {}),
              str(list((_db.get_scores(aid) or {}).get("sections", {}))[-3:]))

        # THE CAPTURE IS THE ONLY SOURCE OF THE DETAIL ON A BLOCKED SITE.
        #
        # The endpoint saved nine findings and nothing else, so the consent
        # page an operator opened after going to the trouble of running the
        # capture said "no consent detail was stored for this run" — about the
        # run that had just answered everything.
        from app.artifacts import get_artifact as _ga
        _blob = _ga(aid, "consent_scan.json")
        check("the full scan record is stored, not just the nine rows",
              bool(_blob))
        _rec = _json.loads(_blob.decode()) if _blob else {}
        check("and the page can read a scan out of it",
              bool((_rec.get("scan") or {}).get("cmps")))
        check("the endpoint says where to look",
              body.get("consent", "").endswith("/consent"), str(body))
        _ex = _json.loads(_db.get_audit(aid)["extras"] or "{}")
        check("the audit stops claiming the scan ran without a browser",
              (_ex.get("consent") or {}).get("mode") == "full",
              str(_ex.get("consent")))
        check("and records that it came from the extension",
              (_ex.get("consent") or {}).get("source") == "extension")

        # The page renders from the stored record, end to end.
        _pg = _ch(_db.get_audit(aid), _rec)
        check("and the stored record renders as a page",
              "Consent platform" in _pg and "OneTrust" in _pg)
    finally:
        srv.should_exit = True
        t.join(timeout=5)

    F = findings_from_scan

    print("\nA SCAN THAT NEVER SAW THE PAGE ANSWERS NOTHING")
    # The worst bug this adapter had. `_apply_verdict` marks a bot challenge,
    # a 4xx, or a sub-2KB body as inconclusive and DELIBERATELY leaves
    # error=None and ok=True, because the run itself succeeded. Guarding only
    # on `error` let all of it through, so a Cloudflare "Checking your
    # browser" page produced Critical findings about a consent banner.
    r = F({"mode": "full", "error": None, "inconclusive": True,
           "challenged": True, "http_status": 403, "html_len": 900,
           "page_title": "Just a moment...",
           "verdict_detail": "Scan inconclusive - bot challenge served",
           "cmps": [], "banner_visible": False, "pre_consent": [],
           "optout_link": None})
    check("an inconclusive scan produces no findings at all",
          {v["status"] for v in r.values()} == {"Need Access"},
          str(sorted({v["status"] for v in r.values()})))
    check("and it carries the diagnosis so the next run is not a guess",
          "403" in r["CONS-02"]["evidence"]
          and "challenge" in r["CONS-02"]["evidence"].lower())
    check("and points at the tool that gets past it",
          "extension" in r["CONS-02"]["recommendation"])

    print("\nA NOTICE BAR IS NOT A CONSENT PLATFORM")
    # A bar with an OK button and no reject collects nothing and offers no
    # opt-out. Counting any cmps[] entry as a Pass made it a green row on the
    # finding most likely to matter legally.
    r = F({"mode": "basic", "cmps": [{"name": "Notice-only banner"}]})
    check("a notice-only banner fails CONS-01 rather than passing it",
          r["CONS-01"]["status"] == "Fail", r["CONS-01"]["status"])
    check("and says what it is missing",
          "reject" in r["CONS-01"]["evidence"].lower())
    r = F({"mode": "basic", "cmps": [{"name": "OneTrust", "gtm_event": "X",
                                      "notes": "fires on every page view"}]})
    check("a real CMP still passes", r["CONS-01"]["status"] == "Pass")
    check("and the per-CMP operator note is carried through, not dropped",
          r["CONS-01"]["value"].get("notes") == ["fires on every page view"])

    print("\nA SITE WITH NO CMP AND LIVE PIXELS CANNOT PASS 'NO TRACKING'")
    # _dedupe_product_pixels strips every ungated pre-consent row that matches
    # a product pixel, so it can be shown once under Product pixels instead of
    # twice. "ungated" is what EVERY pre-consent tracker gets when there is no
    # CMP. The standalone tool renders products right below; this adapter never
    # read them — so no CMP + Meta + GA4 came back "Pass: no advertising or
    # analytics tags contacted their servers before consent."
    r = F({"mode": "full", "cmps": [], "pre_consent": [], "products": [
        {"product": "Meta", "pixels": [
            {"name": "Meta Pixel", "fired_pre": True, "severity": "ungated",
             "sample_url": "https://facebook.com/tr?id=1", "src": "page"}]},
        {"product": "GA4", "pixels": [
            {"name": "GA4", "fired_pre": True, "severity": "ungated",
             "sample_url": "https://g.co/collect", "src": "runtime"}]}]})
    check("product pixels that fired pre-consent are counted",
          r["CONS-04"]["status"] == "Fail", r["CONS-04"]["status"])
    check("and both vendors are named",
          set(r["CONS-04"]["value"]["vendors"]) == {"GA4", "Meta Pixel"})
    # `src` decides WHO does the work. A hardcoded tag cannot be fixed in GTM,
    # and telling someone to fix it there sends them hunting for a tag that
    # was never in the container.
    rec = r["CONS-04"]["recommendation"]
    check("a runtime tag is sent to Tag Manager",
          "Tag Manager" in rec and "GA4" in rec.split("hardcoded")[0])
    check("and a hardcoded tag is sent to the theme instead",
          "hardcoded in the page template" in rec and "Meta Pixel" in rec)
    check("an actually-clean site still passes",
          F({"mode": "full", "cmps": [], "pre_consent": [],
             "products": []})["CONS-04"]["status"] == "Pass")

    print("\n'STATE PRIVACY LAW REQUIREMENTS' MUST CHECK A STATE")
    # The scanner always emits one universal privacy-policy row tagged "US".
    # Because nothing ever requested a state, that row was the only one that
    # arrived, and this checkpoint reported "All 1 checked requirements are met
    # across US" — a privacy-policy-link check wearing a state-law label, shown
    # as a clean pass on twenty states nobody had looked at.
    r = F({"mode": "full", "state_checks": [
        {"state": "US", "check": "Privacy policy link", "status": "pass"}]})
    check("no states selected is unanswered, never a pass",
          r["CONS-08"]["status"] == "Need Access", r["CONS-08"]["status"])
    check("and it says how to make it answerable",
          "states" in r["CONS-08"]["recommendation"].lower())
    r = F({"mode": "full", "state_checks": [
        {"state": "US", "check": "Privacy policy link", "status": "pass"},
        {"state": "CA", "check": "GPC signal", "status": "fail",
         "detail": "California requires GPC to be honored as an opt-out."},
        {"state": "CO", "check": "Opt-out mechanism", "status": "pass"}]})
    check("with states selected it counts only the state rows",
          r["CONS-08"]["value"]["checks"] == 2, str(r["CONS-08"]["value"]))
    check("and never reports 'US' as a state",
          "US" not in r["CONS-08"]["value"]["states"])
    check("the statute explanation is carried, not replaced by a label",
          "California requires"
          in (r["CONS-08"]["value"]["failures"][0]["detail"] or ""))

    print("\nTHE FORM CAN ACTUALLY SET STATES AND INDUSTRIES")
    # Both were vendored, tested and unreachable: the scanner took them, the
    # worker passed them, and nothing ever set them.
    import app.ui as _ui, inspect as _insp
    from types import SimpleNamespace as _N
    _html = _ui.dashboard_html([], _N(name="V", email="e"), 0,
                               caps={"consent": True, "aivis": True})
    check("the form offers a states field", "consent_states" in _html)
    # WAS: asserted the box was prefilled `CA CO CT TX VA OR`. That was right
    # while a guess beat a blank — an empty list is not "check nothing", it is
    # "silently answer nothing". It is wrong now: the states are derived from
    # the markets, which is where the answer actually lives. A Knoxville firm
    # was having California's law tested because of that prefill.
    check("the states box is derived rather than guessed",
          "consent_states" in _html and "value='CA CO CT TX VA OR'" not in _html)
    check("and an industry field", "consent_industries" in _html)
    import app.api as _api
    # submit_form, not create_audit — create_audit is the JSON API and the
    # consent options are a form concern.
    _sig = _insp.signature(_api.submit_form)
    check("the API accepts both",
          {"consent_states", "consent_industries"} <= set(_sig.parameters))

    print("\nA PHASE THAT CANNOT RUN STILL WRITES ITS ROWS")
    # Both optional phases used to `return` on their unhappy paths — a failed
    # import, no platform keys — leaving their checkpoints with NO finding at
    # all. The panel could then only say "produced no result for this run",
    # which names no cause, because the cause went to a log and was dropped.
    from app.worker import _phase_unanswered as _pu
    from engine.consent.checks import CONS_IDS as _CID
    rows = _pu(_CID, "The consent scanner could not be loaded on this worker "
                     "(ImportError: no module named playwright).",
               "This is a deployment problem, not a client one.")
    check("every checkpoint in the phase gets a row",
          set(rows) == set(_CID), f"{len(rows)} rows")
    check("unanswered, never passed or failed",
          {r["status"] for r in rows.values()} == {"Need Access"})
    check("carrying zero confidence, so scoring leaves them out",
          all(r["confidence"] == 0.0 for r in rows.values()))
    check("and naming the actual cause rather than the absence of a result",
          "playwright" in rows["CONS-01"]["evidence"].lower())
    check("with a fix that says whose problem it is",
          "deployment problem" in rows["CONS-01"]["recommendation"])

    print("\nA BASIC SCAN SAYS WHAT STOPPED THE BROWSER")
    # The scanner degrades to basic when Chromium will not start, printed the
    # reason to stdout, and dropped it. So the report said "this ran as a
    # basic scan" and left the WHY in a worker log that is gone by the time
    # anyone reads the report — with five checkpoints unanswered and no way
    # to get them answered.
    r = F({"mode": "basic", "cmps": [],
           "full_scan_error": "BrowserType.launch: Executable doesn't exist"})
    check("the launch failure reaches the reader",
          "Executable doesn't exist" in r["CONS-02"]["evidence"])
    check("and it is named as ours, not the client's",
          "not a client one" in r["CONS-02"]["recommendation"])
    r2 = F({"mode": "basic", "cmps": []})
    check("a basic scan with no recorded reason still reads cleanly",
          "basic scan" in r2["CONS-02"]["evidence"]
          and "did not start" not in r2["CONS-02"]["evidence"])
    from engine.consent.scanner import scan_site as _ss
    import inspect as _i
    check("and the scanner is what records it",
          "full_scan_error" in _i.getsource(_ss))

    print("\nSTRUCTURED EVIDENCE REACHES THE READER")
    # Every finding carries a `value` dict; the DB stored it and NOTHING
    # rendered it. The reader got one sentence where eight request URLs
    # proving it sat unread.
    from engine.report import _value_block
    _vb = _value_block({"vendors": ["Meta Pixel"],
                        "examples": ["https://facebook.com/tr?id=1"],
                        "by_source": {"page": ["Meta Pixel"]}})
    check("vendors are rendered", "Meta Pixel" in _vb)
    check("the request URL is rendered", "facebook.com/tr" in _vb)
    check("and the source is spelled out, not left as a keyword",
          "hardcoded in the page template" in _vb)
    check("an empty value renders nothing at all", _value_block({}) == "")

    print("\nTHE CLIENT PROFILE SURVIVES A RUN WITH CONSENT UNTICKED")
    # THE BUG: every one of these was parsed inside `if run_consent:`. Tick
    # "Full audit" and leave the consent box alone and the conversion URLs,
    # the products, the industry, the derived states and the implementation
    # were all read off the form and thrown away — the operator watched them
    # sit in the field right up to submit, then the settings panel said "—".
    # That is what "conversion urls didn't save" was.
    import app.api as _api2
    from app import db as _db2
    _saved = {}

    def _fake_create(owner, name, url, vert, _x, options):
        _saved.update(options or {})
        return "testaudit"

    _real_create, _real_enq = _db2.create_audit, _api2.Q.enqueue
    _db2.create_audit = _fake_create
    _api2.Q.enqueue = lambda *_a, **_k: None
    # Called directly, so the FastAPI `Form(...)` defaults never resolve —
    # fill every parameter the way an unticked, empty form actually posts.
    _kw = {}
    for _n, _p in _insp.signature(_api2.submit_form).parameters.items():
        _kw[_n] = 150 if _n == "max_pages" else (
            None if _n == "x_api_key" else "")
    _kw.update(
        target_url="https://ootenlawfirm.com/", client_name="Ooten",
        primary_markets="Knox County, TN × Blount County, TN",
        conversion_urls="https://ootenlawfirm.com/contact/ "
                        "https://ootenlawfirm.com/thank-you",
        consent_products="meta,google_ads", consent_industries="Legal",
        implementation="gtm", phases="1", do_audit="on",
        run_judgment="on", run_collectors="on", run_screenshots="on",
        run_consent="")              # <- THE BOX IS NOT TICKED
    try:
        _api2.submit_form(**_kw)
    finally:
        _db2.create_audit, _api2.Q.enqueue = _real_create, _real_enq

    check("the consent phase is correctly OFF",
          not _saved.get("run_consent"))
    check("but the conversion URLs are still on the record",
          len(_saved.get("conversion_urls") or []) == 2,
          str(_saved.get("conversion_urls")))
    check("the products too", _saved.get("consent_products") == ["meta", "google_ads"])
    check("the industry too", _saved.get("consent_industries") == ["Legal"])
    check("the implementation too", _saved.get("implementation") == "gtm")
    check("and the states derived from the markets, not from a guess",
          _saved.get("consent_states") == ["TN"], str(_saved.get("consent_states")))

    print("\nA ROW WITH NOTHING TO MEASURE IS NOT A SECOND FINDING")
    # Ooten's real scan: full browser mode, no CMP anywhere, Tennessee only.
    # Three rows landed on "Ours to fix — nothing to ask anyone for", one of
    # them carrying the instruction "Load the page and look", which is a
    # person doing something. All three were restatements of CONS-01, which
    # is already on the report and IS the finding.
    _ooten = {"mode": "full", "cmps": [], "verdict": "no_cmp",
              "states": ["TN"], "banner_visible": None,
              "reject_tested": False, "gpc_tested": False,
              "consent_mode_default": False, "consent_defaults": {},
              "pre_consent": []}
    _r = F(_ooten)
    check("the banner row points at CONS-01 instead of asking for a human",
          _r["CONS-02"]["source"] == "consent_no_cmp"
          and "CONS-01" in _r["CONS-02"]["evidence"])
    check("and no longer tells anyone to load the page and look",
          "look" not in _r["CONS-02"]["recommendation"].lower())
    check("the Reject row does the same",
          _r["CONS-05"]["source"] == "consent_no_cmp")
    check("CONS-01 itself still carries the actual finding",
          _r["CONS-01"]["status"] == "Warning"
          and "no recognized consent management platform"
          in _r["CONS-01"]["evidence"].lower())

    print("\nAND A CHECK THAT DOES NOT APPLY IS AN ANSWER, NOT AN OMISSION")
    # GPC is law in twelve states. Tennessee is not one, so the scanner is
    # RIGHT to skip the pass for a Knoxville firm — and the row was reporting
    # that correct decision as a gap on our fix list.
    check("Tennessee-only makes GPC not applicable, not unmeasured",
          _r["CONS-06"]["status"] == "N/A"
          and _r["CONS-06"]["source"] == "consent_not_applicable")
    check("and it names the states it checked rather than shrugging",
          "TN" in _r["CONS-06"]["evidence"])
    # The case that IS ours must not be swept up with it.
    _ca = F(dict(_ooten, states=["CA", "TN"]))["CONS-06"]
    check("a GPC state in scope with no pass run is still ours to fix",
          _ca["status"] == "Need Access" and _ca["source"] == "consent_unknown",
          f"{_ca['status']} / {_ca['source']}")
    check("and says which state required it",
          "CA" in _ca["evidence"])
    # And a site that HAS a CMP keeps the old, correct diagnosis.
    _cmp = F(dict(_ooten, cmps=[{"name": "OneTrust"}], verdict="cmp",
                  banner_visible=True))["CONS-05"]
    check("a real CMP with no reject control is still a scan gap",
          _cmp["source"] == "consent_unknown"
          and "consent platform was found" in _cmp["evidence"])

    print("\nAND NONE OF THE THREE SITS ON THE FIX LIST")
    import re as _re3
    from engine.report import _todo_panel as _tp
    from engine.scoring import load_catalog as _lc
    _cat3 = {k: v for k, v in _lc("seed/checkpoints.csv").items()
             if k.startswith("CONS-")}
    _txt3 = _re3.sub(r"\s+", " ", _re3.sub(r"<[^>]+>", " ", "".join(
        _tp(_r, _cat3, {"extras": {"phases_run": {"run_consent": True,
                                                  "run_aivis": True}}}))))
    check("the banner row is off it", "no consent platform was found"
          not in _txt3.lower())
    check("the GPC row is off it",
          "Global Privacy Control does not apply" not in _txt3)
    check("and nothing on it tells a person to go and look",
          "Load the page and look" not in _txt3)

    print("\nTHE SCAN IS KEPT, NOT JUST THE NINE ROWS DERIVED FROM IT")
    # Everything the scanner learned — CMP signatures and the evidence that
    # matched them, container ids, Consent Mode defaults, every tracker with
    # the moment it fired, per-state statute results, product pixels — was
    # computed and thrown away as soon as nine findings existed. That is most
    # of what the standalone tool puts on screen.
    import inspect as _i4
    from app import worker as _wk
    _csrc = _i4.getsource(_wk._consent)
    check("the worker stores the whole scan as an artifact",
          'put_artifact(audit_id, "consent_scan.json"' in _csrc)
    check("with each page's own result, not only the merged one",
          '"pages": pages' in _csrc and '"role": "conversion"' in _csrc)
    check("a page that failed to scan is still in the record",
          '"error": f"{type(exc).__name__}: {exc}"' in _csrc)
    check("and a detail write that fails says so instead of vanishing",
          'has_detail' in _csrc and 'detail_error' in _csrc)
    import app.api as _api4
    check("the page and the JSON are both routed",
          hasattr(_api4, "consent_page") and hasattr(_api4, "consent_detail"))

    print("\nAND THE DASHBOARD RENDERS WHAT IT WAS GIVEN")
    from app.ui_consent import consent_html as _ch
    _aud = {"id": "abc123", "client_name": "The Ooten Law Firm",
            "target_url": "https://ootenlawfirm.com/"}
    _det = {"scan": {"mode": "full", "verdict": "no_cmp",
                     "verdict_detail": "No CMP detected.",
                     "cmps": [], "gtm": {"found": True,
                                         "container_ids": ["GTM-K4SZBGQZ"]},
                     "consent_mode_default": False, "banner_visible": None,
                     "reject_tested": False, "gpc_tested": False,
                     "pre_consent": [{"vendor": "Meta Pixel", "severity":
                                      "ungated",
                                      "url": "https://facebook.com/tr?id=1"}],
                     "post_reject": [], "gpc_fires": [], "states": ["TN"],
                     "state_checks": [{"state": "TN", "check": "Opt-out link",
                                       "status": "Fail", "detail": "None."}],
                     "products": [{"product": "PMax", "expected": True,
                                   "fired": False, "pixels": []}]},
            "pages": [{"url": "https://ootenlawfirm.com/", "role": "homepage",
                       "scan": {"mode": "full", "pre_consent": [
                           {"vendor": "Meta Pixel", "severity": "ungated",
                            "url": "https://facebook.com/tr?id=1"}]}},
                      {"url": "https://ootenlawfirm.com/thank-you/",
                       "role": "conversion",
                       "scan": {"mode": "full", "pre_consent": []}}],
            "requested": {"states": ["TN"], "products": ["PMax"],
                          "conversion_urls":
                              ["https://ootenlawfirm.com/thank-you/"]}}
    _html = _ch(_aud, _det)
    check("the container id is on the page", "GTM-K4SZBGQZ" in _html)
    check("the ungated pixel is named with its request",
          "Meta Pixel" in _html and "facebook.com/tr" in _html)
    check("and attributed to the page it fired on",
          "thank-you" in _html and "Page" in _html)
    check("a bought product that never fires is called out",
          "PMax" in _html and "no pixels seen" in _html)
    # The evidence column ran str() over a dict of pixel state and printed
    # Python at the client. It must never come back.
    check("and the evidence column never prints a Python dict",
          "'fired_pre'" not in _html and "{'name'" not in _html)
    check("the state result carries its statute detail",
          "Opt-out link" in _html)

    print("\nAN EMPTY TABLE AND A CLEAN ONE MUST NOT LOOK THE SAME")
    # "No trackers under Fired after Reject" reads as a pass. It is a pass
    # only if Reject was clicked; with no banner to click, the identical empty
    # table means nothing was tested.
    check("an untested Reject says there was no banner to click",
          "no Reject control was found to click" in _html)
    check("and GPC says it does not apply in Tennessee rather than 'not run'",
          "Not applicable" in _html and "(TN)" in _html)
    _ca = _ch(_aud, {**_det, "requested": {"states": ["CA"]}})
    check("but a state that DOES require GPC makes it ours to fix",
          "ours to fix" in _ca and "CA" in _ca)
    _basic = _ch(_aud, {**_det, "scan": {**_det["scan"], "mode": "basic"}})
    check("a basic scan says the empty tables mean untested, not clean",
          "mean untested, not clean" in _basic)

    print("\nAND AN AUDIT WITH NO DETAIL EXPLAINS ITSELF")
    # The link is drawn on every consent audit; older ones have no artifact.
    # A 404 there reads as a broken feature.
    _none = _ch(_aud, None)
    check("no stored detail renders a page, not an error",
          "No consent detail was stored" in _none)
    check("and says how to get it", "Re-run" in _none)

    print("\nOUR MEDIA STACK NEVER REACHES A CLIENT'S PDF")
    # THE BUG, REPLAYED.
    #
    # CONS-04 stopped naming the demand-side platforms three builds ago. A
    # report rendered afterwards still listed them - because the collector fix
    # only applies to runs that happen after it, and findings are STORED. The
    # PDF renders fresh from the store, so the redaction has to run there too.
    from engine.redact import client as _client
    stored = ("13 trackers fired before any consent interaction: Beeswax "
              "conversion, Beeswax segment, DoubleClick / Floodlight, "
              "Floodlight, Google Ads, Google Analytics, Meta Pixel, The "
              "Trade Desk, Yahoo, xAd/GroundTruth.")
    out = _client(stored)
    check("no platform is named in the client copy",
          not any(n in out for n in ("Beeswax", "Trade Desk", "xAd",
                                     "Floodlight", "Yahoo")), out)
    check("the count survives, because the count is the finding",
          "13" in out, out)
    check("and it is called what we call it in front of a client",
          "marketing pixel" in out, out)
    check("a sentence that merely mentions one vendor is left alone",
          _client("Google Analytics fired before consent.")
          == "Google Analytics fired before consent.")

    # And end to end, through the renderer that actually ships it.
    from engine.pdf_report import _pl
    check("the PDF's prose helper applies the same redaction",
          "Beeswax" not in _pl(stored), _pl(stored)[:70])

    print("\nA ROW NOBODY CAN UNBLOCK IS NOT 'NEED ACCESS'")
    # THE CLIENT'S QUESTION, VERBATIM: "what access am I missing?" None. The
    # scan found no consent platform, so there was no banner to test and no
    # Reject button to press. That is CONS-01 restated, and no login anybody
    # could hand over changes it - but the pill asked them for one.
    from engine.pdf_report import _status_word
    check("no consent platform reads as not applicable",
          _status_word("Need Access", "CONS-02", "consent_no_cmp")
          == "Not applicable")
    check("so does a check that does not apply to their states",
          _status_word("Need Access", "CONS-08", "consent_not_applicable")
          == "Not applicable")
    check("but a real Search Console gap still asks for access",
          _status_word("Need Access", "GSC-04", "gsc_ui_only")
          == "Need Access")
    check("and 'Not Implemented' is written the way a client would say it",
          _status_word("Not Implemented", "ONP-34") == "Missing")

    print("\nA PAGE WITH NOTHING ON IT IS NOT A MISSING CREDENTIAL")
    # The row read "This page carried no readable text for this check" under a
    # heading reading "A credential we have not set, or a call we have not
    # written". Both on screen at once, contradicting each other - the same
    # fault as the platform rows, one bucket along.
    from engine.report import _todo_panel as _tp
    _F2 = {"EEAT-01": {"status": "Need Access", "severity": "Low",
                       "evidence": "This page carried no readable text for "
                                   "this check.",
                       "recommendation": "If the page builds its content in "
                                         "the browser, re-run with Render "
                                         "JavaScript forced.",
                       "confidence": 0.0, "source": "page_unreadable"}}
    _c2 = {"EEAT-01": {"prefix": "EEAT", "checkpoint": "First-hand experience"}}
    _html = "".join(_tp(_F2, _c2, {"extras": {"phases_run":
                                              {"run_consent": True,
                                               "run_aivis": True}}}))
    check("it gets its own group", "Nothing on the page to read" in _html)
    check("and is not filed under a credential we have not set",
          "Ours to fix" not in _html, _html[:0])
    check("the fix line travels with it",
          "Render JavaScript forced" in _html)

    print("\n" + "=" * 68)
    if FAILED:
        print(f"  {len(FAILED)} FAILED: {FAILED}")
    else:
        print("  ALL CHECKS PASSED — consent scanning is a phase of the audit, "
              "and a basic scan cannot pass what it never saw")
    print("=" * 68 + "\n")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
