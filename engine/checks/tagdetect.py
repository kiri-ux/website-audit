"""
Section 01 — Analytics & Tracking (ANA-01 … ANA-12).

The audit template marks all twelve of these "Manual Review". Every one is a
pattern match over the scripts the crawler already collected. This module is
~80 lines and eliminates twelve manual checks per audit.
"""
from __future__ import annotations
import re
from . import check, finding

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


def _haystack(art) -> str:
    parts = []
    for p in art.pages.values():
        parts.extend(p.scripts)
        parts.append(p.inline_script_text or "")
        parts.extend(h for h in (p.headers or {}).values() if isinstance(h, str))
    return "\n".join(parts)


def _make(cid, label, patterns):
    @check(cid)
    def _fn(a, c, _l=label, _p=patterns):
        hay = c.setdefault("_tag_haystack", _haystack(a))
        hits = [pat for pat in _p if re.search(pat, hay, re.I)]
        found = bool(hits)
        return finding(
            "Pass" if found else "Not Implemented",
            {"implemented": found, "matched": hits[:3]},
            f"{_l} detected on the site." if found
            else f"{_l} not detected in page scripts, inline JS, or response headers.",
            [], "Low" if found else "Medium",
            "" if found else f"Implement {_l} to close a measurement gap.")
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
