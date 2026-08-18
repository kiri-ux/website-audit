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


def run_all(art, ctx=None):
    """Execute every registered check against the artifact."""
    ctx = ctx or {}
    out = {}
    for cid, fn in REGISTRY.items():
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
