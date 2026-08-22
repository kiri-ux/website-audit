"""
Search Console's UI-only reports, captured from a signed-in browser.

WHY THIS EXISTS
---------------
Eight checkpoints are published by Google in the Search Console interface and
exposed through no API: index coverage and its exclusion reasons, Core Web
Vitals, and the Enhancements reports. No credential fixes that. The report has
been honest about it — "Google publishes no API for this" — but honest and
unmeasured is still unmeasured, and someone was retyping numbers off a screen.

The extension already runs in the operator's own signed-in browser, which is
exactly the thing those reports require. So it reads them there.

WHAT THIS MODULE WILL NOT DO
----------------------------
It will not accept a number it cannot attribute. Every field is optional and a
missing one stays unmeasured — a capture that half-worked must not fill the
other half with zeros, because a zero here reads as "no pages excluded" and
that is a materially wrong statement about a site.

The labels below are the ones GOOGLE prints on the page, in English, for a
human to read. Anchoring on those is deliberate: they are the most stable thing
on a heavily obfuscated Angular app, far more so than any class name, and when
Google renames one the capture returns nothing for that row rather than
returning the wrong row's number.
"""
from __future__ import annotations

# The exclusion reasons Search Console lists under "Why pages aren't indexed",
# mapped to the checkpoints that ask about them. Google's wording, verbatim.
REASON_IDS = {
    "crawled - currently not indexed": "GSC-07",
    "discovered - currently not indexed": "GSC-08",
    "soft 404": "GSC-09",
    "server error (5xx)": "GSC-10",
    "server error": "GSC-10",
    "redirect error": "GSC-11",
}

CAPTURE_IDS = ("GSC-05", "GSC-06", "GSC-07", "GSC-08", "GSC-09", "GSC-10",
               "GSC-11", "GSC-12")

# How many excluded pages stops being housekeeping and starts being a finding.
# A site with a handful of soft 404s has a tidy-up; one with hundreds has a
# structural problem. Expressed as a share of the indexed count rather than an
# absolute, because 200 excluded pages means something different on a 50-page
# site and a 50,000-page one.
_SHARE_WARN = 0.25


def _f(status, value=None, evidence="", severity="Medium", rec="", conf=1.0):
    return {"status": status, "value": value or {}, "evidence": evidence,
            "affected_pages": [], "severity": severity, "recommendation": rec,
            "confidence": conf, "source": "gsc_ui_capture"}


def _int(v):
    """A count, or None. Accepts '1,234' and '1.2K' the way the UI prints them."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().replace(",", "").replace(" ", "")
    if not s:
        return None
    mult = 1
    if s[-1:].upper() in ("K", "M"):
        mult = 1000 if s[-1:].upper() == "K" else 1000000
        s = s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def findings_from_capture(cap: dict | None) -> dict:
    """
    Turn one console capture into checkpoint findings.

    `cap` is what the extension posts:

        {"indexed": 118, "not_indexed": 41,
         "reasons": {"Crawled - currently not indexed": 22, ...},
         "cwv": {"poor": 0, "needs_improvement": 6, "good": 112,
                 "metric": "LCP"},
         "captured_at": "2026-08-22T15:40:00Z",
         "property": "https://ootenlawfirm.com/"}

    Anything absent is simply not returned, so the caller merges it over the
    existing findings and the rows nobody captured stay exactly as they were.
    """
    out = {}
    if not cap:
        return out

    indexed = _int(cap.get("indexed"))
    excluded = _int(cap.get("not_indexed"))
    # Keep GOOGLE'S OWN CASING for display and lowercase only for the lookup.
    # Title-casing it produced "Crawled - Currently Not Indexed" and "Server
    # Error (5Xx)" — a quiet rewrite of the label the reader is about to go
    # and find on Google's own screen, which is the one thing that has to
    # match exactly.
    reasons = [(str(k).strip(), _int(v))
               for k, v in (cap.get("reasons") or {}).items()]

    if indexed is not None:
        out["GSC-05"] = _f(
            "Info", {"indexed": indexed, "captured_from": "Search Console UI"},
            f"Search Console reports {indexed:,} indexed "
            f"{'page' if indexed == 1 else 'pages'}.", "Low")

    if excluded is not None:
        total = (indexed or 0) + excluded
        share = (excluded / total) if total else 0
        heavy = share >= _SHARE_WARN and excluded >= 10
        out["GSC-06"] = _f(
            "Warning" if heavy else "Info",
            {"not_indexed": excluded, "indexed": indexed,
             "share_not_indexed": round(share, 3)},
            f"{excluded:,} of {total:,} known "
            f"{'page is' if total == 1 else 'pages are'} not indexed"
            + (f" ({share:.0%} of everything Google knows about)."
               if total else "."),
            "Medium" if heavy else "Low",
            "Open the exclusion reasons below — the large ones are usually "
            "one template, not a thousand separate problems." if heavy else "")

    for label, n in reasons:
        cid = REASON_IDS.get(label.lower())
        if not cid or n is None:
            continue
        # A COUNT IS NOT A VERDICT.
        #
        # Zero is a clean pass. Anything else is reported as a measurement
        # with the number attached, and only a large share earns a Warning —
        # every site of any age has a few of these, and calling nine soft 404s
        # a failure trains people to skip the row.
        pretty = label
        if n == 0:
            out[cid] = _f("Pass", {"count": 0},
                          f"No pages in Search Console's "
                          f"“{pretty}” report.", "Low")
        else:
            big = indexed and n >= max(10, indexed * 0.1)
            out[cid] = _f(
                "Warning" if big else "Info",
                {"count": n, "indexed": indexed},
                f"{n:,} {'page' if n == 1 else 'pages'} in Search Console's "
                f"“{pretty}” report.",
                "Medium" if big else "Low",
                "Worth opening — a count this size is usually one template "
                "rather than many separate pages." if big else "")

    cwv = cap.get("cwv") or {}
    poor, ni = _int(cwv.get("poor")), _int(cwv.get("needs_improvement"))
    good = _int(cwv.get("good"))
    if poor is not None or ni is not None:
        poor, ni = poor or 0, ni or 0
        metric = str(cwv.get("metric") or "").strip()
        out["GSC-12"] = _f(
            "Fail" if poor else ("Warning" if ni else "Pass"),
            {"poor": poor, "needs_improvement": ni, "good": good,
             "metric": metric or None},
            (f"{poor:,} URL {'group' if poor == 1 else 'groups'} rated Poor"
             + (f" and {ni:,} Needs improvement" if ni else "")
             + (f", on {metric}" if metric else "") + "."
             if poor or ni else
             "No URL groups rated Poor or Needs improvement."),
            "High" if poor else ("Medium" if ni else "Low"),
            "Core Web Vitals groups URLs by template, so one fix usually "
            "moves a whole group." if poor or ni else "")

    # Provenance travels with every row. A number read off a screen and a
    # number pulled from an API are not the same kind of fact, and six months
    # from now nobody will remember which this was.
    when = str(cap.get("captured_at") or "").strip()
    for f in out.values():
        f["value"]["captured_from"] = "Search Console UI"
        if when:
            f["value"]["captured_at"] = when
    return out
