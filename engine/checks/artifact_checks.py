"""
Checkpoints answerable from the crawl we already hold.

Every check in here was previously reported as "Manual — an analyst answers
this by hand", which was true only in the sense that nobody had written it.
None of them needs a single new request to the client's site: the robots.txt,
the asset URLs, the hreflang tags, the response codes and the redirect chains
are all sitting in the artifact already.

The bar for including a check here is deliberately high: it must be decidable
from stored data, and it must be decidable CORRECTLY. A check that can only
half-answer belongs in the manual pile, because a confident half-answer is the
failure mode this whole tool is built to avoid. Anything needing the raw HTML
(meta refresh, plugin embeds) or a fresh fetch (asset weight, minification) is
deliberately NOT here — the crawler does not retain what those need, and
guessing from `rendered_text` would be exactly that half-answer.
"""
from __future__ import annotations
import re
from urllib.parse import urlparse

from . import check, finding

OK = lambda a: [p for p in a.pages.values()
                if not p.error and 200 <= p.status_code < 300]

# Language subtags we accept without a region. Not exhaustive by design: the
# check only FAILS on a value that cannot be a language tag at all, so a rare
# but valid tag passes rather than generating a false defect.
_LANG_RE = re.compile(r"^(x-default|[a-z]{2,3}(-[A-Za-z]{2,4})?(-[A-Za-z0-9]{2,8})*)$")


def _ok_pages(a):
    return [p for p in a.pages.values()
            if not p.error and 200 <= (p.status_code or 0) < 300]


# ----------------------------------------------------------------- robots
def _robots_rules(a) -> list:
    """
    Disallow paths that apply to every crawler.

    Only the `*` group. A rule aimed at a named bot is not a statement about
    Googlebot, and treating it as one would invent findings on sites that
    politely block a scraper we do not care about.
    """
    rules, applies = [], False
    for raw in (a.robots_txt or "").splitlines():
        line = raw.split("#")[0].strip()
        if not line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip().lower(), val.strip()
        if key == "user-agent":
            applies = val == "*"
        elif key == "disallow" and applies and val:
            rules.append(val)
    return rules


def _blocked(path: str, rules: list) -> bool:
    return any(path.startswith(r.rstrip("*")) for r in rules if r)


@check("TECH-16")
def tech16(a, c):
    """Internal JS/CSS/image resources the site blocks in its own robots.txt."""
    rules = _robots_rules(a)
    if not a.robots_txt:
        return finding("Need Access", {}, "robots.txt was not retrievable, so "
                                          "resource blocking cannot be checked.",
                       [], "Low", "", 0.0)
    if not rules:
        return finding("Pass", {"rules": 0},
                       "robots.txt blocks nothing for general crawlers, so no "
                       "resource is hidden from rendering.", [], "Low")
    host = a.host.lower()
    hits = {}
    for p in _ok_pages(a):
        for src in list(p.scripts or []) + [i.get("src") for i in (p.images or [])]:
            if not src or not isinstance(src, str):
                continue
            u = urlparse(src if "//" in src else f"{a.scheme}://{host}{src}")
            if u.netloc and u.netloc.lower().replace("www.", "") != host.replace("www.", ""):
                continue
            if _blocked(u.path, rules):
                hits.setdefault(u.path, set()).add(p.url)
    if not hits:
        return finding("Pass", {"blocked": 0},
                       f"No internal script, stylesheet or image is blocked by "
                       f"the {len(rules)} robots.txt rules.", [], "Low")
    pages = sorted({u for s in hits.values() for u in s})
    return finding("Fail", {"blocked_paths": sorted(hits)[:10],
                            "count": len(hits)},
                   f"{len(hits)} internal resource path(s) are blocked in "
                   f"robots.txt but loaded by {len(pages)} page(s) — Google "
                   f"renders those pages without them.",
                   pages[:10], "High",
                   "Allow the asset paths in robots.txt; blocking CSS or JS "
                   "makes Google evaluate a broken version of the page.")


@check("TECH-20")
def tech20(a, c):
    """Are the pages that matter actually crawlable and indexable?"""
    shallow = [p for p in _ok_pages(a) if p.depth <= 1]
    if not shallow:
        return finding("Need Access", {}, "No shallow pages were reached, so "
                                          "crawlability cannot be judged.",
                       [], "Low", "", 0.0)
    rules = _robots_rules(a)
    bad = []
    for p in shallow:
        robots = f"{p.meta_robots or ''} {p.x_robots_tag or ''}".lower()
        if "noindex" in robots:
            bad.append((p.url, "noindex"))
        elif rules and _blocked(urlparse(p.url).path, rules):
            bad.append((p.url, "blocked in robots.txt"))
    if not bad:
        return finding("Pass", {"checked": len(shallow)},
                       f"All {len(shallow)} top-level pages are crawlable and "
                       f"indexable.", [], "Low")
    return finding("Fail", {"blocked": bad[:10]},
                   f"{len(bad)} of {len(shallow)} top-level pages cannot be "
                   f"indexed ({bad[0][1]}).",
                   [u for u, _ in bad][:10], "Critical",
                   "Remove the noindex or robots.txt rule from pages you want "
                   "to rank.")


# ----------------------------------------------------------------- HTTPS
@check("SEC-13")
def sec13(a, c):
    """Pages that finally resolve over plain HTTP."""
    pages = _ok_pages(a)
    if not pages:
        return finding("Need Access", {}, "No pages were retrieved.", [], "Low",
                       "", 0.0)
    insecure = [p.url for p in pages
                if (p.final_url or p.url).lower().startswith("http://")]
    if not insecure:
        return finding("Pass", {"checked": len(pages)},
                       f"All {len(pages)} pages resolve over HTTPS.", [], "Low")
    return finding("Fail", {"insecure": len(insecure)},
                   f"{len(insecure)} page(s) still resolve over plain HTTP.",
                   insecure[:10], "Critical",
                   "Redirect every HTTP URL to its HTTPS equivalent.")


# ----------------------------------------------------------------- crawl errors
def _errors(a) -> list:
    return [p for p in a.pages.values() if p.error]


@check("TECH-04")
def tech04(a, c):
    """DNS failures, distinguished from every other kind of fetch error."""
    dns = [p for p in _errors(a)
           if re.search(r"name or service not known|nodename nor servname|"
                        r"getaddrinfo|dns", p.error or "", re.I)]
    if not dns:
        return finding("Pass", {"dns_failures": 0},
                       "No page failed to resolve.", [], "Low")
    return finding("Fail", {"count": len(dns)},
                   f"{len(dns)} URL(s) could not be resolved — the hostname "
                   f"does not answer.",
                   [p.url for p in dns][:10], "High",
                   "Correct or remove links to hostnames that no longer exist.")


@check("TECH-05")
@check("TECH-12")
def tech05(a, c):
    """URLs the crawler could not parse — malformed hrefs, stray whitespace."""
    bad = []
    for p in _ok_pages(a):
        for l in (p.links_internal or []) + (p.links_external or []):
            href = (l.get("href") or "") if isinstance(l, dict) else str(l)
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            if " " in href.strip() or href.count("://") > 1 or \
                    re.match(r"^https?:/[^/]", href):
                bad.append((p.url, href[:90]))
    if not bad:
        return finding("Pass", {"malformed": 0},
                       "Every link on the site is a well-formed URL.", [], "Low")
    return finding("Fail", {"examples": bad[:8], "count": len(bad)},
                   f"{len(bad)} link(s) are malformed and cannot be followed.",
                   sorted({u for u, _ in bad})[:10], "Medium",
                   "Fix the href values — a URL with a space or a doubled "
                   "scheme is dropped by every crawler.")


# ----------------------------------------------------------------- hreflang
def _hreflang_pairs(p):
    for h in (p.hreflang or []):
        if isinstance(h, dict):
            yield (h.get("hreflang") or h.get("lang") or "").strip(), \
                  (h.get("href") or "").strip()
        elif isinstance(h, (list, tuple)) and len(h) >= 2:
            yield str(h[0]).strip(), str(h[1]).strip()


@check("INTL-03")
def intl03(a, c):
    """hreflang values that are not valid language tags."""
    tagged = [p for p in _ok_pages(a) if p.hreflang]
    if not tagged:
        return finding("N/A", {}, "The site declares no hreflang tags, so this "
                                  "does not apply.", [], "Low", "", 1.0)
    bad = [(p.url, lang) for p in tagged for lang, _ in _hreflang_pairs(p)
           if lang and not _LANG_RE.match(lang)]
    if not bad:
        return finding("Pass", {"pages": len(tagged)},
                       f"All hreflang values across {len(tagged)} pages are "
                       f"valid language tags.", [], "Low")
    return finding("Fail", {"invalid": bad[:8]},
                   f"{len(bad)} hreflang value(s) are not valid language tags, "
                   f"e.g. \"{bad[0][1]}\".",
                   sorted({u for u, _ in bad})[:10], "Medium",
                   "Use ISO language and region codes; an unparseable value is "
                   "ignored entirely.")


@check("INTL-02")
def intl02(a, c):
    """The same language claimed twice on one page, pointing at different URLs."""
    tagged = [p for p in _ok_pages(a) if p.hreflang]
    if not tagged:
        return finding("N/A", {}, "The site declares no hreflang tags, so this "
                                  "does not apply.", [], "Low", "", 1.0)
    conflicts = []
    for p in tagged:
        seen = {}
        for lang, href in _hreflang_pairs(p):
            if not lang:
                continue
            if lang in seen and seen[lang] != href:
                conflicts.append((p.url, lang))
            seen[lang] = href
    if not conflicts:
        return finding("Pass", {"pages": len(tagged)},
                       f"No page declares the same language twice.", [], "Low")
    return finding("Fail", {"conflicts": conflicts[:8]},
                   f"{len(conflicts)} page(s) declare one language for two "
                   f"different URLs, so Google honours neither.",
                   sorted({u for u, _ in conflicts})[:10], "Medium",
                   "One URL per language per page.")


@check("INTL-05")
def intl05(a, c):
    """A page whose own lang attribute contradicts its self-referencing hreflang."""
    tagged = [p for p in _ok_pages(a) if p.hreflang and p.lang]
    if not tagged:
        return finding("N/A", {}, "No page carries both a lang attribute and "
                                  "hreflang tags, so this does not apply.",
                       [], "Low", "", 1.0)
    bad = []
    for p in tagged:
        own = (p.lang or "").split("-")[0].lower()
        self_tags = [lang.split("-")[0].lower()
                     for lang, href in _hreflang_pairs(p)
                     if href.rstrip("/") == (p.final_url or p.url).rstrip("/")]
        if self_tags and own not in self_tags:
            bad.append((p.url, own, self_tags[0]))
    if not bad:
        return finding("Pass", {"pages": len(tagged)},
                       f"Declared page language matches hreflang on all "
                       f"{len(tagged)} pages.", [], "Low")
    return finding("Fail", {"mismatched": bad[:8]},
                   f"{len(bad)} page(s) declare lang=\"{bad[0][1]}\" but "
                   f"hreflang \"{bad[0][2]}\" for themselves.",
                   [u for u, _, _ in bad][:10], "Medium",
                   "Make the lang attribute and the self-referencing hreflang "
                   "agree.")


# ----------------------------------------------------------------- markup
@check("HTML-06")
def html06(a, c):
    """
    The structural declarations every page needs.

    Not a full validator — a real one needs the raw markup, which the crawler
    does not keep. This checks the three things whose absence actually changes
    how a browser or a crawler treats the document.
    """
    pages = _ok_pages(a)
    if not pages:
        return finding("Need Access", {}, "No pages were retrieved.", [], "Low",
                       "", 0.0)
    missing = {"doctype": [], "charset": [], "lang": []}
    for p in pages:
        if not (p.doctype or "").strip():
            missing["doctype"].append(p.url)
        if not (p.charset or "").strip():
            missing["charset"].append(p.url)
        if not (p.lang or "").strip():
            missing["lang"].append(p.url)
    worst = max(missing, key=lambda k: len(missing[k]))
    if not missing[worst]:
        return finding("Pass", {"checked": len(pages)},
                       f"All {len(pages)} pages declare a doctype, a character "
                       f"set and a language.", [], "Low")
    parts = [f"{len(v)} missing {k}" for k, v in missing.items() if v]
    return finding("Fail", {k: len(v) for k, v in missing.items()},
                   "; ".join(parts) + ".",
                   missing[worst][:10], "Low",
                   "Add the missing declarations to the page template.")


# =====================================================================
# SIX MORE OFF THE ANALYST'S LIST
#
# Every one of these was on a person's to-do list, and every one is answered by
# something the crawler already loaded and simply was not writing down. The
# crawler now keeps stylesheet hrefs, rel=next/prev/amphtml and meta refresh —
# three lines of parsing — and these six read them.
#
# The bar for moving a row off that list: the answer must be as good as the one
# a person would give, not merely present. Where it is not — subdomain TLS, for
# instance, which needs live handshakes against hosts the crawl never visits —
# the row stays where it is.
# =====================================================================

_ASSET_EXT = (".css", ".js", ".json", ".xml", ".txt", ".pdf", ".doc", ".docx",
              ".xls", ".xlsx", ".zip", ".gz", ".mp4", ".mp3", ".svg", ".webp",
              ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf")


@check("URL-05")
def url05(a, c):
    """Meta refresh redirects. A substring search over HTML we already hold."""
    pages = OK(a)
    if not pages:
        return finding("Need Access", {}, "No pages were retrieved.", [], "Low",
                       "", 0.0)
    hit = [(p.url, p.meta_refresh) for p in pages if (p.meta_refresh or "").strip()]
    return finding("Fail" if hit else "Pass",
                   {"pages": len(hit), "checked": len(pages),
                    "examples": [u for u, _ in hit[:10]]},
                   f"{len(hit)} of {len(pages)} pages use a meta refresh "
                   f"redirect." if hit else
                   f"No meta refresh redirects on any of the {len(pages)} pages "
                   f"reviewed.",
                   [u for u, _ in hit[:10]], "Medium" if hit else "Low",
                   "Replace meta refresh with a 301 redirect — Google treats it "
                   "as a weaker signal and it passes less authority."
                   if hit else "")


@check("CANON-03")
def canon03(a, c):
    """AMP pages must declare a canonical back to the HTML version."""
    pages = OK(a)
    amp_refs = [p for p in pages if (p.rel_links or {}).get("amphtml")]
    # A site with no AMP at all is not failing an AMP check.
    if not amp_refs:
        return finding("N/A", {"amp_pages": 0},
                       "This site publishes no AMP pages, so AMP canonicals do "
                       "not apply.", [], "Low", confidence=1.0)
    amp_urls = {u for p in amp_refs for u in p.rel_links["amphtml"]}
    seen = [p for p in pages if p.url in amp_urls]
    bad = [p.url for p in seen if not (p.canonical or "").strip()]
    return finding("Fail" if bad else "Pass",
                   {"amp_pages": len(amp_urls), "reviewed": len(seen),
                    "missing_canonical": len(bad)},
                   f"{len(bad)} of the {len(seen)} AMP pages reviewed carry no "
                   f"canonical tag." if bad else
                   f"{len(amp_urls)} AMP page(s) referenced"
                   + (f"; all {len(seen)} of those reviewed declare a canonical."
                      if seen else ", none of which were reachable to review."),
                   bad[:10], "High" if bad else "Low",
                   "Point each AMP page's canonical at its HTML equivalent."
                   if bad else "")


@check("CANON-06")
def canon06(a, c):
    """
    Paginated pages must self-canonicalize.

    The classic error is page 2 of a listing canonicalizing to page 1, which
    tells Google to drop every product or article that only appears on page 2.
    """
    pages = OK(a)
    paged = [p for p in pages
             if (p.rel_links or {}).get("next") or (p.rel_links or {}).get("prev")
             or re.search(r"[?&/](page|p)[=/]\d+", p.url, re.I)]
    if not paged:
        return finding("N/A", {"paginated_pages": 0},
                       "No paginated series were found, so pagination "
                       "canonicals do not apply.", [], "Low", confidence=0.9)
    bad = []
    for p in paged:
        canon = (p.canonical or "").strip().rstrip("/")
        if canon and canon != p.url.rstrip("/") and canon != (p.final_url or "").rstrip("/"):
            bad.append(p.url)
    return finding("Fail" if bad else "Pass",
                   {"paginated_pages": len(paged), "pointing_elsewhere": len(bad),
                    "examples": bad[:10]},
                   f"{len(bad)} of {len(paged)} paginated pages canonicalize to "
                   f"a different URL, which asks Google to drop everything that "
                   f"only appears on those pages." if bad else
                   f"All {len(paged)} paginated pages canonicalize to "
                   f"themselves.",
                   bad[:10], "High" if bad else "Low",
                   "Each page in a series should canonicalize to itself."
                   if bad else "")


@check("HTML-05")
def html05(a, c):
    """
    Assets linked as if they were pages.

    A navigation or body link straight to a .pdf, .css or .jpg sends crawlers
    and visitors to a file with no way back into the site.
    """
    pages = OK(a)
    if not pages:
        return finding("Need Access", {}, "No pages were retrieved.", [], "Low",
                       "", 0.0)
    hits, where = set(), []
    for p in pages:
        for link in (p.links_internal or []):
            href = (link.get("href") or "").split("?")[0].split("#")[0].lower()
            if href.endswith(_ASSET_EXT) and not href.endswith((".html", ".htm")):
                hits.add(href)
                if len(where) < 10:
                    where.append(p.url)
    # A PDF linked from a resources page is normal and useful. Style and script
    # files linked as navigation are not.
    code = {h for h in hits if h.endswith((".css", ".js", ".json", ".xml"))}
    return finding("Fail" if code else "Pass",
                   {"asset_links": len(hits), "code_links": len(code),
                    "examples": sorted(code)[:10]},
                   f"{len(code)} stylesheet or script file(s) are linked as if "
                   f"they were pages." if code else
                   f"No stylesheets or scripts are linked as pages"
                   + (f"; {len(hits)} document link(s) such as PDFs are, which "
                      f"is normal." if hits else "") + ".",
                   where, "Medium" if code else "Low",
                   "Link to a page that describes the file, not to the file."
                   if code else "")


@check("INTL-08")
def intl08(a, c):
    """
    Country targeting.

    Read from hreflang: a tag like `en-us` targets a country, a bare `en`
    targets a language everywhere. Both are valid; which one is right depends on
    whether the business sells across borders, and the report says so rather
    than guessing.
    """
    pages = OK(a)
    tags = [str(h.get("lang") or "").strip().lower()
            for p in pages for h in (p.hreflang or []) if h.get("lang")]
    tags = [t for t in tags if t and t != "x-default"]
    if not tags:
        host = (a.start_url or "").split("//")[-1].split("/")[0].lower()
        cc = host.rsplit(".", 1)[-1]
        # A country-code domain IS country targeting, and a very strong one.
        known_cc = {"uk", "ca", "au", "de", "fr", "es", "it", "nl", "ie", "nz",
                    "in", "jp", "br", "mx", "za"}
        if cc in known_cc:
            return finding("Pass", {"signal": "ccTLD", "tld": cc},
                           f"The .{cc} domain itself targets that country — the "
                           f"strongest signal available, and no hreflang is "
                           f"needed for a single-country site.", [], "Low")
        return finding("N/A", {"hreflang_tags": 0},
                       "No country or language targeting is declared, which is "
                       "correct for a business serving one country from a .com.",
                       [], "Low", confidence=0.8)
    countries = sorted({t.split("-")[1] for t in tags if "-" in t})
    langs = sorted({t.split("-")[0] for t in tags})
    return finding("Pass", {"countries": countries, "languages": langs,
                            "tags": sorted(set(tags))[:20]},
                   (f"Country targeting is declared for "
                    f"{', '.join(c.upper() for c in countries)} across "
                    f"{len(langs)} language(s)."
                    if countries else
                    f"Language targeting is declared ({', '.join(langs)}) with "
                    f"no country attached, so the same pages serve every "
                    f"country speaking those languages."),
                   [], "Low")


def _asset_status(a, urls):
    """Status codes the crawl already recorded for these asset URLs."""
    checked = getattr(a, "external_checked", {}) or {}
    broken = {b.get("to"): b.get("status")
              for b in (getattr(a, "broken_links", []) or [])}
    out = {}
    for u in urls:
        if u in broken:
            out[u] = broken[u]
        elif u in checked:
            out[u] = checked[u]
    return out


@check("TECH-17")
def tech17(a, c):
    """
    Stylesheets and scripts blocked by robots.txt.

    Google renders the page to judge it. A blocked stylesheet means Google sees
    an unstyled page and may conclude it is not mobile friendly.
    """
    pages = OK(a)
    if not pages:
        return finding("Need Access", {}, "No pages were retrieved.", [], "Low",
                       "", 0.0)
    rules = _robots_rules(a)
    if rules is None:
        return finding("N/A", {}, "No robots.txt was retrieved, so nothing is "
                                  "blocked by one.", [], "Low", confidence=0.8)
    assets = {u for p in pages for u in (list(p.stylesheets or [])
                                         + [s for s in (p.scripts or [])
                                            if isinstance(s, str) and s.startswith("http")])}
    if not assets:
        return finding("N/A", {}, "No external stylesheets or scripts were "
                                  "found to check.", [], "Low", confidence=0.7)
    host = (a.start_url or "").split("//")[-1].split("/")[0].lower()
    same = [u for u in assets if host in u.lower()]
    blocked = [u for u in same if _blocked(u, rules)]
    return finding("Fail" if blocked else "Pass",
                   {"assets": len(same), "blocked": len(blocked),
                    "examples": blocked[:10]},
                   f"{len(blocked)} of {len(same)} stylesheets and scripts on "
                   f"this domain are blocked by robots.txt, so Google renders "
                   f"the page without them." if blocked else
                   f"None of the {len(same)} stylesheets and scripts on this "
                   f"domain are blocked by robots.txt.",
                   blocked[:10], "High" if blocked else "Low",
                   "Unblock CSS and JavaScript in robots.txt — Google needs "
                   "them to render the page as a visitor sees it."
                   if blocked else "")
