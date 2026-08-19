"""
Section 01 — Analytics & Tracking (ANA-01 … ANA-12).

The audit template marks all twelve of these "Manual Review". Every one is a
pattern match over the scripts the crawler already collected. This module is
~80 lines and eliminates twelve manual checks per audit.
"""
from __future__ import annotations
import re
from . import check, finding

# ---------------------------------------------------------------------------
# Which of these is a DEFECT depends on what the client actually runs.
#
# The first draft reported "LinkedIn Insight Tag not detected" as a Medium
# issue on every site — including clients who have never bought a LinkedIn ad.
# Recommending a pixel for a channel someone does not use is noise at best, and
# it is the kind of wrong that makes a client distrust the rest of the document.
#
# Brendan's own template lists these as a STATE ("Implemented") with a
# Priority column, not as a pass/fail. So:
#
#   CORE     — every site should have these. Absent is a real finding.
#   CHANNEL  — only meaningful if the client runs that channel. Absent is N/A
#              unless we have evidence they run it, and then it is a real gap:
#              spending on a channel you cannot measure is worse than not
#              running it.
#   OPTIONAL — genuinely nice-to-have. Absent is never a defect.
#
# "Evidence they run it" is either the intake (`channels` on the audit) or a
# sibling tag from the same platform showing up in the page source. If the
# Meta Pixel is installed, they run Meta — we do not need to be told.
# ---------------------------------------------------------------------------
SIGNATURES = {
    "ANA-01": ("Google Tag Manager",
               [r"googletagmanager\.com/gtm\.js", r"GTM-[A-Z0-9]{4,}"]),
    "ANA-02": ("Google Analytics 4",
               [r"gtag/js\?id=G-", r"\bG-[A-Z0-9]{8,}\b", r"googletagmanager\.com/gtag"]),
    "ANA-04": ("Microsoft Clarity", [r"clarity\.ms"]),
    "ANA-06": ("Meta Pixel",
               [r"connect\.facebook\.net", r"\bfbq\s*\(", r"facebook\.com/tr\?"]),
    "ANA-07": ("LinkedIn Insight Tag",
               [r"snap\.licdn\.com", r"_linkedin_partner_id"]),
    "ANA-08": ("Google Ads Conversion Tracking",
               [r"googleadservices\.com/pagead/conversion", r"gtag\([\"']event[\"'],\s*[\"']conversion"]),
    "ANA-09": ("Google Ads Remarketing",
               [r"google_remarketing_only", r"googleads\.g\.doubleclick\.net",
                r"googleadservices\.com/pagead/conversion_async"]),
    "ANA-10": ("Call Tracking",
               [r"callrail\.com", r"calltrk\.com", r"whatconverts\.com",
                r"marchex\.com", r"invoca\.net", r"calltrackingmetrics\.com",
                r"phonewagon", r"dialogtech"]),
    "ANA-11": ("Heatmap / Session Recording",
               [r"clarity\.ms", r"static\.hotjar\.com", r"mouseflow\.com",
                r"luckyorange\.com", r"crazyegg\.com", r"fullstory\.com",
                r"smartlook\.com", r"inspectlet\.com"]),
    "ANA-12": ("Cookie Consent / CMP",
               [r"onetrust", r"cookiebot", r"cookieyes", r"termly\.io",
                r"iubenda", r"osano", r"quantcast.*choice", r"cookie-?consent",
                r"complianz", r"cookie-?law-?info"]),
}

CORE = {"ANA-01", "ANA-02", "ANA-12"}
CHANNEL = {"ANA-06": "meta", "ANA-07": "linkedin",
           "ANA-08": "google_ads", "ANA-09": "google_ads"}
OPTIONAL = {"ANA-04", "ANA-11"}          # analytics extras, never required
PHONE_LED = {"ANA-10"}                   # only if the business sells by phone

CHANNEL_LABEL = {"meta": "Meta (Facebook/Instagram) ads",
                 "linkedin": "LinkedIn ads", "google_ads": "Google Ads"}


def _channels_in_use(a, c) -> set:
    """
    Channels we have EVIDENCE for: named at intake, or a sibling tag detected.

    Detection beats intake here rather than the other way round — a tag in the
    page source is a fact, an intake field is a memory.
    """
    if "_channels" in c:
        return c["_channels"]
    stated = {str(x).strip().lower().replace(" ", "_")
              for x in (c.get("channels") or []) if str(x).strip()}
    hay = c.setdefault("_tag_haystack", _haystack(a))
    for cid, chan in CHANNEL.items():
        pats = SIGNATURES[cid][1]
        if any(re.search(p, hay, re.I) for p in pats):
            stated.add(chan)
    c["_channels"] = stated
    return stated


def _haystack(art) -> str:
    parts = []
    for p in art.pages.values():
        parts.extend(p.scripts)
        parts.append(p.inline_script_text or "")
        parts.extend(h for h in (p.headers or {}).values() if isinstance(h, str))
    return "\n".join(parts)


def _make(cid, label, patterns):
    @check(cid)
    def _fn(a, c, _cid=cid, _l=label, _p=patterns):
        hay = c.setdefault("_tag_haystack", _haystack(a))
        hits = [pat for pat in _p if re.search(pat, hay, re.I)]
        found = bool(hits)
        val = {"implemented": found, "matched": hits[:3]}

        if found:
            return finding("Pass", val, f"{_l} detected on the site.", [], "Low")

        # ---- absent. Whether that is a problem depends on the client. ----
        if _cid in OPTIONAL:
            return finding("N/A", val, "Not in use. Optional.", [], "Low", "", 1.0)

        if _cid in PHONE_LED:
            # Only relevant if the phone is a real conversion path. A published
            # number on the page is the evidence for that.
            phone = bool(re.search(r"tel:\+?[\d\-\(\) ]{7,}", 
                                   "\n".join((p.rendered_text or "") + 
                                              " ".join(str(x) for x in (p.links_internal or []))
                                              for p in a.pages.values())[:400000], re.I))
            if not phone:
                return finding("N/A", val,
                               "Not in use. No click-to-call links on the site.",
                               [], "Low", "", 1.0)
            return finding(
                "Not Implemented", val,
                f"{_l} not detected, but the site publishes click-to-call links. "
                f"Calls are converting and nothing is counting them.",
                [], "Medium",
                "Add call tracking so phone conversions show up next to form fills.")

        chan = CHANNEL.get(_cid)
        if chan:
            in_use = _channels_in_use(a, c)
            if chan not in in_use:
                # One line. If it is not installed and does not apply, a
                # paragraph explaining why is just noise in a 313-row table.
                return finding("N/A", val,
                               f"Not in use. Only needed if you run "
                               f"{CHANNEL_LABEL.get(chan, chan)}.",
                               [], "Low", "", 1.0)
            # They DO run this channel. Missing measurement is now a real gap.
            return finding(
                "Not Implemented", val,
                f"{_l} not detected, but you are running "
                f"{CHANNEL_LABEL.get(chan, chan)} — that spend cannot be "
                f"attributed without it.",
                [], "High",
                f"Install {_l} so {CHANNEL_LABEL.get(chan, chan)} conversions "
                f"are measurable.")

        # CORE
        return finding(
            "Not Implemented", val,
            f"{_l} not detected in page scripts, inline JS, or response headers.",
            [], "Medium", f"Implement {_l} to close a measurement gap.")
    return _fn


for _cid, (_label, _pats) in SIGNATURES.items():
    _make(_cid, _label, _pats)


@check("ANA-03")
def ana03(a, c):
    """Search Console verification — meta tag or DNS/file token is the only
    client-side signal available without API access."""
    hay = "\n".join((p.inline_script_text or "") + " ".join(p.scripts)
                    for p in a.pages.values())
    meta = re.search(r"google-site-verification", hay, re.I)
    return finding("Pass" if meta else "Need Access", {"meta_verification": bool(meta)},
                   "Search Console verification meta tag present." if meta
                   else "Cannot confirm Search Console access without client credentials.",
                   [], "Medium",
                   "" if meta else "Request Search Console access from the client.")


@check("ANA-05")
def ana05(a, c):
    hay = "\n".join((p.inline_script_text or "") + " ".join(p.scripts)
                    for p in a.pages.values())
    found = bool(re.search(r"msvalidate\.01|bat\.bing\.com|clarity\.ms", hay, re.I))
    return finding("Pass" if found else "Not Implemented", {"implemented": found},
                   "Bing Webmaster / Microsoft tooling signal detected." if found
                   else "No Bing Webmaster Tools verification or Bing UET tag detected.",
                   [], "Low" if found else "Medium",
                   "" if found else "Verify the site in Bing Webmaster Tools — it also feeds Copilot.")
