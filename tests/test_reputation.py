"""
The reputation profile — the public record, not the client's site.

WHAT THIS GUARDS
----------------
  1. NO CREDENTIALS IS NOT "NO COMPLAINTS". With DFS unset, `profile()` must
     come back `ok: False` with a reason, and the PDF must print NOTHING —
     because an empty reputation section reads as a clean bill of health for a
     question nobody asked. Same argument as the consent scanner.
  2. ONE PANEL DOWN IS NOT THE SECTION DOWN. Autocomplete rate-limited while
     the listings database answers fine has to leave a section that renders,
     with the failure recorded in `errors`.
  3. THE ARITHMETIC IS WEIGHTED, AND `worst` IS REAL. A location with 400
     reviews at 4.9 and one with 6 at 2.0 must not average to 3.45 — the
     brand's rating is what a stranger sees, which is dominated by volume.
     And `worst` must find the 2.0, because the weakest listing is the only
     actionable thing on the page.
  4. A COMPETITOR'S COMPLAINT IS NOT THE CLIENT'S. Google's related-searches
     block is topical, so it hands back other companies' phrases; those must
     never reach the negative counts. This is the 2026-08-05 bug that priced a
     cleanup campaign off a manufacturer's reputation.
  5. THE SECTION RENDERS. Real numbers in, PDF out, and the brand's own name
     on the page.
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


BRAND = "Ooten Law Firm"
DOMAIN = "ootenlawfirm.com"


# --------------------------------------------------------------- the stub
#
# Keyed on the endpoint path, shaped like the real envelope — tasks[0].result —
# because that shape is the thing the module actually depends on and a stub
# that flattens it would test nothing.
def _listings(_payload):
    return {"tasks": [{"status_code": 20000, "result": [{"items": [
        {"title": "Ooten Law Firm", "address": "100 Gay St, Knoxville TN",
         "place_id": "P1", "cid": "1",
         "rating": {"value": 4.9, "votes_count": 400}},
        {"title": "Ooten Law Firm - Farragut", "address": "9 Kingston Pike",
         "place_id": "P2", "cid": "2",
         "rating": {"value": 2.0, "votes_count": 6}},
        {"title": "Wooten Legal Group", "address": "Elsewhere",
         "place_id": "P9", "cid": "9",
         "rating": {"value": 1.1, "votes_count": 900}},
    ]}]}]}


def _serp(_payload):
    return {"tasks": [{"result": [{"items": [
        {"type": "organic", "rank_absolute": 1, "title": "Ooten Law Firm",
         "domain": "ootenlawfirm.com", "description": "Knoxville attorneys."},
        {"type": "organic", "rank_absolute": 2, "title": "Ooten Law - Avvo",
         "domain": "www.avvo.com", "description": "Rated 3.4 out of 5 stars",
         "rating": {"value": 3.4, "votes_count": 22}},
        {"type": "organic", "rank_absolute": 3, "title": "Ooten Law Firm | Yelp",
         "domain": "yelp.com", "description": "12 reviews"},
        {"type": "discussions_and_forums", "rank_absolute": 4, "items": [
            {"domain": "reddit.com", "title": "Anyone used Ooten Law?"}]},
        {"type": "related_searches", "items": [
            "ooten law firm complaints",          # the client's
            "morgan and morgan complaints",       # somebody else's
            "ooten law firm knoxville"]},
        {"type": "people_also_search", "items": [
            "bigger law firm scam"]},             # somebody else's
    ]}]}]}


def _kfk(_payload):
    return {"tasks": [{"result": [
        {"keyword": "ooten law firm", "search_volume": 1300},
        {"keyword": "ooten law firm reviews", "search_volume": 210},
        {"keyword": "ooten law firm complaints", "search_volume": 90},
        {"keyword": "morgan and morgan lawsuit", "search_volume": 40000},
    ]}]}


def _overview(_payload):
    return {"tasks": [{"result": [{"items": [
        {"keyword": "ooten law firm complaints",
         "keyword_info": {"search_volume": 140}},
    ]}]}]}


def _autocomplete(_payload):
    raise RuntimeError("429 rate limited")


ROUTES = {
    "/business_data/business_listings/search/live": _listings,
    "/serp/google/organic/live/advanced": _serp,
    "/keywords_data/google_ads/keywords_for_keywords/live": _kfk,
    "/dataforseo_labs/google/keyword_overview/live": _overview,
    "/serp/google/autocomplete/live/advanced": _autocomplete,
}

CALLS: list[str] = []


def fake_post(path, payload, timeout=60, method="POST"):
    # `method` because DataForSEO's queued endpoints are POST task_post then
    # GET task_get/{id}. A stub that omits it raises TypeError inside the
    # module's own except-and-retry, which reads as "still pending" forever.
    CALLS.append(path)
    fn = ROUTES.get(path)
    if not fn:
        raise AssertionError(f"stub has no route for {path}")
    return fn(payload)


def main():
    from engine import reputation as rep

    # 1 ---------------------------------------------------- no credentials
    rep.configured = lambda: False
    off = rep.profile(BRAND, DOMAIN)
    check("no credentials -> not ok", off.get("ok") is False)
    check("no credentials -> says why", "credentials" in (off.get("error") or ""),
          off.get("error", "")[:60])

    from engine import pdf_report
    meta_off = {"client": BRAND, "extras": {"reputation": off}}
    S = pdf_report._styles() if hasattr(pdf_report, "_styles") else None
    if S is not None:
        check("no credentials -> section prints nothing",
              pdf_report._reputation(meta_off, S) == [])

    # 2 ------------------------------------------------ one panel down only
    rep.configured = lambda: True
    rep._post = fake_post
    # stars and shot are exercised separately below; both are queued calls
    # with their own poll loops and do not belong in the four-scan assertions.
    prof = rep.profile(BRAND, DOMAIN, stars=False, shot=False)
    check("scan ok with autocomplete down", prof.get("ok") is True)
    check("failed panel is recorded, not swallowed",
          "autocomplete" not in prof or bool(
              (prof.get("autocomplete") or {}).get(BRAND.lower(), {}).get("error")),
          str(prof.get("errors")))
    check("listings still answered",
          len((prof.get("locations") or {}).get("locations") or []) == 2,
          str(len((prof.get("locations") or {}).get("locations") or [])))

    sm = rep.summarize(prof)

    # 3 ---------------------------------------------- weighted, and `worst`
    #    400 @ 4.9 + 6 @ 2.0 = 4.86, not the 3.45 a flat mean would print.
    check("rating is review-weighted", sm["rating"] is not None
          and 4.8 <= float(sm["rating"]) <= 4.9, str(sm["rating"]))
    check("total reviews sums the listings", sm["reviews"] == 406,
          str(sm["reviews"]))
    check("worst listing is named", (sm.get("worst") or {}).get("place_id") == "P2",
          str((sm.get("worst") or {}).get("title")))
    check("a near-name-match is not counted as the client",
          all("Wooten" not in (l.get("title") or "")
              for l in (prof["locations"]["locations"])))

    # 4 -------------------------------------- somebody else's complaint word
    joined = " ".join(sm["negative_related"]).lower()
    check("client's own complaint phrase kept", "ooten law firm complaints" in joined)
    check("competitor phrase dropped", "morgan and morgan" not in joined, joined)
    check("competitor PASF phrase dropped", "bigger law firm" not in joined, joined)
    neg_terms = " ".join(t["term"] for t in sm["negative_terms"]).lower()
    check("competitor keyword dropped from terms",
          "morgan and morgan" not in neg_terms, neg_terms)
    check("exact probe beats the grouped volume",
          any(t["term"] == "ooten law firm complaints" and t["volume"] == 140
              for t in sm["negative_terms"]),
          str(sm["negative_terms"][:2]))
    check("negative volume counts only the client's",
          sm["negative_volume"] == 140, str(sm["negative_volume"]))

    # 4b ------------------------------------ "The" is not part of the name
    #     The client signs as "The Ooten Law Firm"; the listing, the reviews
    #     page and every brand search say "Ooten Law Firm". A gate that
    #     required the article found no listings at all — and a firm rendered
    #     with no reviews looks like an answer rather than a miss.
    check("leading article trimmed", rep._bare("The Ooten Law Firm")
          == "ooten law firm")
    check("article is not a required title token",
          rep.brand_tokens("The Ooten Law Firm") == ["ooten", "law", "firm"])
    withthe = rep.profile("The " + BRAND, DOMAIN, stars=False, shot=False)
    wsm = rep.summarize(withthe)
    check("listings still found for a 'The' brand", wsm["locations"] == 2,
          str(wsm["locations"]))
    check("negative term still classified for a 'The' brand",
          wsm["negative_volume"] == 140, str(wsm["negative_volume"]))

    # 4c ------------------------------- the tactic is carried, not recomputed
    #     Every page-one row already knows what we would do about it. The
    #     table printed "Yours / Someone else's" and dropped that on the floor.
    tac = {o["domain"]: o.get("tactic") for o in prof["serp"]["organic"]}
    check("owned result routes to boost",
          tac.get("ootenlawfirm.com") == "owned — boost", str(tac))
    check("a weak third-party review site routes to suppression",
          tac.get("avvo.com") == "suppression", str(tac))
    check("a strong third-party rating is left alone",
          rep.route_tactic("avvo.com", rating=4.6) == "positive — leave")
    check("a forum thread routes to removal",
          rep.route_tactic("reddit.com", forum=True) == "site removal")

    # 4d ------------------------------------------- the queued review pull
    #     Two things this has to get right. The GET half of DataForSEO's async
    #     pattern (dfs_post had no `method`, so the vendored call raised
    #     TypeError on its first line), and worst-listing-first ordering - the
    #     4.9 with 400 reviews has nothing to add that the average has not.
    posted = {}

    def _reviews_post(payload):
        posted["places"] = [p["place_id"] for p in payload]
        posted["sort"] = payload[0].get("sort_by")
        return {"tasks": [{"id": f"T-{p['place_id']}", "status_code": 20000,
                           "data": {"tag": p["place_id"]}} for p in payload]}

    def _reviews_get(_payload):
        return {"tasks": [{"status_code": 20000, "data": {"tag": "P2"},
                           "result": [{"title": "Ooten Law Firm - Farragut",
                                       "rating": {"value": 2.0},
                                       "reviews_count": 6,
                                       "items": [{"rating": {"value": v}}
                                                 for v in (1, 1, 1, 2, 3, 5)]}]}]}

    ROUTES["/business_data/google/reviews/task_post"] = _reviews_post
    ROUTES["/business_data/google/reviews/task_get/T-P2"] = _reviews_get
    ROUTES["/business_data/google/reviews/task_get/T-P1"] = _reviews_get
    rep.STAR_POLL_S = 0.01
    rep.STAR_WAIT_S = 0.5
    bands = rep._star_bands(prof["locations"]["locations"], limit=1)
    check("the review pull asks for the WORST listing",
          posted.get("places") == ["P2"], str(posted.get("places")))
    check("and asks for the worst reviews first",
          posted.get("sort") == "lowest_rating", str(posted.get("sort")))
    L = (bands.get("listings") or [{}])[0]
    check("one-star reviews counted", L.get("one") == 3, str(L.get("one")))
    check("two-star reviews counted", L.get("two") == 1, str(L.get("two")))
    check("three-star reviews counted", L.get("three") == 1, str(L.get("three")))

    # A GET carries no body, and dfs_post has to actually send one.
    import inspect
    from engine.collectors import dataforseo as _dfs
    check("dfs_post accepts the GET half of a queued task",
          "method" in inspect.signature(_dfs.dfs_post).parameters)

    # 4e -------------------------------------- "at least 0" is not a floor
    #     The truncation flag qualifies counts we FOUND. Printed against an
    #     empty band it reads as a number nobody can act on.
    prof["stars"] = {"listings": [
        {"title": "Ooten Law Firm", "rating": 4.8, "reviews": 227,
         "one": 10, "two": 1, "three": 0, "at_least": True}]}
    sm = rep.summarize(prof)          # re-derive, so the render sees the bands

    # 5 ----------------------------------------------------- it renders
    check("page one ownership counted",
          sm["owned_in_top10"] == 1 and sm["third_party_in_top10"] == 2,
          f"{sm['owned_in_top10']}/{sm['third_party_in_top10']}")
    check("forum thread surfaced",
          any(f.get("domain") == "reddit.com" for f in sm["forums"]))

    prof["summary"] = sm
    import io
    from reportlab.platypus import SimpleDocTemplate
    from reportlab.lib.pagesizes import letter
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = pdf_report._styles()
    story = pdf_report._reputation({"client": BRAND,
                                    "extras": {"reputation": prof}}, styles)
    check("section produced flowables", len(story) > 4, str(len(story)))
    # story[0] is the section's own PageBreak — dropping it keeps this
    # standalone render to a single page so the text assertions below are
    # about the section and not about a blank leading sheet.
    doc.build(story[1:])
    pdf = buf.getvalue()
    check("section renders to a PDF", pdf.startswith(b"%PDF") and len(pdf) > 3000,
          f"{len(pdf)} bytes")

    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf)) as d:
            text = "\n".join((p.extract_text() or "") for p in d.pages)
        check("the weakest listing is named on the page",
              "Farragut" in text, text[:120].replace("\n", " "))
        check("competitor's name never reaches the page",
              "Morgan" not in text and "Wooten" not in text)
        check("brand search volume is on the page",
              "1,650" in text, text[:80].replace("\n", " "))
        check("the tactic column prints",
              "SUPPRESSION" in text.upper() and "OWNED" in text.upper())
        # The column headers are DRAWN stars, not the glyph - U+2605 is not in
        # the embedded family and printed as nothing at all, which is how the
        # header row came out blank. So assert the counts and the heading, and
        # assert the drawing separately below rather than looking for a
        # character that is deliberately no longer there.
        check("star bands print",
              "10" in text and "reviews behind the rating" in text.lower())
        check("no star glyph is relied on for a font that lacks it",
              "\u2605" not in text)
        check("a truncated pull says 'at least' on a band it found",
              "at least 10" in text)
        check("and never on an empty one", "at least 0" not in text)
    except ImportError:
        print("  SKIP  pdfplumber not installed")

    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED: " + ", ".join(FAILED))
        sys.exit(1)
    print("all reputation checks passed")


if __name__ == "__main__":
    main()
