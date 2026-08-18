"""
Browser-capture ingest.

Turns a payload from the Chrome extension into the SAME `SiteArtifact` the
Python crawler produces, so the identical 159 checkers, the identical scoring
and the identical report run over it with no special-casing.

That equivalence is the whole design goal. A second code path for "browser
findings" would drift from the server path within a month and you would have two
subtly different audits to reason about.

What the browser supplies (because a WAF cannot tell it apart from a person):
  * rendered DOM for every sampled page — strictly better than raw HTML on any
    JS-rendered site
  * robots.txt / sitemap.xml / llms.txt, which were also being blocked

What the SERVER still supplies (no browser needed, and not WAF-dependent):
  * TLS certificate, protocol version, expiry
  * PageSpeed Insights (Google fetches the site, we do not)
"""
from __future__ import annotations
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.crawler import Crawler, Page, SiteArtifact, CrawlQuality


def _page_from_payload(d: dict) -> Page:
    """Map one captured page onto the crawler's Page dataclass."""
    p = Page(url=d.get("url", ""), final_url=d.get("final_url") or d.get("url", ""),
             status_code=int(d.get("status_code") or 200), depth=int(d.get("depth") or 0))
    p.content_type = d.get("content_type", "text/html")
    p.bytes_html = int(d.get("bytes_html") or 0)
    p.headers = {k.lower(): v for k, v in (d.get("headers") or {}).items()}
    p.redirect_chain = d.get("redirect_chain") or []
    p.title = d.get("title")
    p.meta_description = d.get("meta_description")
    p.meta_robots = d.get("meta_robots")
    p.x_robots_tag = p.headers.get("x-robots-tag")
    p.canonical = d.get("canonical")
    p.viewport = d.get("viewport")
    p.charset = d.get("charset")
    p.doctype = d.get("doctype")
    p.lang = d.get("lang")
    p.hreflang = d.get("hreflang") or []
    p.h1 = d.get("h1") or []
    # JSON gives lists; the checkers unpack (level, text) tuples.
    p.headings = [tuple(h) if isinstance(h, list) else h for h in (d.get("headings") or [])]
    p.word_count = int(d.get("word_count") or 0)
    p.text_html_ratio = float(d.get("text_html_ratio") or 0)
    p.rendered_text = d.get("rendered_text") or ""
    p.images = d.get("images") or []
    p.links_internal = d.get("links_internal") or []
    p.links_external = d.get("links_external") or []
    p.scripts = d.get("scripts") or []
    p.inline_script_text = d.get("inline_script_text") or ""
    p.schema_types = d.get("schema_types") or []
    p.schema_raw = d.get("schema_raw") or []
    return p


def _parse_sitemap(body: str) -> list:
    import re
    return [m.strip() for m in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body or "", re.I)]


def artifact_from_capture(payload: dict, probe_transport: bool = True) -> SiteArtifact:
    """
    Build a SiteArtifact from a browser capture.

    `probe_transport` runs the server-side TLS and host-resolution probes, which
    do not go through the site's HTTP layer and so are usually unaffected by the
    WAF that blocked the crawl in the first place.
    """
    start = payload.get("start_url") or ""
    cr = Crawler(start, max_pages=1, verbose=False)     # for host parsing + probes
    art = SiteArtifact(start_url=cr.start_url, host=cr.host, scheme=cr.scheme)
    art.crawled_at = time.time()

    for d in payload.get("pages") or []:
        pg = _page_from_payload(d)
        if pg.url:
            art.pages[pg.url] = pg

    # ---- text endpoints, fetched by the browser ----
    robots = payload.get("robots") or {}
    art.robots_status = int(robots.get("status") or 0)
    body = robots.get("body") or ""
    if art.robots_status == 200 and body and not Crawler._is_html(body):
        art.robots_txt = body
        for line in body.splitlines():
            if line.lower().startswith("sitemap:"):
                art.sitemap_urls.append(line.split(":", 1)[1].strip())
    elif art.robots_status == 200 and Crawler._is_html(body):
        art.robots_served_html = True
        art.robots_status = -1

    sm = payload.get("sitemap") or {}
    sm_status = int(sm.get("status") or 0)
    sm_body = sm.get("body") or ""
    sm_url = f"{art.scheme}://{art.host}/sitemap.xml"
    if sm_status == 200 and Crawler._is_html(sm_body):
        art.sitemap_served_html = True
        art.sitemap_status[sm_url] = {"status": -1, "bytes": len(sm_body),
                                      "urls": [], "format_error": False,
                                      "served_html": True}
    else:
        urls = _parse_sitemap(sm_body) if sm_status == 200 else []
        art.sitemap_status[sm_url] = {
            "status": sm_status, "bytes": len(sm_body.encode()),
            "urls": urls, "format_error": sm_status == 200 and not urls,
            "served_html": False}
    art.sitemap_status["_all_urls"] = sorted(set(
        art.sitemap_status.get(sm_url, {}).get("urls", [])))

    llms = payload.get("llms") or {}
    llms_status = int(llms.get("status") or 0)
    llms_body = llms.get("body") or ""
    if llms_status == 200 and Crawler._is_html(llms_body):
        art.llms_served_html = True
        art.llms_txt_status = -1
    else:
        art.llms_txt_status = llms_status
        art.llms_txt = llms_body if llms_status == 200 else None

    # ---- inbound link counts (the checkers expect these) ----
    counts = {u: 0 for u in art.pages}
    for pg in art.pages.values():
        for l in pg.links_internal:
            t = (l.get("href") or "").rstrip("/")
            for cand in (l.get("href"), t, t + "/"):
                if cand in counts and cand != pg.url:
                    counts[cand] += 1
                    break
    for u, n in counts.items():
        art.pages[u].inbound_internal_links = n

    # ---- server-side transport probes ----
    if probe_transport:
        try:
            cr.art = art
            cr.probe_tls()
            cr.probe_www_and_http()
        except Exception as e:
            art.tls = {"valid": False, "error": f"probe failed: {e}"}

    # ---- quality gate, same rules as a server crawl ----
    art.quality = _assess(art)
    return art


def _assess(art: SiteArtifact) -> CrawlQuality:
    """
    Reuse the crawler's own degeneracy rules.

    A browser capture can be degenerate too — if the operator pointed it at the
    wrong site, or every page failed to capture. The safety net must apply to
    this path exactly as it does to the server path.
    """
    ok = [p for p in art.pages.values()
          if not p.error and 200 <= p.status_code < 300]
    if not ok:
        return CrawlQuality(True, "no pages were captured",
                            ["the extension returned zero usable pages"], 0,
                            "capture failed or was stopped before any page loaded")
    home = min(ok, key=lambda p: p.depth)
    sig = []
    if home.bytes_html < 2048:
        sig.append(f"homepage HTML is only {home.bytes_html} bytes")
    if not home.title:
        sig.append("homepage has no <title>")
    if not home.h1:
        sig.append("homepage has no <h1>")
    if not home.links_internal:
        sig.append("homepage exposes no internal links")
    if home.word_count < 50:
        sig.append(f"homepage has {home.word_count} words of text")
    if len(sig) < 3:
        return CrawlQuality(False, "capture looks healthy", [], home.bytes_html, "")
    return CrawlQuality(True, "captured pages are structurally empty",
                        sig, home.bytes_html,
                        "the browser rendered an empty or error page")
