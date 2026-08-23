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

# Same family as the body copy. The charts are drawn straight onto the canvas,
# so they do not inherit the paragraph styles and would otherwise stay in
# Helvetica while everything around them changed — the kind of mismatch that
# reads as "assembled from two documents".
# BIND AFTER REGISTERING, NEVER DURING THE IMPORT LINE.
#
# This said:
#
#     from .fonts import register as _register_fonts, BODY as F, ...
#     _register_fonts()
#
# `from X import BODY as F` copies the CURRENT value of fonts.BODY into this
# module - which, at import time, is still the "Helvetica" default. register()
# then rebinds fonts.BODY to GT Walsheim and this module never hears about it.
# So the paragraphs were in the brand face and every mark drawn straight onto
# the canvas - the gauge number, the bar labels, the legends - stayed in
# Helvetica, in the same document, a quarter inch apart.
#
# pdf_report.py already had a comment warning about exactly this. The charts
# did not.
from . import fonts as _fonts
_fonts.register()
F, FB, FI = _fonts.BODY, _fonts.BOLD, _fonts.ITALIC

# Vici brand palette — Atlas Blue #002D58, Velocity Blue #0066B3, Ink #212121,
# Parchment #FDFBF7, with the brand's own 50% and 10% fades. Kept in step with
# the same constants in pdf_report.py: these charts are drawn straight onto the
# canvas and inherit nothing, so a value that drifts here shows up as one chart
# in the wrong blue.
INK     = colors.HexColor("#212121")
INK2    = colors.HexColor("#4A5461")
MUTED   = colors.HexColor("#8096AC")   # Atlas 50%
LINE    = colors.HexColor("#E6EAEE")   # Atlas 10%
TRACK   = colors.HexColor("#E9E9E9")   # Ink 10%
SEQ     = colors.HexColor("#0066B3")   # Velocity
SEQ_DIM = colors.HexColor("#80B2D9")   # Velocity 50%

ORD = {"Critical": colors.HexColor("#002D58"), "High": colors.HexColor("#0066B3"),
       "Medium": colors.HexColor("#4D94CB"), "Low": colors.HexColor("#80B2D9")}

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


def _gap_w(r, thick, dy):
    """
    Clear width inside the gauge's bottom opening, `dy` below the center.

    Half-chord of the circle at that height, doubled, less the stroke the arc
    occupies on each side. At dy=0.8r this is about one short word; at dy=0.55r
    it comfortably holds "Needs Improvement".
    """
    import math
    k = min(abs(dy) / r, 0.999) if r else 0.999
    # 1.6x the stroke, not 1.0x: half a stroke each side is the geometric
    # minimum and leaves the last glyph kissing the arc. The extra is margin.
    return max(1.0, 2 * r * math.sqrt(1 - k * k) - thick * 1.6)


# ---------------------------------------------------------------- gradients
#
# WITHIN ONE HUE, ALWAYS.
#
# The dataviz rules at the top of report.py are not decoration: section scores
# are magnitude, and magnitude is carried by a sequential single hue plus
# length. A gradient that crosses hues would turn a ranked scale into a
# categorical palette and destroy the ordering it exists to show.
#
# So every gradient here runs light-to-dark inside the same blue. It reads as
# depth and finish; it never becomes a second channel of meaning. Length is
# still the whole message.
GRAD_LO = colors.HexColor("#80B2D9")   # Velocity 50%
GRAD_HI = colors.HexColor("#002D58")   # Atlas


def _lerp(a, b, t):
    """A color t of the way from a to b."""
    t = max(0.0, min(1.0, t))
    return colors.Color(a.red + (b.red - a.red) * t,
                        a.green + (b.green - a.green) * t,
                        a.blue + (b.blue - a.blue) * t)


def _grad_rect(c, x, y, w, h, lo=GRAD_LO, hi=GRAD_HI, steps=None):
    """
    A horizontal gradient, drawn as thin bands.

    reportlab has `linearGradient`, but it fills the CURRENT PATH and interacts
    badly with the clipping these flowables already do. Bands are dumber and
    work everywhere.

    Band count is derived from the WIDTH, not fixed. A fixed count is the bug
    that made the inline meters look striped while the big bars looked smooth:
    the same 48 bands are invisible across four inches and countable across
    one. One band every 1.5pt holds up at print resolution and at the zoom
    levels anyone actually reads a PDF at.
    """
    if w <= 0 or h <= 0:
        return
    if steps is None:
        steps = max(16, min(160, int(w / 1.5)))
    step = w / steps
    for i in range(steps):
        c.setFillColor(_lerp(lo, hi, i / max(1, steps - 1)))
        # A hair of overlap: adjacent fills that merely touch leave hairlines
        # at some zoom levels, which reads as banding rather than a gradient.
        c.rect(x + i * step, y, step + 0.4, h, stroke=0, fill=1)


class GradRule(Flowable):
    """
    A gradient rule. The document's one piece of pure decoration.

    Everything else in here encodes something — length is a score, position is
    a rank, tone is depth along a single hue. This encodes nothing, and that is
    deliberate: a report of this length needs a repeating mark that says "a new
    part starts here" faster than a heading can be read, and a hairline in flat
    gray does not do it.

    `taper` fades the right end into the page instead of stopping square, which
    is what makes it read as a flourish rather than as a bar someone forgot to
    fill.
    """

    def __init__(self, width=2.1 * inch, height=3.0, taper=True,
                 space_before=0, space_after=0, lo=GRAD_LO, hi=GRAD_HI):
        super().__init__()
        self.width, self.height, self.taper = width, height, taper
        self._sb, self._sa = space_before, space_after
        # Rules run DARK to LIGHT, left to right — the opposite of the bars,
        # where light-to-dark tracks a growing measurement. Nothing is being
        # measured here, and starting at full strength at the margin is what
        # anchors the mark to the text block beside it.
        self.lo, self.hi = lo, hi

    def wrap(self, aw, ah):
        self.width = min(self.width, aw)
        return self.width, self.height + self._sb + self._sa

    def draw(self):
        c = self.canv
        y = self._sa
        if not self.taper:
            _grad_rect(c, 0, y, self.width, self.height,
                       lo=self.hi, hi=self.lo)
            return
        # The tail fades toward the PAGE COLOR, not toward transparent.
        #
        # setFillAlpha was the obvious way to do this and it printed a dashed
        # line. Each band overlaps its neighbor by 0.4pt to stop hairlines
        # from opening up between them — and two translucent fills stacked in
        # that overlap are twice as opaque as either one, so the fade came out
        # striped at exactly the band pitch. Opaque bands lerped to white keep
        # the overlap harmless. The rule only ever sits on the white page, so
        # there is nothing for a white tail to ghost against.
        steps = 60
        step = self.width / steps
        for i in range(steps):
            t = i / (steps - 1)
            col = _lerp(self.hi, self.lo, t)
            if t > 0.55:
                col = _lerp(col, colors.white, (t - 0.55) / 0.45)
            c.setFillColor(col)
            c.rect(i * step, y, step + 0.4, self.height, stroke=0, fill=1)


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
                # Swept in segments so the arc can carry a gradient. A single
                # stroke can only be one color, and the arc is the largest
                # single mark in the document — the one place the extra dozen
                # lines of drawing buy the most.
                n = max(6, int(60 * frac))
                sweep = -270.0 * frac
                for i in range(n):
                    c.setStrokeColor(_lerp(GRAD_LO, GRAD_HI, i / max(1, n - 1)))
                    # Segments overlap by a whisker for the same reason the
                    # gradient bands do.
                    c.arc(x1, y1, x2, y2,
                          225 + sweep * (i / n),
                          sweep / n - (0.35 if i < n - 1 else 0))

        # centered readout
        c.setFillColor(INK if self.score is not None else MUTED)
        num = str(self.score) if self.score is not None else "—"
        c.setFont(FB, s * 0.27)
        c.drawCentredString(cx, cy + s * 0.005, num)
        if self.score is not None:
            c.setFont(F, s * 0.08)
            c.setFillColor(MUTED)
            c.drawCentredString(cx, cy - s * 0.10, "/ 100")

        # The rating and caption sit in the arc's bottom gap — inside the
        # flowable, and inside the GAP. Both constraints are real: text below
        # y=0 lands on the panel border, and text wider than the gap strikes
        # through the arc on both sides. "Strong" fit at any height, which is
        # how "Needs Improvement" shipped crossed out.
        #
        # The gap narrows fast as you go down, so the width available depends
        # on where the baseline is. Compute it rather than guessing, and sit
        # higher than the old 0.80r where the opening is barely a word wide.
        rate_dy = r * 0.55
        lbl_dy = rate_dy + s * 0.085
        c.setFillColor(INK2)
        txt = self.rating or ("Not scored" if self.score is None else "")
        txt, size = _fit(c, txt, FB, s * 0.095,
                         _gap_w(r, thick, rate_dy))
        c.setFont(FB, size)
        c.drawCentredString(cx, cy - rate_dy, txt)
        lbl, lsize = _fit(c, self.label, F, s * 0.072,
                          _gap_w(r, thick, lbl_dy))
        c.setFont(F, lsize)
        c.setFillColor(MUTED)
        c.drawCentredString(cx, cy - lbl_dy, lbl)
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
            font = FB if i in worst else F
            c.setFillColor(INK if i in worst else INK2)
            txt, size = _fit(c, label, font, 8, self.label_w)
            c.setFont(font, size)
            c.drawString(0, y + bar_h * 0.25, txt)

            if sc is None:
                c.saveState()
                c.setStrokeColor(LINE)
                c.setLineWidth(0.6)
                c.setDash(2, 2)
                c.roundRect(bar_x, y, bar_w, bar_h,
                            min(bar_h / 2.0, 4.0), stroke=1, fill=0)
                c.restoreState()
                c.setFillColor(MUTED)
                c.setFont(FI, 7)
                c.drawString(bar_x + 4, y + bar_h * 0.28, "Not assessed")
                c.setFont(F, 7.5)
                c.drawRightString(self.width, y + bar_h * 0.25, "—")
                continue

            radius = min(bar_h / 2.0, 4.0)
            c.setFillColor(TRACK)
            # Rounded, and the fill is clipped to the track's own rounded
            # shape so a short bar keeps square inner ends rather than
            # floating as a separate pill inside the track.
            c.roundRect(bar_x, y, bar_w, bar_h, radius, stroke=0, fill=1)
            fill_w = bar_w * max(0.0, min(1.0, sc / 100.0))
            # EVERY bar gets the SAME ramp.
            #
            # The first cut gave the three worst areas a full-depth gradient
            # and everything else a pale one. On the page that turned tone
            # into a second reading of the data — dark bars looked like the
            # bad ones — and it contradicted the gauge on page one, where dark
            # is simply "further along the arc". Same ink, two opposite
            # meanings, in one document.
            #
            # Length is the whole message. The three worst are already called
            # out by a bold label in full-strength ink, which is emphasis
            # applied to the label rather than to the measurement.
            # ROUND THE FILL TOO.
            #
            # The track was rounded and the gradient inside it was not, so a
            # bar at 100 had square ends sitting a half-point proud of a
            # rounded outline - which reads as a rendering fault rather than a
            # style. Same clip trick the segment bar uses.
            c.saveState()
            clip = c.beginPath()
            clip.roundRect(bar_x, y, bar_w, bar_h, radius)
            c.clipPath(clip, stroke=0, fill=0)
            _grad_rect(c, bar_x, y, fill_w, bar_h)
            c.restoreState()

            # Fit the value to its own column. "70  Needs Improvement" is more
            # than twice the width of "100  Strong", and at a fixed size the
            # long ones ran back over the bar.
            c.setFillColor(INK2)
            txt = f"{sc}  {rating or ''}".strip()
            txt, size = _fit(c, txt, FB, 7.5, self.value_w - 4)
            c.setFont(FB, size)
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

    # A count too narrow to sit inside its own segment is not drawn in the
    # bar at all.
    #
    # It was, briefly: 4 Critical out of 111 is an eleven-point block, so the
    # number went into a gutter above the bar with a tick pointing down at its
    # segment. Accurate, and it read as an error mark hovering over the chart
    # - two small floating numbers at different heights on two adjacent
    # charts, which is worse than the thing it fixed.
    #
    # Nothing is lost by leaving it out. The legend directly underneath prints
    # "Critical 4" in words, which is where a reader looks for the exact
    # figure anyway; the bar's job is the proportion.
    _TIGHT = 22

    def wrap(self, aw, ah):
        self.width = min(self.width, aw)
        return self.width, self.height

    def draw(self):
        c = self.canv
        total = sum(max(0, n) for _, n, _ in self.segments) or 1
        y = self.height - self.bar_h
        x = 0.0
        # ROUND THE BAR, NOT THE SEGMENTS.
        #
        # Rounding each segment would put a curve on every internal join and
        # break the read: a stacked bar means "these add up to one whole", and
        # four separately-rounded blocks read as four separate bars. Clipping
        # the whole strip to one rounded rectangle rounds the two outer ends
        # and leaves the joins square, which is the shape the number line
        # actually has.
        r = min(self.bar_h / 2.0, 5.0)
        c.saveState()
        clip = c.beginPath()
        clip.roundRect(0, y, self.width, self.bar_h, r)
        c.clipPath(clip, stroke=0, fill=0)
        for label, n, col in self.segments:
            if n <= 0:
                continue
            w = self.width * n / total
            c.setFillColor(col)
            c.rect(x, y, w, self.bar_h, stroke=0, fill=1)
            # count inside the segment only when it comfortably fits
            if w > self._TIGHT:
                c.setFillColor(colors.white if col not in (TRACK, LINE) else INK2)
                c.setFont(FB, 8)
                c.drawCentredString(x + w / 2, y + self.bar_h * 0.32, str(n))
            x += w
        c.restoreState()

        # legend — every segment gets its word, so color is never load-bearing
        lx, ly = 0.0, y - 15
        c.setFont(F, 7.5)
        for label, n, col in self.segments:
            sw = c.stringWidth(f"{label} {n}", F, 7.5) + 16
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
            c.setFont(FI, 7.5)
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
        # Same shape as every other bar in the document. These sit inches from
        # the rounded bars in Scores by Area and were the only square ones
        # left, which made them read as a different kind of object.
        r = self.height / 2.0
        if self.score is None:
            c.saveState()
            c.setStrokeColor(LINE)
            c.setLineWidth(0.6)
            c.setDash(2, 2)
            c.roundRect(0, 0, self.width, self.height, r, stroke=1, fill=0)
            c.restoreState()
            return
        c.setFillColor(TRACK)
        c.roundRect(0, 0, self.width, self.height, r, stroke=0, fill=1)
        # Same ramp as the big bars, and the same band density.
        #
        # Band count comes from the width — see _grad_rect. Hard-coding it
        # here is what made these look striped next to identical-looking bars
        # four times as wide.
        c.saveState()
        clip = c.beginPath()
        clip.roundRect(0, 0, self.width, self.height, r)
        c.clipPath(clip, stroke=0, fill=0)
        _grad_rect(c, 0, 0,
                   self.width * max(0.0, min(1.0, self.score / 100.0)),
                   self.height)
        c.restoreState()


GOLD = colors.HexColor("#F1B434")


class Lamp(Flowable):
    """
    A small lightbulb, drawn as vectors.

    Deliberately NOT the emoji. U+1F4A1 is absent from every font this renderer
    can rely on — Roboto does not have it and neither does DejaVu, which is the
    fallback we register precisely for stray glyphs — and reportlab's answer to a
    missing glyph is a solid black box. A hand-drawn path is a dozen lines and
    cannot fail that way.
    """

    def __init__(self, size=7.5):
        super().__init__()
        self.width = self.height = size

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        c, s = self.canv, self.width
        c.saveState()
        c.setStrokeColor(GOLD)
        c.setFillColor(GOLD)
        c.setLineWidth(max(0.5, s * 0.11))
        c.setLineCap(1)
        # Glass: a circle sitting above the base.
        r = s * 0.32
        cx, cy = s / 2.0, s * 0.63
        c.circle(cx, cy, r, stroke=1, fill=0)
        # Neck, down from the glass to the screw base.
        c.line(cx - r * 0.55, cy - r * 0.86, cx - r * 0.55, s * 0.22)
        c.line(cx + r * 0.55, cy - r * 0.86, cx + r * 0.55, s * 0.22)
        # Two filament rings at the base.
        for y in (s * 0.18, s * 0.06):
            c.line(cx - r * 0.55, y, cx + r * 0.55, y)
        c.restoreState()


def severity_segments(counts: dict) -> list:
    """[(label, n, color)] in ordinal order, worst first."""
    return [(k, int(counts.get(k, 0) or 0), ORD[k])
            for k in ("Critical", "High", "Medium", "Low")]


def coverage_segments(measured: int, client: int, ours: int, na: int) -> list:
    """
    Split by WHO IT IS BLOCKED ON, not by whether we happened to get a number.

    The old two-way split lumped "your Search Console is private" together with
    "we haven't set the backlink API key" and labelled the whole pile as the
    client's to fix. Only the middle segment is an ask; the third is our work.
    """
    # A ZERO SEGMENT KEEPS ITS LEGEND ENTRY — except this one.
    #
    # The rule elsewhere in this file is that a zero stays visible, because
    # "none of these" and "we didn't look" are different facts. "Need your
    # access 0" is the exception: it is an ASK, and an ask with nothing in it
    # is not a fact the client needs — it is a line inviting them to wonder
    # what we wanted. When the number is zero there is nothing to ask for, so
    # the row goes.
    out = [("Measured", measured, SEQ)]
    if client:
        out.append(("Need your access", client, MUTED))
    out += [("We complete these", ours, SEQ_DIM),
            ("Not applicable", na, TRACK)]
    return out


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
