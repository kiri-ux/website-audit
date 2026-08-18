"""
Regression test for the production failure on 2026-08-18.

A bot-protected site returned a near-empty 200 shell. The checkers reported ~20
confident findings (no title, no H1, no images, no links) describing a site that
looks nothing like that. Every one was false.

A crawler that cannot see the page must say so — never let "we were blocked"
become "your site is broken".
"""
import os, sys, threading, functools, http.server, socketserver, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite:///data/test_blocked.db")

from engine.crawler import Crawler
from engine import checks

PORT = 8097
FAILURES = []
def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not cond: FAILURES.append(label)

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass

def main():
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "fixture", "blocked")
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("0.0.0.0", PORT), functools.partial(Quiet, directory=root))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.6)

    print("\nBLOCKED-CRAWL DETECTION")
    art = Crawler(f"http://localhost:{PORT}/", max_pages=10, delay=0.01,
                  verbose=False).crawl()
    q = art.quality
    check("degenerate crawl detected", q.degenerate, q.reason)
    check("multiple independent signals recorded", len(q.signals) >= 3,
          f"{len(q.signals)} signals")
    check("cause identified as bot protection", "bot protection" in q.likely_cause,
          q.likely_cause)

    F = checks.run_all(art, {"skip_psi": True})

    print("\nFALSE FINDINGS SUPPRESSED")
    # These are precisely the rows that were wrong in production.
    for cid, what in (("ONP-02", "no title tag"), ("ONP-31", "no H1"),
                      ("ONP-06", "no meta description"), ("MOB-01", "no viewport"),
                      ("HTML-01", "no charset"), ("HTML-02", "no doctype"),
                      ("INTL-04", "no lang attribute"), ("ONP-10", "thin content"),
                      ("SCHEMA-02", "no Organization schema"),
                      ("EEAT-12", "no contact page"), ("ANA-01", "no GTM")):
        check(f"{cid} ({what}) -> Need Access, not Fail",
              F[cid]["status"] == "Need Access", F[cid]["status"])

    check("suppressed rows carry confidence 0",
          all(F[c]["confidence"] == 0.0 for c in ("ONP-02", "MOB-01", "SCHEMA-02")))

    print("\nINFRASTRUCTURE CHECKS STILL RUN")
    for cid, what in (("TECH-14", "robots.txt exists"), ("GEO-01", "llms.txt"),
                      ("URL-01", "www resolution"), ("GEO-04", "AI crawler policy")):
        check(f"{cid} ({what}) still evaluated",
              F[cid]["status"] != "Need Access" or F[cid]["source"] != "crawl_blocked",
              F[cid]["status"])

    print("\nSCORING NOT POISONED")
    from engine import scoring
    cat = scoring.load_catalog("seed/checkpoints.csv")
    sc = scoring.score(F, cat)
    onp = sc["sections"].get("ONP", {})
    check("On-Page section is Not Assessed, not a low score",
          onp.get("score") is None, f"score={onp.get('score')} rating={onp.get('rating')}")
    check("overall score is not a confident number",
          sc["overall"]["score"] is None or sc["overall"]["score"] >= 60,
          str(sc["overall"]["score"]))

    print("\n" + "=" * 64)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — blocked crawls no longer produce false findings")
    print("=" * 64 + "\n")
    httpd.shutdown()
    return 1 if FAILURES else 0

if __name__ == "__main__":
    sys.exit(main())
