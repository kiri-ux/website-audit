"""
Section 06 — Performance & Core Web Vitals.

Split by data source:
  * Field/lab CWV (PERF-10..14, PERF-19) come from the PageSpeed Insights API.
    Free, no key required at low volume. Degrades to "Need Access" offline.
  * Everything else (compression, minification, caching, HTML weight) is
    derived from response headers the crawler already captured — these are
    [SEMRUSH-SPIKE] rows.
"""
from __future__ import annotations
import json
import re
import urllib.request
from . import check, finding, escalate

OK = lambda a: [p for p in a.pages.values() if not p.error and 200 <= p.status_code < 300]
PSI = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def psi_fetch(url: str, strategy: str = "mobile", timeout: int = 60, key: str | None = None):
    q = f"{PSI}?url={urllib.parse.quote(url, safe='')}&strategy={strategy}"
    for cat in ("performance", "seo", "accessibility", "best-practices"):
        q += f"&category={cat}"
    if key:
        q += f"&key={key}"
    try:
        with urllib.request.urlopen(q, timeout=timeout) as r:
            return json.loads(r.read().decode()), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _psi(a, c):
    """Cached PSI result for the start URL."""
    if "_psi" not in c:
        if c.get("skip_psi"):
            c["_psi"], c["_psi_err"] = None, "PSI collection disabled"
        else:
            c["_psi"], c["_psi_err"] = psi_fetch(a.start_url, key=c.get("psi_key"))
    return c["_psi"], c.get("_psi_err")


def _need_access(err, label):
    return finding("Need Access", {"error": err},
                   f"{label} unavailable — PageSpeed Insights API unreachable from the "
                   f"audit host ({err}).", [], "Medium", confidence=0.0)


def _metric(cid, label, audit_key, good, poor, unit="ms"):
    @check(cid)
    def _fn(a, c, _l=label, _k=audit_key, _g=good, _p=poor, _u=unit):
        data, err = _psi(a, c)
        if not data:
            return _need_access(err, _l)
        try:
            au = data["lighthouseResult"]["audits"][_k]
            val = au.get("numericValue")
            disp = au.get("displayValue", "")
        except Exception as e:
            return _need_access(str(e), _l)
        if val is None:
            return _need_access("metric absent", _l)
        status = "Pass" if val <= _g else ("Warning" if val <= _p else "Fail")
        sev = {"Pass": "Low", "Warning": "Medium", "Fail": "High"}[status]
        return finding(status, {"value": round(val, 3), "display": disp, "unit": _u,
                                "good_threshold": _g, "poor_threshold": _p},
                       f"{_l}: {disp} (good ≤ {_g}{_u}, poor > {_p}{_u}).",
                       [a.start_url], sev,
                       "" if status == "Pass" else f"Improve {_l} to at or below {_g}{_u}.")
    return _fn


_metric("PERF-11", "Largest Contentful Paint (LCP)", "largest-contentful-paint", 2500, 4000)
_metric("PERF-13", "Cumulative Layout Shift (CLS)", "cumulative-layout-shift", 0.1, 0.25, "")
_metric("PERF-14", "Time to First Byte (TTFB)", "server-response-time", 800, 1800)


@check("PERF-10")
def perf10(a, c):
    data, err = _psi(a, c)
    if not data:
        return _need_access(err, "Core Web Vitals assessment")
    try:
        score = round(data["lighthouseResult"]["categories"]["performance"]["score"] * 100)
    except Exception as e:
        return _need_access(str(e), "Core Web Vitals assessment")
    le = data.get("loadingExperience", {})
    overall = le.get("overall_category", "UNKNOWN")
    passed = overall == "FAST"
    return finding("Pass" if passed else "Fail",
                   {"lighthouse_performance": score, "crux_assessment": overall},
                   f"Lighthouse performance score {score}/100; CrUX field assessment: {overall}.",
                   [a.start_url], "Low" if passed else escalate(100 - score,
                                                               [(0, "Medium"), (50, "High")]),
                   "" if passed else "Address the failing Core Web Vitals metrics below.")


@check("PERF-12")
def perf12(a, c):
    data, err = _psi(a, c)
    if not data:
        return _need_access(err, "Interaction to Next Paint (INP)")
    le = data.get("loadingExperience", {}).get("metrics", {})
    inp = le.get("INTERACTION_TO_NEXT_PAINT")
    if not inp:
        return finding("N/A", {},
                       "INP requires CrUX field data; insufficient real-user traffic for "
                       "this origin.", [], "Low", confidence=0.5)
    v = inp.get("percentile")
    status = "Pass" if v <= 200 else ("Warning" if v <= 500 else "Fail")
    return finding(status, {"value": v, "category": inp.get("category")},
                   f"INP p75 = {v}ms ({inp.get('category')}).", [a.start_url],
                   {"Pass": "Low", "Warning": "Medium", "Fail": "High"}[status])


@check("PERF-19")
def perf19(a, c):
    data, err = _psi(a, c)
    if not data:
        return _need_access(err, "Image optimisation")
    auds = data["lighthouseResult"]["audits"]
    keys = ["uses-optimized-images", "modern-image-formats", "uses-responsive-images"]
    fails = {k: auds[k].get("displayValue") for k in keys
             if k in auds and auds[k].get("score") not in (1, None)}
    return finding("Fail" if fails else "Pass", {"failing_audits": fails},
                   f"{len(fails)} image-optimisation audits failing: {', '.join(fails)}."
                   if fails else "Image optimisation audits pass.", [a.start_url],
                   "Medium" if fails else "Low",
                   "Serve next-gen formats (WebP/AVIF) and correctly sized images." if fails else "")


# ---------------- crawler-derived (SEMRUSH-SPIKE rows) ----------------
@check("PERF-01")
def perf01(a, c):
    slow = [p.url for p in OK(a) if p.elapsed_ms > 1500]
    worst = max((p.elapsed_ms for p in OK(a)), default=0)
    return finding("Fail" if slow else "Pass",
                   {"count": len(slow), "worst_ms": worst},
                   f"{len(slow)} pages took over 1.5s to respond (worst {worst}ms)." if slow
                   else f"All pages responded within 1.5s (worst {worst}ms).", slow[:30],
                   "Medium" if slow else "Low")


@check("PERF-02")
def perf02(a, c):
    bad = [p.url for p in OK(a) if p.text_html_ratio < 0.10]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages have a text-to-HTML ratio below 10%." if bad
                   else "Text-to-HTML ratios are healthy across the site.", bad[:30], "Low")


@check("PERF-03")
def perf03(a, c):
    big = [p.url for p in OK(a) if p.bytes_html > 200_000]
    largest = max((p.bytes_html for p in OK(a)), default=0)
    return finding("Fail" if big else "Pass",
                   {"count": len(big), "largest_bytes": largest},
                   f"{len(big)} pages exceed 200KB of HTML (largest {largest//1024}KB)." if big
                   else f"All HTML documents are under 200KB (largest {largest//1024}KB).",
                   big[:30], "Medium" if big else "Low")


@check("PERF-04")
@check("PERF-15")
def perf04(a, c):
    unc = [p.url for p in OK(a)
           if "gzip" not in (p.headers.get("content-encoding") or "").lower()
           and "br" not in (p.headers.get("content-encoding") or "").lower()]
    return finding("Fail" if unc else "Pass", {"count": len(unc), "total": len(OK(a))},
                   f"{len(unc)} of {len(OK(a))} pages are served without GZIP/Brotli "
                   f"compression." if unc
                   else f"All {len(OK(a))} pages served with GZIP/Brotli compression.",
                   unc[:30], escalate(len(unc), [(1, "Medium"), (50, "High")]) if unc else "Low",
                   "Enable Brotli or GZIP compression at the server or CDN." if unc else "")


@check("PERF-06")
@check("PERF-16")
def perf06(a, c):
    nc = [p.url for p in OK(a) if not (p.headers.get("cache-control") or
                                       p.headers.get("expires"))]
    return finding("Fail" if nc else "Pass", {"count": len(nc)},
                   f"{len(nc)} pages send no Cache-Control or Expires header." if nc
                   else "Caching headers present on all pages.", nc[:30],
                   "Medium" if nc else "Low",
                   "Set explicit Cache-Control policies for static assets." if nc else "")


@check("PERF-08")
def perf08(a, c):
    bad = [p.url for p in OK(a) if len(p.scripts) > 30]
    mx = max((len(p.scripts) for p in OK(a)), default=0)
    return finding("Fail" if bad else "Pass", {"count": len(bad), "max_scripts": mx},
                   f"{len(bad)} pages load more than 30 script files (max {mx})." if bad
                   else f"Script counts are reasonable (max {mx} per page).", bad[:20],
                   "Medium" if bad else "Low")


@check("PERF-17")
def perf17(a, c):
    CDN = re.compile(r"cloudflare|cloudfront|fastly|akamai|akamaized|azureedge|"
                     r"stackpath|bunnycdn|keycdn|netlify|vercel|shopifycdn", re.I)
    sigs = set()
    for p in OK(a):
        for k, v in (p.headers or {}).items():
            if k in ("server", "via", "cf-ray", "x-cache", "x-served-by", "x-amz-cf-id"):
                if CDN.search(str(v)) or k in ("cf-ray", "x-amz-cf-id"):
                    sigs.add(f"{k}: {v}"[:60])
        for s in p.scripts:
            if CDN.search(s):
                sigs.add(CDN.search(s).group(0).lower())
    return finding("Pass" if sigs else "Not Implemented",
                   {"signals": sorted(sigs)[:6]},
                   f"CDN detected: {', '.join(sorted(sigs)[:3])}." if sigs
                   else "No CDN signature detected in response headers or asset hosts.",
                   [], "Low" if sigs else "Medium",
                   "" if sigs else "Front the site with a CDN to improve TTFB and global latency.")


@check("PERF-18")
def perf18(a, c):
    tot = sum(len(p.images) for p in OK(a))
    lazy = sum(1 for p in OK(a) for i in p.images if i["loading"] == "lazy")
    pct = round(100 * lazy / max(1, tot))
    return finding("Pass" if pct > 50 else "Fail",
                   {"lazy": lazy, "total": tot, "pct": pct},
                   f"{lazy} of {tot} images ({pct}%) use native lazy loading.", [],
                   "Low" if pct > 50 else "Medium")
