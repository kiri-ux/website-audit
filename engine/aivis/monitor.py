"""
Monitor orchestration.

Runs a panel across every configured platform, N times each, and aggregates.

The `repeats` parameter is the whole reason this module exists rather than being
a loop in the worker. These platforms are non-deterministic: ask the same
question three times and you can get cited once. Reporting a single-shot yes/no
would produce a metric that swings 30 points between runs for no real-world
reason, and a client watching that would rightly stop believing it.

So: every query runs `repeats` times, and every number downstream is a RATE over
attempts. Three is the practical floor; five is better if budget allows.
"""
from __future__ import annotations
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .panel import ClientProfile, build_panel, panel_summary
from .providers import ReplayProvider, active_providers
from .analyze import analyse_answer, aggregate, headline


def run_panel(profile: ClientProfile, queries=None, providers=None,
              repeats: int = 3, max_workers: int = 6, progress=None,
              skipped=None) -> dict:
    """
    Execute the panel. Returns the full result set plus aggregates.

    `providers` is a list of Provider instances. If omitted, every platform with
    credentials configured is used, and platforms without credentials are
    reported as skipped — never silently counted as zero visibility.

    `skipped` MATTERS EVEN WHEN THE CALLER SUPPLIES THE PROVIDERS.

    It used to be computed here and only here, so a caller that had already
    called `active_providers()` itself — which the audit worker does, to log
    the platform list before it starts — passed the providers in and the
    skipped list stayed empty. The aggregate then said nothing was skipped,
    and four checkpoints for four unconfigured platforms reported "no
    successful responses collected" instead of "no credentials configured".
    Two entirely different problems, printed identically, for months.
    """
    queries = queries or build_panel(profile)
    qmap = {q.id: q for q in queries}

    skipped = list(skipped or [])
    if providers is None:
        providers, skipped = active_providers()

    if not providers:
        return {"error": "no AI platforms configured",
                "skipped_platforms": skipped,
                "panel": panel_summary(queries), "results": [], "aggregate": {}}

    tasks = [(p, q, i) for p in providers for q in queries for i in range(repeats)]
    total, done = len(tasks), 0
    results, raw_answers = [], []

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(p.ask, q.id, q.text): (p, q, i) for p, q, i in tasks}
        for fut in as_completed(futs):
            p, q, i = futs[fut]
            try:
                ans = fut.result()
            except Exception as e:
                from .providers import Answer
                ans = Answer(p.name, q.id, error=f"{type(e).__name__}: {e}")
            row = analyse_answer(ans, profile)
            row["repeat"] = i
            row["intent"] = q.intent
            row["prompted"] = q.prompted
            results.append(row)
            raw_answers.append({"platform": ans.platform, "query_id": q.id,
                                "repeat": i, "text": ans.text[:4000],
                                "citations": ans.citations})
            done += 1
            if progress and done % 20 == 0:
                progress(done, total)

    agg = aggregate(results, qmap, profile)
    agg["skipped_platforms"] = skipped
    agg["repeats"] = repeats
    return {"panel": panel_summary(queries),
            "queries": [q.to_dict() for q in queries],
            "results": results, "raw": raw_answers,
            "aggregate": agg, "headline": headline(agg, profile)}


def run_replay(profile: ClientProfile, corpus: dict, queries=None,
               repeats: int = 1) -> dict:
    """Deterministic run against a recorded corpus — demos, CI, and accuracy tests."""
    provs = [ReplayProvider(corpus, platform=p) for p in corpus]
    return run_panel(profile, queries=queries, providers=provs,
                     repeats=repeats, max_workers=4)


def record_corpus(profile: ClientProfile, queries=None, repeats: int = 1,
                  path: str = "fixture/ai_corpus.json") -> str:
    """
    Capture real platform responses to disk so they can be replayed.

    Run this once against live APIs, commit the result, and CI gets a realistic
    regression corpus that costs nothing and never flakes.
    """
    out = run_panel(profile, queries=queries, repeats=repeats)
    corpus = {}
    for r in out["raw"]:
        corpus.setdefault(r["platform"], {})[r["query_id"]] = {
            "text": r["text"], "citations": r["citations"]}
    with open(path, "w") as f:
        json.dump(corpus, f, indent=1)
    return path
