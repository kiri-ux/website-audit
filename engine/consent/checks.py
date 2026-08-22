"""
One consent scan, turned into nine audit checkpoints.

THE ONLY NEW CODE IN THIS PACKAGE. Everything else is the standalone scanner,
vendored unchanged. This file is the adapter, and it is deliberately thin: it
reads the scan result and states what it says. It does no detection of its own,
because a second opinion about whether a CMP is present would be a second thing
that can be wrong.

THE RULE THAT SHAPES EVERY ROW HERE
-----------------------------------
A basic scan — raw HTML, no browser — can detect most CMPs and nothing else. It
cannot see whether the banner appears, whether Consent Mode defaults are set, or
what fired before anyone clicked. Reporting "no tracking before consent: Pass"
off a basic scan would be a clean bill of health for a question that was never
asked.

So every row that needs the browser reports **Need Access** when the scan ran in
basic mode, and says so. The scanner's own `mode` field is what decides, not a
guess about what the numbers look like.

The second rule: a consent finding is a LEGAL exposure, not a ranking one. The
severities here are higher than an SEO reader expects, and that is correct —
a pixel firing before consent in a state with a private right of action is a
different kind of problem from a missing meta description.
"""
from __future__ import annotations

CONS_IDS = tuple(f"CONS-{i:02d}" for i in range(1, 10))

# Rows that cannot be answered without a real browser. In basic mode they are
# unanswered rather than passed.
_NEEDS_BROWSER = {"CONS-02", "CONS-03", "CONS-04", "CONS-05", "CONS-06"}


def _f(status, value=None, evidence="", severity="Medium", rec="", conf=1.0,
       src="consent"):
    return {"status": status, "value": value or {}, "evidence": evidence,
            "affected_pages": [], "severity": severity, "recommendation": rec,
            "confidence": conf, "source": src}


def _unanswered(ids, why, rec=""):
    return {cid: _f("Need Access", {}, why, "Low", rec, 0.0, "consent_basic")
            for cid in ids}


def _cons04_rec(by_src: dict) -> str:
    """
    Source-aware remediation. Two different jobs, two different people.

    A tag hardcoded in the page template is a developer ticket — find it,
    remove it, reinstate it behind the consent event. A tag injected by GTM is
    a container change — add an additional consent check requiring ad_storage,
    then publish. Telling someone to "gate these behind the CMP's consent
    event" when the tag is baked into the theme sends them looking in GTM for
    something that was never there.
    """
    page = by_src.get("page") or []
    runtime = by_src.get("runtime") or []
    parts = []
    if runtime:
        parts.append(
            f"In Tag Manager, set an additional consent check requiring "
            f"ad_storage on {', '.join(runtime)}, then publish.")
    if page:
        parts.append(
            f"{', '.join(page)} {_plural(len(page), 'is', 'are')} hardcoded in "
            f"the page template, so no container change will stop "
            f"{_plural(len(page), 'it', 'them')} — the tag has to come out of "
            f"the theme and be reinstated behind the consent event.")
    if not parts:
        parts.append("Gate these behind the CMP's consent event.")
    parts.append("Until then the banner is decorative.")
    return " ".join(parts)


def _plural(n, one, many=None):
    return one if n == 1 else (many or one + "s")


def findings_from_scan(scan: dict | None) -> dict:
    """
    Nine checkpoints from one scan result.

    Returns Need Access for everything if the scan did not happen at all — the
    audit must survive a consent scan that failed exactly as it survives a
    DataForSEO outage.
    """
    if not scan:
        return _unanswered(CONS_IDS,
                           "The consent scan did not run for this audit.",
                           "Tick 'Check consent and privacy' when starting the "
                           "run.")
    if scan.get("error"):
        return _unanswered(CONS_IDS,
                           f"The consent scan could not complete: "
                           f"{scan['error']}",
                           "Re-run; if the site challenges automated browsers, "
                           "capture it with the extension instead.")

    # A SCAN THAT DID NOT SEE THE PAGE ANSWERS NOTHING.
    #
    # This was the worst bug in this file, because it produced confident
    # findings about pages that never rendered. `_apply_verdict` sets
    # `inconclusive=True` — a bot challenge, an HTTP 4xx, a body under 2KB,
    # or nothing found at all — and deliberately leaves `error` as None and
    # `ok` as True, because from the scanner's point of view the run itself
    # succeeded. Guarding only on `error` therefore let all of it through:
    # a Cloudflare challenge screen produced CONS-02 "Fail / Critical: a
    # consent platform is installed but no banner appeared" and CONS-04
    # "Pass: no advertising or analytics tags contacted their servers before
    # consent", about a page consisting of the words "Checking your browser".
    #
    # The standalone tool refuses exactly this, in those words: "Nothing here
    # should be treated as a finding about the site."
    if scan.get("inconclusive"):
        why = scan.get("verdict_detail") or "The page did not load properly."
        bits = []
        for key, label in (("http_status", "HTTP"), ("html_len", "body"),
                           ("page_title", "title"), ("final_url", "landed on")):
            v = scan.get(key)
            if v not in (None, "", 0):
                bits.append(f"{label} {v}" if key != "html_len"
                            else f"body {v} bytes")
        if scan.get("challenged"):
            bits.insert(0, "a bot-protection challenge was served")
        # The diagnosis travels WITH the row. Otherwise the next run has to
        # guess at the same wall, which is how this went three builds without
        # anyone noticing the findings were about a challenge page.
        return _unanswered(
            CONS_IDS,
            " ".join(str(why).split())
            + (f" ({'; '.join(bits)})" if bits else ""),
            "Capture the page with the Site Scanner extension — it runs in a "
            "real signed-in browser, which is what these sites are checking "
            "for.")

    basic = (scan.get("mode") or "basic") != "full"
    out = {}

    # ---- CONS-01 is answerable from HTML alone, so it always reports --------
    cmps = scan.get("cmps") or []
    from .scanner import NOTICE_ONLY_CMP
    # A BAR WITH AN "OK" BUTTON IS NOT A CONSENT PLATFORM.
    #
    # The scanner distinguishes three things and this file counted them as
    # one. `NOTICE_ONLY_CMP` is a banner with an accept or dismiss control and
    # no reject and no preferences — it informs, it collects nothing, and it
    # offers no opt-out, so under the state laws that require one it is worth
    # exactly as much as no banner. "Unrecognized consent banner" is the other
    # side: something with real choices whose vendor we cannot name.
    #
    # Counting any entry in `cmps` as a Pass meant a notice-only bar reported
    # "Notice-only banner is installed on this site — Pass", which is a green
    # row on the one finding most likely to matter legally.
    real = [c for c in cmps if c.get("name") != NOTICE_ONLY_CMP]
    notice_only = [c for c in cmps if c.get("name") == NOTICE_ONLY_CMP]
    if real:
        names = ", ".join(c.get("name", "?") for c in real)
        # Carry the evidence and the operator note through. `evidence` is the
        # script domains, JS globals and cookies that matched; `notes` is the
        # per-CMP warning, e.g. OneTrust firing its event on every page view
        # including reject, or Usercentrics rendering in shadow DOM.
        out["CONS-01"] = _f(
            "Pass", {"cmps": [c.get("name") for c in real],
                     "gtm_event": next((c.get("gtm_event") for c in real
                                        if c.get("gtm_event")), None),
                     "evidence": [x for c in real
                                  for x in (c.get("evidence") or [])][:12],
                     "notes": [c["notes"] for c in real if c.get("notes")]},
            f"{names} {_plural(len(real), 'is', 'are')} installed on this site.",
            "Low")
    elif notice_only:
        out["CONS-01"] = _f(
            "Fail", {"cmps": [NOTICE_ONLY_CMP], "notice_only": True},
            "The banner on this site informs but does not ask. It offers no "
            "reject control and no preferences, so nothing on the page lets a "
            "visitor opt out.", "High",
            "Replace it with a consent platform that offers a reject control. "
            "Several state laws require an opt-out mechanism, and a notice bar "
            "is not one.")
    else:
        # A custom-built banner with no known signature also lands here, which
        # is why this is a Warning with an instruction to look rather than a
        # flat Fail. The scanner's own README makes the same point.
        out["CONS-01"] = _f(
            "Warning", {"cmps": []},
            "No recognized consent management platform was found. Either there "
            "is none, or the banner is custom-built and carries no signature we "
            "know.", "High",
            "Confirm by hand. If there is genuinely no CMP, one is required "
            "before any of the consent checks below can pass.")

    if basic:
        # The scanner now records WHY full mode was unavailable. Printing
        # "re-run with the browser available" without saying what stopped it
        # is an instruction with no next step attached — the reason lived in
        # the worker's log, which is gone by the time anyone reads the report.
        why = " ".join(str(scan.get("full_scan_error") or "").split())
        # CAUSE FIRST. Any display that truncates should lose the explanation
        # of what a basic scan is — which never changes — before it loses the
        # exception, which is the only part that tells anyone what to do.
        out.update(_unanswered(
            _NEEDS_BROWSER,
            (f"The browser did not start on the worker — {why} — so this fell "
             f"back to a basic scan of the raw HTML, which cannot see the "
             f"banner, Consent Mode, or what fired before consent."
             if why else
             "This ran as a basic scan — raw HTML with no browser — which "
             "cannot see the banner, Consent Mode, or what fired before "
             "consent."),
            "This is a worker deployment problem, not a client one."
            if why else
            "Re-run with the browser available on the worker."))

    # ---- CONS-02 banner actually appears -----------------------------------
    if not basic:
        vis = scan.get("banner_visible")
        if vis is True:
            out["CONS-02"] = _f("Pass", {"visible": True},
                                "The consent banner appears on load.", "Low")
        elif vis is False:
            out["CONS-02"] = _f(
                "Fail", {"visible": False},
                "A consent platform is installed but no banner appeared. An "
                "installed CMP that never shows is the same as no CMP for "
                "compliance purposes.", "Critical",
                "Check the CMP's geo-targeting and publish state — a banner "
                "restricted to the EU does nothing for US state law.")
        else:
            out["CONS-02"] = _f(
                "Need Access", {}, "The scan could not determine whether a "
                "banner appeared.", "Low",
                "Load the page and look.", 0.0, "consent_unknown")

    # ---- CONS-03 Consent Mode defaults -------------------------------------
    if not basic:
        cm = scan.get("consent_mode_default")
        defaults = scan.get("consent_defaults") or {}
        if cm is True:
            denied = [k for k, v in defaults.items() if str(v).lower() == "denied"]
            out["CONS-03"] = _f(
                "Pass", {"defaults": defaults},
                f"Google Consent Mode defaults are set"
                + (f", denying {', '.join(sorted(denied))} until consent."
                   if denied else "."), "Low")
        elif cm is False:
            out["CONS-03"] = _f(
                "Fail", {"defaults": defaults},
                "Google Consent Mode defaults are not set, so Google tags "
                "behave as though consent were granted until told otherwise.",
                "High",
                "Set default consent to denied for ad_storage and "
                "analytics_storage, before the tags load.")
        else:
            out["CONS-03"] = _f("Need Access", {},
                                "Consent Mode state could not be determined.",
                                "Low", "", 0.0, "consent_unknown")

    # ---- CONS-04 pre-consent fires -----------------------------------------
    if not basic:
        pre = scan.get("pre_consent") or []
        # The scanner already separates a real violation from an expected
        # cookieless ping carrying a denied gcs= parameter. Respect that
        # classification rather than counting rows.
        bad = [p for p in pre
               if str(p.get("severity", "")).lower() not in ("info", "informational")]

        # PRE-CONSENT IS NOT THE WHOLE LIST, AND THAT PRODUCED A FALSE PASS.
        #
        # `_dedupe_product_pixels` removes every ungated pre-consent row whose
        # URL matches one of the client's product pixels, so it can be shown
        # once under Product pixels instead of twice. "ungated" is the severity
        # the scanner gives EVERY pre-consent tracker when there is no CMP at
        # all. So on a site with no consent platform running Meta and GA4 —
        # about as bad as this gets — both rows got claimed by a product and
        # stripped, `pre_consent` came back empty, and this reported:
        #
        #     Pass. No advertising or analytics tags contacted their servers
        #     before consent.
        #
        # The standalone tool gets away with the dedupe because it renders the
        # products section right underneath. This file never read `products`.
        ungated = []
        for prod in (scan.get("products") or []):
            for px in (prod.get("pixels") or []):
                if px.get("fired_pre") and str(px.get("severity", "")).lower() \
                        not in ("info", "informational"):
                    ungated.append({"vendor": px.get("name") or prod.get("product"),
                                    "url": px.get("sample_url"),
                                    "product": prod.get("product"),
                                    "src": px.get("src"),
                                    "severity": px.get("severity")})
        bad = bad + [u for u in ungated
                     if u["url"] not in {p.get("url") for p in bad}]

        if not pre and not ungated:
            out["CONS-04"] = _f("Pass", {"pre_consent": 0},
                                "No advertising or analytics tags contacted "
                                "their servers before consent.", "Low")
        elif not bad:
            out["CONS-04"] = _f(
                "Pass", {"pre_consent": len(pre), "informational": len(pre)},
                f"{len(pre)} Google {_plural(len(pre), 'request')} appeared "
                f"before consent, all carrying a denied Consent Mode flag — "
                f"expected cookieless pings, not tracking.", "Low")
        else:
            vendors = sorted({p.get("vendor") or "?" for p in bad})
            # `src` is the fact that decides who does the work: "page" means
            # the tag is hardcoded in the theme and a developer has to move it;
            # "runtime" means GTM injected it and the fix is a consent check in
            # the container. Dropping it made every recommendation the same
            # sentence regardless of which was true.
            by_src = {}
            for p in bad:
                by_src.setdefault(p.get("src") or "unknown", []).append(
                    p.get("vendor") or "?")
            out["CONS-04"] = _f(
                "Fail", {"pre_consent": len(bad),
                         "vendors": vendors,
                         "by_source": {k: sorted(set(v))
                                       for k, v in by_src.items()},
                         "examples": [p.get("url") for p in bad][:8]},
                f"{len(bad)} {_plural(len(bad), 'tracker')} fired before any "
                f"consent interaction: {', '.join(vendors)}.", "Critical",
                _cons04_rec(by_src))

    # ---- CONS-05 reject respected ------------------------------------------
    if not basic:
        if not scan.get("reject_tested"):
            out["CONS-05"] = _f(
                "Need Access", {},
                "The scan could not find a Reject control to test.", "Low",
                "If the banner offers no reject option, that is itself the "
                "finding under several state laws.", 0.0, "consent_unknown")
        else:
            after = scan.get("post_reject") or []
            if after:
                vendors = sorted({p.get("vendor") or "?" for p in after})
                out["CONS-05"] = _f(
                    "Fail", {"vendors": vendors, "count": len(after)},
                    f"{len(after)} {_plural(len(after), 'tracker')} still fired "
                    f"after Reject was clicked: {', '.join(vendors)}.",
                    "Critical",
                    "Reject must stop these. A reject button that changes "
                    "nothing is worse than none — it documents intent.")
            else:
                out["CONS-05"] = _f("Pass", {},
                                    "Clicking Reject stopped the advertising "
                                    "and analytics tags.", "Low")

    # ---- CONS-06 Global Privacy Control ------------------------------------
    if not basic:
        if not scan.get("gpc_tested"):
            out["CONS-06"] = _f("Need Access", {},
                                "Global Privacy Control was not tested on this "
                                "scan.", "Low", "", 0.0, "consent_unknown")
        else:
            fires = scan.get("gpc_fires") or []
            if fires:
                vendors = sorted({p.get("vendor") or "?" for p in fires})
                out["CONS-06"] = _f(
                    "Fail", {"vendors": vendors, "count": len(fires)},
                    f"Advertising tags fired despite a Global Privacy Control "
                    f"signal: {', '.join(vendors)}. California, Colorado and "
                    f"Connecticut require GPC to be honored as an opt-out.",
                    "Critical",
                    "Wire the GPC signal to your opt-out logic, not only to the "
                    "banner.")
            else:
                out["CONS-06"] = _f("Pass", {},
                                    "A Global Privacy Control signal was "
                                    "honored — no advertising tags fired.",
                                    "Low")

    # ---- CONS-07 opt-out link ----------------------------------------------
    link = scan.get("optout_link")
    if link:
        out["CONS-07"] = _f("Pass", {"link_text": link},
                            f"An opt-out link is present, labelled "
                            f"“{link}”.", "Low")
    else:
        out["CONS-07"] = _f(
            "Warning", {},
            "No “Do Not Sell or Share” style opt-out link was found "
            "on this page. Several state laws require one in the footer of "
            "every page.", "High",
            "Add a clearly labelled opt-out link to the site footer.")

    # ---- CONS-08 state law ---------------------------------------------------
    checks = scan.get("state_checks") or []
    # "US" IS NOT A STATE, AND SAYING SO IS THE WHOLE FIX HERE.
    #
    # The scanner always emits one universal row — the privacy-policy link,
    # tagged state "US" — and then one row per requirement per state that was
    # actually requested. Because nothing ever requested a state, "US" was the
    # only row that ever arrived, and this checkpoint, titled "State privacy
    # law requirements", reported: "All 1 checked requirements are met across
    # US." A privacy-policy-link check wearing a state-law label, reported as
    # a clean pass on twenty states nobody had looked at.
    real = [c for c in checks if (c.get("state") or "US") != "US"]
    states = sorted({c.get("state") for c in real if c.get("state")})
    if not real:
        out["CONS-08"] = _f(
            "Need Access", {"universal_only": True},
            "No states were selected, so no state requirement was checked. "
            "The scan still confirmed the site-wide items that apply "
            "everywhere.", "Low",
            "Add the states the client sells into on the audit form — twelve "
            "of the twenty supported require Global Privacy Control to be "
            "honored, and that test only runs when one of them is listed.",
            0.0, "consent_unknown")
    else:
        fails = [c for c in real
                 if str(c.get("status", "")).lower() in ("fail", "failed", "no")]
        out["CONS-08"] = _f(
            "Fail" if fails else "Pass",
            {"states": states, "checks": len(real), "failing": len(fails),
             # `detail` is the scanner's own explanation of the requirement,
             # three to eight sentences with the statute context. It was being
             # thrown away and replaced with "CA: GPC signal", which names the
             # row without saying what is wrong or why it matters.
             "failures": [{"state": c.get("state"), "check": c.get("check"),
                           "detail": c.get("detail")} for c in fails][:12]},
            f"{len(fails)} of {len(real)} state requirements are not met "
            f"across {', '.join(states)}." if fails else
            f"All {len(real)} checked requirements are met across "
            f"{', '.join(states)}.",
            "Critical" if fails else "Low",
            "Each failing item below names the state, the requirement and why "
            "it applies." if fails else "")

    # ---- CONS-09 GTM consent trigger ---------------------------------------
    gtm = scan.get("gtm") or {}
    event = next((c.get("gtm_event") for c in cmps if c.get("gtm_event")), None)
    if gtm.get("found") and event:
        ids = gtm.get("container_ids") or []
        where = ", ".join(ids) or "container id not exposed"
        out["CONS-09"] = _f(
            "Pass", {"containers": ids, "event": event},
            f"Tag Manager is present ({where}) and the CMP fires "
            f"“{event}”, which is the trigger to gate tags on.",
            "Low")
    elif gtm.get("found"):
        out["CONS-09"] = _f(
            "Warning", {"containers": gtm.get("container_ids") or []},
            "Tag Manager is present but the consent platform publishes no "
            "custom event to trigger on, so tags cannot be gated cleanly.",
            "Medium",
            "Use the CMP's API callback, or switch to a platform that emits a "
            "dataLayer event.")
    elif gtm.get("gtag_only"):
        # gtag.js with no container is a materially different situation from
        # "no Google tagging at all", and this file reported them identically.
        # There is nowhere to add a consent check, because there is no
        # container — every fix is a code change.
        ids = gtm.get("gtag_ids") or []
        out["CONS-09"] = _f(
            "Warning", {"gtag_only": True, "gtag_ids": ids},
            f"Google tags load through gtag.js directly"
            + (f" ({', '.join(ids)})" if ids else "")
            + " with no Tag Manager container, so there is no container to "
              "add a consent check to.", "Medium",
            "Either set Consent Mode defaults in the page code before gtag.js "
            "loads, or move the tags into a container where the gating can be "
            "configured and verified rather than hand-written.")
    else:
        out["CONS-09"] = _f(
            "Warning", {},
            "No Tag Manager container was found, so consent gating has to be "
            "handled in the page code itself.", "Medium",
            "Tag Manager is not required, but it is where consent gating is "
            "easiest to get right and to verify.")

    for cid in CONS_IDS:
        out.setdefault(cid, _f("Need Access", {},
                               "Not reported by the consent scan.", "Low",
                               "", 0.0, "consent_unknown"))
    return out
