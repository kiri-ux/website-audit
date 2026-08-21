"""
Job queue abstraction.

Two implementations behind one interface:

  DbQueue     — leases rows in the `jobs` table. No external dependency, so the
                POC runs with `python3 -m app.dev` and nothing else installed.
                Correct for single-worker internal use.
  RedisQueue  — BRPOPLPUSH onto a processing list, for multiple workers in
                production. Selected automatically when REDIS_URL is set.

Both are **at-least-once**: a crashed worker's job is redelivered after its
lease expires. Handlers must therefore be idempotent — `run_audit_job` is,
because it overwrites findings for the audit rather than appending.
"""
from __future__ import annotations
import json
import os
import time
import uuid

from .config import cfg
from . import db


class DbQueue:
    """Lease-based queue over the jobs table."""

    LEASE_S = 3600

    def enqueue(self, audit_id: str, job_type: str = "audit") -> str:
        jid = uuid.uuid4().hex[:16]
        with db.conn() as c:
            c.cursor().execute(db._q(
                "INSERT INTO jobs (id,audit_id,job_type,state,attempts,created_at) "
                "VALUES (?,?,?,?,?,?)"),
                (jid, audit_id, job_type, "pending", 0, time.time()))
        return jid

    def lease(self) -> dict | None:
        """Claim one job. Reclaims jobs whose lease expired (crashed worker)."""
        now = time.time()
        with db.conn() as c:
            cur = c.cursor()
            cur.execute(db._q(
                "SELECT id,audit_id,attempts,job_type FROM jobs "
                "WHERE state='pending' OR (state='leased' AND leased_until < ?) "
                "ORDER BY created_at LIMIT 1"), (now,))
            row = cur.fetchone()
            if not row:
                return None
            jid, aid, attempts, jtype = row[0], row[1], row[2], row[3]
            # Conditional update is the lock: if another worker claimed it
            # between our SELECT and here, rowcount is 0 and we return None.
            cur.execute(db._q(
                "UPDATE jobs SET state='leased', leased_until=?, attempts=? "
                "WHERE id=? AND (state='pending' OR leased_until < ?)"),
                (now + self.LEASE_S, attempts + 1, jid, now))
            if cur.rowcount == 0:
                return None
            return {"job_id": jid, "audit_id": aid, "attempts": attempts + 1,
                    "job_type": jtype or "audit"}

    def complete(self, job: dict):
        with db.conn() as c:
            c.cursor().execute(db._q("UPDATE jobs SET state='done' WHERE id=?"),
                               (job["job_id"],))

    def fail(self, job: dict, err: str, retry: bool = True):
        state = "pending" if retry else "failed"
        with db.conn() as c:
            c.cursor().execute(db._q(
                "UPDATE jobs SET state=?, last_error=?, leased_until=NULL WHERE id=?"),
                (state, err[:500], job["job_id"]))

    def depth(self) -> int:
        with db.conn() as c:
            cur = c.cursor()
            cur.execute("SELECT COUNT(*) FROM jobs WHERE state='pending'")
            return cur.fetchone()[0] or 0


class RedisQueue:
    """Production queue. Same interface; multiple workers safe."""

    KEY, PROCESSING = "vici:jobs", "vici:jobs:processing"
    LEASE_S = 3600

    def __init__(self, url: str):
        import redis
        # Socket timeouts, for the same reason the Postgres connect timeout
        # exists: a redis-py client built without them will wait FOREVER on a
        # host that accepts the connection and then goes quiet. The health
        # check reads queue depth, so an unbounded wait there stalls a request
        # thread, and enough stalled threads stop the health check answering at
        # all — which is how a Redis hiccup became a 502 on the report page.
        #
        # `lease()` is the deliberate exception: it uses a 2-second blocking pop
        # and must be allowed to sit on that call, so it gets a socket timeout
        # comfortably longer than its own block, not a shorter one.
        self.r = redis.from_url(
            url, decode_responses=True,
            socket_connect_timeout=float(os.getenv("REDIS_CONNECT_TIMEOUT", "5")),
            socket_timeout=float(os.getenv("REDIS_TIMEOUT", "10")),
            socket_keepalive=True,
            health_check_interval=30,
            retry_on_timeout=True)

    def enqueue(self, audit_id: str, job_type: str = "audit") -> str:
        jid = uuid.uuid4().hex[:16]
        self.r.lpush(self.KEY, json.dumps(
            {"job_id": jid, "audit_id": audit_id, "job_type": job_type}))
        return jid

    def lease(self) -> dict | None:
        raw = self.r.brpoplpush(self.KEY, self.PROCESSING, timeout=2)
        if not raw:
            return None
        d = json.loads(raw)
        d["_raw"], d["attempts"] = raw, 1
        d.setdefault("job_type", "audit")
        self.r.setex(f"vici:lease:{d['job_id']}", self.LEASE_S, "1")
        return d

    def complete(self, job: dict):
        raw = job.get("_raw")
        if raw:
            self.r.lrem(self.PROCESSING, 1, raw)
        self.r.delete(f"vici:lease:{job['job_id']}")

    def fail(self, job: dict, err: str, retry: bool = True):
        raw = job.get("_raw")
        if raw:
            self.r.lrem(self.PROCESSING, 1, raw)
            # Dead-letter after the worker's retry budget, so a permanently
            # broken target cannot cycle through the queue forever.
            self.r.lpush(self.KEY if retry else "vici:jobs:dead", raw)

    def depth(self) -> int:
        return self.r.llen(self.KEY)


def get_queue():
    return RedisQueue(cfg.redis_url) if cfg.redis_url else DbQueue()
