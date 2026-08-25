"""
A consent scan assembled from what the EXTENSION saw, not from Playwright.

WHY THIS EXISTS
---------------
The scanner's known dead end is bot protection. `_looks_challenged` catches
SiteGround's sgcaptcha, Cloudflare and friends, and the honest response is to
fall back to `basic_scan` — raw HTML, no browser. That fallback loses banner
visibility, Consent Mode defaults, pre-consent fires AND the reject test, which
is three and a half of the four questions the scanner exists to answer. On a
challenged site the tool reports almost nothing.

The audit already solved the same problem for crawling: an extension running in
the operator's own Chrome, on their own IP, with their own cookies, which
challenge pages let through because it is a person. This does the consent
version of that.

THE SPLIT THAT MAKES IT CHEAP
-----------------------------
The scanner is two halves that were never separated because nothing needed them
apart: DRIVING a browser, and CLASSIFYING what came back. The classification
half — CMP fingerprints, tracker endpoints, `gcs=` denied-state parsing, GTM
container detection — is already browser-free, so it is reused here verbatim.

That matters more than the code saved. If the two paths classified
independently, the same site could come back "OneTrust, 2 pre-consent fires"
through Playwright and "no CMP, clean" through the extension, and there would be
no way to tell which was lying. One classifier, two sources of raw material.

WHAT THE EXTENSION MUST SEND
----------------------------
    {
      "url": str,
      "html": str,                  final rendered HTML
      "pre_requests":  [url, ...]   every request before any interaction
      "post_requests": [url, ...]   requests after Accept was clicked
      "reject_requests": [url, ...] requests after Reject, if it was tested
      "gpc_requests":  [url, ...]   requests on a load with GPC set
      "banner_visible": bool | None
      "consent_defaults": {"ad_storage": "denied", ...}
      "accept_clicked": bool,
      "reject_clicked": bool,
      "scripts": [url, ...]         script srcs, for CMP fingerprinting
    }

Anything missing is reported as unknown rather than guessed — the same rule the
Playwright path follows when a step does not complete.
"""
from __future__ import annotations
from datetime import datetime, timezone

from .scanner import (_empty_result, _match_domains, _cmp_by_name,
                      _classify_tracker, _gcs_denied, _gtm_info, normalize_url,
                      _apply_verdict, _dedupe_product_pixels,
                      products_and_containers, state_checks_for,
                      _category_checks)
from .state_checks import OPTOUT_LINK_PHRASES


def _fires(urls, exclude_denied_pings=True):
    """
    Classify a list of request URLs into tracker hits.

    `exclude_denied_pings` marks a Google request carrying a denied-state `gcs=`
    parameter as informational rather than a violation — the same call the
    Playwright path makes, and the reason a correctly configured Consent Mode
    site does not report as failing.
    """
    out = []
    for u in urls or []:
        t = _classify_tracker(u)
        if not t:
            continue
        sev = t.get("severity", "high")
        if exclude_denied_pings and _gcs_denied(u):
            sev = "info"
        out.append({"vendor": t.get("vendor") or t.get("name"),
                    "url": u[:300], "severity": sev,
                    "note": t.get("note", "")})
    return out


def _optout(html: str):
    low = (html or "").lower()
    for phrase in OPTOUT_LINK_PHRASES:
        if phrase.lower() in low:
            return phrase
    return None


def result_from_capture(cap: dict, states=None, products=None,
                        industries=None) -> dict:
    """
    Build the standard scan result dict from an extension capture.

    `states`, `products` and `industries` come from the AUDIT, not from the
    capture. The extension has no business knowing which statutes a client
    sells under or which pixels they pay for, and asking the operator to
    retype them into a popup is how the two drift apart. The API reads them
    off the stored options and passes them in.
    """
    url = normalize_url(cap.get("url") or "") or (cap.get("url") or "")
    r = _empty_result(url)
    r["scanned_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    # "full" is the truth: a real browser rendered this and clicked the banner.
    # Reporting it as basic would make the adapter withhold every row the
    # capture went to the trouble of answering.
    r["mode"] = "full"
    r["ok"] = True
    r["source"] = "extension"

    html = cap.get("html") or ""
    r["html_len"] = len(html)
    corpus = html + "\n" + "\n".join(cap.get("scripts") or [])

    # ---- which CMP -------------------------------------------------------
    for name, evidence in _match_domains(corpus).items():
        c = _cmp_by_name(name) or {}
        r["cmps"].append({"name": name, "evidence": evidence,
                          "gtm_event": c.get("gtm_event"),
                          "notes": c.get("notes", "")})
    r["gtm"] = _gtm_info(corpus)

    # ---- what the browser saw -------------------------------------------
    vis = cap.get("banner_visible")
    r["banner_visible"] = vis if isinstance(vis, bool) else "unknown"

    defaults = cap.get("consent_defaults") or {}
    r["consent_defaults"] = defaults
    # A capture that reported defaults knows the answer either way; one that
    # could not read the dataLayer at all must not be scored as "no defaults".
    if cap.get("consent_defaults_read"):
        r["consent_mode_default"] = bool(defaults)
    else:
        r["consent_mode_default"] = "unknown"

    r["pre_consent"] = _fires(cap.get("pre_requests"))
    r["accept_clicked"] = bool(cap.get("accept_clicked"))
    if r["accept_clicked"]:
        pre_urls = set(cap.get("pre_requests") or [])
        after = [u for u in (cap.get("post_requests") or []) if u not in pre_urls]
        # Vendors that fired ONLY after Accept are the gated-correctly ones —
        # this is the "is the pixel actually working" half of the question.
        r["post_consent"] = sorted({f["vendor"] for f in _fires(after)})

    r["reject_tested"] = bool(cap.get("reject_clicked"))
    if r["reject_tested"]:
        # Anything still firing after Reject, denied-ping exclusion included:
        # a cookieless ping after Reject is still correct behavior.
        r["post_reject"] = [f for f in _fires(cap.get("reject_requests"))
                            if f["severity"] != "info"]

    r["gpc_tested"] = bool(cap.get("gpc_requests") is not None)
    if r["gpc_tested"]:
        r["gpc_fires"] = [f for f in _fires(cap.get("gpc_requests"))
                          if f["severity"] != "info"]

    r["optout_link"] = _optout(html)
    # The universal FTC-baseline input. Same four phrases the Playwright path
    # looks for, in the same rendered HTML.
    low = (html or "").lower()
    r["privacy_policy_link"] = next(
        (p for p in ("privacy policy", "privacy notice", "privacy statement",
                     "privacy center") if p in low), None)
    if not r["privacy_policy_link"] and 'href="/privacy' in low:
        r["privacy_policy_link"] = "/privacy (href)"

    # A PAGE THAT MADE NO REQUESTS DID NOT LOAD.
    #
    # A capture came back with HTML, a GTM container id, and an empty request
    # list on every pass — and the page rendered that as "Nothing fired",
    # "0 fired before consent", and every bought pixel "configured, not
    # firing". Four confident statements about a client's tags, all of them
    # derived from a recorder that never attached.
    #
    # Zero requests is not a quiet result, it is an impossible one: a real
    # page load fetches its own stylesheet. So the count is recorded, shown,
    # and — when it is zero — the whole page result is marked inconclusive,
    # exactly as a challenge-page crawl is. A clean scan and a scan that
    # watched nothing must never look the same.
    r["capture_counts"] = {
        "pre": len(cap.get("pre_requests") or []),
        "post": len(cap.get("post_requests") or []),
        "reject": len(cap.get("reject_requests") or []),
        "gpc": len(cap.get("gpc_requests") or []),
    }
    # AND A SAMPLE OF WHAT WAS RECORDED, WHEN NOTHING MATCHED.
    #
    # A capture came back with 105 requests and zero classified trackers on a
    # site running a Tag Manager container. The count proved the recorder
    # attached and told us nothing else, and the URLs — the one thing that
    # would have answered it in a glance — were thrown away the moment they
    # were classified. Kept now, bounded, and ONLY in the case that needs
    # them: traffic recorded, nothing recognized.
    _all = ((cap.get("pre_requests") or []) + (cap.get("post_requests") or [])
            + (cap.get("reject_requests") or []) + (cap.get("gpc_requests") or []))
    if _all and not (r["pre_consent"] or r.get("gpc_fires")
                     or r.get("post_reject") or r.get("post_consent")):
        seen, sample = set(), []
        for u in _all:
            try:
                host = u.split("/")[2]
            except Exception:  # noqa: BLE001
                host = u[:60]
            if host in seen:
                continue
            seen.add(host)
            sample.append(u[:220])
            if len(sample) >= 25:
                break
        r["unmatched_sample"] = sample

    r["no_requests_recorded"] = (
        sum(r["capture_counts"].values()) == 0 and len(html) > 500)

    # ---- everything below is the browser-free half of the scanner ---------
    #
    # It was Playwright-only for no reason other than where the code happened
    # to sit. A capture arrives BECAUSE the server scan could not run, so the
    # capture path is the one that most needs these rows, not the one that can
    # do without them.
    pre_urls = list(cap.get("pre_requests") or [])
    post_urls = [u for u in (cap.get("post_requests") or [])
                 if u not in set(pre_urls)]
    products_and_containers(r, html, low, pre_urls, post_urls, products)
    _dedupe_product_pixels(r)
    state_checks_for(r, [str(s).upper() for s in (states or [])])
    for cat in (industries or []):
        _category_checks(r, cat)

    # A verdict, so the page header says something. Without this the record
    # came back with an empty verdict and the consent page printed "not
    # recorded" above a scan that had answered every question it was asked.
    _apply_verdict(r)
    return r
