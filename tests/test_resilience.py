"""
The 502, and the marks that tell a reviewer where to look.

THE 502
-------
A run reached the judgment layer and the report page returned 502 Bad Gateway.
The API's own code was fine. What was not fine was that three separate things
had no ceiling on how long they could wait:

  * `psycopg2.connect()` with no `connect_timeout` waits FOREVER when Postgres
    cannot accept another connection.
  * A query with no `statement_timeout` waits forever behind a lock.
  * `redis.from_url()` with no socket timeout waits forever on a host that
    accepts the connection and then goes quiet.

Uvicorn serves sync routes from a bounded thread pool. A handful of permanently
stuck requests takes every thread, and once that happens `/healthz` cannot be
answered either — so Render concludes the service is dead and starts serving
502s to the browser. A database having a bad minute became a total outage.

The fix is not "make it faster". It is a ceiling on the damage, and a health
check that reports on ITSELF rather than on its dependencies. A liveness probe
that fails when Redis is slow is not a liveness probe; it is a mechanism for
converting someone else's bad minute into your own.

THE LAMP
--------
Rows the judgment layer produced are read, not counted — and a reading can be
wrong in ways a count cannot. They carry a lightbulb so the team knows which
rows to check hardest before a report goes out.

The mark lives in BOTH documents; the legend explaining it lives only in the
internal one. The client was never asked to act on the lamp, so a paragraph in
their report explaining a symbol is furniture — and the review it exists to
prompt happens on the operator page, not in the delivered PDF.
"""
from __future__ import annotations
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILED: list[str] = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILED.append(label)


def main():
    print("NOTHING THE API WAITS ON MAY WAIT FOREVER")
    from app import db
    src = inspect.getsource(db.conn)
    check("the Postgres connect has a timeout", "connect_timeout" in src, src[:0])
    check("statements have a server-side deadline", "statement_timeout" in src)
    check("the connect timeout is a real number, not zero",
          db.PG_CONNECT_TIMEOUT > 0, str(db.PG_CONNECT_TIMEOUT))
    check("the statement deadline is generous enough for an artifact write",
          db.PG_STATEMENT_TIMEOUT_MS >= 20000, str(db.PG_STATEMENT_TIMEOUT_MS))

    from app import queue as qmod
    rsrc = inspect.getsource(qmod.RedisQueue.__init__)
    check("the Redis client has a connect timeout", "socket_connect_timeout" in rsrc)
    check("the Redis client has a read timeout", "socket_timeout" in rsrc)
    # lease() blocks for 2s on purpose. A socket timeout shorter than its own
    # block would turn normal idling into a stream of timeout errors.
    check("the read timeout outlasts the blocking pop it has to survive",
          float(os.getenv("REDIS_TIMEOUT", "10")) > qmod.RedisQueue.LEASE_S / 1000 + 2,
          "lease() blocks 2s")

    print("\nTHE HEALTH CHECK REPORTS ON ITSELF, NOT ON ITS DEPENDENCIES")
    from app import api
    hsrc = inspect.getsource(api.healthz)
    check("queue depth is wrapped, so a dead queue cannot fail the probe",
          "try:" in hsrc and "except" in hsrc)

    class Broken:
        def depth(self):
            raise RuntimeError("redis is gone")

    real = api.Q
    api.Q = Broken()
    try:
        out = api.healthz()
    finally:
        api.Q = real
    check("the service still reports healthy when the queue is unreachable",
          out.get("ok") is True, str(out.get("ok")))
    check("and says the depth is unknown rather than inventing a zero",
          out.get("queue_depth") is None, str(out.get("queue_depth")))
    check("the build is still reported, which is what makes it diagnosable",
          bool(out.get("build")))

    print("\nA RUN WHOSE WORKER DIED STOPS PRETENDING TO BE ALIVE")
    import time
    from app import ui
    from app.db import MIGRATIONS
    check("audits carry a heartbeat column",
          any(t == "audits" and c == "heartbeat_at" for t, c, _ in MIGRATIONS))
    src = inspect.getsource(ui)
    check("the worker's step stamps it", "heartbeat_at" in
          inspect.getsource(__import__("app.worker", fromlist=["x"])))

    base = {"id": "abc123", "client_name": "Ooten", "target_url": "https://x.com",
            "status": "checking", "progress": "judgment 20/44", "options": "{}",
            "pages_crawled": 40}
    live = ui.audit_html({**base, "heartbeat_at": time.time() - 5})
    dead = ui.audit_html({**base, "heartbeat_at": time.time() - 3600})
    old = ui.audit_html({**base, "heartbeat_at": None})

    check("a live run still auto-refreshes", "http-equiv='refresh'" in live)
    check("a live run shows the phase it is in", "judgment 20/44" in live)
    check("a dead run says so", "stopped responding" in dead)
    check("a dead run stops auto-refreshing at a corpse",
          "http-equiv='refresh'" not in dead)
    check("a dead run offers the rerun", "/audits/abc123/rerun" in dead)
    check("and offers it WITHOUT re-crawling the client's server",
          "reuse_crawl" in dead)
    # Runs that predate the column have no heartbeat. Unknown must not read as
    # dead — calling a live run dead is the worse error of the two.
    check("a run with no heartbeat is treated as live, not dead",
          "stopped responding" not in old and "http-equiv='refresh'" in old)

    print("\nTHE RERUN ROUTE ACCEPTS WHAT THE PANEL SENDS IT")
    sig = inspect.signature(api.rerun_audit)
    check("rerun takes reuse_crawl", "reuse_crawl" in sig.parameters)
    check("rerun passes it through",
          "reuse_crawl" in inspect.getsource(api.rerun_audit))

    print("\nJUDGED ROWS ARE MARKED, IN BOTH RENDERERS")
    from engine import report as R
    from engine.report import is_judged, _lamp, LAMP, JUDGED_NOTE
    from engine.pdf_report import _judged
    from engine.judgment import CHECKPOINT_IDS

    check("every judgment checkpoint is recognized",
          all(is_judged(c) for c in CHECKPOINT_IDS), str(len(CHECKPOINT_IDS)))
    check("a crawler-measured checkpoint is not",
          not is_judged("TECH-01") and not is_judged("GSC-01"))
    check("the two renderers agree on which rows carry a reading",
          all(_judged(c, "Warning") == bool(_lamp(c, "Warning"))
              for c in list(CHECKPOINT_IDS) + ["TECH-01", "GSC-01", "OFF-01"]))

    print("\nAN UNANSWERED ROW CARRIES NO MARK")
    # The lamp sends a reviewer to reread a judgment. There is nothing to reread
    # on a row that was never judged because the key was missing.
    for status in ("Need Access", "N/A"):
        check(f"a {status} row is not marked",
              _lamp("EEAT-01", status) == "" and not _judged("EEAT-01", status))
    check("an answered row is marked", _lamp("EEAT-01", "Warning") != "")

    print("\nTHE MARK IS A TEAM SIGNAL, NOT CLIENT-FACING FURNITURE")
    # The lamp exists so whoever reviews the draft knows which rows to reread.
    # The client was never asked to act on it, so a paragraph in their document
    # explaining a symbol is furniture. It stays on the internal HTML report,
    # where the review actually happens.
    import inspect as _i
    from engine import pdf_report as _pdf
    check("the client PDF carries no legend paragraph",
          "Judged by review" not in _i.getsource(_pdf))
    check("the internal report still explains it",
          "Judged by review" in _i.getsource(R))
    check("but the PDF still marks the rows",
          "Lamp(" in _i.getsource(_pdf))

    print("\nTHE MARK IS EXPLAINED, AND EXPLAINED HONESTLY")
    check("the lamp is drawn, not an emoji that renders as a black box",
          "<svg" in LAMP and "\U0001F4A1" not in LAMP)
    check("the legend says what the row IS",
          JUDGED_NOTE == "Judged by review rather than measured.")
    # The client reads this document. It must not carry a machine disclosure,
    # and it must not carry a falsehood either — hence a description of the
    # row's nature rather than of its provenance.
    lowered = (JUDGED_NOTE + " " + R.LAMP).lower()
    for word in ("ai-generated", "ai generated", "chatgpt", "llm", "claude",
                 "machine-generated", "automated guess"):
        check(f"the report does not say '{word}'", word not in lowered)

    print("\n" + "=" * 68)
    if FAILED:
        print(f"  {len(FAILED)} FAILED: {FAILED}")
    else:
        print("  ALL CHECKS PASSED — a slow dependency can no longer take the "
              "service down, and judged rows are marked")
    print("=" * 68 + "\n")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
