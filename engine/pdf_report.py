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
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Flowable,
                                Frame, PageBreak, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle, KeepTogether)

from .charts import (ScoreGauge, SectionBars, SegmentBar, MiniMeter, GradRule,
                     DefBadge, Lamp, severity_segments, coverage_segments)
# The MODULE, never `from .fonts import BODY`. The names on it are rebound by
# register(); a copy taken at import time is a copy of "Helvetica".
from . import fonts as _fonts
from . import redact as _redact

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
# Star glyphs are colored by what the band MEANS, not by "stars are gold":
# one and two stars are the complaint, three is the lukewarm middle, and the
# profile average is the number that is working.
_STAR_BAD  = "#A6192E"
_STAR_MEH  = "#8A5A00"
_STAR_GOOD = "#1E7A45"


def _inline(*flowables, gap=3):
    """Lay flowables out side by side inside one table cell."""
    row = list(flowables)
    t = Table([row], colWidths=[None] * len(row))
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("LEFTPADDING", (1, 0), (-1, 0), gap),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    t.hAlign = "LEFT"
    return t


def _star_row(n, color, size=7.0):
    """
    n stars, DRAWN.

    U+2605 is not in the embedded family, so "★" printed as nothing at all -
    the column headers came out blank and the profile figure lost its star.
    Exactly the same trap as the magnifier emoji, and the same answer: draw
    the shape rather than hoping a glyph exists. reportlab renders a Polygon
    at any size in any font, which also means the stars stay the right weight
    next to 7.5pt text.
    """
    from reportlab.graphics.shapes import Drawing, Polygon
    import math
    gap = size * 1.18
    d = Drawing(max(1.0, gap * n), size + 1)
    c = color if isinstance(color, colors.Color) else colors.HexColor(color)
    r_out, r_in = size / 2.0, size / 4.6
    for i in range(n):
        cx, cy = gap * i + r_out, size / 2.0 + 0.5
        pts = []
        for k in range(10):
            ang = math.pi / 2 + k * math.pi / 5
            rad = r_out if k % 2 == 0 else r_in
            pts += [cx + rad * math.cos(ang), cy + rad * math.sin(ang)]
        d.add(Polygon(pts, fillColor=c, strokeColor=None))
    return d
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
        # PRINT IT AGAIN, WITH A POINTER — NOT A POINTER INSTEAD OF IT.
        #
        # "Same finding as ONP-01." saved four lines and cost the reader a
        # page-flip to find out what ONP-01 said. In an appendix nobody reads
        # front to back, a cross-reference is a dead end: the row they landed
        # on is the row they care about.
        #
        # The repetition IS the point — it is the same problem showing up
        # under several checks — so the sentence stays and the pointer moves
        # to the end where it adds context instead of replacing it.
        if ratio >= 0.93:
            f = {**f, "evidence": f"{ev} (Also reported under {best}.)"}
        elif ratio >= 0.72 and best:
            prev = next(p for p in seen if p[0] == best)[2]
            tail = _distinct_tail(prev, ev)
            f = {**f, "evidence": (f"{ev} (Related to {best}.)" if tail
                                   else f"{ev} (Also reported under {best}.)")}
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


def _pl(text):
    """
    Escaped, redacted AND linkified: what every piece of running prose uses.

    The redaction runs HERE, at render, not only in the collector that wrote
    the string. Findings are stored and the PDF renders fresh from the store,
    so a report produced last week still carries last week's wording - which
    is how a client read "the middle sections are omitted from the material"
    and a list of our demand-side platforms in the same document, both from
    code that had already been fixed. See engine/redact.py.

    `_linkify` was applied at three call sites out of a dozen, so the same
    URL printed as a clickable path in Top Findings and as forty characters
    of raw address in the appendix two pages later. One helper, used
    everywhere text from a finding reaches a Paragraph.

    Not folded into `_p` because `_p` also renders the cover's Website row and
    the methodology line, where the whole point is to print the domain.
    """
    return _linkify(_p(_redact.client(text)))


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


_URL_RE = __import__("re").compile(r"\(?(https?://[^\s<>)\]]+)\)?")


def _linkify(text: str) -> str:
    """
    Replace printed URLs with a short clickable label.

    "The Family Law page (https://ootenlawfirm.com/practice-areas/family-law/),
    Criminal Defense page (https://ootenlawfirm.com/practice-areas/criminal-
    defense/), and DUI page (https://ootenlawfirm.com/practice-areas/dui/)" is
    four lines, three of them machine-readable rather than human-readable, in
    a paragraph whose actual finding is the last clause.

    The URL is not deleted - it becomes the path, underlined and clickable, so
    the reader can still see WHICH page and still get there. The host is
    dropped because every one of these is the client's own site and they know
    what their domain is.

    Runs AFTER escaping, so the text is already safe; the link target has to
    be escaped separately for the attribute.
    """
    def rep(m):
        url = m.group(1).rstrip(".,;")
        try:
            from urllib.parse import urlparse
            u = urlparse(url)
            # A bare domain has no path worth printing. "/" as a link label is
            # not a shorter way of saying anything, so the host stands in.
            path = u.path if u.path not in ("", "/") else (u.netloc or url)
        except Exception:  # noqa: BLE001
            path = url
        label = path if len(path) <= 42 else path[:39] + "..."
        return (f'<link href="{_h.escape(url, quote=True)}" '
                f'color="#0066B3"><u>{_h.escape(label)}</u></link>')
    return _URL_RE.sub(rep, text or "")


def _keep_headings_with_content(story, S):
    """
    Never leave a heading alone at the foot of a page.

    "Top Findings" printed at the top of one page with its first finding on
    the next - the heading, its rule, and eight inches of nothing.

    Two ways to fix that, and only one of them is safe. `KeepTogether([heading,
    next])` binds the heading to whatever follows, which is right until the
    thing following is a table taller than a page: then reportlab breaks to a
    new page, still cannot fit it, and you have spent a blank page to change
    nothing.

    `CondPageBreak` asks a smaller question - "is there at least this much room
    left?" - and only breaks when the answer is no. It cannot loop, it cannot
    strand a table, and it is enough: a heading with two inches of space under
    it always has its first line of content with it.
    """
    heads = {id(S[k]) for k in ("h1", "h2", "h3") if k in S}
    out = []
    for f in story:
        if isinstance(f, Paragraph) and id(getattr(f, "style", None)) in heads:
            # h1 opens a section and gets more room than an h3 sub-head.
            need = 2.1 if id(f.style) == id(S.get("h2")) else 1.5
            out.append(CondPageBreak(need * inch))
        out.append(f)
    return out


def _styles():
    # HEADLINES AND BODY ARE DIFFERENT FACES.
    #
    # Agdasima for headlines, GT Walsheim Pro for body copy — the brand book's
    # own pairing. `register()` falls back per family, so a document can end up
    # with brand headlines over Roboto body copy if only one set of files is
    # installed, which is a good deal better than losing both.
    #
    # Read AFTER register() on purpose: these are module-level names that
    # register() rebinds, so `from .fonts import BODY` anywhere would capture
    # "Helvetica" before the fonts loaded. The module itself is imported at the
    # top of this file; only the values are taken here.
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
        # ONE MEASURE FOR THE WHOLE DOCUMENT.
        #
        # The margins were 0.72in, giving a 7.06in frame, while every table,
        # panel and chart in here is built at 6.6in. reportlab centers a table
        # narrower than its frame, so headings, rules and body copy hung from
        # the left margin and everything in a table sat 0.23in to the right of
        # them - including the gradient cap on the score panel, which is drawn
        # as a flowable and therefore did NOT move, so it overhung the panel it
        # is supposed to be the top edge of.
        #
        # Matching the margin to the content measure fixes all of it at once
        # and needs no per-table alignment: 8.5 - 6.6 = 1.9, half each side.
        super().__init__(buf, pagesize=LETTER,
                         leftMargin=0.95 * inch, rightMargin=0.95 * inch,
                         topMargin=0.62 * inch, bottomMargin=0.72 * inch, **kw)
        self.meta = meta
        # THE FRAME'S OWN PADDING WAS THE MISALIGNMENT.
        #
        # reportlab's Frame defaults to 6pt of padding on every side. So the
        # text column started 6pt inside the margin - headings, rules, body
        # copy - while every full-measure table in here is built at exactly
        # 6.6in, which is 12pt WIDER than what the padded frame offers. A
        # table too wide for its frame is centered on the overflow, so each one
        # hung 6pt off the left and 6pt off the right of everything else.
        #
        # That is the "fix alignment" on the cover table, the severity pill
        # under each finding heading, and the gradient cap that looked wider
        # than the panel it caps. One number, three symptoms.
        frame = Frame(self.leftMargin, self.bottomMargin,
                      self.width, self.height, id="main",
                      leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="all", frames=[frame],
                                            onPage=self._chrome)])

    def _chrome(self, canvas, doc):
        canvas.saveState()
        # The footer is drawn straight onto the canvas, so it inherits no
        # paragraph style - and it was the one line of the document still
        # hard-coded to Helvetica, on every page, under copy set in the brand
        # face. Read the registered name at DRAW time, not at import.
        canvas.setFont(_fonts.BODY, 7.5)
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
    # Nothing was withheld and nothing is owed - see _status_word.
    "Not applicable":  (colors.HexColor("#F1F1F1"), colors.HexColor("#8096AC")),
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
# "NOT IMPLEMENTED" IS OUR WORD FOR AN EMPTY RESULT, NOT THEIRS.
#
# It reads as a note about software - "we have not built this yet" - on a row
# that means the opposite: we looked, and the thing the check is about is not
# on the site. "Missing" says that in a word a client already owns.
STATUS_LABEL = {"Info": "Reference", "Manual": "In review",
                "Not Implemented": "Missing"}
for _raw, _shown in STATUS_LABEL.items():
    STATUS_PILL[_shown] = STATUS_PILL[_raw]


# CONSENT IS A LEGAL QUESTION, AND "PASS" IS A LEGAL OPINION.
#
# Everywhere else in this report "Pass" means a measurement came back clean,
# and that is fine. On a consent row it reads as "you are compliant", which is
# a conclusion about liability that a scan of one browser, in one location, at
# one moment cannot support - and that we are not qualified to give.
#
# The measurement is unchanged and the scoring is unchanged; only the word a
# client reads is different. "No issue seen" says exactly what happened.
CONSENT_LABEL = {"Pass": "No issue seen"}


# NEED ACCESS MEANS THERE IS SOMETHING TO GRANT.
#
# Two consent rows came back "Need Access" and the client's question was the
# only sensible one: what access am I missing? None. The scan found no consent
# platform, so there was no banner to test and no Reject button to press -
# that is CONS-01's finding, restated, and nothing anybody can hand over
# changes it. Same for a check that does not apply to the states in scope.
#
# The status stays as it is (scoring already leaves these out); the WORD the
# client reads becomes the true one. Keyed on the source the collector
# recorded, so a report produced before this is relabelled on reload.
_NOTHING_TO_GRANT = {"consent_no_cmp", "consent_not_applicable",
                     "ai_platform_absent"}


def _status_word(status: str, cid: str = "", source: str = "") -> str:
    if status == "Need Access" and source in _NOTHING_TO_GRANT:
        return "Not applicable"
    if str(cid).upper().startswith("CONS-"):
        return CONSENT_LABEL.get(status, STATUS_LABEL.get(status, status))
    return STATUS_LABEL.get(status, status)


def _pill(label, palette, S, width=0.82 * inch):
    """A rounded, filled label. Color plus text, never color alone."""
    bg, fg = palette.get(label, (TRACK, INK2))
    st = ParagraphStyle("pill", parent=S["cellsm"], textColor=fg,
                        # Same reason as the footer: a literal font name here
                        # put every status pill in Helvetica.
                        fontName=_fonts.BOLD, fontSize=7.5, leading=9.5,
                        alignment=1)
    t = Table([[Paragraph(_p(label), st)]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    # HANG IT FROM THE LEFT EDGE, like the heading above it.
    #
    # A Table defaults to hAlign="CENTER", so a 0.62in pill in a 0.68in column
    # sat 3pt right of the margin - just far enough that the severity chip
    # under every finding heading looked nudged out of line with it.
    t.hAlign = "LEFT"
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


# ---------------------------------------------------------------------------
# CHECK NAMES THAT MEAN NOTHING TO THE PERSON PAYING FOR THE REPORT.
#
# "Semantic keywords" is a fine name for a checkpoint in our template and a
# closed door in an appendix a client reads. They asked, in exactly these
# words: what is the semantic keyword check?
#
# One line under the name, in the client's vocabulary. Only for the rows that
# actually need it - a gloss under "Pages have no viewport tag" would be
# noise, and glossing everything is how a table stops being scannable.
# What the red outline is actually around, per checkpoint. Mirrors
# engine/screenshots.SELECTORS - if a selector is added there, its plain-
# English name belongs here or the caption falls back to saying nothing.
MARK_LABEL = {
    "ONP-08": "every H1 heading on the page",
    "ONP-14": "the images with no alt text",
    "ONP-17": "the links with no words in them",
    "ONP-32": "every H1 heading on the page",
    "ONP-33": "the headings, in the order they appear",
    "ONP-42": "the images, whose filenames were checked",
    "ONP-44": "the images with no responsive versions",
    "ONP-45": "the images that load eagerly",
    "PERF-19": "the images checked for weight and format",
    "MOB-05": "the links and buttons, sized for a thumb",
    "MOB-06": "the body text, checked for legible size",
    "EEAT-05": "the footer, where trust signals live",
    "EEAT-06": "the footer, where trust signals live",
}


CHECK_MEANS = {
    "ONP-12": "Whether the page uses real headings and lists rather than "
              "styled text, which is how a machine reads its structure.",
    "ONP-34": "Whether the page answers what someone searching that term "
              "actually came for.",
    "ONP-36": "Whether the page covers the related words and subtopics people "
              "expect on that subject, not just the one phrase.",
    "ONP-37": "Whether the page shows who is behind it and why they would "
              "know - author, credentials, real detail.",
    "ONP-40": "Whether the page has been updated recently enough to be "
              "trusted on a subject that changes.",
    "ONP-47": "Whether links say where they go in their own words instead of "
              "\u201cclick here\u201d.",
    "ONP-50": "Whether the page cites anything outside itself - a statute, a "
              "standards body, a source worth checking.",
    "ONP-49": "Whether the page links out to anything at all, or only back "
              "into the site.",
    "EEAT-01": "Whether the writing shows the work was actually done, rather "
               "than described in general terms.",
    "EEAT-03": "Whether the page says something the competitors' pages do "
               "not.",
    "EEAT-04": "Whether the page reads as written by someone who does this "
               "for a living.",
    "EEAT-09": "Whether the site makes the case for the organization itself - "
               "history, memberships, recognition.",
    "EEAT-11": "How clearly and consistently the brand is presented across "
               "the site.",
    "GEO-11": "Whether the pages answer questions the way people ask them "
              "out loud.",
    "GEO-12": "Whether each page makes clear WHO and WHAT it is about, in "
              "terms a machine can match to a known thing.",
    "GEO-13": "Whether the business is connected to the entries Google "
              "already holds about it.",
    "GEO-14": "Whether related topics on the site are linked so the coverage "
              "reads as one body of work.",
    "GEO-15": "Whether there is anything on the site worth quoting.",
    "GEO-16": "Whether the site publishes figures of its own that exist "
              "nowhere else.",
    "GEO-20": "Whether the authors are identifiable as real, named people.",
    "GEO-21": "Whether the organization is identifiable as a real, named "
              "entity.",
    "GEO-22": "Whether the brand is legible to search engines and assistants "
              "as a single thing.",
    "OFF-05": "A third-party score for how much authority a domain carries. "
              "Useful as a trend, not as a target.",
    "OFF-06": "Another vendor's version of the same idea.",
    "OFF-15": "Links that use the brand name as their wording.",
    "OFF-16": "Links whose wording is exactly the term being targeted - "
              "natural in small numbers, a flag in large ones.",
    "OFF-17": "Links that show a bare web address instead of words.",
}


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



def _ai_platforms(v) -> list:
    """
    The assistants we asked, named and de-duplicated.

    THE COUNT WAS THE LENGTH OF A STRING.
    #
    The tile read "across 48 assistants". `platforms` is stored as
    "ai_overview, chatgpt, claude, gemini, perplexity" - a string - and
    `len()` of a string is its character count. Five became forty-eight, in a
    client's report, under a number they are meant to trust.
    """
    plats = v.get("platforms")
    if isinstance(plats, str):
        names = [p.strip() for p in plats.split(",") if p.strip()]
    else:
        names = [str(p).strip() for p in (plats or []) if str(p).strip()]
    pretty = {"chatgpt": "ChatGPT", "claude": "Claude", "gemini": "Gemini",
              "perplexity": "Perplexity", "ai_overview": "Google AI Overviews",
              "copilot": "Copilot"}
    out = []
    for n in names:
        label = pretty.get(n.lower(), n.title())
        if label not in out:
            out.append(label)
    return out


def _ai_intro(v) -> str:
    """
    Say what was actually done, in the client's terms.

    WAS: "…questions someone would ask when they are looking for a business
    like yours and do not know your name. None of them named you." Two
    sentences, both wrong about the panel sitting underneath them: a third of
    the questions DO name the client on purpose (that is how you find out
    whether an assistant knows you exist at all), and three of those came back
    cited - so the paragraph contradicted its own table.
    """
    shown = _ai_platforms(v)
    who = (", ".join(shown[:-1]) + " and " + shown[-1]) if len(shown) > 1 \
        else (shown[0] if shown else "the AI tools")
    n = v.get("questions") or 0
    # WAS "assistant", which is what the industry calls these and not what a
    # client calls them. They are the things that now answer a search before
    # a list of links appears; "AI tools" needs no explaining and no glossary.
    # WHY THE NUMBER MOVES BETWEEN RUNS.
    #
    # "8 questions" one month and "21" the next, with nothing saying why, and
    # the obvious reading is that the tool is inconsistent. It is not: the
    # panel is built from what the site publishes - five about the business by
    # name, then a set for each service and each place it serves. A site with
    # three services and two towns gets more questions than one with one
    # service and no location pages, and that IS the right behavior. It just
    # has to be said, in the sentence that reports the count.
    return (f"We posed {n} questions to {who} and recorded, for each "
            f"answer, whether it named you and whether it linked to your "
            f"site. The set is built from your own site - a few about the "
            f"business by name, then one group per service and location it "
            f"publishes - so the count moves as the site does.")


def _asked_by_name(question, brand) -> bool:
    """
    Did this question hand the assistant the client's name?

    Derived from the text rather than read from a field, because the field
    (`prompted`) exists on the query and was never carried into the stored
    example - so every report already produced can be labelled correctly on
    the next render instead of after another paid run.
    """
    q = str(question or "").lower()
    b = str(brand or "").strip().lower()
    if not b:
        return False
    if b in q:
        return True
    # "The Ooten Law Firm" in the profile, "Ooten Law Firm" in the question.
    core = " ".join(w for w in b.split() if w not in ("the", "a", "an"))
    return bool(core) and core in q


def _ai_examples(v, S, brand=""):
    """
    The questions, the verdicts and what was actually said.

    A FOUR-COLUMN TABLE COULD NOT CARRY THIS.
    #
    Result / Question / How it was asked / Cited instead - four columns of
    which two were usually blank, and a reader who asked, fairly, "what are
    these saying, and what is cited versus not cited?" The answer to that is
    not another column. It is one block per question that reads as a sentence:
    what was asked, what came back, and the answer's own words.
    """
    _SHOW_FIRST = {"ai_overview": 0, "chatgpt": 1, "perplexity": 2,
                   "gemini": 3, "claude": 4, "copilot": 5}

    def _spread(items, n):
        """
        Different questions, not the same question three ways.

        THREE EXAMPLES ABOUT ONE SERVICE IS ONE EXAMPLE.
        #
        The misses came back as "Who should I hire for estate planning...",
        "How much does estate planning cost...", "Who is best for estate
        planning..." - the panel asks three shapes per service, so taking the
        first three in order takes one service three times. Worse, it made a
        side practice look like the firm's whole business.
        #
        Greedy, on the words the questions do not share. Cheap, and it cannot
        pick the same subject twice while a different one is available.
        """
        STOP = {"who", "what", "how", "much", "does", "is", "are", "the", "a",
                "an", "in", "for", "should", "i", "hire", "best", "good",
                "find", "cost", "do", "of", "to", "my", "me", "and", "with",
                "when", "choosing", "before", "look"}

        def words(x):
            import re as _re
            return {w for w in _re.findall(r"[a-z]+",
                                           str(x.get("question") or "").lower())
                    if w not in STOP and len(w) > 2}

        out, used = [], set()
        pool = list(items or [])
        while pool and len(out) < n:
            best, best_overlap = None, None
            for it in pool:
                overlap = len(words(it) & used)
                if best_overlap is None or overlap < best_overlap:
                    best, best_overlap = it, overlap
                if overlap == 0:
                    break
            out.append(best)
            used |= words(best)
            pool.remove(best)
        return out

    def _pref(items):
        # Google's AI answers and ChatGPT first - see the same list in
        # app/worker.py, which decides which examples get STORED. This orders
        # what a run already stored, so an audit from before that change also
        # leads with the tools the client has heard of.
        return sorted(items or [],
                      key=lambda x: _SHOW_FIRST.get(x.get("platform"), 9))

    # PERPLEXITY IS MEASURED, NOT SHOWN.
    #
    # It answers, it counts in every rate above, and as an EXAMPLE it costs
    # more than it pays: a client who has never opened it reads "Asked of
    # Perplexity" and asks why, which is a question about our tooling in the
    # middle of a section about their visibility.
    _NOT_SHOWN = {"perplexity", "claude"}
    def _shown(items):
        keep = [x for x in items
                if str(x.get("platform") or "").lower() not in _NOT_SHOWN]
        # Unless that leaves nothing - a run where only those answered is
        # still better evidenced with them than with an empty section.
        return keep or items

    wins = _shown(_pref(v.get("cited_examples")))
    miss = _shown(_pref(v.get("missed_examples")))

    # THE SAME QUESTION TWICE IS NOT TWO EXAMPLES.
    #
    # "Is Ooten Law Firm legit or a scam?" appeared twice - cited by Google,
    # not cited by Perplexity - which is a real and interesting difference,
    # and it reads as the report repeating itself. One row per question; the
    # first one in platform order keeps the slot.
    # AND NEITHER IS THE SAME QUESTION IN DIFFERENT WORDS.
    #
    # Exact-text dedupe fixed the pair that read identically and left the pair
    # that reads identically to a CLIENT: "Is Ooten Law Firm legit or a scam?"
    # next to "Is Ooten Law Firm a reputable company?" is one question about
    # trust, asked twice, and printing both spends two of six example slots on
    # the same finding. So the key is what the question is ASKING, not how it
    # was phrased - and anything we cannot bucket falls back to its content
    # words, which still catches word-order variants.
    _INTENT = (
        ("trust", ("legit", "scam", "reputable", "trustworthy", "trust",
                   "reliable", "safe", "ripoff", "rip off", "fraud")),
        ("quality", ("reviews", "rating", "complaints", "good", "any good")),
        ("cost", ("cost", "price", "pricing", "how much", "fee", "fees",
                  "charge", "expensive", "afford")),
        ("best", ("best", "top", "recommend", "who should i", "leading")),
        ("about", ("known for", "what is", "who is", "specialize",
                   "specialise", "what does", "services", "offer")),
        ("choose", ("how do i choose", "what to look for", "questions to ask",
                    "how to pick", "how to find")),
    )
    _STOP = {"a", "an", "the", "is", "are", "do", "does", "in", "of", "for",
             "to", "or", "and", "i", "my", "you", "your", "what", "who",
             "how", "with", "on", "at", "near", "me", "it", "be", "any"}

    def _intent(q, brand):
        t = " ".join(str(q or "").lower().split())
        b = " ".join(str(brand or "").lower().split())
        if b:
            t = t.replace(b, " ")
        t = " ".join(t.replace("?", " ").split())
        for name, words in _INTENT:
            if any(w in t for w in words):
                return name
        return " ".join(sorted(w for w in t.split()
                               if w not in _STOP and len(w) > 2))

    # AND NOT TWICE ABOUT THE SAME PRACTICE AREA EITHER.
    #
    # Intent dedupe caught "legit or a scam" beside "a reputable company". It
    # did not catch "who is best for estate planning" beside "how much does
    # estate planning cost", because those genuinely ARE two intents - and the
    # report still spent two of its six slots on one practice area while
    # criminal defense and DUI went unmentioned. A client reads that as the
    # report having one idea about them.
    #
    # The SUBJECT is what is left after the brand, the intent words, the
    # geography and the generic role nouns come out: "estate planning",
    # "dui", "family law". One card per subject.
    _ROLE_WORDS = {"attorney", "attorneys", "lawyer", "lawyers", "firm",
                   "firms", "company", "companies", "business", "service",
                   "services", "agency", "provider", "providers", "office",
                   "practice", "near", "around", "area", "areas"}
    _INTENT_WORDS = {w for _n, ws in _INTENT for w in ws for w in w.split()}

    def _subject(q, brand):
        t = " ".join(str(q or "").lower().split())
        b = " ".join(str(brand or "").lower().split())
        if b:
            t = t.replace(b, " ")
        t = re.sub(r"[^a-z0-9\s]", " ", t)
        # "... in Knoxville, Tennessee" and "... near me" are the market, not
        # the subject. Two questions about different places are still one
        # question as far as this report's variety is concerned.
        t = re.sub(r"\bin\s+.*$", " ", t)
        t = re.sub(r"\bnear\s+me\b", " ", t)
        words = [w for w in t.split()
                 if len(w) > 2 and w not in _STOP and w not in _ROLE_WORDS
                 and w not in _INTENT_WORDS]
        return " ".join(sorted(words))

    seen_q = set()

    def _fresh(items):
        out = []
        for it in items:
            q = str(it.get("question") or "")
            k = " ".join(q.lower().split())
            if not k:
                continue
            # Both keys, so an exact repeat and a reworded one are each caught
            # once, and a question whose intent we cannot name is still deduped
            # on its own text.
            ik = _intent(q, brand)
            sk = _subject(q, brand)
            sk = f"subj:{sk}" if sk else ""
            if k in seen_q or (ik and ik in seen_q) or (sk and sk in seen_q):
                continue
            seen_q.add(k)
            if ik:
                seen_q.add(ik)
            if sk:
                seen_q.add(sk)
            out.append(it)
        return out

    _raw_wins, _raw_miss = wins, miss
    wins = _fresh(wins)
    miss = _fresh(miss)
    # DEDUPE MUST NOT DELETE THE HALF THAT MATTERS.
    #
    # The intent key is shared across both lists on purpose - a trust question
    # answered and a trust question missed is still one question - but if every
    # miss happened to share an intent with a win, the misses vanish and the
    # section shows only good news. The misses are the finding. When intent
    # dedupe empties them, fall back to exact-text dedupe for that half.
    if _raw_miss and not miss:
        _seen = set()
        for it in _raw_miss:
            k = " ".join(str(it.get("question") or "").lower().split())
            if k and k not in _seen:
                _seen.add(k)
                miss.append(it)
    if not wins and not miss:
        return []

    GOOD = (colors.HexColor("#E4F1E8"), colors.HexColor("#1E7A45"))
    BAD = (colors.HexColor("#F7E4E7"), colors.HexColor("#A6192E"))

    out = [Spacer(1, 12),
           Paragraph("What was asked, and what came back", S["h3"]),
           Paragraph(
               "<b>Linked to you</b> means the answer used your website as one "
               "of its sources, with a link a reader can follow. <b>Did not "
               "link to you</b> means it answered from somewhere else. Only "
               "the link sends anyone to you.", S["small"]),
           Spacer(1, 8)]

    def block(item, cited):
        q = item.get("question")
        named = _asked_by_name(q, brand)
        plat = _ai_platforms({"platforms": [item.get("platform") or ""]})
        asked = (f"Asked of {plat[0]}" if plat and plat[0] else "Asked")
        asked += (", using your name" if named else ", without naming you")
        others = [d for d in (item.get("cited_instead") or []) if d][:3]
        if cited:
            verdict = "It linked to your site."
        elif others:
            verdict = ("It did not link to you. It linked to "
                       + ", ".join(others) + " instead.")
        else:
            verdict = "It did not link to you, or to any source we could name."

        inner = [Paragraph(f"<b>\u201c{_p(q)}\u201d</b>", S["cell"]),
                 Spacer(1, 2),
                 Paragraph(f"<font color='#8096AC'>{_p(asked)}</font>",
                           S["cellsm"]),
                 Spacer(1, 4),
                 Paragraph(_p(verdict), S["cellsm"])]
        # THE ANSWER'S OWN WORDS, WHERE WE HAVE THEM.
        #
        # Stored from the run since the build that stopped throwing the raw
        # answers away; an older audit has none, and prints the verdict alone
        # rather than an empty quotation mark.
        ans = " ".join(str(item.get("answer") or "").split())
        if ans:
            if len(ans) > 260:
                ans = ans[:257].rsplit(" ", 1)[0] + "\u2026"
            inner += [Spacer(1, 5),
                      Paragraph(f"<font color='#52514e'>\u201c{_p(ans)}"
                                f"\u201d</font>", S["cellsm"])]

        pill = _pill("Linked to you" if cited else "Did not link",
                     {"Linked to you": GOOD, "Did not link": BAD}, S,
                     1.15 * inch)
        t = Table([[pill, inner]], colWidths=[1.25 * inch, 5.35 * inch])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 10),
            ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ]))
        return KeepTogether([t])

    for w in _spread(wins, 2):
        out.append(block(w, True))
    # THE MISSES WORTH SHOWING ARE THE ONES THAT DID NOT NAME YOU.
    #
    # Three brand questions in the "did not link" half tells the reader that
    # assistants are unsure about a firm they were asked about by name. True,
    # and it is the same story as the two rows above it. The ones that carry
    # new information are the questions where somebody was looking for the
    # SERVICE and got sent elsewhere - so those go first, and at most one
    # by-name miss is kept for contrast.
    unnamed = [m for m in miss if not _asked_by_name(m.get("question"), brand)]
    named = [m for m in miss if _asked_by_name(m.get("question"), brand)]
    # A by-name miss only earns a slot when the cited half did not already
    # spend the reader's attention on by-name questions - otherwise "is it a
    # reputable company" lands two inches under "is it legit or a scam" and
    # reads as the report asking the same thing twice.
    shown_named = sum(1 for w in _spread(wins, 2)
                      if _asked_by_name(w.get("question"), brand))
    picks = _spread(unnamed, 3)
    if len(picks) < 3 and shown_named < 2:
        picks += _spread(named, 3 - len(picks))
    for m in picks:
        out.append(block(m, False))
    return out


def _listy_pdf(items) -> str:
    """a, b and c - the way a person writes it."""
    items = [str(i) for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _reputation(meta, S):
    """
    What the public record says - reviews, brand searches, page one.

    A DIFFERENT KIND OF FACT FROM THE REST OF THIS REPORT, and it reads in a
    different order because of that. Everything else is about the client's own
    site and can be fixed by editing it. This is about what other people have
    published, where the only levers are earning more of the good and
    answering the bad - so the section leads with the score a stranger sees
    before it gets anywhere near a recommendation.
    """
    rep = (meta.get("extras") or {}).get("reputation") or {}
    if not rep or not rep.get("ok"):
        return []
    sm = rep.get("summary") or {}
    out = [PageBreak(),
           # "Reputation" named the topic; it did not say what the pages are
           # about. Every other section heading in this report says what was
           # examined, and what was examined here is not the client's site at
           # all - it is what a stranger finds when they look the client up.
           Paragraph("What People Find When They Search You", S["h2"]), _rule(),
           # THE CLIENT'S ACTUAL NAME, NOT "YOUR NAME".
           #
           # Every figure in this section was measured against a specific
           # search - "ooten law firm reviews" - so printing the placeholder
           # made the sentence vaguer than the data behind it, and left the
           # reader guessing which phrase we had actually run.
           Paragraph(
               "Before anyone reads a word of your site, most of them search "
               "your name. This is what that search returns: the star rating "
               "on your listings, what else holds page one for "
               "\u201c{} reviews\u201d, and whether people are searching your "
               "name alongside a complaint.".format(
                   _p(rep.get("brand") or meta.get("client") or "your name")),
               S["small"])]
    # A CARRIED PROFILE SAYS SO.
    #
    # Reputation is the fastest-moving section in the report - one bad week
    # moves a star rating - so a profile taken from an earlier run has to be
    # dated on the page. Silently reprinting last month's number as this
    # month's is the exact failure this codebase keeps chasing.
    if rep.get("carried_at"):
        out.append(Paragraph(
            f"Measured on an earlier run of this site "
            f"({_p(str(rep['carried_at'])[:10])}) and carried forward, so it "
            f"describes the public record as of that date.", S["tiny"]
            if "tiny" in S else S["small"]))
    out.append(Spacer(1, 10))

    _big = ParagraphStyle("repbig", parent=S["cellsm"], fontName=_fonts.BOLD,
                          fontSize=21, leading=24, textColor=INK)
    _lead = ParagraphStyle("replead", parent=S["cellsm"], fontName=_fonts.BOLD,
                           fontSize=8.5, leading=11, textColor=INK)
    _sub = ParagraphStyle("repsub", parent=S["cellsm"], fontSize=7.5,
                          leading=9.5, textColor=colors.HexColor("#4A5461"))

    def tile(big, lead, sub):
        return [Paragraph(_p(big), _big), Paragraph(_p(lead), _lead),
                Paragraph(_p(sub), _sub)]

    rating = sm.get("rating")
    locs = sm.get("locations") or 0
    # FOUR TILES, BECAUSE THE FOURTH IS THE SIZE OF THE PROBLEM.
    #
    # The other three describe the state of the reputation; brand search
    # volume says how many people MEET it every month. A 3.9 average matters
    # differently at 200 brand searches a month than at 52,000, and without
    # the denominator the reader has no way to tell which of those they are
    # looking at. The quote builder leads on this number for the same reason.
    _bv = sm.get("brand_volume") or 0
    _tiles = [
        tile(f"{rating}" if rating else "\u2014", "average rating",
             f"across {locs} listing{'s' if locs != 1 else ''}"),
        tile(f"{sm.get('reviews') or 0:,}", "reviews in total",
             "on your Google listings"),
        tile(f"{sm.get('owned_in_top10') or 0} of "
             f"{(sm.get('owned_in_top10') or 0) + (sm.get('third_party_in_top10') or 0)}",
             "page one is yours",
             "for \u201c{} reviews\u201d".format(rep.get("brand") or "your name")),
    ]
    if _bv:
        _tiles.append(tile(f"{_bv:,}", "searches a month",
                           "for your name and its variants"))
    _cw = (6.6 / len(_tiles)) * inch
    tiles = Table([_tiles], colWidths=[_cw] * len(_tiles))
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

    # THE WEAKEST LISTING, NAMED.
    #
    # An average of 4.7 across nine locations is a good number that hides the
    # one at 3.2, and the one at 3.2 is the only actionable thing on the page.
    worst = sm.get("worst") or {}
    if worst and rating and float(worst.get("rating") or 5) < float(rating) - 0.3:
        out.append(Spacer(1, 8))
        out.append(_banner(
            "", f"{worst.get('title')} is your weakest listing at "
                f"{worst.get('rating')} from {worst.get('reviews') or 0} "
                f"reviews - below your own average. One location can carry the "
                f"whole brand's rating down in a local pack.", GOLD, S))

    # ---- page one for "<brand> reviews" --------------------------------
    #
    # OWNED VERSUS THIRD PARTY, AND WHAT WE WOULD DO ABOUT EACH.
    #
    # "Yours / Someone else's" answered half the question and stopped. The
    # quote builder's version of this table is the one that sells, because
    # every row carries a TACTIC: a result is not just somebody else's, it is
    # somebody else's and therefore something to suppress, or leave alone
    # because its four stars are working for you, or get removed outright.
    # `route_tactic` already decides that per row and stores it - it was being
    # computed and thrown away here.
    organic = ((rep.get("serp") or {}).get("organic") or [])[:10]
    if organic:
        _OWN = (colors.HexColor("#E4F1E8"), colors.HexColor("#1E7A45"))
        _THIRD = (colors.HexColor("#EEF2F6"), colors.HexColor("#4A5461"))
        # A tactic is a recommendation, so it is colored by what it asks of
        # us: green where the result is already working, amber where it needs
        # pushing down, red where it should not be there at all.
        _TACT = {
            "owned \u2014 boost": (colors.HexColor("#E4F1E8"), colors.HexColor("#1E7A45")),
            "positive \u2014 leave": (colors.HexColor("#E4F1E8"), colors.HexColor("#1E7A45")),
            "suppression": (colors.HexColor("#FDF3E2"), colors.HexColor("#8A5A00")),
            "site removal": (colors.HexColor("#F7E4E7"), colors.HexColor("#A6192E")),
        }
        rows = [[Paragraph("<b>#</b>", S["cellsm"]),
                 Paragraph("<b>Result</b>", S["cellsm"]),
                 Paragraph("<b>Whose</b>", S["cellsm"]),
                 Paragraph("<b>Rating</b>", S["cellsm"]),
                 Paragraph("<b>What we would do</b>", S["cellsm"])]]
        for o in organic:
            tac = (o.get("tactic") or "").strip()
            rows.append([
                Paragraph(str(o.get("pos") or ""), S["cellsm"]),
                Paragraph(f"<b>{_p(o.get('domain'))}</b><br/>"
                          f"<font color='#8096AC'>{_p(o.get('title'))}</font>",
                          S["cellsm"]),
                _pill("OWNED" if o.get("owned") else "3RD PARTY",
                      {"OWNED": _OWN, "3RD PARTY": _THIRD}, S, 0.72 * inch),
                Paragraph(str(o.get("rating") or "\u2014"), S["cellsm"]),
                (_pill(tac.upper(), {tac.upper(): _TACT.get(tac, _THIRD)}, S,
                       1.45 * inch) if tac else Paragraph("", S["cellsm"])),
            ])
        t = Table(rows, colWidths=[0.3 * inch, 2.85 * inch, 0.82 * inch,
                                   0.58 * inch, 1.55 * inch])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
            ("LINEBELOW", (0, 1), (-1, -1), 0.35, colors.HexColor("#F1F4F7")),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        out += [Spacer(1, 14),
                Paragraph("Who owns page one for \u201c{} reviews\u201d".format(
                    rep.get("brand") or "your name"), S["h3"]),
                Paragraph("Every result here is what a person deciding "
                          "whether to call you reads instead of your site. "
                          "The last column is what we would do about each one.",
                          S["small"]),
                Spacer(1, 6), t]

    # ---- the star bands behind the average -----------------------------
    #
    # "4.8 from 227 reviews" is the number the client already knows and is
    # comfortable with. "Ten one-star reviews" is the one that starts the
    # conversation, and the average is designed to hide it: ten 1-stars move a
    # 227-review average by about a tenth of a point. So the bands are printed
    # beside the profile figure they are invisible inside.
    _stars = (sm.get("stars") or {}).get("listings") or []
    if _stars:
        # STARS DRAWN AS STARS.
        #
        # "1 star / 2 star / 3 star" as three word-headers made the reader
        # translate a rating into a column position on every row. The glyphs
        # are the thing being counted, so they are what the header shows, and
        # the eye finds the one-star column without reading anything. Color
        # is never the only signal: each column still carries its count.
        srows = [[Paragraph("<b>Listing</b>", S["cellsm"]),
                  Paragraph("<b>Profile</b>", S["cellsm"]),
                  _star_row(1, _STAR_BAD), _star_row(2, _STAR_BAD),
                  _star_row(3, _STAR_MEH)]]
        def _band(n, floor):
            # "at least 0" is not a floor, it is a typo with a reason. The
            # truncation flag says the pull ran out of room while still
            # returning bad reviews, so it qualifies a count we DID find - it
            # says nothing about a band that came back empty.
            n = int(n or 0)
            return f"at least {n}" if (floor and n) else str(n)

        for L in _stars:
            _fl = bool(L.get("at_least"))
            # A LINK TO THE LISTING ITSELF.
            #
            # The row names a Google Business Profile and the next thing
            # anybody wants is to look at it - which meant copying the name
            # into a search box. Google's place_id URL form resolves straight
            # to the profile, and place_id is the one identifier the listings
            # database already returns for every location we find.
            _pid = L.get("place_id")
            _nm = _p(L.get("title"))
            _title = (f"<a href='https://www.google.com/maps/place/?q=place_id:"
                      f"{_p(_pid)}' color='#1A56A8'><b>{_nm}</b></a>"
                      if _pid else f"<b>{_nm}</b>")
            srows.append([
                Paragraph(_title
                          + (f"<br/><font color='#8096AC'>"
                             f"{_p(L.get('address'))}</font>"
                             if L.get("address") else ""), S["cellsm"]),
                # NO STAR IN THIS CELL.
                #
                # A drawn star, then a number, then a slash, then another
                # number, inside a one-inch column - four marks doing the work
                # of one phrase, and it read as clutter rather than as a
                # rating. The band headers are where the star glyph earns its
                # place, because there the shape IS the label. Here the words
                # are shorter than the decoration.
                Paragraph(f"{L.get('rating') or '—'} from "
                          f"{L.get('reviews') or 0:,}", S["cellsm"]),
                Paragraph(_band(L.get("one"), _fl), S["cellsm"]),
                Paragraph(_band(L.get("two"), _fl), S["cellsm"]),
                Paragraph(_band(L.get("three"), _fl), S["cellsm"]),
            ])
        st_ = Table(srows, colWidths=[2.9 * inch, 1.1 * inch, 0.87 * inch,
                                      0.87 * inch, 0.86 * inch])
        st_.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
            ("LINEBELOW", (0, 1), (-1, -1), 0.35, colors.HexColor("#F1F4F7")),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        _low = sum((L.get("one") or 0) + (L.get("two") or 0) for L in _stars)
        _sub = ("These are the reviews a person reads first when they sort "
                "by lowest.")
        if _low:
            _sub = (f"<b>{_low} review{'s' if _low != 1 else ''} at one or two "
                    f"stars.</b> " + _sub)
        out += [Spacer(1, 14),
                Paragraph("The reviews behind the rating", S["h3"]),
                Paragraph(_sub, S["small"]), Spacer(1, 6), st_]
        if any(L.get("at_least") for L in _stars):
            out.append(Paragraph(
                "“At least” means the pull reached its limit while still "
                "returning bad reviews — there are more below the ones "
                "counted here.", S["small"]))

    # ---- a picture of that page ----------------------------------------
    #
    # The table above is the analysis; this is the evidence. A row saying
    # yelp.com holds position two is a claim about their search results. A
    # picture of their search results with Yelp above their own website is the
    # thing itself, and it ends the argument rather than starting one.
    _shot = rep.get("shot") or {}
    if _shot.get("ok") and _shot.get("png"):
        _w = 6.0 * inch
        _iw, _ih = _png_size(_shot["png"])
        _ratio = (_ih / _iw) if (_iw and _ih) else 1.2
        _full = _w * _ratio
        # THE HEADING, THE LINE UNDER IT AND THE PICTURE ARE ONE THING.
        #
        # They were three loose flowables, so the break landed between the
        # description and the image it describes - leaving a heading and a
        # sentence alone at the foot of a page promising a picture overleaf.
        # A caption separated from what it captions is not a caption.
        out += [PageBreak(), KeepTogether([
                Paragraph("What that search actually looks like", S["h3"]),
                Paragraph("Google, today, for “{}”. Nothing has been moved or "
                          "removed.".format(_p(_shot.get("keyword")
                                               or "your name reviews")),
                          S["small"]),
                Spacer(1, 8),
                # CROPPED TO THE TOP, NOT SHRUNK TO FIT. A full-page Google
                # capture is several thousand pixels tall; drawn whole it
                # becomes a thumbnail strip nobody can read, and the part that
                # matters - who holds the first few results - is the part at
                # the top. Same treatment as the homepage shot.
                Shot(_shot["png"], _w, min(_full, 6.2 * inch), draw_h=_full)])]

    # ---- what Google suggests while they are typing ---------------------
    #
    # Reproduced rather than summarised. "One negative suggestion" is a
    # statistic; the drop-down itself, with "complaints" sitting seventh among
    # six harmless ones, is what a person actually sees when they start typing
    # the client's name - and the ordinary suggestions around it are what make
    # the odd one out visible. Stripping them to save space would leave the
    # summary and throw away the exhibit.
    _panels = [g for g in (sm.get("suggestions") or []) if g.get("items")]
    _pasf = list(sm.get("pasf") or [])
    if _panels or _pasf:
        _negset = {str(x).strip().lower()
                   for g in _panels for x in (g.get("negative") or [])}
        _negset |= {str(x).strip().lower()
                    for x in (sm.get("pasf_negative") or [])}
        _BAD = (colors.HexColor("#FBEAEC"), colors.HexColor("#A6192E"))
        _OK = (colors.HexColor("#F7F8FA"), colors.HexColor("#3A4552"))

        # STYLED THE WAY THE QUOTE BUILDER STYLES IT.
        #
        # That version is a facsimile of Google's own drop-down, and the
        # facsimile is the persuasion: a client recognizes the shape of their
        # own search box instantly and reads the red row as something they
        # have seen rather than something we have calculated. Three details
        # carry it, and all three were missing here - the magnifier down the
        # left, the brand name set plain with only the MODIFIER in bold (so
        # "complaints" is the word the eye lands on), and full-width rows
        # rather than a grid of tiles.
        _brandlow = " ".join(str(rep.get("brand") or "").lower().split())

        def _boldmod(text):
            """Brand plain, the words after it bold - as the quote tool does."""
            t = str(text or "")
            if _brandlow and t.lower().startswith(_brandlow):
                return (f"{_p(t[:len(_brandlow)])}"
                        f"<b>{_p(t[len(_brandlow):])}</b>")
            return _p(t)

        def _mag(fg):
            """A magnifier, drawn. The emoji the web version uses is not in
            any font we embed, and would print as a hollow box."""
            from reportlab.graphics.shapes import Drawing, Circle, Line
            d = Drawing(9, 9)
            # The negative palette hands back a Color; the neutral case is a
            # hex string. Accept both rather than making callers convert.
            c = fg if isinstance(fg, colors.Color) else colors.HexColor(fg)
            d.add(Circle(4, 5.2, 2.7, strokeColor=c, strokeWidth=0.9,
                         fillColor=None))
            d.add(Line(6, 3.3, 7.9, 1.4, strokeColor=c, strokeWidth=0.9))
            return d

        def _row(text, wide, icon_right=False):
            neg = str(text).strip().lower() in _negset
            bg, fg = (_BAD if neg else _OK)
            st_ = ParagraphStyle("sug", parent=S["cellsm"], textColor=fg,
                                 fontSize=8.5, leading=11)
            para = Paragraph(_boldmod(text), st_)
            icon = _mag(fg if neg else "#8B93A1")
            # PADDING PER CELL, NOT ACROSS THE ROW.
            #
            # A blanket 8pt each side is wider than the icon column itself, and
            # reportlab's answer to a negative available width is an exception
            # from inside its own error formatter - so the whole report died
            # rather than one magnifier being cramped. The icon cell gets the
            # outer margin only; the text cell gets the gap and the far edge.
            _ICON = 0.24 * inch
            cells = ([[para, icon]] if icon_right else [[icon, para]])
            widths = ([wide - _ICON, _ICON] if icon_right
                      else [_ICON, wide - _ICON])
            c = Table(cells, colWidths=widths)
            _ic = 1 if icon_right else 0      # column holding the magnifier
            _tc = 0 if icon_right else 1      # column holding the text
            c.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("ROUNDEDCORNERS", [5, 5, 5, 5]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (_ic, 0), (_ic, 0), 0 if icon_right else 9),
                ("RIGHTPADDING", (_ic, 0), (_ic, 0), 9 if icon_right else 0),
                ("LEFTPADDING", (_tc, 0), (_tc, 0), 9 if icon_right else 7),
                ("RIGHTPADDING", (_tc, 0), (_tc, 0), 7 if icon_right else 9),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            c.hAlign = "LEFT"
            return c

        def _grid(items, cols=1, icon_right=False):
            wide = (6.6 / cols) * inch - (6 if cols > 1 else 0)
            rws = [items[i:i + cols] for i in range(0, len(items), cols)]
            cells = [[_row(x, wide, icon_right) for x in r]
                     + [""] * (cols - len(r)) for r in rws]
            g = Table(cells, colWidths=[(6.6 / cols) * inch] * cols)
            g.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6 if cols > 1 else 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
            g.hAlign = "LEFT"
            return g

        # THE SECTION HEADING TRAVELS WITH THE FIRST PANEL TOO.
        #
        # Binding each panel to its own label fixed half of it and left the
        # other half: the section heading and its explanation sat alone at the
        # top of a page with the whole page empty underneath, and the chips
        # they introduce started the page after. Two paragraphs of setup with
        # nothing to set up reads as a rendering fault, which is what it was.
        _intro = [Paragraph("What Google suggests while they type", S["h3"]),
                  Paragraph("These are Google's own auto-complete suggestions "
                            "for your name. Anything in red pairs you with a "
                            "complaint before the person has finished typing.",
                            S["small"])]
        out.append(Spacer(1, 16))
        for i, g in enumerate(_panels[:2]):
            _panel = [Paragraph(f"<b>“{_p(g.get('keyword'))}”</b>",
                                S["cellsm"]),
                      # TWO UP, LIKE THE QUOTE TOOL.
                      #
                      # A single full-width column reproduced Google's
                      # drop-down faithfully and ran ten rows down the page
                      # for it - most of a sheet spent on a list of short
                      # phrases with three inches of white to the right of
                      # every one. Two columns keep the magnifier, the bold
                      # modifier and the red highlight, and fit the same
                      # exhibit in half the height.
                      Spacer(1, 4), _grid(list(g["items"])[:10], cols=2)]
            out.append(KeepTogether((_intro + [Spacer(1, 8)] + _panel)
                                    if i == 0 else _panel))
            if i == 0:
                out.append(Spacer(1, 10))
        if _pasf:
            out += [Spacer(1, 10),
                    KeepTogether([
                        Paragraph("<b>People also search for</b>", S["cellsm"]),
                        Spacer(1, 4), _grid(_pasf[:8], cols=2, icon_right=True)])]

    # ---- brand searches carrying a complaint ---------------------------
    neg = sm.get("negative_terms") or []
    # SAY EACH PHRASE ONCE.
    #
    # The same phrase reaches this block from three different databases -
    # keyword volume, autocomplete, related searches - and printing it in all
    # three sentences reads as three separate problems. It is one, found three
    # ways, so the first mention keeps it and the rest drop it.
    _said = {(t.get("term") or "").strip().lower() for t in neg[:4]}

    def _new(seq):
        out = []
        for x in seq:
            k = str(x).strip().lower()
            if k and k not in _said:
                _said.add(k)
                out.append(x)
        return out

    sugg = _new(sm.get("negative_suggestions") or [])
    related = _new(sm.get("negative_related") or [])
    if neg or sugg or related:
        lines = []
        if sm.get("negative_volume"):
            lines.append(
                f"<b>{sm['negative_volume']:,} searches a month</b> pair your "
                f"name with a complaint word - out of "
                f"{sm.get('brand_volume') or 0:,} brand searches in total.")
        if neg:
            lines.append("The largest are " + _listy_pdf(
                [f"\u201c{t['term']}\u201d ({t['volume']:,}/mo)"
                 for t in neg[:4]]) + ".")
        if sugg:
            lines.append("Google's own search box suggests "
                         + _listy_pdf([f"\u201c{x}\u201d" for x in sugg[:4]])
                         + " while somebody is typing your name.")
        if related:
            lines.append("Related searches on the results page include "
                         + _listy_pdf([f"\u201c{x}\u201d"
                                       for x in related[:4]]) + ".")
        out += [Spacer(1, 14),
                Paragraph("Searches that carry a complaint", S["h3"]),
                Paragraph(" ".join(lines), S["body"])]

    forums = sm.get("forums") or []
    if forums:
        out += [Spacer(1, 10),
                Paragraph(
                    "A discussion thread ranks for your name: "
                    + _listy_pdf(sorted({f.get("domain") for f in forums
                                         if f.get("domain")})[:4])
                    + ". Threads outrank most owned pages and cannot be "
                      "edited - they are answered, not removed.", S["small"])]
    return out


# DOMAINS ANYONE CAN GET A PROFILE ON, BY CATEGORY.
#
# The distinction that makes the sources block actionable rather than
# informational. When an assistant answers "who is the best DUI attorney in
# Knoxville" by citing Avvo and Justia, the recommendation is not "write more
# content" - it is "you are not on Avvo, and Avvo is what it reads". That is a
# week of work with a known finish line, and it is invisible unless the report
# separates the sources you can join from the ones you cannot.
#
# Deliberately a list rather than a heuristic: "is this a directory" has no
# reliable signal in the domain string, and a wrong guess here recommends
# buying a profile on a competitor's website.
_LISTABLE = {
    # legal
    "avvo.com", "justia.com", "lawyers.com", "martindale.com", "nolo.com",
    "findlaw.com", "superlawyers.com", "bestlawyers.com", "lawinfo.com",
    "attorneyatlaw.com", "chambers.com", "legalmatch.com",
    # local / general
    "yelp.com", "bbb.org", "angi.com", "thumbtack.com", "houzz.com",
    "expertise.com", "threebestrated.com", "manta.com", "yellowpages.com",
    "birdeye.com", "trustpilot.com", "clutch.co", "g2.com", "capterra.com",
    # health
    "healthgrades.com", "zocdoc.com", "vitals.com", "webmd.com",
    "ratemds.com", "sharecare.com",
    # home services / trades
    "homeadvisor.com", "porch.com", "buildzoom.com", "nextdoor.com",
}

# Somebody else's plumbing, not a source. See the share-of-voice note.
_NOT_A_SOURCE = {"vertexaisearch.cloud.google.com", "google.com",
                 "webcache.googleusercontent.com", "bing.com",
                 "duckduckgo.com", "search.yahoo.com"}


def _ai_sources(v, S, rep=None):
    """
    Where the answers actually came from, and whether the client is on them.

    THE QUESTION THE SHARE-OF-VOICE CHART DOES NOT ANSWER.

    A ranked list of domains says who is winning. It does not say what to DO,
    and for a local service business the answer is usually not "publish more"
    - it is "the assistants are reading Avvo and Justia, and you have no
    profile on either". That is the difference between a report that describes
    a problem and one that names a week of work.

    The presence half is free: the reputation scan already fetched page one
    for "<brand> reviews", and a directory that ranks for the client's own
    name is a directory the client is on. Where reputation was not run the
    column honestly says so rather than guessing - an unchecked box printed as
    "not listed" would send someone to claim a profile they already own.
    """
    sov = [d for d in (v.get("share_of_voice") or [])
           if d.get("domain") and d["domain"] not in _NOT_A_SOURCE]
    if not sov:
        return []

    # Domains that rank for the brand's own name = domains the brand is on.
    known, checked = set(), False
    if rep and rep.get("ok"):
        checked = True
        for o in ((rep.get("serp") or {}).get("organic") or []):
            if o.get("domain"):
                known.add(str(o["domain"]).lower().replace("www.", ""))

    rows = [[Paragraph("<b>Source</b>", S["cellsm"]), "",
             Paragraph("<b>Cited</b>", S["cellsm"]),
             Paragraph("<b>What it is</b>", S["cellsm"]),
             Paragraph("<b>You on it?</b>", S["cellsm"])]]
    _OWN = (colors.HexColor("#E4F1E8"), colors.HexColor("#1E7A45"))
    _DIR = (colors.HexColor("#FDF3E2"), colors.HexColor("#8A5A00"))
    _OTH = (colors.HexColor("#EEF2F6"), colors.HexColor("#4A5461"))
    listable = 0
    for d in sov[:8]:
        dom = str(d["domain"]).lower().replace("www.", "")
        if d.get("is_client"):
            kind, pal = "YOURS", _OWN
            on = "—"
        elif dom in _LISTABLE:
            kind, pal = "DIRECTORY", _DIR
            listable += 1
            on = ("Yes" if dom in known else "No sign of you") if checked \
                else "Not checked"
        else:
            kind, pal = "SOMEONE ELSE", _OTH
            on = "—"
        _share = d.get("share") or 0
        rows.append([
            Paragraph(f"<b>{_p(dom)}</b>", S["cellsm"]),
            # The meter is the one thing the old share-of-voice grid did well:
            # the ORDER is the finding, and a bar shows order faster than a
            # column of near-identical small percentages.
            MiniMeter(round(_share * 100) if _share <= 1 else _share,
                      width=1.25 * inch, height=7),
            Paragraph(str(d.get("citations") or 0), S["cellsm"]),
            _pill(kind, {kind: pal}, S, 1.15 * inch),
            Paragraph(_p(on), S["cellsm"]),
        ])
    t = Table(rows, colWidths=[1.85 * inch, 1.35 * inch, 0.55 * inch,
                               1.3 * inch, 1.15 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.35, colors.HexColor("#F1F4F7")),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))

    lead = ("These are the pages the assistants read before answering. The "
            "ones marked DIRECTORY are the ones you can do something about "
            "this month: a profile there is a form, not a campaign.")
    if checked and listable:
        _missing = [str(d["domain"]).lower().replace("www.", "")
                    for d in sov[:8]
                    if not d.get("is_client")
                    and str(d["domain"]).lower().replace("www.", "") in _LISTABLE
                    and str(d["domain"]).lower().replace("www.", "") not in known]
        if _missing:
            lead += (" We found no sign of you on " + _listy_pdf(_missing)
                     + ", and the assistants are citing them.")
    out = [Spacer(1, 14),
           KeepTogether([Paragraph("Where those answers came from", S["h3"]),
                         Paragraph(lead, S["small"]), Spacer(1, 6), t])]
    # The gap sentence came off the old grid. It is the one comparison in the
    # section a client repeats out loud.
    gap = v.get("citation_gap")
    if gap and gap > 0 and v.get("top_competitor_domain"):
        out.append(Spacer(1, 6))
        out.append(Paragraph(
            f"<font color='#52514e'>{_p(v['top_competitor_domain'])} is cited "
            f"{gap} more times than you across the same questions.</font>",
            S["small"]))
    return out


def _ai_gate(findings, S):
    """
    Whether the assistants are allowed to read the site at all.

    THE ONE ROW THAT SITS UNDERNEATH EVERY OTHER NUMBER IN THIS SECTION.

    GEO-04 already reads robots.txt for GPTBot, ClaudeBot, PerplexityBot,
    Google-Extended and the rest, and it was filed in the appendix among three
    hundred other rows. That is the wrong place for it: if the site is
    blocking the crawlers, the citation rate above is not a marketing result,
    it is a consequence, and every recommendation in this section is moot
    until one line of robots.txt changes. A security plugin or a CDN bot rule
    turns this on by default on plenty of small-business sites, so it is a
    real and common cause rather than a theoretical one.

    Printed either way. A clean answer is worth saying too - it closes off the
    cheapest explanation before anyone spends money on the expensive ones.
    """
    f = (findings or {}).get("GEO-04") or {}
    st = f.get("status")
    if st not in ("Pass", "Fail", "Warning"):
        return []
    blocked = list((f.get("value") or {}).get("blocked") or [])
    if blocked:
        body = ("Your robots.txt tells " + _listy_pdf(blocked) + " not to "
                "read the site. Until that changes, the numbers above are a "
                "consequence of a setting rather than a measure of your "
                "content - an assistant cannot cite a page it is not allowed "
                "to fetch. This is usually a security plugin or a CDN bot "
                "rule rather than a decision anybody made.")
        tone = colors.HexColor("#A6192E")
    else:
        body = ("Your robots.txt lets the AI crawlers read the site, so "
                "nothing above is explained by access. That matters because "
                "it is the cheapest possible cause and it has been ruled out.")
        tone = colors.HexColor("#1E7A45")
    return [Spacer(1, 12),
            KeepTogether([Paragraph("Can the assistants read your site?",
                                    S["h3"]),
                          Spacer(1, 4), _banner("", body, tone, S)])]


def _ai_visibility(meta, S, findings=None):
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
    _ctx = (meta.get("extras") or {}).get("context") or {}
    _brand = (_ctx.get("brand") or meta.get("client") or "").strip()
    out = [Paragraph("AI Search Visibility", S["h2"]),
           _rule(),
           Paragraph(_p(_ai_intro(v)).replace("\n", "<br/><br/>"),
                     S["small"]),
           Spacer(1, 8)]
    _gate = _ai_gate(findings, S)

    cite = v.get("citation_rate") or 0
    ment = v.get("mention_rate") or 0
    unp = v.get("unprompted_citation_rate")
    # THREE TILES, THREE LABELS THAT WRAP DIFFERENTLY.
    #
    # "of answers CITED your site as a source" is three lines, "mentioned the
    # brand without linking to you" is two, "total citations across 27
    # platforms" is two — so the numbers sat at the same height and the boxes
    # did not, which is what read as wonky. The label is now one short line in
    # every tile, with the qualifier below it, so all three set to the same
    # depth whatever the numbers are.
    # FIVE, NOT FORTY-EIGHT. `platforms` is a comma-separated STRING, so
    # len() counted its characters. See _ai_platforms.
    _names = _ai_platforms(v)
    _plats = len(_names)

    # THREE LINES, THREE STYLES, EACH WITH ITS OWN LEADING.
    #
    # This was one Paragraph carrying <font size=21> on the first line inside a
    # style whose leading is 9.5pt. reportlab measures a paragraph from the
    # STYLE's leading, not from the glyphs, so the table row was sized for
    # three 9.5pt lines while the ink needed twenty-one - and the third line
    # was cut in half by the bottom of the tile.
    _big = ParagraphStyle("aibig", parent=S["cellsm"], fontName=_fonts.BOLD,
                          fontSize=21, leading=24, textColor=INK)
    _lead = ParagraphStyle("ailead", parent=S["cellsm"], fontName=_fonts.BOLD,
                           fontSize=8.5, leading=11, textColor=INK)
    _sub = ParagraphStyle("aisub", parent=S["cellsm"], fontSize=7.5,
                          leading=9.5, textColor=colors.HexColor("#4A5461"))

    def _tile3(big, lead, sub):
        return [Paragraph(_p(big), _big), Paragraph(_p(lead), _lead),
                Paragraph(_p(sub), _sub)]

    # NAMED FIRST, THEN LINKED. The two numbers are a sequence, not a pair:
    # a tool has to know you before it can cite you, and the gap between them
    # is the finding. Reading the smaller number first hid that.
    tiles = Table([[
        _tile3(f"{ment}%", "of answers named you",
               "said your name, linked elsewhere"),
        _tile3(f"{cite}%", "of answers linked to you",
               "your site was one of the sources"),
        _tile3(v.get("client_citations") or 0, "links to your site",
               f"across {_plats} tool{'s' if _plats != 1 else ''}"),
    ]], colWidths=[2.2 * inch, 2.2 * inch, 2.2 * inch])
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
    # Straight after the numbers, before anything is recommended about them:
    # the reader's first question about a low citation rate should be "are we
    # even letting them in", and this answers it in one line.
    out += _gate

    # ---- HOW SOLID THE NUMBERS ABOVE ARE ---------------------------------
    #
    # Straight under the tiles, because it changes how they should be read.
    # Reported as a bare "12%" a rate invites a precision it does not have,
    # and the reading it invites - that next month's 18% is progress - is the
    # one it cannot support. Saying the width out loud is the difference
    # between an estimate and a claim.
    _ci = v.get("citation_ci") or {}
    if _ci.get("n"):
        _pm = _ci.get("plus_minus")
        _rep = v.get("repeats") or 1
        _asked = ("each question asked "
                  f"{_rep} time{'s' if _rep != 1 else ''}")
        out += [Spacer(1, 10), Paragraph(
            f"<b>How firm are these numbers?</b> They come from "
            f"{_ci['n']:,} answers, {_asked}. These systems do not answer "
            f"identically twice, so the linked-to figure is "
            f"<b>{cite}%, give or take {_pm} points</b> "
            f"({_ci['low']}–{_ci['high']}%). A change smaller than that "
            f"between one month and the next is the tools varying, not your "
            f"visibility moving - which is why we quote a range rather than "
            f"a single number.", S["small"])]

    # ---- MARKET BY MARKET ------------------------------------------------
    #
    # A blended rate across three counties is true of none of them. This is
    # the most consequential thing missing from a local AI-visibility reading:
    # the campaign you would run for a firm invisible in Clinton and fine in
    # Knoxville is not the campaign you would run for one that is middling
    # everywhere, and the blended number cannot tell those apart.
    _mkt = v.get("by_market") or {}
    if len(_mkt) > 1:
        _mrows = [[Paragraph("<b>Market</b>", S["cellsm"]),
                   Paragraph("<b>Questions</b>", S["cellsm"]),
                   Paragraph("<b>Named you</b>", S["cellsm"]),
                   Paragraph("<b>Linked to you</b>", S["cellsm"])]]
        for name, m in sorted(_mkt.items(),
                              key=lambda kv: -(kv[1].get("citation_rate") or 0)):
            _mrows.append([
                Paragraph(f"<b>{_p(name)}</b>", S["cellsm"]),
                Paragraph(str(m.get("questions") or 0), S["cellsm"]),
                Paragraph(f"{m.get('mention_rate') or 0}%", S["cellsm"]),
                Paragraph(f"{m.get('citation_rate') or 0}%", S["cellsm"]),
            ])
        _mt = Table(_mrows, colWidths=[3.0 * inch, 1.0 * inch, 1.3 * inch,
                                       1.3 * inch])
        _mt.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
            ("LINEBELOW", (0, 1), (-1, -1), 0.35, colors.HexColor("#F1F4F7")),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        _best = max(_mkt.items(), key=lambda kv: kv[1].get("citation_rate") or 0)
        _worst = min(_mkt.items(), key=lambda kv: kv[1].get("citation_rate") or 0)
        _lead = ("The figures above are an average across your markets, and "
                 "an average is true of none of them.")
        if (_best[1].get("citation_rate") or 0) > (_worst[1].get("citation_rate") or 0):
            _lead += (f" You are strongest in {_p(_best[0])} and weakest in "
                      f"{_p(_worst[0])}.")
        out += [Spacer(1, 14),
                KeepTogether([Paragraph("Market by market", S["h3"]),
                              Paragraph(_lead, S["small"]),
                              Spacer(1, 6), _mt])]

    out += _ai_sources(v, S, rep=(meta.get("extras") or {}).get("reputation"))
    out += _ai_examples(v, S, brand=_brand)

    if ment > cite:
        out.append(Spacer(1, 8))
        out.append(_banner("", f"Being named is not the same as being linked "
                               f"to. These tools said your name in {ment}% of "
                               f"answers and linked to your site in only "
                               f"{cite}% - so they already know who you are, "
                               f"and are sending the reader somewhere else "
                               f"for the detail.", SEQ, S))

    # A GOOGLE REDIRECT IS NOT A COMPETITOR.
    #
    # The chart's top row was vertexaisearch.cloud.google.com with 7.4% - the
    # host Gemini wraps its citation links in. It is Google's own plumbing
    # showing through our parser, it outranked the client on their own chart,
    # and the first question anyone sensible asks is "what is that?".
    #
    # Filtered at render, so reports already produced are fixed on reload.

    # THE OLD SHARE-OF-VOICE GRID LIVED HERE AND HAS BEEN MERGED UPWARDS.
    #
    # It listed the same domains as "Where those answers came from" with a
    # share meter and nothing else, so the section printed two tables of the
    # same eight websites a page apart - and the second one, which the reader
    # met last, was the one that said the least. The meter was worth keeping
    # and moved into the merged table; the ranked list, the gap sentence and
    # everything else it did are up there now, next to the columns that say
    # what to do about each row.

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
    "TECH": "whether search engines can find, fetch and read the pages",
    "URL": "whether addresses are readable and organized by topic",
    "SEC": "whether the site is served securely end to end",
    # WAS: "whether Google can tell which version of a page is the real one".
    # Which version of what? The reader has not been told the page HAS
    # versions - that is the part of canonicalization that needs saying, and
    # it is the whole of what the area checks.
    "CANON": "whether one page reachable at several web addresses is counted "
             "once instead of as duplicates",
    "PERF": "how fast the site feels to a real visitor on a real phone",
    "ONP": "titles, headings and copy — what a page says it is about",
    "MOB": "how the site behaves on a phone, which is most of the traffic",
    "SCHEMA": "the machine-readable labels that produce rich search results",
    "INTL": "whether the right language and region version is served",
    # WAS: "whether the code is clean enough not to get in its own way".
    # A metaphor standing in for a fact. It says nothing about WHAT is
    # checked, so a reader who wanted to know why this counts as a strength
    # learned only that the code is not tripping over itself.
    "HTML": "whether the page markup is valid, so browsers and search engines "
            "read it the same way",
    "EEAT": "the signals that show a real, qualified business is behind the site",
    "GEO": "whether AI tools can read the site and link to it in an answer",
    "OFF": "who links to the site, and what that says about its authority",
    "CONS": "whether tracking waits for consent, which is a legal question",
}


def _strength(text, S, width=6.55 * inch):
    """One strength as a card, with a plain-English line about the area."""
    # TWO NAME MAPS, AND THE CARDS WERE WRITTEN WITH THE OTHER ONE.
    #
    # engine/report calls it "HTTPS & Security"; engine/summarise, which
    # writes these cards, calls it "HTTPS and security". Matching against one
    # map meant any area whose two names differ got no plain-English line at
    # all - the whole reason the card exists. Both maps, longest name first so
    # "Search Console" cannot win inside "Google Search Console".
    from .report import SECTION_NAMES as _SN
    from .summarise import SECTION_NAMES as _SN2
    names = []
    for src in (_SN, _SN2):
        for code, name in src.items():
            if SECTION_MEANS.get(code):
                names.append((name.lower(), code))
    names.sort(key=lambda x: -len(x[0]))
    low = (text or "").lower()
    means, seen_codes = [], set()
    for name, code in names:
        if name in low and code not in seen_codes:
            seen_codes.add(code)
            means.append(SECTION_MEANS[code])
        if len(means) == 2:
            break
    gloss = ""
    if means:
        gloss = means[0] if len(means) == 1 else f"{means[0]}; {means[1]}"
        gloss = gloss[0].upper() + gloss[1:] + "."

    # "Canonicalization: 6 of 6 checks passed." - the area is the card's
    # subject, so it is set as one, and what follows is the measurement.
    head, _, rest = str(text or "").partition(": ")

    # THE COUNT GOES IN THE CORNER, NOT ON A LINE OF ITS OWN.
    #
    # "4 of 4 checks passed." was a full-width sentence saying a thing a badge
    # says in five characters, and it cost every card a line - eight lines
    # across the grid, which is most of the reason Biggest Opportunity kept
    # landing on page 3 with half of page 2 empty. As a chip in the top right
    # it also reads better: the score is a label on the card, not a claim
    # competing with the area name for the reader's attention.
    #
    # Anything that is not a plain count stays in the body. "8 of 9 checks
    # passed, scoring 94 out of 100" carries a second fact, and squeezing that
    # into a corner chip would lose it.
    # THE SCORE IN THE CORNER, AND THE SENTENCE GONE.
    #
    # First pass moved a bare "4 of 4 checks passed." into a badge and left
    # anything richer in the body - so the HTML card still spent a full line
    # on "8 of 9 checks passed, scoring 94 out of 100." while its neighbours
    # had none, and the grid came out ragged. Worse, that line is the least
    # interesting thing on a card whose job is to say what the area IS: the
    # client does not care that one of nine checks missed, they care that the
    # area scores 94.
    #
    # So the SCORE wins the badge where there is one, the ratio takes it where
    # there is not, and the sentence is dropped either way. Four cards, four
    # lines back - which is what finally gives Biggest Opportunity room on
    # page 2 rather than leaving it one line short.
    _sc = re.search(r"scoring\s+(\d+)\s+out\s+of\s+100", rest or "", re.I)
    _m = re.match(r"^\s*(\d+)\s+of\s+(\d+)\s+checks?\s+passed\b", rest or "",
                  re.I)
    badge, body_rest = "", rest
    if _sc:
        badge, body_rest = _sc.group(1), ""
    elif _m:
        badge, body_rest = f"{_m.group(1)}/{_m.group(2)}", ""
    body = f"<b>{_p(head)}</b>" + (f"<br/>{_p(body_rest)}" if body_rest
                                   else "")
    inner = [Paragraph(body, S["cell"])]
    if gloss:
        inner.append(Spacer(1, 3))
        inner.append(Paragraph(
            f"<font color='#4A5461'>{_p(gloss)}</font>", S["cellsm"]))
    if badge:
        # Wide enough that "10/12" cannot wrap. The first attempt was 0.52in
        # and reportlab broke "4/4" across two lines, which is a worse version
        # of the line this change removed.
        _bst = ParagraphStyle("passbadge", parent=S["cellsm"],
                              fontName=_fonts.BOLD, fontSize=8.5, leading=11,
                              alignment=2, textColor=colors.HexColor("#1E7A45"))
        _bw = 0.62 * inch
        t = Table([[inner, Paragraph(badge, _bst)]],
                  colWidths=[width - _bw, _bw])
        _pad = [("LEFTPADDING", (1, 0), (1, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 4)]
    else:
        t = Table([[inner]], colWidths=[width])
        _pad = []
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F7F4")),
        ("ROUNDEDCORNERS", [10, 10, 10, 10]),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, colors.HexColor("#1E7A45")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 13),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        # Two points off the top and one off the bottom of each card. Trivial
        # on its own; there are two rows of them, and this is one of four
        # small trims that together buy the ~15pt Biggest Opportunity needed to
        # join Current Strengths on page 2 instead of opening page 3 alone.
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ] + _pad))
    return t


def _strength_grid(items, S):
    """
    Strength cards two to a row, each half the measure.

    A full-measure card holding one short sentence is a band of pale green
    across the page with an inch of empty space on the right of it, three
    times over. Half-width puts them side by side, which is also how they
    read: parallel pieces of good news, not a sequence.
    """
    if not items:
        return []
    half = 3.18 * inch
    cards = [_strength(it, S, width=half) for it in items]
    rows = [cards[i:i + 2] for i in range(0, len(cards), 2)]
    for r in rows:
        while len(r) < 2:
            r.append("")
    grid = Table(rows, colWidths=[3.28 * inch, 3.28 * inch])
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 10),
        ("RIGHTPADDING", (1, 0), (1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    # RETURNED BARE, NOT WRAPPED.
    #
    # It used to come back as KeepTogether([grid]), and the caller then bound
    # THAT inside another KeepTogether with the heading. A KeepTogether inside
    # a KeepTogether cannot measure itself - the inner one has no canvas while
    # the outer is wrapping - and reportlab's fallback for that is to assume
    # it will not fit. Which is why "Current Strengths" kept jumping to the
    # next page with six inches of clear space above it.
    #
    # The caller does the binding, once.
    return [grid]


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


class Shot(Flowable):
    """
    A screenshot with rounded corners and a soft drop shadow.

    reportlab has no image masking, so the rounding is done by drawing the
    image inside a clipped rounded path - the same trick the segment bar uses
    for its ends. The shadow is three offset rounded rects at decreasing
    alpha underneath, which is cheap and prints without banding.

    Without this a screenshot is a hard-edged rectangle butted against the
    page, and it reads as a paste rather than as part of the document.
    """

    def __init__(self, png, width, height, radius=7, draw_h=None):
        super().__init__()
        self.png, self.width, self.height, self.radius = png, width, height, radius
        # The height the image is DRAWN at, which can exceed the box. A tall
        # capture is cropped to the top of the page rather than squeezed into
        # the box - squeezing is what made the homepage look smushed.
        self.draw_h = draw_h or height

    def wrap(self, aw, ah):
        if self.width > aw:
            k = aw / self.width
            self.height *= k
            self.draw_h *= k
            self.width = aw
        return self.width, self.height + 5

    def draw(self):
        from reportlab.lib.utils import ImageReader
        c = self.canv
        w, h, r = self.width, self.height, self.radius
        # Shadow first, under everything, offset down and out.
        for i, (dx, dy, a) in enumerate(((0, -2.5, 0.10), (0, -1.5, 0.09),
                                         (0, -0.6, 0.08))):
            c.saveState()
            c.setFillColor(colors.HexColor("#002D58"))
            c.setFillAlpha(a)
            c.roundRect(dx + i * 0.4, dy - i * 0.4, w - i * 0.8, h, r,
                        stroke=0, fill=1)
            c.restoreState()
        c.saveState()
        p = c.beginPath()
        p.roundRect(0, 0, w, h, r)
        c.clipPath(p, stroke=0, fill=0)
        try:
            dh = self.draw_h or h
            # Top-aligned inside the clip: y is where the BOTTOM of the image
            # goes, so a taller-than-box image hangs below and is cropped.
            c.drawImage(ImageReader(io.BytesIO(self.png)), 0, h - dh, width=w,
                        height=dh, preserveAspectRatio=False, mask="auto")
        except Exception:  # noqa: BLE001
            pass
        c.restoreState()
        c.setStrokeColor(colors.HexColor("#E6EAEE"))
        c.setLineWidth(0.6)
        c.roundRect(0, 0, w, h, r, stroke=1, fill=0)


def _png_size(png: bytes):
    """
    (width, height) from the PNG header, without an image library.

    Pillow is not in requirements — the annotation is done in CSS before the
    capture precisely so no image library is needed — so the only honest way
    to know a screenshot's shape is to read its IHDR, which is at a fixed
    offset in every PNG ever written. Assuming a shape instead is what
    squashed the homepage: an 1280x820 viewport drawn into a 1280x620 box,
    with preserveAspectRatio off, is a 25% vertical squeeze applied to the
    first picture in the document.
    """
    try:
        if png[:8] == b"\x89PNG\r\n\x1a\n" and png[12:16] == b"IHDR":
            import struct
            w, h = struct.unpack(">II", png[16:24])
            if w and h:
                return int(w), int(h)
    except Exception:  # noqa: BLE001
        pass
    return None, None


def _hero_shot(meta, S):
    """
    The homepage, near the top, before any finding.

    It is not evidence and it is not marked up - it is the thing the whole
    document is about, and putting it on the cover is what makes the rest read
    as being about a real site rather than about a spreadsheet.
    """
    shots = (meta.get("extras") or {}).get("screenshot_blobs") or []
    home = next((s for s in shots if s.get("kind") == "homepage"), None) \
        or next((s for s in shots if not s.get("boxed")), None)
    if not home or not home.get("png"):
        return []
    # ITS OWN SHAPE, NOT AN ASSUMED ONE.
    #
    # The capture is a 1280x820 viewport (engine/screenshots.capture), and
    # this drew it 1280x620 with preserveAspectRatio off - every face on the
    # page a quarter too short. Read the header; fall back to the viewport
    # shape only if the bytes will not parse.
    # NARROWER THAN THE MEASURE, ON PURPOSE.
    #
    # The capture is decorative - it is the thing the document is about, not a
    # finding - and at full measure a wide viewport shot is 220pt of page 2
    # spent on a picture nobody reads. Insetting it buys the Biggest
    # Opportunity block its place beside Current Strengths, which is content,
    # and an inset image also reads as a figure rather than as a banner.
    w = 5.9 * inch
    iw, ih = _png_size(home["png"])
    ratio = (ih / iw) if (iw and ih) else (820 / 1280)
    # A full-page capture would run past the bottom of the page and print as a
    # strip of thumbnail. Cap the BOX and crop to the top of the image; the
    # image itself is still drawn at its own proportions.
    full = w * ratio
    return [Spacer(1, 4),
            Shot(home["png"], w, min(full, 3.9 * inch), draw_h=full),
            Spacer(1, 9)]


def _evidence(meta, S, catalog=None):
    """Annotated screenshots — the problem, in a picture, on their own site."""
    catalog = catalog or {}
    shots = (meta.get("extras") or {}).get("screenshot_blobs") or []
    # THE HERO ALREADY SHOWED THEM THE HOMEPAGE.
    #
    # "What This Looks Like" was printing the same unmarked full-page capture
    # under a caption promising red outlines, for findings like "no HTTPS"
    # that have nothing on the page to outline. A screenshot earns its place
    # here only when something on it is marked.
    shots = [s for s in shots if s.get("boxed")]
    if not shots:
        return []
    from reportlab.platypus import Image as RLImage
    head = [Paragraph("The Problems, On Your Pages", S["h2"]),
            _rule(),
           # WAS: "Captured from your live site. Red outlines mark the
           # elements the check flagged." Two problems: it described our
           # process rather than their site, and it promised outlines that
           # only some findings have — an HTTPS failure has nothing on the
           # page to outline, so the reader hunts for a mark that was never
           # drawn.
            # WAS "What This Looks Like" over "pages as they loaded, with the
            # thing each check flagged outlined in red" - a title that names
            # nothing and a line that describes our method. The question it
            # left was the right one: what is the red box around? Each caption
            # answers that for its own picture; the heading just has to say
            # what the section is.
            Paragraph("Your own pages, with the exact thing a check flagged "
                      "outlined in red. The caption under each says what the "
                      "outline is around.", S["small"]),
            Spacer(1, 8)]
    out = []
    # ALL OF THEM ON ONE PAGE.
    #
    # Three shots at full measure is twelve inches of picture, so the section
    # ran to two pages and the third shot sat alone under nothing. The page
    # has about nine inches once the heading and the captions are paid for -
    # so the shots are sized to fit the page they are on rather than to fill
    # the measure.
    n_shots = len(shots[:3])
    room = (9.1 * inch - 0.75 * inch) / max(1, n_shots)      # heading + rules
    for sh in shots[:3]:
        try:
            iw, ih = _png_size(sh["png"])
            ratio = (ih / iw) if (iw and ih) else 820 / 1280
            # Width first, then shrink to the height this page can give it.
            sw = min(6.4 * inch, (room - 0.32 * inch) / ratio)
            full = sw * ratio
            # A CAPTURE TALLER THAN A PAGE CANNOT BE LAID OUT AS ONE FLOWABLE.
            #
            # Our own captures are a 1280x820 viewport and fit comfortably.
            # A stored shot from another source can be a full-page image -
            # 1280 by six thousand - which asks reportlab for a flowable
            # thirty inches tall, and what comes out is a strip at the top of
            # an otherwise blank page. Cap the box and crop to the top, the
            # way the cover shot does.
            img = Shot(sh["png"], sw, full, draw_h=full)
        except Exception:
            continue
        # WHAT IS ACTUALLY MARKED, NOT THE CHECKPOINT'S NAME.
        #
        # The caption read "Expert-written content - http://ootenlawfirm.com/"
        # under a picture of a homepage, and the client's question was simply
        # "what is this?" - fair, because the checkpoint name describes what
        # we were LOOKING for, not what the red box is around.
        mark = MARK_LABEL.get(sh.get("checkpoint") or "")
        name = (catalog.get(sh.get("checkpoint") or "", {}) or {}).get(
            "checkpoint") or sh.get("caption") or ""
        where = (sh.get("url") or "").split("//")[-1].rstrip("/")
        cap_txt = (f"In red: {mark}. " if mark else "")
        cap_txt += f"Checked for \u201c{name}\u201d on {where}." if name \
            else where
        cap = Paragraph(f"<font color='#52514e'>{_p(cap_txt)}</font>",
                        S["muted"])
        # Flat, for the same reason as the strength grid: these are bound
        # into one KeepTogether below, and nesting them inside their own
        # would leave the outer one unable to measure anything.
        out += [img, Spacer(1, 3), cap, Spacer(1, 14)]
    if not out:
        return []
    # One block: the heading and every shot, together or not at all.
    return [KeepTogether(head + out)]


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
        # `local_service` is a key in our config, not a description of a
        # business. Same class of leak as CONS reaching the client.
        _VERT = {"local_service": "Local service business",
                 "ecommerce": "Online retailer",
                 "finance_ymyl": "Finance / regulated advice",
                 "publisher": "Publisher", "saas": "Software"}
        _bm = meta.get("business_model") or meta.get("vertical") or ""
        facts.append(("Business model",
                      _VERT.get(str(_bm).strip().lower(),
                                str(_bm).replace("_", " ").strip().capitalize())))
    # PRIMARY MARKETS IS NOT A FINDING.
    #
    # Thirteen counties the client typed into our own form, printed back to
    # them as thirteen pills across four rows, is the largest block on the
    # first page and it tells them something they told us. The snapshot is
    # for what we OBSERVED. `_market_pills` stays — it is still the right
    # rendering if this ever earns its place back — but the row does not.
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

    # THE HOMEPAGE GOES HERE, NOT AT THE TOP.
    #
    # It was the first thing after the cover facts, and four inches of
    # screenshot pushed the score gauge - the number the whole document is
    # about - onto page two. Sitting between the coverage bars and the
    # Executive Summary it does the same job (this report is about a real
    # site) without costing the reader the headline.
    for fl in _hero_shot(meta, S):
        story.append(fl)

    # ------------------------------------------------ executive summary
    # One definition per term, at first use, document-wide. Seeded here rather
    # than beside the findings because the summary is where the words first
    # appear.
    defined = set()
    if summary:
        story.append(Paragraph("Executive Summary", S["h2"]))
        story.append(_rule())
        if summary.get("overview"):
            story.append(Paragraph(_pl(summary["overview"]), S["body"]))
        if summary.get("headline"):
            story.append(_banner("", summary["headline"], SEQ, S))
            story.append(Spacer(1, 8))
        # NO DEFINITIONS IN THE EXECUTIVE SUMMARY.
        #
        # They started here on the argument that a term should be explained at
        # first mention. True, and this is the wrong place to apply it: the
        # summary is four paragraphs someone reads in one go, and dropping a
        # tinted box between them to explain a word used once breaks the only
        # part of the document that is meant to be read straight through.
        #
        # Every term defined here appears again beside a finding, where the
        # reader has to act on it - which is where the definition is worth the
        # interruption. `defined` therefore stays empty until Top Findings.
        def _define(text, limit=3):
            return

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
                story.append(Paragraph(_pl(items), S["body"]))
                block.append(items)
            elif key == "working":
                # STRENGTHS AS CARDS, EACH SAYING WHAT THE AREA IS.
                #
                # "Canonicalization, International SEO and Mobile SEO came back
                # clean" is true and lands on a client who does not know what
                # canonicalization is — so the good news reads as jargon and
                # gets skipped, which is a waste of the one section that is
                # not asking them for anything.
                # AND THE HEADING GOES WITH THEM.
                #
                # KeepTogether around the grid alone left "Current Strengths"
                # at the foot of page 2 with four inches of nothing under it
                # and the cards on page 3. The heading is not content; it
                # travels with the block it names. `story` already carries the
                # heading, so it is pulled back off and bound to the grid.
                head = story.pop()
                for fl in _strength_grid(list(items), S):
                    story.append(KeepTogether([head, Spacer(1, 4), fl]))
                    head = Spacer(1, 0)
                # NO DEFINITION BUBBLE UNDER THE STRENGTHS.
                #
                # `block` is what gets scanned for terms to define, and adding
                # the strengths put a full-width "Canonical tag" bubble under
                # three cards that had ALREADY said, in plain English, what
                # canonicalization is. The term is defined at its next real
                # appearance instead - beside a finding, where the reader needs
                # it to act on something. Deliberately not appended.
            else:
                # Short lists read better as prose than as bullets; a bulleted
                # list of two items looks like a form that was filled in.
                #
                # AND THE HEADING TRAVELS WITH THE FIRST LINE. The trims above
                # bought the space for this block to sit on page 2; binding it
                # is what stops a future change re-separating "Biggest
                # Opportunity" from the sentence that says what it is. Same
                # rule the strength cards already follow.
                head = story.pop()
                for j, it in enumerate(items):
                    para = Paragraph(_pl(it), S["body"])
                    story.append(KeepTogether([head, para]) if j == 0 else para)
                    head = Spacer(1, 0)
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
            block.append(Paragraph(
                f"<b>What we found.</b> {_pl(t.get('finding'))}",
                                   S["body"]))
            if t.get("why"):
                block.append(Paragraph(f"<b>Why it matters.</b> {_pl(t['why'])}",
                                       S["body"]))
            # Scope, not instructions — see SERVICE_ACTION in summarise.py.
            if t.get("service") or t.get("action"):
                block.append(Paragraph(
                    f"<b>How we handle it.</b> "
                    f"{_pl(t.get('service') or t.get('action'))}", S["body"]))
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

    for fl in _evidence(meta, S, catalog):
        story.append(fl)

    # ------------------------------------------------ area snapshot
    # No forced page break here: the exec summary rarely fills a page, and a
    # break left a third of page 2 blank. KeepTogether keeps the chart intact.
    story.append(Spacer(1, 6))
    secs = [(k, v) for k in ORDER if (v := (scores.get("sections") or {}).get(k))]
    # Ranked worst-first: the reader should not have to scan a table to find
    # where the work is. Unassessed areas sort last — they are not "worst".
    ranked = sorted(secs, key=lambda kv: (kv[1].get("score") is None,
                                          kv[1].get("score") if kv[1].get("score")
                                          is not None else 0))
    # THE HEADING TRAVELS WITH THE CHART.
    #
    # KeepTogether was around the chart ALONE, so when the chart did not fit
    # reportlab moved the chart and left "Scores by Area", its rule and its
    # one-line intro sitting at the top of the previous page with eight inches
    # of nothing under them. A heading is not content; binding the whole block
    # is what "don't split a header from its section" actually means here.
    story.append(KeepTogether([
        Paragraph("Scores by Area", S["h2"]),
        _rule(),
        Paragraph("Ordered by severity, with the areas to fix first at the "
                  "top.", S["small"]),
        Spacer(1, 8),
        SectionBars([(SHORT_NAMES.get(k, SECTION_NAMES[k]), v.get("score"),
                      v.get("rating")) for k, v in ranked], width=6.55 * inch),
    ]))
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
                         Paragraph(_linkify(_agree(_p(_redact.client(f.get("evidence"))))),
                                   S["cell"])])
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
        # ONE PAGE, AND SAY WHAT WAS LEFT OFF.
        #
        # 25 rows ran a row and a half past the bottom, so the table broke and
        # page nine carried a repeated header and one keyword. Twenty fits
        # under the heading and the intro with room for the two-line URLs, and
        # the count below says how many more there are rather than letting the
        # list end without explanation.
        _SHOWN = 20
        for r in rk["rows"][:_SHOWN]:
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
        for i, r in enumerate(rk["rows"][:_SHOWN], start=1):
            if (r.get("position") or 999) <= 10:
                # Light tint, dark text. The full-strength ramp color put a
                # mid-blue number on a mid-blue field and lost the number.
                st.append(("BACKGROUND", (1, i), (1, i), SEV_PILL["Low"][0]))
                st.append(("TEXTCOLOR", (1, i), (1, i), SEV_PILL["Low"][1]))
        t.setStyle(TableStyle(st))
        story.append(t)
        _more = max(0, len(rk["rows"]) - _SHOWN)
        if _more:
            story.append(Spacer(1, 6))
            story.append(Paragraph(
                f"<font color='#52514e'>Showing the top {_SHOWN} by position. "
                f"{_more} further ranking keyword"
                f"{'s' if _more != 1 else ''} came back in the same pull.</font>",
                S["small"]))
    elif rk and not rk.get("available"):
        story.append(Paragraph("Keyword Rankings &amp; Industry Benchmarks", S["h2"]))
        story.append(_rule())
        story.append(Paragraph(
            f"Not collected — {_p(rk.get('reason'))}. This section is omitted rather "
            f"than estimated.", S["small"]))

    ai_block = _ai_visibility(meta, S, findings)
    if ai_block:
        story.append(PageBreak())
        for fl in ai_block:
            story.append(fl)

    # ------------------------------------------------ reputation
    # Its own page: it opens with a PageBreak of its own because the section
    # is a change of subject, not a continuation. Everything above is the
    # client's site; this is everybody else's pages about the client.
    for fl in _reputation(meta, S):
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
                block.append(Paragraph(_pl(phase["rationale"]), mid))
            block.append(Spacer(1, 5))

            # Work items, not instructions: the checkpoint name is what we are
            # taking on. The fix itself is the engagement.
            cells = []
            for a in actions[:14]:
                label = str(a).split(" — ")[0].strip().rstrip(".")
                cells.append(Paragraph(f"•  {_pl(label)}", S["cellsm"]))
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
    # THE LEGEND WAS EXPLAINING ITSELF, NOT THE WORDS.
    #
    # "Reference is a number with no pass or fail attached to it - a backlink
    # count is neither good nor bad on its own" is a definition of a category
    # of finding, followed by an example of the category. Two abstractions
    # before the reader learns what to DO with a row marked Reference.
    #
    # Each word now gets the shortest sentence that says what the row is.
    story.append(Paragraph(
        "By area, with what each status means. "
        "<b>Reference</b> - a figure we recorded for you, like your backlink "
        "count. Nothing to fix. "
        "<b>Missing</b> - the check looked for something and it is not there. "
        "<b>In review</b> - a check only a person can judge; we do it as part "
        "of the work and it has no verdict yet. "
        "<b>Need Access</b> - we could not read this without your Search "
        "Console or Analytics."
        + (f" {n_na} checks that do not apply to a site like yours are left "
           f"out." if n_na else ""), S["small"]))

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
        # A SCAN IS NOT A COMPLIANCE OPINION, AND THIS SECTION IS THE ONE
        # WHERE THAT MATTERS.
        #
        # Every other area here is a technical judgment we can stand behind.
        # Consent is law, it varies by state, it changes, and this is one
        # browser in one location at one moment. Saying so once, at the top of
        # the section, is the difference between reporting what fired and
        # appearing to certify that a client is in the clear.
        _pre = []
        if k == "CONS":
            # WAS, in front: "What this section is. A record of what the site
            # did during one automated visit - which tags fired, when, and
            # what the banner did." The heading above it already says what the
            # section is, and the rows below show the tags and the timing - so
            # it explained the table to someone who was looking at the table.
            # What earns its place is the legal caveat, which is the whole
            # reason the banner exists.
            _pre = [_banner("", "Privacy law varies by state and changes; "
                                "this is not a legal opinion and does not "
                                "certify compliance. Use it to decide what to "
                                "fix and where it matters.", ATLAS, S),
                    Spacer(1, 8)]
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
                    # SIT ON THE ID'S OWN LINE, not above it.
                    #
                    # 1pt of top padding put the bulb's baseline a couple of
                    # points high, so it floated over the text rather than
                    # beside it - visible the moment two rows in a column have
                    # one and the row between them does not.
                    #
                    # 2.5pt was measured against the lamp's BOX. The ink
                    # inside it is top-heavy - a circle of glass over two thin
                    # legs - so a box that lines up leaves the bulb reading
                    # high. 4pt sits the glass inside the cap-height band of
                    # "ONP-13", which is where the eye expects it.
                    ("TOPPADDING", (1, 0), (1, 0), 4.0),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
            # The name, and where the name is jargon, one line saying what
            # the check looks at.
            _gloss = CHECK_MEANS.get(cid)
            _name = [Paragraph(_p(m.get("checkpoint")), S["cell"])]
            if _gloss:
                _name.append(Paragraph(
                    f"<font color='#8096AC'>{_p(_gloss)}</font>", S["cellsm"]))
            data.append([ident, _name,
                         _pill(_status_word(f["status"], cid, f.get("source") or ""),
                               STATUS_PILL, S,
                               0.86 * inch),
                         Paragraph(_linkify(_agree(_p(_redact.client(f.get("evidence"))))),
                                   S["cell"])])
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
        for _fl in _pre:
            story.append(_fl)
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
                             f"third-party data."
         + (f" {_cf['count']} of them were measured on an earlier run of this "
            f"site and carried forward rather than repeated, so they describe "
            f"the site as of that run."
            if (_cf := ((meta.get("extras") or {}).get("carried_forward") or {})
                ).get("count") else "")),
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

    doc.build(_keep_headings_with_content(story, S))
    return buf.getvalue()


def _banner(title, body, color, S):
    # Title is optional: used with one for warnings, without one for a pulled
    # quote. An empty <b></b> would leave a stray blank line.
    head = f"<b>{_p(title)}</b><br/>" if title else ""
    t = Table([[Paragraph(head + f"<font size={'8.5' if title else '10'}>"
                          f"{_pl(body)}</font>", S["body"])]],
              colWidths=[6.6 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LINEBEFORE", (0, 0), (0, -1), 3, color),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t
