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
EXCLUDED = {"N/A", "Need Access"}
CAP = 70  # max penalty a single section can accrue

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


def score(findings: dict, catalog: dict, vertical: str | None = None):
    sections = defaultdict(list)
    for cid, f in findings.items():
        meta = catalog.get(cid)
        if not meta:
            continue
        sections[meta["prefix"]].append((cid, f, meta))

    out, per_section = {}, {}
    for sec, rows in sections.items():
        applicable = [(c, f) for c, f, m in rows if f["status"] not in EXCLUDED]
        if not applicable:
            per_section[sec] = {"score": None, "rating": "Not Assessed",
                                "checked": 0, "total": len(rows),
                                "failing": 0, "need_access": len(rows)}
            continue
        pen = 0.0
        fails = []
        for cid, f in applicable:
            if f["status"] in FAILING:
                pen += PENALTY.get(f["severity"], 6) * weight_for(cid, vertical)
                fails.append(cid)
        pen = min(pen, CAP)
        s = max(0, min(100, round(100 - pen)))
        per_section[sec] = {
            "score": s, "rating": rating(s), "checked": len(applicable),
            "total": len(rows), "failing": len(fails),
            "need_access": sum(1 for _, f, _ in rows if f["status"] == "Need Access"),
            "failing_ids": fails,
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
