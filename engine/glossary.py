"""
Plain-English glossary.

The audit is read by business owners, not by SEOs. "Canonicalization" is a word
that makes a reader either stop and google it or, more often, skip the finding
entirely — which means the finding may as well not be there. Defining the term
where it is used is the difference between a report that is understood and one
that is merely delivered.

Two icon sets on purpose:

  * `emoji` — used in the HTML report, where the browser has a color emoji font.
  * `glyph` — used in the PDF. reportlab embeds the font it is given, and no
    color emoji font can be embedded into a PDF this way; a codepoint the font
    lacks renders as a black box, which looks far worse than no icon at all.
    Every glyph here is verified against the font at render time, and anything
    missing is dropped rather than drawn. See tests/test_glossary.py.

Definitions are deliberately short and consequence-first: what it is, then why
a business owner should care, in one sentence each.
"""
from __future__ import annotations
import re

# term key -> (display name, emoji, pdf glyph, definition, match patterns)
TERMS = {
    "canonical": (
        "Canonical tag", "🚩", "⚑",
        "A line of code that tells Google which version of a page is the "
        "official one. Without it, several URLs showing the same content "
        "compete against each other instead of adding up.",
        (r"canonical", r"canonicaliz", r"canonicaliz")),
    "signal": (
        "Ranking signal", "\U0001F4E1", "\u25CE",
        "Anything Google measures about a page and feeds into where it ranks — "
        "the words on it, how fast it loads, whether it is secure, who links to "
        "it. No single one decides a position; they accumulate.",
        (r"ranking signal", r"\bsignals?\b")),
    "schema": (
        "Structured data (schema)", "🧩", "◆",
        "Hidden labels in your page code that tell search engines what things "
        "are — a product, a price, a review, a store. It is what produces the "
        "star ratings and prices you see in results.",
        (r"\bschema\b", r"structured data", r"json-?ld", r"rich result")),
    "nofollow": (
        "Nofollow", "\U0001F6AB", "\u2298",
        "A tag on a link telling search engines not to pass ranking credit "
        "through it. Used on paid, sponsored and user-posted links. A followed "
        "link passes credit; a nofollowed one still sends visitors but not "
        "authority.",
        (r"nofollow", r"rel=.?nofollow")),
    "srcset": (
        "Responsive images (srcset)", "\U0001F5BC", "\u25A4",
        "A list of the same image at several sizes, so a phone downloads a "
        "small one and a desktop downloads a large one. Without it every "
        "visitor downloads the full-size file, however small their screen.",
        (r"\bsrcset\b", r"responsive image")),
    "cwv": (
        "Core Web Vitals", "⚡", "⚡",
        "Google's three speed and stability measurements: how fast the main "
        "content appears (Largest Contentful Paint), how quickly the page "
        "responds, and whether things jump around while loading.",
        (r"core web vital", r"\blcp\b", r"\bcls\b", r"\binp\b",
         r"largest contentful", r"cumulative layout")),
    "eeat": (
        "E-E-A-T", "⭐", "★",
        "Experience, Expertise, Authoritativeness and Trust — the signals "
        "Google uses to judge whether a site is a credible source. Author "
        "names, credentials and a real About page are the visible parts.",
        (r"e-e-a-t", r"\beeat\b")),
    "robots": (
        "robots.txt", "⚙️", "⚙",
        "A file at the root of your site listing which automated visitors may "
        "read which pages. Getting it wrong can hide the whole site from "
        "search engines.",
        (r"robots\.txt",)),
    "llms": (
        "llms.txt", "🧪", "⚗",
        "A newer, still-informal file that tells AI assistants what your site "
        "covers and which pages to trust. Cheap to add, and one of the few "
        "direct levers on how assistants describe you.",
        (r"llms\.txt",)),
    "geo": (
        "AI Search (GEO)", "🤖", "◉",
        "Being found and quoted inside AI answers — ChatGPT, Perplexity, "
        "Google's AI Overviews — rather than in the classic list of ten blue "
        "links. Different rules, same goal.",
        (r"\bgeo\b", r"generative engine", r"ai overview", r"ai assistant",
         r"ai crawler")),
    "orphan": (
        "Orphan page", "🏚️", "⌂",
        "A page nothing else on your site links to. Search engines find pages "
        "by following links, so an orphan is close to invisible however good "
        "it is.",
        (r"orphan",)),
    "hreflang": (
        "hreflang", "🌐", "✈",
        "Code that says which language or country a page is meant for, so the "
        "Spanish page is shown in Spain rather than competing with the "
        "English one.",
        (r"hreflang",)),
    "redirect301": (
        "301 redirect", "➡️", "➔",
        "A permanent forwarding instruction from an old URL to a new one. It "
        "carries the old page's ranking value across; a missing one throws "
        "that value away.",
        (r"\b301\b", r"redirect chain", r"permanent redirect")),
    "alt": (
        "Alt text", "✏️", "✎",
        "A short written description of an image, read by screen readers and "
        "by search engines, which cannot see pictures.",
        (r"alt text", r"alt attribute", r"missing alt")),
    "sitemap": (
        "XML sitemap", "🗺️", "☰",
        "A machine-readable list of every page you want indexed. It does not "
        "guarantee indexing, but it is how search engines discover pages that "
        "are buried deep in the site.",
        (r"sitemap",)),
    "indexing": (
        "Indexing", "🔎", "☑",
        "Whether a page has actually been stored in Google's database. A page "
        "that is crawled but not indexed cannot appear in results at all.",
        (r"\bnoindex\b", r"index coverage", r"\bindexab", r"\bindexed\b")),
    "lazyload": (
        "Lazy loading", "🐢", "◷",
        "Telling the browser to hold off downloading images until the visitor "
        "scrolls near them. The page above the fold appears sooner, which is "
        "what both Google and your visitors actually measure.",
        (r"lazy.?load", r'loading="lazy"', r"loading=lazy")),
    "compression": (
        "GZIP / Brotli compression", "📦", "⬟",
        "Server-side squashing of page code before it is sent, typically "
        "cutting transfer size by two thirds. It is a switch, not a rebuild.",
        (r"gzip", r"brotli", r"compression")),
}

# Fallback for the PDF when the glyph is unavailable in the embedded font.
FALLBACK_GLYPH = "●"          # ● — present in essentially every font


def _compiled():
    out = {}
    for key, (_n, _e, _g, _d, pats) in TERMS.items():
        out[key] = [re.compile(p, re.I) for p in pats]
    return out


_PATTERNS = _compiled()


def terms_used(*texts, limit: int = 6) -> list:
    """
    Which glossary terms actually appear in this report?

    Only terms the reader will meet are defined. A full A–Z glossary is
    reference material; four definitions for the four bits of jargon on the
    page in front of them is help.

    Returned in ORDER OF FIRST APPEARANCE and capped, so the block stays a
    sidebar rather than becoming a chapter.

    Appearance order, not TERMS order. The summary named canonicalization in its
    first sentence and E-E-A-T in its second, and the definitions came back in
    the opposite order — so the reader met "canonical tag" explained underneath
    a paragraph about E-E-A-T, two paragraphs after the word they needed it for.
    A definition placed after its term has already gone by is an index entry
    pretending to be help.
    """
    blob = " ".join(str(t or "") for t in texts).lower()
    hits = []
    for key, pats in _PATTERNS.items():
        at = min((m.start() for p in pats
                  for m in [p.search(blob)] if m), default=None)
        if at is not None:
            hits.append((at, key))
    return [k for _, k in sorted(hits)][:limit]


def entry(key: str, medium: str = "html") -> dict:
    name, emoji, glyph, definition, _ = TERMS[key]
    return {"key": key, "name": name, "definition": definition,
            "icon": emoji if medium == "html" else glyph}


def entries(keys, medium: str = "html") -> list:
    return [entry(k, medium) for k in keys if k in TERMS]
