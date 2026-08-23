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


class _Path:
    """A no-op path object, for canvas clipping."""

    def roundRect(self, *a, **k):
        pass

    def rect(self, *a, **k):
        pass


class _Rec:
    """
    A canvas stand-in that records what was drawn and where.

    Cheaper and far more precise than eyeballing a screenshot: we can assert
    that nothing was painted outside the flowable's own box.
    """

    def __init__(self):
        self.rects, self.texts, self.arcs = [], [], []
        self._font = ("Helvetica", 10)
        self._fill = None

    # --- geometry
    def rect(self, x, y, w, h, stroke=1, fill=0):
        # The fill COLOR is recorded now, and it has to be.
        #
        # Bars used to be one rect each, so "how many filled rects" was a fair
        # proxy for "how many bars". They are gradients now — dozens of thin
        # bands per bar — and that proxy started reporting 176 bars for a
        # four-row chart. Counting draw calls was always measuring the
        # implementation; what the test actually cares about is how far the
        # ink reaches, and telling bar ink from track ink needs the color.
        self.rects.append({"x": x, "y": y, "w": w, "h": h,
                           "stroke": stroke, "fill": fill,
                           "color": self._fill})

    def roundRect(self, x, y, w, h, r, stroke=1, fill=0):
        # Bars are rounded now. To this recorder a rounded rect is a rect —
        # the corner radius changes no assertion here, and every test that
        # measures how far the ink reaches must keep counting it.
        self.rect(x, y, w, h, stroke=stroke, fill=fill)

    def beginPath(self):
        return _Path()

    def clipPath(self, p, stroke=0, fill=0):
        # The segment bar clips itself to a rounded outline. Nothing is
        # painted by the clip, so there is nothing to record.
        pass

    def arc(self, x1, y1, x2, y2, startAng=0, extent=90):
        self.arcs.append({"box": (x1, y1, x2, y2), "start": startAng,
                          "extent": extent})

    def line(self, *a):
        pass

    # --- text
    def setFont(self, name, size, leading=None):
        self._font = (name, size)

    def drawString(self, x, y, t):
        self.texts.append({"x": x, "y": y, "t": t, "size": self._font[1],
                           "font": self._font[0]})

    def drawCentredString(self, x, y, t):
        self.texts.append({"x": x, "y": y, "t": t, "size": self._font[1],
                           "font": self._font[0]})

    def drawRightString(self, x, y, t):
        self.texts.append({"x": x, "y": y, "t": t, "size": self._font[1],
                           "font": self._font[0]})

    def stringWidth(self, t, font="Helvetica", size=10):
        # generous over-estimate, so a fit test that passes here passes for real
        return len(t) * size * 0.62

    # --- state (no-ops)
    def saveState(self): pass
    def restoreState(self): pass
    def setLineWidth(self, *a): pass
    def setLineCap(self, *a): pass
    def setStrokeColor(self, *a): pass
    def setFillColor(self, col, *a):
        self._fill = getattr(col, "hexval", lambda: str(col))()
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

    from engine.charts import TRACK
    track_hex = TRACK.hexval()
    filled = [r for r in rec.rects if r["fill"]]
    hollow = [r for r in rec.rects if not r["fill"] and r["stroke"]]

    # Group the ink by row, and ask how far each row's BAR reaches past the
    # left edge of its track. That is the thing a reader sees and the thing a
    # zero-length bar would get wrong, and it holds whether the bar is one
    # rect or sixty bands.
    def spans():
        rows_ = {}
        for r in filled:
            key = round(r["y"], 1)
            lo, hi_, is_track = rows_.get(key, (None, None, False))
            if r["color"] == track_hex:
                rows_[key] = (lo, hi_, True)
                continue
            lo = r["x"] if lo is None else min(lo, r["x"])
            hi_ = r["x"] + r["w"] if hi_ is None else max(hi_, r["x"] + r["w"])
            rows_[key] = (lo, hi_, is_track)
        return {k: v for k, v in rows_.items() if v[0] is not None}

    bars = spans()
    check("assessed rows draw filled bars", len(bars) == 2, f"{len(bars)} bars")
    check("unassessed rows draw a hollow outline instead",
          len(hollow) == 2, f"{len(hollow)} hollow")
    check("no zero-width bar is ever emitted",
          all(hi_ - lo > 0.5 for lo, hi_, _ in bars.values()),
          str([round(hi_ - lo, 2) for lo, hi_, _ in bars.values()]))
    check("every bar sits on a track, so length reads as a proportion",
          all(t for _, _, t in bars.values()))
    check("a higher score draws a longer bar",
          sorted(round(hi_ - lo) for lo, hi_, _ in bars.values())[-1] >
          sorted(round(hi_ - lo) for lo, hi_, _ in bars.values())[0])
    check("unassessed rows are labelled in words, not just by colour",
          sum(1 for t in rec.texts if "Not assessed" in t["t"]) == 2)
    check("unassessed rows show a dash for the score, never 0",
          sum(1 for t in rec.texts if t["t"] == "—") == 2)
    check("no row is labelled '0'", not any(t["t"].strip() == "0" for t in rec.texts))

    print("\nTHE REPORT TYPEFACE")
    # Falling back to Helvetica is deliberate and safe, but it is also silent,
    # so a base image that quietly lost fonts-roboto would ship a worse-looking
    # PDF with nothing to notice. Assert the image actually has it.
    from engine.fonts import register, status, BODY, BOLD
    fam = register()
    check("Roboto is registered (fonts-roboto installed in the image)",
          fam == "Roboto", fam)
    check("bold resolves to the same family, not back to Helvetica",
          BODY.startswith(fam) and BOLD.startswith(fam), f"{BODY}/{BOLD}")
    check("status reports what is actually in use", status()["registered"] is True)

    print("\nCOUNTS OF ONE READ AS SINGULAR")
    from engine.pdf_report import _agree
    check("noun and verb both agree",
          _agree("1 pages exceed 200KB.") == "1 page exceeds 200KB.",
          _agree("1 pages exceed 200KB."))
    check("real plurals are untouched",
          _agree("4 pages send no header.") == "4 pages send no header.")
    check("a word that merely ends in s is not mangled",
          "addres " not in _agree("1 address is present."),
          _agree("1 address is present."))

    print("\nREPEATED EVIDENCE IS REPEATED, AND CROSS-REFERENCED")
    from engine.pdf_report import _dedupe_evidence
    same = "83 pages share 25 duplicated title tags."
    d = _dedupe_evidence([("ONP-01", {"status": "Fail", "evidence": same}),
                          ("ONP-23", {"status": "Fail", "evidence": same})])
    check("the first row keeps the detail", d[0][1]["evidence"] == same)
    # WAS: asserted the second row read only "Same finding as ONP-01." That
    # saved four lines and cost the reader a page-flip in an appendix nobody
    # reads front to back - the row they landed on is the row they care about.
    # The finding is printed again and the pointer moved to the end, where it
    # adds context instead of replacing it.
    check("the second repeats the finding and says where else it appears",
          d[1][1]["evidence"].startswith(same)
          and "Also reported under ONP-01" in d[1][1]["evidence"],
          d[1][1]["evidence"])
    short = [("A-1", {"status": "Pass", "evidence": "Not detected."}),
             ("A-2", {"status": "Pass", "evidence": "Not detected."})]
    check("short rows are left alone — cross-referencing them is longer",
          _dedupe_evidence(short)[1][1]["evidence"] == "Not detected.")

    print("\nTHE RATING WORD NEVER CROSSES THE GAUGE ARC")
    # "Strong" fit at any height and "Needs Improvement" did not, so the long
    # ratings shipped struck through by the arc on both sides. Every band the
    # scorer can emit has to clear the opening it is drawn into.
    from engine.charts import _gap_w
    for band in ("Excellent", "Strong", "Needs Improvement", "Weak", "Critical",
                 "Not Assessed"):
        rec, w, h = _render(ScoreGauge(72, band))
        thick = w * 0.105
        r = (w - (thick / 2 + 1) * 2) / 2
        hit = []
        for t in rec.texts:
            if t["t"] not in (band, "Overall score"):
                continue
            dy = w / 2 - t["y"]
            if dy <= 0:
                continue
            width = rec.stringWidth(t["t"], t["font"], t["size"])
            if width > _gap_w(r, thick, dy) + 0.5:
                hit.append(f"{t['t']!r} {width:.1f}pt in {_gap_w(r, thick, dy):.1f}pt")
        check(f"'{band}' fits the arc's opening", not hit, "; ".join(hit))

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
    m, need, ours, na = _coverage_counts(findings, catalog)
    check("counts sum to the full catalog, not just returned findings",
          m + need + ours + na == len(catalog),
          f"{m}+{need}+{ours}+{na} vs {len(catalog)}")
    check("checkpoints never returned are counted, not silently dropped",
          need + ours == 17, f"need={need} ours={ours}")
    check("measured counts only real answers", m == 2, f"measured={m}")
    check("N/A is tracked apart from the unmeasured", na == 1, f"na={na}")

    # The whole point of the split: an unknown prefix is OUR work to finish,
    # never filed as homework for the client. Over-reporting the client's
    # to-do list is the failure this bucketing exists to prevent.
    check("an unrecognised section is never charged to the client",
          need == 0, f"need={need}")

    print("\nONLY SEARCH CONSOLE AND ANALYTICS ARE THE CLIENT'S TO GRANT")
    from engine.access import blocked_on, counts as _acounts
    check("GSC is the client's", blocked_on("GSC-01") == "client")
    check("GA4 is the client's", blocked_on("GA4-07") == "client")
    check("backlinks are ours to buy", blocked_on("OFF-01") == "vendor")
    check("a judgment-layer row is ours to configure",
          blocked_on("EEAT-01") == "vendor")
    # SEC-06 is subdomain HSTS: no crawler check, no collector, no judgment
    # spec — it genuinely needs a person with an external TLS scanner.
    #
    # ONP-34, then ONP-43, then CANON/URL/INTL, then SEC, then the GEO rows —
    # every occupant of this bucket has been automated in turn, and the catalog
    # now has none. What is tested is the RULE, with an id the catalog does not
    # contain: anything unrecognised must still fall to `manual` rather than to
    # `client`, because over-reporting the client's homework is the failure the
    # whole three-way split exists to prevent.
    check("an unrecognised checkpoint is ours to do by hand",
          blocked_on("ZZZ-01") == "manual")
    # THE ONE THAT SHIPPED WRONG. A granted, working Search Console connection
    # still left 27 rows the API does not expose, and bucketing by prefix
    # called every one of them a missing client grant — telling us to email a
    # client for access they had already given and that was demonstrably
    # working two rows above.
    check("a GSC row the API cannot expose is OURS, not the client's",
          blocked_on("GSC-05", {"source": "gsc_ui_only"}) == "vendor")
    check("a GA4 row needing the Admin API is OURS",
          blocked_on("GA4-03", {"source": "ga4_admin_only"}) == "vendor")
    check("a GSC row genuinely lacking a grant is still the client's",
          blocked_on("GSC-01", {"source": "gsc"}) == "client")
    check("our own missing credentials are never billed to the client",
          blocked_on("GSC-01", {"source": "gsc_misconfigured"}) == "vendor")
    mixed_cat = {"GSC-01": {"prefix": "GSC"}, "OFF-01": {"prefix": "OFF"},
                 "ZZZ-01": {"prefix": "ZZZ"}, "TECH-01": {"prefix": "TECH"}}
    c = _acounts({"TECH-01": {"status": "Pass"}}, mixed_cat)
    check("buckets split three ways over the whole catalog",
          (c["client"], c["vendor"], c["manual"], c["measured"]) == (1, 1, 1, 1),
          str(c))

    print("\nTHE ANALYST WORK LIST CONTAINS ONLY WORK FOR AN ANALYST")
    # The list is only worth reading if everything on it needs a person. A
    # checkpoint with a WORKING automated check used to land here whenever the
    # check came back empty — so PageSpeed Insights timing out put "open
    # DevTools and read the waterfall" in front of a human for three rows we
    # had automated the build before. They do the work twice, or they learn to
    # ignore the list.
    from engine.checks import REGISTRY as _REG
    import csv as _csv
    _cat = {r["id"]: r for r in _csv.DictReader(open("seed/checkpoints.csv"))}
    strays = sorted(c for c in _cat
                    if blocked_on(c) == "manual" and c in _REG)
    check("no checkpoint with an automated check is on the human list",
          not strays, str(strays[:8]))
    # And the inverse: a row we automated must be ours even with no finding,
    # because an empty row from a check that exists is our failure this run.
    for cid in ("PERF-05", "PERF-07", "PERF-09", "HTML-09", "ONP-43", "ANA-03"):
        check(f"{cid} is ours, not a person's", blocked_on(cid) == "vendor",
              blocked_on(cid))
    # The genuinely unautomated ones must NOT be swept up by the same rule.
    #
    # This list has been ONP-34, then ONP-43, then CANON-03/URL-05/INTL-08, then
    # SEC-06/07/15 — every one of them automated in turn. What is left is the AI
    # visibility rows, which a separate scheduled run answers rather than this
    # audit. If they ever leave too, this assertion should be deleted, not
    # weakened: an empty analyst list would be the point of all of it.
    import csv as _csv2
    _all = {r["id"] for r in _csv2.DictReader(open("seed/checkpoints.csv"))}
    left = sorted(c for c in _all if blocked_on(c) == "manual")
    check("no checkpoint in the catalog needs a person at all", not left,
          str(left))

    print("\nCOVERAGE IS REPORTED AS 'OF WHAT APPLIES', NOT 'OF THE TEMPLATE'")
    # "Analytics & Tracking — Reviewed 4/12" next to a rating of Strong reads as
    # "they managed a third of the audit". It was two different numbers printed
    # as one ratio: a numerator that excluded Info rows we HAD measured, over a
    # denominator that counted template rows which do not apply to this site.
    from engine.scoring import _coverage
    rows = [("A", {"status": "Pass"}), ("B", {"status": "Fail"}),
            ("C", {"status": "Info"}),            # measured, no threshold
            ("D", {"status": "N/A"}),             # does not apply here
            ("E", {"status": "Need Access"})]     # applies, could not answer
    cov = _coverage(rows, catalog_total=8)
    check("an Info row counts as reviewed — we measured and reported it",
          cov["reviewed"] == 3, str(cov))
    check("an N/A row leaves the denominator, not the numerator",
          cov["applies"] == 7 and cov["not_applicable"] == 1, str(cov))
    check("a Need Access row stays in the denominator — it applies and we missed it",
          cov["applies"] - cov["reviewed"] == 4, str(cov))
    # A section of nothing but inapplicable rows must not read as 0/8.
    allna = _coverage([("A", {"status": "N/A"})] * 8, catalog_total=8)
    check("a section that does not apply at all never reports a zero denominator",
          allna["applies"] >= allna["reviewed"] and allna["applies"] == 0,
          str(allna))

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
    cov = coverage_segments(132, 38, 128, 15)
    check("coverage segments are labelled in words",
          [c[0] for c in cov] == ["Measured", "Need your access",
                                  "We complete these", "Not applicable"])
    check("the client-facing ask is the small number, not the pile",
          cov[1][1] == 38 and cov[2][1] == 128, str([c[1] for c in cov]))

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

    print("\nAN OPTIONAL PHASE NOBODY TICKED IS NOT A DEFECT")
    # Consent and AI visibility are opt-in — one drives a browser, the other
    # pays several platforms per question — so most runs leave them off on
    # purpose. With both off, fifteen rows produced no findings and the panel
    # printed all fifteen under "Ours to fix — a credential we have not set".
    # Nothing was broken. A fix list full of no-action items is a list people
    # stop reading, which takes the one real failure down with it.
    from engine.report import _todo_panel
    from engine.consent.checks import CONS_IDS as _CONS
    from engine.aivis.geo_checks import GEO_IDS as _GEO
    import re as _re

    from engine.scoring import load_catalog as _load
    _cat = _load("seed/checkpoints.csv")
    _F = {c: {"status": "Pass", "value": {}, "evidence": "ok",
              "affected_pages": [], "severity": "Low", "recommendation": "",
              "confidence": 1.0, "source": "crawl"} for c in _cat}
    for _c in list(_CONS) + list(_GEO):
        _F.pop(_c, None)
    # One GENUINE vendor failure, so we can prove the split does not swallow
    # real problems along with the phases nobody asked for.
    _F["OFF-19"] = {"status": "Need Access", "value": {},
                    "evidence": "DataForSEO returned no rows",
                    "affected_pages": [], "severity": "Low",
                    "recommendation": "", "confidence": 1.0, "source": "dfs"}

    def _counts(phases):
        html = "".join(_todo_panel(_F, _cat, {"extras": {"phases_run": phases}}))
        def _n(label):
            m = _re.search(label + r" &middot; (\d+)</b>", html)
            return int(m.group(1)) if m else 0
        return _n("Ours to fix"), _n("Not requested on this run"), html

    ours, skip, html = _counts({"run_consent": False, "run_aivis": False})
    check("both phases off leaves only the real failure to fix",
          ours == 1, f"{ours} ours")
    check("and the rest are listed as not requested",
          skip == len(_CONS) + len(_GEO), f"{skip} skipped")
    check("phrased as a choice, never as a fault",
          "Not a fault" in html and "not scored against the client" in html)
    check("and it names the checkbox that would have covered them",
          "tick 'Consent &amp; privacy' on the next run" in html)

    # THE CASE THAT MUST NOT REGRESS. Ticking the box and getting nothing back
    # is a bug, and it has to stay on the fix list.
    ours2, skip2, _ = _counts({"run_consent": True, "run_aivis": False})
    check("a phase that WAS requested and returned nothing is still ours to fix",
          ours2 == 1 + len(_CONS), f"{ours2} ours")
    check("and only the unticked phase moves",
          skip2 == len(_GEO), f"{skip2} skipped")

    # An older audit recorded nothing. Claiming "not requested" without
    # evidence would hide real failures, so the RENDERER claims nothing...
    html3 = "".join(_todo_panel(_F, _cat, {"extras": {}}))
    check("the renderer claims nothing without evidence",
          "Not requested" not in html3)

    # ...but there IS evidence, and it was there the whole time. Every audit
    # row stores the options it was submitted with, and run_consent /
    # run_aivis live in them. Deriving from those makes the fix retroactive to
    # every audit ever run, instead of only to runs after this build — which
    # matters because the panel people are looking at right now is on a report
    # that already exists.
    import json as _json
    from app.api import _extras as _ex
    _pre32 = {"id": "a", "extras": _json.dumps({"context": {}}),
              "options": _json.dumps({"max_pages": 150, "run_consent": False})}
    check("a pre-stamp audit derives its phases from its own options",
          _ex(_pre32)["phases_run"] == {"run_consent": False,
                                        "run_aivis": False},
          str(_ex(_pre32).get("phases_run")))
    _on = {"id": "a", "extras": "{}",
           "options": _json.dumps({"run_consent": True, "run_aivis": True})}
    check("and a run that DID ask for them is not misread as unticked",
          _ex(_on)["phases_run"] == {"run_consent": True, "run_aivis": True})
    # The worker's stamp records what the run actually did; options record
    # what was asked of it. The stamp wins where both exist.
    _both = {"id": "a", "options": _json.dumps({"run_consent": False}),
             "extras": _json.dumps({"phases_run": {"run_consent": True,
                                                   "run_aivis": False}})}
    check("a recorded stamp beats the derived value",
          _ex(_both)["phases_run"]["run_consent"] is True)

    # End to end: the old report re-renders with the split.
    html4 = "".join(_todo_panel(_F, _cat, {"extras": _ex(_pre32)}))
    check("so an existing report stops printing unticked phases as defects",
          "Not requested on this run" in html4)

    print("\n" + "=" * 68)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — charts cannot report unmeasured as zero")
    print("=" * 68 + "\n")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
