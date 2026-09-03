"""
Section 01 — Analytics & Tracking (ANA-01 … ANA-13).

The audit template marks all twelve of the original checks "Manual Review".
Every one is a pattern match over the scripts the crawler already collected.
This module is ~80 lines and eliminates twelve manual checks per audit.

ANA-13 was added separately (Sep 2026) — see the check itself for why.
"""
from __future__ import annotations
import re
from . import check, finding

# ---------------------------------------------------------------------------
# Which of these is a DEFECT depends on what the row is for.
#
# The first draft reported "LinkedIn Insight Tag not detected" as a Medium issue
# on every site, including clients who have never bought a LinkedIn ad. Paid
# media is a different team at Vici and often a different agency entirely, so
# those rows are now detected and reported but never scored as defects.
#
# Brendan's own template lists all twelve of these as a STATE ("Implemented")
# with a Priority column, not as a pass/fail. So:
#
#   CORE      — every site should have these. Absent is a real finding.
#   AD_PIXELS — paid media. Detected and reported, never a defect.
#   OPTIONAL  — genuinely nice-to-have. Absent is never a defect.
#   PHONE_LED — only a finding when the site actually sells by phone.
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

# Paid-media pixels. NEVER a finding, in either direction.
#
# Vici's paid team owns these, and the client may not be running that channel at
# all — so "Meta Pixel not detected" is at best noise and at worst an invoice
# for work nobody asked for. We still DETECT them, because knowing a pixel is
# present is useful context, but the row is informational: N/A when absent, Pass
# when present, never a defect and never in the roadmap.
AD_PIXELS = {"ANA-06": "Meta Pixel", "ANA-07": "LinkedIn Insight Tag",
             "ANA-08": "Google Ads Conversion Tracking",
             "ANA-09": "Google Ads Remarketing"}
OPTIONAL = {"ANA-04", "ANA-11"}          # analytics extras, never required
PHONE_LED = {"ANA-10"}                   # only if the business sells by phone


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
            return finding("Pass", val, f"{_l} detected on the site.",
                           [], "Low")

        # ---- absent ----
        if _cid in AD_PIXELS:
            return finding("N/A", val, "Not detected.", [], "Low", "", 1.0)

        if _cid in OPTIONAL:
            return finding("N/A", val,
                           "Not in use. Optional.", [], "Low", "", 1.0)

        if _cid in PHONE_LED:
            phone = bool(re.search(r"tel:\+?[\d\-\(\) ]{7,}",
                                   "\n".join((p.rendered_text or "")
                                              for p in a.pages.values())[:400000],
                                   re.I))
            if not phone:
                return finding("N/A", val,
                               "Not in use. No click-to-call links on the site.",
                               [], "Low", "", 1.0)
            return finding(
                "Not Implemented", val,
                "Not detected, but the site publishes click-to-call links — "
                "phone conversions are not being counted.",
                [], "Medium",
                "Add call tracking so phone conversions show up next to form fills.")

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
                   else "No Search Console verification tag in the page source. "
                        "Verification by DNS record or by an uploaded HTML file "
                        "leaves no trace we can see from outside, so this is not "
                        "evidence the site is unverified.",
                   [], "Medium",
                   # The collector overwrites this row whenever it can read the
                   # property — a working connection IS the verification. This
                   # branch is only reached when there is no connection at all.
                   "" if meta else "Confirmed either way once Search Console "
                                   "access is connected.",
                   # WHOSE PROBLEM AN UNANSWERED ANA-03 IS.
                   #
                   # Nobody's code. This check ran and answered: there is no
                   # verification tag in the source, and DNS or file
                   # verification leaves nothing visible from outside. What
                   # closes the row is the client adding us to the property.
                   # Without this the row inherited "we have a check for it,
                   # so an empty row is ours" from engine/access and printed
                   # under "a credential we have not set" - directly
                   # contradicting its own recommendation line two lines
                   # below. See CLIENT_DESPITE_REGISTRY.
                   source="" if meta else "needs_gsc_grant")


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


# ---------------------------------------------------------------------------
# ANA-13 — GTM container + hardcoded gtag('config') outside it
#
# Google is retiring gtm.js's support for gtag('config') commands that live
# outside the container — see support.google.com/tagmanager/answer/17231523
# (rollout is phased per account, not one universal date). Running GTM alone
# is fine. Running gtag.js alone with no container is fine. The break is the
# COMBINATION: a gtm.js container on the page AND a hardcoded
# gtag('config', 'G-...'/'AW-...'/'DC-...') call sitting in the site's own
# HTML/JS, outside anything the container itself injected. GTM stops
# recognizing that config call once the change reaches that container, and
# the tag it configures goes dark.
#
# Most common trigger, per the Aug–Sep 2026 Google Partners thread
# (UTVFX/CBX): a client already had their own GA4 installed directly before
# a Vici container tag was added on top of it, and the original snippet was
# never removed.
#
# Both halves of this pattern are static-source facts — a page either ships
# gtm.js and a hardcoded gtag('config', ...) call or it doesn't — so a plain
# crawl sees this without needing a live browser render.
# ---------------------------------------------------------------------------
_HARDCODED_GTAG_CONFIG_RE = re.compile(
    r"gtag\(\s*[\"']config[\"']\s*,\s*[\"'](?P<id>(?:G|AW|DC)-[A-Za-z0-9]+)[\"']",
    re.I)


@check("ANA-13")
def ana13(a, c):
    hay = c.setdefault("_tag_haystack", _haystack(a))
    has_container = bool(re.search(SIGNATURES["ANA-01"][1][0], hay, re.I)
                         or re.search(SIGNATURES["ANA-01"][1][1], hay, re.I))
    ids = sorted({m.group("id").upper()
                 for m in _HARDCODED_GTAG_CONFIG_RE.finditer(hay)})
    val = {"container_present": has_container,
           "hardcoded_gtag_config_ids": ids}
    are = "is" if len(ids) == 1 else "are"
    tag_word = "this tag" if len(ids) == 1 else "these tags"

    if has_container and ids:
        return finding(
            "Fail", val,
            f"A GTM container is installed on this site AND "
            f"{', '.join(ids)} {are} configured with a hardcoded "
            f"gtag('config', ...) call outside that container. Google is "
            f"retiring gtm.js support for this combination — the config "
            f"call stops being recognized once the change reaches this "
            f"container, and {tag_word} will stop firing.",
            [], "High",
            f"Have the client's dev team remove the hardcoded "
            f"gtag('config', ...) snippet(s) for {', '.join(ids)} from the "
            f"page template or CMS, and configure that tag inside the GTM "
            f"container instead. Check every page template and CMS plugin, "
            f"not just the homepage — this is most common when a client's "
            f"own GA4 was installed directly before a container tag was "
            f"added on top of it, and the original snippet was never "
            f"removed.")
    if has_container and not ids:
        return finding(
            "Pass", val,
            "A GTM container is present and no hardcoded gtag('config', "
            "...) call was found outside it — not the mixed setup Google "
            "is retiring support for.", [], "Low")
    if ids and not has_container:
        return finding(
            "N/A", val,
            f"{', '.join(ids)} {are} configured via gtag.js directly with "
            f"no GTM container present. That's Google's own supported "
            f"pattern, not the one being deprecated.", [], "Low")
    return finding(
        "N/A", val,
        "No GTM container or hardcoded gtag('config', ...) call detected.",
        [], "Low")
