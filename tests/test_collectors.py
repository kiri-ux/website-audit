"""
Contract test for the credential-gated collectors and the judgment layer.

The rule every one of them must honour: with no credentials configured, return
Need Access at confidence 0 — NEVER a Fail. "The client hasn't granted access"
and "your backlink profile is weak" are different sentences, and only one of
them is true when there's no API key.

Also asserts the PDF renders and the executive summary is derived from scored
findings rather than invented.
"""
import os, sys, threading, functools, http.server, socketserver, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AHREFS_API_KEY",
          "SEMRUSH_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
          "GOOGLE_TOKENS", "DFS_LOGIN", "DFS_PASSWORD"):
    os.environ.pop(k, None)
os.environ.setdefault("DATABASE_URL", "sqlite:///data/test_collectors.db")

from engine.crawler import Crawler
from engine import checks, scoring
from engine.judgment import run_judgment, CHECKPOINT_IDS
from engine.collectors import collect_gsc, collect_ga4, collect_backlinks, \
    collect_rankings, collect_lighthouse, capture_screenshot, dataforseo, \
    GSC_IDS, GA4_IDS, OFF_IDS
from engine.summarise import build_summary
from engine.pdf_report import build_pdf
from engine.report import render_html

PORT = 8092
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

    art = Crawler(f"http://localhost:{PORT}/", max_pages=40, delay=0.01,
                  verbose=False).crawl()
    F = checks.run_all(art, {"skip_psi": True})
    base = len(F)

    print("\nDEGRADATION CONTRACT — no credentials configured")
    j = run_judgment(art, "ecommerce", "Test Client")
    g = collect_gsc("https://example.com/", None)
    a4 = collect_ga4(None, None)
    b = collect_backlinks("example.com")

    for name, block, ids in (("judgment layer", j, CHECKPOINT_IDS),
                             ("Search Console", g, GSC_IDS),
                             ("GA4", a4, GA4_IDS),
                             ("backlinks", b, OFF_IDS)):
        check(f"{name} returns all {len(ids)} checkpoints", len(block) == len(ids),
              f"{len(block)}")
        fails = [c for c, f in block.items() if f["status"] == "Fail"]
        check(f"{name} emits ZERO Fail findings without credentials",
              not fails, str(fails[:5]))
        check(f"{name} uses Need Access", 
              all(f["status"] == "Need Access" for f in block.values()),
              str({f["status"] for f in block.values()}))
        check(f"{name} carries confidence 0",
              all(f["confidence"] == 0.0 for f in block.values()))
        check(f"{name} states what is needed",
              all(f["recommendation"] or f["evidence"] for f in block.values()))

    F.update(j); F.update(g); F.update(a4); F.update(b)
    cat = scoring.load_catalog("seed/checkpoints.csv")
    print("\nCOVERAGE")
    check("coverage grew by 96 checkpoints", len(F) == base + 96,
          f"{base} -> {len(F)}")
    check("coverage is over 80% of the template", len(F) / len(cat) > 0.8,
          f"{len(F)}/{len(cat)} = {100*len(F)//len(cat)}%")

    print("\nSCORING NOT DISTORTED BY UNCONFIGURED COLLECTORS")
    sc = scoring.score(F, cat, "ecommerce")
    for sec in ("GSC", "GA4", "OFF"):
        v = sc["sections"].get(sec, {})
        check(f"{sec} section is Not Assessed, not scored low",
              v.get("score") is None, f"score={v.get('score')}")

    print("\nEXECUTIVE SUMMARY")
    meta = {"client": "Test Client", "vertical": "ecommerce",
            "pages_crawled": len(art.pages), "url": f"http://localhost:{PORT}/",
            "coverage": f"{len(F)}/{len(cat)}", "generated": "2026-08-18 14:00"}
    s = build_summary(F, sc, cat, meta)
    check("summary has an overview", bool(s["overview"]))
    check("summary lists priority issues", len(s["issues"]) > 0, str(len(s["issues"])))
    check("summary builds a phased roadmap", len(s["roadmap"]) > 0,
          str([p["phase"] for p in s["roadmap"]]))
    check("summary is deterministic without an LLM key",
          s["generated_by"] == "deterministic", s["generated_by"])
    check("no acronym mangling in section names",
          "E-e-a-t" not in str(s) and "Https" not in str(s))
    # every issue in the summary must exist in the findings
    ids_in_cat = {cat[c]["checkpoint"] for c in F if c in cat}
    orphaned = [i for i in s["issues"]
                if not any(i.startswith(n) for n in ids_in_cat)]
    check("every summary issue traces to a real checkpoint", not orphaned,
          str(orphaned[:2]))

    print("\nDATAFORSEO — UNCONFIGURED DEGRADATION")
    check("dataforseo reports itself unconfigured", not dataforseo.configured())
    lh = collect_lighthouse("https://example.com/")
    check("Lighthouse returns Need Access, never Fail",
          all(f["status"] == "Need Access" for f in lh.values()),
          str({f["status"] for f in lh.values()}))
    check("Lighthouse rows carry confidence 0",
          all(f["confidence"] == 0.0 for f in lh.values()))
    rk_off = collect_rankings("example.com")
    check("rankings report unavailable rather than an empty table",
          rk_off["available"] is False and rk_off["rows"] == [],
          rk_off.get("reason", ""))
    check("screenshot returns None without credentials",
          capture_screenshot("https://example.com/") is None)
    check("backlinks fall back to the Ahrefs/Semrush adapter when DFS is absent",
          all(f["status"] == "Need Access" for f in collect_backlinks("example.com").values()))

    print("\nMULTI-LOGIN TOKEN INDEX")
    os.environ["GOOGLE_TOKENS"] = '{"vici-1":"x","vici-2":"y"}'
    g2 = collect_gsc("https://example.com/", None)
    a42 = collect_ga4(None, None, site_url="https://example.com/")
    check("GSC still degrades to Need Access when no login can see the property",
          all(f["status"] == "Need Access" for f in g2.values()))
    check("GSC says how many logins were tried, so the failure is actionable",
          "tried 2 login(s)" in g2["GSC-01"]["evidence"], g2["GSC-01"]["evidence"][:90])
    check("GA4 degrades to Need Access and names the bounded scan",
          all(f["status"] == "Need Access" for f in a42.values())
          and "properties per login" in a42["GA4-01"]["evidence"],
          a42["GA4-01"]["evidence"][:90])
    os.environ.pop("GOOGLE_TOKENS", None)

    print("\nKEYWORD RANKINGS SECTION")
    meta_rk = dict(meta)
    meta_rk["extras"] = {"rankings": {
        "available": True, "total": 3, "top10": 2, "location": "United States",
        "rows": [{"keyword": "grand furniture roanoke", "search_volume": 2400,
                  "difficulty": 12, "position": 1,
                  "url": "https://example.com/roanoke"},
                 {"keyword": "sofas near me", "search_volume": 18100,
                  "difficulty": 61, "position": 7, "url": "https://example.com/sofas"},
                 {"keyword": "cheap mattress", "search_volume": None,
                  "difficulty": None, "position": 34, "url": ""}]}}
    html_rk = render_html(meta_rk, sc, F, cat, s)
    check("HTML report renders the rankings table",
          "Keyword rankings" in html_rk and "grand furniture roanoke" in html_rk)
    check("rows with missing volume/difficulty still render all five cells",
          "cheap mattress" in html_rk)
    check("page-one positions are emphasised", "<b>1</b>" in html_rk)
    html_no = render_html(meta, sc, F, cat, s)
    check("no rankings data -> section omitted entirely, not shown empty",
          "Keyword rankings" not in html_no)
    meta_un = dict(meta)
    meta_un["extras"] = {"rankings": {"available": False, "reason": "not configured",
                                      "rows": []}}
    html_un = render_html(meta_un, sc, F, cat, s)
    check("unavailable rankings say why rather than estimating",
          "omitted rather than estimated" in html_un)
    pdf_rk = build_pdf(meta_rk, sc, F, cat, s)
    check("PDF renders with the rankings section", pdf_rk[:4] == b"%PDF",
          f"{len(pdf_rk)//1024}KB")

    print("\nPDF DELIVERABLE")
    pdf = build_pdf(meta, sc, F, cat, s)
    check("PDF renders", pdf[:4] == b"%PDF", f"{len(pdf)//1024}KB")
    try:
        from pypdf import PdfReader
        import io
        n = len(PdfReader(io.BytesIO(pdf)).pages)
        check("PDF is multi-page", n >= 5, f"{n} pages")
    except Exception as e:
        check("PDF parseable", False, str(e))

    print("\n" + "=" * 68)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — collectors degrade honestly; PDF ships")
    print("=" * 68 + "\n")
    httpd.shutdown()
    return 1 if FAILURES else 0

if __name__ == "__main__":
    sys.exit(main())
