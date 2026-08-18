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
        print(f"[worker] {audit_id} TRUNCATED: {art.truncated}", flush=True)
    q = art.quality
    if q.degenerate:
        # Do not silently produce a report full of false findings.
        print(f"[worker] {audit_id} CRAWL DEGENERATE: {q.reason} | {q.likely_cause} "
              f"| signals={q.signals}", flush=True)
        step("checking", f"crawl blocked ({q.likely_cause}); "
                         f"content checks will report Need Access")
    else:
        step("checking", f"crawled {len(art.pages)} pages; running checkpoints")

    ctx = {"psi_key": cfg.psi_key,
           "skip_psi": bool(opts.get("skip_psi", cfg.skip_psi))}
    findings = engine_checks.run_all(art, ctx)
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
