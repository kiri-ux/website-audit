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

    basic = (scan.get("mode") or "basic") != "full"
    out = {}

    # ---- CONS-01 is answerable from HTML alone, so it always reports --------
    cmps = scan.get("cmps") or []
    if cmps:
        names = ", ".join(c.get("name", "?") for c in cmps)
        out["CONS-01"] = _f(
            "Pass", {"cmps": [c.get("name") for c in cmps],
                     "gtm_event": next((c.get("gtm_event") for c in cmps
                                        if c.get("gtm_event")), None)},
            f"{names} {_plural(len(cmps), 'is', 'are')} installed on this site.",
            "Low")
    else:
        # A custom-built banner with no known signature also lands here, which
        # is why this is a Warning with an instruction to look rather than a
        # flat Fail. The scanner's own README makes the same point.
        out["CONS-01"] = _f(
            "Warning", {"cmps": []},
            "No recognised consent management platform was found. Either there "
            "is none, or the banner is custom-built and carries no signature we "
            "know.", "High",
            "Confirm by hand. If there is genuinely no CMP, one is required "
            "before any of the consent checks below can pass.")

    if basic:
        out.update(_unanswered(
            _NEEDS_BROWSER,
            "This ran as a basic scan — raw HTML with no browser — which "
            "cannot see the banner, Consent Mode, or what fired before "
            "consent.",
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
        if not pre:
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
            out["CONS-04"] = _f(
                "Fail", {"pre_consent": len(bad),
                         "vendors": vendors,
                         "examples": [p.get("url") for p in bad][:8]},
                f"{len(bad)} {_plural(len(bad), 'tracker')} fired before any "
                f"consent interaction: {', '.join(vendors)}.", "Critical",
                "Gate these behind the CMP's consent event. Until then the "
                "banner is decorative.")

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
                    f"Connecticut require GPC to be honoured as an opt-out.",
                    "Critical",
                    "Wire the GPC signal to your opt-out logic, not only to the "
                    "banner.")
            else:
                out["CONS-06"] = _f("Pass", {},
                                    "A Global Privacy Control signal was "
                                    "honoured — no advertising tags fired.",
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
    if not checks:
        out["CONS-08"] = _f(
            "N/A", {},
            "No state privacy requirements were selected for this scan.",
            "Low", "", 0.9)
    else:
        fails = [c for c in checks
                 if str(c.get("status", "")).lower() in ("fail", "failed", "no")]
        states = sorted({c.get("state") for c in checks if c.get("state")})
        out["CONS-08"] = _f(
            "Fail" if fails else "Pass",
            {"states": states, "checks": len(checks), "failing": len(fails),
             "detail": [f"{c.get('state')}: {c.get('check')}" for c in fails][:10]},
            f"{len(fails)} of {len(checks)} state requirements are not met "
            f"across {', '.join(states)}." if fails else
            f"All {len(checks)} checked requirements are met across "
            f"{', '.join(states)}.",
            "Critical" if fails else "Low",
            "Each failing item below names the state and the requirement."
            if fails else "")

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
