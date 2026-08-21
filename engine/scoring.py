"""
Scoring engine — implements the template's own rubric (spec §8).

Two guardrails that matter more than the formula:
  1. A section where everything is Need Access scores None ("Not Assessed"),
     never 0. Conflating "we couldn't check" with "it's broken" is the fastest
     way to lose a partner's trust.
  2. Penalty is capped per section so one catastrophic row doesn't flatten an
     otherwise-healthy section into noise.
"""
from __future__ import annotations
import csv
from collections import defaultdict

PENALTY = {"Critical": 25, "High": 12, "Medium": 6, "Low": 2, "Opportunity": 0}
FAILING = {"Fail", "Not Implemented", "Warning"}
# "Info" is a MEASUREMENT, not a test: a backlink count, a referring-IP count.
# There is no number of backlinks that is correct, so such a row can neither
# pass nor fail, and counting it as a pass is how retrieving thirteen numbers
# scored Off-Page authority 94/100 Excellent. Excluded from the score the same
# way N/A is — and, like N/A, excluded from the coverage denominator too, since
# it is not something we failed to see.
EXCLUDED = {"N/A", "Need Access", "Info"}
INFORMATIONAL = {"Info"}
CAP = 70  # max penalty a single section can accrue

# A section must have at least this fraction of its checkpoints assessable
# before we publish a score for it.
MIN_SECTION_COVERAGE = 0.5

BANDS = [(90, "Excellent"), (75, "Strong"), (60, "Needs Improvement"),
         (40, "Weak"), (0, "Critical")]

VERTICAL_WEIGHTS = {
    "ecommerce":    {"SCHEMA-06": 2.0, "SCHEMA-08": 1.5, "PERF": 1.3, "EEAT-05": 0.6},
    "finance_ymyl": {"EEAT": 1.5, "SCHEMA-09": 1.2, "GEO": 1.3},
    "local_service": {"SCHEMA-09": 2.0, "ANA-10": 1.5, "MOB": 1.3},
}


def weight_for(cid: str, vertical: str | None) -> float:
    if not vertical:
        return 1.0
    w = VERTICAL_WEIGHTS.get(vertical, {})
    return w.get(cid, w.get(cid.split("-")[0], 1.0))


def rating(score):
    if score is None:
        return "Not Assessed"
    for thresh, label in BANDS:
        if score >= thresh:
            return label
    return "Critical"


def load_catalog(path="checkpoints.csv"):
    cat = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            cat[r["id"]] = r
    return cat


def _coverage(rows, catalog_total: int) -> dict:
    """
    What the READER should be told about coverage, as opposed to what the
    scoring maths needs.

    Two different numbers were being printed as one. `checked` counts rows that
    could be SCORED, and the denominator counted every row the template has —
    so International SEO showed "2/8" next to a rating of Excellent, and
    Analytics showed "4/12". Both read as "we managed a third of the audit",
    which is not what happened and is a bad thing for a client to conclude.

    Two corrections, and they pull in opposite directions:

      * N/A comes OUT of the denominator. A US-only law firm has six
        international checkpoints that do not apply to it. They are not gaps in
        our work and counting them as such invents a shortfall.

      * Info goes INTO the numerator. An Info row is a measurement we took and
        reported — a backlink count, a referring-domain total — it simply has
        no pass/fail threshold behind it. Excluding it from "reviewed" hid
        thirteen answered Off-Page rows and reported 10 of 29 for a section we
        had largely measured.

    What is left in the denominator and out of the numerator is the honest
    remainder: checks that apply to this site and that we could not answer.
    """
    na = sum(1 for r in rows if r[1]["status"] == "N/A")
    answered = sum(1 for r in rows if r[1]["status"] not in ("Need Access", "N/A"))
    return {"reviewed": answered, "applies": max(answered, catalog_total - na),
            "not_applicable": na}



def score(findings: dict, catalog: dict, vertical: str | None = None):
    sections = defaultdict(list)
    for cid, f in findings.items():
        meta = catalog.get(cid)
        if not meta:
            continue
        sections[meta["prefix"]].append((cid, f, meta))

    # How many checkpoints the TEMPLATE has in this area, as opposed to how
    # many we returned a finding for. Reporting "34/34" for a section the
    # template gives 50 rows reads as full coverage of the area; it was really
    # full coverage of the subset we automated. The gating denominator below is
    # deliberately NOT changed — see the comment there.
    catalog_totals = defaultdict(int)
    for meta in catalog.values():
        catalog_totals[(meta or {}).get("prefix")] += 1

    out, per_section = {}, {}
    for sec, rows in sections.items():
        applicable = [(c, f) for c, f, m in rows if f["status"] not in EXCLUDED]
        if not applicable:
            per_section[sec] = {
                "score": None, "rating": "Not Assessed",
                "checked": 0, "total": catalog_totals[sec] or len(rows),
                "returned": len(rows), "failing": 0, "need_access": len(rows),
                **_coverage([(c, f) for c, f, _m in rows],
                            catalog_totals[sec] or len(rows))}
            continue
        pen = 0.0
        fails = []
        for cid, f in applicable:
            if f["status"] in FAILING:
                pen += PENALTY.get(f["severity"], 6) * weight_for(cid, vertical)
                fails.append(cid)
        pen = min(pen, CAP)
        s = max(0, min(100, round(100 - pen)))

        # A score computed from a small minority of a section's checkpoints is
        # not a verdict on that section — it is a verdict on whichever handful
        # happened to be measurable. "E-E-A-T 100/100 Excellent" off a single
        # TLS check out of nine is actively misleading, and flattering errors
        # are the dangerous kind.
        # Coverage is measured against what COULD be assessed. "Need Access"
        # counts against us — the check applies and we could not see it. "N/A"
        # does not — the check does not apply to this site, so including it in
        # the denominator would mark a section unassessable for the crime of
        # having irrelevant rows in the template. Without this, a site that runs
        # no paid ads can never score its Analytics section.
        assessable = [r for r in rows
                      if r[1]["status"] not in ("N/A", "Info")]
        if len(applicable) / max(1, len(assessable)) < MIN_SECTION_COVERAGE:
            per_section[sec] = {
                "score": None, "rating": "Not Assessed",
                "checked": len(applicable),
                "total": catalog_totals[sec] or len(rows),
                "returned": len(rows), "failing": len(fails),
                "need_access": sum(1 for _, f, _ in rows
                                   if f["status"] == "Need Access"),
                "insufficient_coverage": True,
                **_coverage([(c, f) for c, f, _m in rows],
                            catalog_totals[sec] or len(rows))}
            continue

        per_section[sec] = {
            "score": s, "rating": rating(s), "checked": len(applicable),
            "total": catalog_totals[sec] or len(rows), "returned": len(rows),
            "failing": len(fails),
            "need_access": sum(1 for _, f, _ in rows if f["status"] == "Need Access"),
            "failing_ids": fails,
            **_coverage([(c, f) for c, f, _m in rows],
                        catalog_totals[sec] or len(rows)),
        }

    scored = [v["score"] for v in per_section.values() if v["score"] is not None]
    overall = round(sum(scored) / len(scored)) if scored else None

    # Refuse to publish an overall score built from a small minority of sections.
    # A blocked crawl leaves only the infrastructure sections assessable, and a
    # confident "68/100" on top of that reads as a verdict on the site when it is
    # really a verdict on four robots.txt checks.
    assessed = len(scored)
    total_sections = len(per_section)
    if total_sections and assessed / total_sections < 0.5:
        overall = None
    out["sections"] = per_section
    out["overall"] = {"score": overall, "rating": rating(overall)}
    return out


def top_issues(findings, catalog, n=8):
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Opportunity": 4}
    rows = [(cid, f) for cid, f in findings.items()
            if f["status"] in FAILING and cid in catalog]
    rows.sort(key=lambda x: (order.get(x[1]["severity"], 9),
                             -(x[1]["value"].get("count", 0)
                               if isinstance(x[1].get("value"), dict) else 0)))
    return rows[:n]


def wins(findings, catalog, n=6):
    rows = [(cid, f) for cid, f in findings.items()
            if f["status"] == "Pass" and cid in catalog and f["evidence"]]
    return rows[:n]
