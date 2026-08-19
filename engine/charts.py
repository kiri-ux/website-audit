"""
Vector chart primitives for the PDF report.

Deliberately hand-drawn on the canvas rather than pulled from a charting
library. Three reasons:

  * They stay vector. A client zooms into the PDF and the arc is still smooth,
    and the whole chart set costs a couple of KB rather than a megabyte of
    rasterized PNG.
  * No new runtime dependency. reportlab is already here; matplotlib is not,
    and adding it to the worker image for four charts is a bad trade.
  * We control the honesty rules. An unassessed section MUST NOT draw as a
    zero-length bar — a zero-length bar reads as "scored zero", which is
    exactly the lie the whole Need Access model exists to prevent. It draws
    hollow, with a label saying so. A library would happily plot None as 0.

Encoding rules, carried over from the HTML report and dashboard:
  * Severity is an ORDERED scale, so it gets a single-hue ordinal ramp.
  * Score magnitude is sequential, so it gets one hue and varies length only.
  * Status colors never carry meaning alone — every segment ships a text label.
"""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import Flowable

INK     = colors.HexColor("#0b0b0b")
INK2    = colors.HexColor("#52514e")
MUTED   = colors.HexColor("#898781")
LINE    = colors.HexColor("#e6e5e1")
TRACK   = colors.HexColor("#eceae6")
SEQ     = colors.HexColor("#2a78d6")
SEQ_DIM = colors.HexColor("#9cc3f0")

ORD = {"Critical": colors.HexColor("#104281"), "High": colors.HexColor("#256abf"),
       "Medium": colors.HexColor("#3987e5"), "Low": colors.HexColor("#86b6ef")}

# Rating bands, used only to place the marker on the gauge track. The number
# and the word are both printed, so color is never the sole carrier.
BANDS = [(0, 50), (50, 70), (70, 85), (85, 100)]


def _fit(c, text, font, size, maxw):
    """Shrink then truncate, so a long label degrades instead of overlapping."""
    while size > 5.5 and c.stringWidth(text, font, size) > maxw:
        size -= 0.25
    if c.stringWidth(text, font, size) > maxw:
        while text and c.stringWidth(text + "…", font, size) > maxw:
            text = text[:-1]
        text += "…"
    return text, size


class ScoreGauge(Flowable):
    """
    Overall score as a 270° arc.

    The arc gives the number a context the number alone does not have: the
    reader sees 62/100 as two-thirds of the way round rather than as a bare
    integer they have to calibrate themselves.
    """

    def __init__(self, score, rating="", size=1.85 * inch, label="Overall score"):
        super().__init__()
        self.score, self.rating, self.size, self.label = score, rating, size, label
        # Height equals the diameter on purpose: the rating and caption are
        # drawn INSIDE the arc's bottom gap, not below the flowable. Anything
        # drawn below y=0 escapes the cell and lands on the panel border.
        self.width, self.height = size, size

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        c = self.canv
        s = self.size
        thick = s * 0.105
        pad = thick / 2 + 1
        x1, y1 = pad, pad
        x2, y2 = s - pad, s - pad
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        r = (x2 - x1) / 2

        c.saveState()
        c.setLineWidth(thick)
        c.setLineCap(1)
        c.setStrokeColor(TRACK)
        c.arc(x1, y1, x2, y2, 225, -270)

        if self.score is not None:
            frac = max(0.0, min(1.0, self.score / 100.0))
            if frac > 0:
                c.setStrokeColor(SEQ)
                c.arc(x1, y1, x2, y2, 225, -270 * frac)

        # centered readout
        c.setFillColor(INK if self.score is not None else MUTED)
        num = str(self.score) if self.score is not None else "—"
        c.setFont("Helvetica-Bold", s * 0.27)
        c.drawCentredString(cx, cy + s * 0.005, num)
        if self.score is not None:
            c.setFont("Helvetica", s * 0.08)
            c.setFillColor(MUTED)
            c.drawCentredString(cx, cy - s * 0.10, "/ 100")

        # rating word sits in the arc's bottom gap — inside the flowable
        c.setFillColor(INK2)
        c.setFont("Helvetica-Bold", s * 0.095)
        txt = self.rating or ("Not scored" if self.score is None else "")
        c.drawCentredString(cx, cy - r * 0.80, txt)
        c.setFont("Helvetica", s * 0.072)
        c.setFillColor(MUTED)
        c.drawCentredString(cx, cy - r * 0.80 - s * 0.085, self.label)
        c.restoreState()


class SectionBars(Flowable):
    """
    Every audit area in one ranked view, worst first.

    `rows` is [(label, score_or_None, rating)]. A None score draws as a hollow
    dashed track labelled "Not assessed" — never as a zero-length bar.
    """

    def __init__(self, rows, width=6.4 * inch, row_h=13.5, label_w=1.95 * inch,
                 value_w=1.5 * inch):
        super().__init__()
        self.rows = rows
        self.width = width
        self.row_h = row_h
        self.label_w = label_w
        self.value_w = value_w
        self.height = row_h * len(rows) + 4

    def wrap(self, aw, ah):
        self.width = min(self.width, aw)
        return self.width, self.height

    def draw(self):
        c = self.canv
        bar_x = self.label_w + 6
        bar_w = self.width - self.label_w - self.value_w - 12
        bar_h = self.row_h * 0.52
        worst = [i for i, (_, sc, _) in enumerate(self.rows) if sc is not None][:3]

        for i, (label, sc, rating) in enumerate(self.rows):
            y = self.height - (i + 1) * self.row_h + (self.row_h - bar_h) / 2

            # Measure with the font we will ACTUALLY draw in — bold is wider,
            # and fitting against regular is how a label ends up under the bar.
            font = "Helvetica-Bold" if i in worst else "Helvetica"
            c.setFillColor(INK if i in worst else INK2)
            txt, size = _fit(c, label, font, 8, self.label_w)
            c.setFont(font, size)
            c.drawString(0, y + bar_h * 0.25, txt)

            if sc is None:
                c.saveState()
                c.setStrokeColor(LINE)
                c.setLineWidth(0.6)
                c.setDash(2, 2)
                c.rect(bar_x, y, bar_w, bar_h, stroke=1, fill=0)
                c.restoreState()
                c.setFillColor(MUTED)
                c.setFont("Helvetica-Oblique", 7)
                c.drawString(bar_x + 4, y + bar_h * 0.28, "Not assessed")
                c.setFont("Helvetica", 7.5)
                c.drawRightString(self.width, y + bar_h * 0.25, "—")
                continue

            c.setFillColor(TRACK)
            c.rect(bar_x, y, bar_w, bar_h, stroke=0, fill=1)
            c.setFillColor(SEQ if i in worst else SEQ_DIM)
            c.rect(bar_x, y, bar_w * max(0.0, min(1.0, sc / 100.0)), bar_h,
                   stroke=0, fill=1)

            # Fit the value to its own column. "70  Needs Improvement" is more
            # than twice the width of "100  Strong", and at a fixed size the
            # long ones ran back over the bar.
            c.setFillColor(INK2)
            txt = f"{sc}  {rating or ''}".strip()
            txt, size = _fit(c, txt, "Helvetica-Bold", 7.5, self.value_w - 4)
            c.setFont("Helvetica-Bold", size)
            c.drawRightString(self.width - 2, y + bar_h * 0.25, txt)
        # baseline under the block
        c.setStrokeColor(LINE)
        c.setLineWidth(0.4)
        c.line(0, 0, self.width, 0)


class SegmentBar(Flowable):
    """
    A single stacked bar with a labelled legend beneath.

    Used for the severity distribution and the coverage strip. `segments` is
    [(label, count, color)]. Segments with a zero count are dropped from the
    bar but KEPT in the legend showing 0, so the reader can tell "none of these"
    apart from "we didn't look".
    """

    def __init__(self, segments, width=6.4 * inch, bar_h=17, note=""):
        super().__init__()
        self.segments = [s for s in segments]
        self.width = width
        self.bar_h = bar_h
        self.note = note
        self.height = bar_h + 30 + (11 if note else 0)

    def wrap(self, aw, ah):
        self.width = min(self.width, aw)
        return self.width, self.height

    def draw(self):
        c = self.canv
        total = sum(max(0, n) for _, n, _ in self.segments) or 1
        y = self.height - self.bar_h
        x = 0.0
        for label, n, col in self.segments:
            if n <= 0:
                continue
            w = self.width * n / total
            c.setFillColor(col)
            c.rect(x, y, w, self.bar_h, stroke=0, fill=1)
            # count inside the segment only when it comfortably fits
            if w > 22:
                c.setFillColor(colors.white if col not in (TRACK, LINE) else INK2)
                c.setFont("Helvetica-Bold", 8)
                c.drawCentredString(x + w / 2, y + self.bar_h * 0.32, str(n))
            x += w

        # legend — every segment gets its word, so color is never load-bearing
        lx, ly = 0.0, y - 15
        c.setFont("Helvetica", 7.5)
        for label, n, col in self.segments:
            sw = c.stringWidth(f"{label} {n}", "Helvetica", 7.5) + 16
            if lx + sw > self.width:
                lx, ly = 0.0, ly - 11
            c.setFillColor(col)
            c.setStrokeColor(LINE)
            c.setLineWidth(0.5)
            # outlined so the palest swatch is still visible on white paper
            c.rect(lx, ly, 7, 7, stroke=1, fill=1)
            c.setFillColor(INK2)
            c.drawString(lx + 10, ly + 0.8, f"{label} {n}")
            lx += sw
        if self.note:
            c.setFillColor(MUTED)
            c.setFont("Helvetica-Oblique", 7.5)
            c.drawString(0, ly - 11, self.note)


class MiniMeter(Flowable):
    """Inline score meter for section headers — magnitude by length, one hue."""

    def __init__(self, score, width=1.15 * inch, height=6):
        super().__init__()
        self.score, self.width, self.height = score, width, height

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        c = self.canv
        if self.score is None:
            c.saveState()
            c.setStrokeColor(LINE)
            c.setLineWidth(0.6)
            c.setDash(2, 2)
            c.rect(0, 0, self.width, self.height, stroke=1, fill=0)
            c.restoreState()
            return
        c.setFillColor(TRACK)
        c.rect(0, 0, self.width, self.height, stroke=0, fill=1)
        c.setFillColor(SEQ)
        c.rect(0, 0, self.width * max(0.0, min(1.0, self.score / 100.0)),
               self.height, stroke=0, fill=1)


def severity_segments(counts: dict) -> list:
    """[(label, n, color)] in ordinal order, worst first."""
    return [(k, int(counts.get(k, 0) or 0), ORD[k])
            for k in ("Critical", "High", "Medium", "Low")]


def coverage_segments(measured: int, need_access: int, na: int) -> list:
    return [("Measured", measured, SEQ),
            ("Need client access", need_access, MUTED),
            ("Not applicable", na, TRACK)]


class DefBadge(Flowable):
    """
    The "this is a definition" marker: a filled circle with a lower-case i.

    Drawn as vector rather than set as a glyph, and that is the whole point.
    The first version used a symbol font looked up on disk; the production
    container turned out not to have it, so `_icon()` correctly dropped the
    character and the bubbles shipped with no icon at all. A circle and a
    letter in Helvetica cannot go missing — Helvetica is one of the fourteen
    fonts every PDF reader is required to have.
    """

    def __init__(self, size=12, fill=None, ink=None):
        super().__init__()
        self.width = self.height = size
        self.fill = fill or colors.HexColor("#2a78d6")
        self.ink = ink or colors.white

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        c = self.canv
        r = self.width / 2
        c.setFillColor(self.fill)
        c.circle(r, r, r, stroke=0, fill=1)
        c.setFillColor(self.ink)
        c.setFont("Helvetica-Bold", self.width * 0.72)
        c.drawCentredString(r, r - self.width * 0.26, "i")
