"""
Map monitor results onto audit checkpoints GEO-23 … GEO-30.

These eight rows are marked "Manual Review" in the audit template, which today
means someone typing prompts into chat windows and screenshotting the answers.
This module replaces that with a measurement.

Note the honest handling of the two rows that are NOT AI platforms:
GEO-24 (Featured Snippets) and GEO-25 (Passage Ranking) are Google SERP features.
They cannot be measured by querying chatbots, so unless a SERP provider is
configured they report `Need Access` rather than borrowing a number from an
adjacent platform. Fabricating coverage is how an automated audit loses the
credibility of its other 300 rows.
"""
from __future__ import annotations

PLATFORM_CHECKPOINT = {
    "ai_overview": ("GEO-23", "Google AI Overviews"),
    "copilot":     ("GEO-26", "Microsoft Bing Copilot"),
    "chatgpt":     ("GEO-27", "ChatGPT"),
    "perplexity":  ("GEO-28", "Perplexity"),
    "gemini":      ("GEO-29", "Google Gemini"),
    "claude":      ("GEO-30", "Claude"),
}

SERP_FEATURE_ROWS = {
    "GEO-24": "Featured Snippets",
    "GEO-25": "Passage-based / long-tail ranking",
}


def _finding(status, value=None, evidence="", pages=None, severity="Medium",
             recommendation="", confidence=1.0, source="ai_visibility"):
    return {"status": status, "value": value or {}, "evidence": evidence,
            "affected_pages": pages or [], "severity": severity,
            "recommendation": recommendation, "confidence": confidence,
            "source": source}


def _severity(citation_rate, mention_rate):
    """Citation drives severity; mention only softens it."""
    if citation_rate is None:
        return "Medium"
    if citation_rate >= 25:
        return "Low"
    if citation_rate >= 10:
        return "Medium"
    if citation_rate > 0 or (mention_rate or 0) > 20:
        return "High"
    return "Critical"


def findings_from_run(agg: dict, profile) -> dict:
    """Produce the GEO-23..30 findings dict from an aggregate."""
    out = {}
    by_platform = agg.get("by_platform", {}) or {}
    skipped = set(agg.get("skipped_platforms", []) or [])
    repeats = agg.get("repeats", 1)

    for plat, (cid, label) in PLATFORM_CHECKPOINT.items():
        stats = by_platform.get(plat)

        if not stats:
            reason = ("not configured — no API credentials supplied"
                      if plat in skipped else "no successful responses collected")
            out[cid] = _finding(
                "Need Access", {"platform": plat},
                f"{label} visibility not measured: {reason}.",
                severity="Medium", confidence=0.0,
                recommendation=f"Configure {label} access to measure citation share.")
            continue

        cr, mr = stats["citation_rate"], stats["mention_rate"]
        n = stats["answers"]
        status = "Pass" if (cr or 0) >= 25 else ("Warning" if (cr or 0) > 0
                                                else "Not Implemented")
        ev = (f"{label}: cited as a source in {cr}% of {n} answers "
              f"({repeats} repeats per query); brand mentioned in {mr}%. "
              f"Average {stats['avg_citations']} sources cited per answer.")
        rec = ""
        if (cr or 0) < 25:
            top = agg.get("top_competitor_domain")
            rec = (f"Increase citation-worthy content — FAQ blocks, original data and "
                   f"clear entity markup — targeting the queries where {label} currently "
                   f"cites other sources")
            rec += f" such as {top}." if top else "."
        out[cid] = _finding(status,
                            {"citation_rate": cr, "mention_rate": mr, "answers": n,
                             "avg_prominence": stats["avg_prominence"],
                             "errors": stats["errors"]},
                            ev, severity=_severity(cr, mr), recommendation=rec)

    # SERP-feature rows — measured only if a SERP provider ran.
    serp_ran = "ai_overview" in by_platform
    for cid, label in SERP_FEATURE_ROWS.items():
        if serp_ran:
            cr = by_platform["ai_overview"]["citation_rate"]
            # A PROXY CAN NEVER PRODUCE A PASS.
            # "Pass" asserts we checked this and it is fine. We did not check it —
            # we looked at an adjacent surface and inferred. The best a 0.4-
            # confidence inference may claim is "Warning: look at this yourself".
            # Letting a proxy report Pass is how an automated audit quietly starts
            # certifying things it never measured.
            out[cid] = _finding(
                "Warning",
                {"proxy": "ai_overview", "proxy_citation_rate": cr,
                 "directly_measured": False},
                f"{label} was NOT measured directly. The Google AI Overviews citation "
                f"rate ({cr}%) is shown as a directional proxy only — treat this row as "
                f"unverified.",
                severity="Medium", confidence=0.4,
                recommendation="Add a dedicated SERP-feature check to measure this "
                               "directly rather than inferring it.")
        else:
            out[cid] = _finding(
                "Need Access", {},
                f"{label} is a Google SERP feature, not an AI chat platform — it "
                f"requires a SERP data provider and was not measured.",
                severity="Medium", confidence=0.0,
                recommendation="Configure SERP_ENDPOINT / SERP_API_KEY to measure this.")
    return out


def summary_row(agg: dict, profile) -> dict:
    """A compact record for the time series."""
    return {
        "mention_rate": agg.get("mention_rate"),
        "citation_rate": agg.get("citation_rate"),
        "unprompted_citation_rate": agg.get("unprompted_citation_rate"),
        "client_citations": agg.get("client_citations"),
        "top_competitor_domain": agg.get("top_competitor_domain"),
        "citation_gap": agg.get("citation_gap"),
        "answers_ok": agg.get("answers_ok"),
    }


# The eight rows this module answers. Exported so the access bucketing knows
# they belong to a tool of ours rather than to a person — they were the last
# entries on the analyst work list, and only because the monitor had to be
# started by hand. It is a phase of the audit now.
GEO_IDS = tuple(f"GEO-{i}" for i in range(23, 31))
