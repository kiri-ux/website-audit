"""
Executive summary and prioritized roadmap.

The only page most clients read. Everything here is generated from the SCORED
findings, never from raw crawl data — the scoring pass has already decided what
matters, and re-deciding it in a prompt would produce a summary that disagrees
with the table underneath it.

Two modes:
  * deterministic (default) — assembled from the findings by plain code. Free,
    instant, and it cannot hallucinate. Good enough to ship.
  * LLM polish (optional)   — rewrites the deterministic draft into client-ready
    prose. Enabled when an API key is present; the FACTS still come from the
    deterministic pass, so the model is editing, not deciding.

That split matters. Letting a model choose the findings would let it invent one.
Letting it only rephrase pre-selected findings bounds the damage to tone.
"""
from __future__ import annotations
import json
import os

from .scoring import FAILING, top_issues

# Sentence-start form. Written out rather than derived, because .capitalize()
# turns "E-E-A-T" into "E-e-a-t" and "HTTPS" into "Https".
SECTION_NAMES = {
    "ANA": "Analytics and tracking", "GSC": "Search Console", "GA4": "Google Analytics",
    "TECH": "Technical SEO", "URL": "URL structure", "SEC": "HTTPS and security",
    "CANON": "Canonicalisation", "PERF": "Site performance and Core Web Vitals",
    "ONP": "On-page SEO", "MOB": "Mobile SEO", "SCHEMA": "Structured data",
    "INTL": "International SEO", "HTML": "HTML and code quality",
    "EEAT": "E-E-A-T and trust signals", "GEO": "AI search visibility (GEO)",
    "OFF": "Off-page authority",
}

VERTICAL_NOTE = {
    "ecommerce": ("Product and Review schema, page speed and mobile experience carry "
                  "disproportionate weight for a retailer."),
    "finance_ymyl": ("As a YMYL brand, author credentials, expert review and "
                     "organisational trust signals matter far more than they would "
                     "in most sectors."),
    "local_service": ("LocalBusiness schema, location pages and call tracking are the "
                      "highest-leverage signals for a service business."),
}


def _pct(v):
    return "—" if v is None else f"{v}"


def build_summary(findings: dict, scores: dict, catalog: dict,
                  meta: dict | None = None) -> dict:
    """Deterministic executive summary. No model required."""
    meta = meta or {}
    secs = scores.get("sections") or {}
    assessed = {k: v for k, v in secs.items() if v.get("score") is not None}

    strong = sorted(assessed.items(), key=lambda kv: -kv[1]["score"])[:4]
    weak = sorted(assessed.items(), key=lambda kv: kv[1]["score"])[:4]

    # ---------- What's Working ----------
    working = []
    for code, v in strong:
        if v["score"] < 75:
            continue
        passes = [cid for cid, f in findings.items()
                  if (catalog.get(cid, {}) or {}).get("prefix") == code
                  and f["status"] == "Pass"]
        # Count against ASSESSED checkpoints, not the section total. Saying
        # "1 of 4 passing" next to a 94/100 Excellent rating reads as a
        # contradiction; the other 3 were Need Access or N/A, not failures.
        working.append(
            f"{SECTION_NAMES.get(code, code)} scores {v['score']}/100 "
            f"({v['rating']}) — {len(passes)} of {v['checked']} assessed "
            f"checkpoints passing.")
    if not working:
        working.append("No section reached a Strong rating in this audit.")

    # ---------- Priority Issues ----------
    issues = []
    for cid, f in top_issues(findings, catalog, 5):
        m = catalog.get(cid, {})
        issues.append(f"{m.get('checkpoint', cid)} ({f['severity']}): "
                      f"{f.get('evidence','').rstrip('.')}.")

    # ---------- Biggest Opportunity ----------
    opp = ""
    if weak:
        code, v = weak[0]
        gaps = [cid for cid, f in findings.items()
                if (catalog.get(cid, {}) or {}).get("prefix") == code
                and f["status"] in FAILING]
        names = [catalog.get(c, {}).get("checkpoint", c) for c in gaps[:5]]
        opp = (f"{SECTION_NAMES.get(code, code)} is the least mature area "
               f"at {v['score']}/100 ({v['rating']}), with {v['failing']} of "
               f"{v['checked']} assessed checkpoints needing work"
               + (f" — including {', '.join(names[:3])}." if names else "."))
        note = VERTICAL_NOTE.get(meta.get("vertical") or "")
        if note:
            opp += " " + note

    # ---------- overview ----------
    o = scores.get("overall", {}) or {}
    n_fail = sum(1 for f in findings.values() if f["status"] in FAILING)
    n_na = sum(1 for f in findings.values() if f["status"] == "Need Access")
    overview = (
        f"This audit evaluated {len(findings)} checkpoints across "
        f"{len(secs)} areas of {meta.get('client', 'the site')}"
        + (f", based on {meta.get('pages_crawled')} pages analysed" if meta.get("pages_crawled") else "")
        + ". "
        + (f"The overall score is {o.get('score')}/100 ({o.get('rating')}). "
           if o.get("score") is not None else
           "No overall score is published because too few sections could be assessed. ")
        + f"{n_fail} checkpoints require action"
        + (f"; {n_na} could not be assessed and are reported as Need Access rather "
           f"than as defects." if n_na else "."))

    return {"overview": overview, "working": working, "issues": issues,
            "opportunity": opp, "roadmap": build_roadmap(findings, catalog),
            "generated_by": "deterministic"}


def build_roadmap(findings: dict, catalog: dict) -> list:
    """
    Group actionable findings into phases by severity.

    Sequenced by severity rather than by section, because that is the order a
    client should actually work in — and it makes the roadmap fall out of the
    scoring rubric instead of being invented separately.
    """
    buckets = {"Critical": [], "High": [], "Medium": [], "Low": [], "Opportunity": []}
    for cid, f in findings.items():
        if f["status"] not in FAILING:
            continue
        sev = f.get("severity", "Medium")
        if sev in buckets:
            m = catalog.get(cid, {})
            buckets[sev].append(
                f"{m.get('checkpoint', cid)} — "
                f"{f.get('recommendation') or f.get('evidence', '')}".strip().rstrip(".") + ".")

    phases = []
    if buckets["Critical"] or buckets["High"]:
        phases.append({
            "phase": "Phase 1 — Immediate (0–30 days)",
            "rationale": "Issues that block indexing, create risk, or have broad "
                         "sitewide impact. Fix these before any content work.",
            "actions": (buckets["Critical"] + buckets["High"])[:10]})
    if buckets["Medium"]:
        phases.append({
            "phase": "Phase 2 — Short term (30–90 days)",
            "rationale": "Meaningful improvements with moderate effort, including "
                         "structured data and on-page optimisation.",
            "actions": buckets["Medium"][:12]})
    if buckets["Low"]:
        phases.append({
            "phase": "Phase 3 — Ongoing (90+ days)",
            "rationale": "Cleanup and best-practice work, best folded into normal "
                         "release cycles.",
            "actions": buckets["Low"][:10]})
    if buckets["Opportunity"]:
        phases.append({
            "phase": "Growth initiatives",
            "rationale": "Beyond defect remediation — where new visibility is won.",
            "actions": buckets["Opportunity"][:8]})
    return phases


# --------------------------------------------------------------------------
def polish_with_llm(summary: dict, meta: dict) -> dict:
    """
    Optional: rewrite the deterministic draft as client-ready prose.

    The model receives the ALREADY-SELECTED facts and is told to rephrase only.
    It cannot add findings, and on any failure the deterministic version is
    returned unchanged — a summary that silently degrades to plain English is
    far better than one that invents a problem.
    """
    key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        return summary

    prompt = (
        "You are writing the executive summary of a professional SEO audit for a "
        "paying client.\n\n"
        f"Client: {meta.get('client')}\nWebsite: {meta.get('url')}\n"
        f"Business type: {meta.get('vertical') or 'general'}\n\n"
        "Below are the findings ALREADY SELECTED by the scoring engine. Rewrite "
        "them as clear, confident, non-hyperbolic prose suitable for a business "
        "owner.\n\n"
        "STRICT RULES:\n"
        "- Do NOT add any finding, number, or claim that is not below.\n"
        "- Do NOT soften or dramatise the severity.\n"
        "- Keep every number exactly as given.\n"
        "- No marketing language, no 'unlock', no 'leverage'.\n\n"
        f"OVERVIEW: {summary['overview']}\n\n"
        f"WHAT'S WORKING:\n" + "\n".join(f"- {x}" for x in summary["working"]) + "\n\n"
        f"PRIORITY ISSUES:\n" + "\n".join(f"- {x}" for x in summary["issues"]) + "\n\n"
        f"BIGGEST OPPORTUNITY: {summary['opportunity']}\n\n"
        "Return JSON only: {\"overview\": str, \"working\": [str], "
        "\"issues\": [str], \"opportunity\": str}"
    )

    try:
        import urllib.request
        if os.getenv("ANTHROPIC_API_KEY"):
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps({
                    "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
                    "max_tokens": 1500,
                    "messages": [{"role": "user", "content": prompt}]}).encode(),
                headers={"Content-Type": "application/json",
                         "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
                         "anthropic-version": "2023-06-01"}, method="POST")
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read())
            text = "".join(b.get("text", "") for b in d.get("content", [])
                           if b.get("type") == "text")
        else:
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=json.dumps({
                    "model": os.getenv("OPENAI_MODEL", "gpt-4.1"),
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"}}).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
                method="POST")
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read())
            text = d["choices"][0]["message"]["content"]

        start, end = text.find("{"), text.rfind("}")
        polished = json.loads(text[start:end + 1])
        for k in ("overview", "working", "issues", "opportunity"):
            if k in polished and polished[k]:
                summary[k] = polished[k]
        summary["generated_by"] = "llm_polished"
    except Exception as e:
        summary["polish_error"] = f"{type(e).__name__}: {e}"
    return summary
