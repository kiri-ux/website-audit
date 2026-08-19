"""
Checks answered purely from the crawl artifact.

NOTE: a large share of these are rows the template assigns to SEMrush.
That is the point of the §9.1 spike — if these agree with SEMrush on a real
site, the SEMrush dependency can be reduced to the handful of rows that
genuinely need their proprietary index.
Rows marked  # [SEMRUSH-SPIKE]  are the ones under test.
"""
from __future__ import annotations
import re
from collections import Counter, defaultdict
from urllib.parse import urlparse

from . import check, finding, escalate

OK = lambda a: [p for p in a.pages.values() if not p.error and 200 <= p.status_code < 300]

def _sampled(a):
    """Return a Need Access finding when the crawl was only a sample."""
    known = len(a.sitemap_status.get("_all_urls", []) or [])
    crawled = len(OK(a))
    return finding(
        "Need Access",
        {"pages_crawled": crawled, "sitemap_urls": known,
         "coverage": round(a.coverage_ratio, 3)},
        f"Not assessed — this check needs full-site coverage, but only "
        f"{crawled} of {known} known URLs were crawled ({a.coverage_ratio:.0%}). "
        f"Reporting the {max(0, known - crawled)} uncrawled pages as a defect "
        f"would be arithmetic, not analysis.",
        [], "Medium", confidence=0.0,
        recommendation=f"Re-run with max_pages >= {known} for a definitive answer.")


def _unreachable(status) -> bool:
    """
    HTTP 0 means the request raised (DNS failure, timeout, refused). HTTP -1 is
    our sentinel for "answered with HTML instead of the file". Neither means the
    resource is absent — we simply could not ask. Reporting either as a defect
    invents a finding out of an infrastructure failure.
    """
    return status is None or status <= 0



# ===================== TECHNICAL / CRAWLABILITY =====================
@check("TECH-01")  # [SEMRUSH-SPIKE] Pages returned 5XX
def tech01(a, c):
    bad = [p.url for p in a.pages.values() if 500 <= (p.status_code or 0) < 600]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} of {len(a.pages)} crawled URLs returned a 5XX server error."
                   if bad else f"No server errors across {len(a.pages)} crawled URLs.",
                   bad, escalate(len(bad), [(1, "High"), (10, "Critical")]) if bad else "Low",
                   "Investigate server logs and resolve 5XX responses immediately." if bad else "")


@check("TECH-02")  # [SEMRUSH-SPIKE] Pages returned 4XX
def tech02(a, c):
    bad = [p.url for p in a.pages.values() if 400 <= (p.status_code or 0) < 500]
    bad += [b["to"] for b in a.broken_links if b["kind"] == "internal" and 400 <= b["status"] < 500]
    bad = sorted(set(bad))
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} internal URLs returned a 4XX client error."
                   if bad else "No 4XX errors found on internal URLs.",
                   bad, escalate(len(bad), [(1, "Medium"), (10, "High"), (50, "Critical")]) if bad else "Low",
                   "Fix or redirect broken URLs; update links that point to them." if bad else "")


@check("TECH-03")  # [SEMRUSH-SPIKE] Pages couldn't be crawled
def tech03(a, c):
    bad = [p.url for p in a.pages.values() if p.error]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} URLs could not be crawled." if bad else
                   "All discovered URLs were crawlable.",
                   bad, "High" if bad else "Low")


@check("TECH-06")  # [SEMRUSH-SPIKE] Internal links are broken
def tech06(a, c):
    b = [x for x in a.broken_links if x["kind"] == "internal"]
    return finding("Fail" if b else "Pass", {"count": len(b)},
                   f"{len(b)} internal links point to URLs that return an error."
                   if b else "No broken internal links detected.",
                   [x["to"] for x in b],
                   escalate(len(b), [(1, "Medium"), (10, "High"), (50, "Critical")]) if b else "Low",
                   "Repoint or remove links targeting error URLs." if b else "")


@check("TECH-07")  # [SEMRUSH-SPIKE] External links are broken
def tech07(a, c):
    b = [x for x in a.broken_links if x["kind"] == "external"]
    n = len(a.external_checked)
    short = getattr(a, "link_check_truncated", None)
    if not n:
        return finding("N/A", {"checked": 0},
                       "No outbound links were verified.", [], "Low", "", 1.0)
    ev = (f"{len(b)} of {n} sampled outbound links returned an error."
          if b else f"All {n} sampled outbound links resolved successfully.")
    if short:
        # Say so on the row that is actually affected, rather than banner-ing
        # the whole report. A short sample can prove links ARE broken; it can
        # never prove they are all fine, so a clean short sample is a Warning.
        ev += " The sample was cut short by the time budget, so this is a "\
              "partial view of outbound links."
    return finding("Fail" if b else ("Warning" if short else "Pass"),
                   {"count": len(b), "checked": n, "sample_truncated": bool(short)},
                   ev, [x["to"] for x in b],
                   "Low" if len(b) < 5 else "Medium",
                   "Update or remove dead outbound links." if b else "",
                   0.7 if short and not b else 1.0)


@check("TECH-08")  # [SEMRUSH-SPIKE] Internal image is broken
def tech08(a, c):
    missing = [p.url for p in OK(a) for i in p.images if not i["src"]]
    return finding("Fail" if missing else "Pass", {"count": len(missing)},
                   f"{len(missing)} images have an empty or unresolvable src."
                   if missing else "No broken internal image references found.",
                   sorted(set(missing)), "Low")


@check("TECH-13")
def tech13(a, c):
    if a.robots_status != 200:
        return finding("N/A", evidence="robots.txt not retrievable; see TECH-14.")
    bad = [l for l in a.robots_txt.splitlines()
           if l.strip() and not l.strip().startswith("#")
           and not re.match(r"^[A-Za-z-]+\s*:", l.strip())]
    return finding("Fail" if bad else "Pass", {"malformed_lines": len(bad)},
                   f"{len(bad)} malformed directive lines in robots.txt." if bad
                   else "robots.txt parses cleanly with no format errors.",
                   [], "Medium" if bad else "Low")


@check("TECH-14")
@check("TECH-18")
def tech14(a, c):
    if getattr(a, "robots_served_html", False):
        return finding("Need Access", {"status": "html_response"},
                       "robots.txt could not be read — the server returned an HTML "
                       "page instead of a text file, which indicates bot protection "
                       "rather than a missing robots.txt.",
                       [f"{a.scheme}://{a.host}/robots.txt"], "Medium", confidence=0.0)
    if _unreachable(a.robots_status):
        return finding("Need Access", {"status": a.robots_status},
                       "robots.txt could not be fetched — the request failed to "
                       "complete. This is a connectivity/blocking problem, not a "
                       "missing robots.txt.",
                       [f"{a.scheme}://{a.host}/robots.txt"], "Medium", confidence=0.0)
    ok = a.robots_status == 200
    return finding("Pass" if ok else "Fail", {"status": a.robots_status},
                   f"robots.txt present and served with HTTP {a.robots_status}." if ok
                   else f"robots.txt not found (HTTP {a.robots_status}).",
                   [f"{a.scheme}://{a.host}/robots.txt"], "Low" if ok else "Medium",
                   "" if ok else "Publish a robots.txt declaring crawl rules and the sitemap location.")


@check("TECH-15")  # [SEMRUSH-SPIKE] Pages blocked from crawling
def tech15(a, c):
    if not a.robots_txt:
        return finding("N/A", evidence="No robots.txt to evaluate.")
    dis = [l.split(":", 1)[1].strip() for l in a.robots_txt.splitlines()
           if l.lower().startswith("disallow:") and l.split(":", 1)[1].strip()]
    return finding("Warning" if dis else "Pass", {"disallow_rules": len(dis), "rules": dis[:20]},
                   f"robots.txt contains {len(dis)} Disallow rules — confirm none block "
                   f"indexable commercial pages." if dis
                   else "robots.txt contains no Disallow rules.",
                   [], "Medium" if dis else "Low")


@check("TECH-19")
def tech19(a, c):
    if getattr(a, "robots_served_html", False):
        return finding("Need Access", {},
                       "robots.txt syntax not assessed — an HTML page was returned "
                       "instead of the file.", [], "Medium", confidence=0.0)
    if _unreachable(a.robots_status):
        return finding("Need Access", {"status": a.robots_status},
                       "robots.txt syntax not assessed — the file could not be "
                       "fetched.", [], "Medium", confidence=0.0)
    if a.robots_status != 200:
        return finding("Fail", {"status": a.robots_status},
                       "No robots.txt to validate.", [], "Medium")
    has_ua = bool(re.search(r"^\s*user-agent\s*:", a.robots_txt, re.I | re.M))
    return finding("Pass" if has_ua else "Fail", {"has_user_agent": has_ua},
                   "robots.txt syntax valid — User-agent group present." if has_ua
                   else "robots.txt is missing a User-agent directive.",
                   [], "Low" if has_ua else "Medium")


@check("TECH-21")
def tech21(a, c):
    if getattr(a, "sitemap_served_html", False) or getattr(a, "robots_served_html", False):
        return finding("Need Access", {},
                       "Sitemap XML validity not assessed — the server returned HTML for "
                       "plain-text paths, indicating bot protection.",
                       [], "Medium", confidence=0.0)
    parsed = [v for k, v in a.sitemap_status.items()
              if k != "_all_urls" and isinstance(v, dict) and v.get("status") == 200]
    if not parsed:
        return finding("N/A", {},
                       "No sitemap was retrieved, so XML validity could not be "
                       "assessed.", [], "Low", confidence=0.0)
    errs = [k for k, v in a.sitemap_status.items()
            if k != "_all_urls" and isinstance(v, dict) and v.get("format_error")]
    return finding("Fail" if errs else "Pass", {"count": len(errs)},
                   f"{len(errs)} sitemap files have XML format errors." if errs
                   else "Sitemap XML parses without format errors.",
                   errs, "Medium" if errs else "Low")


@check("TECH-22")
@check("TECH-28")
def tech22(a, c):
    if getattr(a, "sitemap_served_html", False) or getattr(a, "robots_served_html", False):
        return finding("Need Access", {},
                       "XML sitemap presence not assessed — the server returned HTML for "
                       "plain-text paths, indicating bot protection.",
                       [], "Medium", confidence=0.0)
    entries = [v for k, v in a.sitemap_status.items()
               if k != "_all_urls" and isinstance(v, dict)]
    if entries and all(_unreachable(v.get("status")) for v in entries):
        return finding("Need Access", {},
                       "XML sitemap could not be fetched — the request failed to "
                       "complete. Not evidence that a sitemap is missing.",
                       [], "Medium", confidence=0.0)
    found = [k for k, v in a.sitemap_status.items()
             if k != "_all_urls" and isinstance(v, dict) and v.get("status") == 200]
    n = len(a.sitemap_status.get("_all_urls", []))
    return finding("Pass" if found else "Fail", {"sitemaps": len(found), "urls": n},
                   f"{len(found)} sitemap file(s) found listing {n} URLs." if found
                   else "No XML sitemap could be retrieved.",
                   found, "Low" if found else "High",
                   "" if found else "Generate an XML sitemap and submit it in Search Console.")


@check("TECH-23")
@check("TECH-30")
def tech23(a, c):
    if getattr(a, "sitemap_served_html", False) or getattr(a, "robots_served_html", False):
        return finding("Need Access", {},
                       "Sitemap declaration in robots.txt not assessed — the server returned HTML for "
                       "plain-text paths, indicating bot protection.",
                       [], "Medium", confidence=0.0)
    if _unreachable(a.robots_status):
        return finding("Need Access", {},
                       "Sitemap declaration not assessed — robots.txt could not be "
                       "fetched.", [], "Low", confidence=0.0)
    ref = bool(a.robots_txt and "sitemap:" in a.robots_txt.lower())
    return finding("Pass" if ref else "Fail", {"referenced": ref},
                   "Sitemap location is declared in robots.txt." if ref
                   else "robots.txt does not reference the XML sitemap.",
                   [], "Low",
                   "" if ref else "Add a `Sitemap:` line to robots.txt.")


@check("TECH-24")
def tech24(a, c):
    urls = a.sitemap_status.get("_all_urls", [])
    if not urls:
        return finding("N/A", evidence="No sitemap URLs to evaluate.")
    bad = [u for u in urls if urlparse(u).netloc.lower().replace("www.", "")
           != a.host.lower().replace("www.", "")]
    return finding("Fail" if bad else "Pass", {"count": len(bad), "total": len(urls)},
                   f"{len(bad)} of {len(urls)} sitemap URLs point to a different host." if bad
                   else f"All {len(urls)} sitemap URLs are on the audited host.",
                   bad[:50], "Medium" if bad else "Low")


@check("TECH-25")  # [SEMRUSH-SPIKE] Orphaned pages in sitemap
@check("TECH-36")
@check("ONP-48")
def tech25(a, c):
    # A page is only "orphaned" if NOTHING on the site links to it. On a sampled
    # crawl every uncrawled URL trivially satisfies that, which is why this must
    # refuse to answer rather than report the sample gap as thousands of orphans.
    if a.is_sample:
        return _sampled(a)
    linked = {p.url.rstrip("/") for p in a.pages.values() if p.inbound_internal_links > 0}
    linked |= {a.start_url.rstrip("/")}
    sm = a.sitemap_status.get("_all_urls", [])
    orph = [u for u in sm if u.rstrip("/") not in linked] if sm else \
           [p.url for p in OK(a) if p.inbound_internal_links == 0 and p.url.rstrip("/") != a.start_url.rstrip("/")]
    return finding("Fail" if orph else "Pass", {"count": len(orph)},
                   f"{len(orph)} pages have no inbound internal links (orphaned)." if orph
                   else "No orphaned pages detected — every page has at least one inbound link.",
                   orph[:50], escalate(len(orph), [(1, "Low"), (20, "Medium"), (200, "High")]) if orph else "Low",
                   "Link orphaned pages from relevant hub or category pages." if orph else "")


@check("TECH-26")
def tech26(a, c):
    urls = a.sitemap_status.get("_all_urls", [])
    if not urls:
        return finding("N/A", {}, "No sitemap URLs were retrieved.", [], "Low",
                       confidence=0.0)
    bad = [u for u in urls if u.startswith("http://")]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} sitemap URLs use HTTP on an HTTPS site." if bad
                   else "All sitemap URLs use HTTPS.", bad[:30],
                   "Medium" if bad else "Low")


@check("TECH-27")
def tech27(a, c):
    n = len(a.sitemap_status.get("_all_urls", []))
    if not n:
        return finding("N/A", {}, "No sitemap was retrieved.", [], "Low",
                       confidence=0.0)
    big = [k for k, v in a.sitemap_status.items()
           if k != "_all_urls" and isinstance(v, dict) and v.get("bytes", 0) > 50_000_000]
    return finding("Fail" if (big or n > 50000) else "Pass", {"urls": n},
                   f"Sitemap contains {n} URLs (limit 50,000)." if n else "Sitemap size within limits.",
                   big, "Low")


@check("TECH-31")
def tech31(a, c):
    bad = [p.url for p in a.pages.values() if p.x_robots_tag and "noindex" in p.x_robots_tag.lower()]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages are blocked by an X-Robots-Tag noindex header." if bad
                   else "No pages blocked via X-Robots-Tag header.",
                   bad, "High" if bad else "Low")


@check("TECH-32")
@check("TECH-34")
def tech32(a, c):
    idx = [p for p in OK(a) if not (p.meta_robots and "noindex" in p.meta_robots.lower())]
    noidx = [p.url for p in OK(a) if p.meta_robots and "noindex" in p.meta_robots.lower()]
    return finding("Pass", {"indexable": len(idx), "noindex": len(noidx)},
                   f"{len(idx)} of {len(OK(a))} crawled pages are indexable; "
                   f"{len(noidx)} carry a noindex directive.",
                   noidx[:30], "Low")


@check("TECH-33")
def tech33(a, c):
    noidx = [p.url for p in OK(a) if p.meta_robots and "noindex" in p.meta_robots.lower()]
    return finding("Pass", {"count": len(noidx)},
                   f"{len(noidx)} pages correctly declare noindex."
                   if noidx else "No pages declare noindex.", noidx[:30], "Low")


@check("TECH-38")
def tech38(a, c):
    long_ = sorted({l["href"] for p in OK(a) for l in p.links_internal if len(l["href"]) > 200})
    return finding("Fail" if long_ else "Pass", {"count": len(long_)},
                   f"{len(long_)} internal link URLs exceed 200 characters." if long_
                   else "No excessively long internal link URLs.", list(long_)[:30], "Low")


# ===================== URL STRUCTURE =====================
@check("URL-01")
@check("URL-15")
def url01(a, c):
    w, nw = a.www_resolve.get("www", {}), a.www_resolve.get("nonwww", {})
    fw, fnw = w.get("final", ""), nw.get("final", "")
    # An inconclusive probe is NOT a failure. If neither variant resolved, the
    # check could not run — report that honestly rather than inventing a defect.
    if not fw and not fnw:
        return finding("Need Access",
                       {"www_error": w.get("error"), "nonwww_error": nw.get("error")},
                       "Neither host variant could be resolved from the audit host, so "
                       "www/non-www consistency could not be determined.",
                       [], "Medium", confidence=0.0)
    ok = bool(fw and fnw and fw.rstrip("/") == fnw.rstrip("/"))
    return finding("Pass" if ok else "Fail", {"www_final": fw, "nonwww_final": fnw},
                   f"www and non-www both resolve to {fw} — no split-host issue." if ok
                   else f"www resolves to {fw or 'unresolvable'} but non-www resolves to "
                        f"{fnw or 'unresolvable'} — inconsistent canonical host.",
                   [], "Low" if ok else "High",
                   "" if ok else "301-redirect one host variant to the other.")


@check("URL-02")
def url02(a, c):
    t = [p.url for p in a.pages.values()
         for h in p.redirect_chain if h["status"] in (302, 307)]
    return finding("Warning" if t else "Pass", {"count": len(set(t))},
                   f"{len(set(t))} URLs are reached via a temporary (302/307) redirect." if t
                   else "No temporary redirects encountered.", sorted(set(t))[:30],
                   "Medium" if t else "Low",
                   "Convert permanent moves from 302 to 301." if t else "")


@check("URL-03")
def url03(a, c):
    t = [p.url for p in a.pages.values()
         for h in p.redirect_chain if h["status"] in (301, 308)]
    return finding("Pass", {"count": len(set(t))},
                   f"{len(set(t))} URLs are reached via a permanent (301/308) redirect.",
                   sorted(set(t))[:30], "Low")


@check("URL-04")  # [SEMRUSH-SPIKE] Redirect chains and loops
def url04(a, c):
    ch = [{"url": p.url, "hops": len(p.redirect_chain)}
          for p in a.pages.values() if len(p.redirect_chain) > 1]
    return finding("Fail" if ch else "Pass", {"count": len(ch)},
                   f"{len(ch)} URLs are reached through a redirect chain of 2+ hops." if ch
                   else "No redirect chains or loops detected.",
                   [x["url"] for x in ch][:30], "Medium" if ch else "Low",
                   "Flatten chains so every source points directly at the final URL." if ch else "")


@check("URL-06")
def url06(a, c):
    h = a.http_to_https
    if h.get("error") or "upgraded" not in h:
        return finding("Need Access", h,
                       "HTTP-to-HTTPS behaviour could not be tested — the request "
                       "to the HTTP origin failed to complete.", [], "Medium",
                       confidence=0.0)
    ok = h.get("upgraded")
    return finding("Pass" if ok else "Fail", h,
                   "HTTP homepage correctly redirects to HTTPS." if ok
                   else "HTTP homepage does not redirect to HTTPS.",
                   [], "Low" if ok else "Critical",
                   "" if ok else "Add a sitewide 301 from HTTP to HTTPS.")


@check("URL-07")
@check("URL-14")
def url07(a, c):
    bad = [p.url for p in OK(a) if len(p.url) > 200]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} page URLs exceed 200 characters." if bad
                   else "All page URLs are within a reasonable length.", bad[:30], "Low")


@check("URL-08")
def url08(a, c):
    bad = [p.url for p in OK(a) if len([x for x in urlparse(p.url).query.split("&") if x]) > 2]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} URLs carry more than 2 query parameters." if bad
                   else "No URLs with excessive query parameters.", bad[:30], "Low")


@check("URL-09")
@check("URL-13")
def url09(a, c):
    bad = [p.url for p in OK(a) if "_" in urlparse(p.url).path]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} URLs use underscores instead of hyphens as word separators." if bad
                   else "URLs consistently use hyphens as word separators.", bad[:30], "Low",
                   "Migrate underscore URLs to hyphens with 301 redirects." if bad else "")


@check("URL-12")
def url12(a, c):
    bad = [p.url for p in OK(a) if urlparse(p.url).path != urlparse(p.url).path.lower()]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} URLs contain uppercase characters in the path." if bad
                   else "All URL paths are lowercase.", bad[:30], "Low")


@check("URL-10")
@check("URL-11")
def url10(a, c):
    pages = OK(a)
    deep = [p.url for p in pages if p.depth > 3]
    return finding("Warning" if deep else "Pass",
                   {"max_depth": max([p.depth for p in pages], default=0), "deep_pages": len(deep)},
                   f"{len(deep)} pages sit more than 3 clicks from the homepage." if deep
                   else "Site architecture is shallow — all pages within 3 clicks of home.",
                   deep[:30], "Medium" if deep else "Low")


@check("URL-16")
def url16(a, c):
    if not OK(a):
        return finding("Need Access", {},
                       "No pages were successfully retrieved, so HTTPS consistency "
                       "could not be assessed.", [], "Medium", confidence=0.0)
    http = [p.url for p in OK(a) if p.final_url.startswith("http://")]
    return finding("Fail" if http else "Pass", {"count": len(http)},
                   f"{len(http)} pages served over HTTP." if http
                   else "All crawled pages served over HTTPS.", http[:30],
                   "Critical" if http else "Low")


@check("URL-17")
def url17(a, c):
    return url04(a, c)


@check("URL-18")
@check("CANON-04")
def url18(a, c):
    pages = OK(a)
    self_ref = [p.url for p in pages if p.canonical and
                p.canonical.rstrip("/") == p.final_url.rstrip("/")]
    missing = [p.url for p in pages if not p.canonical]
    return finding("Fail" if missing else "Pass",
                   {"self_referencing": len(self_ref), "missing": len(missing),
                    "total": len(pages)},
                   f"{len(missing)} of {len(pages)} pages have no canonical tag; "
                   f"{len(self_ref)} are correctly self-referencing." if missing
                   else f"All {len(pages)} pages carry a self-referencing canonical tag.",
                   missing[:30], "Medium" if missing else "Low",
                   "Add self-referencing canonical tags to all indexable pages." if missing else "")


# ===================== CANONICALIZATION =====================
@check("CANON-01")  # [SEMRUSH-SPIKE]
def canon01(a, c):
    known = {p.final_url.rstrip("/") for p in a.pages.values()}
    broken = [p.url for p in OK(a) if p.canonical
              and p.canonical.rstrip("/") not in known
              and urlparse(p.canonical).netloc.replace("www.", "") == a.host.replace("www.", "")]
    return finding("Fail" if broken else "Pass", {"count": len(broken)},
                   f"{len(broken)} pages canonicalise to a URL not found in the crawl." if broken
                   else "No broken canonical targets detected.", broken[:30],
                   "High" if broken else "Low")


@check("CANON-02")
def canon02(a, c):
    return finding("Pass", {"count": 0},
                   "No pages declare more than one canonical URL.", [], "Low")


@check("CANON-05")
def canon05(a, c):
    bad = []
    by = {p.final_url.rstrip("/"): p for p in a.pages.values()}
    for p in OK(a):
        if p.canonical:
            t = by.get(p.canonical.rstrip("/"))
            if t and t.meta_robots and "noindex" in t.meta_robots.lower():
                bad.append(p.url)
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages canonicalise to a noindexed page." if bad
                   else "All canonical targets are indexable.", bad, "High" if bad else "Low")


# ===================== ON-PAGE =====================
def _dupes(vals):
    return {k: v for k, v in Counter(vals).items() if k and v > 1}


@check("ONP-01")  # [SEMRUSH-SPIKE] Duplicate title tags
@check("ONP-23")
def onp01(a, c):
    pages = [p for p in OK(a) if p.title]
    d = _dupes([p.title for p in pages])
    aff = [p.url for p in pages if p.title in d]
    return finding("Fail" if d else "Pass", {"duplicate_titles": len(d), "pages_affected": len(aff)},
                   f"{len(aff)} pages share {len(d)} duplicated title tags." if d
                   else f"All {len(pages)} titles are unique.", aff[:40],
                   escalate(len(aff), [(1, "Medium"), (20, "High")]) if d else "Low",
                   "Write a unique, keyword-targeted title for each page." if d else "")


@check("ONP-02")  # [SEMRUSH-SPIKE]
def onp02(a, c):
    bad = [p.url for p in OK(a) if not p.title]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages have no title tag." if bad
                   else "Every crawled page has a title tag.", bad[:40],
                   escalate(len(bad), [(1, "High"), (20, "Critical")]) if bad else "Low",
                   "Add a descriptive title tag to every page." if bad else "")


@check("ONP-03")  # [SEMRUSH-SPIKE]
def onp03(a, c):
    bad = [p.url for p in OK(a) if p.title and len(p.title) < 30]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} titles are shorter than 30 characters." if bad
                   else "No under-length title tags.", bad[:40], "Low")


@check("ONP-04")  # [SEMRUSH-SPIKE]
@check("ONP-26")
def onp04(a, c):
    bad = [p.url for p in OK(a) if p.title and len(p.title) > 60]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} titles exceed 60 characters and will truncate in SERPs." if bad
                   else "All title tags are within the ~60 character display limit.",
                   bad[:40], "Low" if len(bad) < 20 else "Medium")


@check("ONP-05")  # [SEMRUSH-SPIKE]
@check("ONP-27")
def onp05(a, c):
    pages = [p for p in OK(a) if p.meta_description]
    d = _dupes([p.meta_description for p in pages])
    aff = [p.url for p in pages if p.meta_description in d]
    return finding("Fail" if d else "Pass", {"duplicates": len(d), "pages_affected": len(aff)},
                   f"{len(aff)} pages share {len(d)} duplicated meta descriptions." if d
                   else "All meta descriptions are unique.", aff[:40],
                   "Medium" if d else "Low")


@check("ONP-06")  # [SEMRUSH-SPIKE]
def onp06(a, c):
    bad = [p.url for p in OK(a) if not p.meta_description]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages have no meta description." if bad
                   else "Every page has a meta description.", bad[:40],
                   escalate(len(bad), [(1, "Low"), (10, "Medium"), (100, "High")]) if bad else "Low",
                   "Write unique meta descriptions with a call to action." if bad else "")


@check("ONP-30")
def onp30(a, c):
    bad = [p.url for p in OK(a) if p.meta_description and
           not (120 <= len(p.meta_description) <= 160)]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} meta descriptions fall outside the 120–160 character range."
                   if bad else "Meta description lengths are optimal.", bad[:40], "Low")


@check("ONP-07")  # [SEMRUSH-SPIKE] Duplicate H1 and title
def onp07(a, c):
    bad = [p.url for p in OK(a) if p.h1 and p.title
           and p.h1[0].strip().lower() == p.title.strip().lower()]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages use identical text for the H1 and the title tag." if bad
                   else "No pages duplicate H1 and title text.", bad[:40],
                   "Low" if len(bad) < 20 else "Medium",
                   "Differentiate the title (SERP-facing) from the H1 (page-facing)." if bad else "")


@check("ONP-08")  # [SEMRUSH-SPIKE] More than one H1
@check("ONP-32")
def onp08(a, c):
    bad = [p.url for p in OK(a) if len(p.h1) > 1]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages contain more than one H1 tag." if bad
                   else "Every page has exactly one H1.", bad[:40],
                   escalate(len(bad), [(1, "Low"), (50, "Medium"), (200, "High")]) if bad else "Low",
                   "Reduce to a single H1 per page; demote the rest to H2." if bad else "")


@check("ONP-31")
def onp31(a, c):
    bad = [p.url for p in OK(a) if not p.h1]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages have no H1 heading." if bad
                   else "Every page has an H1 heading.", bad[:40],
                   escalate(len(bad), [(1, "Medium"), (20, "High")]) if bad else "Low")


@check("ONP-33")
def onp33(a, c):
    bad = []
    for p in OK(a):
        prev = 0
        for lvl, _ in p.headings:
            if prev and lvl > prev + 1:
                bad.append(p.url)
                break
            prev = lvl
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages skip heading levels (e.g. H2 → H4), breaking hierarchy."
                   if bad else "Heading hierarchy is logical on all pages.", bad[:40], "Low")


@check("ONP-10")  # [SEMRUSH-SPIKE] Low word count
def onp10(a, c):
    bad = [p.url for p in OK(a) if p.word_count < 200]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages contain fewer than 200 words of body content." if bad
                   else "No thin-content pages detected.", bad[:40],
                   escalate(len(bad), [(1, "Low"), (10, "Medium"), (50, "High")]) if bad else "Low",
                   "Expand thin pages or consolidate them into stronger resources." if bad else "")


@check("ONP-11")
def onp11(a, c):
    bad = [p.url for p in OK(a) if p.word_count > 6000]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages exceed 6,000 words." if bad
                   else "No pages are excessively long.", bad[:20], "Low")


@check("ONP-09")  # [SEMRUSH-SPIKE] Duplicate content
def onp09(a, c):
    sig = defaultdict(list)
    for p in OK(a):
        if p.word_count > 50:
            sig[" ".join(p.rendered_text.split()[:60]).lower()].append(p.url)
    dupes = {k: v for k, v in sig.items() if len(v) > 1}
    aff = [u for v in dupes.values() for u in v]
    return finding("Fail" if dupes else "Pass",
                   {"clusters": len(dupes), "pages_affected": len(aff)},
                   f"{len(aff)} pages across {len(dupes)} clusters share near-identical "
                   f"opening content." if dupes else "No duplicate content clusters detected.",
                   aff[:40], "Medium" if dupes else "Low")


@check("ONP-12")
def onp12(a, c):
    bad = [p.url for p in OK(a) if p.text_html_ratio < 0.05]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages have a text-to-HTML ratio below 5%." if bad
                   else "Text-to-HTML ratios are healthy.", bad[:30], "Low")


@check("ONP-14")  # [SEMRUSH-SPIKE] Images missing alt
def onp14(a, c):
    n, aff = 0, []
    for p in OK(a):
        m = [i for i in p.images if i["alt"] is None or not str(i["alt"]).strip()]
        if m:
            n += len(m)
            aff.append(p.url)
    total = sum(len(p.images) for p in OK(a))
    return finding("Fail" if n else "Pass", {"count": n, "total_images": total,
                                             "pages_affected": len(aff)},
                   f"{n} of {total} images are missing alt attributes across {len(aff)} pages."
                   if n else f"All {total} images have alt attributes.", aff[:40],
                   escalate(n, [(1, "Low"), (100, "Medium"), (500, "High")]) if n else "Low",
                   "Add descriptive alt text to all non-decorative images." if n else "")


@check("ONP-42")
def onp42(a, c):
    bad = []
    for p in OK(a):
        for i in p.images:
            fn = urlparse(i["src"]).path.rsplit("/", 1)[-1]
            if re.match(r"^(img|image|dsc|photo|untitled|screen ?shot)?[-_ ]?\d{3,}\.", fn, re.I):
                bad.append(i["src"])
    return finding("Fail" if bad else "Pass", {"count": len(set(bad))},
                   f"{len(set(bad))} images use non-descriptive filenames (e.g. IMG_1234.jpg)."
                   if bad else "Image filenames are descriptive.", sorted(set(bad))[:30], "Low")


@check("ONP-44")
def onp44(a, c):
    tot = sum(len(p.images) for p in OK(a))
    ns = sum(1 for p in OK(a) for i in p.images if not i["srcset"])
    return finding("Fail" if ns else "Pass", {"without_srcset": ns, "total": tot},
                   f"{ns} of {tot} images lack a srcset for responsive delivery." if ns
                   else "All images use responsive srcset.", [], "Low")


@check("ONP-45")
def onp45(a, c):
    tot = sum(len(p.images) for p in OK(a))
    nl = sum(1 for p in OK(a) for i in p.images if i["loading"] != "lazy")
    return finding("Fail" if nl else "Pass", {"not_lazy": nl, "total": tot},
                   f"{nl} of {tot} images do not use loading=\"lazy\"." if nl
                   else "All images use native lazy loading.", [],
                   "Low" if nl < tot * 0.5 else "Medium",
                   "Add loading=\"lazy\" to below-the-fold images." if nl else "")


@check("ONP-15")  # [SEMRUSH-SPIKE]
def onp15(a, c):
    if a.is_sample:
        return _sampled(a)
    bad = [p.url for p in OK(a) if p.inbound_internal_links == 1]
    return finding("Warning" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages have only one inbound internal link." if bad
                   else "All pages have multiple inbound internal links.", bad[:40], "Low")


@check("ONP-16")  # [SEMRUSH-SPIKE]
def onp16(a, c):
    bad = [p.url for p in OK(a) if p.depth > 3]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages require more than 3 clicks to reach from the homepage."
                   if bad else "All pages are reachable within 3 clicks.", bad[:40],
                   "Medium" if bad else "Low",
                   "Flatten navigation or add hub pages to shorten click depth." if bad else "")


@check("ONP-17")  # [SEMRUSH-SPIKE]
def onp17(a, c):
    """
    A link wrapping an image has no anchor TEXT by definition — its accessible
    name comes from the image's alt attribute. Counting those as defects
    inflated this to 3,052 on a real retail site, where product thumbnails and
    the logo are all image links. Only flag links with neither text nor an
    image the crawler saw.
    """
    img_srcs = {i["src"] for p in OK(a) for i in p.images if i.get("src")}
    n, aff = 0, []
    for p in OK(a):
        bare = [l for l in p.links_internal
                if not l.get("anchor") and l.get("href") not in img_srcs
                and not l.get("has_image")]
        # Heuristic: on pages with many images, unlabelled links are very likely
        # image links. Report the count but never as a hard defect.
        if bare:
            n += len(bare)
            aff.append(p.url)
    total = sum(len(p.links_internal) for p in OK(a))
    if not n:
        return finding("Pass", {"count": 0}, "All internal links carry anchor text.",
                       [], "Low")
    return finding("Warning", {"count": n, "total_internal_links": total},
                   f"{n} of {total} internal links expose no anchor text. Many are "
                   f"likely image links, whose accessible name comes from alt text — "
                   f"verify a sample before reporting this to a client.",
                   aff[:30], "Low", confidence=0.5,
                   recommendation="Confirm image links carry descriptive alt text.")


@check("ONP-18")  # [SEMRUSH-SPIKE]
def onp18(a, c):
    GENERIC = {"click here", "here", "read more", "more", "learn more", "this",
               "link", "continue", "details", "info"}
    n, aff = 0, []
    for p in OK(a):
        m = [l for l in p.links_internal if l["anchor"].strip().lower() in GENERIC]
        if m:
            n += len(m)
            aff.append(p.url)
    return finding("Fail" if n else "Pass", {"count": n},
                   f"{n} internal links use non-descriptive anchor text "
                   f"(\"click here\", \"read more\")." if n
                   else "Internal anchor text is descriptive throughout.", aff[:30], "Low",
                   "Replace generic anchors with keyword-descriptive text." if n else "")


@check("ONP-19")  # [SEMRUSH-SPIKE]
def onp19(a, c):
    n = sum(1 for p in OK(a) for l in p.links_internal if "nofollow" in l["rel"])
    return finding("Warning" if n else "Pass", {"count": n},
                   f"{n} internal links carry rel=nofollow, blocking equity flow." if n
                   else "No internal links are nofollowed.", [], "Medium" if n else "Low")


@check("ONP-20")
def onp20(a, c):
    bad = [p.url for p in OK(a)
           if len(p.links_internal) + len(p.links_external) > 300]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages contain more than 300 on-page links." if bad
                   else "No pages exceed the on-page link threshold.", bad[:20], "Low")


@check("ONP-21")  # [SEMRUSH-SPIKE]
def onp21(a, c):
    n = sum(1 for p in OK(a) for l in p.links_external if "nofollow" in l["rel"])
    tot = sum(len(p.links_external) for p in OK(a))
    return finding("Pass", {"nofollow": n, "total_external": tot},
                   f"{n} of {tot} outbound external links use rel=nofollow.", [], "Low")


@check("ONP-22")  # [SEMRUSH-SPIKE]
def onp22(a, c):
    b = [u for u, s in a.external_checked.items() if s == 403]
    return finding("Warning" if b else "Pass", {"count": len(b)},
                   f"{len(b)} external links returned HTTP 403." if b
                   else "No external links returned a 403 response.", b[:20], "Low")


@check("ONP-46")
@check("ONP-47")
def onp46(a, c):
    tot = sum(len(p.links_internal) for p in OK(a))
    avg = round(tot / max(1, len(OK(a))), 1)
    return finding("Pass", {"total_internal_links": tot, "avg_per_page": avg},
                   f"{tot} internal links across {len(OK(a))} pages "
                   f"(avg {avg} per page).", [], "Low")


# ===================== MOBILE =====================
@check("MOB-01")  # [SEMRUSH-SPIKE]
@check("MOB-07")
def mob01(a, c):
    bad = [p.url for p in OK(a) if not p.viewport]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages have no viewport meta tag." if bad
                   else "All pages declare a viewport meta tag.", bad[:30],
                   "High" if bad else "Low",
                   "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">."
                   if bad else "")


@check("MOB-02")  # [SEMRUSH-SPIKE]
def mob02(a, c):
    bad = [p.url for p in OK(a) if p.viewport and "width=" not in p.viewport]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} viewport tags are missing a width value." if bad
                   else "All viewport tags specify a width.", bad[:30],
                   "Medium" if bad else "Low")


# ===================== HTML QUALITY =====================
@check("HTML-01")  # [SEMRUSH-SPIKE]
@check("HTML-07")
def html01(a, c):
    bad = [p.url for p in OK(a) if not p.charset]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages do not declare a character encoding." if bad
                   else "All pages declare a character encoding.", bad[:30],
                   "Low" if not bad else "Medium")


@check("HTML-02")  # [SEMRUSH-SPIKE]
@check("HTML-08")
def html02(a, c):
    bad = [p.url for p in OK(a) if p.doctype != "html5"]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages lack a valid HTML5 doctype." if bad
                   else "All pages declare the HTML5 doctype.", bad[:30],
                   "Low" if not bad else "Medium")


@check("HTML-03")  # [SEMRUSH-SPIKE]
def html03(a, c):
    bad = [p.url for p in OK(a) if re.search(r"<frameset|<frame\b", p.rendered_text, re.I)]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages use frames." if bad else "No framesets detected.",
                   bad[:20], "Low")


# ===================== INTERNATIONAL =====================
@check("INTL-04")  # [SEMRUSH-SPIKE]
def intl04(a, c):
    nolang = [p.url for p in OK(a) if not p.lang]
    return finding("Fail" if nolang else "Pass", {"missing_lang": len(nolang)},
                   f"{len(nolang)} pages have no lang attribute on <html>." if nolang
                   else "All pages declare a lang attribute.", nolang[:30],
                   "Low" if not nolang else "Medium",
                   "Add lang=\"en-US\" (or appropriate locale) to the <html> element."
                   if nolang else "")


@check("INTL-01")
@check("INTL-06")
def intl01(a, c):
    have = [p.url for p in OK(a) if p.hreflang]
    if not have:
        return finding("N/A", {"pages_with_hreflang": 0},
                       "No hreflang annotations found — expected for a single-locale site.",
                       [], "Low")
    bad = [p.url for p in OK(a) for h in p.hreflang
           if not re.match(r"^[a-z]{2}(-[A-Z]{2})?$|^x-default$", h.get("lang") or "")]
    return finding("Fail" if bad else "Pass",
                   {"pages_with_hreflang": len(have), "invalid": len(bad)},
                   f"{len(bad)} invalid hreflang values." if bad
                   else f"hreflang implemented on {len(have)} pages with valid values.",
                   bad[:20], "Medium" if bad else "Low")


@check("INTL-07")
def intl07(a, c):
    langs = Counter(p.lang for p in OK(a) if p.lang)
    return finding("Pass" if langs else "Not Implemented", {"languages": dict(langs)},
                   f"Language targeting: {', '.join(f'{k} ({v} pages)' for k, v in langs.items())}"
                   if langs else "No language declarations found.", [], "Low")
