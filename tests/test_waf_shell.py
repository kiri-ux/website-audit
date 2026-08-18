"""
Regression for the 11:44 production run.

A WAF answered EVERY path with an HTML challenge page and a 200 status. The
crawler parsed that page as robots.txt (inventing "99 Disallow rules"), then on
a later run reported the same page as a valid 922-byte llms.txt. Two runs minutes
apart produced contradictory infrastructure findings — the tell that none of it
was real.
"""
import os, sys, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.crawler import Crawler
from engine import checks, scoring

PORT = 8096
FAILURES = []
def check(l, c, d=""):
    print(f"  {'PASS' if c else 'FAIL'}  {l}" + (f"  ({d})" if d else ""))
    if not c: FAILURES.append(l)

def main():
    srv = subprocess.Popen([sys.executable, "/tmp/wafsrv.py", str(PORT)])
    time.sleep(1.2)
    try:
        art = Crawler(f"http://localhost:{PORT}/", max_pages=5, delay=0.01,
                      verbose=False).crawl()
        print("\nWAF SHELL DETECTION")
        check("robots.txt HTML response detected", art.robots_served_html,
              f"status={art.robots_status}")
        check("llms.txt HTML response detected", art.llms_served_html,
              f"status={art.llms_txt_status}")
        check("no phantom robots.txt content parsed", art.robots_txt is None)
        check("crawl marked degenerate", art.quality.degenerate)
        check("text-path signal recorded",
              any("plain-text paths" in s for s in art.quality.signals),
              str(art.quality.signals))

        F = checks.run_all(art, {"skip_psi": True})
        print("\nINFRASTRUCTURE NOT FOOLED")
        check("TECH-14 robots.txt -> Need Access, not Fail",
              F["TECH-14"]["status"] == "Need Access", F["TECH-14"]["status"])
        check("TECH-19 robots syntax -> Need Access",
              F["TECH-19"]["status"] == "Need Access", F["TECH-19"]["status"])
        check("GEO-01 llms.txt -> Need Access, NOT a false Pass",
              F["GEO-01"]["status"] == "Need Access", F["GEO-01"]["status"])
        check("GEO-02 llms formatting -> Need Access",
              F["GEO-02"]["status"] == "Need Access", F["GEO-02"]["status"])
        check("TECH-15 does not invent Disallow rules",
              F["TECH-15"]["value"].get("disallow_rules") in (None, 0),
              str(F["TECH-15"]["value"]))

        print("\nCONTENT CHECKS SUPPRESSED")
        for cid in ("ONP-02", "MOB-01", "HTML-01", "SCHEMA-02", "EEAT-12"):
            check(f"{cid} -> Need Access", F[cid]["status"] == "Need Access",
                  F[cid]["status"])

        print("\nNO CONFIDENT SCORE")
        sc = scoring.score(F, scoring.load_catalog("seed/checkpoints.csv"))
        check("overall score suppressed", sc["overall"]["score"] is None,
              str(sc["overall"]["score"]))
        # URL-06/16 and SEC-* measure transport, which IS observable even behind
        # a WAF (our test server is plain HTTP, so those failing is correct).
        TRANSPORT = {"URL-06", "URL-16", "SEC-01", "SEC-08", "SEC-10", "EEAT-19"}
        fails = [c for c, f in F.items()
                 if f["status"] == "Fail" and c not in TRANSPORT]
        check("no content/infrastructure Fail invented from a challenge page",
              len(fails) == 0, f"{len(fails)} fails: {fails[:8]}")
    finally:
        srv.terminate()

    print("\n" + "=" * 66)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — WAF challenge pages produce no false findings")
    print("=" * 66 + "\n")
    return 1 if FAILURES else 0

if __name__ == "__main__":
    sys.exit(main())
