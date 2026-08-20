"""
DataForSEO collector — the credentials Vici already pays for.

This replaces what would otherwise be an Ahrefs or Semrush subscription, and it
fills four gaps at once:

    /backlinks/*                    -> the 29 Off-Page rows
    /dataforseo_labs/ranked_keywords -> the Keyword Rankings table
    /on_page/lighthouse             -> Core Web Vitals + Mobile SEO
                                       (and no more PSI 429s, because Google
                                        fetches the site for DataForSEO, not
                                        from our shared Render egress IP)
    /serp/screenshot                -> the supporting evidence the proposal promises

Auth and retry semantics are copied deliberately from seo-quote's `dfs_post`,
including one hard-won detail worth preserving:

    RATE LIMITS DO NOT ARRIVE AS AN HTTP STATUS. A "40202: rates limit per
    minute exceeded" comes back inside an HTTP 200, nested in the task. Their
    code notes a quote that silently priced at $0 because of exactly this. So we
    inspect the body, and we back off with a real pause rather than the 1s a
    timeout gets — retrying immediately just spends another slot on the same
    refusal.
"""
from __future__ import annotations
import base64
import json
import os
import time
import urllib.error
import urllib.request

BASE = "https://api.dataforseo.com/v3"
TIMEOUT = int(os.getenv("DFS_TIMEOUT", "30"))
RATE_WAIT = float(os.getenv("DFS_RATE_LIMIT_WAIT", "8"))
RATE_CODES = {40202, 40203, 40204, 40205}


def configured() -> bool:
    return bool(os.getenv("DFS_LOGIN") and os.getenv("DFS_PASSWORD"))


def _rate_limited(data: dict) -> bool:
    """A rate limit is reported inside a 200. Check the envelope AND the task."""
    if not isinstance(data, dict):
        return False
    if int(data.get("status_code") or 0) in RATE_CODES:
        return True
    for t in (data.get("tasks") or []):
        if isinstance(t, dict) and int(t.get("status_code") or 0) in RATE_CODES:
            return True
    return False


def dfs_post(path: str, payload, timeout: int | None = None, retries: int = 1):
    login = os.getenv("DFS_LOGIN", "")
    pw = os.getenv("DFS_PASSWORD", "")
    token = base64.b64encode(f"{login}:{pw}".encode()).decode()
    hdrs = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
    body = json.dumps(payload).encode()
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(BASE + path, data=body, headers=hdrs,
                                         method="POST")
            with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as r:
                data = json.loads(r.read())
            if attempt < retries and _rate_limited(data):
                last = RuntimeError("40202: DataForSEO per-minute rate limit")
                time.sleep(RATE_WAIT)
                continue
            if _rate_limited(data):
                raise RuntimeError("40202: DataForSEO per-minute rate limit")
            return data
        except urllib.error.HTTPError as e:
            # 4xx is a real answer about the request; repeating it wastes budget.
            if e.code < 500 or attempt >= retries:
                raise
            last = e
            time.sleep(1.0 + attempt)
        except Exception as e:
            last = e
            if attempt >= retries:
                break
            time.sleep(1.0 + attempt)
    raise last


def _result(data):
    try:
        return (data["tasks"][0]["result"] or [])
    except Exception:
        return []


def _f(status, value=None, evidence="", severity="Medium", rec="", conf=1.0,
       src="dataforseo"):
    return {"status": status, "value": value or {}, "evidence": evidence,
            "affected_pages": [], "severity": severity, "recommendation": rec,
            "confidence": conf, "source": src}


def _need(ids, reason, src="dataforseo_unconfigured"):
    return {cid: _f("Need Access", {}, reason, "Medium",
                    "Set DFS_LOGIN and DFS_PASSWORD on the worker — the same "
                    "credentials the SEO quote tool already uses.", 0.0, src)
            for cid in ids}


# ============================================================== BACKLINKS
OFF_IDS = [f"OFF-{i:02d}" for i in range(1, 30)]


def collect_backlinks(domain: str) -> dict:
    if not configured():
        return _need(OFF_IDS, "DataForSEO credentials not configured.")
    try:
        summary = _result(dfs_post("/backlinks/summary/live",
                                   [{"target": domain, "internal_list_limit": 1,
                                     "backlinks_status_type": "live"}]))
    except Exception as e:
        return _need(OFF_IDS, f"DataForSEO backlinks call failed: "
                              f"{type(e).__name__}: {e}", "dataforseo_error")
    if not summary:
        return _need(OFF_IDS, "DataForSEO returned no backlink summary for this "
                              "domain.", "dataforseo_empty")

    s = summary[0]
    out = {}
    bl = s.get("backlinks")
    rd = s.get("referring_domains")
    rank = s.get("rank")
    spam = s.get("backlinks_spam_score")
    ips = s.get("referring_ips")
    subnets = s.get("referring_subnets")
    nofollow = (s.get("referring_links_attributes") or {}).get("nofollow")
    follow = bl - nofollow if (bl is not None and nofollow is not None) else None
    broken = s.get("broken_backlinks")
    lost = s.get("referring_domains_nofollow")

    def add(cid, ok, val, ev, sev="Low", rec=""):
        out[cid] = _f("Pass" if ok else "Fail", val, ev, sev, rec)

    def info(cid, val, ev):
        """
        A measurement with no threshold behind it.

        "727 total live backlinks" is context, not a verdict — there is no
        number of backlinks that is correct. Recording it as Pass meant that
        merely RETRIEVING it counted as the site doing well, and thirteen such
        rows scored Off-Page authority 94/100 Excellent for a firm with 131
        referring domains. Info is excluded from scoring entirely, so the
        section is scored on the rows that actually judge something.
        """
        out[cid] = _f("Info", val, ev, "Low", "", 1.0, "dataforseo")

    def unmapped(cid, what):
        """
        A checkpoint this endpoint does not answer.

        The previous version reached for the nearest available number, so
        "Lost backlinks" printed the nofollow percentage and "New backlinks"
        printed a count of broken outbound pages. Wrong data under a
        confident-looking label is the one failure mode this whole tool is
        built to avoid — say we do not have it.
        """
        out[cid] = _f("Need Access", {},
                      f"Not retrieved — {what} needs an additional DataForSEO "
                      f"backlinks endpoint.", "Low",
                      "Extend the collector to the backlinks history endpoint.",
                      0.0, "dataforseo_partial")

    if bl is not None:
        info("OFF-01", {"backlinks": bl}, f"{bl:,} total live backlinks.")
    if rd is not None:
        sev = "Low" if rd >= 100 else ("Medium" if rd >= 25 else "High")
        add("OFF-02", rd >= 25, {"referring_domains": rd},
            f"{rd:,} referring domains.", sev,
            "" if rd >= 25 else "Referring-domain count is low — prioritise digital "
                                "PR, resource pages and unlinked-mention reclamation.")
    if ips is not None:
        info("OFF-03", {"referring_ips": ips}, f"{ips:,} referring IPs.")
    if subnets is not None:
        info("OFF-04", {"referring_subnets": subnets},
             f"{subnets:,} referring subnets.")
    if rank is not None:
        sev = "Low" if rank >= 200 else ("Medium" if rank >= 100 else "High")
        add("OFF-05", rank >= 100, {"dfs_rank": rank},
            f"DataForSEO domain rank {rank} (0–1000 scale).", sev)
        out["OFF-06"] = _f("Pass" if rank >= 100 else "Fail", {"dfs_rank": rank},
                           f"Authority equivalent: DataForSEO rank {rank}.", sev)
    if spam is not None:
        ok = spam <= 30
        add("OFF-08", ok, {"spam_score": spam},
            f"Backlink spam score {spam}/100.",
            "Low" if ok else "High",
            "" if ok else "Review and consider disavowing the worst referring domains.")
    if broken is not None:
        add("OFF-12", broken == 0, {"broken_backlinks": broken},
            f"{broken:,} broken backlinks pointing at missing pages.",
            "Low" if not broken else "Medium",
            "" if not broken else "Redirect the target URLs to recover this equity.")
    types = s.get("referring_links_types") or {}
    if isinstance(types, dict) and types.get("image") is not None:
        info("OFF-18", {"image_backlinks": types["image"]},
             f"{types['image']:,} backlinks come from images.")
    # `referring_pages` and `referring_main_domains` come back from this
    # endpoint but answer no checkpoint in the template. Parking them on the
    # nearest free row would be the same mistake in a new place, so they are
    # dropped. The numbers live in OFF-01/OFF-02's value payload if wanted.

    # These four are NOT in the summary endpoint. Do not substitute.
    unmapped("OFF-10", "lost backlinks")
    unmapped("OFF-11", "newly gained backlinks")
    unmapped("OFF-19", "backlinks pointing specifically at the homepage")
    unmapped("OFF-20", "backlinks pointing at deep pages")

    if follow is not None and nofollow is not None and bl:
        pct = round(100 * follow / bl, 1)
        add("OFF-13", pct >= 50, {"follow_pct": pct, "follow": follow,
                                  "nofollow": nofollow},
            f"{pct}% of backlinks are follow links "
            f"({follow:,} follow / {nofollow:,} nofollow).",
            "Low" if pct >= 50 else "Medium")

    # anchors are a separate endpoint; only call it if the summary succeeded
    try:
        anchors = _result(dfs_post("/backlinks/anchors/live",
                                   [{"target": domain, "limit": 40,
                                     "backlinks_status_type": "live"}]))
        items = (anchors[0].get("items") or []) if anchors else []
        if items:
            top = [(i.get("anchor") or "(empty)", i.get("backlinks", 0))
                   for i in items[:12]]
            branded = [a for a, _ in top
                       if domain.split(".")[0].lower() in (a or "").lower()]
            out["OFF-14"] = _f("Pass" if len(set(a for a, _ in top)) > 5 else "Warning",
                               {"distinct_anchors": len(set(a for a, _ in top)),
                                "top": top[:8]},
                               f"{len(set(a for a, _ in top))} distinct anchors in the "
                               f"top {len(top)}; most common: "
                               f"{', '.join(a for a, _ in top[:3])}.", "Low")
            out["OFF-15"] = _f("Pass" if branded else "Warning",
                               {"branded_anchors": len(branded)},
                               f"{len(branded)} of the top anchors are branded.", "Low")
    except Exception:
        pass   # anchors are a bonus; never fail the section over them

    # OFF-21..29 are link PROSPECTING — competitor gap, guest posting, digital
    # PR, HARO, unlinked mentions. They are not measurements of the client's
    # site; they are the outreach work of the campaign itself. Brendan left all
    # nine blank in his audit for the same reason. Reporting them as Need
    # Access implied a missing credential, and dragged the section below the
    # coverage floor so nothing in it could be scored at all.
    PROSPECTING = {f"OFF-{i}" for i in range(21, 30)}
    for cid in OFF_IDS:
        if cid in PROSPECTING:
            out.setdefault(cid, _f(
                "N/A", {},
                "Not measured.", "Low", "", 1.0, "campaign_scope"))
        else:
            out.setdefault(cid, _f(
                "Need Access", {},
                "Not retrieved — requires an additional DataForSEO backlinks "
                "endpoint.", "Medium",
                "Each endpoint is a metered call; add them deliberately rather "
                "than all at once.", 0.0, "dataforseo_not_implemented"))
    return out


# ========================================================= RANKED KEYWORDS
def collect_rankings(domain: str, location_name: str | None = None,
                     limit: int = 25) -> dict:
    """
    The Keyword Rankings & Industry Benchmarks table.

    This is the one report section with no crawler-only path — it needs a rank
    dataset. `ranked_keywords` returns the keywords the domain ALREADY ranks
    for, with volume, difficulty and position, which is exactly the table shape
    in the audit template.
    """
    if not configured():
        return {"available": False,
                "reason": "DataForSEO credentials not configured.", "rows": []}
    payload = [{"target": domain, "limit": limit,
                "order_by": ["keyword_data.keyword_info.search_volume,desc"],
                "location_name": location_name or "United States",
                "language_name": "English"}]
    try:
        res = _result(dfs_post("/dataforseo_labs/google/ranked_keywords/live",
                               payload, timeout=60))
    except Exception as e:
        return {"available": False,
                "reason": f"ranked_keywords call failed: {type(e).__name__}: {e}",
                "rows": []}
    items = (res[0].get("items") or []) if res else []
    rows = []
    for it in items[:limit]:
        kd = it.get("keyword_data") or {}
        ki = kd.get("keyword_info") or {}
        kp = kd.get("keyword_properties") or {}
        se = (it.get("ranked_serp_element") or {}).get("serp_item") or {}
        rows.append({
            "keyword": kd.get("keyword"),
            "search_volume": ki.get("search_volume"),
            "difficulty": kp.get("keyword_difficulty"),
            "position": se.get("rank_absolute"),
            "url": se.get("url"),
        })
    rows.sort(key=lambda r: (r["position"] or 999, -(r["search_volume"] or 0)))
    top10 = [r for r in rows if (r["position"] or 999) <= 10]
    return {"available": True, "rows": rows, "total": len(rows),
            "top10": len(top10),
            "location": location_name or "United States"}


# ============================================================== LIGHTHOUSE
LIGHTHOUSE_IDS = ["PERF-10", "PERF-11", "PERF-12", "PERF-13", "PERF-14", "PERF-19",
                  "MOB-03", "MOB-04", "MOB-05", "MOB-06"]


def collect_lighthouse(url: str) -> dict:
    """
    Core Web Vitals + the Mobile rows, via DataForSEO's hosted Lighthouse.

    Two problems solved at once. PageSpeed Insights was returning 429 because
    unauthenticated calls share a per-IP pool with every other anonymous caller
    on Render's egress. And Google retired the Mobile-Friendly Test API, whose
    replacement is exactly Lighthouse — which is what MOB-03..06 now read.
    """
    if not configured():
        return _need(LIGHTHOUSE_IDS, "DataForSEO credentials not configured.")
    try:
        res = _result(dfs_post("/on_page/lighthouse/live/json",
                               [{"url": url, "for_mobile": True,
                                 "categories": ["performance", "accessibility",
                                                "best-practices", "seo"]}],
                               timeout=120))
    except Exception as e:
        return _need(LIGHTHOUSE_IDS,
                     f"Lighthouse call failed: {type(e).__name__}: {e}",
                     "dataforseo_error")
    if not res:
        return _need(LIGHTHOUSE_IDS, "Lighthouse returned no result.",
                     "dataforseo_empty")

    lh = (res[0].get("lighthouse_result") or res[0].get("items", [{}])[0]
          if isinstance(res[0], dict) else {}) or {}
    audits = lh.get("audits") or {}
    cats = lh.get("categories") or {}

    def num(key):
        a = audits.get(key) or {}
        return a.get("numericValue"), a.get("displayValue")

    def band(v, good, poor, label, cid, unit="ms"):
        if v is None:
            return _f("Need Access", {}, f"{label} not returned by Lighthouse.",
                      "Medium", "", 0.0, "dataforseo_partial")
        st = "Pass" if v <= good else ("Warning" if v <= poor else "Fail")
        return _f(st, {"value": round(v, 3), "good": good, "poor": poor},
                  f"{label}: {round(v,1)}{unit} (good ≤ {good}{unit}).",
                  {"Pass": "Low", "Warning": "Medium", "Fail": "High"}[st],
                  "" if st == "Pass" else f"Reduce {label} to at or below {good}{unit}.")

    out = {}
    lcp, _ = num("largest-contentful-paint")
    cls, _ = num("cumulative-layout-shift")
    ttfb, _ = num("server-response-time")
    tbt, _ = num("total-blocking-time")

    out["PERF-11"] = band(lcp, 2500, 4000, "Largest Contentful Paint", "PERF-11")
    out["PERF-13"] = band(cls, 0.1, 0.25, "Cumulative Layout Shift", "PERF-13", "")
    out["PERF-14"] = band(ttfb, 800, 1800, "Time to First Byte", "PERF-14")
    # INP cannot be measured in a lab run; TBT is the accepted lab proxy and we
    # say so rather than presenting it as INP.
    out["PERF-12"] = (_f("Warning" if tbt and tbt > 200 else "Pass",
                         {"total_blocking_time_ms": tbt, "proxy_for": "INP"},
                         f"Total Blocking Time {round(tbt or 0)}ms — a LAB PROXY for "
                         f"INP, which can only be measured from real user traffic.",
                         "Medium" if tbt and tbt > 200 else "Low", "", 0.6)
                      if tbt is not None else
                      _f("Need Access", {}, "INP requires field data.", "Low", "", 0.0))

    perf = (cats.get("performance") or {}).get("score")
    if perf is not None:
        pct = round(perf * 100)
        out["PERF-10"] = _f("Pass" if pct >= 90 else ("Warning" if pct >= 50 else "Fail"),
                            {"lighthouse_performance": pct},
                            f"Lighthouse mobile performance score {pct}/100.",
                            "Low" if pct >= 90 else ("Medium" if pct >= 50 else "High"))

    img_fail = [k for k in ("uses-optimized-images", "modern-image-formats",
                            "uses-responsive-images", "efficient-animated-content")
                if (audits.get(k) or {}).get("score") not in (1, None)]
    out["PERF-19"] = _f("Fail" if img_fail else "Pass", {"failing": img_fail},
                        f"{len(img_fail)} image-optimisation audits failing: "
                        f"{', '.join(img_fail)}." if img_fail
                        else "Image optimisation audits pass.",
                        "Medium" if img_fail else "Low",
                        "Serve next-gen formats and correctly sized images."
                        if img_fail else "")

    # ---- Mobile rows: the documented replacement for the retired
    #      Mobile-Friendly Test is Lighthouse. These are that reroute.
    vp = (audits.get("viewport") or {}).get("score")
    out["MOB-03"] = _f("Pass" if vp == 1 else "Fail", {"viewport_audit": vp},
                       "Lighthouse mobile viewport audit passes."
                       if vp == 1 else
                       "Lighthouse reports the page is not sized for mobile viewports.",
                       "Low" if vp == 1 else "High")
    out["MOB-04"] = _f("Pass" if vp == 1 else "Fail", {"responsive": vp == 1},
                       "Responsive rendering confirmed by the mobile Lighthouse run."
                       if vp == 1 else "Mobile rendering issues detected.",
                       "Low" if vp == 1 else "High")
    tap = (audits.get("tap-targets") or {}).get("score")
    out["MOB-05"] = (_f("Pass" if tap == 1 else "Fail", {"tap_targets": tap},
                        "Touch targets are appropriately sized and spaced."
                        if tap == 1 else
                        "Touch targets are too small or too close together.",
                        "Low" if tap == 1 else "Medium",
                        "" if tap == 1 else "Increase tap-target size to at least 48x48px.")
                     if tap is not None else
                     _f("Need Access", {}, "Tap-target audit not returned.", "Low",
                        "", 0.0))
    fs = (audits.get("font-size") or {}).get("score")
    out["MOB-06"] = (_f("Pass" if fs == 1 else "Fail", {"font_size": fs},
                        "Font sizes are legible on mobile." if fs == 1 else
                        "Text is too small to read on mobile without zooming.",
                        "Low" if fs == 1 else "Medium")
                     if fs is not None else
                     _f("Need Access", {}, "Font-size audit not returned.", "Low",
                        "", 0.0))

    for cid in LIGHTHOUSE_IDS:
        out.setdefault(cid, _f("Need Access", {},
                               "Not returned by the Lighthouse run.", "Low", "", 0.0,
                               "dataforseo_partial"))
    return out


# ============================================================== SCREENSHOT
def capture_screenshot(url: str) -> dict | None:
    """Supporting evidence — the proposal promises screenshots."""
    if not configured():
        return None
    try:
        res = _result(dfs_post("/serp/screenshot", [{"url": url}], timeout=90))
        if res and res[0].get("items"):
            return {"url": url, "image_url": res[0]["items"][0].get("image_url")}
        if res and res[0].get("image_url"):
            return {"url": url, "image_url": res[0]["image_url"]}
    except Exception:
        return None
    return None
