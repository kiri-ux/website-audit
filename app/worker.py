"""
Background worker.

This is where a crawl actually runs. It is a separate process from the API for
one non-negotiable reason: a crawl takes minutes to hours, and an HTTP request
cannot. The API enqueues and returns immediately; this consumes the queue.

Run:  python3 -m app.worker
"""
from __future__ import annotations
import json
import os
import signal
import sys
import time
import traceback

from .config import cfg
from . import db, version
from .queue import get_queue
from .artifacts import put_artifact, get_artifact

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.crawler import Crawler
from engine import checks as engine_checks
from engine import scoring as engine_scoring
from engine import aivis
from engine.judgment import run_judgment
from engine import screenshots
from engine.collectors import (collect_gsc, collect_ga4, collect_backlinks,
                               collect_rankings, collect_lighthouse,
                               capture_screenshot, dataforseo)

_stop = False


def _sig(signum, frame):
    global _stop
    _stop = True
    print("[worker] shutdown requested; finishing current job…", flush=True)


class Cancelled(Exception):
    """Someone pressed Stop. Not an error, and not a failure to report."""


def _stop_if_cancelled(audit_id: str):
    """
    Raise if a stop was requested. Called from every progress step.

    COOPERATIVE, BECAUSE THERE IS NO OTHER KIND HERE. The API runs in a
    different container from the worker; it cannot signal this process, and
    killing the worker would take whatever ELSE it is doing down with it. So
    Stop writes a timestamp and the worker checks it - between phases, and
    inside the collector heartbeat, which is the longest anything runs without
    reporting in.

    A cancelled run keeps its findings. Everything answered before the stop is
    already written, and throwing that away would make Stop a destructive
    button - people would stop using it and let bad runs finish instead.
    """
    row = db.get_audit(audit_id) or {}
    if row.get("cancel_at"):
        raise Cancelled()


def run_audit_job(audit_id: str):
    """
    Idempotent: re-running for the same audit_id overwrites its findings and
    scores rather than appending. That is what makes at-least-once delivery safe.
    """
    a = db.get_audit(audit_id)
    if not a:
        raise RuntimeError(f"audit {audit_id} not found")
    opts = json.loads(a.get("options") or "{}")

    def step(status, progress):
        # heartbeat_at is stamped on EVERY step, not just at the start. It is
        # what lets the status page distinguish a long phase from a dead worker:
        # a run whose container was killed mid-judgment stops updating this, and
        # the page can say so instead of auto-refreshing forever against a job
        # nothing is working on.
        #
        # It is also where a cancel lands. The API cannot interrupt this
        # process, so it writes a flag and this reads it - which makes every
        # step a checkpoint, and the worst case one phase of latency.
        _stop_if_cancelled(audit_id)
        db.update_audit(audit_id, status=status, progress=progress,
                        heartbeat_at=time.time())
        print(f"[worker] {audit_id} :: {progress}", flush=True)

    db.update_audit(audit_id, started_at=time.time(), error=None,
                    heartbeat_at=time.time())
    # REUSE A PREVIOUS CRAWL.
    #
    # The crawl is the slow, rude part — 150 pages against someone's server.
    # Re-running an audit because the judgment layer had no API key should not
    # cost the client's site another 150 requests. When `reuse_artifact_from`
    # names an earlier audit whose artifact we still hold, the phases downstream
    # run against those pages instead.
    #
    # The evidence is a snapshot, and the report says as much: pages_crawled and
    # every sitewide count describe the site AS OF that crawl, not today. That is
    # a fair trade for re-scoring, and a bad one for "has the fix landed yet" —
    # so the progress line always states which of the two happened.
    art = None
    src = opts.get("reuse_artifact_from")
    reused_note = ""
    if not src and opts.get("reuse_crawl"):
        src = _newest_artifact_for(a["target_url"])
        if not src:
            # NOW THAT THIS BOX IS TICKED BY DEFAULT, A MISSING CRAWL IS NOT
            # A CONTRADICTION.
            #
            # This used to fail the run outright, and the reasoning was sound
            # while the box was opt-in: someone ticked it because the site
            # blocks crawlers or because 150 requests to a client's server is
            # not free, so crawling anyway was doing the expensive, rude thing
            # after being told not to.
            #
            # Default-on changes what the tick MEANS. It is now "don't crawl
            # again if you already have this site", which on a first run of a
            # new client is a preference with nothing to apply it to - and
            # failing the very first audit of every new client with "there is
            # none to reuse" is the worse of the two mistakes.
            #
            # So: crawl, and say so - loudly, in the progress line and the
            # worker log, because a silent fallback here is exactly the
            # failure this codebase keeps re-learning.
            seen = [r for r in db.list_audits()
                    if (r.get("target_url") or "").rstrip("/").lower()
                    == (a["target_url"] or "").rstrip("/").lower()
                    and r["id"] != audit_id]
            reused_note = (
                "No stored crawl to reuse, so this run crawled the site. "
                + (f"{len(seen)} earlier run(s) of this URL exist, but none "
                   f"has a stored crawl - a run that was blocked, failed or "
                   f"had its artifact pruned has nothing to reuse."
                   if seen else
                   "This is the first run of this URL."))
            print(f"[worker] {audit_id} {reused_note}", flush=True)
            step("crawling", reused_note)
    if src:
        blob = get_artifact(src, "crawl_artifact.json")
        if blob:
            from engine.crawler import artifact_from_json
            art = artifact_from_json(blob.decode())
            # IS THIS CRAWL OLD ENOUGH TO BE MISSING FIELDS WE NOW READ?
            #
            # The page record has grown — the footer, stylesheet URLs,
            # rel=next/prev/amphtml, meta refresh — and a crawl taken before a
            # field existed cannot contain it. Reusing it silently leaves the
            # checks that read those fields empty with nothing to explain why,
            # which turns into "do I need to recrawl?" every single time.
            #
            # Say it here, in the progress line, where the person watching the
            # run will actually see it.
            from engine.crawler import CRAWL_SCHEMA
            have = getattr(art, "crawl_schema", 0) or 0
            stale = have < CRAWL_SCHEMA
            note = ("" if not stale else
                    f" — NOTE: this crawl predates fields the current build "
                    f"reads (schema {have} of {CRAWL_SCHEMA}), so the footer, "
                    f"pagination, AMP, meta-refresh and asset checks will be "
                    f"unanswered. Re-crawl to fill them.")
            step("checking", f"reusing the crawl from {src} "
                             f"({len(art.pages)} pages) — the site was not "
                             f"re-crawled{note}")
            print(f"[worker] {audit_id} reusing crawl artifact from {src} "
                  f"({len(art.pages)} pages, schema {have}/{CRAWL_SCHEMA})"
                  + (" STALE SCHEMA" if stale else ""), flush=True)
            if stale:
                opts["_stale_crawl"] = {"have": have, "want": CRAWL_SCHEMA,
                                        "from": src}
        else:
            print(f"[worker] {audit_id} asked to reuse {src} but its artifact "
                  f"is gone — crawling instead", flush=True)

    if art is None:
        art = _crawl(a, opts, audit_id, db, step)
        if art is None:
            return                      # parked for browser capture
    else:
        step("checking", f"{len(art.pages)} pages from the stored crawl; "
                         f"running checkpoints")

    ctx = {"psi_key": cfg.psi_key,
           "skip_psi": bool(opts.get("skip_psi", cfg.skip_psi))}
    findings = engine_checks.run_all(art, ctx)
    return _after_crawl(a, opts, audit_id, art, findings, step)


def _newest_artifact_for(target_url: str) -> str | None:
    """
    Newest audit of this exact URL whose crawl artifact we can still read.

    Runs on the worker because the worker is what shares a filesystem with the
    artifact store in a local-path deployment.
    """
    want = (target_url or "").rstrip("/").lower()
    for row in db.list_audits():
        if (row.get("target_url") or "").rstrip("/").lower() != want:
            continue
        if get_artifact(row["id"], "crawl_artifact.json"):
            return row["id"]
    return None


def _crawl(a, opts, audit_id, db, step):
    """The crawl phase. Returns None when the audit was parked for capture."""
    step("crawling", "crawling site")

    # DECIDE THE TWO SETTINGS NOBODY CAN KNOW IN ADVANCE.
    #
    # "Browser user-agent" and "Render JavaScript" were checkboxes asking the
    # operator to predict something about a site they had not crawled yet, and
    # both are expensive to get wrong in ways that do not announce themselves:
    # the wrong user-agent turns "we were blocked" into "your site is broken",
    # and JS rendering left off on an app produces 118 empty shells scored as
    # 118 pages with no content.
    #
    # One request to the homepage answers both. Ticking either box still forces
    # it on — someone who knows the site beats a probe — but the default is now
    # evidence rather than a guess.
    forced_ua = bool(opts.get("user_agent"))
    forced_js = bool(opts.get("render_js"))
    if not (forced_ua and forced_js):
        try:
            from engine.preflight import decide as _pre
            pf = _pre(a["target_url"])
        except Exception as exc:  # noqa: BLE001
            pf = {"checked": False, "error": f"{type(exc).__name__}: {exc}",
                  "why": [], "user_agent": None, "render_js": False}
        if pf.get("checked"):
            if pf.get("user_agent") and not forced_ua:
                opts["user_agent"] = pf["user_agent"]
            if pf.get("render_js") and not forced_js:
                opts["render_js"] = True
            for line in pf.get("why") or []:
                # ON THE RECORD, NOT IN A LOG. A run that quietly switched to a
                # browser user-agent and a run where someone ticked the box are
                # different facts about the client's site.
                print(f"[worker] {audit_id} preflight: {line}", flush=True)
            if pf.get("why"):
                opts.setdefault("_preflight", []).extend(pf["why"])
                step("crawling", "crawling site — " + pf["why"][0])
        elif pf.get("error"):
            print(f"[worker] {audit_id} preflight could not run "
                  f"({pf['error']}); crawling with the defaults", flush=True)

    def crawl_progress(msg, done, total):
        # Live progress is what makes "slow" distinguishable from "hung".
        #
        # And it is the only place a stop can land during the longest phase in
        # the run. 150 pages at a polite delay is minutes; checking only
        # between phases would mean pressing Stop and watching the crawl
        # continue to the end.
        _stop_if_cancelled(audit_id)
        db.update_audit(audit_id, progress=f"crawling — {msg}")

    cr = Crawler(
        a["target_url"],
        max_pages=int(opts.get("max_pages", cfg.max_pages)),
        max_depth=int(opts.get("max_depth", cfg.max_depth)),
        delay=float(opts.get("delay", cfg.crawl_delay)),
        render_js=bool(opts.get("render_js", cfg.render_js)),
        user_agent=opts.get("user_agent") or cfg.user_agent,
        max_seconds=int(opts.get("max_seconds", cfg.crawl_max_seconds)),
        progress=crawl_progress,
        verbose=False,
    )
    art = cr.crawl()
    if art.truncated:
        print(f"[worker] {audit_id} CRAWL TRUNCATED: {art.truncated}", flush=True)
    if getattr(art, "link_check_truncated", None):
        print(f"[worker] {audit_id} link sample short: "
              f"{art.link_check_truncated}", flush=True)
    q = art.quality
    if q.degenerate:
        # Do not silently produce a report full of false findings. Park the audit
        # for browser capture instead — a blocked crawl is a handoff, not a result.
        print(f"[worker] {audit_id} CRAWL DEGENERATE: {q.reason} | {q.likely_cause} "
              f"| signals={q.signals}", flush=True)
        db.update_audit(
            audit_id, status="needs_capture",
            progress=f"server crawl blocked ({q.likely_cause}) — "
                     f"run the Chrome extension against this site",
            crawl_blocked=1,
            crawl_note=f"{q.likely_cause} · " + "; ".join(q.signals),
            completed_at=time.time())
        print(f"[worker] {audit_id} parked for browser capture", flush=True)
        return None
    step("checking", f"crawled {len(art.pages)} pages; running checkpoints")
    return art


def _after_crawl(a, opts, audit_id, art, findings, step):
    """Everything downstream of the pages: judgment, collectors, score, save."""
    # ---- Phase 3: judgment layer (E-E-A-T + GEO assessment) ----
    if not opts.get("skip_judgment"):
        step("checking", "assessing E-E-A-T and GEO checkpoints")
        j = run_judgment(
            art, business_model=a.get("vertical"), client=a.get("client_name"),
            progress=lambda d, t: (_stop_if_cancelled(audit_id),
                                   db.update_audit(
                                       audit_id, progress=f"judgment {d}/{t}",
                                       heartbeat_at=time.time()))[-1])
        findings.update(j)
        # Same reasoning as the DataForSEO line below: when the LLM key is
        # missing every row degrades to a tidy "Need Access" and the report
        # still renders, so the failure is invisible unless we say it. This is
        # what makes E-E-A-T and AI Search show as Not Assessed — those two
        # sections cannot clear the coverage threshold without these rows.
        answered = sum(1 for f in j.values() if f.get("status") != "Need Access")
        if answered:
            print(f"[worker] {audit_id} judgment layer answered {answered}/"
                  f"{len(j)} E-E-A-T and AI Search rows", flush=True)
        else:
            print(f"[worker] {audit_id} judgment layer produced NOTHING — "
                  f"ANTHROPIC_API_KEY is not set ON THE WORKER. E-E-A-T and AI "
                  f"Search will report Not Assessed.", flush=True)

    # ---- external collectors (client credentials / vendor keys) ----
    if opts.get("skip_collectors"):
        print(f"[worker] {audit_id} collectors skipped by request — Search "
              f"Console, Analytics, backlinks and rankings will be blank",
              flush=True)
        return _score_and_save(a, opts, audit_id, art, findings,
                               {"context": _context_of(art)}, step)
    step("checking", "collecting Search Console, Analytics and backlink data")
    # HEARTBEAT THROUGH THE SLOW PART.
    #
    # This phase stamped one progress line before it and the next one after
    # all of it. URL Inspection is up to twenty-five calls at a 45-second
    # timeout, so a Search Console pass working perfectly could run for
    # fifteen minutes in silence — and the status page, which decides a run is
    # dead when the heartbeat is ten minutes old, told the operator their
    # worker had been recycled. On a run that was fine.
    #
    # A stall detector is only as good as the heartbeat it watches. Every slow
    # loop inside a phase has to touch it, or the detector reports the phase
    # rather than the fault.
    def _beat(done, total):
        _stop_if_cancelled(audit_id)
        db.update_audit(audit_id,
                        progress=f"Search Console: inspecting URL "
                                 f"{done + 1} of {total}",
                        heartbeat_at=time.time())

    # The crawl and the findings so far both feed Search Console: the artifact
    # gives URL Inspection something to sample and the link graph to read, and
    # PERF-11 already holds the CrUX field data the Core Web Vitals report is
    # built from. Passing them in is what turns 17 "read it from the UI" rows
    # into measurements.
    gsc = collect_gsc(a["target_url"], opts.get("gsc_refresh_token"),
                      property_url=opts.get("gsc_property"),
                      artifact=art, known=findings, progress=_beat)
    step("checking", "collecting Analytics data")
    ga4 = collect_ga4(opts.get("ga4_property_id"),
                      opts.get("ga4_refresh_token"),
                      site_url=a["target_url"])
    findings.update(gsc)
    findings.update(ga4)
    # Say which of the three states we are in, because they are easy to confuse
    # and only one of them is the client's to fix.
    for name, rows in (("Search Console", gsc), ("GA4", ga4)):
        got = sum(1 for f in rows.values() if f.get("status") != "Need Access")
        if got:
            print(f"[worker] {audit_id} {name} answered {got}/{len(rows)} rows",
                  flush=True)
        else:
            why = next(iter(rows.values()), {}).get("evidence", "")
            print(f"[worker] {audit_id} {name} EMPTY — {why}", flush=True)
    step("checking", "collecting the backlink profile")
    findings.update(collect_backlinks(art.host))

    # Business context: what the crawl learned about the CLIENT rather than
    # about their SEO. Free — it re-reads the artifact we already have — and it
    # is what lets the report open with a sentence that could only have been
    # written about this company.
    from engine.context import extract as extract_context
    bc = extract_context(art)
    extras = {"context": {**bc.to_dict(), "describe": bc.describe()}}
    if opts.get("_stale_crawl"):
        extras["stale_crawl"] = opts["_stale_crawl"]
    # What the preflight decided, and why. A crawl that needed a browser
    # user-agent is a FACT ABOUT THE CLIENT'S SITE, not a setting we happened
    # to use — it belongs on the record next to the findings it explains.
    if opts.get("_preflight"):
        extras["preflight"] = opts["_preflight"]

    if dataforseo.configured() and not opts.get("skip_dataforseo"):
        # Lighthouse via DataForSEO FILLS GAPS ONLY. Where PageSpeed Insights
        # answered we keep it, because PSI carries CrUX field data and this is a
        # lab run. Where PSI was rate-limited or skipped — the 429s on Render's
        # shared egress — these rows are the difference between a measurement
        # and a blank.
        step("checking", "running Lighthouse via DataForSEO")
        lh = collect_lighthouse(a["target_url"])
        filled = 0
        for cid, f in lh.items():
            cur = findings.get(cid)
            if f.get("status") == "Need Access":
                continue
            if cur is None or cur.get("status") == "Need Access" \
                    or (cur.get("confidence") or 0) == 0:
                findings[cid] = f
                filled += 1
        if filled:
            print(f"[worker] {audit_id} DataForSEO Lighthouse filled {filled} "
                  f"rows PSI could not answer", flush=True)

        step("checking", "collecting keyword rankings")
        rk = collect_rankings(art.host, opts.get("location_name"))
        extras["rankings"] = rk
        # GEO-24 and GEO-25 ride along. They are Google SERP features rather
        # than AI platforms, so the visibility monitor rightly declines them —
        # and the keyword call already carries the answer.
        if rk.get("geo"):
            findings.update(rk["geo"])
        # Logged loudly because this is the one collector whose success is
        # invisible from the outside: a failed call degrades to an empty table
        # and the report still renders cleanly. Without this line the only way
        # to tell a live API from a silent no-op is to read the PDF.
        if rk.get("available"):
            print(f"[worker] {audit_id} DataForSEO rankings OK — "
                  f"{rk.get('total', 0)} keywords, {rk.get('top10', 0)} in the "
                  f"top 10, location={rk.get('location')}", flush=True)
        else:
            print(f"[worker] {audit_id} DataForSEO rankings UNAVAILABLE — "
                  f"{rk.get('reason')}", flush=True)
        shot = capture_screenshot(a["target_url"])
        if shot:
            extras["screenshot"] = shot
    else:
        # Silence here used to be indistinguishable from success. Credentials
        # set on the API service instead of the worker is the easy mistake —
        # the dashboard looks configured and the collector never runs.
        why = ("skip_dataforseo was set on this audit"
               if dataforseo.configured()
               else "DFS_LOGIN / DFS_PASSWORD are not set ON THE WORKER")
        print(f"[worker] {audit_id} DataForSEO SKIPPED — {why}", flush=True)

    return _score_and_save(a, opts, audit_id, art, findings, extras, step)


def _phase_unanswered(ids, why, rec="", src="phase_unavailable"):
    """
    Rows for a phase that could not run.

    A PHASE THAT BAILS MUST STILL WRITE ITS ROWS.

    Both optional phases used to `return` on their unhappy paths — a failed
    import, no platform keys — leaving their checkpoints with no finding at
    all. Every other part of this codebase treats an unmeasured thing as
    something that must SAY it is unmeasured; these two made theirs vanish,
    and a checkpoint with no finding has no evidence to quote, so the internal
    panel could only fall back to "the consent and privacy scan produced no
    result for this run". True, and it names no cause, because the cause was
    printed to a log nobody was reading and then dropped.

    Writing the rows costs nothing and turns silence into a diagnosis.
    """
    return {cid: {"status": "Need Access", "value": {}, "evidence": why,
                  "affected_pages": [], "severity": "Low",
                  "recommendation": rec, "confidence": 0.0, "source": src}
            for cid in ids}


def _consent(a, audit_id, findings, extras, opts, step):
    """
    One consent scan of the homepage, turned into nine checkpoints.

    ONE page, not the whole crawl. A consent banner and its pre-consent network
    traffic are a property of the site's tag setup, not of any particular URL,
    and loading 150 pages in a browser to click Accept 150 times would cost
    twenty minutes to learn the same thing.

    The scanner is vendored rather than reimplemented, so this function is
    almost entirely error handling — which is the point. A consent scan that
    fails must leave nine rows honestly unanswered and the audit otherwise
    intact.
    """
    try:
        from engine.consent import scan_site
        from engine.consent.checks import findings_from_scan, CONS_IDS
    except Exception as exc:  # noqa: BLE001
        print(f"[worker] {audit_id} consent scanner unavailable: "
              f"{type(exc).__name__}: {exc}", flush=True)
        try:
            from engine.consent.checks import CONS_IDS as _ids
        except Exception:  # noqa: BLE001
            _ids = tuple(f"CONS-{i:02d}" for i in range(1, 10))
        findings.update(_phase_unanswered(
            _ids,
            f"The consent scanner could not be loaded on this worker "
            f"({type(exc).__name__}: {exc}).",
            "This is a deployment problem, not a client one — the scanner "
            "needs Playwright and Chromium in the worker image."))
        return
    step("checking", "checking consent, cookie banner and pre-consent tags")
    try:
        scan = scan_site(a["target_url"],
                         prefer_full=not opts.get("skip_consent_browser"),
                         states=opts.get("consent_states") or None,
                         industries=opts.get("consent_industries") or None,
                         products=opts.get("consent_products") or None)
        # CONVERSION PAGES TOO.
        #
        # The scan looked at the homepage and said so. But a thank-you page is
        # where the conversion pixels actually fire, which makes it the page
        # most likely to carry an ungated one — and the page nobody looked at.
        # Site-level checks run once, on the homepage, exactly as the
        # standalone tool does it; the extra pages contribute their pixels.
        extra = []
        # KEEP EACH PAGE'S OWN RESULT, not only the merge.
        #
        # The merge below is right for the checkpoints — a pixel firing
        # pre-consent on ANY page is a pre-consent fire, and CONS-04 should
        # say so once. It is wrong for a dashboard: once three pages are
        # concatenated into one list, "which page was this on" is gone, and
        # that is the first question anyone asks about an ungated pixel.
        pages = []
        if isinstance(scan, dict):
            pages.append({"url": a["target_url"], "role": "homepage",
                          "scan": scan})
        for url in (opts.get("conversion_urls") or []):
            try:
                one = scan_site(
                    url, prefer_full=not opts.get("skip_consent_browser"),
                    site_checks=False,
                    products=opts.get("consent_products") or None)
                extra.append(one)
                pages.append({"url": url, "role": "conversion", "scan": one})
            except Exception as exc:  # noqa: BLE001
                print(f"[worker] {audit_id} conversion scan failed for {url}: "
                      f"{type(exc).__name__}: {exc}", flush=True)
                # A page that could not be scanned is part of the record too.
                # Dropping it means the dashboard lists two pages for a run
                # that was asked to cover three, and says nothing about the
                # third.
                pages.append({"url": url, "role": "conversion",
                              "error": f"{type(exc).__name__}: {exc}"})
        if extra and isinstance(scan, dict):
            # Merge the pixel evidence, keep the homepage's verdict. A pixel
            # firing pre-consent on ANY scanned page is a pre-consent fire.
            for other in extra:
                for key in ("pre_consent", "post_reject", "gpc_fires",
                            "post_consent"):
                    if other.get(key):
                        scan[key] = (scan.get(key) or []) + other[key]
            scan["pages_scanned"] = 1 + len(extra)
    except Cancelled:
        raise                       # a Stop is not a phase failure
    except Exception as exc:  # noqa: BLE001
        print(f"[worker] {audit_id} consent scan errored: "
              f"{type(exc).__name__}: {exc}", flush=True)
        scan = None
    rows = findings_from_scan(scan)
    findings.update(rows)
    if scan:
        mode = scan.get("mode")
        answered = sum(1 for f in rows.values() if f.get("status") != "Need Access")
        # A basic-mode scan answers four of nine and cannot answer the rest.
        # Say which happened, because "4/9" alone reads as a partial failure
        # when it is the correct and complete result for that mode.
        print(f"[worker] {audit_id} consent scan ({mode}) answered "
              f"{answered}/{len(rows)} rows"
              + ("; browser unavailable, so banner, Consent Mode and "
                 "pre-consent could not be tested" if mode != "full" else ""),
              flush=True)
        extras["consent"] = {
            "mode": mode,
            "cmps": [c.get("name") for c in (scan.get("cmps") or [])],
            "verdict": scan.get("verdict"),
            "verdict_detail": scan.get("verdict_detail"),
            "scanned_at": scan.get("scanned_at"),
            "pages_scanned": scan.get("pages_scanned") or 1,
            "has_detail": True,
        }
        # THE SCAN ITSELF IS THE PRODUCT; NINE CHECKPOINTS ARE A SUMMARY OF IT.
        #
        # Everything the scanner learned — every CMP signature and the evidence
        # that matched it, container ids, Consent Mode defaults, each tracker
        # with its vendor and URL and when it fired, the per-state statute
        # results, the product pixels — was being thrown away the moment nine
        # findings were derived from it. That is most of what the standalone
        # tool shows on screen, computed and discarded on every run.
        #
        # It goes to the artifact store, which is the one place the API and the
        # worker demonstrably share.
        try:
            put_artifact(audit_id, "consent_scan.json", json.dumps(
                {"scan": scan, "pages": pages,
                 "requested": {
                     "states": opts.get("consent_states") or [],
                     "industries": opts.get("consent_industries") or [],
                     "products": opts.get("consent_products") or [],
                     "conversion_urls": opts.get("conversion_urls") or [],
                     "implementation": opts.get("implementation") or ""}},
                default=str).encode())
        except Exception as exc:  # noqa: BLE001
            # Never fail the audit over the detail record. But say so — a
            # dashboard that is quietly empty is worse than one that explains
            # why it is empty.
            extras["consent"]["has_detail"] = False
            extras["consent"]["detail_error"] = f"{type(exc).__name__}: {exc}"
            print(f"[worker] {audit_id} consent detail not stored: "
                  f"{type(exc).__name__}: {exc}", flush=True)


def _ai_visibility(a, audit_id, findings, extras, step):
    """
    Ask the assistants, in line, and record what they said.

    Failures here must never take the audit down: the eight rows degrade to
    unanswered exactly as they did before, which is the state this whole phase
    is an improvement on.
    """
    try:
        from engine.aivis.providers import active_providers
        providers, skipped = active_providers()
        if not providers:
            print(f"[worker] {audit_id} AI visibility skipped — no platform "
                  f"keys configured ({', '.join(skipped) or 'none found'})",
                  flush=True)
            from engine.aivis.geo_checks import GEO_IDS
            findings.update(_phase_unanswered(
                GEO_IDS,
                "No AI platform keys are set on this worker, so no assistant "
                "was asked.",
                "Set one or more of OPENAI_API_KEY, ANTHROPIC_API_KEY, "
                "PERPLEXITY_API_KEY or GEMINI_API_KEY on vici-audit-worker. "
                "Missing: " + (", ".join(skipped) or "none reported") + "."))
            return
        from engine.aivis.panel import profile_from_audit, build_panel
        from engine.aivis.monitor import run_panel
        from engine.aivis.geo_checks import findings_from_run

        ctx = (extras.get("context") or {})
        profile = profile_from_audit(a["client_name"], a["target_url"], ctx,
                                     a.get("vertical"))
        queries = build_panel(profile)
        names = ", ".join(sorted(p.name for p in providers))
        step("checking", f"asking {len(providers)} AI assistants about "
                         f"{profile.brand}")
        print(f"[worker] {audit_id} AI visibility: {len(queries)} questions "
              f"across {names}"
              + (f" (skipped: {', '.join(skipped)})" if skipped else ""),
              flush=True)

        # One repeat, not three. Three is right for a trend line, where
        # run-to-run variance has to be averaged out; for a first reading it
        # triples the spend to sharpen a number the report rounds anyway.
        run = run_panel(profile, queries=queries, providers=providers,
                        skipped=skipped,
                        repeats=int(os.getenv("AIVIS_AUDIT_REPEATS", "1")),
                        progress=lambda d, t: db.update_audit(
                            audit_id, progress=f"AI visibility {d}/{t}",
                            heartbeat_at=time.time()))
        if run.get("error"):
            print(f"[worker] {audit_id} AI visibility failed: {run['error']}",
                  flush=True)
            return
        agg = run.get("aggregate") or {}
        rows = findings_from_run(agg, profile)
        findings.update(rows)
        answered = sum(1 for f in rows.values() if f.get("status") != "Need Access")
        # THE ANSWERS THEMSELVES, NOT JUST THE RATES.
        #
        # Every question, every answer and every citation was computed and
        # thrown away, leaving a section that could only report percentages —
        # and a percentage does not tell anyone what to write next. Two
        # examples do: one question where the assistants cited the client, and
        # one where they cited somebody else instead.
        #
        # `share_of_voice` was worse than unused: the PDF already reads it and
        # renders a whole "who gets cited in your category" table from it, and
        # nothing ever put it here, so that table has never appeared.
        qtext = {q.id: q.text for q in queries}
        wins, losses = [], []
        for r in (run.get("results") or []):
            if not r.get("ok"):
                continue
            q = qtext.get(r.get("query_id"))
            if not q:
                continue
            if r.get("cited") and len(wins) < 3:
                wins.append({"question": q, "platform": r.get("platform")})
            elif not r.get("cited") and len(losses) < 3:
                others = [d for d in (r.get("other_domains") or [])][:3]
                losses.append({"question": q, "platform": r.get("platform"),
                               "cited_instead": others})
            if len(wins) >= 3 and len(losses) >= 3:
                break
        # THE WHOLE RUN, ON DISK, BEFORE WE DERIVE ANYTHING FROM IT.
        #
        # Every question, answer and citation existed in memory and was thrown
        # away once the rates were computed - so when the report needed
        # examples, the only way to get them was to ask every assistant again
        # and pay for it twice. The derived block below is still what the PDF
        # reads; this is the raw material behind it, and it is what lets a
        # future renderer show more without a re-run.
        try:
            put_artifact(audit_id, "aivis_run.json", json.dumps(
                {"aggregate": agg, "results": run.get("results") or [],
                 "questions": {q.id: q.text for q in queries}},
                default=str).encode())
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] {audit_id} AI run not stored: "
                  f"{type(exc).__name__}: {exc}", flush=True)
        extras["ai_visibility"] = {
            **{k: agg.get(k) for k in
               ("citation_rate", "mention_rate", "unprompted_citation_rate",
                "client_citations", "top_competitor_domain")},
            "share_of_voice": (agg.get("share_of_voice") or [])[:8],
            "cited_examples": wins, "missed_examples": losses,
            "platforms": names, "skipped": skipped,
            "questions": len(queries), "from_audit": True}
        print(f"[worker] {audit_id} AI visibility answered {answered}/"
              f"{len(rows)} GEO rows", flush=True)
    except Cancelled:
        # A BROAD HANDLER MUST NOT EAT A STOP.
        #
        # Every phase in here swallows its own failures on purpose - one dead
        # collector should not take the audit down. Cancelled is an Exception
        # too, so without this the run would log "AI visibility errored:
        # Cancelled" and carry straight on to the next phase, and Stop would
        # look like it did nothing.
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"[worker] {audit_id} AI visibility errored: "
              f"{type(exc).__name__}: {exc}", flush=True)


def _context_of(art):
    from engine.context import extract as extract_context
    bc = extract_context(art)
    return {**bc.to_dict(), "describe": bc.describe()}


def _score_and_save(a, opts, audit_id, art, findings, extras, step):
    """Screenshots, scoring, persistence. Reached by every path, including the
    one that skips collectors entirely."""
    # An EARLY save, so a crash in the optional phases below still leaves a
    # readable audit rather than nothing. It is not the last word — see the
    # second save after the phases have run.
    db.save_findings(audit_id, findings)

    # ---- evidence screenshots ------------------------------------------
    # Last, and strictly optional: by this point the audit is already complete,
    # so a browser that hangs costs us a picture rather than the report. Skipped
    # entirely when the crawl was blocked — we would be photographing a
    # challenge page and captioning it as the client's site.
    if (not art.quality.degenerate and not opts.get("skip_screenshots")
            and screenshots.available()):
        step("scoring", "capturing evidence screenshots")
        shots = []
        # THE HOMEPAGE, UNMARKED, FOR THE FRONT OF THE REPORT.
        #
        # Not evidence - the thing the document is about. It goes near the top
        # with rounded corners and a shadow, and it is what makes the rest read
        # as being about a real site. Captured with no selector so nothing is
        # outlined on it.
        try:
            hero = screenshots.capture(art.start_url)
            if hero:
                put_artifact(audit_id, "homepage.png", hero)
                shots.append({"checkpoint": "", "name": "homepage.png",
                              "url": art.start_url, "caption": "",
                              "boxed": False, "kind": "homepage"})
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] {audit_id} homepage shot failed: "
                  f"{type(exc).__name__}: {exc}", flush=True)
        cat_now = db.catalog()
        for cid, url, sel, caption in screenshots.pick_targets(
                findings, cat_now, art.start_url, limit=3):
            png = screenshots.capture(url, sel)
            if not png:
                continue
            name = f"evidence_{cid.replace('/', '_')}.png"
            put_artifact(audit_id, name, png)
            shots.append({"checkpoint": cid, "name": name, "url": url,
                          "caption": caption, "boxed": bool(sel)})
        if shots:
            extras["screenshots"] = shots
            print(f"[worker] {audit_id} captured {len(shots)} evidence shots",
                  flush=True)

    # ---- consent and privacy ------------------------------------------
    if opts.get("run_consent"):
        _consent(a, audit_id, findings, extras, opts, step)

    # ---- AI visibility, as a phase of the audit rather than a separate errand
    #
    # GEO-23..30 were the last eight rows on the "needs a person" list, and the
    # person's job was building a monitor profile by hand from facts the crawl
    # had already extracted. That is data entry, not judgment.
    #
    # The monitor is still a standalone product — a monthly time series with a
    # frozen question panel, which is what a retainer is sold on. What changes
    # here is only that the FIRST run can start itself, so the audit can say
    # something about AI visibility instead of promising to later.
    #
    # Opt-in, because it is the one phase that spends money per question across
    # several platforms.
    if opts.get("run_aivis"):
        _ai_visibility(a, audit_id, findings, extras, step)

    # WHICH OPTIONAL PHASES WERE ASKED FOR.
    #
    # Recorded because the report cannot tell the difference otherwise. Nine
    # consent rows with no findings look identical whether the scan crashed or
    # nobody ticked the box, and the panel was printing both as "Ours to fix".
    # One is a bug; the other is a run that did exactly what was asked.
    extras["phases_run"] = {"run_consent": bool(opts.get("run_consent")),
                            "run_aivis": bool(opts.get("run_aivis"))}

    # SAVE AGAIN. THE FIRST SAVE HAPPENED BEFORE THE PHASES RAN.
    #
    # This is the bug that made nine consent rows and six GEO rows vanish from
    # every audit since the consent phase shipped, and it hid behind a set of
    # symptoms that all pointed elsewhere:
    #
    #   * `extras["consent"]` and `extras["ai_visibility"]` were populated, so
    #     the phases had plainly RUN.
    #   * Coverage read 322/322, because scoring runs on this in-memory dict
    #     and could see all fifteen.
    #   * The findings table had none of them, because the only write happened
    #     forty lines earlier.
    #   * So the panel fell to "produced no result for this run" — the message
    #     for a checkpoint with no row at all — and every reading of that
    #     pointed at the scanner, the worker's keys, or the deploy. The scanner
    #     was fine the whole time. The rows were written to a dict that was
    #     never flushed again.
    #
    # `save_findings` deletes and rewrites the audit's rows, so a second call
    # is idempotent and costs one statement. The early save stays, because a
    # crash inside an optional phase should still leave a readable audit.
    db.save_findings(audit_id, findings)

    step("scoring", f"{len(findings)} checkpoints evaluated; scoring")
    cat = db.catalog()
    sc = engine_scoring.score(findings, cat, a.get("vertical"))
    db.save_scores(audit_id, sc)

    # Artifact goes to object storage, never the DB — it is large and only
    # needed to re-run checks without re-crawling.
    put_artifact(audit_id, "crawl_artifact.json", art.to_json().encode())

    db.update_audit(
        audit_id, status="ready",
        progress=("complete — CRAWL BLOCKED, content checks not assessed"
                  if art.quality.degenerate else "complete"),
        crawl_blocked=1 if art.quality.degenerate else 0,
        crawl_note=(f"{art.quality.likely_cause} · " + "; ".join(art.quality.signals)
                    if art.quality.degenerate else None),
        crawl_truncated=art.truncated,
        extras=json.dumps(extras),
        overall_score=sc["overall"]["score"], overall_rating=sc["overall"]["rating"],
        pages_crawled=len(art.pages), coverage=f"{len(findings)}/{len(cat)}",
        completed_at=time.time())
    print(f"[worker] {audit_id} DONE score={sc['overall']['score']} "
          f"coverage={len(findings)}/{len(cat)}", flush=True)


def run_ai_monitor_job(run_id: str):
    """
    AI visibility monitor run.

    Idempotent like the audit job: results for this run_id are deleted and
    rewritten rather than appended.

    Note it reuses the profile's FROZEN panel rather than regenerating. The
    product is a time series; regenerating the questions between runs would make
    consecutive points incomparable while still looking like a trend.
    """
    run = db.get_ai_run(run_id)
    if not run:
        raise RuntimeError(f"ai_run {run_id} not found")
    prof_row = db.get_ai_profile(run["profile_id"])
    if not prof_row:
        raise RuntimeError(f"ai_profile {run['profile_id']} not found")

    pdict = json.loads(prof_row["profile"])
    profile = aivis.ClientProfile(**pdict)
    panel_raw = json.loads(prof_row["panel"] or "[]")
    queries = [aivis.Query(**q) for q in panel_raw] or aivis.build_panel(profile)

    def step(status, progress):
        db.update_ai_run(run_id, status=status, progress=progress)
        print(f"[worker] ai_run {run_id} :: {progress}", flush=True)

    step("running", f"querying platforms ({len(queries)} queries x "
                    f"{run['repeats']} repeats)")

    corpus_path = os.getenv("AI_REPLAY_CORPUS")
    if corpus_path and os.path.exists(corpus_path):
        # Deterministic mode — demos and CI, no API keys, no spend.
        with open(corpus_path) as f:
            corpus = json.load(f)
        out = aivis.run_replay(profile, corpus, queries=queries,
                               repeats=run["repeats"] or 1)
    else:
        out = aivis.run_panel(profile, queries=queries,
                              repeats=run["repeats"] or 3,
                              progress=lambda d, t: db.update_ai_run(
                                  run_id, progress=f"{d}/{t} answers collected"))

    agg = out.get("aggregate") or {}
    if out.get("error"):
        db.update_ai_run(run_id, status="failed", progress="failed",
                         error=out["error"],
                         skipped=json.dumps(out.get("skipped_platforms", [])),
                         completed_at=time.time())
        raise RuntimeError(out["error"])

    step("scoring", "aggregating share of voice")
    db.save_ai_results(run_id, out["results"], agg.get("share_of_voice", []))

    summ = aivis.summary_row(agg, profile)
    db.update_ai_run(
        run_id, status="ready", progress="complete",
        platforms=json.dumps(sorted(agg.get("by_platform", {}).keys())),
        skipped=json.dumps(agg.get("skipped_platforms", [])),
        mention_rate=agg.get("mention_rate"),
        citation_rate=agg.get("citation_rate"),
        unprompted_citation_rate=agg.get("unprompted_citation_rate"),
        client_citations=summ["client_citations"],
        top_competitor_domain=summ["top_competitor_domain"],
        citation_gap=summ["citation_gap"],
        answers_ok=agg.get("answers_ok"), answers_error=agg.get("answers_error"),
        headline=out.get("headline"), completed_at=time.time())

    # Feed GEO-23..30 back onto the linked audit, if there is one.
    if run.get("audit_id"):
        geo = aivis.findings_from_run(agg, profile)
        existing = db.get_findings(run["audit_id"])
        existing.update(geo)
        db.save_findings(run["audit_id"], existing)
        cat = db.catalog()
        a = db.get_audit(run["audit_id"])
        sc = engine_scoring.score(existing, cat, (a or {}).get("vertical"))
        db.save_scores(run["audit_id"], sc)
        db.update_audit(run["audit_id"],
                        overall_score=sc["overall"]["score"],
                        overall_rating=sc["overall"]["rating"],
                        coverage=f"{len(existing)}/{len(cat)}")
        print(f"[worker] ai_run {run_id} merged {len(geo)} GEO rows into "
              f"audit {run['audit_id']}", flush=True)

    print(f"[worker] ai_run {run_id} DONE citation_rate={agg.get('citation_rate')}% "
          f"mention_rate={agg.get('mention_rate')}%", flush=True)


HANDLERS = {"audit": run_audit_job, "ai_monitor": run_ai_monitor_job}


# ---------------------------------------------------------------------------
# WHAT THIS WORKER CAN ACTUALLY DO, WRITTEN DOWN WHERE THE FORM CAN READ IT.
#
# Every credential that matters runs HERE, on the worker, and the audit form is
# served by the API — a different container with a different environment. So the
# form could offer "AI visibility" as a checkbox with no way of knowing whether
# a single platform key was set, and the honest answer to "are we set up to run
# this?" was "start a run and find out".
#
# The worker publishes its own capability set on startup instead. The database
# is the one thing both services demonstrably share, which is the same reason
# crawl artifacts live there.
# ---------------------------------------------------------------------------
CAPS_KEY = "_worker"


def _font_caps() -> dict:
    """Registered families, and the files that are missing if any are."""
    try:
        from engine.fonts import register, status, _find, _BODY_FACES, _HEAD_FACES
        register()
        st = status()
        missing = [f for _n, f, _b, _i in (_BODY_FACES + _HEAD_FACES)
                   if not _find(f)]
        return {"body": st.get("family"), "headings": st.get("heading_family"),
                "missing": missing}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _publish_capabilities():
    try:
        from engine.aivis.providers import active_providers
        avail, skipped = active_providers()
        caps = {
            "at": time.time(),
            "build": version.BUILD,
            "service": os.getenv("RENDER_SERVICE_NAME", "local"),
            "ai_platforms": sorted(p.name for p in avail),
            "ai_missing": sorted(skipped),
            "judgment": bool(os.getenv("ANTHROPIC_API_KEY")),
            "dataforseo": dataforseo.configured(),
            "google": bool(os.getenv("GOOGLE_TOKENS")
                           and os.getenv("GOOGLE_CLIENT_ID")
                           and os.getenv("GOOGLE_CLIENT_SECRET")),
            "psi_key": bool(os.getenv("PSI_API_KEY")),
            # WHICH TYPEFACES ACTUALLY REGISTERED, not which files we hoped
            # for. Fonts load on the WORKER, and the only evidence until now
            # was one line in a boot log nobody is watching at the moment it
            # scrolls past — so a font that silently fell back to Roboto
            # looked exactly like a font that was never uploaded.
            "fonts": _font_caps(),
        }
        db.put_blob(CAPS_KEY, "capabilities.json",
                    json.dumps(caps).encode())
        print(f"[worker] capabilities published: "
              f"AI {caps['ai_platforms'] or 'none'} · "
              f"judgment {caps['judgment']} · DataForSEO {caps['dataforseo']} · "
              f"Google {caps['google']}", flush=True)
    except Exception as exc:  # noqa: BLE001
        # A worker that cannot advertise itself must still take jobs.
        print(f"[worker] could not publish capabilities: "
              f"{type(exc).__name__}: {exc}", flush=True)


def _reap_abandoned():
    """
    Fail runs whose worker vanished, so they stop claiming to be in flight.

    THE CASE THIS EXISTS FOR: an audit reached "collecting Search Console,
    Analytics and backlink data", stamped a heartbeat 73 seconds in, and never
    wrote another byte. No error was recorded — and that absence is the
    evidence. Every exception path in this worker writes `error` and sets the
    status to failed, so a run that stops with `error` still null did not
    raise. The process went away underneath it: an out-of-memory kill or the
    instance being recycled.

    Nothing then moved it. The queue had already leased the job, the container
    that held the lease was gone, and the row sat at `checking` indefinitely —
    counting under "in flight" on the dashboard, forever, for a run that no
    process was working on.

    A worker starting up is the right moment to do this: if a run's heartbeat
    is older than the stall window and no worker is on it, the only honest
    status is failed, with a message that says what the silence means.

    NOT REQUEUED. If the cause was memory, an automatic retry loops on the
    same wall at the same point and burns an instance doing it. The rerun
    button is one click and it reuses the stored crawl.
    """
    from .ui import STALE_AFTER_S
    cutoff = time.time() - STALE_AFTER_S
    running = ("queued", "crawling", "checking", "scoring")
    n = 0
    for row in db.list_audits():
        if row.get("status") not in running:
            continue
        hb = row.get("heartbeat_at")
        # No heartbeat at all means a run from before heartbeats existed.
        # Unknown is not dead, and guessing here would fail live work.
        if not hb or float(hb) > cutoff:
            continue
        mins = int((time.time() - float(hb)) // 60)
        # A run somebody asked to stop, whose worker then went away before it
        # could notice, is CANCELLED and not failed. Reporting it as a crash
        # would blame the site for a decision a person made.
        if row.get("cancel_at"):
            db.update_audit(row["id"], status="cancelled", error=None,
                            progress="stopped on request",
                            completed_at=time.time())
            print(f"[worker] closed cancelled audit {row['id']}", flush=True)
            n += 1
            continue
        msg = (f"This run stopped responding {mins} minutes ago, at "
               f"\u201c{row.get('progress') or 'an early step'}\u201d, and "
               f"recorded no error. That combination means it was interrupted "
               f"rather than failed \u2014 a deploy going out mid-scan, or the "
               f"instance being recycled. Nothing was wrong with the site. "
               f"Re-run it; the stored crawl is reused, so the client's "
               f"server is not touched again.")
        db.update_audit(row["id"], status="failed", progress=msg, error=msg,
                        completed_at=time.time())
        print(f"[worker] reaped abandoned audit {row['id']} "
              f"(no heartbeat for {mins}m)", flush=True)
        n += 1
    if n:
        print(f"[worker] {n} abandoned run(s) marked failed on startup",
              flush=True)


def main():
    # Graceful shutdown matters in production: Render sends SIGTERM on deploy,
    # and we want the in-flight crawl to finish rather than be killed mid-job.
    # Signal handlers can only be installed from the main thread, so this is a
    # no-op under app.dev (which runs the worker in a thread).
    import threading
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _sig)
        signal.signal(signal.SIGINT, _sig)
    db.init_db()
    q = get_queue()
    from .config import warn_startup
    warn_startup()
    _publish_capabilities()
    _reap_abandoned()
    print(f"[worker] up · {version.label()} · {cfg.summary()} · waiting for jobs",
          flush=True)

    idle = 0
    while not _stop:
        job = q.lease()
        if not job:
            idle += 1
            if idle % 30 == 0:
                print(f"[worker] idle (queue depth {q.depth()})", flush=True)
            time.sleep(cfg.poll_interval_s)
            continue
        idle = 0
        aid = job["audit_id"]
        jtype = job.get("job_type", "audit")
        try:
            handler = HANDLERS.get(jtype)
            if handler is None:
                raise RuntimeError(f"unknown job_type {jtype!r}")
            handler(aid)
            q.complete(job)
        except Cancelled:
            # A STOP IS NOT A FAILURE, AND MUST NOT BE RETRIED.
            #
            # Falling through to the handler below would mark it failed with a
            # traceback and put it back on the queue twice - so pressing Stop
            # would start the run again, which is the opposite of Stop.
            print(f"[worker] job {job['job_id']} cancelled on request",
                  flush=True)
            db.update_audit(aid, status="cancelled",
                            progress="stopped on request",
                            error=None, completed_at=time.time())
            q.complete(job)
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[worker] job {job['job_id']} FAILED\n{tb}", flush=True)
            # Three strikes, then park it. A permanently broken target should
            # not occupy a worker forever.
            retry = job.get("attempts", 1) < 3
            upd = db.update_audit if jtype == "audit" else db.update_ai_run
            upd(aid, status="queued" if retry else "failed",
                progress="retrying after error" if retry else "failed",
                error=f"{type(e).__name__}: {e}")
            q.fail(job, str(e), retry)
    print("[worker] stopped", flush=True)


if __name__ == "__main__":
    main()
