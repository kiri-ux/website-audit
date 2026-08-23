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

from .charts import (ScoreGauge, SectionBars, SegmentBar, MiniMeter, GradRule,
                     DefBadge, Lamp, severity_segments, coverage_segments)

# ---- palette (matches the HTML report) -------------------------------------
# ---- Vici brand palette, from VICI_ColorPalette_2025 ----------------------
#
# Primary:   Atlas Blue #002D58 (PMS 648 C) · Velocity Blue #0066B3 (PMS 300 C)
#            Ink #212121 (PMS Black C) · Parchment #FDFBF7 (PMS 7506 C @10%)
# Fades:     Velocity 50% #80B2D9, 10% #E6F0F7
#            Atlas    50% #8096AC, 10% #E6EAEE
#            Ink      50% #909090, 10% #E9E9E9
# Secondary: Plum #78286E · Gold #F1B434 · Cardinal #A6192E · Teal #4FD4E0
#
# The ordinal severity ramp is built from Atlas -> Velocity -> the Velocity
# fades, so the darkest step is the brand's own darkest blue rather than a
# generic navy. Severity stays a SINGLE-HUE ordinal scale — the secondaries
# are not used as an adjacent categorical set, which they would fail.
ATLAS      = colors.HexColor("#002D58")
VELOCITY   = colors.HexColor("#0066B3")
PARCHMENT  = colors.HexColor("#FDFBF7")
PLUM       = colors.HexColor("#78286E")
GOLD       = colors.HexColor("#F1B434")
CARDINAL   = colors.HexColor("#A6192E")
TEAL       = colors.HexColor("#4FD4E0")

INK        = colors.HexColor("#212121")   # brand Ink
INK2       = colors.HexColor("#4A5461")   # Atlas, lightened for running text
MUTED      = colors.HexColor("#8096AC")   # Atlas 50%
LINE       = colors.HexColor("#E6EAEE")   # Atlas 10%
SURFACE    = colors.HexColor("#FDFBF7")   # Parchment
TRACK      = colors.HexColor("#E9E9E9")   # Ink 10%
SEQ        = VELOCITY
# validated ordinal ramp, light mode (validate_palette.js --ordinal: all pass)
ORD = {"Critical": colors.HexColor("#002D58"), "High": colors.HexColor("#0066B3"),
       "Medium": colors.HexColor("#4D94CB"), "Low": colors.HexColor("#80B2D9"),
       "Opportunity": TRACK}
# Semantic status is deliberately NOT the brand blues — a reader must be able
# to tell "this failed" from "this is severity 3" without reading the label.
# Cardinal and Gold are the brand's own red and amber, so it still belongs to
# the palette.
STATUS = {"Pass": colors.HexColor("#1E7A45"), "Warning": GOLD,
          "Fail": CARDINAL,
          "Not Implemented": colors.HexColor("#C2653A"),
          "Need Access": MUTED, "N/A": MUTED}

SECTION_NAMES = {
    "ANA": "Analytics & Tracking", "GSC": "Search Console", "GA4": "Google Analytics 4",
    "TECH": "Technical SEO", "URL": "URL Structure & Site Architecture",
    "SEC": "HTTPS & Security", "CANON": "Canonicalization",
    "PERF": "Website Performance & Core Web Vitals", "ONP": "On-Page SEO",
    "MOB": "Mobile SEO", "SCHEMA": "Structured Data (Schema)",
    "INTL": "International SEO", "HTML": "HTML & Code Quality",
    "EEAT": "E-E-A-T Audit", "GEO": "AI Search", "OFF": "Off-Page SEO & Authority",
    "CONS": "Consent & Privacy",
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
    "OFF": "Off-Page & Authority", "CONS": "Consent & Privacy",
}
ORDER = list(SECTION_NAMES)
STATUS_ORDER = ["Fail", "Not Implemented", "Warning", "Pass", "Info",
                "Need Access", "Manual", "N/A"]


def _judged(cid: str, status: str = "") -> bool:
    """
    Does this row carry a reading rather than a measurement?

    Shares its definition with the HTML report so the two documents cannot drift
    into marking different rows — which would be worse than marking none, since
    the whole point of the lamp is telling a reviewer where to look.
    """
    from .report import is_judged
    if status in ("Need Access", "N/A", "Manual"):
        return False
    return is_judged(cid)


def _synthetic_rows(catalog: dict, findings: dict, prefix: str) -> list:
    """
    Catalog rows for this section that produced no finding at all.

    They used to be counted in the coverage chart and then omitted from an
    appendix headed "the full record, by area" — so the document both charged
    the client for them and refused to name them. Now they are named, and
    labelled with who they are waiting on.
    """
    from engine.access import blocked_on
    out = []
    for cid, m in catalog.items():
        if (m or {}).get("prefix") != prefix or cid in findings:
            continue
        who = blocked_on(cid, None)
        if who == "manual":
            # A short, per-section note rather than nothing. An empty cell under
            # "What we found" reads as work not done; see report.MANUAL_NOTE.
            from .report import manual_note
            out.append((cid, {"status": "Manual",
                              "evidence": manual_note(prefix),
                              "severity": "Low"}))
        else:
            out.append((cid, {"status": "Need Access",
                              "evidence": "Waiting on our data provider for "
                                          "this run.", "severity": "Low"}))
    return out


# Words that end in "s" without being plural. Stripping the s off these turns
# "1 address" into "1 addres", which is worse than the bug being fixed.
_NOT_PLURAL = {"css", "js", "https", "rss", "status", "address", "class",
               "canonicals", "less", "bypass", "analysis", "https"}

# Third-person singular for the verbs that actually follow a count in our
# evidence strings. Deliberately a closed list: a general -s rule would produce
# "1 page hass".
_VERB_S = {
    "exceed": "exceeds", "share": "shares", "have": "has", "are": "is",
    "send": "sends", "contain": "contains", "lead": "leads", "use": "uses",
    "point": "points", "return": "returns", "miss": "misses", "load": "loads",
    "take": "takes", "declare": "declares", "carry": "carries",
    "redirect": "redirects", "block": "blocks", "fail": "fails",
    "include": "includes", "expose": "exposes", "serve": "serves",
    "reference": "references", "link": "links", "contain,": "contains,",
}

_COUNT_RE = re.compile(r"\b1 ([A-Za-z][A-Za-z-]*?)s\b(\s+)([A-Za-z]+)?")


def _agree(text: str) -> str:
    """
    "1 pages exceed 200KB" -> "1 page exceeds 200KB".

    Evidence strings are built with f-strings around a count, and a count of
    exactly one falls out of the plural wording every check is written in. It
    is a small thing that reads as carelessness, and it appears in a document
    whose entire argument is that the numbers were checked.

    Applied at render time rather than in forty check modules, because the
    findings store holds the measurement and this is presentation.
    """
    def fix(m):
        noun, gap, verb = m.group(1), m.group(2), m.group(3)
        if f"{noun}s".lower() in _NOT_PLURAL or noun.lower() in _NOT_PLURAL:
            return m.group(0)
        out = f"1 {noun}{gap}"
        if verb:
            out += _VERB_S.get(verb.lower(), verb) if verb.lower() in _VERB_S \
                else verb
        return out
    return _COUNT_RE.sub(fix, text or "")


def _dedupe_evidence(rows: list) -> list:
    """
    Stop the appendix restating one observation twenty times.

    Two sources of it. The crawler answers several checkpoints from the same
    measurement, so ONP-01 "Issues with duplicate title tags" and ONP-23
    "Unique title on every page" both print "83 pages share 25 duplicated title
    tags" verbatim. And the judgment layer writes each row independently, so a
    site with thin content gets fifteen paragraphs that all open "All examined
    pages (homepage, practice areas, …) contain only generic marketing copy".

    Both read as padding. Nothing is deleted — the later row points at the one
    that carries the detail, which is shorter AND more useful, because it says
    these are the same problem.

    Near-duplicates keep whatever is actually different. A row whose text is
    entirely contained in an earlier one has nothing left, so it gets the
    cross-reference alone.
    """
    import difflib

    def norm(s):
        return " ".join((s or "").lower().split())

    seen = []            # [(cid, normalized, original)]
    out = []
    for cid, f in rows:
        ev = (f.get("evidence") or "").strip()
        n = norm(ev)
        # Manual rows carry a deliberate per-section note, and several in a row
        # SHOULD read the same — that repetition is the status, not padding.
        # Collapsing them to "Same finding as PERF-05." would say something
        # false: they are not one finding, they are three separate checks that
        # happen to be handled the same way.
        if f.get("status") == "Manual":
            out.append((cid, f))
            continue
        if len(n) < 40:                      # short rows are not the problem
            seen.append((cid, n, ev))
            out.append((cid, f))
            continue
        best, ratio = None, 0.0
        for pcid, pn, _pev in seen:
            r = difflib.SequenceMatcher(None, pn, n).ratio()
            if r > ratio:
                best, ratio = pcid, r
        if ratio >= 0.93:
            f = {**f, "evidence": f"Same finding as {best}."}
        elif ratio >= 0.72 and best:
            prev = next(p for p in seen if p[0] == best)[2]
            tail = _distinct_tail(prev, ev)
            f = {**f, "evidence": (f"As {best}. {tail}" if tail
                                   else f"Same finding as {best}.")}
        seen.append((cid, n, ev))
        out.append((cid, f))
    return out


def _distinct_tail(prev: str, cur: str) -> str:
    """
    The part of `cur` that is not shared opening boilerplate with `prev`.

    Cuts at a sentence boundary rather than mid-word: a fragment starting
    "…ages contain only generic" is worse than printing the whole thing.
    """
    import difflib
    sm = difflib.SequenceMatcher(None, prev, cur)
    match = sm.find_longest_match(0, len(prev), 0, len(cur))
    # Only treat it as a shared PREAMBLE if the overlap starts near the top of
    # the current text; a match in the middle is a coincidence, not boilerplate.
    if match.size < 60 or match.b > 25:
        return ""
    rest = cur[match.b + match.size:].lstrip(" ,.;")
    cut = max(rest.find(". "), 0)
    if cut:
        rest = rest[cut + 2:]
    rest = rest.strip()
    if len(rest) < 30:
        return ""
    return rest[0].upper() + rest[1:]


def _us_date(stamp) -> str:
    """2026-08-18 14:00 -> 08/18/2026. US clients, US format, no time of day."""
    raw = str(stamp or "").split(" ")[0]
    try:
        d = datetime.strptime(raw, "%Y-%m-%d")
        return d.strftime("%m/%d/%Y")
    except Exception:
        return _h.escape(raw)



# NO EM DASHES ANYWHERE IN THE OUTPUT.
#
# House style, and it has to be enforced HERE rather than by editing strings.
# Plenty of this copy is not ours to edit: the judgment layer writes evidence
# at scan time, and a rule in a prompt is a request, not a guarantee. One
# substitution at the escape boundary catches every path into the document,
# including text that has not been written yet.
#
# En dashes go too. They are the same typographic gesture and read as an
# inconsistency when only half of them are converted.
def _dashes(t: str) -> str:
    return (t.replace("\u2014", "-").replace("\u2013", "-")
             .replace("&mdash;", "-").replace("&ndash;", "-"))


def _p(text):
    return _dashes(_h.escape(str(text if text is not None else "")))


def _rule(width=1.75 * inch):
    """
    The section mark, in one place.

    A short tapered gradient under every section heading. It is the same mark
    as the cover's full-measure rule, scaled down — which is the whole point:
    the reader meets it once on page one and thereafter recognizes it as
    "a new section", without reading the heading first. Twelve headings
    calling this beats twelve headings each deciding their own width.
    """
    return GradRule(width=width, height=2.6, space_before=0, space_after=3)


def _styles():
    # HEADLINES AND BODY ARE DIFFERENT FACES.
    #
    # Agdasima for headlines, GT Walsheim Pro for body copy — the brand book's
    # own pairing. `register()` falls back per family, so a document can end up
    # with brand headlines over Roboto body copy if only one set of files is
    # installed, which is a good deal better than losing both.
    #
    # Imported INSIDE the function and read after register() on purpose: these
    # are module-level names that register() rebinds, so a module-level `from
    # .fonts import BODY` would capture "Helvetica" before the fonts loaded.
    from . import fonts as _fonts
    _fonts.register()
    BODY, BOLD = _fonts.BODY, _fonts.BOLD
    HEAD, HEAD_BOLD = _fonts.HEAD, _fonts.HEAD_BOLD
    ss = getSampleStyleSheet()
    def mk(name, **kw):
        base = dict(fontName=BODY, fontSize=9.5, leading=13, textColor=INK)
        base.update(kw)
        return ParagraphStyle(name, parent=ss["Normal"], **base)
    return {
        # Agdasima is CONDENSED, so the same point size reads smaller and sets
        # far more text per line. Headings get a couple of points back to
        # hold the same optical weight against the body face.
        "h1": mk("h1", fontName=HEAD_BOLD, fontSize=23, leading=26,
                 spaceAfter=4),
        "h2": mk("h2", fontName=HEAD_BOLD, fontSize=14.5, leading=18,
                 spaceBefore=16, spaceAfter=7),
        "h3": mk("h3", fontName=HEAD_BOLD, fontSize=11.5, leading=15,
                 spaceBefore=10, spaceAfter=4),
        "body": mk("body", spaceAfter=6),
        "small": mk("small", fontSize=8.5, leading=11.5, textColor=INK2),
        "muted": mk("muted", fontSize=8, leading=11, textColor=MUTED),
        "cell": mk("cell", fontSize=8.5, leading=11),
        "cellsm": mk("cellsm", fontSize=8, leading=10.5, textColor=INK2),
        "hero": mk("hero", fontName=HEAD_BOLD, fontSize=46, leading=50),
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
        left = f"{self.meta.get('client','')} - Website Audit"
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
    "Critical":    (colors.HexColor("#002D58"), colors.white),
    "High":        (colors.HexColor("#0066B3"), colors.white),
    "Medium":      (colors.HexColor("#E6F0F7"), colors.HexColor("#004E88")),
    "Low":         (colors.HexColor("#F2F7FB"), colors.HexColor("#0066B3")),
    "Opportunity": (colors.HexColor("#E9E9E9"), colors.HexColor("#4A5461")),
}
ORD_PHASE = [colors.HexColor("#002D58"), colors.HexColor("#0066B3"),
             colors.HexColor("#4D94CB")]

STATUS_PILL = {
    "Pass":            (colors.HexColor("#E4F1E8"), colors.HexColor("#1E7A45")),
    "Fail":            (colors.HexColor("#F7E4E7"), colors.HexColor("#A6192E")),
    "Warning":         (colors.HexColor("#FDF2DC"), colors.HexColor("#8A6209")),
    "Not Implemented": (colors.HexColor("#F9E9E1"), colors.HexColor("#9C4A1E")),
    "Need Access":     (colors.HexColor("#E9E9E9"), colors.HexColor("#4A5461")),
    "Manual":          (colors.HexColor("#E6EAEE"), colors.HexColor("#002D58")),
    "Info":            (colors.HexColor("#E6F0F7"), colors.HexColor("#004E88")),
    "N/A":             (colors.HexColor("#F1F1F1"), colors.HexColor("#8096AC")),
}

# WHAT THE STATUS COLUMN IS FOR.
#
# Every other value in it states a VERDICT: Pass, Fail, Warning, N/A. Two did
# not. "Manual" answered how the check gets done, and "Info" named a category
# of finding — both answer a different question from the one the column asks,
# and a reader scanning down for a result hits them and has to stop.
#
# The internal values do not change: `Info` is load-bearing in the scoring
# code, which excludes it from the denominator, and renaming it there would be
# a rename in service of a caption. Only the printed word changes.
#
#   Info   -> Reference   a number we took, with no pass/fail threshold behind
#                         it. 727 backlinks is neither good nor bad.
#   Manual -> In review   no verdict yet, because a person reaches it during
#                         the engagement.
#
# NOT "Measured" for Info, which was the first choice: the coverage strip two
# pages earlier already labels a segment "Measured", meaning every check we
# managed to answer. The same word for two different counts is worse than the
# jargon it replaced.
STATUS_LABEL = {"Info": "Reference", "Manual": "In review"}
for _raw, _shown in STATUS_LABEL.items():
    STATUS_PILL[_shown] = STATUS_PILL[_raw]


def _status_word(status: str) -> str:
    return STATUS_LABEL.get(status, status)


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


BUBBLE_BG = colors.HexColor("#E6F0F7")     # Velocity Blue at 10%
BUBBLE_EDGE = colors.HexColor("#C2DAEC")


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


def _bubbles_for(text, S, seen, width=6.55 * inch, indent=0.0, limit=2,
                 only=None):
    """
    Definition bubbles for jargon in `text` that has not been defined yet.

    `seen` is mutated. A term is explained ONCE, at its first appearance — the
    same word defined on four pages is the tell of a document assembled rather
    than written.

    `only` restricts the candidates. The Canonicalization section printed a
    definition of *indexing*, because "canonical" had already been defined
    earlier in the document and the next unused term that happened to appear in
    a row ("Canonicals point to indexable pages") won by default. A definition
    that has nothing to do with the heading above it is worse than no
    definition, so a section passes the terms its own subject licenses and
    prints nothing when they are spent.
    """
    from .glossary import terms_used, entry
    out = []
    for key in terms_used(text, limit=99):
        if only is not None and key not in only:
            continue
        if key in seen or len(out) >= limit:
            continue
        seen.add(key)
        e = entry(key, medium="pdf")
        out.append(_bubble(e["name"], e["definition"], e["icon"], S, width, indent))
    return out


SEVERITY_LEGEND = [
    ("Critical", "Stops the site being found or indexed, creates real risk, or "
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
    return ", ".join(got) if got else "None — public data only"



def _ai_visibility(meta, S):
    """
    What AI assistants say when asked about this client.

    Two numbers that look similar and are not: MENTIONED means the brand name
    appeared in the answer; CITED means the assistant linked to the site as a
    source. Only the second one sends traffic and only the second one is
    defensible, so they are printed side by side with the gap called out.
    """
    v = (meta.get("extras") or {}).get("ai_visibility") or {}
    if not v or v.get("citation_rate") is None:
        return []
    out = [Paragraph("AI Search Visibility", S["h2"]),
           _rule(),
           Paragraph("Measured by asking the assistants real buying questions "
                     "in your category and recording what came back. No brand "
                     "name in the question — this is what someone finds when "
                     "they are not already looking for you.", S["small"]),
           Spacer(1, 8)]

    cite = v.get("citation_rate") or 0
    ment = v.get("mention_rate") or 0
    unp = v.get("unprompted_citation_rate")
    tiles = Table([[
        Paragraph(f"<font size=20><b>{cite}%</b></font><br/>"
                  f"<font size=8 color='#52514e'>of answers CITED your site "
                  f"as a source</font>", S["cellsm"]),
        Paragraph(f"<font size=20><b>{ment}%</b></font><br/>"
                  f"<font size=8 color='#52514e'>mentioned the brand without "
                  f"linking to you</font>", S["cellsm"]),
        Paragraph(f"<font size=20><b>{v.get('client_citations') or 0}</b></font><br/>"
                  f"<font size=8 color='#52514e'>total citations across "
                  f"{len(v.get('platforms') or [])} platforms</font>", S["cellsm"]),
    ]], colWidths=[2.18 * inch, 2.18 * inch, 2.18 * inch])
    tiles.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ("ROUNDEDCORNERS", [9, 9, 9, 9]),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 11), ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    out.append(tiles)

    if ment > cite:
        out.append(Spacer(1, 8))
        out.append(_banner("", f"Mentioned is not cited. Assistants named you in "
                               f"{ment}% of answers but linked to you in only "
                               f"{cite}% — the gap is visibility you are already "
                               f"earning and not being credited for.", SEQ, S))

    sov = v.get("share_of_voice") or []
    if sov:
        out.append(Spacer(1, 12))
        out.append(Paragraph("Who gets cited in your category", S["h3"]))
        rows = [[Paragraph("<b>Domain</b>", S["cellsm"]), "",
                 Paragraph("<b>Share</b>", S["cellsm"]),
                 Paragraph("<b>Citations</b>", S["cellsm"])]]
        for d in sov:
            is_client = bool(d.get("is_client"))
            name = _p(d.get("domain"))
            rows.append([
                Paragraph(f"<b>{name}</b>" if is_client else name, S["cell"]),
                MiniMeter(round((d.get("share") or 0) * 100)
                          if (d.get("share") or 0) <= 1 else d.get("share"),
                          width=1.9 * inch, height=7),
                Paragraph(f"{round((d.get('share') or 0) * 100)}%"
                          if (d.get("share") or 0) <= 1
                          else f"{d.get('share')}%", S["cellsm"]),
                Paragraph(str(d.get("citations") or 0), S["cellsm"]),
            ])
        t = Table(rows, colWidths=[2.3 * inch, 2.1 * inch, 0.9 * inch, 1.25 * inch])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 3)]))
        out.append(t)
        gap = v.get("citation_gap")
        if gap and v.get("top_competitor_domain"):
            out.append(Spacer(1, 6))
            out.append(Paragraph(
                f"<font color='#52514e'>{_p(v['top_competitor_domain'])} is cited "
                f"{gap} more times than you across the same questions.</font>",
                S["small"]))

    # WHICH PLATFORMS WE DO NOT PAY FOR IS NOT THE CLIENT'S BUSINESS.
    #
    # "Not measured: perplexity, chatgpt, copilot" named our tooling gaps in
    # their report and invited the question "so why not?", which has no answer
    # that helps them. The platforms we DID measure are named beside every
    # number above; that is the honest scope statement.
    return out


# What each area IS, in one line, for the strengths cards. Deliberately not the
# glossary: those definitions explain a TERM the reader just met in a finding,
# and these explain an AREA that came back clean, which is a different job and
# a different length.
SECTION_MEANS = {
    "ANA": "whether the tracking on the site actually records what it should",
    "GSC": "what Google's own Search Console reports about the site",
    "GA4": "whether Google Analytics is set up to answer real questions",
    "TECH": "the plumbing search engines use to find and read pages",
    "URL": "whether addresses are readable and organized by topic",
    "SEC": "whether the site is served securely end to end",
    "CANON": "whether Google can tell which version of a page is the real one",
    "PERF": "how fast the site feels to a real visitor on a real phone",
    "ONP": "titles, headings and copy — what a page says it is about",
    "MOB": "how the site behaves on a phone, which is most of the traffic",
    "SCHEMA": "the machine-readable labels that produce rich search results",
    "INTL": "whether the right language and region version is served",
    "HTML": "whether the code is clean enough not to get in its own way",
    "EEAT": "the signals that show a real, qualified business is behind the site",
    "GEO": "whether AI assistants can read the site and cite it",
    "OFF": "who links to the site, and what that says about its authority",
    "CONS": "whether tracking waits for consent, which is a legal question",
}


def _strength(text, S):
    """One strength as a card, with a plain-English line about the area."""
    from .report import SECTION_NAMES as _SN
    low = (text or "").lower()
    means = []
    for code, name in _SN.items():
        if name.lower() in low and SECTION_MEANS.get(code):
            means.append(SECTION_MEANS[code])
        if len(means) == 2:
            break
    gloss = ""
    if means:
        gloss = means[0] if len(means) == 1 else f"{means[0]}; {means[1]}"
        gloss = gloss[0].upper() + gloss[1:] + "."

    inner = [Paragraph(_p(text), S["cell"])]
    if gloss:
        inner.append(Spacer(1, 3))
        inner.append(Paragraph(
            f"<font color='#4A5461'>{_p(gloss)}</font>", S["cellsm"]))
    t = Table([[inner]], colWidths=[6.55 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F7F4")),
        ("ROUNDEDCORNERS", [10, 10, 10, 10]),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, colors.HexColor("#1E7A45")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 13),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    return KeepTogether([t, Spacer(1, 7)])


def _market_pills(raw, S):
    """
    One rounded chip per market, wrapped across the cell.

    Returns a flowable, so `_kv_table` has to accept something other than a
    Paragraph in the value column — which it now does.
    """
    try:
        from .geo import split_markets
        items = split_markets(raw)
    except Exception:  # noqa: BLE001
        items = [x.strip() for x in str(raw or "").split(",") if x.strip()]
    if not items:
        return Paragraph(_p(raw), S["cellsm"])

    st = ParagraphStyle("mk", parent=S["cellsm"], fontSize=7.5, leading=9.5,
                        textColor=colors.HexColor("#002D58"), alignment=1)
    chips = []
    for m in items[:40]:
        t = Table([[Paragraph(_p(m), st)]])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E6EAEE")),
            ("ROUNDEDCORNERS", [5, 5, 5, 5]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        chips.append(t)

    # Four to a row: thirteen Tennessee counties at 4.9in is about the widest
    # a name gets before it has to wrap inside its own chip.
    per = 4
    rows = [chips[i:i + per] for i in range(0, len(chips), per)]
    for r in rows:
        while len(r) < per:
            r.append("")
    grid = Table(rows, colWidths=[4.9 * inch / per] * per)
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return grid


def _evidence(meta, S):
    """Annotated screenshots — the problem, in a picture, on their own site."""
    shots = (meta.get("extras") or {}).get("screenshot_blobs") or []
    if not shots:
        return []
    from reportlab.platypus import Image as RLImage
    out = [Paragraph("What This Looks Like", S["h2"]),
           _rule(),
           # WAS: "Captured from your live site. Red outlines mark the
           # elements the check flagged." Two problems: it described our
           # process rather than their site, and it promised outlines that
           # only some findings have — an HTTPS failure has nothing on the
           # page to outline, so the reader hunts for a mark that was never
           # drawn.
           Paragraph("Your homepage as it loaded, with anything the check "
                     "flagged marked in red.", S["small"]),
           Spacer(1, 8)]
    for sh in shots[:3]:
        try:
            img = RLImage(io.BytesIO(sh["png"]), width=6.4 * inch,
                          height=6.4 * inch * 820 / 1280, kind="proportional")
        except Exception:
            continue
        cap = Paragraph(f"<font color='#52514e'>{_p(sh.get('caption'))}</font>",
                        S["muted"])
        out.append(KeepTogether([img, Spacer(1, 3), cap, Spacer(1, 14)]))
    return out


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
    (measured, need_client_access, ours_to_complete, not_applicable) across the
    WHOLE catalog.

    Catalog rows we never returned a finding for are counted, not silently
    absent — an audit that quietly skips 58 rows and shows full coverage is the
    failure mode this chart exists to make impossible. What changed is that
    they are no longer all filed under the client: see engine/access.py for the
    three-way split and why it matters.
    """
    from engine.access import counts
    c = counts(findings, catalog)
    return (c["measured"], c["client"], c["vendor"] + c["manual"], c["na"])


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
    story.append(Paragraph("Comprehensive SEO &amp; AI Search Audit",
                           S["h1"]))
    # The cover's rule is the widest one in the document and the only one that
    # runs the full measure. Every later section gets a short version of the
    # same mark, so the reader learns it here.
    story.append(GradRule(width=6.6 * inch, height=4.0, space_after=2,
                          space_before=8))
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
        # PILLS, NOT THE PASTED STRING.
        #
        # Thirteen counties arrive exactly as they were typed into the form —
        # separated by the multiplication sign someone's spreadsheet used —
        # and print as a wall of text with "TN" thirteen times. The form shows
        # them as pills; the cover should too.
        facts.append(("Primary markets",
                      _market_pills(meta["primary_markets"], S)))
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
        from .context import describe_entities
        words = describe_entities(ctx["entity_types"])
        if words:
            facts.append(("Structured data found", words))
    if facts:
        story.append(Paragraph("Current Site Snapshot", S["h3"]))
        story.append(Spacer(1, 3))
        story.append(_kv_table(
            [[Paragraph(f"<b>{_p(k)}</b>", S["cellsm"]),
              v if hasattr(v, "wrap") else Paragraph(_p(v), S["cellsm"])]
             for k, v in facts],
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
            # The score needs no caption. "The average of the areas we could
            # score" explains a mechanism nobody asked about, in a voice that
            # apologises for the number — and it sat directly above the two
            # figures that actually matter.
            ("<b>No overall score.</b> We couldn't assess enough areas to give "
             "you a number worth quoting. The areas below still stand on their "
             "own.<br/><br/>"
             if o.get("score") is None else "")
            + f"<font size=15 color='#0b0b0b'><b>{open_issues}</b></font>"
              f"<font size=8.5 color='#52514e'> open issues, of which </font>"
              f"<font size=15 color='#0b0b0b'><b>{urgent}</b></font>"
              f"<font size=8.5 color='#52514e'> are Critical or High and should "
              f"be resolved within 30 days.</font>"
              # WAS: "We measured 269 of 322 checks directly." A client reads
              # that as a report that did not finish. The 53 it does not
              # mention are checks Google exposes through no API, plus the
              # ones that do not apply to this site — neither is a gap in the
              # work, and neither is explainable in half a sentence beside a
              # score. The Audit Coverage bar below says it properly, with a
              # legend that separates the two.
              ,
            S["small"])]],
        colWidths=[2.0 * inch, 4.6 * inch])
    hero.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    # A flush gradient cap on the panel. Untapered and full-measure, so it
    # reads as the panel's own top edge rather than as a rule floating above
    # it — the tapered version left a visible gap at the right-hand corner.
    story.append(GradRule(width=6.6 * inch, height=3.0, taper=False))
    story.append(hero)
    story.append(Spacer(1, 12))

    # ---- at a glance ----------------------------------------------------
    # The tile strip from the operator dashboard, which reads faster than any
    # of the charts under it: five whole numbers, no ratios to decode, the
    # shape of the whole audit in one line. It answers "how did we do" before
    # the reader has to interpret a bar.
    from collections import Counter as _C
    _st = _C(f.get("status") for f in findings.values())
    # "Need your access" came off this strip. It is an internal fact — a count
    # of what WE could not read — and putting it beside Passing and Failing
    # invited the client to read it as a fifth score. The rows it counts still
    # say so individually, where the reader can see which check and why.
    tiles = [(_st.get("Pass", 0), "Passing"),
             (_st.get("Fail", 0) + _st.get("Not Implemented", 0), "Failing"),
             (_st.get("Warning", 0), "Worth a look"),
             (meta.get("pages_crawled") or 0, "Pages reviewed")]
    # A style of its own. Setting the size with an inline <font> tag leaves the
    # PARAGRAPH's leading at the 11pt the cell style carries, so 19pt digits
    # overflowed their row and the labels printed on top of the numbers.
    big = ParagraphStyle("glance", parent=S["cell"], fontSize=19, leading=21)
    # Separate rounded cards, one per number, the way the dashboard draws them.
    # The first attempt was one long box with hairlines between the tiles, on
    # the theory that five borders spend more ink on chrome than on numbers.
    # Next to the dashboard it just looked like a table that had lost its
    # header — the rounded card is what makes a figure read as a tile.
    def _tile(v, l):
        t = Table([[Paragraph(f"<b>{v}</b>", big)],
                   [Paragraph(f"<font size=7.5 color='#52514e'>{l}</font>",
                              S["cell"])]],
                  # 8pt of top padding plus 21pt of leading needs 0.41in; at
                  # 0.30 the label row drew straight through the digits.
                  rowHeights=[0.42 * inch, 0.20 * inch])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
            ("ROUNDEDCORNERS", [5, 5, 5, 5]),
            ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
            ("TOPPADDING", (0, 1), (-1, 1), 0),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ]))
        return t

    # Widths in INCHES until the final multiply. Mixing the two — a gap already
    # converted to points, then multiplied by inch again — produced columns
    # wider than the frame and a negative available width inside a cell, which
    # reportlab reports as a TypeError from deep inside its own error handler.
    gap_in = 0.07
    w_in = (6.55 - gap_in * (len(tiles) - 1)) / len(tiles)
    cells, widths = [], []
    for i, (v, l) in enumerate(tiles):
        if i:
            cells.append("")
            widths.append(gap_in * inch)
        cells.append(_tile(v, l))
        widths.append(w_in * inch)
    glance = Table([cells], colWidths=widths)
    glance.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(glance)
    story.append(Spacer(1, 14))

    # ---- severity distribution + coverage, side by side -----------------
    left = [Paragraph("Issues by Severity", S["h3"]),
            SegmentBar(severity_segments(sev_counts), width=3.05 * inch,
                       note="Fix Critical and High first.")]
    right = [Paragraph("Audit Coverage", S["h3"]),
             SegmentBar(coverage_segments(*cov), width=3.05 * inch,
                        note="Unmeasured checks are left out of the score.")]
    grid = Table([[left, right]], colWidths=[3.3 * inch, 3.3 * inch])
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(grid)

    # ------------------------------------------------ executive summary
    # One definition per term, at first use, document-wide. Seeded here rather
    # than beside the findings because the summary is where the words first
    # appear.
    defined = set()
    if summary:
        story.append(Paragraph("Executive Summary", S["h2"]))
        story.append(_rule())
        if summary.get("overview"):
            story.append(Paragraph(_p(summary["overview"]), S["body"]))
        if summary.get("headline"):
            story.append(_banner("", summary["headline"], SEQ, S))
            story.append(Spacer(1, 8))
        # DEFINE AT FIRST MENTION, BLOCK BY BLOCK.
        #
        # "Canonicalization", "E-E-A-T", "Core Web Vitals" all get named in
        # these paragraphs, several pages before the findings that used to carry
        # their definitions. A term explained after the reader has already met
        # it twice is not help, it is an index.
        #
        # Per block rather than pooled, which is the fix for two faults at once.
        # Pooling the text of both paragraphs put the canonical definition
        # underneath the E-E-A-T paragraph, and it pulled in a definition of
        # structured data because the word appeared in the OVERVIEW — so the
        # reader got a definition for a term that is not in either paragraph
        # above it. Each block now defines only what it introduced, and does it
        # directly underneath itself.
        def _define(text, limit=3):
            for b in _bubbles_for(text, S, defined, width=6.55 * inch,
                                  limit=limit):
                story.append(b)
                story.append(Spacer(1, 5))

        if summary.get("overview"):
            _define(str(summary["overview"]), limit=2)
        for key, title in (("working", "Current Strengths"),
                           ("opportunity", "Biggest Opportunity")):
            items = summary.get(key)
            if not items:
                continue
            story.append(Paragraph(title, S["h3"]))
            block = []
            if isinstance(items, str):
                story.append(Paragraph(_p(items), S["body"]))
                block.append(items)
            elif key == "working":
                # STRENGTHS AS CARDS, EACH SAYING WHAT THE AREA IS.
                #
                # "Canonicalization, International SEO and Mobile SEO came back
                # clean" is true and lands on a client who does not know what
                # canonicalization is — so the good news reads as jargon and
                # gets skipped, which is a waste of the one section that is
                # not asking them for anything.
                for it in items:
                    story.append(_strength(it, S))
                    block.append(it)
            else:
                # Short lists read better as prose than as bullets; a bulleted
                # list of two items looks like a form that was filled in.
                for it in items:
                    story.append(Paragraph(_p(it), S["body"]))
                    block.append(str(it))
            if block:
                _define(" ".join(block))

    # ------------------------------------------------ the five things
    five = (summary or {}).get("five_things") or []
    if five:
        story.append(Spacer(1, 6))
        # No subline. The heading says what this is, the numbering says it is
        # ordered, and a sentence explaining both reads like filler written to
        # occupy the space under a header.
        story.append(Paragraph("Top Findings", S["h2"]))
        story.append(_rule())
        story.append(Spacer(1, 8))
        for i, t in enumerate(five, start=1):
            block = [Paragraph(f"{i}. {_p(t.get('title'))}", S["h3"])]
            # Severity as a pill, matching the appendix and the legend. As grey
            # run-in text it was the same weight as "effort: content, ongoing",
            # so the one word a reader scans for read as a caption.
            rest = " · ".join(x for x in (
                _p(t.get("area")),
                (f"effort: {_p(t['effort'])}" if t.get("effort") else "")) if x)
            sev = _p(t.get("severity"))
            if sev:
                mrow = Table([[_pill(sev, SEV_PILL, S, 0.62 * inch),
                               Paragraph(f"<font color='#898781'>{rest}</font>",
                                         S["muted"])]],
                             colWidths=[0.68 * inch, 5.9 * inch])
                mrow.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (0, 0), 0),
                    ("LEFTPADDING", (1, 0), (1, 0), 2),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
                block.append(mrow)
            elif rest:
                block.append(Paragraph(f"<font color='#898781'>{rest}</font>",
                                       S["muted"]))
            block.append(Spacer(1, 4))
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

    for fl in _evidence(meta, S):
        story.append(fl)

    # ------------------------------------------------ area snapshot
    # No forced page break here: the exec summary rarely fills a page, and a
    # break left a third of page 2 blank. KeepTogether keeps the chart intact.
    story.append(Spacer(1, 6))
    story.append(Paragraph("Scores by Area", S["h2"]))
    story.append(_rule())

    secs = [(k, v) for k in ORDER if (v := (scores.get("sections") or {}).get(k))]
    # Ranked worst-first: the reader should not have to scan a table to find
    # where the work is. Unassessed areas sort last — they are not "worst".
    ranked = sorted(secs, key=lambda kv: (kv[1].get("score") is None,
                                          kv[1].get("score") if kv[1].get("score")
                                          is not None else 0))
    story.append(Paragraph(
        "Ordered by severity, with the areas to fix first at the top.",
        S["small"]))
    story.append(Spacer(1, 8))
    story.append(KeepTogether(
        SectionBars([(SHORT_NAMES.get(k, SECTION_NAMES[k]), v.get("score"),
                      v.get("rating")) for k, v in ranked], width=6.55 * inch)))
    story.append(Spacer(1, 16))

    story.append(Paragraph("Score by Area", S["h3"]))
    # "Checked" and "Failing" are two different denominators sitting next to
    # each other with no explanation: 4/12 is "we answered 4 of the 12 in this
    # area", and the 2 beside it is "2 of those 4 came back a problem". Read
    # quickly, "4/12 ... 2" looks like one ratio. Name both, and say so.
    # THE "REVIEWED x/y" COLUMN IS GONE.
    #
    # It went through three rewrites — a corrected numerator, a corrected
    # denominator, then a caption explaining where the difference went — and it
    # still read as "you did not finish". That is the column's fault, not the
    # reader's. A ratio next to a rating invites "why not all of them?" on every
    # single row, and answering that question is what the coverage strip above
    # is FOR: it splits the whole audit into measured, waiting on you, ours to
    # complete, and not applicable, once, where it can be understood.
    #
    # What was left after removing it is what a reader actually wants from this
    # table: how did each area score, and how many problems are in it.
    story.append(Paragraph(
        "How each area scored, worst first. <b>Issues</b> is the number of "
        "checks in that area that came back a problem.", S["small"]))
    story.append(Spacer(1, 6))
    rows = [[Paragraph("<b>Section</b>", S["cellsm"]),
             Paragraph("<b>Score</b>", S["cellsm"]),
             "", Paragraph("<b>Rating</b>", S["cellsm"]),
             Paragraph("<b>Issues</b>", S["cellsm"])]]
    for k, v in secs:
        sc = v.get("score")
        rows.append([
            Paragraph(SECTION_NAMES[k], S["cell"]),
            Paragraph("—" if sc is None else f"<b>{sc}</b>", S["cell"]),
            MiniMeter(sc) if sc is not None else "",
            Paragraph(_p(v.get("rating")), S["cell"]),
            Paragraph(str(v.get("failing", 0)), S["cellsm"]),
        ])
    # Five columns now, not six. The width the Reviewed ratio was using goes to
    # the meter, which is the part of this table that actually communicates.
    t = Table(rows, colWidths=[2.3 * inch, 0.5 * inch, 1.85 * inch,
                               1.35 * inch, 0.5 * inch], repeatRows=1)
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
    # The dedupe was wired only to the appendix, so this table — which is on
    # page 3, where a client is still reading — printed "83 pages share 25
    # duplicated title tags" twice in a row, under ONP-23 and again under
    # ONP-01. One measurement answers both checkpoints; saying so once and
    # cross-referencing is shorter and more useful than saying it twice.
    issues = _dedupe_evidence(issues)
    if issues:
        story.append(Paragraph("Priority Issues", S["h2"]))
        story.append(_rule())
        rows = [[Paragraph("<b>ID</b>", S["cellsm"]),
                 Paragraph("<b>Checkpoint</b>", S["cellsm"]),
                 Paragraph("<b>Severity</b>", S["cellsm"]),
                 Paragraph("<b>What we found</b>", S["cellsm"])]]
        for cid, f in issues:
            m = catalog.get(cid, {})
            rows.append([Paragraph(cid, S["cellsm"]),
                         Paragraph(_p(m.get("checkpoint")), S["cell"]),
                         _pill(f.get("severity"), SEV_PILL, S, 0.66 * inch),
                         Paragraph(_agree(_p(f.get("evidence"))), S["cell"])])
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
        story.append(_rule())
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
        story.append(_rule())
        story.append(Paragraph(
            f"Not collected — {_p(rk.get('reason'))}. This section is omitted rather "
            f"than estimated.", S["small"]))

    ai_block = _ai_visibility(meta, S)
    if ai_block:
        story.append(PageBreak())
        for fl in ai_block:
            story.append(fl)

    # ------------------------------------------------ roadmap
    if summary and summary.get("roadmap"):
        story.append(PageBreak())
        story.append(Paragraph("Our Recommended Plan", S["h2"]))
        story.append(_rule())
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
                # Indented to the phase NAME, not to the page margin.
                #
                # The header is a table whose first column is the 0.72in "Phase
                # 2" chip, so a paragraph starting at x=0 begins underneath the
                # chip and hangs to the left of both the title above it and the
                # card below it — the one element on the block not lined up
                # with anything. It is a caption for the title; it should start
                # where the title starts.
                mid = ParagraphStyle("phasecap", parent=S["small"],
                                     textColor=INK2, leftIndent=0.72 * inch)
                block.append(Paragraph(_p(phase["rationale"]), mid))
            block.append(Spacer(1, 5))

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
    story.append(_rule())
    n_na = sum(1 for f in findings.values() if f.get("status") == "N/A")
    story.append(Paragraph(
        "By area. <b>Reference</b> is a number with no pass or fail attached to "
        "it — a backlink count is neither good nor bad on its own. "
        "<b>In review</b> means an analyst reaches that check during the "
        "engagement, so it has no verdict yet. <b>Need Access</b> means the "
        "check is waiting on access to your Search Console or Analytics."
        + (f" {n_na} checks that don't apply to a site like yours are left out."
           if n_na else ""), S["small"]))

    for k in ORDER:
        # N/A rows are dropped. A page of "Meta Pixel · N/A · Not detected."
        # tells a client nothing they can use — it is the template asking a
        # question that does not apply to them, and the honest thing is to say
        # how many were skipped rather than to print them all. The count is in
        # the line above and in the coverage strip; the rows themselves stay in
        # the findings API for us.
        rows_f = [(cid, f) for cid, f in findings.items()
                  if (catalog.get(cid, {}) or {}).get("prefix") == k
                  and f.get("status") != "N/A"]
        rows_f += _synthetic_rows(catalog, findings, k)
        if not rows_f:
            continue
        rows_f.sort(key=lambda r: (STATUS_ORDER.index(r[1]["status"])
                                   if r[1]["status"] in STATUS_ORDER else 9, r[0]))
        rows_f = _dedupe_evidence(rows_f)
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
            # THE LAMP GOES NEXT TO THE ID, NOT NEXT TO THE NAME.
            #
            # It was in the Check column, in a nested table whose first cell was
            # a fixed 1.55 inches — so on a short checkpoint name the lamp sat
            # an inch and a half away from the text, floating in white space
            # between two columns and reading as belonging to neither. Against
            # the ID it lands in a tidy vertical column, unmistakably attached
            # to its row, which is what makes it scannable.
            ident = Paragraph(cid, S["cellsm"])
            if _judged(cid, f.get("status")):
                ident = Table([[ident, Lamp(size=7)]],
                              colWidths=[0.46 * inch, 0.15 * inch])
                ident.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (1, 0), (1, 0), 1),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
            data.append([ident,
                         Paragraph(_p(m.get("checkpoint")), S["cell"]),
                         _pill(_status_word(f["status"]), STATUS_PILL, S,
                               0.86 * inch),
                         Paragraph(_agree(_p(f.get("evidence"))), S["cell"])])
        t = Table(data, colWidths=[0.72 * inch, 1.68 * inch, 0.95 * inch, 3.15 * inch],
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
        from .glossary import terms_used as _tu
        section_terms = set(_tu(SECTION_NAMES[k], limit=99))
        for b in _bubbles_for(
                SECTION_NAMES[k] + " " + " ".join(
                    (catalog.get(cid, {}) or {}).get("checkpoint", "")
                    for cid, _f in rows_f[:12]),
                S, defined, width=6.55 * inch, limit=1,
                only=section_terms or None):
            story.append(b)
            story.append(Spacer(1, 5))
        story.append(t)

    # ------------------------------------------------ method & sign-off
    story.append(PageBreak())
    # No subtitle. The heading is the explanation; a sentence under it saying
    # the section explains things is filler.
    story.append(Paragraph("Methodology & Data Sources", S["h2"]))
    story.append(_rule())
    story.append(Spacer(1, 8))

    # Severity legend — lifted from the template's own scoring key, because a
    # reader who does not know what "High" means cannot act on the roadmap.
    story.append(Paragraph("How to read the ratings", S["h3"]))
    leg = [[Paragraph("<b>Severity</b>", S["cellsm"]),
            Paragraph("<b>What it means</b>", S["cellsm"]),
            Paragraph("<b>Score</b>", S["cellsm"]),
            Paragraph("<b>Area rating</b>", S["cellsm"])]]
    for sev, definition, rng, rating in SEVERITY_LEGEND:
        # The pill, not a painted cell. A TEXTCOLOR command on a table cell
        # does NOT override the textColor a Paragraph carries in its own style,
        # so "Critical" kept painting itself dark grey on top of dark navy and
        # came out unreadable. The pill decides its own contrast per level, and
        # a legend that draws the same component it is explaining is the point.
        leg.append([_pill(sev, SEV_PILL, S, 0.78 * inch),
                    Paragraph(_p(definition), S["cellsm"]),
                    Paragraph(_p(rng), S["cellsm"]),
                    Paragraph(_p(rating), S["cellsm"])])
    lt = Table(leg, colWidths=[0.85 * inch, 3.5 * inch, 0.7 * inch, 1.55 * inch])
    lst = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
           ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
           ("TOPPADDING", (0, 0), (-1, -1), 5),
           ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
           ("LEFTPADDING", (0, 0), (-1, -1), 3)]
    lt.setStyle(TableStyle(lst))
    story.append(lt)
    story.append(Spacer(1, 14))

    m, need_client, ours, na = _coverage_counts(findings, catalog)
    method = [
        ("Collection",
         "Pages were opened in a real browser and the rendered page was read, "
         "because the site would not serve them to a standard request."
         if meta.get("capture_method") else
         f"{_p(meta.get('pages_crawled'))} pages reviewed from "
         f"{_p(meta.get('url'))}, following internal links and the XML sitemap."),
        ("Framework",
         f"{len(catalog)} checkpoints across {len(SECTION_NAMES)} areas, covering "
         f"technical SEO, on-page, structured data, performance, security, "
         f"E-E-A-T and generative-engine visibility."),
        ("What we measured", f"{m} checks answered from your live site plus "
                             f"third-party data."),
        ("What we need from you",
         f"{need_client} checks read from Search Console and Analytics, which "
         f"we cannot see without a read-only grant. They are left out of the "
         f"scoring rather than counted against you, and they are the only "
         f"thing on this list that needs anything from your side."
         if need_client else
         "Nothing — every check that depends on your accounts was answered."),
        # Two faults in the old wording. It said "crawler", which does not
        # belong in a client document, and it left the reader unsure whether
        # any of it was theirs to do. Nothing on this line is.
        ("What we complete during the engagement",
         f"{ours} checks we finish ourselves. Nothing needed from you."),
        # AN EXAMPLE, NOT A CATEGORY. "Checks that don't apply to a site built
        # like yours" is true of any number and tells the reader nothing about
        # which checks or why, so it reads as padding on a count they cannot
        # verify.
        ("Not applicable",
         f"{na} checks are for things this site does not do - product and "
         f"review markup on a site that sells nothing online, language "
         f"targeting on a site published only in English. They are left out "
         f"rather than failed."),
        ("Scoring", "Each area scores out of 100 from the checks we could run, "
                    "weighted by severity. If there wasn't enough to go on, the "
                    "area is marked Not Assessed instead of scored low."),
    ]
    if meta.get("truncated"):
        method.append(("Coverage limit",
                       _p(meta["truncated"]) + ". Sitewide counts describe the "
                       "pages we reached, not the whole site."))
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
