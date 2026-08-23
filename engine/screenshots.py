"""
Annotated evidence screenshots.

The simplest thing that actually works: open the page in the browser we already
ship, draw an outline around the offending elements with CSS, screenshot the
viewport. No image library, no compositing, no second service — the annotation
is done by the browser before the picture is taken.

Deliberately NOT doing element-level boxes for all 313 checks. Most findings
are about something with no single element to point at (a missing sitemap, a
redirect, a header), and a screenshot of a page with nothing highlighted is
worse than no screenshot. So there is a small map of the checks where a box is
genuinely informative, and everything else is skipped rather than illustrated
with a picture of a normal-looking page.

Bounded on purpose: three shots, ten seconds each, and any failure returns None.
Evidence is a nice-to-have; it must never be the reason an audit does not
finish.
"""
from __future__ import annotations
import os

# checkpoint id -> CSS selector for the thing that is wrong.
# Only checks where a box points at something a human would recognise.
#
# THIS MAP HAD DRIFTED FROM THE CATALOG, WHICH IS WHY NO RED BOX EVER APPEARED.
#
# It listed ONP-30 and ONP-31 as "images missing alt text". In the catalog
# ONP-30 is "Proper length" (meta descriptions) and ONP-31 is "Pages don't have
# an H1 heading"; the alt-text row is ONP-14. So the two ids most likely to
# fail on a real site pointed at selectors for a different check, and the
# checks that DID fail fell through to the page-level list, which produces an
# unboxed shot - and the report only prints boxed ones. Every id below is now
# checked against seed/checkpoints.csv.
SELECTORS = {
    "ONP-08": "h1",                                   # more than one H1
    "ONP-14": "img:not([alt]), img[alt='']",          # images missing alt text
    "ONP-17": "a:empty",                              # links with no anchor text
    "ONP-32": "h1",                                   # one H1 per page
    "ONP-33": "h2, h3, h4",                           # heading hierarchy
    "ONP-42": "img",                                  # image filenames
    "ONP-44": "img:not([srcset])",                    # responsive images
    "ONP-45": "img:not([loading])",                   # no lazy loading
    "PERF-19": "img",                                 # unoptimised images
    "MOB-05": "a, button",                            # tap targets
    "MOB-06": "p",                                    # font readability
    # NOT JUST <footer>. Plenty of themes ship a <div class="site-footer">,
    # and a selector that matches nothing now means no shot at all - so the
    # narrow version quietly cost these two checks their evidence.
    "EEAT-05": "footer, [class*=footer], [id*=footer]",   # trust signals
    "EEAT-06": "footer, [class*=footer], [id*=footer]",
}

# Checks worth a plain page shot even with no element to box.
PAGE_LEVEL = {"SEC-01", "SEC-08", "URL-06", "URL-16", "ONP-01", "ONP-23",
              "SCHEMA-01", "SCHEMA-02", "GEO-04", "PERF-10"}


def available() -> bool:
    if os.getenv("SKIP_SCREENSHOTS", "").lower() in ("1", "true", "yes"):
        return False
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def capture(url: str, selector: str = "", width: int = 1280, height: int = 820,
            timeout_ms: int = 10000) -> bytes | None:
    """
    One annotated viewport screenshot, or None.

    The outline is injected as a stylesheet rather than drawn afterwards, so
    the browser handles every layout case — elements inside scrolled
    containers, transformed elements, elements that move on load — which is
    the part that would be genuinely hard to do with an image library.
    """
    if not available():
        return None
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    png = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox"])
            try:
                page = browser.new_page(viewport={"width": width, "height": height})
                page.set_default_timeout(timeout_ms)
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass          # a chatty page should not cost us the shot
                if selector:
                    # NO MATCH MEANS NO SHOT.
                    #
                    # The report captions these "with anything the check
                    # flagged marked in red". When the selector matches
                    # nothing - "footer" on a site whose footer is a <div> -
                    # the stylesheet styles nothing, the page is captured
                    # anyway, and the client gets an unmarked picture of their
                    # own homepage under a promise of red outlines. That is
                    # the caption lying, and the honest answer is to have no
                    # picture for that check.
                    try:
                        n = page.locator(selector).count()
                    except Exception:  # noqa: BLE001
                        n = 0
                    if not n:
                        print(f"[screenshot] {url}: selector {selector!r} "
                              f"matched nothing — no evidence shot",
                              flush=True)
                        return None
                    page.add_style_tag(content=(
                        f"{selector} {{ outline: 3px solid #d03b3b !important; "
                        f"outline-offset: 2px !important; }}"))
                    try:
                        page.locator(selector).first.scroll_into_view_if_needed(
                            timeout=2500)
                        page.wait_for_timeout(250)
                    except Exception:
                        pass      # highlighted but not scrolled to is still useful
                png = page.screenshot(type="png")
            finally:
                browser.close()
    except Exception as e:
        print(f"[screenshot] {url}: {type(e).__name__}: {e}", flush=True)
        return None
    return png


def pick_targets(findings: dict, catalog: dict, start_url: str, limit: int = 3):
    """
    [(checkpoint_id, url, selector, caption)] worth photographing.

    Ordered by the scoring engine's own priority, so the evidence matches the
    findings the client is being asked to read.
    """
    from .scoring import top_issues
    ranked = top_issues(findings, catalog, 30)

    # BOXED SHOTS FIRST, ALWAYS.
    #
    # A single pass in priority order filled all three slots with page-level
    # checks - a title-tag problem, a schema problem, an HTTPS problem - none
    # of which has anything on the page to outline. The report only prints
    # shots with a mark on them, so the section vanished and the client asked
    # where the red outlines were.
    #
    # Priority still decides the order WITHIN each group; what changes is that
    # a check with something to point at never loses its slot to one without.
    def scan(want_boxed):
        for cid, f in ranked:
            if len(out) >= limit:
                return
            sel = SELECTORS.get(cid)
            if want_boxed and not sel:
                continue
            if not want_boxed and (sel or cid not in PAGE_LEVEL):
                continue
            pages = [p for p in (f.get("affected_pages") or [])
                     if str(p).startswith("http")]
            url = pages[0] if pages else start_url
            if (cid, url) in seen or url in {u for _c, u in seen}:
                continue
            seen.add((cid, url))
            name = (catalog.get(cid, {}) or {}).get("checkpoint", cid)
            out.append((cid, url, sel or "", f"{name} — {url}"))

    out, seen = [], set()
    scan(True)
    scan(False)
    return out
