"""
Search Console + GA4 collectors — 38 checkpoints.

These are the two collectors whose blocker is the CLIENT, not the code. Nothing
here runs until a client grants OAuth access to their property, which is why the
access request should go out in the same onboarding packet as the crawler-IP
allowlist.

Credentials model: a refresh token per client, stored against the audit. The
service exchanges it for an access token at collection time. Google's read-only
scopes are enough:
    https://www.googleapis.com/auth/webmasters.readonly
    https://www.googleapis.com/auth/analytics.readonly

Every checkpoint degrades to Need Access when credentials are absent — never to
a Fail. "The client has not granted access yet" is a normal resting state for
these 38 rows, not a defect in their site.

FOUR SOURCES, NOT ONE
---------------------
The reporting APIs — searchAnalytics and runReport — answer 11 of the 38 rows.
The other 27 used to say some version of "read this from the interface", which
read to the client as a gap in the audit and to us as a build we kept deferring.
They are now answered from three further places:

  * The URL Inspection API for index coverage (GSC-05..11). It answers one URL
    per call and is quota-capped, so this is a bounded SAMPLE and every row it
    produces carries its denominator. "18 of the 25 pages we checked" is a
    defensible sentence; "18 pages are indexed" would be a lie about a 400-page
    site, and the difference is one clause.

  * The `searchAppearance` dimension for rich results (GSC-14..18). Absence of a
    type is recorded as Info, not Fail — a law firm has no product rich results
    and scoring that as a defect is noise.

  * The GA4 Admin API for configuration (GA4-03, GA4-06). Traffic tells you what
    happened; configuration tells you whether what happened was measured
    correctly, and it is the second one that usually explains a bad number.

And four rows are answered from data the audit already holds: Core Web Vitals
from the CrUX field data PageSpeed Insights returned, HTTPS from our own
fetches, internal links from the crawl's link graph, and the organic conversion
rate computed from two numbers GA4 will not divide for us.

WHAT REMAINS UNANSWERABLE, AND WHY THAT IS STATED PLAINLY
---------------------------------------------------------
GSC-20 and GSC-21 (external links, top linking sites) have no API in any form,
and GA4-14 (exit pages) has no equivalent in an event-based model at all. None
of the three is a missing client grant and none is a build being put off, so
they are bucketed as an analyst's read or marked N/A with the reason given.
Filing "Google does not publish this" under "ask the client for access" is the
error this file exists to avoid repeating.
"""
from __future__ import annotations
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

TOKEN_URL = "https://oauth2.googleapis.com/token"

# ---------------------------------------------------------------------------
# MULTI-LOGIN TOKEN INDEX — the model already proven in sitescan/gtm_api.py.
#
# Quoting that file, because the reasoning applies unchanged here:
#
#   "A service account has to be invited to every GTM account individually.
#    With hundreds of partner-named accounts and new ones appearing regularly,
#    that is a permanent chore with a guaranteed failure mode - the invite
#    nobody remembers to do. An OAuth token issued for a Vici login inherits
#    exactly the access that login already has, including accounts created
#    tomorrow, with no per-account setup at all."
#
# Same for Search Console and GA4. GOOGLE_TOKENS is {"label": refresh_token},
# and we try each login in turn until one can see the property. Google caps how
# many properties a single login can hold, which is why there are several.
#
# IMPORTANT: this removes the per-audit OAuth dance, NOT the access grant. A
# token still only inherits what its login has been given. If nobody has added
# a Vici login to the client's Search Console property, no token helps.
# ---------------------------------------------------------------------------


def oauth_configured() -> bool:
    """
    Can we even exchange a refresh token?

    A refresh token is spent AGAINST the client credentials that issued it, so
    the worker needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET as well as
    GOOGLE_TOKENS. Setting the client id only on the API — which is where you
    mint the token, so it is the natural place to put it — leaves the worker
    unable to refresh anything, and `access_token()` returns None with no
    explanation. The rows downstream then reported "no Vici login has access to
    this property", blaming the client for a variable we forgot to set. Hence
    this predicate and the branches that use it.
    """
    return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))


_MISCONFIGURED = ("GOOGLE_TOKENS is set but GOOGLE_CLIENT_ID / "
                  "GOOGLE_CLIENT_SECRET are not — a refresh token can only be "
                  "exchanged against the client that issued it. Set both ON THE "
                  "WORKER. This is our configuration, not a missing client grant.")


def _token_index() -> dict:
    raw = os.getenv("GOOGLE_TOKENS", "")
    if not raw:
        return {}
    try:
        if os.path.exists(raw):
            raw = open(raw).read()
        return json.loads(raw)
    except Exception:
        return {}


GSC_API = "https://searchconsole.googleapis.com/webmasters/v3"
GA4_API = "https://analyticsdata.googleapis.com/v1beta"
GA4_ADMIN = "https://analyticsadmin.googleapis.com/v1beta"

GTM_API = "https://tagmanager.googleapis.com/tagmanager/v2"

# READ-ONLY, DELIBERATELY. `tagmanager.readonly` lists accounts, containers and
# published versions. It cannot create a tag, publish a version, or change a
# workspace. That is the right power for an audit: we are answering "is the
# container ours to edit" and "what is actually live in it", not editing.
GTM_SCOPE = "https://www.googleapis.com/auth/tagmanager.readonly"

SCOPES = ("https://www.googleapis.com/auth/webmasters.readonly "
          "https://www.googleapis.com/auth/analytics.readonly "
          + GTM_SCOPE)

# ADDING A SCOPE DOES NOT UPGRADE THE TOKENS WE ALREADY HAVE.
#
# A refresh token carries the scopes granted at the moment someone consented,
# frozen. Every login already in GOOGLE_TOKENS consented before this line
# existed, so every one of them will get 403 from the Tag Manager API until it
# goes back through /oauth/google/start and approves again.
#
# That distinction is the whole reason `_scope_missing` exists below. A 403 for
# a missing scope and a 403 for "this login was never invited to that GTM
# account" are the same status code and completely different problems: the
# first is ours and takes two minutes, the second is an email to the client.
# Reporting the first as the second is exactly the failure the access buckets
# were built to stop, and it would show up here as a red pill on a container we
# have every right to read.


# ------------------------------------------------------------------ OAuth
def consent_url(redirect_uri: str, state: str = "") -> str | None:
    """URL to send a client to so they can grant read-only access."""
    cid = os.getenv("GOOGLE_CLIENT_ID")
    if not cid:
        return None
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": SCOPES, "access_type": "offline", "prompt": "consent",
        "state": state})


def exchange_code(code: str, redirect_uri: str) -> dict:
    """Swap the one-time code for a refresh token (stored per client)."""
    data = urllib.parse.urlencode({
        "code": code, "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
        "redirect_uri": redirect_uri, "grant_type": "authorization_code"}).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def access_token(refresh_token: str) -> str | None:
    if not (refresh_token and os.getenv("GOOGLE_CLIENT_ID")):
        return None
    data = urllib.parse.urlencode({
        "refresh_token": refresh_token, "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
        "grant_type": "refresh_token"}).encode()
    try:
        req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read()).get("access_token")
    except Exception:
        return None


def _describe(exc) -> str:
    """
    An HTTP error with its status and Google's own reason attached.

    `HTTPError` on its own is the least useful string a log can carry: 403 and
    404 mean completely different things here — one is a permission we can ask
    for, the other is a URL we got wrong — and the panel printed neither.
    Google puts the actual reason in the response body, so read it.
    """
    import urllib.error
    if isinstance(exc, urllib.error.HTTPError):
        detail = ""
        try:
            body = json.loads(exc.read() or b"{}")
            detail = ((body.get("error") or {}).get("message") or "")[:180]
        except Exception:  # noqa: BLE001
            pass
        return f"HTTP {exc.code}" + (f": {detail}" if detail else "")
    return f"{type(exc).__name__}: {exc}"


def _api(url, token, payload=None, timeout=60):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode() if payload else None,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST" if payload else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _f(status, value=None, evidence="", severity="Medium", rec="", conf=1.0,
       src="gsc"):
    return {"status": status, "value": value or {}, "evidence": evidence,
            "affected_pages": [], "severity": severity, "recommendation": rec,
            "confidence": conf, "source": src}


def _need_access(ids, reason, src):
    return {cid: _f("Need Access", {}, reason, "Medium",
                    "Request read-only access from the client during onboarding.",
                    0.0, src) for cid in ids}


# ------------------------------------------------------------------ GSC
GSC_IDS = [f"GSC-{i:02d}" for i in range(1, 23)]

# Rows this collector answers that live under OTHER prefixes in the template.
# The bucketing needs to know about them or they read as an analyst's job even
# though an endpoint answers them.
GSC_EXTRA_IDS = ("TECH-29", "TECH-35", "ANA-03")


def _candidates(site_url: str) -> set:
    """
    Every property string that could legitimately hold this site's data.

    Search Console properties are exact strings, and a URL-prefix property for
    `https://example.com/` is a DIFFERENT property from `http://example.com/`
    or `https://www.example.com/`. We were comparing the audit's target URL
    against them literally, so an audit submitted as `http://ootenlawfirm.com/`
    — which is what someone types, and what the site then redirects from — did
    not match the `https://ootenlawfirm.com/` property that holds the data, and
    the report said no Vici login had access to a property we could read
    perfectly well.

    Scheme and `www` are not meaningful distinctions for "is this the client's
    site", so try all four, plus the domain property.
    """
    host = site_url.split("//")[-1].split("/")[0].lower()
    bare = host[4:] if host.startswith("www.") else host
    out = {f"sc-domain:{bare}"}
    for h in (bare, f"www.{bare}"):
        for scheme in ("https", "http"):
            out.add(f"{scheme}://{h}")
    return out


def _first_login_that_can_see(site_url: str):
    """
    Walk the Vici logins and return the first whose token can read this property.

    Returns (access_token, label, site_url_as_google_spells_it). That third
    value matters: every later call has to use the property string the API
    returned, not the URL the audit was submitted with, or the query 404s even
    though the match succeeded.
    """
    want = _candidates(site_url)
    for label, refresh in (_token_index() or {}).items():
        tok = access_token(refresh)
        if not tok:
            continue
        try:
            sites = _api(f"{GSC_API}/sites", tok)
            for s in sites.get("siteEntry", []):
                raw = s.get("siteUrl", "")
                if raw.rstrip("/").lower() in want:
                    return tok, label, raw
        except Exception:
            continue
    return None, None, None


# --------------------------------------------------------------- URL Inspection
# Search Console's Index Coverage REPORT has no API. The URL Inspection API does,
# but it answers one URL at a time and is quota-capped (2,000/day, 600/minute per
# property). So coverage here is a SAMPLE, and every row it produces says so.
#
# The distinction matters more than it looks. "18 of 25 pages we checked are
# indexed" is a true statement we can defend. "18 pages are indexed" would be a
# lie about a 400-page site, and it is exactly the lie a reader would take away
# if the evidence line did not carry the denominator.
INSPECT_API = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
GSC_INSPECT_SAMPLE = int(os.getenv("GSC_INSPECT_SAMPLE", "25"))

_SEEN_INSPECT_KEYS = False


def _inspect_urls(art, limit: int) -> list[str]:
    """
    Which pages to spend the quota on.

    Shallow first, then widest-linked: those are the pages whose indexing status
    a client actually cares about, and the ones whose absence from the index is
    a real finding rather than a shrug about a paginated archive.
    """
    if art is None:
        return []
    ok = [p for p in art.pages.values()
          if not p.error and 200 <= p.status_code < 300
          and not (p.meta_robots and "noindex" in p.meta_robots.lower())]
    ok.sort(key=lambda p: (p.depth, -(p.inbound_internal_links or 0)))
    return [p.url for p in ok[:limit]]


def _inspect(prop_url: str, tok: str, urls: list[str]) -> tuple[list[dict], int]:
    """Inspect each URL. Returns (index-status blocks, count of failed calls)."""
    global _SEEN_INSPECT_KEYS
    got, failed = [], 0
    for u in urls:
        try:
            r = _api(INSPECT_API, tok, {"inspectionUrl": u,
                                        "siteUrl": prop_url,
                                        "languageCode": "en-US"}, timeout=45)
        except Exception:  # noqa: BLE001
            failed += 1
            continue
        res = (r.get("inspectionResult") or {})
        idx = res.get("indexStatusResult") or {}
        if not _SEEN_INSPECT_KEYS:
            # Same discipline as the DataForSEO parsers: print the field names
            # Google actually returned the first time, so a silent rename shows
            # up in the log rather than as a confident zero in the report.
            print(f"[gsc] urlInspection indexStatusResult keys: "
                  f"{sorted(idx)} | result keys: {sorted(res)}", flush=True)
            _SEEN_INSPECT_KEYS = True
        idx["_url"] = u
        idx["_rich"] = res.get("richResultsResult") or {}
        got.append(idx)
    return got, failed


def _cov(blocks: list[dict], needle: str) -> list[str]:
    n = needle.lower()
    return [b["_url"] for b in blocks
            if n in str(b.get("coverageState", "")).lower()]


def _coverage_rows(blocks: list[dict], failed: int, site_total: int) -> dict:
    """GSC-05..11 from a sample of URL Inspection verdicts."""
    n = len(blocks)
    if not n:
        return {}
    scope = (f"{n} of {site_total} pages found on the site were inspected"
             if site_total > n else f"all {n} pages found on the site were inspected")
    if failed:
        scope += f" ({failed} inspection call(s) failed)"

    indexed = [b["_url"] for b in blocks if b.get("verdict") == "PASS"]
    excluded = [b["_url"] for b in blocks if b.get("verdict") != "PASS"]
    pct = round(100 * len(indexed) / n, 1)
    out = {}
    out["GSC-05"] = _f("Pass" if pct >= 80 else "Warning",
                       {"indexed": len(indexed), "sampled": n, "pct": pct},
                       f"{len(indexed)} of {n} pages sampled are indexed ({pct}%); "
                       f"{scope}.",
                       "Low" if pct >= 80 else "Medium",
                       "" if pct >= 80 else
                       "Review the excluded pages below — each one is a page Google "
                       "has decided not to show.")
    out["GSC-06"] = _f("Pass" if not excluded else "Warning",
                       {"excluded": len(excluded), "sampled": n,
                        "examples": excluded[:10]},
                       f"{len(excluded)} of {n} pages sampled are not indexed; {scope}."
                       if excluded else
                       f"No excluded pages in the sample; {scope}.",
                       "Low" if not excluded else "Medium")

    for cid, needle, label, rec in (
        ("GSC-07", "crawled - currently not indexed",
         "fetched by Google and then left out of the index",
         "Google fetched these pages and chose not to index them — usually thin, "
         "duplicate or low-demand content. Strengthen or consolidate them."),
        ("GSC-08", "discovered - currently not indexed",
         "known to Google but never fetched",
         "Google knows these URLs exist but has not fetched them. Improve internal "
         "linking to them and check crawl budget."),
    ):
        hit = _cov(blocks, needle)
        out[cid] = _f("Pass" if not hit else "Warning",
                      {"pages": len(hit), "sampled": n, "examples": hit[:10]},
                      f"{len(hit)} of the {n} pages sampled "
                      f"{'is' if len(hit) == 1 else 'are'} {label}; {scope}."
                      if hit else
                      f"No pages were {label}; {scope}.",
                      "Low" if not hit else "Medium", "" if not hit else rec)

    fetch = [str(b.get("pageFetchState", "")).upper() for b in blocks]
    for cid, states, label, rec in (
        ("GSC-09", ("SOFT_404",), "soft 404s",
         "A soft 404 returns 200 with an empty or error-like page. Return a real "
         "404, or give the page content."),
        ("GSC-10", ("SERVER_ERROR", "INTERNAL_CRAWL_ERROR"), "server errors",
         "Google could not fetch these pages because the server errored. This "
         "removes them from the index."),
        ("GSC-11", ("REDIRECT_ERROR",), "redirect errors",
         "Fix the redirect chains or loops on these URLs."),
    ):
        hit = [b["_url"] for b, s in zip(blocks, fetch) if s in states]
        out[cid] = _f("Pass" if not hit else "Fail",
                      {"pages": len(hit), "sampled": n, "examples": hit[:10]},
                      f"{len(hit)} {label} in the sample of {n}; {scope}." if hit
                      else f"No {label} in the sample; {scope}.",
                      "Low" if not hit else "High", "" if not hit else rec)
    return out


# --------------------------------------------------------- Search appearance
# GSC-14..18. `searchAppearance` is the one dimension Google will not let you
# combine with anything else, so it gets its own query.
_APPEARANCE = (
    ("GSC-15", ("BREADCRUMB",), "breadcrumb", "Warning",
     "Add BreadcrumbList structured data so the path shows under the result."),
    ("GSC-16", ("PRODUCT",), "product", "Info", ""),
    ("GSC-17", ("FAQ", "QA_PAGE", "HOW_TO"), "FAQ / Q&A", "Info", ""),
    ("GSC-18", ("VIDEO",), "video", "Info", ""),
)


def _appearance_rows(prop: str, tok: str, start, end) -> dict:
    try:
        r = _api(f"{GSC_API}/sites/{prop}/searchAnalytics/query", tok,
                 {"startDate": str(start), "endDate": str(end),
                  "dimensions": ["searchAppearance"], "rowLimit": 100})
    except Exception as exc:  # noqa: BLE001
        print(f"[gsc] searchAppearance query failed: "
              f"{type(exc).__name__}: {exc}", flush=True)
        return {}
    rows = r.get("rows") or []
    seen = {str(x["keys"][0]).upper(): x for x in rows if x.get("keys")}
    print(f"[gsc] searchAppearance types returned: {sorted(seen)}", flush=True)

    out = {}
    total_imp = sum(int(x.get("impressions", 0)) for x in rows)
    out["GSC-14"] = _f(
        "Pass" if rows else "Warning",
        {"types": sorted(seen), "impressions": total_imp},
        f"{len(rows)} rich-result type(s) appeared in search — "
        f"{', '.join(sorted(seen)).lower()} — across {total_imp:,} impressions."
        if rows else
        "No rich results appeared in search for this site in the period.",
        "Low" if rows else "Medium",
        "" if rows else "Add structured data (Organization, LocalBusiness, "
                        "BreadcrumbList, FAQPage where applicable).")

    for cid, needles, label, absent_status, rec in _APPEARANCE:
        hit = {k: v for k, v in seen.items() if any(nd in k for nd in needles)}
        if hit:
            imp = sum(int(v.get("impressions", 0)) for v in hit.values())
            clicks = sum(int(v.get("clicks", 0)) for v in hit.values())
            out[cid] = _f("Pass", {"types": sorted(hit), "impressions": imp,
                                   "clicks": clicks},
                          f"{label.capitalize()} results appeared {imp:,} times and "
                          f"earned {clicks:,} clicks.", "Low")
        else:
            # Absence is only a defect where the markup is universally applicable.
            # A law firm has no products; scoring that as a failure would be noise,
            # so it is recorded as measured-but-not-applicable instead.
            out[cid] = _f(absent_status, {"types": []},
                          f"No {label} results appeared in search. This is expected "
                          f"unless the site publishes {label} content."
                          if absent_status == "Info" else
                          f"No {label} results appeared in search.",
                          "Low", rec)
    return out


# ------------------------------------------------- rows we answer from our own data
def _cwv_row(known: dict | None) -> dict | None:
    """
    GSC-12 Core Web Vitals.

    The Search Console CWV report has no API, but it is built from the same CrUX
    dataset PageSpeed Insights already gave us in PERF-11. Reading our own
    measurement is better than telling the reader to go and look it up.
    """
    src = (known or {}).get("PERF-11") or {}
    val = src.get("value") or {}
    overall = val.get("crux_assessment")
    if overall in ("FAST", "AVERAGE", "SLOW"):
        word = {"FAST": "good", "AVERAGE": "needs improvement", "SLOW": "poor"}[overall]
        return _f("Pass" if overall == "FAST" else "Warning",
                  {"crux_assessment": overall},
                  f"Real-visitor Core Web Vitals for this site are rated {word} by "
                  f"Google (same CrUX data Search Console reports).",
                  "Low" if overall == "FAST" else "Medium",
                  "" if overall == "FAST" else
                  "Address the failing Core Web Vitals metrics in the Performance "
                  "section.")
    if val:
        return _f("N/A", {"lighthouse_performance": val.get("lighthouse_performance")},
                  "The Core Web Vitals report is empty because Google collects "
                  "real-visitor speed data only for sites above a traffic "
                  "threshold, and this site is below it.", "Low", "", 0.6)
    return None


def _https_row(art) -> dict | None:
    """GSC-13 HTTPS. Measured from our own fetches rather than the GSC report."""
    if art is None:
        return None
    ok = [p for p in art.pages.values()
          if not p.error and 200 <= p.status_code < 300]
    if not ok:
        return None
    insecure = [p.url for p in ok
                if not (p.final_url or p.url).lower().startswith("https://")]
    upgraded = (art.http_to_https or {}).get("upgraded")
    bits = []
    if upgraded is True:
        bits.append("plain-HTTP requests are redirected to HTTPS")
    elif upgraded is False:
        bits.append("plain-HTTP requests are NOT redirected to HTTPS")
    bad = bool(insecure) or upgraded is False
    return _f("Pass" if not bad else "Fail",
              {"insecure_pages": len(insecure), "checked": len(ok),
               "http_upgrades": upgraded, "examples": insecure[:10]},
              f"{len(ok) - len(insecure)} of {len(ok)} pages served over HTTPS"
              + (f"; {'; '.join(bits)}" if bits else "") + ".",
              "Low" if not bad else "High",
              "" if not bad else
              "Serve every page over HTTPS and 301-redirect the HTTP equivalents.")


def _internal_links_row(art) -> dict | None:
    """
    GSC-19 Internal links.

    Search Console reports its own view of internal linking; we have the actual
    link graph from the crawl, which is more current and lets us name the pages.
    """
    if art is None:
        return None
    ok = [p for p in art.pages.values()
          if not p.error and 200 <= p.status_code < 300]
    if len(ok) < 2:
        return None
    home = {(art.start_url or "").rstrip("/")}
    orphans = [p.url for p in ok
               if (p.inbound_internal_links or 0) == 0
               and p.url.rstrip("/") not in home]
    thin = [p.url for p in ok if 0 < (p.inbound_internal_links or 0) <= 1]
    total = sum(p.inbound_internal_links or 0 for p in ok)
    avg = round(total / len(ok), 1)
    return _f("Pass" if not orphans else "Warning",
              {"pages": len(ok), "avg_inbound_links": avg,
               "no_inbound": len(orphans), "one_inbound": len(thin),
               "examples": orphans[:10]},
              f"{len(ok)} pages average {avg} internal links pointing at them"
              + (f"; {len(orphans)} page(s) have none" if orphans else "")
              + (f" and {len(thin)} have only one" if thin else "") + ".",
              "Low" if not orphans else "Medium",
              "" if not orphans else
              "Link to the orphaned pages from relevant body content or navigation — "
              "a page nothing links to is hard for Google to find and rank.")


# GSC-20/21 have no public API at all: neither the external-links report nor the
# top-linking-sites report is exposed, and the URL Inspection API says nothing
# about them. This is not a client grant problem and it is not a build we are
# putting off — the endpoint does not exist. DataForSEO answers the same
# question in the Off-Page section, which is why these read as a pointer rather
# than a gap.
_NO_API = ("Search Console does not expose this report through any API. It is "
           "answered from our backlink index instead, which needs the "
           "DataForSEO credentials — they were not available for this run.")


def collect_gsc(site_url: str, refresh_token: str | None = None,
                days: int = 90, property_url: str | None = None,
                artifact=None, known: dict | None = None) -> dict:
    """
    `property_url` is an operator override, chosen from the dropdown on the
    audit form. It wins over the automatic match, because the person picking it
    can see something the matcher cannot — a domain property, a subdomain, a
    site whose GSC entry does not resemble its URL.
    """
    tok = access_token(refresh_token) if refresh_token else None
    label = "per-audit token" if tok else None
    prop_url = site_url
    if not tok and property_url:
        tok, label = _token_for_gsc_property(property_url)
        prop_url = property_url
        if tok:
            label = f"{label}, property chosen by hand"
    if not tok:
        tok, label, prop_url = _first_login_that_can_see(site_url)
    if not tok:
        idx = _token_index()
        if idx and not oauth_configured():
            # Our fault, and it must not read as the client's.
            return _need_access(GSC_IDS, _MISCONFIGURED, "gsc_misconfigured")
        reason = ("No Vici login has access to this Search Console property"
                  if idx else
                  "Search Console access not configured.")
        if idx:
            reason += (f" (tried {len(idx)} login(s): {', '.join(idx)}). "
                       f"Ask the client to add a Vici login as a user on the "
                       f"property — the same grant you already use for GTM.")
        return _need_access(GSC_IDS, reason, "gsc")
    end = date.today() - timedelta(days=2)      # GSC data lags ~2 days
    start = end - timedelta(days=days)
    # The property string Google returned, not the URL the audit was submitted
    # with. Matching on one and querying with the other is how a successful
    # match still comes back empty.
    prop = urllib.parse.quote(prop_url or site_url, safe="")
    out = {}
    try:
        tot = _api(f"{GSC_API}/sites/{prop}/searchAnalytics/query", tok,
                   {"startDate": str(start), "endDate": str(end),
                    "dimensions": [], "rowLimit": 1})
        row = (tot.get("rows") or [{}])[0]
        clicks = int(row.get("clicks", 0)); imps = int(row.get("impressions", 0))
        ctr = round(100 * row.get("ctr", 0), 2); pos = round(row.get("position", 0), 1)
        out["GSC-01"] = _f("Pass", {"clicks": clicks},
                           f"{clicks:,} organic clicks over the last {days} days.", "Low")
        out["GSC-02"] = _f("Pass", {"impressions": imps},
                           f"{imps:,} impressions over the last {days} days.", "Low")
        out["GSC-03"] = _f("Pass" if ctr >= 1.0 else "Warning", {"ctr_pct": ctr},
                           f"Average click-through rate {ctr}%.",
                           "Low" if ctr >= 1.0 else "Medium",
                           "" if ctr >= 1.0 else "Improve title tags and meta "
                                                 "descriptions on high-impression pages.")
        out["GSC-04"] = _f("Pass" if pos <= 20 else "Warning", {"avg_position": pos},
                           f"Average position {pos}.",
                           "Low" if pos <= 20 else "Medium")

        # NOT GSC-22. This query returns the pages that received the most
        # organic TRAFFIC, and GSC-22 is "Top linked pages" — a page can be the
        # most linked on a site and get no traffic at all. Reporting one under
        # the other's name is the same error as OFF-10 printing a nofollow
        # percentage under "Lost backlinks": a real number, confidently
        # mislabelled, which is worse than an admitted gap.
        #
        # GSC-22 is answered from the backlink index instead, in
        # dataforseo._page_split. What this query is genuinely good for is
        # confirming the connection reads real data, so that is what it does.
        pages = _api(f"{GSC_API}/sites/{prop}/searchAnalytics/query", tok,
                     {"startDate": str(start), "endDate": str(end),
                      "dimensions": ["page"], "rowLimit": 25})
        n_pages = len(pages.get("rows", []))
        out["GSC-01"]["value"]["pages_with_traffic"] = n_pages
        out["GSC-01"]["value"]["via_login"] = label
        out["GSC-01"]["evidence"] += (f" {n_pages} pages received organic traffic "
                                      f"in the period (read via {label}).")
    except Exception as e:
        return _need_access(GSC_IDS,
                            f"Search Console query failed: {type(e).__name__}: {e}",
                            "gsc_error")

    # ---- GSC-14..18 rich results, from the searchAppearance dimension --------
    out.update(_appearance_rows(prop, tok, start, end))

    # ---- GSC-05..11 index coverage, sampled through URL Inspection ----------
    urls = _inspect_urls(artifact, GSC_INSPECT_SAMPLE)
    if urls:
        blocks, failed = _inspect(prop_url or site_url, tok, urls)
        if blocks:
            site_total = sum(1 for p in artifact.pages.values()
                             if not p.error and 200 <= p.status_code < 300)
            out.update(_coverage_rows(blocks, failed, site_total))
            print(f"[gsc] inspected {len(blocks)}/{len(urls)} URLs "
                  f"({failed} failed)", flush=True)
        else:
            print(f"[gsc] URL Inspection returned nothing for {len(urls)} URLs — "
                  f"index coverage rows left unanswered", flush=True)

    # ---- rows answered from data we already hold ----------------------------
    for cid, row in (("GSC-12", _cwv_row(known)),
                     ("GSC-13", _https_row(artifact)),
                     ("GSC-19", _internal_links_row(artifact))):
        if row:
            out[cid] = row

    # Three link reports Google publishes and exposes through no API. The
    # backlink collector answers all three and overwrites these; this is what
    # they say when DataForSEO is not configured for the run.
    for cid in ("GSC-20", "GSC-21", "GSC-22"):
        out.setdefault(cid, _f("Need Access", {}, _NO_API, "Low",
                               "Set the DataForSEO credentials — the backlink "
                               "index answers all three of these.",
                               0.0, "gsc_no_api"))

    # ---- three rows outside the GSC block that this connection answers -----
    out.update(_sitemap_and_coverage(prop, tok, out, label))

    for cid in GSC_IDS:
        out.setdefault(cid, _f(
            "Need Access", {},
            "Not available through the Search Console API — read this from the "
            "Search Console UI (Index Coverage, Core Web Vitals, Enhancements).",
            "Low", "Capture manually from Search Console, or use the Index "
                   "Inspection API for per-URL coverage.", 0.0, "gsc_ui_only"))
    return out


def _sitemap_and_coverage(prop: str, tok: str, gsc: dict, label: str) -> dict:
    """
    TECH-29, TECH-35 and ANA-03 — three rows that were on an analyst's list and
    are answered by the Search Console connection we already hold.

    They sit outside the GSC block in the template, which is the only reason
    they were never wired up: the collector filled GSC-01..22 and stopped at the
    prefix boundary. Nobody has to open Search Console to find out whether a
    sitemap was submitted; there is an endpoint for it.
    """
    out = {}
    # ANA-03. The verification meta tag was the only signal we looked for, so a
    # site verified by DNS or by an HTML file reported "cannot confirm Search
    # Console access" while this very function was reading its data.
    out["ANA-03"] = _f("Pass", {"via_login": label},
                       f"Search Console is connected and returning data for "
                       f"this property (read via {label}), which is the "
                       f"verification working.", "Low", "", 1.0, "gsc")

    # TECH-35. Index coverage IS reviewed — GSC-05..11 above are that review.
    cov = gsc.get("GSC-05") or {}
    if cov.get("status") not in (None, "Need Access"):
        v = cov.get("value") or {}
        out["TECH-35"] = _f(
            cov.get("status", "Pass"),
            {"indexed": v.get("indexed"), "sampled": v.get("sampled")},
            f"Index coverage was reviewed through the URL Inspection API: "
            f"{v.get('indexed')} of {v.get('sampled')} pages sampled are "
            f"indexed. The full breakdown is in GSC-05 to GSC-11.",
            "Low", "", 1.0, "gsc")

    try:
        r = _api(f"{GSC_API}/sites/{prop}/sitemaps", tok)
    except Exception as exc:  # noqa: BLE001
        print(f"[gsc] sitemaps call failed: {_describe(exc)}", flush=True)
        return out
    maps = r.get("sitemap") or []
    if not maps:
        out["TECH-29"] = _f(
            "Fail", {"sitemaps": 0},
            "No XML sitemap has been submitted in Search Console. Google will "
            "still find pages by following links, but a sitemap is how it "
            "learns about pages nothing links to yet.", "Medium",
            "Submit the sitemap in Search Console.", 1.0, "gsc")
        return out
    # `errors` and `warnings` are strings in this response. Anything non-zero
    # is worth naming: a submitted sitemap Google cannot parse is worse than
    # none, because it looks done.
    errs = sum(int(m.get("errors") or 0) for m in maps)
    warns = sum(int(m.get("warnings") or 0) for m in maps)
    paths = [m.get("path") for m in maps if m.get("path")]
    last = max((m.get("lastDownloaded") or "") for m in maps) or ""
    out["TECH-29"] = _f(
        "Pass" if not errs else "Warning",
        {"sitemaps": len(maps), "paths": paths[:10], "errors": errs,
         "warnings": warns, "last_downloaded": last[:10]},
        f"{len(maps)} sitemap(s) submitted"
        + (f", last read by Google on {last[:10]}" if last else "")
        + (f"; {errs} error(s) and {warns} warning(s) reported." if errs
           else (f"; {warns} warning(s) reported." if warns else ", with no "
                 "errors reported.")),
        "Low" if not errs else "Medium",
        "" if not errs else "Fix the sitemap errors — Google is rejecting part "
                            "of what you submitted.", 1.0, "gsc")
    return out


# ------------------------------------------------------------------ GA4
GA4_IDS = [f"GA4-{i:02d}" for i in range(1, 17)]

# How many properties we will open data streams for, per login, when the
# property name gives us no hint. Bounded on purpose: a login can hold hundreds
# of properties and each one is an API call. If the scan runs out before it
# finds a match we say the scan was bounded — we never report "no property".
GA4_STREAM_SCAN = int(os.getenv("GA4_STREAM_SCAN", "60"))


def _squash(s: str) -> str:
    """Letters and digits only, lower case. 'Ooten Law Firm' -> 'ootenlawfirm'."""
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _host(site_url: str) -> str:
    h = site_url.split("//")[-1].split("/")[0].lower()
    return h[4:] if h.startswith("www.") else h


def _ga4_properties(tok: str) -> list[tuple[str, str]]:
    """[(property_id, display_name)] visible to this token, across all accounts."""
    props, page = [], None
    for _ in range(10):                     # bounded paging
        url = f"{GA4_ADMIN}/accountSummaries?pageSize=200"
        if page:
            url += f"&pageToken={urllib.parse.quote(page)}"
        data = _api(url, tok)
        for acc in data.get("accountSummaries", []):
            for p in acc.get("propertySummaries", []):
                pid = (p.get("property") or "").split("/")[-1]
                if pid:
                    props.append((pid, p.get("displayName") or ""))
        page = data.get("nextPageToken")
        if not page:
            break
    return props


def _stream_hosts(tok: str, pid: str) -> set[str]:
    try:
        data = _api(f"{GA4_ADMIN}/properties/{pid}/dataStreams?pageSize=50", tok)
    except Exception:
        return set()
    out = set()
    for s in data.get("dataStreams", []):
        uri = ((s.get("webStreamData") or {}).get("defaultUri") or "")
        if uri:
            out.add(_host(uri))
    return out


def _find_ga4_property(site_url: str) -> tuple[str | None, str | None, str | None]:
    """
    Find the GA4 property for this site across the Vici logins.

    Returns (access_token, property_id, label). Match on the data stream's
    defaultUri — the only field that actually states which website a property
    measures. Property display names are matched first only as a cheap way to
    order the scan, never as proof on their own.
    """
    want = _host(site_url)
    slug = _squash(want.split(".")[0])
    for label, refresh in (_token_index() or {}).items():
        tok = access_token(refresh)
        if not tok:
            continue
        try:
            props = _ga4_properties(tok)
        except Exception:
            continue
        # Order the scan by name similarity, then take the cap.
        #
        # This compared "ootenlawfirm" against the lower-cased display name
        # "ooten law firm" — a domain slug has no spaces and a display name
        # does, so the test could essentially never fire. Every property was
        # therefore "unlikely", the scan ran in arbitrary order, and on a login
        # holding hundreds of properties the right one sat past the cap. The
        # report then said no property measured this domain, which was false.
        # Squash both sides to letters and digits before comparing.
        likely = [p for p in props if slug and slug in _squash(p[1])]
        rest = [p for p in props if p not in likely]
        for pid, _name in (likely + rest)[:GA4_STREAM_SCAN]:
            if want in _stream_hosts(tok, pid):
                return tok, pid, label
    return None, None, None


# ----------------------------------------------------------------- Tag Manager
GTM_ACCOUNT_CAP = 40          # per login; see _gtm_containers


def _scope_missing(exc) -> bool:
    """
    Is this 403 "your token lacks the scope" rather than "you lack access"?

    Same status code, opposite owners. Google distinguishes them only in the
    body, with `ACCESS_TOKEN_SCOPE_INSUFFICIENT` in the error status or a
    reason of `insufficientPermissions`/`accessNotConfigured`. Getting this
    wrong prints our own missing consent as the client's missing invite, which
    is the exact error the three access buckets exist to prevent.
    """
    import urllib.error
    if not isinstance(exc, urllib.error.HTTPError) or exc.code not in (401, 403):
        return False
    try:
        body = json.loads(exc.read() or b"{}")
    except Exception:  # noqa: BLE001
        return False
    err = body.get("error") or {}
    blob = json.dumps(err).lower()
    return ("access_token_scope_insufficient" in blob
            or "insufficientpermissions" in blob
            or "accessnotconfigured" in blob
            or "request had insufficient authentication scopes" in blob)


def _gtm_containers(tok: str) -> list:
    """
    Every GTM container this login can read.

    One call for the accounts, then one per account for its containers — so
    the cost is 1 + N, and N is however many GTM accounts a Vici login has
    been invited to. For an agency login that is not a small number, which is
    why it is capped and why the cap is REPORTED rather than silently applied:
    a list that quietly stops at 40 looks exactly like a list of everything,
    and the container you were looking for is the one that got cut.

    `publicId` is the GTM-XXXXXX string that appears in the site's HTML. It is
    the only field that connects what we can administer to what is actually
    installed, and it is what the probe matches on.
    """
    out, truncated = [], False
    accounts = (_api(f"{GTM_API}/accounts", tok, timeout=30).get("account") or [])
    if len(accounts) > GTM_ACCOUNT_CAP:
        truncated = True
        accounts = accounts[:GTM_ACCOUNT_CAP]
    for a in accounts:
        path = a.get("path") or ""
        if not path:
            continue
        try:
            cs = (_api(f"{GTM_API}/{path}/containers", tok,
                       timeout=30).get("container") or [])
        except Exception:  # noqa: BLE001
            continue          # one unreadable account must not hide the rest
        for c in cs:
            out.append({"public_id": c.get("publicId", ""),
                        "container": c.get("name", ""),
                        "account": a.get("name", ""),
                        "path": c.get("path", "")})
    return out, truncated


_GTM_ID_RE = None


def gtm_ids_on_page(site_url: str, timeout: int = 12) -> list:
    """
    The GTM container ids the site actually loads, read off its HTML.

    This is the question worth asking, and it is not one the Tag Manager API
    can answer: the API says what we can ADMINISTER, the page says what is
    INSTALLED. Overlap them and you get the only answer an operator wants —
    "the site runs GTM-ABC1234 and yes, it is in an account we hold" — instead
    of a name-similarity guess between a container called "Client - Main" and
    a domain called ootenlawfirm.com.

    One GET, short timeout, failures swallowed. This runs while somebody is
    waiting on a form.
    """
    global _GTM_ID_RE
    if _GTM_ID_RE is None:
        import re
        _GTM_ID_RE = re.compile(r"GTM-[A-Z0-9]{4,10}")
    try:
        req = urllib.request.Request(site_url, headers={
            "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0 Safari/537.36")})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read(600_000).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return []
    seen, ids = set(), []
    for m in _GTM_ID_RE.findall(html):
        if m not in seen:
            seen.add(m)
            ids.append(m)
    return ids


def _gtm_probe(site_url: str, idx: dict) -> dict:
    """
    Do we administer the container this site is actually running?

    Four outcomes, and they belong to four different people:

      ok         the container on the page is in an account we hold. We can
                 make the change ourselves.
      scope      our tokens predate the tagmanager scope. OURS, two minutes,
                 and it must never render as the client withholding anything.
      not ours   the page runs a container nobody here can see. A real ask,
                 and the one case where emailing the client is the answer.
      none       no GTM on the page at all. Not an access problem — that is a
                 finding, and ANA-01 already reports it.
    """
    installed = gtm_ids_on_page(site_url)
    mine, truncated, scope_blocked, errors = [], False, False, []
    for label, refresh in (idx or {}).items():
        tok = access_token(refresh)
        if not tok:
            continue
        try:
            rows, trunc = _gtm_containers(tok)
        except Exception as exc:  # noqa: BLE001
            if _scope_missing(exc):
                scope_blocked = True
            else:
                errors.append(f"{label}: {_describe(exc)}")
            continue
        truncated = truncated or trunc
        for r in rows:
            mine.append({**r, "login": label})

    if scope_blocked and not mine:
        return {"ok": False, "ours": True, "scope": True,
                "installed": installed,
                "detail": ("Our Google logins have not approved Tag Manager "
                           "access yet — the scope was added after they last "
                           "signed in. Re-authorize each login at "
                           "/oauth/google/start and this answers itself. "
                           "Nothing is needed from the client.")}
    if not installed:
        return {"ok": False, "partial": True, "installed": [],
                "detail": ("No GTM container loads on this page. That is a "
                           "finding rather than an access problem — ANA-01 "
                           "reports it.")}

    for cid in installed:
        for r in mine:
            if r["public_id"] == cid:
                return {"ok": True, "property": cid,
                        "name": f"{r['account']} \u00b7 {r['container']}",
                        "login": r["login"], "installed": installed}

    note = (" The list of containers we can see was capped at "
            f"{GTM_ACCOUNT_CAP} accounts per login, so this could be a miss "
            "rather than a no." if truncated else "")
    return {"ok": False, "installed": installed,
            "detail": (f"The site runs {', '.join(installed[:3])}, and no Vici "
                       f"login can see that container. Publishing a tag change "
                       f"needs the client to grant access." + note)}


_LIST_CACHE: dict = {"at": 0.0, "data": None}


def list_properties(max_age: float = 120.0) -> dict:
    """
    Everything every Vici login can see, for an operator to pick from by hand.

    The automated match is good and still wrong sometimes — a property named
    nothing like its domain, a client on a subdomain, a site whose GSC entry is
    a domain property. When it misses, the useful next question is not "why"
    but "what IS in there", and until now there was no way to look without
    opening the Google console.

    Cheap on purpose: `sites` for Search Console and `accountSummaries` for
    GA4. Neither opens a data stream, so this does not grow with the number of
    properties the way domain-matching does. Cached briefly because clicking
    the button twice should not re-list several hundred properties.

    A login that errors is skipped rather than failing the call — one bad
    refresh token must not hide every other login's properties.
    """
    now = time.time()
    if _LIST_CACHE["data"] is not None and now - _LIST_CACHE["at"] < max_age:
        return _LIST_CACHE["data"]

    out = {"gsc": [], "ga4": [], "gtm": [], "logins": [], "errors": []}
    for label, refresh in (_token_index() or {}).items():
        tok = access_token(refresh)
        if not tok:
            out["errors"].append(f"{label}: refresh token would not exchange")
            continue
        out["logins"].append(label)
        try:
            sites = _api(f"{GSC_API}/sites", tok)
            for s in sites.get("siteEntry", []):
                out["gsc"].append({"site": s.get("siteUrl", ""), "login": label,
                                   "permission": s.get("permissionLevel", "")})
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"{label} Search Console: {type(exc).__name__}")
        try:
            for pid, name in _ga4_properties(tok):
                out["ga4"].append({"id": pid, "name": name, "login": label})
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"{label} GA4: {type(exc).__name__}")
        try:
            rows, trunc = _gtm_containers(tok)
            for r in rows:
                out["gtm"].append({**r, "login": label})
            if trunc:
                # Say it. A capped list is indistinguishable from a complete
                # one, and the container someone is hunting for is exactly the
                # one that fell off the end.
                out["errors"].append(
                    f"{label} Tag Manager: only the first {GTM_ACCOUNT_CAP} "
                    f"accounts were listed")
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(
                f"{label} Tag Manager: "
                + ("the login has not approved the Tag Manager scope yet"
                   if _scope_missing(exc) else _describe(exc)))

    out["gsc"].sort(key=lambda r: r["site"].lower())
    out["ga4"].sort(key=lambda r: (r["name"] or "").lower())
    out["gtm"].sort(key=lambda r: ((r["account"] or "").lower(),
                                   (r["container"] or "").lower()))
    _LIST_CACHE.update({"at": now, "data": out})
    return out


def _token_for_gsc_property(site: str):
    """(token, label) for the first login that can read this exact property."""
    for label, refresh in (_token_index() or {}).items():
        tok = access_token(refresh)
        if not tok:
            continue
        try:
            sites = _api(f"{GSC_API}/sites", tok)
            if any(s.get("siteUrl", "") == site
                   for s in sites.get("siteEntry", [])):
                return tok, label
        except Exception:
            continue
    return None, None


def _token_for_ga4_property(pid: str):
    """(token, label) for the first login that can see this property id."""
    for label, refresh in (_token_index() or {}).items():
        tok = access_token(refresh)
        if not tok:
            continue
        try:
            if any(p == pid for p, _n in _ga4_properties(tok)):
                return tok, label
        except Exception:
            continue
    return None, None


def probe(site_url: str, name_scan: int = 8) -> dict:
    """
    Fast, read-only "do we have access?" check. Answers BEFORE an audit runs.

    Finding out at the end of a 150-page crawl that 38 rows are blank is the
    wrong time to find out. This asks the same questions the collectors ask,
    but bounded so it returns while someone is still looking at the form.

    The bound is the honest part. Search Console is exact: one `sites` call per
    login lists everything, so a "no" here is a real no. GA4 is not — matching
    a property to a domain means opening its data streams, one call each, and a
    login can hold hundreds. So the probe only opens streams for properties
    whose NAME already looks right, and when that finds nothing it says the
    quick check found nothing rather than claiming there is no property. The
    full scan still runs during the audit.

    Never raises. A probe that 500s teaches the operator to ignore the probe.
    """
    out = {"gsc": {"ok": False}, "ga4": {"ok": False}, "gtm": {"ok": False},
           "configured": bool(_token_index()) and oauth_configured()}
    if not _token_index():
        msg = "GOOGLE_TOKENS is not set on this service."
        out["gsc"] = out["ga4"] = out["gtm"] = {"ok": False, "detail": msg,
                                                "ours": True}
        return out
    if not oauth_configured():
        msg = ("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set on this "
               "service, so the refresh token cannot be exchanged.")
        out["gsc"] = out["ga4"] = out["gtm"] = {"ok": False, "detail": msg,
                                                "ours": True}
        return out

    idx = _token_index()
    try:
        tok, label, prop = _first_login_that_can_see(site_url)
        out["gsc"] = ({"ok": True, "property": prop, "login": label} if tok else
                      {"ok": False, "detail": f"No property matching this site "
                                              f"in {len(idx)} login(s): "
                                              f"{', '.join(idx)}."})
    except Exception as exc:  # noqa: BLE001
        out["gsc"] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}

    want = _host(site_url)
    slug = _squash(want.split(".")[0])
    try:
        found = None
        for lbl, refresh in idx.items():
            tok = access_token(refresh)
            if not tok:
                continue
            named = [p for p in _ga4_properties(tok)
                     if slug and slug in _squash(p[1])][:name_scan]
            for pid, nm in named:
                if want in _stream_hosts(tok, pid):
                    found = {"ok": True, "property": pid, "name": nm,
                             "login": lbl}
                    break
            if found:
                break
        out["ga4"] = found or {
            "ok": False, "partial": True,
            "detail": ("No property whose NAME resembles this domain also "
                       "reports it. The audit still scans by data stream, "
                       "which is slower and looks wider — this quick check "
                       "can miss a property named unlike its site.")}
    except Exception as exc:  # noqa: BLE001
        out["ga4"] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}

    # Tag Manager last, because it is the only one of the three that reads the
    # client's page as well as Google's API, and a slow site should not hold up
    # the two answers that were already in hand.
    try:
        out["gtm"] = _gtm_probe(site_url, idx)
    except Exception as exc:  # noqa: BLE001
        out["gtm"] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    return out


# ------------------------------------------------------- GA4 config + reports
_ENHANCED = [("streamEnabled", "page views"),
             ("scrollsEnabled", "scrolls"),
             ("outboundClicksEnabled", "outbound clicks"),
             ("siteSearchEnabled", "site search"),
             ("videoEngagementEnabled", "video engagement"),
             ("fileDownloadsEnabled", "file downloads"),
             ("formInteractionsEnabled", "form interactions")]

_SEEN_GA4_KEYS = set()


def _seen(tag: str, obj) -> None:
    """Log a payload's field names once per shape, for the same reason as GSC."""
    if tag in _SEEN_GA4_KEYS:
        return
    _SEEN_GA4_KEYS.add(tag)
    keys = sorted(obj) if isinstance(obj, dict) else type(obj).__name__
    print(f"[ga4] {tag} keys: {keys}", flush=True)


def _report(pid: str, tok: str, dims: list[str], mets: list[str], limit: int = 50,
            days: int = 90):
    r = _api(f"{GA4_API}/properties/{pid}:runReport", tok, {
        "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
        "dimensions": [{"name": d} for d in dims],
        "metrics": [{"name": m} for m in mets],
        "limit": limit})
    _seen(f"runReport({','.join(dims) or 'total'})", r)
    out = []
    for row in r.get("rows", []):
        out.append(([d["value"] for d in row.get("dimensionValues", [])],
                    [v["value"] for v in row.get("metricValues", [])]))
    return out


# `getEnhancedMeasurementSettings` is not in every version of the Admin API.
# A 404 from v1beta is not a permission problem and not a missing grant — it is
# us asking an endpoint that does not serve this method. Try the alpha surface,
# which does.
GA4_ADMIN_ALPHA = "https://analyticsadmin.googleapis.com/v1alpha"


def _enhanced_settings(pid: str, sid: str, tok: str) -> dict:
    last = None
    for base in (GA4_ADMIN, GA4_ADMIN_ALPHA):
        try:
            return _api(f"{base}/properties/{pid}/dataStreams/{sid}"
                        f"/enhancedMeasurementSettings", tok)
        except Exception as exc:  # noqa: BLE001
            import urllib.error
            last = exc
            # Only a 404 is worth retrying on another version. A 403 means the
            # endpoint exists and we are not allowed in, and asking the alpha
            # surface the same question gets the same answer.
            if not (isinstance(exc, urllib.error.HTTPError) and exc.code == 404):
                raise
    raise last


def _enhanced_row(pid: str, tok: str) -> dict:
    """GA4-03. Enhanced Measurement lives on the data stream, in the Admin API."""
    try:
        streams = _api(f"{GA4_ADMIN}/properties/{pid}/dataStreams", tok)
    except Exception as exc:  # noqa: BLE001
        print(f"[ga4] dataStreams failed: {type(exc).__name__}: {exc}", flush=True)
        return {}
    web = [s for s in streams.get("dataStreams", [])
           if s.get("type") == "WEB_DATA_STREAM"]
    if not web:
        return {"GA4-03": _f("N/A", {}, "This property has no web data stream, so "
                                        "Enhanced Measurement does not apply.",
                             "Low", "", 0.8, "ga4")}
    on, off, errs = [], [], []
    for s in web:
        sid = (s.get("name") or "").split("/")[-1]
        try:
            em = _enhanced_settings(pid, sid, tok)
        except Exception as exc:  # noqa: BLE001
            # This swallowed its exception silently and the row came back
            # saying "requires the admin API" on a run where the admin API was
            # demonstrably working — key events, read from the same API with
            # the same token, filled correctly two rows below. A failure that
            # cannot be told apart from "not built yet" is the failure mode
            # this whole collector exists to avoid.
            why = _describe(exc)
            print(f"[ga4] enhancedMeasurementSettings for stream {sid} "
                  f"failed: {why}", flush=True)
            errs.append(why)
            continue
        _seen("enhancedMeasurementSettings", em)
        for key, label in _ENHANCED:
            (on if em.get(key) else off).append(label)
    if not on and not off:
        # Say which of the two it is. Empty because the call failed is a
        # different fact from empty because the property answered with nothing,
        # and only the first one is ours to chase.
        if errs:
            joined = ", ".join(sorted(set(errs)))
            # 403 is the one worth naming: this specific Admin API method is
            # not covered by a read-only grant on some properties, and no
            # amount of retrying changes that. Saying "Editor" turns a dead end
            # into a one-line ask.
            forbidden = any(e.startswith("HTTP 403") for e in errs)
            missing = any(e.startswith("HTTP 404") for e in errs)
            # DO NOT CALL A 404 A PERMISSION PROBLEM.
            #
            # The first version of this message said "this is a permission on
            # that one setting" whatever the status code, and then printed
            # HTTP 404 immediately before it. 404 means the endpoint did not
            # serve the method — our call, not their account — and asserting
            # otherwise sends someone to change a Google permission that was
            # never the problem. Only 403 is a permission.
            if forbidden:
                why = ("Everything else in GA4 on this report was read with the "
                       "same login, so this is a permission on that one "
                       "setting rather than a missing grant.")
                rec = ("This method needs Editor on the property; a Viewer "
                       "grant reads the traffic but not the stream settings.")
            elif missing:
                why = ("The Analytics Admin API did not serve this method for "
                       "this data stream on either the beta or the alpha "
                       "endpoint. That is our call to fix, not anything about "
                       "the account.")
                rec = "Ours to fix — no action on the client's side."
            else:
                why = "Everything else in GA4 on this report read normally."
                rec = ("Confirm the Vici login can see the data stream, not "
                       "only the property.")
            return {"GA4-03": _f(
                "Need Access", {"errors": sorted(set(errs))},
                f"Enhanced Measurement could not be read for {len(errs)} data "
                f"stream(s) ({joined}). {why}",
                "Low", rec, 0.0, "ga4_admin_only")}
        return {}
    on, off = sorted(set(on)), sorted(set(off) - set(on))
    return {"GA4-03": _f("Pass" if not off else "Warning",
                         {"enabled": on, "disabled": off},
                         f"Enhanced Measurement is capturing {', '.join(on)}."
                         + (f" Not capturing: {', '.join(off)}." if off else ""),
                         "Low" if not off else "Medium",
                         "" if not off else
                         "Turn on the remaining Enhanced Measurement events — they "
                         "are free signals about how visitors use the site.",
                         1.0, "ga4")}


def _key_events_row(pid: str, tok: str) -> dict:
    """
    GA4-06. `keyEvents` is the current name; `conversionEvents` is what older
    properties still answer to. Try both rather than reporting nothing because
    Google renamed the collection.
    """
    for coll, word in (("keyEvents", "key event"), ("conversionEvents", "conversion")):
        try:
            r = _api(f"{GA4_ADMIN}/properties/{pid}/{coll}", tok)
        except Exception:  # noqa: BLE001
            continue
        _seen(coll, r)
        names = [e.get("eventName") for e in (r.get(coll) or []) if e.get("eventName")]
        return {"GA4-06": _f("Pass" if names else "Fail",
                             {"key_events": names},
                             f"{len(names)} {word}(s) configured: "
                             f"{', '.join(names[:12])}." if names else
                             f"No {word}s are configured, so GA4 cannot tell which "
                             f"visits were valuable.",
                             "Low" if names else "High",
                             "" if names else
                             "Mark form submissions, calls and quote requests as key "
                             "events in GA4 Admin.", 1.0, "ga4")}
    return {}


# Hostnames that mean traffic from inside the business is being counted as if it
# were a visitor. We measure the effect rather than reading the filter config,
# because the Admin API does not expose data filters and the effect is what
# distorts the numbers anyway.
_INTERNAL_HOST = ("localhost", "127.0.0.1", ".local", "staging.", "stage.",
                  "dev.", "test.", "uat.", "preview.", ".ngrok.", "webflow.io",
                  "wpengine.com", "kinsta.cloud", "pantheonsite.io")


def _host_rows(pid: str, tok: str, site_url: str, days: int = 90) -> dict:
    """GA4-07 cross-domain tracking and GA4-08 internal traffic, one report."""
    try:
        rows = _report(pid, tok, ["hostName"], ["sessions"], 100, days)
    except Exception as exc:  # noqa: BLE001
        print(f"[ga4] hostName report failed: {type(exc).__name__}: {exc}", flush=True)
        return {}
    if not rows:
        return {}
    hosts = {(d[0] or "").lower(): int(float(m[0])) for d, m in rows}
    total = sum(hosts.values()) or 1
    primary = _host(site_url).lower()
    bare = primary[4:] if primary.startswith("www.") else primary

    other = {h: n for h, n in hosts.items() if bare not in h}
    internal = {h: n for h, n in hosts.items()
                if any(bit in h for bit in _INTERNAL_HOST)}
    out = {}
    if len(hosts) == 1:
        out["GA4-07"] = _f("Pass", {"hosts": sorted(hosts)},
                           f"All measured traffic is on {next(iter(hosts))} — one "
                           f"domain, so cross-domain tracking is not needed.",
                           "Low", "", 1.0, "ga4")
    elif not other:
        # Several hostnames, all of them this domain — subdomains, or www and
        # bare. That is one site, not a cross-domain setup, and nothing is wrong.
        out["GA4-07"] = _f("Pass", {"hosts": sorted(hosts)},
                           f"All measured traffic is on {bare} and its subdomains "
                           f"({', '.join(sorted(hosts)[:6])}), so cross-domain "
                           f"tracking is not needed.", "Low", "", 1.0, "ga4")
    else:
        share = round(100 * sum(other.values()) / total, 1)
        out["GA4-07"] = _f("Pass", {"hosts": sorted(hosts),
                                    "other_hosts": sorted(other),
                                    "other_share_pct": share},
                           f"Sessions are measured across {len(hosts)} hostnames, so "
                           f"cross-domain tracking is in place: {share}% of sessions "
                           f"are on a domain other than {bare} "
                           f"({', '.join(sorted(other)[:6])}). Worth confirming each "
                           f"one is intended rather than a tag left on an old site.",
                           "Low", "", 1.0, "ga4")
    if internal:
        share = round(100 * sum(internal.values()) / total, 1)
        out["GA4-08"] = _f("Fail", {"hosts": sorted(internal), "share_pct": share},
                           f"{share}% of sessions come from staging or internal "
                           f"hostnames ({', '.join(sorted(internal)[:6])}), so "
                           f"internal traffic is not being filtered out.",
                           "High",
                           "Add an internal-traffic filter in GA4 Admin, and stop "
                           "the staging site reporting into the live property.",
                           1.0, "ga4")
    else:
        out["GA4-08"] = _f("Pass", {"hosts": sorted(hosts)},
                           "No staging or internal hostnames appear in the traffic, "
                           "so the numbers reflect real visitors.", "Low", "",
                           0.8, "ga4")
    return out


def collect_ga4(property_id: str | None, refresh_token: str | None,
                days: int = 90, site_url: str = "") -> dict:
    tok = access_token(refresh_token) if refresh_token else None
    label = "per-audit token" if tok else None
    # An explicitly chosen property is authoritative — look for a login that
    # can read it rather than going back to guessing from the domain.
    if property_id and not tok:
        tok, label = _token_for_ga4_property(property_id)
        if tok:
            label = f"{label}, property chosen by hand"
    if not (tok and property_id) and site_url:
        tok, property_id, label = _find_ga4_property(site_url)
    if not (tok and property_id):
        idx = _token_index()
        if idx and not oauth_configured():
            return _need_access(GA4_IDS, _MISCONFIGURED, "ga4_misconfigured")
        reason = ("Google Analytics access not granted by the client."
                  if not idx else
                  f"No GA4 property measuring this domain was found in "
                  f"{len(idx)} Vici login(s) ({', '.join(idx)}); up to "
                  f"{GA4_STREAM_SCAN} properties per login were checked. Ask the "
                  f"client to add a Vici login to the property, or supply the "
                  f"property ID directly.")
        return _need_access(GA4_IDS, reason, "ga4")
    out = {}
    try:
        rep = _api(f"{GA4_API}/properties/{property_id}:runReport", tok, {
            "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
            "dimensions": [{"name": "sessionDefaultChannelGroup"}],
            "metrics": [{"name": "sessions"}, {"name": "engagementRate"},
                        {"name": "bounceRate"}, {"name": "userEngagementDuration"},
                        {"name": "conversions"}]})
        rows = rep.get("rows", [])
        organic = next((r for r in rows
                        if r["dimensionValues"][0]["value"] == "Organic Search"), None)
        out["GA4-01"] = _f("Pass", {"property": property_id, "via_login": label},
                           f"GA4 property {property_id} reachable and returning data "
                           f"(read via {label}).", "Low")
        out["GA4-02"] = _f("Pass" if rows else "Fail", {"rows": len(rows)},
                           f"Data collection active — {len(rows)} channel groups "
                           f"reporting." if rows else "No data returned for the period.",
                           "Low" if rows else "High")
        if organic:
            m = organic["metricValues"]
            sess = int(float(m[0]["value"]))
            eng = round(float(m[1]["value"]) * 100, 1)
            bounce = round(float(m[2]["value"]) * 100, 1)
            conv = int(float(m[4]["value"]))
            out["GA4-09"] = _f("Pass", {"organic_sessions": sess},
                               f"{sess:,} organic sessions in the last {days} days.",
                               "Low")
            out["GA4-10"] = _f("Pass" if eng >= 50 else "Warning",
                               {"engagement_rate_pct": eng},
                               f"Organic engagement rate {eng}%.",
                               "Low" if eng >= 50 else "Medium")
            out["GA4-11"] = _f("Pass", {"bounce_rate_pct": bounce},
                               f"Organic bounce rate {bounce}%.", "Low")
            out["GA4-05"] = _f("Pass" if conv else "Fail", {"conversions": conv},
                               f"{conv:,} conversions attributed to organic search."
                               if conv else
                               "No conversions recorded for organic search — check "
                               "that key events are configured.",
                               "Low" if conv else "High",
                               "" if conv else "Configure key events / conversions in GA4.")
            # GA4-12: GA4 reports total engagement seconds, not an average. The
            # average per session is the number people mean, so divide.
            secs = float(m[3]["value"])
            if sess:
                avg = secs / sess
                mm, ss = divmod(int(round(avg)), 60)
                out["GA4-12"] = _f("Pass" if avg >= 45 else "Warning",
                                   {"avg_engagement_seconds": round(avg, 1)},
                                   f"Organic visitors spend {mm}m {ss:02d}s engaged "
                                   f"per session on average.",
                                   "Low" if avg >= 45 else "Medium",
                                   "" if avg >= 45 else
                                   "Short engagement usually means the landing page "
                                   "does not answer the query it ranks for.")
                # GA4-15: GA4 exposes no organic-only conversion rate metric, so
                # compute it from the two numbers above rather than leaving the
                # row blank or quoting a site-wide rate that means something else.
                rate = round(100 * conv / sess, 2)
                out["GA4-15"] = _f("Pass" if rate >= 1.0 else "Warning",
                                   {"conversion_rate_pct": rate,
                                    "conversions": conv, "sessions": sess},
                                   f"{rate}% of organic sessions convert "
                                   f"({conv:,} of {sess:,}).",
                                   "Low" if rate >= 1.0 else "Medium",
                                   "" if rate >= 1.0 else
                                   "Strengthen calls to action on the pages that "
                                   "receive the most organic traffic.")
    except Exception as e:
        return _need_access(GA4_IDS,
                            f"GA4 query failed: {type(e).__name__}: {e}", "ga4_error")

    # ---- configuration, from the Admin API ---------------------------------
    # Each of these is wrapped on its own: a property whose Admin scope is
    # missing should still keep the reporting rows it already earned.
    for fn in (lambda: _enhanced_row(property_id, tok),
               lambda: _key_events_row(property_id, tok),
               lambda: _host_rows(property_id, tok, site_url, days)):
        try:
            out.update(fn())
        except Exception as exc:  # noqa: BLE001
            print(f"[ga4] config row failed: {type(exc).__name__}: {exc}", flush=True)

    # ---- GA4-04 events -----------------------------------------------------
    try:
        ev = _report(property_id, tok, ["eventName"], ["eventCount"], 50, days)
        if ev:
            named = [(d[0], int(float(m[0]))) for d, m in ev]
            named.sort(key=lambda x: -x[1])
            # An install that only ever fires the automatic events is collecting
            # nothing about what the business cares about.
            auto = {"page_view", "session_start", "first_visit", "user_engagement",
                    "scroll", "click", "form_start", "form_submit", "file_download",
                    "video_start", "video_progress", "video_complete", "view_search_results"}
            custom = [n for n, _ in named if n not in auto]
            out["GA4-04"] = _f("Pass" if custom else "Warning",
                               {"events": len(named), "custom_events": custom[:20],
                                "top": named[:10]},
                               f"{len(named)} event types recorded"
                               + (f", including {len(custom)} beyond GA4's automatic "
                                  f"set ({', '.join(custom[:6])})." if custom else
                                  " — all of them GA4's automatic events, so nothing "
                                  "specific to this business is being measured."),
                               "Low" if custom else "Medium",
                               "" if custom else
                               "Track the actions that matter to this business — "
                               "calls, form submissions, quote requests.", 1.0, "ga4")
    except Exception as exc:  # noqa: BLE001
        print(f"[ga4] eventName report failed: {type(exc).__name__}: {exc}", flush=True)

    # ---- GA4-13 landing pages ----------------------------------------------
    try:
        lp = _report(property_id, tok, ["landingPage"], ["sessions"], 50, days)
        if lp:
            top = [(d[0], int(float(m[0]))) for d, m in lp]
            top.sort(key=lambda x: -x[1])
            tot = sum(n for _, n in top) or 1
            head = round(100 * top[0][1] / tot, 1)
            out["GA4-13"] = _f("Pass" if head < 70 else "Warning",
                               {"landing_pages": len(top), "top": top[:10],
                                "top_share_pct": head},
                               f"{len(top)} pages act as entry points; the busiest "
                               f"({top[0][0]}) takes {head}% of sessions.",
                               "Low" if head < 70 else "Medium",
                               "" if head < 70 else
                               "Traffic concentrated on one page means the rest of "
                               "the site is not earning entries of its own.",
                               1.0, "ga4")
    except Exception as exc:  # noqa: BLE001
        print(f"[ga4] landingPage report failed: {type(exc).__name__}: {exc}", flush=True)

    # ---- GA4-16 revenue ----------------------------------------------------
    try:
        # Two metrics, then one. `transactions` is not accepted by every
        # property and an unknown metric name fails the WHOLE request, taking
        # the revenue figure with it — which is how this row came back blank on
        # a site that simply has no ecommerce.
        try:
            rev = _report(property_id, tok, [],
                          ["totalRevenue", "transactions"], 1, days)
        except Exception:  # noqa: BLE001
            rev = _report(property_id, tok, [], ["totalRevenue"], 1, days)
        # GA4 returns NO ROWS rather than a row of zeros when a property has
        # never recorded revenue. That is an answer — "nothing sold here" — not
        # a failure to read, and treating it as one left the row reported as
        # unbuilt on every non-ecommerce client we have.
        amount = float(rev[0][1][0] or 0) if rev else 0.0
        txns = (int(float(rev[0][1][1] or 0))
                if rev and len(rev[0][1]) > 1 else 0)
        if True:
            out["GA4-16"] = _f(
                "Pass" if amount else "N/A",
                {"total_revenue": round(amount, 2), "transactions": txns},
                f"{amount:,.2f} in tracked revenue from {txns:,} transactions."
                if amount else
                "No revenue is tracked in this property, which is expected for a "
                "site that does not sell online.", "Low", "", 1.0, "ga4")
    except Exception as exc:  # noqa: BLE001
        print(f"[ga4] revenue report failed: {type(exc).__name__}: {exc}", flush=True)

    # GA4-14. Exit pages were a Universal Analytics report. GA4 has no exit-page
    # dimension or metric — the concept did not survive the move to an
    # event-based model. Saying so is the honest answer; leaving it as "Need
    # Access" would imply a grant could produce it.
    out.setdefault("GA4-14", _f(
        "N/A", {},
        "GA4 has no exit-pages report — it was a Universal Analytics concept and "
        "does not exist in the event-based model. Engagement time and landing-page "
        "performance answer the same question.", "Low", "", 1.0, "ga4"))

    for cid in GA4_IDS:
        out.setdefault(cid, _f(
            "Need Access", {},
            "Not retrieved — requires additional GA4 configuration detail (admin "
            "API) beyond the reporting API.", "Low",
            "Read from the GA4 admin interface, or extend to the Admin API.",
            0.0, "ga4_admin_only"))
    return out
