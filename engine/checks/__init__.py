"""
Checkpoint registry.

Every checkpoint is a function taking the crawl artifact and returning a
Finding. Nothing here does I/O — all facts come from the artifact. That
separation is what makes checks cheap to unit-test and lets a single crawl
answer ~190 rows.

A check returns:
    status          Pass | Fail | Warning | Not Implemented | Need Access | N/A
    value           structured raw data ({"count": 579}) — never prose
    evidence        human-readable, goes straight into the report
    affected_pages  list of URLs (capped in the renderer)
    severity        Critical | High | Medium | Low | Opportunity
    recommendation  specific and actionable
"""
from __future__ import annotations

REGISTRY: dict = {}


def check(checkpoint_id: str):
    def deco(fn):
        REGISTRY[checkpoint_id] = fn
        return fn
    return deco


def finding(status, value=None, evidence="", pages=None, severity="Medium",
            recommendation="", confidence=1.0):
    return {"status": status, "value": value or {}, "evidence": evidence,
            "affected_pages": pages or [], "severity": severity,
            "recommendation": recommendation, "confidence": confidence}


def escalate(count, bands):
    """Severity from magnitude. bands = [(threshold, severity), ...] ascending."""
    sev = "Pass"
    for thresh, s in bands:
        if count >= thresh:
            sev = s
    return sev


# import side-effect: populate REGISTRY
from . import crawler_checks, tagdetect, security, geo_schema, perf  # noqa: E402,F401


# Downstream consumers (severity escalation, the renderer, trend tracking) all
# key off value["count"]. Checkers that name their countable field something
# more descriptive get normalised here rather than each caller guessing.
_COUNT_ALIASES = ("count", "pages_affected", "missing", "missing_lang", "invalid",
                  "malformed_lines", "http_pages", "not_lazy", "without_srcset",
                  "disallow_rules", "skipped_levels")


def _normalise(f):
    v = f.get("value")
    if isinstance(v, dict) and "count" not in v:
        for k in _COUNT_ALIASES:
            if k in v and isinstance(v[k], int):
                v["count"] = v[k]
                break
    return f


# Checkpoints that DO NOT depend on page HTML. These stay valid even when the
# crawler was blocked, because they read robots.txt, the sitemap, DNS/TLS, HTTP
# redirects, or an external API — none of which need the page body.
INFRASTRUCTURE_ONLY = {
    # robots.txt / sitemap
    "TECH-13", "TECH-14", "TECH-18", "TECH-19", "TECH-21", "TECH-22", "TECH-23",
    "TECH-24", "TECH-26", "TECH-27", "TECH-28", "TECH-30", "TECH-15",
    # host resolution & transport
    "URL-01", "URL-06", "URL-15", "URL-16",
    "SEC-01", "SEC-02", "SEC-03", "SEC-04", "SEC-09", "SEC-10", "SEC-11",
    "EEAT-19",
    # llms.txt + AI crawler policy (fetched independently of the page)
    "GEO-01", "GEO-02", "GEO-03", "GEO-04",
    # PageSpeed Insights (Google fetches the page itself, not us)
    "PERF-10", "PERF-11", "PERF-12", "PERF-13", "PERF-14", "PERF-19",
}


def run_all(art, ctx=None):
    """
    Execute every registered check against the artifact.

    If the crawl was degenerate (blocked, or a JS-only shell), content-dependent
    checkpoints return Need Access instead of Fail. A crawler that could not see
    the page must not report the page as broken — that turns one infrastructure
    problem into twenty false findings, which is exactly what happened on the
    first production run against a bot-protected site.
    """
    ctx = ctx or {}
    q = getattr(art, "quality", None)
    blocked = bool(q and q.degenerate)
    out = {}
    for cid, fn in REGISTRY.items():
        if blocked and cid not in INFRASTRUCTURE_ONLY:
            out[cid] = finding(
                "Need Access",
                {"crawl_blocked": True, "homepage_bytes": q.homepage_bytes},
                f"Not assessed — the crawler could not retrieve usable page "
                f"content ({q.likely_cause}). Reporting this as a defect would "
                f"be inaccurate.",
                severity="Medium", confidence=0.0)
            out[cid]["source"] = "crawl_blocked"
            continue
        try:
            f = fn(art, ctx)
            if f is None:
                continue
            f.setdefault("source", fn.__module__.split(".")[-1])
            out[cid] = _normalise(f)
        except Exception as e:
            out[cid] = finding("N/A", evidence=f"checker error: {type(e).__name__}: {e}",
                               severity="Low", confidence=0.0)
            out[cid]["source"] = "error"
    return out
