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
                    # THE FIRST MATCH IS NOT ALWAYS A VISIBLE ONE.
                    #
                    # A hidden mobile nav, a print-only footer, an element
                    # with zero height - `.first` finds them, scrolling to
                    # them does nothing, and the capture comes back as the top
                    # of the page with no red on it. Which is exactly what
                    # shipped: a homepage hero under a caption promising an
                    # outline. Pick the first match that is actually on the
                    # page and has a box.
                    target = None
                    try:
                        loc = page.locator(selector)
                        for i in range(min(loc.count(), 12)):
                            el = loc.nth(i)
                            if not el.is_visible():
                                continue
                            box = el.bounding_box()
                            if box and box["width"] > 8 and box["height"] > 8:
                                target = el
                                break
                    except Exception:  # noqa: BLE001
                        target = None
                    if target is None:
                        print(f"[screenshot] {url}: selector {selector!r} "
                              f"matched nothing visible — no evidence shot",
                              flush=True)
                        return None
                    page.add_style_tag(content=(
                        f"{selector} {{ outline: 3px solid #d03b3b !important; "
                        f"outline-offset: 2px !important; }}"))
                    try:
                        target.scroll_into_view_if_needed(timeout=2500)
                        page.wait_for_timeout(200)
                        # A LITTLE HEADROOM, BUT ONLY WHERE THERE IS ROOM.
                        #
                        # A flat scrollBy pushed the element straight back out
                        # of frame whenever the browser had aligned it to the
                        # BOTTOM edge, which is what it does for anything near
                        # the end of a long page - the footer, every time.
                        # Nudge only when the element is jammed against the
                        # top, and only by what fits above it.
                        top = target.evaluate(
                            "e => e.getBoundingClientRect().top")
                        if top < 60:
                            page.evaluate(
                                "n => window.scrollBy(0, -n)",
                                min(160, max(0, 60 - top) + 100))
                            page.wait_for_timeout(200)
                    except Exception:
                        pass      # highlighted but not scrolled to is still useful
                    # AND PROVE THE MARK IS IN FRAME.
                    #
                    # A sticky header, a scroll-locked body, a modal - any of
                    # them can swallow the scroll silently. If the outlined
                    # element is not inside the viewport after all that, the
                    # picture would show no red, and no picture is the honest
                    # answer.
                    try:
                        # getBoundingClientRect, NOT bounding_box(). The
                        # Playwright box is page-relative here, so comparing
                        # it to the viewport height rejected every element
                        # below the fold - including the footer, which is the
                        # one this was written for. The DOM rectangle is
                        # viewport-relative by definition.
                        rect = target.evaluate(
                            "e => {const r = e.getBoundingClientRect();"
                            " return {top: r.top, bottom: r.bottom};}")
                        if rect["top"] > height - 40 or rect["bottom"] < 40:
                            print(f"[screenshot] {url}: {selector!r} would not "
                                  f"stay in frame — no evidence shot",
                                  flush=True)
                            return None
                    except Exception:  # noqa: BLE001
                        pass
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
