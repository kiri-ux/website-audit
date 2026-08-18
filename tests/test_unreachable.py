"""
Regression for the 12:24/12:25 production runs against grandhf.com.

The host refused every request. HTTP 0 (the request threw) was read as "the file
is absent", producing 10 confident Fails — two of them CRITICAL — about a site
we never reached. Meanwhile checks that iterate empty collections returned Pass
("All sitemap URLs use HTTPS" over zero URLs), and E-E-A-T scored 100/100
Excellent off a single TLS check out of nine.

Three rules under test:
  1. a failed request is Need Access, never Fail
  2. no Pass over an empty collection
  3. no section score from a small minority of its checkpoints
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.crawler import Crawler
from engine import checks, scoring

FAILURES = []
def check(l, c, d=""):
    print(f"  {'PASS' if c else 'FAIL'}  {l}" + (f"  ({d})" if d else ""))
    if not c: FAILURES.append(l)

def main():
    # Port 9 (discard) on localhost: connections refused instantly. Nothing is
    # reachable, exactly like a host that blocks our egress IP outright.
    art = Crawler("http://localhost:9/", max_pages=5, delay=0.01, timeout=2,
                  verbose=False, max_seconds=30).crawl()

    print("\nUNREACHABLE HOST DETECTED")
    check("crawl marked degenerate", art.quality.degenerate, art.quality.reason)
    check("cause names blocking/unreachable",
          "unreachable" in art.quality.likely_cause or
          "blocking" in art.quality.likely_cause, art.quality.likely_cause)

    F = checks.run_all(art, {"skip_psi": True})

    print("\nRULE 1 — a failed request is NOT a defect")
    for cid, what in (("TECH-14", "robots.txt"), ("TECH-18", "robots.txt exists"),
                      ("TECH-19", "robots syntax"), ("TECH-22", "sitemap"),
                      ("TECH-28", "sitemap exists"), ("TECH-23", "sitemap in robots"),
                      ("TECH-30", "sitemap referenced"), ("SEC-01", "HTTPS enforced"),
                      ("SEC-10", "HSTS"), ("URL-06", "HTTP->HTTPS"),
                      ("URL-16", "HTTPS consistency"), ("GEO-01", "llms.txt"),
                      ("GEO-03", "llms.txt impl"), ("GEO-04", "AI crawler policy")):
        st = F[cid]["status"]
        check(f"{cid} ({what}) is not a Fail", st != "Fail", st)

    print("\nRULE 2 — no Pass over an empty collection")
    for cid, what in (("TECH-21", "sitemap XML validity"),
                      ("TECH-26", "sitemap URLs use HTTPS"),
                      ("TECH-27", "sitemap size"),
                      ("URL-16", "all pages HTTPS")):
        st = F[cid]["status"]
        check(f"{cid} ({what}) is not a vacuous Pass", st != "Pass", st)

    print("\nRULE 3 — no score from a handful of rows")
    sc = scoring.score(F, scoring.load_catalog("seed/checkpoints.csv"))
    for sec in ("EEAT", "GEO", "URL", "SEC", "TECH"):
        v = sc["sections"].get(sec, {})
        cov = f"{v.get('checked')}/{v.get('total')}"
        thin = v.get("checked", 0) / max(1, v.get("total", 1)) < 0.5
        ok = (v.get("score") is None) if thin else True
        check(f"{sec} score suppressed when coverage is thin ({cov})", ok,
              f"score={v.get('score')} rating={v.get('rating')}")

    check("overall score suppressed", sc["overall"]["score"] is None,
          str(sc["overall"]["score"]))

    fails = [c for c, f in F.items() if f["status"] == "Fail"]
    check("ZERO Fail findings from a completely unreachable host",
          len(fails) == 0, f"{len(fails)}: {fails[:10]}")
    crit = [c for c, f in F.items()
            if f["status"] == "Fail" and f["severity"] == "Critical"]
    check("zero CRITICAL findings invented", len(crit) == 0, str(crit))

    print("\n" + "=" * 66)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — an unreachable host produces no findings")
    print("=" * 66 + "\n")
    return 1 if FAILURES else 0

if __name__ == "__main__":
    sys.exit(main())
