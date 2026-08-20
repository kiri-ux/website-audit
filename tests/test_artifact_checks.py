"""
The checkpoints that moved from "reviewed by hand" to measured.

Every one of these was previously reported as manual, which was only ever true
in the sense that nobody had written it. They are decided entirely from the
stored crawl — no new request to the client's site — so the risk is not cost,
it is CONFIDENCE: a check that half-answers and states it plainly is worse than
no check at all.

So each one is tested twice: once on data that should pass, once on data that
should fail. A check that can only ever say Pass is not a check.

Run:  python3 -m tests.test_artifact_checks
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite:///data/test_artifact.db")

from engine.crawler import Page, SiteArtifact
from engine import checks as C

FAILURES = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)


def art(pages, **kw):
    a = SiteArtifact(start_url="https://x.test/", host="x.test", scheme="https")
    for p in pages:
        a.pages[p.url] = p
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def page(url, **kw):
    p = Page(url=url, status_code=200, final_url=kw.pop("final_url", url))
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def run(a, cid):
    return C.REGISTRY[cid](a, {"skip_psi": True})


def main():
    print("\nBLOCKED RESOURCES — robots.txt vs what the pages actually load")
    good = art([page("https://x.test/", depth=0,
                     scripts=["https://x.test/js/app.js"])],
               robots_txt="User-agent: *\nDisallow: /admin/")
    check("an asset outside the blocked path passes",
          run(good, "TECH-16")["status"] == "Pass")
    bad = art([page("https://x.test/", depth=0,
                    scripts=["https://x.test/admin/app.js"])],
              robots_txt="User-agent: *\nDisallow: /admin/")
    r = run(bad, "TECH-16")
    check("a script under a disallowed path is caught",
          r["status"] == "Fail" and r["severity"] == "High", r["evidence"][:60])
    # The rule that stops this inventing findings: a Disallow aimed at some
    # other bot says nothing about Google.
    named = art([page("https://x.test/", depth=0,
                      scripts=["https://x.test/admin/app.js"])],
                robots_txt="User-agent: AhrefsBot\nDisallow: /admin/")
    check("a rule aimed at a named bot is NOT treated as blocking Google",
          run(named, "TECH-16")["status"] == "Pass")
    check("no robots.txt is Need Access, never a pass or a fail",
          run(art([page("https://x.test/", depth=0)]), "TECH-16")["status"]
          == "Need Access")

    print("\nTOP-LEVEL PAGES MUST BE INDEXABLE")
    check("clean shallow pages pass",
          run(art([page("https://x.test/", depth=0),
                   page("https://x.test/a", depth=1)]), "TECH-20")["status"]
          == "Pass")
    r = run(art([page("https://x.test/", depth=0),
                 page("https://x.test/a", depth=1, meta_robots="noindex")]),
            "TECH-20")
    check("a noindexed top-level page is Critical",
          r["status"] == "Fail" and r["severity"] == "Critical", r["evidence"][:50])

    print("\nHTTPS IS JUDGED ON WHERE THE URL LANDS, NOT WHERE IT STARTED")
    check("an http URL that redirects to https passes",
          run(art([page("http://x.test/", final_url="https://x.test/")]),
              "SEC-13")["status"] == "Pass")
    check("a page that finally resolves over http fails",
          run(art([page("http://x.test/", final_url="http://x.test/")]),
              "SEC-13")["status"] == "Fail")

    print("\nCRAWL ERRORS ARE CLASSIFIED, NOT LUMPED")
    dns = Page(url="https://gone.test/", error="Name or service not known")
    other = Page(url="https://slow.test/", error="timed out")
    a = art([page("https://x.test/")])
    a.pages[dns.url] = dns
    a.pages[other.url] = other
    r = run(a, "TECH-04")
    check("a DNS failure is reported", r["status"] == "Fail", r["evidence"][:50])
    check("and a timeout is NOT counted as one",
          "1 URL" in r["evidence"], r["evidence"][:50])

    print("\nMALFORMED LINKS")
    check("ordinary links pass",
          run(art([page("https://x.test/",
                        links_internal=[{"href": "/a"}, {"href": "https://x.test/b"}])]),
              "TECH-05")["status"] == "Pass")
    r = run(art([page("https://x.test/",
                      links_internal=[{"href": "https://x.test/a b"}])]), "TECH-05")
    check("a space inside an href is caught", r["status"] == "Fail")
    check("anchors, mailto and tel are not links to follow",
          run(art([page("https://x.test/",
                        links_internal=[{"href": "#top"}, {"href": "mailto:a@b.c"},
                                        {"href": "tel:+1"}])]),
              "TECH-05")["status"] == "Pass")

    print("\nHREFLANG")
    none_tagged = art([page("https://x.test/")])
    for cid in ("INTL-02", "INTL-03", "INTL-05"):
        check(f"{cid} is N/A on a site with no hreflang — not a failure",
              run(none_tagged, cid)["status"] == "N/A")
    ok = art([page("https://x.test/", lang="en",
                   hreflang=[{"hreflang": "en", "href": "https://x.test/"},
                             {"hreflang": "es-MX", "href": "https://x.test/es"}])])
    for cid in ("INTL-02", "INTL-03", "INTL-05"):
        check(f"{cid} passes on well-formed tags", run(ok, cid)["status"] == "Pass",
              run(ok, cid)["evidence"][:50])
    bad = art([page("https://x.test/", lang="en",
                    hreflang=[{"hreflang": "english", "href": "https://x.test/"}])])
    check("an invalid language tag is caught",
          run(bad, "INTL-03")["status"] == "Fail")
    dup = art([page("https://x.test/", lang="en",
                    hreflang=[{"hreflang": "en", "href": "https://x.test/a"},
                              {"hreflang": "en", "href": "https://x.test/b"}])])
    check("the same language pointed at two URLs is caught",
          run(dup, "INTL-02")["status"] == "Fail")
    mism = art([page("https://x.test/", lang="de",
                     hreflang=[{"hreflang": "en", "href": "https://x.test/"}])])
    check("lang contradicting the self-referencing hreflang is caught",
          run(mism, "INTL-05")["status"] == "Fail")

    print("\nSTRUCTURAL MARKUP")
    check("a complete page passes",
          run(art([page("https://x.test/", doctype="html", charset="utf-8",
                        lang="en")]), "HTML-06")["status"] == "Pass")
    r = run(art([page("https://x.test/", doctype="html", charset="", lang="en")]),
            "HTML-06")
    check("a missing charset is caught and counted",
          r["status"] == "Fail" and "charset" in r["evidence"], r["evidence"][:60])

    print("\n" + "=" * 68)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — ten checkpoints answered from the "
               "stored crawl")
    print("=" * 68 + "\n")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
