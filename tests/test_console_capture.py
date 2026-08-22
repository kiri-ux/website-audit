"""
Search Console's UI-only numbers, read from a signed-in browser.

Eight checkpoints are published by Google in the interface and exposed through
no API. The extension reads them where they live. The rule this file holds is
the one that makes that safe: **a capture that half-worked must leave the other
half unmeasured**, because a zero in the exclusion reports reads as "no pages
excluded", and that is a materially wrong statement about a site.

Run:  python3 -m tests.test_console_capture
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILED: list[str] = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILED.append(label)


FULL = {"indexed": 118, "not_indexed": 41,
        "reasons": {"Crawled - currently not indexed": 22,
                    "Discovered - currently not indexed": 14,
                    "Soft 404": 0, "Server error (5xx)": 5},
        "cwv": {"poor": 0, "needs_improvement": 6, "good": 112, "metric": "LCP"},
        "captured_at": "2026-08-22T15:40:00Z"}


def main():
    from engine.console_capture import findings_from_capture as F

    print("\nA FULL CAPTURE FILLS THE ROWS GOOGLE WILL NOT SERVE")
    r = F(FULL)
    check("index coverage lands", r["GSC-05"]["value"]["indexed"] == 118)
    check("and the exclusion reasons land on their own checkpoints",
          r["GSC-07"]["value"]["count"] == 22
          and r["GSC-08"]["value"]["count"] == 14
          and r["GSC-10"]["value"]["count"] == 5)
    check("zero is a clean pass, not an omission",
          r["GSC-09"]["status"] == "Pass")
    check("Core Web Vitals reads Poor before Needs improvement",
          r["GSC-12"]["status"] == "Warning"
          and r["GSC-12"]["value"]["needs_improvement"] == 6)
    check("a Poor group is a Fail, because it is a failing template",
          F({"cwv": {"poor": 3}})["GSC-12"]["status"] == "Fail")

    print("\nNOTHING IS INVENTED")
    # The rule the whole module exists for.
    check("a capture with only one number fills only one row",
          sorted(F({"indexed": 10})) == ["GSC-05"])
    check("an empty capture fills nothing", F({}) == {} and F(None) == {})
    check("a reason Google renamed is skipped, not guessed at",
          "GSC-07" not in F({"reasons": {"Crawled but not indexed yet": 9}}))
    check("and a reason with no number is skipped too",
          F({"reasons": {"Soft 404": None}}) == {})

    print("\nTHE NUMBERS ARE READ THE WAY THE UI PRINTS THEM")
    check("thousands separators", F({"indexed": "1,204"})["GSC-05"]["value"]["indexed"] == 1204)
    check("abbreviated counts", F({"indexed": "1.2K"})["GSC-05"]["value"]["indexed"] == 1200)
    check("junk is not a zero", F({"indexed": "—"}) == {})

    print("\nA COUNT IS NOT A VERDICT")
    # Every site of any age has a few of these. Calling nine soft 404s a
    # failure is how a row gets skipped every time thereafter.
    small = F({"indexed": 500, "reasons": {"Soft 404": 4}})
    check("a handful is reported without alarm", small["GSC-09"]["status"] == "Info")
    big = F({"indexed": 100, "reasons": {"Soft 404": 60}})
    check("a large share is a Warning", big["GSC-09"]["status"] == "Warning")
    check("and never worse than a Warning — this is a count, not a diagnosis",
          big["GSC-09"]["severity"] == "Medium")

    print("\nPROVENANCE TRAVELS WITH EVERY ROW")
    # A number read off a screen and a number pulled from an API are not the
    # same kind of fact, and nobody will remember which in six months.
    check("each row says where it came from",
          all(v["value"].get("captured_from") == "Search Console UI"
              for v in r.values()))
    check("and when", all(v["value"].get("captured_at") for v in r.values()))
    check("the source tag separates it from a failed API call",
          all(v["source"] == "gsc_ui_capture" for v in r.values()))

    print("\nTHE ENDPOINT MERGES, IT DOES NOT REPLACE")
    import inspect
    from app import api
    src = inspect.getsource(api.ingest_console_capture)
    check("existing findings are read before writing",
          "db.get_findings(" in src and "findings.update(rows)" in src)
    check("scores are recomputed so the report reflects the new rows",
          "save_scores" in src)
    check("and a capture we recognised nothing in is refused",
          "if not rows" in src and "400" in src)

    print("\nTHE EXTENSION CONFIRMS BEFORE IT SENDS")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bg = open(os.path.join(root, "extension", "background.js")).read()
    pop = open(os.path.join(root, "extension", "popup.js")).read()
    check("the scrape anchors on Google's visible labels",
          "crawled - currently not indexed" in bg and "soft 404" in bg)
    check("capture and send are separate steps",
          "VICI_CONSOLE_SEND" in bg and "consoleDraft" in bg)
    check("nothing posts straight off the scrape",
          bg.index("state.consoleDraft =") < bg.index("async function consoleSend"))
    check("and the draft is editable in the popup, not read-only",
          "collectDraft" in pop and "data-k=" in pop)

    print("\n" + "=" * 68)
    if FAILED:
        print(f"  {len(FAILED)} FAILED: {FAILED}")
    else:
        print("  ALL CHECKS PASSED — the console capture never invents a number")
    print("=" * 68 + "\n")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
