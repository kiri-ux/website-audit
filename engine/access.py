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

  manual  No automation exists for this checkpoint at all. Brendan's template
          handles these by hand and so did we. As of this build the catalog has
          NONE left — every one has been automated in turn — but the bucket
          stays, because the fallback below has to land somewhere and it must
          not land on the client.

Deliberately conservative: anything unrecognized falls to `manual` rather than
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
    # EVERY CHECKPOINT WITH A REGISTERED CHECK.
    #
    # This is the one that made the analyst work list dishonest. A checkpoint
    # that returned no finding fell through to `manual` by default — and
    # "default to manual" was the right call when the alternative was blaming
    # the client, but it also swept up rows we have fully automated. PERF-05,
    # PERF-07, PERF-09, HTML-09, ONP-43 and ANA-03 all have working checks and
    # were still printed on a person's to-do list, because PageSpeed Insights
    # timed out and the check never got to answer.
    #
    # Asking someone to open DevTools and read a waterfall we automated last
    # build is worse than useless: they do the work twice, or they learn to
    # ignore the list. If a check exists, an empty row is OUR failure this run,
    # not a human's job.
    try:
        from engine.checks import REGISTRY
        ids |= set(REGISTRY)
    except Exception:  # noqa: BLE001
        pass
    # Rows a collector answers from under a different prefix — the sitemap
    # submission and index-coverage rows live in TECH, and Search Console
    # verification lives in ANA, but Search Console answers all three.
    try:
        from engine.collectors.analytics import GSC_EXTRA_IDS
        ids |= set(GSC_EXTRA_IDS)
    except Exception:  # noqa: BLE001
        pass
    # AI visibility. These ran last on the analyst list, and only because the
    # monitor had to be started by hand from a profile someone typed out. The
    # audit builds that profile from its own crawl now and runs the panel as a
    # phase, so an empty GEO row means a platform key we have not set — ours.
    try:
        from engine.aivis.geo_checks import GEO_IDS
        ids |= set(GEO_IDS)
    except Exception:  # noqa: BLE001
        pass
    # Consent and privacy. The scanner answers all nine; an empty row means the
    # phase was not run or the browser was unavailable, both of which are ours.
    try:
        from engine.consent.checks import CONS_IDS
        ids |= set(CONS_IDS)
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
                       "gsc_misconfigured", "ga4_misconfigured",
                       # The three link reports. Google exposes no API for
                       # them, so the backlink index answers them instead —
                       # which makes an empty row our failed call, not a
                       # missing client grant and not a job for a person.
                       "gsc_no_api", "ga4_no_api"}

# THIS SET IS NOW EMPTY, AND THAT IS THE POINT.
#
# It held `gsc_no_api` — the three link reports Google publishes and exposes
# through no API. At the time they genuinely were an analyst's read, so filing
# them under "a person does this" was honest.
#
# They are not any more: the backlink index answers all three. The source tag
# survives as the label for "Search Console cannot give us this", but an empty
# row now means our DataForSEO call did not land, which is OURS. Leaving the
# mapping in place kept GSC-22 on a human's list every time that call missed —
# a work item for a person that no person could do anything about.
#
# The set stays declared because the DISTINCTION is still real, and the next
# genuinely-unautomatable checkpoint should land here rather than on the client.
MANUAL_DESPITE_PREFIX: set = set()

# THEIRS, DESPITE HAVING A CHECK OF OUR OWN.
#
# The mirror of OURS_DESPITE_PREFIX, and it exists because `_vendor_ids`
# sweeps in every id with a registered check - correctly, since an empty row
# for an automated check is usually our failed call. ANA-03 is the exception
# that proves it. It HAS a check, the check RAN, and it answered honestly:
# there is no google-site-verification tag in the source, and verification by
# DNS or by an uploaded file leaves nothing we can see from outside. The row
# even says what closes it - "confirmed either way once Search Console access
# is connected" - which is a grant only the client can give.
#
# So it was printed under "a credential we have not set, or a call we have not
# written", next to its own text saying the opposite. That contradiction is
# the exact failure this panel has now hit four times: a fix list that fills
# with things nobody can fix stops being read, and the real item hiding in it
# goes too.
#
# `gsc` and `ga4` are the collectors' own "no login can see this property"
# source. Under a GSC- or GA4- prefix they already route to the client; the two
# rows that live under TECH- (sitemap submitted, index coverage) did not, and
# landed back on the fix list by the same route. The SOURCE is the fact here,
# not the prefix - that is the rule this function was written for.
CLIENT_DESPITE_REGISTRY = {"needs_gsc_grant", "needs_ga4_grant", "gsc", "ga4"}


def _owner_map() -> dict:
    """
    Which subsystem owed each checkpoint an answer.

    `blocked_on` says WHOSE problem an empty row is. That was enough while the
    answer could be "a person" — a name is a next step. Now that the answer is
    always "ours", it stopped being one: a panel that says "6 checks: Not run."
    tells whoever reads it nothing they can act on, and "Not run." was
    literally the string, because a checkpoint with no finding has no evidence
    to quote. Naming the subsystem turns it back into a next step: the
    backlink provider missed, or no LLM key is set, or the browser phase never
    started. Three different fixes that looked identical.
    """
    m = {}

    def tag(mod, attr, name):
        try:
            src = getattr(__import__(mod, fromlist=[attr]), attr)
        except Exception:  # noqa: BLE001
            return
        for cid in src:
            m.setdefault(cid, name)

    # Most specific first — a checkpoint claimed by two producers is owed by
    # the one that would actually have written the row.
    tag("engine.consent.checks", "CONS_IDS", "the consent and privacy scan")
    tag("engine.aivis.geo_checks", "GEO_IDS", "the AI visibility panel")
    tag("engine.judgment", "CHECKPOINT_IDS", "the judgment layer")
    tag("engine.collectors.dataforseo", "LIGHTHOUSE_IDS", "Lighthouse")
    tag("engine.collectors.analytics", "GSC_EXTRA_IDS", "Search Console")
    tag("engine.checks", "REGISTRY", "the crawl checks")
    return m


_OWNER_CACHE: dict | None = None


def owner(cid: str) -> str:
    """Human name of the subsystem that owed this checkpoint, or ''."""
    global _OWNER_CACHE
    if _OWNER_CACHE is None:
        _OWNER_CACHE = _owner_map()
    if cid.startswith("OFF-"):
        return "the backlink provider"
    return _OWNER_CACHE.get(cid, "")


# Phases the operator TICKS ON. Off is a choice, not a defect.
#
# Both cost real money per run — the consent scan drives a browser, the AI
# panel pays several platforms per question — so both are opt-in, and most
# runs leave them off on purpose.
#
# The panel did not know that. With both boxes unticked, nine consent rows and
# six GEO rows produced no findings, fell through to the vendor bucket, and got
# printed under "Ours to fix — a credential we have not set, or a call we have
# not written" as fifteen defects. Nothing was broken. Nobody asked for them.
#
# This is the analyst-list mistake wearing a different hat: a list that fills
# up with things needing no action is a list people stop reading, and the one
# genuine failure hiding among the fifteen goes with it.
# EVERY BOX ON THE FORM, NOT JUST THE TWO OPT-IN ONES.
#
# Only consent and AI visibility were listed, so unticking "Read and judge the
# pages" produced forty-four rows filed under "a credential we have not set,
# or a call we have not written" - and unticking the collectors added another
# thirty-one. Nothing was broken and nothing was missing: the operator had
# those answers from an earlier run and deliberately did not pay for them
# again. A panel that reports a deliberate choice as seventy-six defects is
# the same failure this list was created to fix, one build later.
OPTIONAL_PHASES = (
    ("run_consent", "engine.consent.checks", "CONS_IDS",
     "Consent &amp; privacy", "tick 'Consent &amp; privacy' on the next run"),
    ("run_aivis", "engine.aivis.geo_checks", "GEO_IDS",
     "Ask the AI assistants", "tick 'Ask the AI assistants' on the next run"),
    ("run_judgment", "engine.judgment", "CHECKPOINT_IDS",
     "Read and judge the pages",
     "tick 'Read and judge the pages' on the next run"),
    ("run_collectors", "engine.collectors", "OFF_IDS",
     "Search Console, Analytics, off-page",
     "tick 'Search Console, Analytics, off-page' on the next run"),
    ("run_collectors", "engine.collectors", "GSC_IDS",
     "Search Console, Analytics, off-page",
     "tick 'Search Console, Analytics, off-page' on the next run"),
    ("run_collectors", "engine.collectors", "GA4_IDS",
     "Search Console, Analytics, off-page",
     "tick 'Search Console, Analytics, off-page' on the next run"),
)


def unrequested(ids, phases_run: dict | None) -> tuple:
    """
    Split ids into (not-requested, everything-else).

    `phases_run` is what the worker recorded about THIS run: {"run_consent":
    bool, ...}. Absent — an older audit, or a report rendered outside a run —
    nothing is claimed and every id stays in the normal buckets, because
    guessing "probably not requested" would hide real failures.
    """
    if not phases_run:
        return [], list(ids)
    off = {}
    for key, mod, attr, name, fix in OPTIONAL_PHASES:
        # ABSENT IS UNKNOWN, NEVER "OFF".
        #
        # A stamp written before a phase was added to this list carries no key
        # for it, and reading that as "not requested" would file every
        # judgment and collector row of every older audit under "nobody asked
        # for these" - which is a lie in the reassuring direction, and hides
        # real failures. Only an explicit False counts.
        if key not in phases_run or phases_run.get(key):
            continue
        try:
            src = getattr(__import__(mod, fromlist=[attr]), attr)
        except Exception:  # noqa: BLE001
            continue
        for cid in src:
            off[cid] = (name, fix)
    skipped = [(cid, off[cid]) for cid in ids if cid in off]
    rest = [cid for cid in ids if cid not in off]
    return skipped, rest


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
    if src in CLIENT_DESPITE_REGISTRY:
        return "client"
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
