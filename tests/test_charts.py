"""
Chart honesty tests.

The charts are the part of the report a client actually looks at, which makes
them the easiest place to tell a lie by accident. Two specific lies are guarded
here:

  1. An unassessed section drawn as a zero-length bar. It reads as "scored
     zero" and there is no visual difference between "we could not look" and
     "you failed completely".
  2. A coverage strip that quietly omits catalog rows we never produced a
     finding for, so 132 measured out of 313 renders as 100% coverage.

Also asserts every flowable stays inside its declared box, because reportlab
will happily draw outside one and the overflow lands on top of the next thing.

Run:  python3 -m tests.test_charts
"""
from __future__ import annotations
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reportlab.lib.units import inch
from engine.charts import (ScoreGauge, SectionBars, SegmentBar, MiniMeter,
                           severity_segments, coverage_segments, _fit)
from engine.pdf_report import build_pdf, _severity_counts, _coverage_counts

FAILURES = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)
    return cond


class _Rec:
    """
    A canvas stand-in that records what was drawn and where.

    Cheaper and far more precise than eyeballing a screenshot: we can assert
    that nothing was painted outside the flowable's own box.
    """

    def __init__(self):
        self.rects, self.texts, self.arcs = [], [], []
        self._font = ("Helvetica", 10)

    # --- geometry
    def rect(self, x, y, w, h, stroke=1, fill=0):
        self.rects.append({"x": x, "y": y, "w": w, "h": h,
                           "stroke": stroke, "fill": fill})

    def arc(self, x1, y1, x2, y2, startAng=0, extent=90):
        self.arcs.append({"box": (x1, y1, x2, y2), "start": startAng,
                          "extent": extent})

    def line(self, *a):
        pass

    # --- text
    def setFont(self, name, size, leading=None):
        self._font = (name, size)

    def drawString(self, x, y, t):
        self.texts.append({"x": x, "y": y, "t": t, "size": self._font[1]})

    def drawCentredString(self, x, y, t):
        self.texts.append({"x": x, "y": y, "t": t, "size": self._font[1]})

    def drawRightString(self, x, y, t):
        self.texts.append({"x": x, "y": y, "t": t, "size": self._font[1]})

    def stringWidth(self, t, font="Helvetica", size=10):
        # generous over-estimate, so a fit test that passes here passes for real
        return len(t) * size * 0.62

    # --- state (no-ops)
    def saveState(self): pass
    def restoreState(self): pass
    def setLineWidth(self, *a): pass
    def setLineCap(self, *a): pass
    def setStrokeColor(self, *a): pass
    def setFillColor(self, *a): pass
    def setDash(self, *a): pass


def _render(flowable, avail_w=6.6 * inch):
    rec = _Rec()
    flowable.canv = rec
    w, h = flowable.wrap(avail_w, 800)
    flowable.draw()
    return rec, w, h


def main():
    print("\nUNASSESSED SECTIONS MUST NOT DRAW AS ZERO")
    rows = [("Structured Data", 49, "Weak"), ("Technical SEO", 82, "Strong"),
            ("HTTPS & Security", None, "Not Assessed"),
            ("Off-Page & Authority", None, "Not Assessed")]
    bars = SectionBars(rows, width=6.4 * inch)
    rec, w, h = _render(bars)

    filled = [r for r in rec.rects if r["fill"]]
    hollow = [r for r in rec.rects if not r["fill"] and r["stroke"]]
    check("assessed rows draw filled bars", len(filled) == 4, f"{len(filled)} filled")
    check("unassessed rows draw a hollow outline instead",
          len(hollow) == 2, f"{len(hollow)} hollow")
    check("no zero-width bar is ever emitted",
          all(r["w"] > 0.5 for r in filled),
          str([round(r["w"], 2) for r in filled]))
    check("unassessed rows are labelled in words, not just by colour",
          sum(1 for t in rec.texts if "Not assessed" in t["t"]) == 2)
    check("unassessed rows show a dash for the score, never 0",
          sum(1 for t in rec.texts if t["t"] == "—") == 2)
    check("no row is labelled '0'", not any(t["t"].strip() == "0" for t in rec.texts))

    print("\nNOTHING DRAWS OUTSIDE ITS DECLARED BOX")
    for name, fl in (("SectionBars", SectionBars(rows, width=6.4 * inch)),
                     ("ScoreGauge", ScoreGauge(75, "Strong")),
                     ("ScoreGauge (unscored)", ScoreGauge(None, "")),
                     ("SegmentBar", SegmentBar(
                         severity_segments({"Critical": 4, "High": 1,
                                            "Medium": 35, "Low": 9}),
                         width=3.05 * inch, note="x")),
                     ("MiniMeter", MiniMeter(50)),
                     ("MiniMeter (unscored)", MiniMeter(None))):
        rec, w, h = _render(fl)
        lo = min([r["y"] for r in rec.rects] +
                 [t["y"] - t["size"] * 0.28 for t in rec.texts] +
                 [a["box"][1] for a in rec.arcs] + [0])
        hi = max([r["y"] + r["h"] for r in rec.rects] +
                 [t["y"] + t["size"] * 0.75 for t in rec.texts] +
                 [a["box"][3] for a in rec.arcs] + [0])
        check(f"{name} stays within its height", lo >= -0.6 and hi <= h + 0.6,
              f"drew {lo:.1f}..{hi:.1f} in a box of 0..{h:.1f}")

    print("\nLONG LABELS DEGRADE INSTEAD OF OVERLAPPING")
    rec = _Rec()
    txt, size = _fit(rec, "Website Performance & Core Web Vitals",
                     "Helvetica-Bold", 8, 1.95 * inch)
    check("an over-long label is shrunk or truncated to fit",
          rec.stringWidth(txt, "Helvetica-Bold", size) <= 1.95 * inch + 0.5,
          f"{txt!r} @ {size}pt")

    print("\nCOVERAGE COUNTS THE WHOLE CATALOG")
    catalog = {f"X-{i:02d}": {"prefix": "X"} for i in range(1, 21)}
    findings = {"X-01": {"status": "Pass", "severity": "Low"},
                "X-02": {"status": "Fail", "severity": "Critical"},
                "X-03": {"status": "Need Access", "severity": "Medium"},
                "X-04": {"status": "N/A", "severity": "Low"}}
    m, need, na = _coverage_counts(findings, catalog)
    check("counts sum to the full catalog, not just returned findings",
          m + need + na == len(catalog), f"{m}+{need}+{na} vs {len(catalog)}")
    check("checkpoints never returned count as Need Access, not as absent",
          need == 17, f"need={need}")
    check("measured counts only real answers", m == 2, f"measured={m}")
    check("N/A is tracked apart from Need Access", na == 1, f"na={na}")

    print("\nSEVERITY COUNTS OPEN ISSUES ONLY")
    sev = _severity_counts({
        "A": {"status": "Fail", "severity": "Critical"},
        "B": {"status": "Warning", "severity": "Medium"},
        "C": {"status": "Pass", "severity": "High"},          # passing: not an issue
        "D": {"status": "Need Access", "severity": "High"},   # unmeasured: not an issue
        "E": {"status": "Not Implemented", "severity": "Low"}})
    check("a passing checkpoint contributes no severity", sev.get("High", 0) == 0,
          str(sev))
    check("a Need Access row is not counted as an issue", sum(sev.values()) == 3,
          str(sev))

    print("\nSEGMENTS")
    segs = severity_segments({"Critical": 0, "High": 2, "Medium": 0, "Low": 5})
    check("zero-count severities stay in the legend so 'none' is visible",
          len(segs) == 4 and segs[0][1] == 0)
    rec, w, h = _render(SegmentBar(segs, width=3.0 * inch))
    check("zero-count severities draw no segment in the bar",
          len([r for r in rec.rects if r["fill"] and r["h"] > 10]) == 2,
          str([round(r["w"], 1) for r in rec.rects if r["fill"] and r["h"] > 10]))
    cov = coverage_segments(132, 166, 15)
    check("coverage segments are labelled in words",
          [c[0] for c in cov] == ["Measured", "Need client access", "Not applicable"])

    print("\nFULL PDF STILL BUILDS WITH AN UNASSESSED SECTION")
    scores = {"overall": {"score": 75, "rating": "Strong"},
              "sections": {"TECH": {"score": 82, "rating": "Strong", "checked": 20,
                                    "total": 26, "failing": 3},
                           "SEC": {"score": None, "rating": "Not Assessed",
                                   "checked": 0, "total": 11, "failing": 0}}}
    cat = {"TECH-01": {"prefix": "TECH", "checkpoint": "Robots.txt"},
           "SEC-01": {"prefix": "SEC", "checkpoint": "HTTPS"}}
    F = {"TECH-01": {"status": "Fail", "severity": "High", "evidence": "broken",
                     "recommendation": "fix", "confidence": 1.0, "source": "crawl"},
         "SEC-01": {"status": "Need Access", "severity": "Medium", "evidence": "n/a",
                    "recommendation": "", "confidence": 0.0, "source": "tls"}}
    pdf = build_pdf({"client": "T", "url": "https://t.test/", "pages_crawled": 3,
                     "coverage": "2/2", "generated": "2026-08-18", "build": "test"},
                    scores, F, cat)
    check("PDF builds", pdf[:4] == b"%PDF", f"{len(pdf)//1024}KB")
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf)) as d:
            text = "\n".join((p.extract_text() or "") for p in d.pages)
        check("the unassessed section is named as such in the output",
              "Not assessed" in text or "Not Assessed" in text)
        check("no section is printed as 0/100", "0/100" not in text)
    except ImportError:
        print("  SKIP  pdfplumber not installed")

    print("\n" + "=" * 68)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — charts cannot report unmeasured as zero")
    print("=" * 68 + "\n")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
