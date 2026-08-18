"""
Regression for the first real production audit (grandhf.com, 13:06).

The crawl covered 50 pages of a 3,108-URL sitemap. Orphan detection compared
sitemap URLs against links seen in that 50-page sample and reported
"3058 pages have no inbound internal links" — as the TOP THREE priority issues,
at High severity.

3108 - 50 = 3058. It was subtraction, not analysis.

Rule under test: a check whose answer depends on the whole corpus must refuse to
answer on a sample, rather than reporting the sample gap as a defect.
"""
import os, sys, threading, functools, http.server, socketserver, time, pathlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.crawler import Crawler
from engine import checks

PORT = 8093
FAILURES = []
def check(l, c, d=""):
    print(f"  {'PASS' if c else 'FAIL'}  {l}" + (f"  ({d})" if d else ""))
    if not c: FAILURES.append(l)

def main():
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "fixture", "site")
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("0.0.0.0", PORT),
                                   functools.partial(Quiet, directory=root))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.6)

    # The fixture sitemap points at :8099; serving on :8093 makes those URLs
    # off-host, which reproduces exactly the shape we need: a sitemap far larger
    # than the crawled set.
    print("\nSAMPLED CRAWL (few pages, large sitemap)")
    art = Crawler(f"http://localhost:{PORT}/", max_pages=3, delay=0.01,
                  verbose=False).crawl()
    # Force the sampled condition deterministically.
    art.sitemap_status["_all_urls"] = [f"http://localhost:{PORT}/p{i}/"
                                       for i in range(3000)]
    check("coverage ratio reflects the sample", art.coverage_ratio < 0.1,
          f"{art.coverage_ratio:.1%}")
    check("artifact knows it is a sample", art.is_sample)

    F = checks.run_all(art, {"skip_psi": True})

    print("\nFULL-COVERAGE CHECKS REFUSE TO ANSWER")
    for cid, what in (("TECH-25", "orphaned pages in sitemap"),
                      ("TECH-36", "orphan pages identified"),
                      ("ONP-48", "no orphan pages"),
                      ("ONP-15", "pages with one inbound link")):
        f = F[cid]
        check(f"{cid} ({what}) is Need Access, not a Fail",
              f["status"] == "Need Access", f["status"])
        check(f"{cid} does not quote a fabricated orphan count",
              "orphan" not in f["evidence"].lower() or "not assessed" in f["evidence"].lower(),
              f["evidence"][:60])
    check("the refusal states the actual coverage",
          "3000" in F["TECH-25"]["evidence"] or "coverage" in str(F["TECH-25"]["value"]),
          str(F["TECH-25"]["value"]))

    print("\nFULL CRAWL STILL ANSWERS NORMALLY")
    art2 = Crawler("http://localhost:8093/", max_pages=60, delay=0.01,
                   verbose=False).crawl()
    F2 = checks.run_all(art2, {"skip_psi": True})
    check("with full coverage, orphan check runs",
          F2["TECH-25"]["status"] in ("Pass", "Fail"), F2["TECH-25"]["status"])
    check("coverage ratio is complete", not art2.is_sample,
          f"{art2.coverage_ratio:.0%}")

    print("\nIMAGE LINKS ARE NOT 'MISSING ANCHOR TEXT' DEFECTS")
    f17 = F2["ONP-17"]
    check("ONP-17 never reports a hard Fail", f17["status"] != "Fail", f17["status"])
    if f17["status"] == "Warning":
        check("ONP-17 flags it as needing verification", f17["confidence"] < 1.0,
              str(f17["confidence"]))

    print("\n" + "=" * 68)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — sampled crawls no longer claim sitewide findings")
    print("=" * 68 + "\n")
    httpd.shutdown()
    return 1 if FAILURES else 0

if __name__ == "__main__":
    sys.exit(main())
