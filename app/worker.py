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
    # which is why this is opt-in per run rather than a default.
    art = None
    src = opts.get("reuse_artifact_from")
    if not src and opts.get("reuse_crawl"):
        src = _newest_artifact_for(a["target_url"])
        if not src:
            # Do NOT quietly crawl instead. Someone ticked this box because the
            # site blocks crawlers, or because 150 requests to a client's server
            # is not free. Doing the expensive, rude thing after being told not
            # to is worse than stopping and saying why.
            # Name what was considered. "No stored crawl" reads as a lie when
            # the dashboard is showing three earlier runs of the same client —
            # the reason is that those runs were blocked or their artifact was
            # pruned, and saying so is the difference between a useful error
            # and an argument.
            seen = [r for r in db.list_audits()
                    if (r.get("target_url") or "").rstrip("/").lower()
                    == (a["target_url"] or "").rstrip("/").lower()
                    and r["id"] != audit_id]
            detail = (f"{len(seen)} earlier run(s) of this URL exist, but none "
                      f"has a stored crawl — a run that was blocked, failed or "
                      f"had its artifact pruned has nothing to reuse."
                      if seen else "There are no earlier runs of this URL.")
            msg = ("Asked to reuse a previous crawl, and there is none to "
                   f"reuse. {detail} Nothing was crawled. Untick 'Reuse the "
                   "last crawl' to run a fresh one.")
            print(f"[worker] {audit_id} {msg}", flush=True)
            db.update_audit(audit_id, status="failed", progress=msg, error=msg,
                            completed_at=time.time())
            return
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

    def crawl_progress(msg, done, total):
        # Live progress is what makes "slow" distinguishable from "hung".
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
            progress=lambda d, t: db.update_audit(
                audit_id, progress=f"judgment {d}/{t}",
                heartbeat_at=time.time()))
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
    # The crawl and the findings so far both feed Search Console: the artifact
    # gives URL Inspection something to sample and the link graph to read, and
    # PERF-11 already holds the CrUX field data the Core Web Vitals report is
    # built from. Passing them in is what turns 17 "read it from the UI" rows
    # into measurements.
    gsc = collect_gsc(a["target_url"], opts.get("gsc_refresh_token"),
                      property_url=opts.get("gsc_property"),
                      artifact=art, known=findings)
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
                         industries=opts.get("consent_industries") or None)
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
        }


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
        extras["ai_visibility"] = {
            **{k: agg.get(k) for k in
               ("citation_rate", "mention_rate", "unprompted_citation_rate",
                "client_citations", "top_competitor_domain")},
            "platforms": names, "skipped": skipped,
            "questions": len(queries), "from_audit": True}
        print(f"[worker] {audit_id} AI visibility answered {answered}/"
              f"{len(rows)} GEO rows", flush=True)
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
