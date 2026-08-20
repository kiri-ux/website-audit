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

SCOPES = ("https://www.googleapis.com/auth/webmasters.readonly "
          "https://www.googleapis.com/auth/analytics.readonly")


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


def collect_gsc(site_url: str, refresh_token: str | None = None,
                days: int = 90) -> dict:
    tok = access_token(refresh_token) if refresh_token else None
    label = "per-audit token" if tok else None
    prop_url = site_url
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

        pages = _api(f"{GSC_API}/sites/{prop}/searchAnalytics/query", tok,
                     {"startDate": str(start), "endDate": str(end),
                      "dimensions": ["page"], "rowLimit": 25})
        top = [r["keys"][0] for r in pages.get("rows", [])][:10]
        out["GSC-22"] = _f("Pass", {"top_pages": top, "via_login": label},
                           f"{len(pages.get('rows', []))} pages received organic "
                           f"traffic in the period (read via {label}).", "Low")
    except Exception as e:
        return _need_access(GSC_IDS,
                            f"Search Console query failed: {type(e).__name__}: {e}",
                            "gsc_error")

    for cid in GSC_IDS:
        out.setdefault(cid, _f(
            "Need Access", {},
            "Not available through the Search Console API — read this from the "
            "Search Console UI (Index Coverage, Core Web Vitals, Enhancements).",
            "Low", "Capture manually from Search Console, or use the Index "
                   "Inspection API for per-URL coverage.", 0.0, "gsc_ui_only"))
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


def collect_ga4(property_id: str | None, refresh_token: str | None,
                days: int = 90, site_url: str = "") -> dict:
    tok = access_token(refresh_token) if refresh_token else None
    label = "per-audit token" if tok else None
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
    except Exception as e:
        return _need_access(GA4_IDS,
                            f"GA4 query failed: {type(e).__name__}: {e}", "ga4_error")

    for cid in GA4_IDS:
        out.setdefault(cid, _f(
            "Need Access", {},
            "Not retrieved — requires additional GA4 configuration detail (admin "
            "API) beyond the reporting API.", "Low",
            "Read from the GA4 admin interface, or extend to the Admin API.",
            0.0, "ga4_admin_only"))
    return out
