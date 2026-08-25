"""
Section 09 — Structured Data (SCHEMA-*)
Section 12 — E-E-A-T page-existence rows (the deterministic subset)
Section 13 — GEO / AI readiness (the deterministic subset)

The GEO rows here are the ones the template calls "Manual Review" but which
are pure fact retrieval: does /llms.txt exist, does robots.txt admit AI
crawlers, is there FAQ schema. The genuinely subjective GEO rows (entity
optimization, citation-worthiness) are Tier B and are NOT implemented here.
"""
from __future__ import annotations
import re
from collections import Counter
from . import check, finding

OK = lambda a: [p for p in a.pages.values() if not p.error and 200 <= p.status_code < 300]

CORE_SCHEMA = {
    "SCHEMA-02": ("Organization", ["Organization", "Corporation", "LocalBusiness",
                                   "Store", "FurnitureStore", "HomeGoodsStore"]),
    "SCHEMA-03": ("WebSite", ["WebSite"]),
    "SCHEMA-04": ("BreadcrumbList", ["BreadcrumbList"]),
    "SCHEMA-05": ("Article", ["Article", "BlogPosting", "NewsArticle"]),
    "SCHEMA-06": ("Product", ["Product", "ProductGroup"]),
    "SCHEMA-07": ("FAQPage", ["FAQPage", "QAPage"]),
    "SCHEMA-08": ("Review", ["Review", "AggregateRating"]),
    "SCHEMA-09": ("LocalBusiness", ["LocalBusiness", "Store", "FurnitureStore",
                                    "HomeGoodsStore"]),
}


def _all_types(a):
    c = Counter()
    for p in OK(a):
        c.update(p.schema_types)
    return c


def _make_schema(cid, label, types):
    @check(cid)
    def _fn(a, c, _l=label, _t=types):
        found = c.setdefault("_schema_counts", _all_types(a))
        hits = {t: found[t] for t in _t if found.get(t)}
        pages = [p.url for p in OK(a) if any(t in p.schema_types for t in _t)]
        ok = bool(hits)
        return finding("Pass" if ok else "Not Implemented",
                       {"implemented": ok, "types_found": hits, "pages": len(pages)},
                       f"{_l} schema found on {len(pages)} pages ({', '.join(hits)})." if ok
                       else f"{_l} schema is not implemented anywhere on the site.",
                       pages[:20], "Low" if ok else "Medium",
                       "" if ok else f"Implement {_l} structured data to improve rich-result "
                                     f"and AI-citation eligibility.")
    return _fn


for _cid, (_l, _t) in CORE_SCHEMA.items():
    _make_schema(_cid, _l, _t)


@check("SCHEMA-01")
def schema01(a, c):
    bad = [p.url for p in OK(a) if "__INVALID_JSONLD__" in p.schema_types]
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} pages contain malformed JSON-LD that fails to parse." if bad
                   else "All JSON-LD blocks parse as valid JSON.", bad[:20],
                   "High" if bad else "Low",
                   "Fix JSON-LD syntax errors — invalid blocks are ignored entirely." if bad else "")


@check("SCHEMA-10")
def schema10(a, c):
    counts = c.setdefault("_schema_counts", _all_types(a))
    withs = [p.url for p in OK(a) if p.schema_types]
    pct = round(100 * len(withs) / max(1, len(OK(a))))
    return finding("Pass" if pct > 50 else "Fail",
                   {"pages_with_schema": len(withs), "coverage_pct": pct,
                    "distinct_types": len(counts)},
                   f"{len(withs)} of {len(OK(a))} pages ({pct}%) carry structured data, "
                   f"across {len(counts)} distinct types.",
                   [], "Low" if pct > 50 else "Medium")


# ---------------- GEO / AI readiness (deterministic subset) ----------------
AI_CRAWLERS = ["GPTBot", "ClaudeBot", "Claude-Web", "anthropic-ai", "PerplexityBot",
               "Google-Extended", "CCBot", "Bingbot", "Applebot-Extended",
               "Meta-ExternalAgent", "Amazonbot"]


@check("GEO-01")
@check("GEO-03")
def geo01(a, c):
    if getattr(a, "llms_served_html", False):
        return finding("Need Access", {"status": "html_response"},
                       "/llms.txt could not be read — the server returned an HTML "
                       "page rather than a text file. This indicates bot protection, "
                       "not a published llms.txt.", [], "Medium", confidence=0.0)
    if a.llms_txt_status is None or a.llms_txt_status <= 0:
        return finding("Need Access", {"status": a.llms_txt_status},
                       "/llms.txt could not be fetched — the request failed to "
                       "complete. Not evidence that llms.txt is missing.",
                       [], "Medium", confidence=0.0)
    ok = a.llms_txt_status == 200
    return finding("Pass" if ok else "Not Implemented",
                   {"status": a.llms_txt_status, "bytes": len(a.llms_txt or "")},
                   f"/llms.txt found ({len(a.llms_txt or '')} bytes)." if ok
                   else f"/llms.txt not found (HTTP {a.llms_txt_status}).", [],
                   "Low" if ok else "Medium",
                   "" if ok else "Publish an /llms.txt describing the site's key pages and "
                                 "entities for AI crawlers.")


@check("GEO-02")
def geo02(a, c):
    if getattr(a, "llms_served_html", False):
        return finding("Need Access", {},
                       "/llms.txt formatting not assessed — an HTML page was "
                       "returned instead of the file.", [], "Low", confidence=0.0)
    if a.llms_txt_status != 200:
        return finding("N/A", evidence="No /llms.txt to validate.", severity="Low")
    t = a.llms_txt or ""
    has_h1 = bool(re.search(r"^#\s+\S", t, re.M))
    has_links = bool(re.search(r"\[.+?\]\(.+?\)", t))
    ok = has_h1 and has_links
    return finding("Pass" if ok else "Fail",
                   {"has_title": has_h1, "has_links": has_links},
                   "llms.txt follows the expected Markdown structure." if ok
                   else "llms.txt is present but missing a title heading or link list.",
                   [], "Low" if ok else "Medium")


@check("GEO-04")
def geo04(a, c):
    # "No robots.txt therefore all AI crawlers are allowed" is a vacuous truth
    # when robots.txt was simply unreachable. Only assert it when we actually
    # read the file.
    if a.robots_status is None or a.robots_status <= 0:
        return finding("Need Access", {"robots_status": a.robots_status},
                       "AI crawler policy not assessed — robots.txt could not be "
                       "fetched.", [], "Medium", confidence=0.0)
    txt = a.robots_txt or ""
    blocked, allowed = [], []
    for bot in AI_CRAWLERS:
        m = re.search(rf"user-agent:\s*{re.escape(bot)}\s*(.*?)(?=^user-agent:|\Z)",
                      txt, re.I | re.S | re.M)
        if m and re.search(r"^\s*disallow:\s*/\s*$", m.group(1), re.I | re.M):
            blocked.append(bot)
        else:
            allowed.append(bot)
    return finding("Fail" if blocked else "Pass",
                   {"blocked": blocked, "allowed_count": len(allowed)},
                   f"robots.txt blocks {len(blocked)} AI crawlers: {', '.join(blocked)}. "
                   f"These cannot cite the site." if blocked
                   else f"All {len(AI_CRAWLERS)} major AI crawlers are permitted by robots.txt.",
                   [], "High" if blocked else "Low",
                   "Allow AI crawlers unless there is a deliberate policy reason not to."
                   if blocked else "")


@check("GEO-06")
def geo06(a, c):
    # rendered_text has tags stripped, so heading structure is the proxy for
    # "machine-parseable document outline".
    structured = [p.url for p in OK(a) if p.headings]
    pct = round(100 * len(structured) / max(1, len(OK(a))))
    return finding("Pass" if pct > 80 else "Fail",
                   {"pages_with_heading_structure": len(structured), "pct": pct},
                   f"{pct}% of pages expose a heading structure machine parsers can follow.",
                   [], "Low" if pct > 80 else "Medium")


@check("GEO-08")
def geo08(a, c):
    bad = []
    for p in OK(a):
        prev = 0
        for lvl, _ in p.headings:
            if prev and lvl > prev + 1:
                bad.append(p.url)
                break
            prev = lvl
    noh1 = [p.url for p in OK(a) if not p.h1]
    tot = sorted(set(bad + noh1))
    return finding("Fail" if tot else "Pass",
                   {"skipped_levels": len(bad), "missing_h1": len(noh1)},
                   f"{len(tot)} pages have a broken heading hierarchy (skipped levels or no H1) — "
                   f"this degrades AI extraction." if tot
                   else "Heading hierarchy is clean sitewide.", tot[:30],
                   "Medium" if tot else "Low")


@check("GEO-10")
def geo10(a, c):
    faq = [p.url for p in OK(a) if any(t in p.schema_types for t in ("FAQPage", "QAPage"))]
    return finding("Pass" if faq else "Not Implemented", {"pages": len(faq)},
                   f"FAQ schema implemented on {len(faq)} pages." if faq
                   else "No FAQPage or QAPage schema found anywhere on the site.",
                   faq[:20], "Low" if faq else "Medium",
                   "" if faq else "Add FAQ sections with FAQPage schema — the highest-leverage "
                                  "format for AI Overview and chatbot citation.")


@check("GEO-19")
def geo19(a, c):
    counts = c.setdefault("_schema_counts", _all_types(a))
    present = [l for cid, (l, ts) in CORE_SCHEMA.items() if any(counts.get(t) for t in ts)]
    missing = [l for cid, (l, ts) in CORE_SCHEMA.items() if not any(counts.get(t) for t in ts)]
    return finding("Fail" if missing else "Pass",
                   {"present": present, "missing": missing,
                    "coverage": f"{len(present)}/{len(CORE_SCHEMA)}"},
                   f"{len(present)} of {len(CORE_SCHEMA)} core schema types implemented. "
                   f"Missing: {', '.join(missing)}." if missing
                   else "All core schema types are implemented.", [],
                   "Medium" if missing else "Low")


# ---------------- E-E-A-T page-existence subset ----------------
TRUST_PAGES = {
    "EEAT-12": ("Contact page", r"/contact"),
    "EEAT-13": ("About page", r"/about|/our-story|/who-we-are|/company"),
    "EEAT-15": ("Privacy Policy", r"/privacy"),
    "EEAT-16": ("Terms & Conditions", r"/terms|/tos|/conditions"),
    "EEAT-17": ("Refund / Return Policy", r"/refund|/return|/exchange"),
    "EEAT-18": ("Disclosure page", r"/disclosure|/disclaimer|/accessibility"),
    "EEAT-07": ("Author pages", r"/author|/team|/staff|/our-people|/bio"),
}


def _make_trust(cid, label, pattern):
    @check(cid)
    def _fn(a, c, _l=label, _p=pattern):
        hits = [p.url for p in OK(a) if re.search(_p, p.url, re.I)]
        linked = [l["href"] for p in OK(a) for l in p.links_internal
                  if re.search(_p, l["href"], re.I)]
        found = hits or linked
        return finding("Pass" if found else "Not Implemented",
                       {"pages": len(set(hits)), "linked": len(set(linked))},
                       f"{_l} present ({len(set(hits or linked))} URL(s))." if found
                       else f"No {_l} found in the crawl.",
                       sorted(set(hits or linked))[:10],
                       "Low" if found else "Medium",
                       "" if found else f"Publish a {_l} — a baseline trust signal for E-E-A-T.")
    return _fn


for _cid, (_l, _p) in TRUST_PAGES.items():
    _make_trust(_cid, _l, _p)


@check("EEAT-19")
def eeat19(a, c):
    tls = a.tls or {}
    if tls.get("error"):
        return finding("Need Access", {"error": tls.get("error")},
                       "HTTPS trust not assessed — the TLS handshake could not be "
                       "completed, which means the host was unreachable rather than "
                       "insecure.", [], "Medium", confidence=0.0)
    ok = tls.get("valid")
    return finding("Pass" if ok else "Fail", {"tls_valid": bool(ok)},
                   "Site served over valid HTTPS — baseline trust signal met." if ok
                   else "TLS validation failed.", [], "Low" if ok else "Critical")


@check("EEAT-24")
def eeat24(a, c):
    BADGE = re.compile(r"bbb|trustpilot|verified|secure|guarantee|accredited|"
                       r"norton|mcafee|ssl|award|certified", re.I)
    hits = sorted({i["src"] for p in OK(a) for i in p.images
                   if BADGE.search(i["src"] or "") or BADGE.search(str(i["alt"] or ""))})
    return finding("Pass" if hits else "Not Implemented", {"count": len(hits)},
                   f"{len(hits)} trust-badge style images detected." if hits
                   else "No trust badges or accreditation imagery detected.",
                   list(hits)[:15], "Low" if hits else "Low")
