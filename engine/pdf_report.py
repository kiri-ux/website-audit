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
  * Status colours are the reserved status palette and ALWAYS ship with a text
    label, never as the sole carrier of meaning.
"""
from __future__ import annotations
import html as _h
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
                     severity_segments, coverage_segments)

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
    "EEAT": "E-E-A-T Audit", "GEO": "AI SEO / GEO", "OFF": "Off-Page SEO & Authority",
}
# Chart labels. The full names are correct in prose and in the tables, but a
# ranked bar chart has a fixed label gutter — shortening beats auto-shrinking,
# which produces a chart with six different type sizes in it.
SHORT_NAMES = {
    "ANA": "Analytics & Tracking", "GSC": "Search Console", "GA4": "Analytics 4",
    "TECH": "Technical SEO", "URL": "URL & Architecture", "SEC": "HTTPS & Security",
    "CANON": "Canonicalization", "PERF": "Performance & CWV", "ONP": "On-Page SEO",
    "MOB": "Mobile SEO", "SCHEMA": "Structured Data", "INTL": "International SEO",
    "HTML": "HTML & Code Quality", "EEAT": "E-E-A-T", "GEO": "AI SEO / GEO",
    "OFF": "Off-Page & Authority",
}
ORDER = list(SECTION_NAMES)
STATUS_ORDER = ["Fail", "Not Implemented", "Warning", "Pass", "Need Access", "N/A"]


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
        left = f"{self.meta.get('client','')} — SEO & GEO Audit"
        canvas.drawString(self.leftMargin, y, left[:90])
        canvas.drawRightString(self.leftMargin + self.width, y, f"Page {doc.page}")
        if self.meta.get("build"):
            canvas.drawCentredString(self.leftMargin + self.width / 2, y,
                                     self.meta["build"])
        canvas.restoreState()


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
    story.append(Paragraph("Comprehensive SEO &amp; Generative Engine "
                           "Optimization Audit", S["h1"]))
    story.append(Paragraph(_p(meta.get("client", "")), S["h2"]))
    story.append(Spacer(1, 4))
    analyst = meta.get("analyst") or {}
    prepared = []
    if analyst.get("name"):
        prepared = [[Paragraph("<b>Prepared by</b>", S["cell"]),
                     Paragraph(_p(analyst["name"])
                               + (f", {_p(analyst.get('title'))}"
                                  if analyst.get("title") else "")
                               + (f"<br/><font color='#52514e'>"
                                  f"{_p(analyst.get('firm'))}</font>"
                                  if analyst.get("firm") else ""), S["cell"])]]
    story.append(_kv_table(prepared + [
        [Paragraph("<b>Website</b>", S["cell"]), Paragraph(_p(meta.get("url")), S["cell"])],
        [Paragraph("<b>Audit date</b>", S["cell"]), Paragraph(_p(meta.get("generated")), S["cell"])],
        [Paragraph("<b>Pages analysed</b>", S["cell"]),
         Paragraph(_p(meta.get("pages_crawled")), S["cell"])],
        [Paragraph("<b>Checkpoints evaluated</b>", S["cell"]),
         Paragraph(_p(meta.get("coverage")), S["cell"])],
        [Paragraph("<b>Collection method</b>", S["cell"]),
         Paragraph("Browser capture (real-render)" if meta.get("capture_method")
                   else "Automated crawl", S["cell"])],
    ]))
    story.append(Spacer(1, 14))

    # ---- what we understand about the business ---------------------------
    # Everything in this box came off their own site. It is the fastest way to
    # signal that a person looked, and it gives the client something concrete
    # to correct — which turns the report into a conversation.
    ctx = ((meta.get("extras") or {}).get("context") or {})
    facts = []
    if ctx.get("categories"):
        facts.append(("Main sections", ", ".join(ctx["categories"][:5])))
    if ctx.get("locations"):
        where = ", ".join(sorted({l.get("region") for l in ctx["locations"]
                                  if l.get("region")}))
        facts.append((f"Locations found", f"{len(ctx['locations'])}"
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
        story.append(Paragraph("What we understand about your business", S["h3"]))
        story.append(Paragraph(
            "Read from your own pages during the crawl. If anything here is "
            "wrong, tell us — it usually means search engines have it wrong too.",
            S["small"]))
        story.append(Spacer(1, 5))
        story.append(_kv_table(
            [[Paragraph(f"<b>{_p(k)}</b>", S["cellsm"]),
              Paragraph(_p(v), S["cellsm"])] for k, v in facts],
            w1=1.7, w2=4.9))
        story.append(Spacer(1, 14))

    # data-integrity banners come FIRST — before any number the reader might trust
    if meta.get("crawl_blocked"):
        story.append(_banner("This report is not valid — crawl blocked",
                             f"{meta.get('crawl_note','')}. Every content-dependent "
                             f"checkpoint is reported as Need Access rather than as a "
                             f"defect. Do not send this to a client.",
                             colors.HexColor("#d03b3b"), S))
    if meta.get("truncated"):
        story.append(_banner("Partial crawl",
                             f"{meta['truncated']} — coverage reflects only the pages "
                             f"reached within the time budget.",
                             colors.HexColor("#fab219"), S))

    # ------------------------------------------------ overall score
    sev_counts = _severity_counts(findings)
    cov = _coverage_counts(findings, catalog)
    open_issues = sum(sev_counts.values())
    urgent = sev_counts.get("Critical", 0) + sev_counts.get("High", 0)

    hero = Table([[
        ScoreGauge(o.get("score"), _p(o.get("rating", "Not Assessed"))),
        Paragraph(
            ("<b>No overall score.</b> Too few sections could be assessed to "
             "produce a figure worth quoting — the sections below still stand "
             "on their own."
             if o.get("score") is None else
             "Mean of assessed section scores. Sections with no assessable data "
             "are excluded, never scored zero.")
            + f"<br/><br/><font size=15 color='#0b0b0b'><b>{open_issues}</b></font>"
              f"<font size=8.5 color='#52514e'> open issues, of which </font>"
              f"<font size=15 color='#0b0b0b'><b>{urgent}</b></font>"
              f"<font size=8.5 color='#52514e'> are Critical or High and should be "
              f"actioned this month.</font>"
              f"<br/><font size=8.5 color='#52514e'><b>{cov[0]}</b> of "
              f"<b>{sum(cov)}</b> checkpoints were measured directly.</font>",
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
    left = [Paragraph("Where the issues sit", S["h3"]),
            SegmentBar(severity_segments(sev_counts), width=3.05 * inch,
                       note="Severity is what to fix first, not how many.")]
    right = [Paragraph("What we were able to measure", S["h3"]),
             SegmentBar(coverage_segments(*cov), width=3.05 * inch,
                        note="“Need client access” is not a defect.")]
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
        for key, title in (("working", "What's Working"),
                           ("opportunity", "Where the Ground Is")):
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
    five = (summary or {}).get("five_things") or []
    if five:
        story.append(Spacer(1, 6))
        story.append(Paragraph("The Five Things That Matter Most", S["h2"]))
        story.append(Paragraph(
            f"This audit checked {_p(meta.get('coverage'))} checkpoints. These "
            f"five are the ones we would fix first, in this order. Everything "
            f"else is in the detail section and the appendix — real, but not "
            f"where the return is.", S["small"]))
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
            if t.get("action"):
                block.append(Paragraph(f"<b>What to do.</b> {_p(t['action'])}",
                                       S["body"]))
            block.append(Spacer(1, 9))
            story.append(KeepTogether(block))

    # ------------------------------------------------ area snapshot
    # No forced page break here: the exec summary rarely fills a page, and a
    # break left a third of page 2 blank. KeepTogether keeps the chart intact.
    story.append(Spacer(1, 6))
    story.append(Paragraph("Audit Area Snapshot", S["h2"]))

    secs = [(k, v) for k in ORDER if (v := (scores.get("sections") or {}).get(k))]
    # Ranked worst-first: the reader should not have to scan a table to find
    # where the work is. Unassessed areas sort last — they are not "worst".
    ranked = sorted(secs, key=lambda kv: (kv[1].get("score") is None,
                                          kv[1].get("score") if kv[1].get("score")
                                          is not None else 0))
    story.append(Paragraph(
        "All areas ranked weakest first. The three weakest are emphasised; "
        "hollow bars are areas we could not assess, which is not the same as "
        "an area that scored badly.", S["small"]))
    story.append(Spacer(1, 8))
    story.append(KeepTogether(
        SectionBars([(SHORT_NAMES.get(k, SECTION_NAMES[k]), v.get("score"),
                      v.get("rating")) for k, v in ranked], width=6.55 * inch)))
    story.append(Spacer(1, 16))

    story.append(Paragraph("Coverage by area", S["h3"]))
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
            ev = _p(f.get("evidence"))
            if f.get("recommendation"):
                ev += (f"<br/><font color='#898781'><i>→ "
                       f"{_p(f['recommendation'])}</i></font>")
            rows.append([Paragraph(cid, S["cellsm"]),
                         Paragraph(_p(m.get("checkpoint")), S["cell"]),
                         Paragraph(_p(f.get("severity")), S["cellsm"]),
                         Paragraph(ev, S["cell"])])
        t = Table(rows, colWidths=[0.62 * inch, 1.6 * inch, 0.7 * inch, 3.58 * inch],
                  repeatRows=1)
        st = [("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
              ("TOPPADDING", (0, 0), (-1, -1), 5),
              ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
              ("LEFTPADDING", (0, 0), (-1, -1), 3)]
        # severity swatch: ordinal ramp, always beside the text label
        for i, (cid, f) in enumerate(issues, start=1):
            st.append(("BACKGROUND", (2, i), (2, i),
                       ORD.get(f.get("severity"), TRACK)))
            st.append(("TEXTCOLOR", (2, i), (2, i),
                       colors.white if f.get("severity") in ("Critical", "High")
                       else INK))
        t.setStyle(TableStyle(st))
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
                st.append(("BACKGROUND", (1, i), (1, i), ORD.get("Low", TRACK)))
        t.setStyle(TableStyle(st))
        story.append(t)
    elif rk and not rk.get("available"):
        story.append(Paragraph("Keyword Rankings &amp; Industry Benchmarks", S["h2"]))
        story.append(Paragraph(
            f"Not collected — {_p(rk.get('reason'))}. This section is omitted rather "
            f"than estimated.", S["small"]))

    # ------------------------------------------------ roadmap
    if summary and summary.get("roadmap"):
        story.append(Paragraph("Prioritized Next Steps", S["h2"]))
        for phase in summary["roadmap"]:
            story.append(Paragraph(_p(phase.get("phase", "")), S["h3"]))
            if phase.get("rationale"):
                story.append(Paragraph(_p(phase["rationale"]), S["small"]))
            for a in phase.get("actions", []) or []:
                story.append(Paragraph(_p(a), S["bullet"], bulletText="•"))

    # ------------------------------------------------ detailed findings
    story.append(PageBreak())
    story.append(Paragraph("Appendix — Full Checkpoint Detail", S["h2"]))
    story.append(Paragraph(
        "The complete record, area by area. This is here so any finding above "
        "can be checked and so nothing is hidden — not because we expect it to "
        "be read start to finish. Every row carries its source and a raw value, "
        "so a disputed finding can be traced to the collector that produced it. "
        "<b>Need Access</b> means the check could not run — not that it failed.",
        S["small"]))

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
                 Paragraph("<b>Checkpoint</b>", S["cellsm"]),
                 Paragraph("<b>Status</b>", S["cellsm"]),
                 Paragraph("<b>Evidence</b>", S["cellsm"])]]
        for cid, f in rows_f:
            m = catalog.get(cid, {})
            ev = _p(f.get("evidence"))
            if f.get("recommendation"):
                ev += (f"<br/><font color='#898781'><i>→ "
                       f"{_p(f['recommendation'])}</i></font>")
            data.append([Paragraph(cid, S["cellsm"]),
                         Paragraph(_p(m.get("checkpoint")), S["cell"]),
                         Paragraph(_p(f["status"]), S["cellsm"]),
                         Paragraph(ev, S["cell"])])
        t = Table(data, colWidths=[0.62 * inch, 1.75 * inch, 0.85 * inch, 3.28 * inch],
                  repeatRows=1)
        st = [("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("LINEBELOW", (0, 0), (-1, -1), 0.35, LINE),
              ("TOPPADDING", (0, 0), (-1, -1), 4),
              ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
              ("LEFTPADDING", (0, 0), (-1, -1), 3)]
        for i, (cid, f) in enumerate(rows_f, start=1):
            st.append(("TEXTCOLOR", (2, i), (2, i),
                       STATUS.get(f["status"], MUTED)))
        t.setStyle(TableStyle(st))
        story.append(Spacer(1, 8))
        story.append(head)
        story.append(t)

    # ------------------------------------------------ method & sign-off
    story.append(PageBreak())
    story.append(Paragraph("How This Audit Was Carried Out", S["h2"]))
    story.append(Paragraph(
        "Stating the method is part of the finding. A number without a method "
        "behind it cannot be argued with, checked, or repeated next quarter.",
        S["small"]))
    story.append(Spacer(1, 8))

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
        ("What we measured", f"{m} checkpoints answered from direct observation "
                             f"of your site and third-party data."),
        ("What we could not measure",
         f"{need} checkpoints need access to accounts only you control — Search "
         f"Console and Analytics, chiefly. They are reported as Need Access and "
         f"are excluded from scoring rather than counted as failures. Granting "
         f"read-only access closes most of that gap."),
        ("Not applicable", f"{na} checkpoints do not apply to a site of this "
                           f"shape and are excluded."),
        ("Scoring", "Each area scores out of 100 from its assessed checkpoints, "
                    "weighted by severity. Areas with too little assessable data "
                    "are marked Not Assessed rather than scored low — an "
                    "unmeasured area is not a failing one."),
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
            "Questions about this report",
            "Any finding here can be walked through line by line, and anything "
            "you disagree with is worth raising — a wrong finding usually means "
            "we saw something a search engine also saw.", SEQ, S))
        story.append(Spacer(1, 8))
        story.append(Paragraph(line, S["body"]))

    doc.build(story)
    return buf.getvalue()


def _banner(title, body, colour, S):
    # Title is optional: used with one for warnings, without one for a pulled
    # quote. An empty <b></b> would leave a stray blank line.
    head = f"<b>{_p(title)}</b><br/>" if title else ""
    t = Table([[Paragraph(head + f"<font size={'8.5' if title else '10'}>"
                          f"{_p(body)}</font>", S["body"])]],
              colWidths=[6.6 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LINEBEFORE", (0, 0), (0, -1), 3, colour),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t
