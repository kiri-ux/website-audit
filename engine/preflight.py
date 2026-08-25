"""
One request, before the crawl, to decide two things nobody can know in advance.

WHY THIS EXISTS
---------------
"Browser user-agent — if the site blocks bots" and "Render JavaScript — for SPA
sites" were checkboxes on the run form. Both ask the operator to predict
something about a site they have not crawled yet, and getting either one wrong
is expensive in a way that does not announce itself:

  * UA too honest on a WAF-protected site -> every path answers with a
    challenge page, and the checks report a site that is broken rather than a
    crawl that was blocked.
  * JS rendering off on a client-side app -> 118 pages of empty shell, scored
    as 118 pages with no content.
  * JS rendering on when it was not needed -> a browser per page, minutes of
    wall clock, and memory on a 2GB instance for nothing.

The crawler already DIAGNOSES both conditions after the fact — `CrawlQuality`
separates "bot protection" from "client-side rendering" and says so. It just
never acted on it, because by then the crawl was over.

So: fetch the homepage, look at what came back, and escalate only on evidence.
Costs one request, or two when it escalates.

WHAT IT WILL NOT DO
-------------------
It will not decide silently. Every escalation returns the reason that triggered
it, and the worker records that on the audit — a run that quietly switched to a
browser user-agent and a run where someone ticked the box are different facts
about the client's site, and six months from now nobody will remember which.

It never escalates on a network error. A site that is down is not a site that
blocks bots, and pretending otherwise sends someone to fix the wrong thing.
"""
from __future__ import annotations

import urllib.error
import urllib.request

from .crawler import USER_AGENT

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 "
              "Safari/537.36")

# Statuses a bot gets and a browser often does not. 401 is deliberately absent:
# that is real authentication, and a different user-agent does not fix it.
BLOCK_STATUS = (403, 406, 429, 503)

# The words these pages actually print. Same list the crawler's own quality
# assessment uses, kept here so a challenge that returns HTTP 200 — which is
# most of them — is still recognized.
CHALLENGE = ("just a moment", "enable javascript", "checking your browser",
             "access denied", "captcha", "cloudflare", "are you a robot",
             "unusual traffic", "request unsuccessful", "attention required",
             "ddos protection", "verifying you are human")

# Markers of an app that renders itself. Presence alone proves nothing — plenty
# of server-rendered sites ship React — so these only count when the page also
# has almost no text.
SPA_MARKERS = ('id="root"', "id='root'", 'id="app"', "id='app'",
               "__next_data__", "ng-app", "ng-version", "data-reactroot",
               "window.__nuxt__", "window.__initial_state__")

# Below this, a homepage is not a homepage. A real one has navigation, a
# heading and a paragraph; 40 words is a cookie notice and a spinner.
THIN_WORDS = 40


def _get(url: str, ua: str, timeout: int = 15):
    """(status, body, error). Never raises — a dead site is an answer."""
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(400_000).decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        try:
            body = (e.read() or b"").decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = ""
        return e.code, body, None
    except Exception as exc:  # noqa: BLE001
        return None, "", f"{type(exc).__name__}: {exc}"


def _text_words(html: str) -> int:
    """Rough visible-word count, with script and style stripped."""
    import re
    s = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return len([w for w in s.split() if len(w) > 1])


def _blocked(status, html) -> str:
    """Why this looks like bot protection, or ''."""
    low = (html or "").lower()
    hit = next((w for w in CHALLENGE if w in low), "")
    if hit:
        return f"the page says “{hit}”, which is a bot-protection screen"
    if status in BLOCK_STATUS:
        return f"the server answered HTTP {status} to our crawler"
    return ""


def _needs_js(html) -> str:
    """Why this looks client-rendered, or ''."""
    low = (html or "").lower()
    words = _text_words(html)
    if words >= THIN_WORDS:
        return ""
    marker = next((m for m in SPA_MARKERS if m in low), "")
    if marker:
        return (f"the homepage has {words} words of text and a "
                f"“{marker}” mount point, so the content is built "
                f"by JavaScript")
    if len(low) < 4096 and low.count("<script") >= 2:
        return (f"the homepage is {len(html):,} bytes with {words} words of "
                f"text and several scripts, which is a shell rather than a "
                f"page")
    return ""


def decide(url: str, timeout: int = 15) -> dict:
    """
    Look at the homepage and say what the crawl needs.

    Returns {"user_agent": str|None, "render_js": bool, "why": [str],
             "checked": bool, "error": str|None}.

    `checked` is False when the probe itself could not run. The caller must
    treat that as "decide nothing" rather than "nothing needed" — an
    unreachable homepage is exactly the case where guessing does harm.
    """
    out = {"user_agent": None, "render_js": False, "why": [],
           "checked": False, "error": None}

    status, html, err = _get(url, USER_AGENT, timeout)
    if err:
        # NOT AN ESCALATION. A site that is down is not a site that blocks
        # bots, and switching user-agent because of a DNS failure sends
        # someone to argue with a client about their WAF.
        out["error"] = err
        return out
    out["checked"] = True

    why = _blocked(status, html)
    if why:
        b_status, b_html, b_err = _get(url, BROWSER_UA, timeout)
        # Only adopt it if it actually helped. A site that blocks both is not
        # fixed by pretending to be Chrome, and claiming otherwise buries the
        # real finding (the crawl was blocked) under a setting that did
        # nothing.
        if not b_err and not _blocked(b_status, b_html) and (b_status or 0) < 400:
            out["user_agent"] = BROWSER_UA
            out["why"].append(f"Using a browser user-agent: {why}, and the "
                              f"same request as a browser returned the page.")
            html, status = b_html, b_status
        else:
            out["why"].append(f"Bot protection detected — {why} — and a "
                              f"browser user-agent did not get past it either. "
                              f"The crawl will report being blocked rather than "
                              f"pretending the site is broken.")

    js = _needs_js(html)
    if js:
        out["render_js"] = True
        out["why"].append(f"Rendering JavaScript: {js}.")
    return out
