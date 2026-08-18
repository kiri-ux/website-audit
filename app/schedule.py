"""
Scheduled monitor runs — the thing that makes this a retainer product.

Run from a Render cron service (or any cron):

    python3 -m app.schedule --due-only

It enqueues a monitor run for every profile whose last run is older than
INTERVAL_DAYS. It does NOT execute the runs — it only enqueues; the worker
consumes them. That separation matters because Render hard-stops a cron run at
12 hours, and a fleet of monitor runs across many clients will exceed that. The
cron should always finish in seconds.

Idempotency: a profile with a run already queued or in-flight is skipped, so a
double-fired cron cannot double-bill you for API calls.
"""
from __future__ import annotations
import argparse
import os
import sys
import time

from . import db
from .queue import get_queue

INTERVAL_DAYS = float(os.getenv("MONITOR_INTERVAL_DAYS", "30"))
DEFAULT_REPEATS = int(os.getenv("MONITOR_REPEATS", "3"))


def due_profiles(interval_days: float = INTERVAL_DAYS):
    cutoff = time.time() - interval_days * 86400
    out = []
    for prof in db.list_ai_profiles():
        runs = db.list_ai_runs(profile_id=prof["id"], limit=1)
        if runs and runs[0]["status"] in ("queued", "running", "scoring"):
            continue                      # already in flight — never double-enqueue
        if not runs or (runs[0]["created_at"] or 0) < cutoff:
            out.append(prof)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--due-only", action="store_true",
                    help="only profiles past the interval (default: all)")
    ap.add_argument("--interval-days", type=float, default=INTERVAL_DAYS)
    ap.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    db.init_db()
    q = get_queue()
    profiles = due_profiles(a.interval_days) if a.due_only else db.list_ai_profiles()

    if not profiles:
        print("[schedule] nothing due")
        return 0

    for prof in profiles:
        if a.dry_run:
            print(f"[schedule] would enqueue {prof['client_name']} ({prof['domain']})")
            continue
        rid = db.create_ai_run(prof["partner_id"], prof["id"], a.repeats,
                               None, prof["panel_version"])
        q.enqueue(rid, job_type="ai_monitor")
        print(f"[schedule] enqueued {rid} for {prof['client_name']} ({prof['domain']})")

    print(f"[schedule] {len(profiles)} run(s) enqueued; worker will process them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
