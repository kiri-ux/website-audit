"""
Voice tests — does the report read as written, or as assembled?

This is a real product requirement, not polish. The deliverable is sold as
expert analysis; if it reads like generated output, the client discounts the
findings regardless of whether they are correct. So the tells are treated as
defects and tested for.

The four tells this guards against, all observed in real drafts of this report:

  1. PARALLEL GRAMMAR. Four consecutive bullets of the form "X scores N/100
     (R) — a of b passing". Nobody writes four sentences with identical
     structure by hand.
  2. THE SAME PROBLEM LISTED N TIMES. A draft opened with four "top findings"
     that were all "the site is not on HTTPS", because the checkpoint framework
     holds them as separate rows. A person writes that up once.
  3. DUPLICATED RATIONALE. The identical "why it matters" paragraph printed
     twice on one page.
  4. NO CLIENT IN IT. An opening paragraph that would be true of any website.

Run:  python3 -m tests.test_voice
"""
from __future__ import annotations
import functools
import http.server
import os
import re
import socketserver
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite:///data/test_voice.db")

from engine.crawler import Crawler
from engine import checks, scoring
from engine.context import extract
from engine.summarise import build_summary

PORT = 8094
FAILURES = []

# Phrases that mark generated marketing prose. Some are here because they are
# vague ("leverage"), some because they are chatbot filler ("it is important to
# note"), some because they are hype a paid audit should never need ("unlock").
BANNED = [
    "leverage", "unlock", "delve", "seamless", "cutting-edge", "game-chang",
    "in today's", "in the world of", "it is important to note",
    "it is worth noting", "furthermore", "moreover", "additionally,",
    "robust solution", "best-in-class", "supercharge", "elevate your",
    "landscape of", "navigate the", "harness", "synergy", "tapestry",
    "look no further", "dive into", "embark",
]


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)
    return cond


def _opening(s: str, n: int = 4) -> str:
    return " ".join(re.findall(r"[A-Za-z']+", s)[:n]).lower()


def _shape(s: str) -> str:
    """
    A crude grammatical fingerprint: words replaced by W, numbers by #.

    Two sentences with the same shape were almost certainly produced by the
    same template with different values substituted in.
    """
    toks = re.findall(r"\d+(?:[./]\d+)?|[A-Za-z']+|[—:;,()/]", s)
    return " ".join("#" if re.match(r"^\d", t) else
                    ("W" if t[0].isalpha() else t) for t in toks)[:120]


def main():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(
        ("0.0.0.0", PORT), functools.partial(
            Quiet, directory=os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "fixture", "site")))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.6)

    art = Crawler(f"http://localhost:{PORT}/", max_pages=40, delay=0.01,
                  verbose=False).crawl()
    F = checks.run_all(art, {"skip_psi": True})
    cat = scoring.load_catalog("seed/checkpoints.csv")
    sc = scoring.score(F, cat, "ecommerce")
    bc = extract(art)
    meta = {"client": "Grand Home Furnishings", "vertical": "ecommerce",
            "pages_crawled": len(art.pages), "url": "https://www.grandhf.com/",
            "coverage": f"{len(F)}/{len(cat)}", "generated": "2026-08-18 14:00",
            "extras": {"context": {**bc.to_dict(), "describe": bc.describe()}}}
    s = build_summary(F, sc, cat, meta)
    five = s["five_things"]

    print("\n1. NO TWO HEADLINE ITEMS ARE THE SAME PROBLEM")
    titles = [t["title"] for t in five]
    check("headline items are distinct", len(set(titles)) == len(titles),
          str([t for t in titles if titles.count(t) > 1]))
    # The specific regression: HTTPS appearing as several separate "problems".
    https_items = [t for t in titles if "https" in t.lower()]
    check("HTTPS is one problem, not four", len(https_items) <= 1,
          str(https_items))
    all_ids = [i for t in five for i in t["ids"]]
    check("no checkpoint is headlined twice", len(set(all_ids)) == len(all_ids))
    check("grouping is stated, not hidden",
          all(("separate checks" in t["finding"]) or t["count"] == 1
              for t in five),
          str([(t["title"][:26], t["count"]) for t in five]))

    print("\n2. NO RATIONALE IS PRINTED TWICE ON THE SAME PAGE")
    whys = [t["why"] for t in five if t["why"]]
    dupes = [w[:40] for w in whys if whys.count(w) > 1]
    check("each 'why it matters' appears once", not dupes, str(set(dupes)))

    print("\n3. SENTENCES ARE NOT STAMPED FROM ONE TEMPLATE")
    working = s["working"]
    shapes = [_shape(w) for w in working]
    check("no two 'what's working' sentences share a grammar shape",
          len(set(shapes)) == len(shapes), str(len(shapes) - len(set(shapes))))
    openings = [_opening(w) for w in working]
    check("no two 'what's working' sentences open the same way",
          len(set(openings)) == len(openings), str(openings))
    f_open = [_opening(t["finding"], 3) for t in five]
    check("headline findings do not all open identically",
          len(set(f_open)) > 1 or len(f_open) < 2, str(f_open))
    check("'what's working' is prose, not one bullet per section",
          len(working) <= 3, f"{len(working)} sentences")

    print("\n4. THE OPENING IS ABOUT THIS CLIENT")
    ov = s["overview"]
    check("overview names the client or their brand",
          "Grand Home" in ov or (bc.brand and bc.brand in ov), ov[:70])
    check("overview names the actual domain", "grandhf.com" in ov)
    # WAS: asserted the opener quoted the site's own meta description. Two
    # framings of that quote were rejected in review, and the reason holds:
    # a meta description is written to win a click, so quoting it opens a
    # report the client paid for with their own advertising read back to them.
    # The opener now leads with what WE did and names them in it.
    check("the opening does not quote their marketing copy back at them",
          not bc.self_description
          or bc.self_description.split(". ")[0][:40] not in ov,
          ov[:70])
    # The exact regression: URL path segments presented as business categories.
    check("no URL slug is passed off as a description of the business",
          "publishes pages covering" not in ov.lower(), ov[:80])
    check("overview carries real counts", bool(re.search(r"\d+ pages", ov)))
    check("overview leads with the business, not the audit",
          not ov.lower().startswith("this audit"), ov[:48])
    check("business context was extracted from the site",
          bool(bc.sections or bc.locations or bc.brand),
          f"brand={bc.brand!r} sections={bc.sections}")

    print("\n4b. PAID-MEDIA PIXELS ARE NEVER REPORTED AS DEFECTS")
    # Paid media is a different team and often a different agency. Reporting a
    # missing ad pixel as a finding bills work nobody asked for.
    from engine import checks as _checks
    ana = _checks.run_all(art, {"skip_psi": True})
    for cid in ("ANA-06", "ANA-07", "ANA-08", "ANA-09"):
        f = ana.get(cid, {})
        check(f"{cid} is never a defect",
              f.get("status") in ("N/A", "Pass"),
              f"{f.get('status')} / {f.get('severity')}")
    joined = " ".join((f.get("evidence") or "") for f in ana.values())
    check("no ad pixel is recommended anywhere",
          "Implement Meta Pixel" not in joined
          and "Install Google Ads" not in joined, "")

    print("\n5. NO MARKETING FILLER ANYWHERE IN THE PROSE")
    blob = " ".join([s["overview"], s.get("headline", ""), s["opportunity"],
                     *working, *[t["why"] for t in five],
                     *[t["finding"] for t in five],
                     *[t["action"] or "" for t in five]]).lower()
    hits = [b for b in BANNED if b in blob]
    check("no banned marketing phrase", not hits, str(hits))
    check("no unresolved template placeholder",
          not re.search(r"\{\w+\}|\bNone\b|\bnan\b", blob), "")
    check("no double spaces from a dropped clause", "  " not in blob)
    check("no orphaned punctuation from an empty variable",
          " ," not in blob and " ." not in blob and "()" not in blob)

    print("\n6. AMERICAN SPELLING THROUGHOUT")
    # Vici is a US agency with US clients (see VOICE.md). One British spelling
    # in a client deliverable is the kind of detail that reads as imported from
    # somewhere else.
    import pathlib
    BRITISH = ["canonicalis", "optimis", "organis", "behaviour", "colour",
               "centre", "prioritis", "analyse", "recognis", "emphasis" + "e",
               "normalis", "licence", "defence", "catalogue"]
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    # engine/consent/checks.py is OUR adapter and its strings are printed in
    # the client report; it was simply never on this list, so "recognised" and
    # "honoured" shipped in the consent findings for three builds. The rest of
    # engine/consent/ is the vendored scanner and stays off the list — we do
    # not restyle a dependency.
    for f in ("engine/summarise.py", "engine/pdf_report.py", "engine/report.py",
              "engine/glossary.py", "engine/context.py", "engine/charts.py",
              "engine/judgment.py", "engine/consent/checks.py", "app/ui.py"):
        text = (root / f).read_text()
        # reportlab's own API is spelled drawCentredString. That is a third-party
        # identifier, not our copy, so it is removed before the scan rather than
        # bending our spelling rule around it.
        text = text.replace("drawCentredString", "")
        for b in BRITISH:
            if b in text.lower():
                offenders.append(f"{f}:{b}")
    check("no British spellings in the report copy", not offenders,
          str(offenders[:6]))
    prose = " ".join([s["overview"], s["opportunity"], *working, *titles,
                      *[t["why"] for t in five]]).lower()
    check("rendered prose is American too",
          not any(b in prose for b in BRITISH), "")

    print("\n7. THE READER IS ADDRESSED DIRECTLY")
    check("the summary talks to the client, not about them",
          ("you" in prose or "your" in prose), "")
    check("no 'it is recommended that' constructions",
          "it is recommended" not in prose and "should be implemented" not in prose)

    print("\n7b. SECTION HEADERS ARE LABELS, NOT SENTENCES")
    import re as _re
    hdrs = _re.findall(r'Paragraph\("([A-Z][^"]{4,46})", S\["h[23]"\]\)',
                       (root / "engine/pdf_report.py").read_text())
    chatty = [h for h in hdrs
              if h.lower().startswith(("your ", "we ", "what we", "how we",
                                       "where the", "here", "all of"))
              or h.rstrip().endswith(("?", "!"))]
    check("no conversational section headers", not chatty, str(chatty))
    check("headers were actually found to check", len(hdrs) >= 6, str(len(hdrs)))

    print("\n8. ACRONYMS SURVIVE SENTENCE CASING")
    # Checked on the CASED text only: an acronym is allowed to be lowercase
    # inside a URL, but "Https" or "E-e-a-t" in a sentence means something ran
    # .capitalize() over a section name.
    cased = " ".join([s["overview"], s["opportunity"], *working, *titles])
    check("no 'Https' / 'Seo' / 'E-e-a-t' mangling",
          not re.search(r"\bHttps\b|\bSeo\b|\bE-e-a-t\b|\bGeo\b|\bHtml\b", cased),
          str(re.findall(r"\bHttps\b|\bSeo\b|\bE-e-a-t\b|\bGeo\b|\bHtml\b", cased)))

    print("\n" + "=" * 68)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — the report reads as written, not assembled")
    print("=" * 68 + "\n")
    httpd.shutdown()
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
