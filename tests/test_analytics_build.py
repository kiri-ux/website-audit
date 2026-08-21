"""
Search Console and GA4: the 27 rows that used to say "read this from the UI".

Before this build, a granted, working Google connection filled 11 of 38 rows and
left 27 saying some version of "we haven't built this yet". Every one of those 27
had a real answer available — through the URL Inspection API, the searchAppearance
dimension, the GA4 Admin API, or data the audit already held in its own hands.

What this file guards:

  1. With a working connection, the rows are ANSWERED. Not "present" — answered,
     with a status that is not Need Access.
  2. The sampled ones say they are sampled. GSC-05 reads a bounded number of URLs
     through URL Inspection, and the difference between "18 of 25 pages we checked
     are indexed" and "18 pages are indexed" is the difference between a defensible
     statement and a lie about a 400-page site.
  3. Absence is not automatically a defect. A law firm has no product rich results
     and no ecommerce revenue; those rows are Info and N/A, and are kept out of the
     score rather than counted as failures.
  4. Three link reports have no API at all (GSC-20/21/22) and one row has no
     equivalent in GA4 at all (GA4-14). They must not be dressed up as a missing
     client grant — and the three link reports are answered from the backlink
     index instead of being left for an analyst, which is tested at the bottom
     of this file.
  5. Losing a token still degrades everything to Need Access, never to Fail.
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine.collectors.analytics as A          # noqa: E402
from engine.access import blocked_on             # noqa: E402
from engine.crawler import Page                  # noqa: E402
from engine import scoring                       # noqa: E402

FAILED: list[str] = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILED.append(label)


# --------------------------------------------------------------- fake artifact
class Art:
    start_url = "https://example.com/"
    http_to_https = {"upgraded": True}

    def __init__(self):
        self.pages = {}
        for i in range(12):
            u = f"https://example.com/p{i}"
            pg = Page(url=u, final_url=u, status_code=200, depth=1 if i < 4 else 2)
            pg.inbound_internal_links = 0 if i == 11 else 3
            pg.word_count = 400
            self.pages[u] = pg


# ------------------------------------------------------------------ fake Google
def gsc_api(url, token, payload=None, timeout=60):
    if url.endswith("/sites"):
        return {"siteEntry": [{"siteUrl": "https://example.com/"}]}
    if "searchAnalytics" in url:
        dims = (payload or {}).get("dimensions") or []
        if dims == ["searchAppearance"]:
            return {"rows": [{"keys": ["BREADCRUMBS"], "clicks": 12, "impressions": 400}]}
        if dims == ["page"]:
            return {"rows": [{"keys": ["https://example.com/p1"]}]}
        return {"rows": [{"clicks": 500, "impressions": 20000,
                          "ctr": 0.025, "position": 14.2}]}
    if "index:inspect" in url:
        n = int(payload["inspectionUrl"].rsplit("p", 1)[1])
        if n < 8:
            idx = {"verdict": "PASS", "coverageState": "Submitted and indexed",
                   "pageFetchState": "SUCCESSFUL"}
        elif n == 8:
            idx = {"verdict": "NEUTRAL",
                   "coverageState": "Crawled - currently not indexed",
                   "pageFetchState": "SUCCESSFUL"}
        elif n == 9:
            idx = {"verdict": "NEUTRAL",
                   "coverageState": "Discovered - currently not indexed",
                   "pageFetchState": "SUCCESSFUL"}
        else:
            idx = {"verdict": "FAIL", "coverageState": "Error",
                   "pageFetchState": "REDIRECT_ERROR"}
        return {"inspectionResult": {"indexStatusResult": idx}}
    raise AssertionError(f"unexpected GSC call: {url}")


def ga4_api(url, token, payload=None, timeout=60):
    if ":runReport" in url:
        d = [x["name"] for x in (payload.get("dimensions") or [])]
        if d == ["sessionDefaultChannelGroup"]:
            return {"rows": [
                {"dimensionValues": [{"value": "Organic Search"}],
                 "metricValues": [{"value": "4200"}, {"value": "0.62"},
                                  {"value": "0.38"}, {"value": "310000"},
                                  {"value": "58"}]},
                {"dimensionValues": [{"value": "Direct"}],
                 "metricValues": [{"value": "900"}] * 5}]}
        if d == ["hostName"]:
            return {"rows": [
                {"dimensionValues": [{"value": "example.com"}],
                 "metricValues": [{"value": "5000"}]},
                {"dimensionValues": [{"value": "staging.example.com"}],
                 "metricValues": [{"value": "120"}]}]}
        if d == ["eventName"]:
            return {"rows": [{"dimensionValues": [{"value": v}],
                              "metricValues": [{"value": str(c)}]}
                             for v, c in [("page_view", 9000),
                                          ("session_start", 5000),
                                          ("generate_lead", 58)]]}
        if d == ["landingPage"]:
            return {"rows": [{"dimensionValues": [{"value": p}],
                              "metricValues": [{"value": str(c)}]}
                             for p, c in [("/", 3000), ("/services", 900)]]}
        if d == []:
            return {"rows": [{"dimensionValues": [],
                              "metricValues": [{"value": "0"}, {"value": "0"}]}]}
    if url.endswith("/dataStreams"):
        return {"dataStreams": [{"name": "properties/123/dataStreams/9",
                                 "type": "WEB_DATA_STREAM"}]}
    if "enhancedMeasurementSettings" in url:
        return {"streamEnabled": True, "scrollsEnabled": True,
                "outboundClicksEnabled": True, "siteSearchEnabled": False,
                "videoEngagementEnabled": True, "fileDownloadsEnabled": True,
                "formInteractionsEnabled": False}
    if url.endswith("/keyEvents"):
        return {"keyEvents": [{"eventName": "generate_lead"},
                              {"eventName": "phone_call"}]}
    raise AssertionError(f"unexpected GA4 call: {url}")


def with_api(fn, call):
    real_api, real_tok, real_idx = A._api, A.access_token, A._token_index
    A._api, A.access_token, A._token_index = fn, (lambda rt: "tok"), (lambda: {"vici": "rt"})
    try:
        return call()
    finally:
        A._api, A.access_token, A._token_index = real_api, real_tok, real_idx


def main():
    art = Art()
    known = {"PERF-11": {"value": {"crux_assessment": "AVERAGE",
                                   "lighthouse_performance": 71}}}
    A._SEEN_INSPECT_KEYS = False
    A._SEEN_GA4_KEYS = set()

    gsc = with_api(gsc_api, lambda: A.collect_gsc(
        "http://example.com", "rt", artifact=art, known=known))
    ga4 = with_api(ga4_api, lambda: A.collect_ga4(
        "123", "rt", site_url="https://example.com"))

    print("SEARCH CONSOLE — THE ROWS THE REPORTING API DOES NOT COVER")
    still = sorted(k for k, v in gsc.items() if v["status"] == "Need Access")
    # The three link reports. Google publishes them and exposes no API; the
    # backlink collector fills them in a later stage of the same run, so from
    # here they are correctly still blank.
    check("only the three link reports remain for the backlink collector",
          still == ["GSC-20", "GSC-21", "GSC-22"], str(still))
    for cid in ("GSC-05", "GSC-06", "GSC-07", "GSC-08", "GSC-09", "GSC-10",
                "GSC-11", "GSC-12", "GSC-13", "GSC-14", "GSC-15", "GSC-19"):
        check(f"{cid} is answered", gsc[cid]["status"] != "Need Access",
              gsc[cid]["status"])

    print("\nA SAMPLE IS DESCRIBED AS A SAMPLE")
    # The whole risk of URL Inspection is that a bounded read gets written up as
    # a sitewide count. Both halves of the denominator have to appear in the
    # sentence the client reads.
    ev = gsc["GSC-05"]["evidence"]
    check("the indexed count carries its denominator",
          "of 12" in ev and "inspected" in ev, ev)
    check("the value records what was sampled",
          gsc["GSC-05"]["value"].get("sampled") == 12,
          str(gsc["GSC-05"]["value"]))
    check("coverage counts are right", (gsc["GSC-05"]["value"]["indexed"],
                                        gsc["GSC-06"]["value"]["excluded"]) == (8, 4),
          str(gsc["GSC-05"]["value"]))
    check("a redirect error is a Fail, not a warning",
          gsc["GSC-11"]["status"] == "Fail" and gsc["GSC-11"]["value"]["pages"] == 2)
    check("a clean state is a Pass, not silence",
          gsc["GSC-09"]["status"] == "Pass")

    print("\nABSENCE IS NOT AUTOMATICALLY A DEFECT")
    check("breadcrumbs that appeared are a Pass", gsc["GSC-15"]["status"] == "Pass")
    check("product results the site never had are Info, not Fail",
          gsc["GSC-16"]["status"] == "Info", gsc["GSC-16"]["status"])
    check("Info is kept out of the score", "Info" in scoring.EXCLUDED)

    print("\nOUR OWN DATA ANSWERS THE REPORTS WITH NO API")
    check("Core Web Vitals come from the CrUX data we already fetched",
          gsc["GSC-12"]["value"].get("crux_assessment") == "AVERAGE")
    check("HTTPS is measured from our own fetches",
          gsc["GSC-13"]["status"] == "Pass"
          and gsc["GSC-13"]["value"]["checked"] == 12)
    check("the internal link graph finds the orphan",
          gsc["GSC-19"]["value"]["no_inbound"] == 1, str(gsc["GSC-19"]["value"]))

    print("\nA REPORT WITH NO API IS NOT THE CLIENT'S HOMEWORK")
    check("GSC-20 is an analyst's job, not a missing grant",
          blocked_on("GSC-20", gsc["GSC-20"]) == "manual")
    check("GSC-21 is an analyst's job, not a missing grant",
          blocked_on("GSC-21", gsc["GSC-21"]) == "manual")
    check("it names what would answer it",
          "DataForSEO" in gsc["GSC-20"]["evidence"])
    # The bug this replaced: GSC-22 "Top linked pages" was filled with the
    # pages that got the most organic TRAFFIC. A real number under the wrong
    # label is worse than an admitted gap.
    check("top linked pages is not answered with top trafficked pages",
          "received organic traffic" not in (gsc["GSC-22"]["evidence"] or ""))
    check("the traffic figure is kept where it belongs",
          "pages received organic traffic" in gsc["GSC-01"]["evidence"],
          gsc["GSC-01"]["evidence"])

    print("\nGA4 — CONFIGURATION, NOT JUST TRAFFIC")
    still = sorted(k for k, v in ga4.items() if v["status"] == "Need Access")
    check("no GA4 row is left unanswered", still == [], str(still))
    check("Enhanced Measurement names what is switched off",
          "form interactions" in ga4["GA4-03"]["evidence"]
          and ga4["GA4-03"]["status"] == "Warning")
    check("key events are read from the Admin API",
          ga4["GA4-06"]["value"]["key_events"] == ["generate_lead", "phone_call"])
    check("a custom event is recognized as more than GA4's automatic set",
          ga4["GA4-04"]["value"]["custom_events"] == ["generate_lead"],
          str(ga4["GA4-04"]["value"]["custom_events"]))
    check("staging traffic in the property is a Fail",
          ga4["GA4-08"]["status"] == "Fail"
          and "staging.example.com" in ga4["GA4-08"]["evidence"])
    check("subdomains alone are not a cross-domain problem",
          ga4["GA4-07"]["status"] == "Pass", ga4["GA4-07"]["evidence"][:60])
    check("engagement time is an average per session, not a total",
          ga4["GA4-12"]["value"]["avg_engagement_seconds"] == 73.8,
          str(ga4["GA4-12"]["value"]))
    check("conversion rate is computed from the two organic numbers",
          ga4["GA4-15"]["value"]["conversion_rate_pct"] == 1.38,
          str(ga4["GA4-15"]["value"]))
    check("landing pages name the busiest entry point",
          ga4["GA4-13"]["value"]["top"][0][0] == "/")

    print("\nWHAT GA4 SIMPLY DOES NOT HAVE")
    check("exit pages are N/A, not Need Access", ga4["GA4-14"]["status"] == "N/A")
    check("the reason is stated, not implied",
          "Universal Analytics" in ga4["GA4-14"]["evidence"])
    check("no revenue on a non-ecommerce site is N/A, not a failure",
          ga4["GA4-16"]["status"] == "N/A")

    print("\nLOSING ACCESS STILL DEGRADES TO NEED ACCESS, NEVER TO FAIL")
    def blind(url, token, payload=None, timeout=60):
        raise RuntimeError("403")
    A._SEEN_INSPECT_KEYS = False
    g2 = with_api(blind, lambda: A.collect_gsc("http://example.com", "rt",
                                               artifact=art, known=known))
    a2 = with_api(blind, lambda: A.collect_ga4("123", "rt",
                                               site_url="https://example.com"))
    for name, block in (("Search Console", g2), ("GA4", a2)):
        check(f"{name} emits no Fail without a working connection",
              not [k for k, v in block.items() if v["status"] == "Fail"])
        check(f"{name} degrades entirely to Need Access",
              {v["status"] for v in block.values()} == {"Need Access"},
              str({v["status"] for v in block.values()}))

    print("\nTHE THREE LINK REPORTS ARE ANSWERED FROM THE BACKLINK INDEX")
    # "An analyst opens Search Console and reads it off" is a plan that means it
    # never happens. Every one of these questions is answered by data the
    # backlink collector already pays for and already fetches.
    import engine.collectors.dataforseo as D

    def dfs(path, payload, timeout=None, retries=1):
        if "domain_pages" in path:
            items = [{"page_address": "https://example.com/", "backlinks": 400},
                     {"page_address": "https://example.com/services",
                      "backlinks": 120},
                     {"page_address": "https://example.com/about", "backlinks": 9}]
        elif "referring_domains" in path:
            order = (payload[0].get("order_by") or [""])[0]
            if order.startswith("backlinks,"):
                items = [{"domain": "bigpaper.com", "backlinks": 220},
                         {"domain": "citydirectory.org", "backlinks": 90}]
            else:
                items = [{"domain": "spammy.xyz", "backlinks_spam_score": 88},
                         {"domain": "ok.com", "backlinks_spam_score": 4}]
        else:
            items = []
        return {"tasks": [{"result": [{"items": items}]}]}

    real = D.dfs_post
    D.dfs_post = dfs
    try:
        out = {}
        D._page_split("example.com", out, 131)
        D._link_reports("example.com", out, 727)
    finally:
        D.dfs_post = real

    for cid in ("GSC-20", "GSC-21", "GSC-22"):
        check(f"{cid} is answered", out.get(cid, {}).get("status") == "Info",
              str(out.get(cid, {}).get("status")))
    check("external links carries the real total",
          out["GSC-20"]["value"]["external_links"] == 727)
    check("top linking sites are ordered by volume, biggest first",
          out["GSC-21"]["value"]["top_linking_sites"][0] == ("bigpaper.com", 220),
          str(out["GSC-21"]["value"]["top_linking_sites"][:2]))
    # The toxicity check queries the same endpoint ordered by SPAM score. If
    # GSC-21 reused that sample it would name the most-linked of the 200
    # diciest domains and call it the top linking site.
    check("and NOT from the spam-ordered sample the toxicity check uses",
          "spammy.xyz" not in str(out["GSC-21"]["value"]))
    check("top linked pages are ordered by links, not by traffic",
          out["GSC-22"]["value"]["top_linked_pages"][0]
          == ("https://example.com/", 400),
          str(out["GSC-22"]["value"]["top_linked_pages"][:2]))

    print("\nAND EVERY ONE OF THEM SAYS IT IS NOT SEARCH CONSOLE'S NUMBER")
    # Ours are generally larger — Google's Links report shows a sample. Someone
    # who opens Search Console, sees a different figure and was not warned stops
    # trusting the whole document.
    for cid in ("GSC-20", "GSC-21", "GSC-22"):
        ev = out[cid]["evidence"]
        check(f"{cid} names its source", "backlink index" in ev, ev[:70])
        check(f"{cid} warns the two will not match",
              "sample" in ev and "lower" in ev)

    print("\n" + "=" * 68)
    if FAILED:
        print(f"  {len(FAILED)} FAILED: {FAILED}")
    else:
        print("  ALL CHECKS PASSED — 27 Search Console and Analytics rows "
              "now carry measurements")
    print("=" * 68 + "\n")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
