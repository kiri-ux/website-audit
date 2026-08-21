"""
Who is a missing checkpoint actually blocked on?

Until now the report had one bucket — "Need Access" — and told the client it
meant "accounts only you control". For 38 of those rows that is true. For the
other ~120 it is not: they are waiting on a vendor key we have not set, or on a
checkpoint we have not automated yet. Printing our own configuration gap as the
client's homework is the single most embarrassing thing this document can do,
and it did it on every run.

Three buckets, one rule each:

  client  The data lives in an account we cannot see without a grant. Search
          Console and Analytics. This is the ONLY bucket the client can act on,
          and the only number worth putting in front of them as an ask.

  vendor  We own this and have not wired it up for this run — a backlink
          provider, the judgment layer's LLM key, Lighthouse. Nothing for the
          client to do. It disappears the moment the key is set, which makes it
          a deployment checklist item rather than a finding.

  manual  No automation exists for this checkpoint. Brendan's template handles
          these by hand and so do we. Honest framing: reviewed during the
          engagement, not "we couldn't get in".

Deliberately conservative: anything unrecognised falls to `manual` rather than
`client`, because over-reporting the client's homework is the failure we are
fixing.
"""
from __future__ import annotations

# Accounts the CLIENT grants. Nothing else belongs here.
CLIENT_PREFIXES = ("GSC", "GA4")


def _vendor_ids() -> set:
    """
    Checkpoints a collector or the judgment layer owns.

    Imported lazily and defensively: this module is pulled in by the PDF
    renderer, which runs in the API process where the collector's optional
    dependencies may not matter. A missing import must degrade to "manual",
    never take the report down.
    """
    ids = set()
    try:
        from engine.judgment import CHECKPOINT_IDS
        ids |= set(CHECKPOINT_IDS)
    except Exception:  # noqa: BLE001
        pass
    try:
        from engine.collectors.dataforseo import LIGHTHOUSE_IDS
        ids |= set(LIGHTHOUSE_IDS)
    except Exception:  # noqa: BLE001
        pass
    return ids


_VENDOR_CACHE: set | None = None


def vendor_ids() -> set:
    global _VENDOR_CACHE
    if _VENDOR_CACHE is None:
        _VENDOR_CACHE = _vendor_ids()
    return _VENDOR_CACHE


# Search Console and Analytics rows that the APIs simply do not expose. The
# client granting access changes nothing about them — they are answered from
# the Search Console UI or the GA4 Admin API, and until we write that, they are
# OURS. Filing them under "waiting on a client grant" produced the worst kind
# of error: a run where access demonstrably worked (11 of 38 rows filled with
# real numbers) still told us to go and ask the client for access again.
OURS_DESPITE_PREFIX = {"gsc_ui_only", "ga4_admin_only",
                       "gsc_misconfigured", "ga4_misconfigured"}

# And a third case, which is neither: reports Google publishes in the Search
# Console interface and exposes through no API at all — the external-links and
# top-linking-sites reports. No grant unlocks them and no build we could do
# would reach them. They belong with the checkpoints an analyst reads by hand,
# not on a list of things we owe the client or ourselves.
MANUAL_DESPITE_PREFIX = {"gsc_no_api", "ga4_no_api"}


def blocked_on(cid: str, finding: dict | None = None) -> str:
    """
    'client' | 'vendor' | 'manual' for a checkpoint we could not measure.

    The REASON decides, not the section. Two GSC rows can be blocked on
    completely different people: GSC-01 needs the client's grant, GSC-05 needs
    us to write the Index Inspection call. Bucketing by prefix called both the
    client's problem.
    """
    src = (finding or {}).get("source") or ""
    if src in OURS_DESPITE_PREFIX:
        return "vendor"
    if src in MANUAL_DESPITE_PREFIX:
        return "manual"
    if cid.split("-")[0] in CLIENT_PREFIXES:
        return "client"
    if cid.startswith("OFF-") or cid in vendor_ids():
        return "vendor"
    return "manual"


def buckets(findings: dict, catalog: dict) -> dict:
    """
    Classify the WHOLE catalog, not just the rows we returned findings for.

    A checkpoint with no finding at all is the one that used to vanish: it was
    counted as Need Access in the coverage strip and then omitted from an
    appendix headed "the full record, by area". Both halves of that were wrong.
    """
    out = {"measured": [], "client": [], "vendor": [], "manual": [], "na": []}
    for cid in catalog:
        f = findings.get(cid)
        if f is None:
            out[blocked_on(cid)].append(cid)
        elif f.get("status") == "Need Access":
            out[blocked_on(cid, f)].append(cid)
        elif f.get("status") == "N/A":
            out["na"].append(cid)
        else:
            out["measured"].append(cid)
    return out


def counts(findings: dict, catalog: dict) -> dict:
    return {k: len(v) for k, v in buckets(findings, catalog).items()}
