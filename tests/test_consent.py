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
    check("naming the vendor, which is what gets fixed",
          "Meta Pixel" in r["CONS-04"]["evidence"])

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
    check("no recognised CMP is a Warning", none["CONS-01"]["status"] == "Warning")
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

    print("\nA CAPTURE THAT COULD NOT READ THE DATALAYER SAYS SO")
    # "No Consent Mode defaults" and "we could not look" are opposite findings.
    blind = result_from_capture(dict(cap, consent_defaults={},
                                     consent_defaults_read=False))
    check("unknown is not reported as absent",
          blind["consent_mode_default"] == "unknown")
    check("so the row is unanswered rather than failed",
          findings_from_scan(blind)["CONS-03"]["status"] == "Need Access")

    print("\nTHE ENDPOINT WORKS OVER HTTP, NOT ONLY IN CODE")
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
    check("prefilled, because blank silently checked nothing",
          "value='CA CO CT TX VA OR'" in _html)
    check("and an industry field", "consent_industries" in _html)
    import app.api as _api
    # submit_form, not create_audit — create_audit is the JSON API and the
    # consent options are a form concern.
    _sig = _insp.signature(_api.submit_form)
    check("the API accepts both",
          {"consent_states", "consent_industries"} <= set(_sig.parameters))

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
