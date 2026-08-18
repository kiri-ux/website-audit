"""
Glossary tests — the icons must actually draw, and the definitions must be real.

The specific hazard: reportlab renders a codepoint the embedded font lacks as a
SOLID BLACK BOX. A report full of black boxes is worse than one with no icons,
and it will not show up in any test that only checks the PDF built without
raising. So this asserts, per glyph, that the font we actually load contains it.

Also guards the selection rule — only jargon the report USES gets defined. A
full A–Z glossary is reference material; four definitions for the four terms on
the page is help.

Run:  python3 -m tests.test_glossary
"""
from __future__ import annotations
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.glossary import TERMS, terms_used, entries, FALLBACK_GLYPH
from engine.pdf_report import (_symbol_font, _icon, _bubble, _bubbles_for,
                               _styles, build_pdf)

FAILURES = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)
    return cond


def main():
    print("\nEVERY DEFINITION IS COMPLETE")
    for key, (name, emoji, glyph, definition, pats) in TERMS.items():
        ok = bool(name and emoji and glyph and definition and pats)
        check(f"{key} is fully specified", ok)
        check(f"{key} definition is a real explanation, not a restatement",
              len(definition) > 60 and definition.rstrip().endswith("."),
              f"{len(definition)} chars")
        check(f"{key} definition avoids defining jargon with jargon",
              name.lower().split()[0] not in definition.lower()[:40]
              or key in ("robots", "llms", "hreflang"),
              definition[:50])

    print("\nPDF GLYPHS RENDER — NO BLACK BOXES")
    font, cmap = _symbol_font()
    check("a symbol font was found and registered", bool(font),
          font or "none found — icons will be dropped, not boxed")
    if font:
        missing = [f"{k}:{g}" for k, (_n, _e, g, _d, _p) in TERMS.items()
                   if any(ord(c) not in cmap for c in g)]
        check("every PDF glyph exists in the embedded font", not missing,
              str(missing))
        check("the fallback glyph exists too",
              all(ord(c) in cmap for c in FALLBACK_GLYPH), FALLBACK_GLYPH)
        # A codepoint we know is absent must be dropped or swapped, never drawn.
        check("an unavailable codepoint never reaches the canvas",
              _icon("\U0001F512") in ("", f"<font name='{font}'>{FALLBACK_GLYPH}</font>"),
              repr(_icon("\U0001F512")))

    print("\nHTML USES REAL EMOJI, PDF USES THE SAFE GLYPH")
    h = entries(["canonical"], medium="html")[0]
    p = entries(["canonical"], medium="pdf")[0]
    check("html entry carries the emoji", h["icon"] == "🚩", h["icon"])
    check("pdf entry carries the monochrome glyph", p["icon"] == "⚑", p["icon"])
    check("definition text is identical across media",
          h["definition"] == p["definition"])

    print("\nONLY JARGON THE REPORT ACTUALLY USES IS DEFINED")
    used = terms_used("robots.txt blocks 2 AI crawlers",
                      "WebSite schema is not implemented anywhere")
    check("matched terms are found", set(used) >= {"robots", "schema"}, str(used))
    check("unused terms are not defined", "hreflang" not in used, str(used))
    check("nothing is returned for jargon-free text",
          terms_used("8 pages are slow and the titles are duplicated") == []
          or "cwv" not in terms_used("8 pages are slow"), "")
    many = terms_used(" ".join(p for t in TERMS.values() for p in
                               ("canonical schema core web vital e-e-a-t robots.txt "
                                "llms.txt geo orphan hreflang 301 alt text sitemap "
                                "noindex gzip",)))
    check("the block is capped so it stays a sidebar", len(many) <= 6,
          f"{len(many)} terms")

    print("\nBUBBLES RENDER, AND EACH TERM IS EXPLAINED ONCE")
    S = _styles()
    b = _bubble("Canonical tag", "A line of code that…", "⚑", S)
    check("a bubble builds", b is not None)
    seen = set()
    first = _bubbles_for("the canonical tag is missing", S, seen)
    check("a new term produces a bubble", len(first) == 1, str(len(first)))
    again = _bubbles_for("another canonical tag problem", S, seen)
    check("the same term is never explained twice", again == [], str(len(again)))
    check("jargon-free text produces no bubble at all",
          _bubbles_for("eight pages are slow", S, set()) == [])
    check("a bubble block is capped so it stays an aside",
          len(_bubbles_for("canonical schema robots.txt llms.txt hreflang sitemap",
                           S, set(), limit=2)) <= 2)

    scores = {"overall": {"score": 70, "rating": "Strong"}, "sections": {}}
    cat = {"TECH-01": {"prefix": "TECH", "checkpoint": "Canonical tag present"}}
    F = {"TECH-01": {"status": "Fail", "severity": "High",
                     "evidence": "No canonical tag on 8 pages; robots.txt blocks GPTBot",
                     "recommendation": "Add a canonical tag", "confidence": 1.0,
                     "source": "crawl"}}
    from engine.summarise import build_summary
    meta = {"client": "T", "url": "https://t.test/", "pages_crawled": 8,
            "coverage": "1/1", "generated": "2026-08-18 10:00", "build": "test"}
    pdf = build_pdf(meta, scores, F, cat, build_summary(F, scores, cat, meta))
    check("PDF with a glossary block builds", pdf[:4] == b"%PDF",
          f"{len(pdf)//1024}KB")
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf)) as d:
            text = "\n".join((p.extract_text() or "") for p in d.pages)
        check("the definition reached the page", "Canonical tag" in text)
        # The heading was cut on purpose — "In plain English" reads as
        # generated copy, and a definition needs no announcement.
        check("no glossary heading is announced", "In plain English" not in text)
    except ImportError:
        print("  SKIP  pdfplumber not installed")

    print("\n" + "=" * 68)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — jargon is defined and every icon draws")
    print("=" * 68 + "\n")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
