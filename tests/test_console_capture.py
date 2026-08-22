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
    # WAS: asserted nothing posted without a trip to the popup. The
    # confirmation was the right instinct in the wrong place — the operator
    # pressed a button on the audit page, so a capture that ends by telling
    # them to go and find another window is a capture most people abandon.
    #
    # It sends, then puts them back on the audit. The numbers are not lost to
    # sight by that: every captured row renders in the report with its value
    # and a `captured_from` marker, and running the capture again overwrites
    # it — so a wrong number is one click from being right.
    check("the capture sends without a detour through the popup",
          "await consoleSend()" in bg)
    check("and returns the operator to the page they started on",
          "consoleReturnTab" in bg and "tabs.reload" in bg)
    check("the Search Console tab is closed behind them",
          "tabs.remove" in bg)
    check("the popup stays as a CORRECTION path",
          "collectDraft" in pop and "data-k=" in pop)
    check("and says so rather than implying it is required",
          "already" in open(os.path.join(root, "extension", "popup.html")).read())
    check("the scrape scrolls, because the exclusion table is below the fold",
          "scrollHeight" in bg and "scrollTo" in bg)
    # WAS: asserted an Enhancements step. `/search-console/enhancements` 404s
    # — Search Console has no single Enhancements page; each type has its own
    # URL and exists only for a site with that markup. Opening a URL that
    # cannot exist cost thirty seconds and a Google 404, which is worse than
    # not trying: it looks like the capture is broken.
    check("no request is made to a Search Console path that cannot exist",
          'scUrl("enhancements"' not in bg)
    # WAS: asserted the wait string "why aren't pages indexed". That phrase is
    # my wording; Google's heading is "Why pages aren't indexed" — same five
    # words, different order — so the poll never matched and burned its full
    # forty seconds on a page that had rendered fine. The assertion passed the
    # whole time because the phrase survived in a comment.
    #
    # The wait anchors on the reason labels now: the strings we came to read.
    check("the read waits for the report, not for a byte count",
          "wantText" in bg and "scOpen(tab.id, scUrl(\"index\", property, auth), "
          "SC_REASONS)" in bg)
    check("and a hand-closed tab is not reported as a crash",
          "No tab with id" in bg and "changing their mind" in bg)
    check("and a partial capture reports the labels it DID see",
          "Labels seen on the page" in bg)

    print("\nTHE AUDIT ID IS NEVER TYPED BY HAND")
    # "Paste the audit id" was asking someone to copy a sixteen-character hex
    # string out of the URL bar of the tab next door — three chances to get it
    # wrong before anything has been measured.
    con = open(os.path.join(root, "extension", "content.js")).read()
    html = open(os.path.join(root, "extension", "popup.html")).read()
    import inspect as _i2
    from engine import report as _rep
    panel_src = _i2.getsource(_rep._todo_panel)
    check("the report page carries the id and the property",
          "vici-console" in con and "gscProperty" in con)
    # WAS: asserted the button stayed hidden until the extension revealed it.
    # Tidy, and useless — someone told the button exists, looking at a page
    # with no button, cannot tell a missing extension from a broken build.
    # It is always visible now; the extension removes the caveat beside it.
    check("the button is always visible, and says what it needs",
          "vici-console-note" in panel_src
          and "Site Scanner extension" in panel_src)
    check("and the extension removes that caveat when it is present",
          "vici-console-note" in con and "note.remove()" in con)
    from engine.report import _todo_panel
    from engine.scoring import load_catalog
    cat = load_catalog("seed/checkpoints.csv")
    F2 = {c: {"status": "Pass", "value": {}, "evidence": "ok",
              "affected_pages": [], "severity": "Low", "recommendation": "",
              "confidence": 1.0, "source": "crawl"} for c in cat}
    for cid in [c for c in cat if c.startswith("GSC-")][:8]:
        F2[cid] = {"status": "Need Access", "value": {},
                   "evidence": "Google publishes this in Search Console.",
                   "affected_pages": [], "severity": "Low",
                   "recommendation": "", "confidence": 0.0,
                   "source": "gsc_ui_only"}
    panel = "".join(_todo_panel(F2, cat, {
        "audit_id": "abc123def456", "gsc_property": "https://example.com/",
        "extras": {"phases_run": {"run_consent": True, "run_aivis": True}}}))
    check("the boundary panel offers the capture",
          "vici-console-go" in panel and "abc123def456" in panel)
    check("carrying the property so nobody is asked for it",
          "https://example.com/" in panel)
    check("and no button at all when there is no audit to attach it to",
          "vici-console-go" not in "".join(_todo_panel(F2, cat, {"extras": {}})))
    # The path appears inside a regex literal, so the slashes are escaped —
    # searching for the plain string finds nothing and says the feature is
    # missing when it is right there.
    _pop = open(os.path.join(root, "extension", "popup.js")).read()
    check("the popup fills the id from the tab it was opened on",
          "audits" in _pop and "chrome.tabs.query" in _pop)
    check("and never overwrites one already typed", "beats a guess" in _pop)
    check("so the field no longer says 'paste from the dashboard'",
          "paste from the dashboard" not in html)

    print("\nTHE RIGHT GOOGLE ACCOUNT, WITHOUT SIGNING OUT OF THE OTHERS")
    # Chrome signs you into several at once and Search Console opens under
    # whichever is default, so a capture run by someone signed in as one
    # account lands on "Oops, you don't have access to this property" even
    # though another account in the same browser can see it fine.
    bg2 = open(os.path.join(root, "extension", "background.js")).read()
    pop2 = open(os.path.join(root, "extension", "popup.js")).read()
    html2 = open(os.path.join(root, "extension", "popup.html")).read()
    check("the report URL carries an authuser", "authuser" in bg2)
    check("built through one helper, so both reports get it",
          bg2.count("scUrl(") >= 3)
    check("an EMAIL, because an index moves when an account is added",
          "index is a position in the sign-in list" in bg2)
    check("the account is a saved setting, not a per-run prompt",
          "googleAccount" in bg2 and "googleAccount" in pop2
          and "googleAccount" in html2)
    check("blank still means the default account",
          'googleAccount: ""' in bg2)

    print("\nAND THE WRONG-ACCOUNT SCREEN IS RECOGNISED")
    # Without this the scrape finds nothing and reports "nothing recognised",
    # which points at the parser when the truth is a sign-in.
    check("Google's denial page is detected",
          "you don't have access to this property" in bg2)
    check("the account it actually used is read off the page",
          "Signed in as" in bg2 and "signed_in_as" in bg2)
    check("and the run stops there rather than reporting an empty capture",
          "cannot see this property" in bg2)

    print("\nA COMPLETE TABLE LICENSES A ZERO; AN INCOMPLETE ONE DOES NOT")
    # Ooten's real capture: 115 not indexed, two recognised rows accounting for
    # 46 of them. Sixty-nine pages sat in rows the scrape never looked at, so
    # "Soft 404" being absent proved nothing at all.
    partial = F({
        "indexed": 56, "not_indexed": 115,
        "reasons": {"Crawled - currently not indexed": 46,
                    "Discovered - currently not indexed": 0}})
    check("a partial read never turns an unseen reason into a Pass",
          partial["GSC-09"]["status"] != "Pass", partial["GSC-09"]["status"])
    check("and it says so with both numbers, not with silence",
          "46 of 115" in partial["GSC-09"]["evidence"],
          partial["GSC-09"]["evidence"][:90])
    check("carrying zero confidence, so scoring leaves it out",
          partial["GSC-09"]["confidence"] == 0.0)
    check("and it is named as ours to fix, not the client's",
          "ours to fix" in partial["GSC-09"]["recommendation"].lower())

    # The same site once the whole vocabulary is read: every excluded page is
    # accounted for, so a reason that is not on the table has none.
    whole = F({
        "indexed": 56, "not_indexed": 115,
        "reasons": {"Crawled - currently not indexed": 46,
                    "Discovered - currently not indexed": 0,
                    "Alternate page with proper canonical tag": 51,
                    "Page with redirect": 18}})
    check("a complete table makes an absent reason a measured zero",
          whole["GSC-09"]["status"] == "Pass", whole["GSC-09"]["status"])
    check("and says what licensed the zero",
          "accounts for all 115" in whole["GSC-09"]["evidence"])
    check("server errors and redirect errors too",
          whole["GSC-10"]["status"] == "Pass"
          and whole["GSC-11"]["status"] == "Pass")
    check("a captured row still beats the inference",
          whole["GSC-07"]["value"]["count"] == 46)

    print("\nAND THE UNMAPPED ROWS ARE NOT THROWN AWAY")
    # Most of a real exclusion table maps to no checkpoint, and that is
    # usually where most of the excluded pages are. Reporting 115 and hiding
    # the breakdown sends the reader back to Search Console for what we read.
    check("the largest reasons are named on the excluded-pages row",
          "Alternate page with proper canonical tag (51)"
          in whole["GSC-06"]["evidence"], whole["GSC-06"]["evidence"][-90:])
    check("and the full breakdown is kept as structured evidence",
          (whole["GSC-06"]["value"].get("reasons") or {}).get(
              "Page with redirect") == 18)

    print("\nTHE WHOLE VOCABULARY IS WHAT THE EXTENSION READS")
    for _label in ("alternate page with proper canonical tag",
                   "page with redirect", "not found (404)",
                   "duplicate without user-selected canonical"):
        check(f"the scrape knows “{_label}”", _label in bg2)
    check("and a curly apostrophe cannot silently miss a row",
          "\\u2018\\u2019" in bg2 or "‘’" in bg2)

    print("\n" + "=" * 68)
    if FAILED:
        print(f"  {len(FAILED)} FAILED: {FAILED}")
    else:
        print("  ALL CHECKS PASSED — the console capture never invents a number")
    print("=" * 68 + "\n")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
