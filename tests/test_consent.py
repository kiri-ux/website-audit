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
