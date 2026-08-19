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
from .artifacts import put_artifact

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
        db.update_audit(audit_id, status=status, progress=progress)
        print(f"[worker] {audit_id} :: {progress}", flush=True)

    db.update_audit(audit_id, started_at=time.time(), error=None)
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
        return
    else:
        step("checking", f"crawled {len(art.pages)} pages; running checkpoints")

    ctx = {"psi_key": cfg.psi_key,
           "skip_psi": bool(opts.get("skip_psi", cfg.skip_psi))}
    findings = engine_checks.run_all(art, ctx)

    # ---- Phase 3: judgment layer (E-E-A-T + GEO assessment) ----
    if not opts.get("skip_judgment"):
        step("checking", "assessing E-E-A-T and GEO checkpoints")
        j = run_judgment(
            art, business_model=a.get("vertical"), client=a.get("client_name"),
            progress=lambda d, t: db.update_audit(
                audit_id, progress=f"judgment {d}/{t}"))
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
    step("checking", "collecting Search Console, Analytics and backlink data")
    findings.update(collect_gsc(a["target_url"], opts.get("gsc_refresh_token")))
    findings.update(collect_ga4(opts.get("ga4_property_id"),
                                opts.get("ga4_refresh_token"),
                                site_url=a["target_url"]))
    findings.update(collect_backlinks(art.host))

    # Business context: what the crawl learned about the CLIENT rather than
    # about their SEO. Free — it re-reads the artifact we already have — and it
    # is what lets the report open with a sentence that could only have been
    # written about this company.
    from engine.context import extract as extract_context
    bc = extract_context(art)
    extras = {"context": {**bc.to_dict(), "describe": bc.describe()}}

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
