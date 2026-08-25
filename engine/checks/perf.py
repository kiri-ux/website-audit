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
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from . import check, finding, escalate, REGISTRY

OK = lambda a: [p for p in a.pages.values() if not p.error and 200 <= p.status_code < 300]
PSI = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


# PageSpeed Insights fetches the page itself, runs Lighthouse on Google's
# hardware and then returns — so the round trip is a genuine 30-60 seconds on a
# slow site, and 60 was not enough headroom. A timeout here does not fail one
# row: it fails EVERY row that reads Lighthouse, which is now fourteen of them,
# and a single retry recovers most of it for one wasted minute.
PSI_TIMEOUT = int(os.getenv("PSI_TIMEOUT", "120"))
PSI_ATTEMPTS = int(os.getenv("PSI_ATTEMPTS", "2"))


def psi_fetch(url: str, strategy: str = "mobile", timeout: int | None = None,
              key: str | None = None, attempts: int | None = None):
    q = f"{PSI}?url={urllib.parse.quote(url, safe='')}&strategy={strategy}"
    for cat in ("performance", "seo", "accessibility", "best-practices"):
        q += f"&category={cat}"
    if key:
        q += f"&key={key}"
    last = None
    for i in range(max(1, attempts if attempts is not None else PSI_ATTEMPTS)):
        try:
            with urllib.request.urlopen(
                    q, timeout=timeout or PSI_TIMEOUT) as r:
                return json.loads(r.read().decode()), None
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            print(f"[psi] attempt {i + 1} failed for {url}: {last}", flush=True)
            # A 4xx is an answer about the request — a bad URL, a bad key, a
            # quota refusal — and repeating it just spends the quota again.
            if isinstance(e, urllib.error.HTTPError) and e.code < 500:
                break
            time.sleep(2 + 3 * i)
    return None, last


def _psi(a, c):
    """
    A Lighthouse report for the start URL, from whichever provider answers.

    ONE accessor, TWO providers, and that is the whole point. PageSpeed Insights
    is unreachable from Render often enough — 429s on the shared egress pool,
    then read timeouts — that a single failure took down every row reading it:
    fourteen checks in a client's report, each one printing our own
    "TimeoutError: The read operation timed out".

    DataForSEO hosts Lighthouse and answers the same schema, so the fallback
    belongs here rather than in fourteen separate checks. PSI is still tried
    first, because only PSI carries CrUX field data — real visitors rather than
    a lab run — and that is what PERF-11/12/13 prefer to be judged on.
    """
    if "_psi" not in c:
        if c.get("skip_psi"):
            c["_psi"], c["_psi_err"] = None, "Lab performance collection was "\
                                             "switched off for this run"
        else:
            c["_psi"], c["_psi_err"] = psi_fetch(a.start_url, key=c.get("psi_key"))
            c["_psi_source"] = "PageSpeed Insights"
    if c.get("_psi") is None and not c.get("_psi_fallback_tried"):
        c["_psi_fallback_tried"] = True
        try:
            from engine.collectors.dataforseo import lighthouse_report
            lh, err = lighthouse_report(a.start_url)
        except Exception as e:  # noqa: BLE001
            lh, err = None, f"{type(e).__name__}: {e}"
        if lh:
            print(f"[perf] PageSpeed Insights unavailable ({c.get('_psi_err')}); "
                  f"using the DataForSEO Lighthouse run instead", flush=True)
            # Wrapped in PSI's envelope so every existing check reads it
            # unchanged. No CrUX block, which the field-data checks already
            # handle as "not enough traffic" rather than as a failure.
            c["_psi"] = {"lighthouseResult": lh}
            c["_psi_err"] = None
            c["_psi_source"] = "Lighthouse via DataForSEO"
        else:
            print(f"[perf] no Lighthouse from either provider — PSI: "
                  f"{c.get('_psi_err')}; DataForSEO: {err}", flush=True)
    return c["_psi"], c.get("_psi_err")


def _need_access(err, label):
    """
    What the CLIENT reads when no provider answered.

    Not the exception. "PageSpeed Insights API unreachable from the audit host
    (TimeoutError: The read operation timed out)" is a line from our logs, and
    it went out in a paid document fourteen times in one report. The technical
    detail stays in `value`, where the team can see it and the client cannot.
    """
    # RETRYABLE MEANS "NOT ABOUT THE SITE".
    #
    # Every other Need Access on this report is a fact we could not reach —
    # a credential, a permission, a page we could not read. This one is a
    # third party being unreachable from our host, and the sentence below
    # says so in as many words. That distinction is what lets a re-run carry
    # last week's real number forward instead of overwriting it with a gap:
    # nothing about the site changed, so last week's measurement of the site
    # is still a measurement of the site.
    return finding("Need Access", {"error": err, "internal": True,
                                   "retryable": True},
                   f"{label} could not be measured on this run — the speed-testing "
                   f"service did not respond. Nothing about the site caused this, "
                   f"and it is re-run rather than left.",
                   [], "Medium", confidence=0.0)


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


# EVERY CHECKPOINT THAT LIVES OR DIES ON ONE HTTP CALL.
#
# Nine rows read the same Lighthouse report, so when neither provider answers
# it is never one Need Access — it is nine, all with the identical sentence,
# filling the internal panel with what looks like nine separate defects. This
# list is what lets a third source fill exactly those nine and nothing else.
PSI_CHECK_IDS = ("PERF-05", "PERF-07", "PERF-09", "PERF-10", "PERF-11",
                 "PERF-12", "PERF-13", "PERF-14", "PERF-19")


class _StubSite:
    """
    The little that a Lighthouse-reading check touches on the artifact.

    All nine read `a.start_url` and nothing else — they get every other fact
    out of the report. So a re-run of just these nine does not need the crawl
    reconstituted, which matters because the run that needs this most is the
    consent-only run, where there may not be a full crawl to reconstitute.
    """

    def __init__(self, start_url):
        self.start_url = start_url
        self.pages = {}
        self.quality = None


def findings_from_psi(start_url: str, report: dict) -> dict:
    """
    Run the same nine checkers over a Lighthouse report from anywhere.

    A THIRD PROVIDER, NOT A THIRD CLASSIFIER.

    PageSpeed Insights is refused from Render often enough to take out the
    whole section — 429s on the shared egress pool, then read timeouts — and
    the DataForSEO fallback has its own bad days. The operator's own browser
    is a third route to the SAME Google endpoint, on a residential IP that
    Google is not rate-limiting, and it costs nothing.

    What arrives here is the raw PSI response, unread. The extension does not
    decide what a good LCP is, or which audit key holds it: these nine
    functions do, exactly as they do on the server path. Two graders would
    eventually disagree about the same site with no way to tell which was
    right — the same rule the consent capture follows.
    """
    if not (report or {}).get("lighthouseResult"):
        return {}
    a = _StubSite(start_url)
    c = {"_psi": report, "_psi_err": None,
         "_psi_source": "PageSpeed Insights, fetched in the browser",
         # Already answered. Without this the fallback would run again on the
         # first check that finds a metric missing.
         "_psi_fallback_tried": True}
    out = {}
    for cid in PSI_CHECK_IDS:
        fn = REGISTRY.get(cid)
        if not fn:
            continue
        try:
            f = fn(a, c)
        except Exception as exc:  # noqa: BLE001
            continue
        if f is None:
            continue
        f.setdefault("source", "perf")
        out[cid] = f
    return out


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
    overall = le.get("overall_category") or "UNKNOWN"

    # CrUX is Google's REAL-USER data, and a site below its traffic threshold
    # simply has none. Two things were wrong with printing "UNKNOWN": it is a
    # raw API token in a client document, and it was treated as a failure —
    # so a fast site with modest traffic failed the checkpoint for the crime of
    # not being popular enough to measure. Fall back to the lab score, and say
    # which one the reader is looking at.
    if overall in ("FAST", "AVERAGE", "SLOW"):
        passed = overall == "FAST"
        word = {"FAST": "good", "AVERAGE": "needs improvement",
                "SLOW": "poor"}[overall]
        ev = (f"Lighthouse performance score {score}/100. Real-visitor data "
              f"from Google rates this site {word}.")
    else:
        passed = score >= 90
        # WAS three clauses about our method: lab test, traffic threshold,
        # "so the lab score is what we have". All true, none of it the
        # client's problem, and it buried the only number in the sentence.
        # Lead with the score, and say the caveat once, plainly.
        ev = (f"Site speed scores {score}/100 in a simulated test. Google has "
              f"not collected enough real visitor data on this site to report "
              f"its own speed rating.")
    return finding("Pass" if passed else "Fail",
                   {"lighthouse_performance": score, "crux_assessment": overall},
                   ev,
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


# ---------------- asset delivery, from the same Lighthouse run ----------
#
# PERF-05, 07 and 09 were sitting in the report as "Manual — read the DevTools
# waterfall", which is a strange thing to ask of an analyst when the Lighthouse
# run we ALREADY make for PERF-10/11/19 answers all three outright. Nothing new
# is fetched here; this reads audits already in the response.


def _byte_kb(aud) -> int:
    """`overallSavingsBytes` is where Lighthouse puts the wasted weight."""
    d = (aud or {}).get("details") or {}
    for k in ("overallSavingsBytes", "wastedBytes"):
        v = d.get(k) if isinstance(d, dict) else None
        if isinstance(v, (int, float)) and v:
            return int(v / 1024)
    return 0


@check("PERF-05")
def perf05(a, c):
    data, err = _psi(a, c)
    if not data:
        return _need_access(err, "Text compression")
    aud = (data["lighthouseResult"]["audits"] or {}).get("uses-text-compression")
    if not aud:
        return finding("N/A", {}, "Lighthouse did not report on text "
                                  "compression for this page.", [], "Low",
                       confidence=0.5)
    ok = aud.get("score") in (1, None)
    kb = _byte_kb(aud)
    return finding("Pass" if ok else "Fail", {"wasted_kb": kb},
                   "Text assets are served compressed." if ok else
                   f"JavaScript and CSS are served uncompressed — "
                   f"{kb:,} KB of transfer wasted on the homepage alone.",
                   [a.start_url], "Low" if ok else "Medium",
                   "" if ok else "Turn on gzip or brotli compression at the "
                                 "server or CDN. It is a configuration change, "
                                 "not a code change.")


@check("PERF-07")
def perf07(a, c):
    data, err = _psi(a, c)
    if not data:
        return _need_access(err, "Minification")
    auds = data["lighthouseResult"]["audits"] or {}
    bad, kb = [], 0
    for key, label in (("unminified-javascript", "JavaScript"),
                       ("unminified-css", "CSS")):
        aud = auds.get(key)
        if aud and aud.get("score") not in (1, None):
            bad.append(label)
            kb += _byte_kb(aud)
    if not any(k in auds for k in ("unminified-javascript", "unminified-css")):
        return finding("N/A", {}, "Lighthouse did not report on minification "
                                  "for this page.", [], "Low", confidence=0.5)
    return finding("Pass" if not bad else "Fail",
                   {"unminified": bad, "wasted_kb": kb},
                   "JavaScript and CSS are minified." if not bad else
                   f"{' and '.join(bad)} {'is' if len(bad) == 1 else 'are'} "
                   f"not minified — {kb:,} KB of avoidable weight.",
                   [a.start_url], "Low" if not bad else "Medium",
                   "" if not bad else "Enable minification in the build or at "
                                      "the CDN.")


@check("PERF-09")
def perf09(a, c):
    data, err = _psi(a, c)
    if not data:
        return _need_access(err, "Script and stylesheet weight")
    items = (((data["lighthouseResult"]["audits"] or {})
              .get("resource-summary") or {}).get("details") or {}).get("items") or []
    by = {str(i.get("resourceType", "")).lower(): i for i in items}
    js = int((by.get("script") or {}).get("transferSize") or 0)
    css = int((by.get("stylesheet") or {}).get("transferSize") or 0)
    if not (js or css):
        return finding("N/A", {}, "Lighthouse did not report a resource "
                                  "breakdown for this page.", [], "Low",
                       confidence=0.5)
    kb = round((js + css) / 1024)
    # 500 KB of script and stylesheet is already heavy for a content site; it is
    # roughly where Lighthouse's own scoring starts penalising main-thread work.
    ok = kb <= 500
    return finding("Pass" if ok else "Fail",
                   {"js_kb": round(js / 1024), "css_kb": round(css / 1024),
                    "total_kb": kb},
                   f"JavaScript and CSS total {kb:,} KB on the homepage "
                   f"({round(js / 1024):,} KB of script, "
                   f"{round(css / 1024):,} KB of styles).",
                   [a.start_url], "Low" if ok else "Medium",
                   "" if ok else "Split the bundles, drop unused libraries and "
                                 "defer what is not needed for first paint.")


# ---------------- mobile + accessibility, same Lighthouse run -----------
#
# MOB-03..06 and HTML-09 were reporting "Waiting on our data provider for this
# run" — which is not true and reads to a client as an unfinished audit. The
# Lighthouse run this module ALREADY makes is a MOBILE run, and it carries every
# one of these audits. Nothing new is fetched.
#
# One honest note on MOB-03: Google retired the standalone Mobile-Friendly Test
# API. What replaced it is exactly these Lighthouse audits, so that is what the
# row says it is.


def _aud(data, key):
    return ((data.get("lighthouseResult") or {}).get("audits") or {}).get(key)


def _failed(data, key):
    """True only if the audit ran AND failed. A missing audit is not a failure."""
    a = _aud(data, key)
    return bool(a) and a.get("score") not in (1, None)


@check("MOB-03")
def mob03(a, c):
    data, err = _psi(a, c)
    if not data:
        return _need_access(err, "Mobile friendliness")
    keys = {"viewport": "no mobile viewport is declared",
            "content-width": "content is wider than the screen",
            "font-size": "text is too small to read without zooming",
            "tap-targets": "tap targets are too small or too close together"}
    present = [k for k in keys if _aud(data, k)]
    if not present:
        return finding("N/A", {}, "Lighthouse returned no mobile audits for "
                                  "this page.", [], "Low", confidence=0.5)
    bad = [keys[k] for k in present if _failed(data, k)]
    return finding("Pass" if not bad else "Fail",
                   {"checked": present, "failing": bad},
                   "The homepage passes Google's mobile checks — viewport, "
                   "content width, text size and tap targets."
                   if not bad else
                   f"The homepage fails {len(bad)} of Google's mobile checks: "
                   f"{'; '.join(bad)}.",
                   [a.start_url], "Low" if not bad else "High",
                   "" if bad == [] else "Fix these before anything else on "
                                        "mobile — most of this site's visitors "
                                        "arrive on a phone.")


@check("MOB-04")
def mob04(a, c):
    data, err = _psi(a, c)
    if not data:
        return _need_access(err, "Responsive design")
    if not (_aud(data, "viewport") or _aud(data, "content-width")):
        return finding("N/A", {}, "Lighthouse returned no viewport audit for "
                                  "this page.", [], "Low", confidence=0.5)
    vp = _failed(data, "viewport")
    cw = _failed(data, "content-width")
    bits = []
    if vp:
        bits.append("no viewport meta tag is set")
    if cw:
        bits.append("the page is wider than the viewport")
    return finding("Pass" if not bits else "Fail",
                   {"viewport_ok": not vp, "content_width_ok": not cw},
                   "The page declares a mobile viewport and fits the screen."
                   if not bits else
                   f"The layout does not adapt to a phone — {' and '.join(bits)}.",
                   [a.start_url], "Low" if not bits else "High",
                   "" if not bits else "Add a responsive viewport meta tag and "
                                       "make the layout fluid.")


@check("MOB-05")
def mob05(a, c):
    data, err = _psi(a, c)
    if not data:
        return _need_access(err, "Touch elements")
    aud = _aud(data, "tap-targets")
    if not aud:
        return finding("N/A", {}, "Lighthouse did not report on tap targets "
                                  "for this page.", [], "Low", confidence=0.5)
    ok = aud.get("score") in (1, None)
    n = len((((aud.get("details") or {}).get("items")) or []))
    return finding("Pass" if ok else "Fail", {"undersized_targets": n},
                   "Buttons and links are large enough and far enough apart to "
                   "tap accurately." if ok else
                   f"{n} button(s) or link(s) are too small or too close "
                   f"together to tap reliably on a phone.",
                   [a.start_url], "Low" if ok else "Medium",
                   "" if ok else "Give tap targets at least 48x48px and 8px of "
                                 "space around them.")


@check("MOB-06")
def mob06(a, c):
    data, err = _psi(a, c)
    if not data:
        return _need_access(err, "Font readability")
    aud = _aud(data, "font-size")
    if not aud:
        return finding("N/A", {}, "Lighthouse did not report on font sizes for "
                                  "this page.", [], "Low", confidence=0.5)
    ok = aud.get("score") in (1, None)
    return finding("Pass" if ok else "Fail",
                   {"legible": ok, "detail": aud.get("displayValue")},
                   "Body text is large enough to read on a phone without "
                   "zooming." if ok else
                   f"Some text is too small to read on a phone without zooming "
                   f"({aud.get('displayValue') or 'below 12px'}).",
                   [a.start_url], "Low" if ok else "Medium",
                   "" if ok else "Set a base font size of at least 16px on "
                                 "body copy.")


@check("HTML-09")
def html09(a, c):
    data, err = _psi(a, c)
    if not data:
        return _need_access(err, "Accessibility basics")
    cats = (data.get("lighthouseResult") or {}).get("categories") or {}
    acc = (cats.get("accessibility") or {}).get("score")
    if acc is None:
        return finding("N/A", {}, "Lighthouse returned no accessibility score "
                                  "for this page.", [], "Low", confidence=0.5)
    sc = round(acc * 100)
    named = [k for k in ("color-contrast", "image-alt", "link-name",
                         "button-name", "label", "html-has-lang")
             if _failed(data, k)]
    return finding("Pass" if sc >= 90 else "Fail", {"score": sc, "failing": named},
                   f"Accessibility scores {sc}/100 on the homepage"
                   + (f"; the failing basics are {', '.join(named)}." if named
                      else " with no failing basics."),
                   [a.start_url], "Low" if sc >= 90 else "Medium",
                   "" if sc >= 90 else "Fix the failing items above — most are "
                                       "contrast, alt text and unlabelled "
                                       "controls, and all are quick.")


@check("ONP-43")
def onp43(a, c):
    """Same audit as PERF-05; the template asks the question in both sections."""
    data, err = _psi(a, c)
    if not data:
        return _need_access(err, "Compression")
    aud = _aud(data, "uses-text-compression")
    if not aud:
        return finding("N/A", {}, "Lighthouse did not report on compression "
                                  "for this page.", [], "Low", confidence=0.5)
    ok = aud.get("score") in (1, None)
    kb = _byte_kb(aud)
    return finding("Pass" if ok else "Fail", {"wasted_kb": kb},
                   "Text assets are served compressed." if ok else
                   f"Compression is off — {kb:,} KB of avoidable transfer on "
                   f"the homepage alone.",
                   [a.start_url], "Low" if ok else "Medium",
                   "" if ok else "Turn on gzip or brotli at the server or CDN.")


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
    """
    Compression, with corroboration.

    A missing Content-Encoding header is suggestive but not conclusive — some
    CDNs strip it after decompressing at the edge. So we cross-check the
    transferred byte count (Content-Length) against the decoded document size.
    If they are close, the bytes really did travel uncompressed. If
    Content-Length is far smaller, compression happened and only the header is
    absent, which is a very different (and much less urgent) finding.
    """
    pages = OK(a)
    unc, corroborated, header_only = [], 0, 0
    for p in pages:
        enc = (p.headers.get("content-encoding") or "").lower()
        if "gzip" in enc or "br" in enc or "deflate" in enc:
            continue
        unc.append(p.url)
        try:
            clen = int(p.headers.get("content-length") or 0)
        except ValueError:
            clen = 0
        if clen and p.bytes_html and clen < p.bytes_html * 0.75:
            header_only += 1        # far smaller on the wire => it WAS compressed
        elif clen and p.bytes_html:
            corroborated += 1       # wire size ~= document size => genuinely raw

    if not unc:
        return finding("Pass", {"count": 0, "total": len(pages)},
                       f"All {len(pages)} pages served with GZIP/Brotli compression.",
                       [], "Low")

    if header_only and header_only >= corroborated:
        return finding("Warning",
                       {"count": len(unc), "total": len(pages),
                        "wire_smaller_than_document": header_only},
                       f"{len(unc)} pages send no Content-Encoding header, but on "
                       f"{header_only} of them the transferred size is well below the "
                       f"document size — so the content WAS compressed and only the "
                       f"header is missing. Verify at the CDN before reporting this.",
                       unc[:20], "Low", confidence=0.5,
                       recommendation="Confirm edge compression settings; the header "
                                      "may be stripped after edge decompression.")

    return finding("Fail",
                   {"count": len(unc), "total": len(pages),
                    "size_corroborated": corroborated},
                   f"{len(unc)} of {len(pages)} pages are served without GZIP/Brotli "
                   f"compression"
                   + (f" — confirmed on {corroborated} by comparing transferred bytes "
                      f"against document size." if corroborated else "."),
                   unc[:30],
                   escalate(len(unc), [(1, "Medium"), (50, "High")]),
                   "Enable Brotli or GZIP compression at the server or CDN.")


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
