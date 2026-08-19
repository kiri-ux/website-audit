"""
PDF report renderer — the client-facing deliverable.

Another renderer over the findings store, alongside the HTML one. Nothing
upstream knows this exists, which is the point: the store is the product and
formats are interchangeable.

Design notes:
  * Clean and unbranded, with a logo slot partners swap per client.
  * Structure mirrors the white-label audit template so partners get the shape
    they already expect: exec summary, area snapshot, priority issues, then
    per-section detail.
  * Severity uses the SAME validated ordinal blue ramp as the HTML report and
    dashboard — severity is an ordered scale, not a set of categories, so a
    single-hue ramp is the correct encoding and there is no CVD gate to clear.
  * Status colors are the reserved status palette and ALWAYS ship with a text
    label, never as the sole carrier of meaning.
"""
from __future__ import annotations
import html as _h
import re
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, Frame, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle, KeepTogether)

from .charts import (ScoreGauge, SectionBars, SegmentBar, MiniMeter,
                     DefBadge, severity_segments, coverage_segments)

# ---- palette (matches the HTML report) -------------------------------------
INK        = colors.HexColor("#0b0b0b")
INK2       = colors.HexColor("#52514e")
MUTED      = colors.HexColor("#898781")
LINE       = colors.HexColor("#e6e5e1")
SURFACE    = colors.HexColor("#fcfcfb")
TRACK      = colors.HexColor("#eceae6")
SEQ        = colors.HexColor("#2a78d6")
# validated ordinal ramp, light mode (validate_palette.js --ordinal: all pass)
ORD = {"Critical": colors.HexColor("#104281"), "High": colors.HexColor("#256abf"),
       "Medium": colors.HexColor("#3987e5"), "Low": colors.HexColor("#86b6ef"),
       "Opportunity": TRACK}
STATUS = {"Pass": colors.HexColor("#0ca30c"), "Warning": colors.HexColor("#fab219"),
          "Fail": colors.HexColor("#d03b3b"),
          "Not Implemented": colors.HexColor("#ec835a"),
          "Need Access": MUTED, "N/A": MUTED}

SECTION_NAMES = {
    "ANA": "Analytics & Tracking", "GSC": "Search Console", "GA4": "Google Analytics 4",
    "TECH": "Technical SEO", "URL": "URL Structure & Site Architecture",
    "SEC": "HTTPS & Security", "CANON": "Canonicalization",
    "PERF": "Website Performance & Core Web Vitals", "ONP": "On-Page SEO",
    "MOB": "Mobile SEO", "SCHEMA": "Structured Data (Schema)",
    "INTL": "International SEO", "HTML": "HTML & Code Quality",
    "EEAT": "E-E-A-T Audit", "GEO": "AI Search", "OFF": "Off-Page SEO & Authority",
}
# Chart labels. The full names are correct in prose and in the tables, but a
# ranked bar chart has a fixed label gutter — shortening beats auto-shrinking,
# which produces a chart with six different type sizes in it.
SHORT_NAMES = {
    "ANA": "Analytics & Tracking", "GSC": "Search Console", "GA4": "Analytics 4",
    "TECH": "Technical SEO", "URL": "URL & Architecture", "SEC": "HTTPS & Security",
    "CANON": "Canonicalization", "PERF": "Performance & CWV", "ONP": "On-Page SEO",
    "MOB": "Mobile SEO", "SCHEMA": "Structured Data", "INTL": "International SEO",
    "HTML": "HTML & Code Quality", "EEAT": "E-E-A-T", "GEO": "AI Search",
    "OFF": "Off-Page & Authority",
}
ORDER = list(SECTION_NAMES)
STATUS_ORDER = ["Fail", "Not Implemented", "Warning", "Pass", "Need Access", "N/A"]


def _us_date(stamp) -> str:
    """2026-08-18 14:00 -> 08/18/2026. US clients, US format, no time of day."""
    raw = str(stamp or "").split(" ")[0]
    try:
        d = datetime.strptime(raw, "%Y-%m-%d")
        return d.strftime("%m/%d/%Y")
    except Exception:
        return _h.escape(raw)


def _p(text):
    return _h.escape(str(text if text is not None else ""))


def _styles():
    ss = getSampleStyleSheet()
    def mk(name, **kw):
        base = dict(fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK)
        base.update(kw)
        return ParagraphStyle(name, parent=ss["Normal"], **base)
    return {
        "h1": mk("h1", fontName="Helvetica-Bold", fontSize=21, leading=25, spaceAfter=4),
        "h2": mk("h2", fontName="Helvetica-Bold", fontSize=13, leading=17,
                 spaceBefore=16, spaceAfter=7),
        "h3": mk("h3", fontName="Helvetica-Bold", fontSize=10.5, leading=14,
                 spaceBefore=10, spaceAfter=4),
        "body": mk("body", spaceAfter=6),
        "small": mk("small", fontSize=8.5, leading=11.5, textColor=INK2),
        "muted": mk("muted", fontSize=8, leading=11, textColor=MUTED),
        "cell": mk("cell", fontSize=8.5, leading=11),
        "cellsm": mk("cellsm", fontSize=8, leading=10.5, textColor=INK2),
        "hero": mk("hero", fontName="Helvetica-Bold", fontSize=44, leading=48),
        "bullet": mk("bullet", leftIndent=11, bulletIndent=2, spaceAfter=4),
    }


class _Doc(BaseDocTemplate):
    """Adds a running footer with page numbers and the build id."""

    def __init__(self, buf, meta, **kw):
        super().__init__(buf, pagesize=LETTER,
                         leftMargin=0.72 * inch, rightMargin=0.72 * inch,
                         topMargin=0.62 * inch, bottomMargin=0.72 * inch, **kw)
        self.meta = meta
        frame = Frame(self.leftMargin, self.bottomMargin,
                      self.width, self.height, id="main")
        self.addPageTemplates([PageTemplate(id="all", frames=[frame],
                                            onPage=self._chrome)])

    def _chrome(self, canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.setStrokeColor(LINE)
        y = self.bottomMargin - 16
        canvas.line(self.leftMargin, y + 11, self.leftMargin + self.width, y + 11)
        left = f"{self.meta.get('client','')} — SEO & AI Search Audit"
        canvas.drawString(self.leftMargin, y, left[:90])
        canvas.drawRightString(self.leftMargin + self.width, y, f"Page {doc.page}")
        # No build id here. It is operational information for us, and a version
        # string in the footer of a client deliverable reads as a draft.
        canvas.restoreState()



# ---------------------------------------------------------------------------
# PILLS.
#
# The first version painted the severity cell with the ordinal ramp and left
# the label in whatever color happened to be set. "Critical" in dark text on
# #104281 was effectively unreadable at 8pt. Contrast is decided here, per
# level, rather than left to a rule of thumb: the two dark steps take white
# text, the two light steps take dark text, and the ordinal reading survives
# because the BACKGROUND still runs dark to light.
# ---------------------------------------------------------------------------
SEV_PILL = {
    "Critical":    (colors.HexColor("#104281"), colors.white),
    "High":        (colors.HexColor("#256abf"), colors.white),
    "Medium":      (colors.HexColor("#dbe8fa"), colors.HexColor("#17457f")),
    "Low":         (colors.HexColor("#edf3fd"), colors.HexColor("#2a5d9e")),
    "Opportunity": (colors.HexColor("#f1f0ec"), colors.HexColor("#52514e")),
}
ORD_PHASE = [colors.HexColor("#104281"), colors.HexColor("#256abf"),
             colors.HexColor("#3987e5")]

STATUS_PILL = {
    "Pass":            (colors.HexColor("#e3f5e3"), colors.HexColor("#0b6b0b")),
    "Fail":            (colors.HexColor("#fbe4e4"), colors.HexColor("#a32020")),
    "Warning":         (colors.HexColor("#fdf1d9"), colors.HexColor("#8a5d05")),
    "Not Implemented": (colors.HexColor("#fdeadf"), colors.HexColor("#9c4a1e")),
    "Need Access":     (colors.HexColor("#f1f0ec"), colors.HexColor("#52514e")),
    "N/A":             (colors.HexColor("#f6f5f2"), colors.HexColor("#898781")),
}


def _pill(label, palette, S, width=0.82 * inch):
    """A rounded, filled label. Color plus text, never color alone."""
    bg, fg = palette.get(label, (TRACK, INK2))
    st = ParagraphStyle("pill", parent=S["cellsm"], textColor=fg,
                        fontName="Helvetica-Bold", fontSize=7.5, leading=9.5,
                        alignment=1)
    t = Table([[Paragraph(_p(label), st)]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _kv_table(rows, w1=1.7, w2=4.9):
    t = Table(rows, colWidths=[w1 * inch, w2 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _meter(score, width=1.15 * inch, height=6):
    """A tiny score bar. Sequential single hue — magnitude, not identity."""
    filled = 0 if score is None else max(0.0, min(1.0, score / 100.0))
    t = Table([[""]], colWidths=[width], rowHeights=[height])
    style = [("BACKGROUND", (0, 0), (0, 0), TRACK),
             ("LINEBELOW", (0, 0), (0, 0), 0, colors.white)]
    t.setStyle(TableStyle(style))
    if filled <= 0:
        return t
    inner = Table([[""]], colWidths=[width * filled], rowHeights=[height])
    inner.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), SEQ)]))
    wrap = Table([[inner, ""]], colWidths=[width * filled, width * (1 - filled)],
                 rowHeights=[height])
    wrap.setStyle(TableStyle([
        ("BACKGROUND", (1, 0), (1, 0), TRACK),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return wrap


# ---------------------------------------------------------------------------
# SYMBOL FONT.
#
# The built-in PDF fonts (Helvetica et al.) have no pictographs at all, and a
# missing codepoint in reportlab renders as a solid black box — worse than
# having no icon. Color emoji fonts cannot be embedded into a PDF this way
# either. So: find a DejaVu build, which every mainstream Linux image carries
# and which covers the U+2600 symbol block, verify each codepoint against the
# font we actually loaded, and drop any icon that would not render.
# ---------------------------------------------------------------------------
_SYMBOL_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/local/share/fonts/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/DejaVuSans.ttf",
]
_SYM = {"name": None, "cmap": set(), "tried": False}


def _symbol_font():
    """(font_name or None, supported_codepoints)."""
    if _SYM["tried"]:
        return _SYM["name"], _SYM["cmap"]
    _SYM["tried"] = True
    import os as _os
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for path in [_os.getenv("SYMBOL_FONT_PATH") or ""] + _SYMBOL_PATHS:
        if not path or not _os.path.exists(path):
            continue
        try:
            f = TTFont("ViciSymbols", path)
            pdfmetrics.registerFont(f)
            _SYM["name"] = "ViciSymbols"
            _SYM["cmap"] = set(f.face.charToGlyph.keys())
            break
        except Exception:
            continue
    return _SYM["name"], _SYM["cmap"]


def _icon(ch: str) -> str:
    """The glyph wrapped in its font, or "" when it would render as a box."""
    name, cmap = _symbol_font()
    if not name or not ch:
        return ""
    if any(ord(c) not in cmap for c in ch):
        from .glossary import FALLBACK_GLYPH
        ch = FALLBACK_GLYPH
        if any(ord(c) not in cmap for c in ch):
            return ""
    return f"<font name='{name}'>{ch}</font>"


BUBBLE_BG = colors.HexColor("#eef4fd")     # soft tint of the sequential blue
BUBBLE_EDGE = colors.HexColor("#cfe0f8")


def _bubble(term, definition, icon="", S=None, width=6.55 * inch, indent=0.0):
    """
    A rounded, tinted definition bubble with a definition badge on the left.

    Placed beside the finding that used the word, never collected into a
    glossary — that is Kiri's own habit in the AdLib guides ("On AdLib,
    **audiences** are created first and then added to a campaign"), and it is
    the difference between a reader who understands the finding and one who
    skips it.

    The leading badge is a DRAWN circle, not a font glyph. The term-specific
    symbol is a bonus that appears only where the symbol font is available; the
    badge always renders, so a bubble is never left with no marker at all —
    which is exactly what happened in production when the container turned out
    to have no DejaVu installed.
    """
    ic = _icon(icon) if icon else ""
    body = ((f"{ic}  " if ic else "")
            + f"<b>{_p(term)}</b> — {_p(definition)}")
    inner = Table([[DefBadge(11.5), Paragraph(body, S["cellsm"])]],
                  colWidths=[0.24 * inch, width - indent - 0.24 * inch - 22])
    inner.setStyle(TableStyle([
        ("VALIGN", (0, 0), (0, 0), "TOP"),
        ("VALIGN", (1, 0), (1, 0), "MIDDLE"),
        ("TOPPADDING", (0, 0), (0, 0), 1),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 7),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (1, 0), (1, 0), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    t = Table([[inner]], colWidths=[width - indent])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BUBBLE_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, BUBBLE_EDGE),
        ("ROUNDEDCORNERS", [9, 9, 9, 9]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    if not indent:
        return t
    wrap = Table([["", t]], colWidths=[indent, width - indent])
    wrap.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return wrap


def _bubbles_for(text, S, seen, width=6.55 * inch, indent=0.0, limit=2):
    """
    Definition bubbles for jargon in `text` that has not been defined yet.

    `seen` is mutated. A term is explained ONCE, at its first appearance — the
    same word defined on four pages is the tell of a document assembled rather
    than written.
    """
    from .glossary import terms_used, entry
    out = []
    for key in terms_used(text, limit=99):
        if key in seen or len(out) >= limit:
            continue
        seen.add(key)
        e = entry(key, medium="pdf")
        out.append(_bubble(e["name"], e["definition"], e["icon"], S, width, indent))
    return out


SEVERITY_LEGEND = [
    ("Critical", "Blocks crawling or indexing, creates real risk, or materially "
                 "hurts revenue.", "0–39", "Critical"),
    ("High", "Large measurable impact, or a problem repeated across the site.",
     "40–59", "Weak"),
    ("Medium", "Worth doing — moderate effort, moderate return.", "60–74",
     "Needs Improvement"),
    ("Low", "Cleanup and best practice. Fold into normal release work.",
     "75–89", "Strong"),
    ("Opportunity", "Not a defect. Somewhere new visibility can be won.",
     "90–100", "Excellent"),
]


def _access_received(findings: dict) -> str:
    """
    What the client actually granted us, derived rather than asserted.

    A row that came back Need Access means we asked and could not see it, so
    the presence of ANY measured row in a section is the evidence of access.
    """
    got = []
    for label, prefix in (("Search Console", "GSC"), ("Google Analytics", "GA4")):
        rows = [f for cid, f in findings.items() if cid.startswith(prefix + "-")]
        if rows and any(f.get("status") not in ("Need Access", "N/A")
                        and (f.get("confidence") or 0) > 0 for f in rows):
            got.append(label)
    return ", ".join(got) if got else "None — site crawl and public data only"


def _severity_counts(findings: dict) -> dict:
    """Severity of OPEN issues only. A passing checkpoint has no severity."""
    out = {}
    for f in findings.values():
        if f.get("status") in ("Fail", "Not Implemented", "Warning"):
            k = f.get("severity") or "Low"
            if k in ("Critical", "High", "Medium", "Low"):
                out[k] = out.get(k, 0) + 1
    return out


def _coverage_counts(findings: dict, catalog: dict) -> tuple:
    """
    (measured, need_access, not_applicable) across the WHOLE catalog.

    Catalog rows we never returned a finding for count as Need Access, not as
    silently absent — an audit that quietly skips 60 rows and shows 100%
    coverage is the failure mode this chart exists to make impossible.
    """
    measured = need = na = 0
    for cid in catalog:
        f = findings.get(cid)
        if f is None:
            need += 1
        elif f.get("status") == "Need Access":
            need += 1
        elif f.get("status") == "N/A":
            na += 1
        else:
            measured += 1
    return measured, need, na


def build_pdf(meta: dict, scores: dict, findings: dict, catalog: dict,
              summary: dict | None = None, logo_path: str | None = None) -> bytes:
    """
    Render the audit as a PDF.

    `summary` is the optional generated executive summary / roadmap (see
    engine/summarise.py). Absent, the document still renders — the narrative
    sections are simply omitted rather than faked.
    """
    S = _styles()
    buf = io.BytesIO()
    doc = _Doc(buf, meta)
    story = []
    o = scores.get("overall", {}) or {}

    # ------------------------------------------------ cover
    if logo_path:
        try:
            from reportlab.platypus import Image
            story.append(Image(logo_path, width=1.6 * inch, height=0.5 * inch,
                               kind="proportional"))
            story.append(Spacer(1, 10))
        except Exception:
            pass
    story.append(Paragraph("Comprehensive SEO &amp; AI Search (GEO) Audit",
                           S["h1"]))
    story.append(Paragraph(_p(meta.get("client", "")), S["h2"]))
    story.append(Spacer(1, 4))
    analyst = meta.get("analyst") or {}
    story.append(_kv_table([
        [Paragraph("<b>Prepared by</b>", S["cell"]),
         Paragraph(_p(analyst.get("firm") or "Vici"), S["cell"])],
        [Paragraph("<b>Website</b>", S["cell"]), Paragraph(_p(meta.get("url")), S["cell"])],
        [Paragraph("<b>Audit date</b>", S["cell"]),
         Paragraph(_us_date(meta.get("generated")), S["cell"])],
        [Paragraph("<b>Pages analyzed</b>", S["cell"]),
         Paragraph(_p(meta.get("pages_crawled")), S["cell"])],
        [Paragraph("<b>Checks evaluated</b>", S["cell"]),
         Paragraph(_p(meta.get("coverage")), S["cell"])],
    ]))
    story.append(Spacer(1, 14))

    # ---- what we understand about the business ---------------------------
    # Everything in this box came off their own site. It is the fastest way to
    # signal that a person looked, and it gives the client something concrete
    # to correct — which turns the report into a conversation.
    ctx = ((meta.get("extras") or {}).get("context") or {})
    # Brendan's cover carries Business Model, Primary Markets, Primary
    # Conversion and Access Received. Three of those come from intake — a crawl
    # cannot know what a client sells to whom — so they are collected on the
    # form and simply omitted when nobody filled them in. Access Received is
    # derived: it is whichever collectors actually returned data.
    facts = []
    if meta.get("business_model") or meta.get("vertical"):
        facts.append(("Business model",
                      meta.get("business_model") or meta.get("vertical")))
    if meta.get("primary_markets"):
        facts.append(("Primary markets", meta["primary_markets"]))
    if meta.get("primary_conversion"):
        facts.append(("Primary conversion", meta["primary_conversion"]))
    if meta.get("channels"):
        facts.append(("Paid channels running",
                      ", ".join(str(c).replace("_", " ").title()
                                for c in meta["channels"])))
    granted = _access_received(findings)
    facts.append(("Access received", granted))
    if ctx.get("sections"):
        facts.append(("Top-level URL paths", ", ".join(ctx["sections"][:5])))
    if ctx.get("locations"):
        where = ", ".join(sorted({l.get("region") for l in ctx["locations"]
                                  if l.get("region")}))
        facts.append(("Locations found", f"{len(ctx['locations'])}"
                      + (f" — {where}" if where else "")))
    elif ctx.get("location_pages"):
        facts.append(("Location pages", str(ctx["location_pages"])))
    if ctx.get("product_pages"):
        facts.append(("Product pages seen", str(ctx["product_pages"])))
    if ctx.get("blog_pages"):
        facts.append(("Editorial pages seen", str(ctx["blog_pages"])))
    if ctx.get("phone"):
        facts.append(("Phone in markup", ctx["phone"]))
    if ctx.get("entity_types"):
        facts.append(("Schema entities", ", ".join(ctx["entity_types"][:5])))
    if facts:
        story.append(Paragraph("Current Site Snapshot", S["h3"]))
        story.append(Spacer(1, 3))
        story.append(_kv_table(
            [[Paragraph(f"<b>{_p(k)}</b>", S["cellsm"]),
              Paragraph(_p(v), S["cellsm"])] for k, v in facts],
            w1=1.7, w2=4.9))
        story.append(Spacer(1, 14))

    # ------------------------------------------------ overall score
    sev_counts = _severity_counts(findings)
    cov = _coverage_counts(findings, catalog)
    open_issues = sum(sev_counts.values())
    urgent = sev_counts.get("Critical", 0) + sev_counts.get("High", 0)

    hero = Table([[
        ScoreGauge(o.get("score"), _p(o.get("rating", "Not Assessed"))),
        Paragraph(
            ("<b>No overall score.</b> We couldn't assess enough areas to give "
             "you a number worth quoting. The areas below still stand on their "
             "own."
             if o.get("score") is None else
             "The average of the areas we could score. Areas we couldn't "
             "measure are left out, never counted as zero.")
            + f"<br/><br/><font size=15 color='#0b0b0b'><b>{open_issues}</b></font>"
              f"<font size=8.5 color='#52514e'> open issues, of which </font>"
              f"<font size=15 color='#0b0b0b'><b>{urgent}</b></font>"
              f"<font size=8.5 color='#52514e'> are Critical or High and worth "
              f"handling this month.</font>"
              f"<br/><font size=8.5 color='#52514e'>We measured <b>{cov[0]}</b> "
              f"of <b>{sum(cov)}</b> checks directly.</font>",
            S["small"])]],
        colWidths=[2.0 * inch, 4.6 * inch])
    hero.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(hero)
    story.append(Spacer(1, 14))

    # ---- severity distribution + coverage, side by side -----------------
    left = [Paragraph("Issues by Severity", S["h3"]),
            SegmentBar(severity_segments(sev_counts), width=3.05 * inch,
                       note="Severity tells you what to fix first, not how much there is.")]
    right = [Paragraph("Audit Coverage", S["h3"]),
             SegmentBar(coverage_segments(*cov), width=3.05 * inch,
                        note="“Need client access” isn’t a mark against you.")]
    grid = Table([[left, right]], colWidths=[3.3 * inch, 3.3 * inch])
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(grid)

    # ------------------------------------------------ executive summary
    if summary:
        story.append(Paragraph("Executive Summary", S["h2"]))
        if summary.get("overview"):
            story.append(Paragraph(_p(summary["overview"]), S["body"]))
        if summary.get("headline"):
            story.append(_banner("", summary["headline"], SEQ, S))
            story.append(Spacer(1, 8))
        for key, title in (("working", "Current Strengths"),
                           ("opportunity", "Biggest Opportunity")):
            items = summary.get(key)
            if not items:
                continue
            story.append(Paragraph(title, S["h3"]))
            if isinstance(items, str):
                story.append(Paragraph(_p(items), S["body"]))
            else:
                # Short lists read better as prose than as bullets; a bulleted
                # list of two items looks like a form that was filled in.
                for it in items:
                    story.append(Paragraph(_p(it), S["body"]))

    # ------------------------------------------------ the five things
    # One definition per term, at first use, document-wide.
    defined = set()

    five = (summary or {}).get("five_things") or []
    if five:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Top Findings", S["h2"]))
        story.append(Paragraph(
            f"In the order we'd fix them. Everything else is in the appendix "
            f"— real, but not where your money goes furthest.", S["small"]))
        story.append(Spacer(1, 10))
        for i, t in enumerate(five, start=1):
            block = [Paragraph(f"{i}. {_p(t.get('title'))}", S["h3"])]
            meta_line = " · ".join(x for x in (
                _p(t.get("severity")), _p(t.get("area")),
                (f"effort: {_p(t['effort'])}" if t.get("effort") else "")) if x)
            block.append(Paragraph(f"<font color='#898781'>{meta_line}</font>",
                                   S["muted"]))
            block.append(Spacer(1, 3))
            block.append(Paragraph(f"<b>What we found.</b> {_p(t.get('finding'))}",
                                   S["body"]))
            if t.get("why"):
                block.append(Paragraph(f"<b>Why it matters.</b> {_p(t['why'])}",
                                       S["body"]))
            # Scope, not instructions — see SERVICE_ACTION in summarise.py.
            if t.get("service") or t.get("action"):
                block.append(Paragraph(
                    f"<b>How we handle it.</b> "
                    f"{_p(t.get('service') or t.get('action'))}", S["body"]))
            # KeepTogether covers the finding itself. The definition bubbles are
            # appended OUTSIDE it: bundling them made the block tall enough to
            # jump a page break, leaving half of page 2 blank.
            story.append(KeepTogether(block))
            for b in _bubbles_for(
                    " ".join([t.get("title", ""), t.get("finding", ""),
                              t.get("why", ""), t.get("action", "") or ""]),
                    S, defined, width=6.55 * inch, indent=0.16 * inch):
                story.append(Spacer(1, 3))
                story.append(b)
            story.append(Spacer(1, 12))

    # ------------------------------------------------ area snapshot
    # No forced page break here: the exec summary rarely fills a page, and a
    # break left a third of page 2 blank. KeepTogether keeps the chart intact.
    story.append(Spacer(1, 6))
    story.append(Paragraph("Scores by Area", S["h2"]))

    secs = [(k, v) for k in ORDER if (v := (scores.get("sections") or {}).get(k))]
    # Ranked worst-first: the reader should not have to scan a table to find
    # where the work is. Unassessed areas sort last — they are not "worst".
    ranked = sorted(secs, key=lambda kv: (kv[1].get("score") is None,
                                          kv[1].get("score") if kv[1].get("score")
                                          is not None else 0))
    story.append(Paragraph(
        "Weakest first. The three worst are bolded. A hollow bar means we "
        "couldn't assess that area — not that it scored badly.", S["small"]))
    story.append(Spacer(1, 8))
    story.append(KeepTogether(
        SectionBars([(SHORT_NAMES.get(k, SECTION_NAMES[k]), v.get("score"),
                      v.get("rating")) for k, v in ranked], width=6.55 * inch)))
    story.append(Spacer(1, 16))

    story.append(Paragraph("Coverage by Area", S["h3"]))
    rows = [[Paragraph("<b>Section</b>", S["cellsm"]),
             Paragraph("<b>Score</b>", S["cellsm"]),
             "", Paragraph("<b>Rating</b>", S["cellsm"]),
             Paragraph("<b>Checked</b>", S["cellsm"]),
             Paragraph("<b>Failing</b>", S["cellsm"])]]
    for k, v in secs:
        sc = v.get("score")
        rows.append([
            Paragraph(SECTION_NAMES[k], S["cell"]),
            Paragraph("—" if sc is None else f"<b>{sc}</b>", S["cell"]),
            MiniMeter(sc),
            Paragraph(_p(v.get("rating")), S["cell"]),
            Paragraph(f"{v.get('checked')}/{v.get('total')}", S["cellsm"]),
            Paragraph(str(v.get("failing", 0)), S["cellsm"]),
        ])
    t = Table(rows, colWidths=[2.2 * inch, 0.45 * inch, 1.25 * inch,
                               1.35 * inch, 0.7 * inch, 0.55 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(t)

    # ------------------------------------------------ priority issues
    from .scoring import top_issues
    issues = top_issues(findings, catalog, 14)
    if issues:
        story.append(Paragraph("Priority Issues", S["h2"]))
        rows = [[Paragraph("<b>ID</b>", S["cellsm"]),
                 Paragraph("<b>Checkpoint</b>", S["cellsm"]),
                 Paragraph("<b>Severity</b>", S["cellsm"]),
                 Paragraph("<b>Finding &amp; recommended action</b>", S["cellsm"])]]
        for cid, f in issues:
            m = catalog.get(cid, {})
            rows.append([Paragraph(cid, S["cellsm"]),
                         Paragraph(_p(m.get("checkpoint")), S["cell"]),
                         _pill(f.get("severity"), SEV_PILL, S, 0.66 * inch),
                         Paragraph(_p(f.get("evidence")), S["cell"])])
        t = Table(rows, colWidths=[0.62 * inch, 1.6 * inch, 0.78 * inch, 3.5 * inch],
                  repeatRows=1)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("VALIGN", (2, 1), (2, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 3)]))
        story.append(t)

    # ------------------------------------------------ keyword rankings
    rk = ((meta.get("extras") or {}).get("rankings") or {})
    if rk.get("available") and rk.get("rows"):
        story.append(PageBreak())
        story.append(Paragraph("Keyword Rankings &amp; Industry Benchmarks", S["h2"]))
        story.append(Paragraph(
            f"The keywords this domain already ranks for in {_p(rk.get('location'))}, "
            f"ordered by position. <b>{rk.get('top10', 0)} of {rk.get('total', 0)}</b> "
            f"sit on page one. Volume and difficulty are third-party estimates, not "
            f"measurements of this site.", S["small"]))
        story.append(Spacer(1, 6))
        rows = [[Paragraph("<b>Keyword</b>", S["cellsm"]),
                 Paragraph("<b>Pos.</b>", S["cellsm"]),
                 Paragraph("<b>Volume</b>", S["cellsm"]),
                 Paragraph("<b>Difficulty</b>", S["cellsm"]),
                 Paragraph("<b>Ranking URL</b>", S["cellsm"])]]
        for r in rk["rows"][:25]:
            vol = r.get("search_volume")
            rows.append([
                Paragraph(_p(r.get("keyword")), S["cell"]),
                Paragraph(str(r.get("position") or "—"), S["cellsm"]),
                Paragraph(f"{vol:,}" if isinstance(vol, int) else "—", S["cellsm"]),
                Paragraph(str(r.get("difficulty") if r.get("difficulty") is not None
                              else "—"), S["cellsm"]),
                Paragraph(_p((r.get("url") or "").split("//")[-1]), S["cellsm"])])
        t = Table(rows, colWidths=[1.85 * inch, 0.5 * inch, 0.7 * inch, 0.75 * inch,
                                   2.7 * inch], repeatRows=1)
        st = [("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
              ("TOPPADDING", (0, 0), (-1, -1), 4),
              ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
              ("LEFTPADDING", (0, 0), (-1, -1), 3),
              ("ALIGN", (1, 0), (3, -1), "RIGHT")]
        # Page-one positions get the emphasis; everything else stays quiet, so
        # the eye lands on what is already winning.
        for i, r in enumerate(rk["rows"][:25], start=1):
            if (r.get("position") or 999) <= 10:
                # Light tint, dark text. The full-strength ramp color put a
                # mid-blue number on a mid-blue field and lost the number.
                st.append(("BACKGROUND", (1, i), (1, i), SEV_PILL["Low"][0]))
                st.append(("TEXTCOLOR", (1, i), (1, i), SEV_PILL["Low"][1]))
        t.setStyle(TableStyle(st))
        story.append(t)
    elif rk and not rk.get("available"):
        story.append(Paragraph("Keyword Rankings &amp; Industry Benchmarks", S["h2"]))
        story.append(Paragraph(
            f"Not collected — {_p(rk.get('reason'))}. This section is omitted rather "
            f"than estimated.", S["small"]))

    # ------------------------------------------------ roadmap
    if summary and summary.get("roadmap"):
        story.append(PageBreak())
        story.append(Paragraph("Our Recommended Plan", S["h2"]))
        story.append(Paragraph(
            "The order we would work in, and roughly how much sits in each "
            "phase. Item counts come straight from the findings above.",
            S["small"]))
        story.append(Spacer(1, 10))
        for i, phase in enumerate(summary["roadmap"], start=1):
            actions = phase.get("actions", []) or []
            # The chip already says "Phase 2"; repeating it in the title reads
            # as a template that forgot what it had already printed.
            title = _p(re.sub(r"^Phase\s*\d+\s*[—\-:]\s*", "",
                              str(phase.get("phase", ""))))
            # A phase is a card: a numbered chip, the phase name, the count, a
            # one-line rationale and the work itself. The chip and the count do
            # the visual work a wall of bullets could not.
            head = Table([[
                _pill(f"Phase {i}", {f"Phase {i}": (ORD_PHASE[min(i, 3) - 1],
                                                    colors.white)}, S, 0.62 * inch),
                Paragraph(f"<b>{title}</b>", S["body"]),
                Paragraph(f"<font color='#52514e'>{len(actions)} item"
                          f"{'s' if len(actions) != 1 else ''}</font>", S["cellsm"]),
            ]], colWidths=[0.72 * inch, 4.6 * inch, 1.2 * inch])
            head.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (2, 0), (2, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            block = [head]
            if phase.get("rationale"):
                block.append(Paragraph(_p(phase["rationale"]), S["small"]))
            block.append(Spacer(1, 4))

            # Work items, not instructions: the checkpoint name is what we are
            # taking on. The fix itself is the engagement.
            cells = []
            for a in actions[:14]:
                label = str(a).split(" — ")[0].strip().rstrip(".")
                cells.append(Paragraph(f"•  {_p(label)}", S["cellsm"]))
            if cells:
                pairs = [cells[i:i + 2] for i in range(0, len(cells), 2)]
                if len(pairs[-1]) == 1:
                    pairs[-1].append("")
                grid = Table(pairs, colWidths=[3.27 * inch, 3.27 * inch])
                grid.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                    ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                    ("ROUNDEDCORNERS", [8, 8, 8, 8]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]))
                block.append(grid)
            if len(actions) > 14:
                block.append(Paragraph(
                    f"<font color='#898781'>+ {len(actions) - 14} more in this "
                    f"phase, listed in the appendix.</font>", S["muted"]))
            block.append(Spacer(1, 14))
            story.append(KeepTogether(block))

    # ------------------------------------------------ detailed findings
    story.append(PageBreak())
    story.append(Paragraph("Appendix — Full Checkpoint Detail", S["h2"]))
    story.append(Paragraph(
        "The full record, by area. <b>Need Access</b> means we could not run "
        "the check without your account access. <b>N/A</b> means it does not "
        "apply to your site.", S["small"]))

    for k in ORDER:
        rows_f = [(cid, f) for cid, f in findings.items()
                  if (catalog.get(cid, {}) or {}).get("prefix") == k]
        if not rows_f:
            continue
        rows_f.sort(key=lambda r: (STATUS_ORDER.index(r[1]["status"])
                                   if r[1]["status"] in STATUS_ORDER else 9, r[0]))
        v = (scores.get("sections") or {}).get(k, {})
        # Section header carries its own meter, so a reader flipping straight to
        # a section does not have to go back to the snapshot to know how it did.
        head = Table([[Paragraph(
            f"{SECTION_NAMES[k]} — "
            f"{v.get('score') if v.get('score') is not None else '—'}/100 · "
            f"{_p(v.get('rating',''))}", S["h3"]),
            MiniMeter(v.get("score"), width=1.3 * inch, height=7)]],
            colWidths=[5.2 * inch, 1.4 * inch])
        head.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        data = [[Paragraph("<b>ID</b>", S["cellsm"]),
                 Paragraph("<b>Check</b>", S["cellsm"]),
                 Paragraph("<b>Status</b>", S["cellsm"]),
                 Paragraph("<b>What we found</b>", S["cellsm"])]]
        for cid, f in rows_f:
            m = catalog.get(cid, {})
            # The remediation stays out of the client PDF — it is the work we
            # are selling. It is still on the internal HTML report and in the
            # findings API for the team doing the fixing.
            data.append([Paragraph(cid, S["cellsm"]),
                         Paragraph(_p(m.get("checkpoint")), S["cell"]),
                         _pill(f["status"], STATUS_PILL, S, 0.86 * inch),
                         Paragraph(_p(f.get("evidence")), S["cell"])])
        t = Table(data, colWidths=[0.62 * inch, 1.75 * inch, 0.95 * inch, 3.18 * inch],
                  repeatRows=1)
        st = [("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("VALIGN", (2, 1), (2, -1), "MIDDLE"),
              ("LINEBELOW", (0, 0), (-1, -1), 0.35, LINE),
              ("TOPPADDING", (0, 0), (-1, -1), 4),
              ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
              ("LEFTPADDING", (0, 0), (-1, -1), 3)]
        t.setStyle(TableStyle(st))
        story.append(Spacer(1, 8))
        story.append(head)
        # Any jargon this section introduces that the reader has not met yet.
        for b in _bubbles_for(
                SECTION_NAMES[k] + " " + " ".join(
                    (catalog.get(cid, {}) or {}).get("checkpoint", "")
                    for cid, _f in rows_f[:12]),
                S, defined, width=6.55 * inch, limit=1):
            story.append(b)
            story.append(Spacer(1, 5))
        story.append(t)

    # ------------------------------------------------ method & sign-off
    story.append(PageBreak())
    story.append(Paragraph("Methodology & Data Sources", S["h2"]))
    story.append(Paragraph(
        "How we got these numbers, so you can check them or repeat this next "
        "quarter.", S["small"]))
    story.append(Spacer(1, 8))

    # Severity legend — lifted from the template's own scoring key, because a
    # reader who does not know what "High" means cannot act on the roadmap.
    story.append(Paragraph("How to read the ratings", S["h3"]))
    leg = [[Paragraph("<b>Severity</b>", S["cellsm"]),
            Paragraph("<b>What it means</b>", S["cellsm"]),
            Paragraph("<b>Score</b>", S["cellsm"]),
            Paragraph("<b>Area rating</b>", S["cellsm"])]]
    for sev, definition, rng, rating in SEVERITY_LEGEND:
        leg.append([Paragraph(_p(sev), S["cellsm"]),
                    Paragraph(_p(definition), S["cellsm"]),
                    Paragraph(_p(rng), S["cellsm"]),
                    Paragraph(_p(rating), S["cellsm"])])
    lt = Table(leg, colWidths=[0.85 * inch, 3.5 * inch, 0.7 * inch, 1.55 * inch])
    lst = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
           ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
           ("TOPPADDING", (0, 0), (-1, -1), 5),
           ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
           ("LEFTPADDING", (0, 0), (-1, -1), 3)]
    for i, (sev, _d, _r, _rt) in enumerate(SEVERITY_LEGEND, start=1):
        lst.append(("BACKGROUND", (0, i), (0, i), ORD.get(sev, TRACK)))
        lst.append(("TEXTCOLOR", (0, i), (0, i),
                    colors.white if sev in ("Critical", "High") else INK))
    lt.setStyle(TableStyle(lst))
    story.append(lt)
    story.append(Spacer(1, 14))

    m, need, na = _coverage_counts(findings, catalog)
    method = [
        ("Collection",
         "Browser capture — pages were opened in a real browser and the rendered "
         "DOM was read, because the server-side crawl was blocked."
         if meta.get("capture_method") else
         f"Automated crawl of {_p(meta.get('pages_crawled'))} pages from "
         f"{_p(meta.get('url'))}, following internal links and the XML sitemap."),
        ("Framework",
         f"{len(catalog)} checkpoints across {len(SECTION_NAMES)} areas, covering "
         f"technical SEO, on-page, structured data, performance, security, "
         f"E-E-A-T and generative-engine visibility."),
        ("What we measured", f"{m} checks answered from your live site plus "
                             f"third-party data."),
        ("What we couldn't measure",
         f"{need} checks need access to accounts only you control — mostly "
         f"Search Console and Analytics. Those are marked Need Access and left "
         f"out of the scoring instead of counted against you. Give us read-only "
         f"access and most of that gap closes."),
        ("Not applicable", f"{na} checks don't apply to a site built like "
                           f"yours, so they're left out."),
        ("Scoring", "Each area scores out of 100 from the checks we could run, "
                    "weighted by severity. If there wasn't enough to go on, the "
                    "area is marked Not Assessed instead of scored low. An area "
                    "we couldn't measure is not a failing one."),
    ]
    if meta.get("truncated"):
        method.append(("Coverage limit", _p(meta["truncated"])))
    story.append(_kv_table([[Paragraph(f"<b>{_p(k)}</b>", S["cellsm"]),
                             Paragraph(_p(v), S["cellsm"])] for k, v in method],
                           w1=1.55, w2=5.05))

    analyst = meta.get("analyst") or {}
    if analyst.get("name") or analyst.get("email"):
        story.append(Spacer(1, 18))
        who = _p(analyst.get("name") or analyst.get("firm"))
        line = f"<b>{who}</b>"
        if analyst.get("title"):
            line += f", {_p(analyst['title'])}"
        if analyst.get("firm") and analyst.get("name"):
            line += f"<br/>{_p(analyst['firm'])}"
        if analyst.get("email"):
            line += f"<br/>{_p(analyst['email'])}"
        story.append(_banner(
            "Questions About This Report",
            "Happy to walk through any of this line by line. If something looks "
            "wrong, tell us — nine times out of ten it means a search engine saw "
            "the same odd thing we did, which is worth knowing either way.",
            SEQ, S))
        story.append(Spacer(1, 8))
        story.append(Paragraph(line, S["body"]))

    doc.build(story)
    return buf.getvalue()


def _banner(title, body, color, S):
    # Title is optional: used with one for warnings, without one for a pulled
    # quote. An empty <b></b> would leave a stray blank line.
    head = f"<b>{_p(title)}</b><br/>" if title else ""
    t = Table([[Paragraph(head + f"<font size={'8.5' if title else '10'}>"
                          f"{_p(body)}</font>", S["body"])]],
              colWidths=[6.6 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LINEBEFORE", (0, 0), (0, -1), 3, color),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t
