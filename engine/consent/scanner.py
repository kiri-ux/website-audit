"""
Consent Scanner core.

Two tiers:
  basic  - plain HTTP fetch + signature matching on the raw HTML.
           Fast, no browser. Catches CMPs loaded via a direct <script> tag.
  full   - headless Chromium via Playwright. Adds: JS-global + cookie
           detection (catches CMPs injected by GTM/plugins), banner
           visibility, Google Consent Mode default detection, and
           pre-consent tracker network capture.

scan_site() attempts full mode and degrades to basic if Playwright or
Chromium is unavailable, so the app runs anywhere.
"""

import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

# Every challenge hit re-arms the host's IP-reputation timer, so retry
# sparingly: one patient attempt beats several impatient ones.
CHALLENGE_RETRIES = 2
CHALLENGE_WAIT_MS = 20000

SCANNER_REV = "0.15.58"
print(f"[scanner] rev {SCANNER_REV} loaded", flush=True)

from .state_checks import (STATE_CHECKS, OPTOUT_LINK_PHRASES,
                          LAST_REVIEWED, REVIEW_INTERVAL_DAYS)
from .signatures import (CMP_SIGNATURES, TRACKER_ENDPOINTS, PRODUCT_PIXELS, CODE_HINTS,
                        ACCEPT_SELECTORS, GENERIC_ACCEPT_TEXT,
                        STRICT_ACCEPT_TEXT, REJECT_SELECTORS,
                        STRICT_REJECT_TEXT)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

GTM_ID_RE = re.compile(r"GTM-[A-Z0-9]{4,}")
# gtag.js is served from googletagmanager.com but is NOT a Tag Manager
# container - a site running only GA4 or Google Ads trips a bare
# "googletagmanager.com" check while having no container at all.
GTM_CONTAINER_RE = re.compile(r"googletagmanager\.com/(?:gtm\.js|ns\.html)", re.I)
GTAG_LOADER_RE = re.compile(r"googletagmanager\.com/gtag/js", re.I)
GTAG_ID_RE = re.compile(r"\b(?:G-[A-Z0-9]{6,}|AW-\d{6,}|DC-\d{6,})\b")


def _gtm_info(corpus):
    """Separate a real GTM container from a bare gtag.js install."""
    gtm_ids = sorted(set(GTM_ID_RE.findall(corpus)))
    has_container = bool(gtm_ids) or bool(GTM_CONTAINER_RE.search(corpus))
    gtag_ids = sorted(set(GTAG_ID_RE.findall(corpus)))
    has_gtag = bool(gtag_ids) or bool(GTAG_LOADER_RE.search(corpus))
    return {"found": has_container, "container_ids": gtm_ids,
            "gtag_only": (not has_container) and has_gtag,
            "gtag_ids": gtag_ids}
REQUEST_TIMEOUT = 15
PAGE_TIMEOUT_MS = 30000
SETTLE_SECONDS = 2.0
NETIDLE_PRE_MS = 4000
NETIDLE_POST_MS = 3000


# ---------------------------------------------------------------- helpers

def normalize_url(raw):
    url = (raw or "").strip()
    if not url:
        return None
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host or ("." not in host and host != "localhost"):
        return None
    return url


def _match_domains(haystack):
    """Return {cmp_name: [matched fingerprint strings]} found in text."""
    hits = {}
    low = haystack.lower()
    for cmp in CMP_SIGNATURES:
        matched = [d for d in cmp["domains"] if d.lower() in low]
        if matched:
            hits[cmp["name"]] = matched
    return hits


def _cmp_by_name(name):
    return next((c for c in CMP_SIGNATURES if c["name"] == name), None)


def _classify_tracker(url):
    for t in TRACKER_ENDPOINTS:
        if any(p in url for p in t["patterns"]):
            return t
    return None


def _try_accept(page, cmp_names, wait_seconds=4):
    """Click the banner's Accept control. Returns click timestamp or None."""
    selectors = [sel for name in cmp_names
                 for sel in ACCEPT_SELECTORS.get(name, [])]
    return _try_click(page, selectors,
                      re.compile(GENERIC_ACCEPT_TEXT, re.I),
                      re.compile(STRICT_ACCEPT_TEXT, re.I), wait_seconds)


def _try_reject(page, cmp_names, wait_seconds=4):
    """Click the banner's Reject/Decline control. Loose pass uses the
    STRICT pattern too - reject wording is where a sloppy match could
    click the wrong thing, so both passes stay anchored."""
    selectors = [sel for name in cmp_names
                 for sel in REJECT_SELECTORS.get(name, [])]
    strict = re.compile(STRICT_REJECT_TEXT, re.I)
    return _try_click(page, selectors, strict, strict, wait_seconds)


def _try_click(page, selectors, loose, strict, wait_seconds=4):
    """Shared click machinery: CMP-specific selectors retried for up to
    `wait_seconds` across EVERY frame (iframe banners), then visible
    <button>s matching `loose`, then links/[role=button] matching
    `strict`. Playwright selectors pierce open shadow DOM natively.
    Returns the click timestamp, or None."""
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        for frame in page.frames:
            for sel in selectors:
                try:
                    el = frame.query_selector(sel)
                    if el and el.is_visible():
                        t = time.time()
                        el.click(timeout=2000)
                        return t
                except Exception:
                    pass
        try:
            page.wait_for_timeout(500)  # services route callbacks
        except Exception:
            time.sleep(0.5)

    for pattern, css in ((loose, "button"),
                         (strict, "a, [role='button'], input[type='button'], "
                                  "input[type='submit']")):
        for frame in page.frames:
            try:
                loc = frame.locator(css).filter(has_text=pattern)
                for i in range(min(loc.count(), 8)):
                    item = loc.nth(i)
                    try:
                        txt = (item.inner_text(timeout=500) or "").strip()
                        if len(txt) > 40 or not item.is_visible():
                            continue
                        if pattern is strict and not strict.search(txt):
                            continue
                        t = time.time()
                        item.click(timeout=2000)
                        return t
                    except Exception:
                        continue
            except Exception:
                continue
    return None


def _gcs_denied(url):
    """True if a Google request carries a Consent Mode gcs= param in a
    denied/partial state (i.e. it's a cookieless modeling ping)."""
    try:
        qs = parse_qs(urlparse(url).query)
        gcs = (qs.get("gcs") or [""])[0]
        return bool(gcs) and gcs != "G111"
    except Exception:
        return False


def _consent_signalled(url):
    """
    Does this request carry a Consent Mode state at all?

    `gcs=` was the only parameter this file knew about, and current GA4 sends
    `gcd=` instead on a great many properties — so every Consent Mode ping
    from those sites fell through to "verify state in GTM Preview", and a
    correctly configured client got eight amber rows about behavior that was
    exactly right.

    Presence only. The two encodings are not decoded here, on purpose: `gcs`
    is documented and `gcd` is not, and inventing a decoder for the second one
    would be guessing about consent state in the section of the report where
    guessing is least acceptable. Presence is enough when paired with the
    declared defaults below — that pairing is what makes the call safe.
    """
    try:
        qs = parse_qs(urlparse(url).query)
    except Exception:  # noqa: BLE001
        return False
    return bool((qs.get("gcs") or [""])[0] or (qs.get("gcd") or [""])[0])


# security_storage is granted on every site by design — it covers CSRF tokens
# and the like, not tracking — so it must never count against "all denied".
_NON_TRACKING_STORAGE = {"security_storage", "functionality_storage"}


def _defaults_all_denied(defaults):
    """
    Is every tracking-relevant Consent Mode default set to denied?

    THIS IS THE HALF WE CAN READ WITH CERTAINTY. The defaults come from the
    dataLayer, before any tag ran; if all of them are denied then the first
    request a Google tag makes is a cookieless ping by construction. That is
    not an inference about the encoding of a URL parameter, it is what
    "default denied" means.
    """
    d = {k: str(v).lower() for k, v in (defaults or {}).items()}
    track = {k: v for k, v in d.items() if k not in _NON_TRACKING_STORAGE}
    return bool(track) and all(v == "denied" for v in track.values())


_MACRO_RE = re.compile(r"(\$%7B|\$\{|%5B[A-Za-z_]|\[[A-Za-z_][A-Za-z0-9_ -]*\])")


def _empty_result(url):
    return {
        "url": url,
        "scanned_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": "basic",
        "ok": False,
        "error": None,
        "cmps": [],                 # [{name, evidence[], gtm_event, notes}]
        "gtm": {"found": False, "container_ids": []},
        "banner_visible": "unknown",       # true / false / "unknown"
        "consent_mode_default": "unknown", # true / false / "unknown"
        "consent_defaults": {},            # e.g. {"ad_storage": "denied"}
        "pre_consent": [],          # [{vendor, url, severity, note}]
        "accept_clicked": False,    # did the scan simulate clicking Accept
        "reject_tested": False,     # did the scan click Reject on a fresh load
        "post_reject": [],          # trackers that fired AFTER Reject
        "states": [],               # state targets requested for this scan
        "gpc_tested": False,        # did a GPC-signal page load run
        "gpc_fires": [],            # ad trackers contacted despite GPC
        "optout_link": None,        # matched opt-out link text, or None
        "state_checks": [],         # [{state, check, status, detail}]
        "check_map_reviewed": LAST_REVIEWED,
        "post_consent": [],         # tracker vendors that fired only after accept
        "products": [],             # [{product, expected, fired, pixels:[...]}]
        "verdict": None,
        "verdict_detail": None,
    }


# ---------------------------------------------------------------- tier 1

def basic_scan(url, result=None):
    result = result or _empty_result(url)
    try:
        resp = requests.get(url, headers={"User-Agent": UA},
                            timeout=REQUEST_TIMEOUT, allow_redirects=True)
        html = resp.text or ""
    except requests.RequestException as e:
        result["error"] = f"Could not fetch site: {e.__class__.__name__}"
        return result

    result["ok"] = True
    soup = BeautifulSoup(html, "html.parser")

    # Collect script srcs + link hrefs + inline script text, then the raw
    # HTML as a catch-all (covers CMS plugin asset paths).
    corpus_parts = []
    for tag in soup.find_all(["script", "link", "iframe"]):
        for attr in ("src", "href"):
            if tag.get(attr):
                corpus_parts.append(tag[attr])
        if tag.name == "script" and tag.string:
            corpus_parts.append(tag.string[:5000])
    corpus = "\n".join(corpus_parts) + "\n" + html[:200000]

    for name, evidence in _match_domains(corpus).items():
        sig = _cmp_by_name(name)
        result["cmps"].append({
            "name": name,
            "evidence": [f"script/domain: {e}" for e in evidence],
            "gtm_event": sig["gtm_event"],
            "notes": sig["notes"],
        })

    result["gtm"] = _gtm_info(html)
    return result


# ---------------------------------------------------------------- tier 2

# script hosts a hardcoded snippet would reference in raw HTML, per
# vendor family (beacon endpoints often differ from the include host)
# A notice-only bar carries an accept/OK button but no reject or
# preferences control, so it delivers no opt-out. Named here because
# the state opt-out check must not count it as "a CMP exists".
NOTICE_ONLY_CMP = "Notice-only banner"


_SCRIPT_MARKERS = {
    "Meta Pixel": ["connect.facebook.net", "fbq("],
    "Google Analytics 4": ["gtag/js?id=", "gtag('config'", 'gtag("config"'],
    "Google Ads": ["gtag/js?id=aw-", "googleadservices.com/pagead/conversion"],
    "TikTok Pixel": ["analytics.tiktok.com", "ttq.load"],
    "Snapchat Pixel": ["sc-static.net", "snaptr("],
    "LinkedIn Insight": ["snap.licdn.com", "_linkedin_partner_id"],
    "Pinterest Tag": ["s.pinimg.com/ct", "pintrk("],
    "Amazon Ad Tag": ["c.amazon-adsystem.com", "amzn("],
}


def _pixel_source(vendor, req_url, low_html):
    """'page' when the vendor's snippet/host is in the raw HTML
    (hardcoded), 'runtime' when it fired but left no trace in source
    (injected - by GTM when one is present)."""
    try:
        from urllib.parse import urlparse
        host = urlparse(req_url).netloc.lower()
        if host and host in low_html:
            return "page"
        for m in _SCRIPT_MARKERS.get(vendor, []):
            if m in low_html:
                return "page"
    except Exception:
        return None
    return "runtime"


CHALLENGE_URL_HINTS = ("/.well-known/sgcaptcha/", "/cdn-cgi/challenge",
                       "__cf_chl", "/challenge-platform/")
CHALLENGE_TITLE_HINTS = ("robot challenge", "just a moment",
                         "checking your browser", "attention required",
                         "one moment, please", "verifying you are human")


def _looks_challenged(page):
    """Bot-protection interstitial (SiteGround sgcaptcha, Cloudflare, etc).
    These answer 200/202 with a real-sized document, so status alone
    never catches them."""
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    return (any(h in url for h in CHALLENGE_URL_HINTS)
            or any(h in title for h in CHALLENGE_TITLE_HINTS))


def _container_corpora(container_ids, limit=3):
    """Published gtm.js for each container, keyed by container ID.

    These used to be concatenated into one blob, which could answer
    "configured somewhere" but not "configured where". Keeping them
    separate is what lets a pixel name the container it lives in.
    A fetch miss is dropped rather than recorded as empty - absence of
    evidence here is not evidence of absence.
    """
    import urllib.request
    out = {}
    for cid in (container_ids or [])[:limit]:
        try:
            req = urllib.request.Request(
                f"https://www.googletagmanager.com/gtm.js?id={cid}",
                headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                out[cid] = resp.read(2_000_000).decode(
                    "utf-8", "replace").lower()
        except Exception:
            pass  # container fetch is best-effort evidence only
    return out


def _containers_with(hints, corpora):
    """Container IDs whose published JS carries any of these fingerprints.

    This proves the tag is CONFIGURED in that container, not that this
    particular request came from it - two containers holding the same
    vendor tag both match and neither can be ruled out. Definitive
    attribution needs the CDP initiator chain.
    """
    low = [h.lower() for h in hints if h]
    return sorted(cid for cid, js in corpora.items()
                  if any(h in js for h in low))


def _vendor_hints(vendor):
    """Fingerprints for a tracker vendor: its beacon endpoints, the
    script hosts a hardcoded snippet would reference, and any extra
    code hints. Same evidence basis the product pixels use."""
    hints = []
    for t in TRACKER_ENDPOINTS:
        if t.get("vendor") == vendor:
            hints += list(t.get("patterns") or [])
    hints += _SCRIPT_MARKERS.get(vendor, [])
    hints += CODE_HINTS.get(vendor, [])
    return hints


def _generic_banner_probe(page):
    """Anchored element with consent text + accept/reject button, and
    IAB API presence. Used when no CMP signature matches, and as a
    visibility fallback when a known CMP's selectors miss its DOM."""
    try:
        return page.evaluate("""() => {
          const out = {banner: false, tcf: !!window.__tcfapi,
                       usp: !!window.__uspapi, gpp: !!window.__gpp};
          const acceptRe = /^\\s*(accept|agree|allow|got it|ok(ay)?)/i;
          const rejectRe = /^\\s*(reject|decline|deny|refuse|do not sell|manage (choices|preferences|cookies)|cookie settings|preferences|customize)/i;
          const txtRe = /(cookie|consent|privacy choices|personal information|tracking technologies)/i;
          for (const el of document.querySelectorAll('div,section,aside,dialog,footer')) {
            let st; try { st = getComputedStyle(el); } catch(e){ continue; }
            const anchored = st.position === 'fixed' || st.position === 'sticky' ||
                             el.getAttribute('role') === 'dialog' || el.tagName === 'DIALOG';
            if (!anchored) continue;
            const txt = (el.innerText || '').slice(0, 4000);
            if (!txtRe.test(txt)) continue;
            const btns = el.querySelectorAll('button, a[role=button], input[type=button], input[type=submit]');
            let acc = false, rej = false;
            for (const b of btns) {
              const t = (b.innerText || b.value || '').trim();
              if (acceptRe.test(t)) acc = true;
              if (rejectRe.test(t)) rej = true;
            }
            if (acc || rej) { out.banner = true; out.has_choice = rej; return out; }
          }
          return out;
        }""")
    except Exception:
        return None


def _full_scan_impl(browser, url, products=None, states=None,
                    site_checks=True):
    result = _empty_result(url)
    result["mode"] = "full"
    requests_seen = []  # (timestamp, url)

    if True:  # preserve indentation of the original with-block
        context = browser.new_context(user_agent=UA, locale="en-US",
                                      viewport={"width": 1366, "height": 900})
        page = context.new_page()
        page.on("request",
                lambda req: requests_seen.append((time.time(), req.url)))

        def _route(route):
            # Skip downloading heavy assets for speed. Scripts, XHR, and
            # stylesheets still load (CMPs and tags need them); aborted
            # requests are already captured by the request listener above.
            # Exception: on a bot-challenge URL nothing is skipped - the
            # screen may need its own assets to complete.
            try:
                on_challenge = any(h in (page.url or "").lower()
                                   for h in CHALLENGE_URL_HINTS)
            except Exception:
                on_challenge = False
            if (not on_challenge
                    and route.request.resource_type in ("image", "media", "font")):
                route.abort()
            else:
                route.continue_()
        page.route("**/*", _route)

        try:
            _nav_resp = page.goto(url, wait_until="domcontentloaded",
                      timeout=PAGE_TIMEOUT_MS)
            # An error page or a bot challenge returns normally, so
            # goto() not raising is no proof the real site loaded.
            _status = getattr(_nav_resp, "status", None)
            for _attempt in range(CHALLENGE_RETRIES):
                _bad = bool(_status and _status >= 400)
                _chal = _looks_challenged(page)
                if not (_bad or _chal):
                    break
                if _chal:
                    result["challenged"] = True
                    # SiteGround/Cloudflare JS challenges set a cookie and
                    # bounce back on their own. Staying in the same context
                    # keeps that cookie, so waiting it out is what a real
                    # visitor does - no need to defeat anything.
                    try:
                        page.wait_for_url(
                            lambda u: not any(h in (u or "").lower()
                                              for h in CHALLENGE_URL_HINTS),
                            timeout=CHALLENGE_WAIT_MS)
                    except Exception:
                        page.wait_for_timeout(CHALLENGE_WAIT_MS)
                else:
                    page.wait_for_timeout(3000)
                try:
                    _nav_resp = page.goto(url, wait_until="domcontentloaded",
                                          timeout=PAGE_TIMEOUT_MS)
                    _status = getattr(_nav_resp, "status", None)
                except Exception:
                    break
            result["http_status"] = _status
            result["challenged"] = _looks_challenged(page)
            try:
                page.wait_for_load_state("networkidle",
                                         timeout=NETIDLE_PRE_MS)
            except Exception:
                pass  # busy sites never go idle; the settle sleep covers us
            page.wait_for_timeout(int(SETTLE_SECONDS * 1000))  # let late tags + banner render
        except Exception as e:
            try:
                page.unroute("**/*")
            except Exception:
                pass
            context.close()
            result["error"] = f"Page load failed: {e.__class__.__name__}"
            return result

        result["ok"] = True
        result["final_url"] = page.url
        try:  # a challenge page names itself in the title
            result["page_title"] = (page.title() or "")[:200]
        except Exception:
            result["page_title"] = ""
        html = page.content()
        result["html_len"] = len(html or "")
        try:  # raw server HTML (pre-JS) - live DOM would show injected
              # scripts as if hardcoded
            raw_low = (_nav_resp.text() or "").lower() if _nav_resp else ""
        except Exception:
            raw_low = ""

        # --- CMP detection: domains in rendered DOM + network + globals + cookies
        evidence_by_cmp = {}

        for name, matched in _match_domains(html).items():
            evidence_by_cmp.setdefault(name, []).extend(
                f"script/domain: {m}" for m in matched)

        net_corpus = "\n".join(u for _, u in requests_seen)
        for name, matched in _match_domains(net_corpus).items():
            evidence_by_cmp.setdefault(name, []).extend(
                f"network: {m}" for m in matched)

        for cmp in CMP_SIGNATURES:
            for g in cmp["js_globals"]:
                try:
                    if page.evaluate(f"typeof window['{g}'] !== 'undefined'"):
                        evidence_by_cmp.setdefault(cmp["name"], []).append(
                            f"js global: window.{g}")
                except Exception:
                    pass

        try:
            cookie_names = [c["name"] for c in context.cookies()]
        except Exception:
            cookie_names = []
        for cmp in CMP_SIGNATURES:
            hit = [cn for cn in cookie_names
                   if any(cn.startswith(pref) for pref in cmp["cookies"])]
            if hit:
                evidence_by_cmp.setdefault(cmp["name"], []).append(
                    f"cookie: {', '.join(sorted(set(hit))[:3])}")

        for name, evidence in evidence_by_cmp.items():
            sig = _cmp_by_name(name)
            result["cmps"].append({
                "name": name,
                "evidence": sorted(set(evidence)),
                "gtm_event": sig["gtm_event"],
                "notes": sig["notes"],
            })

        # --- banner visibility (only meaningful if a CMP was found)
        if result["cmps"]:
            visible = False
            for c in result["cmps"]:
                sig = _cmp_by_name(c["name"])
                for sel in sig["banner_selectors"]:
                    try:
                        el = page.query_selector(sel)
                        if el and (el.bounding_box() or
                                   sel.startswith("#usercentrics")):
                            visible = True
                    except Exception:
                        pass
            if not visible:
                probe = _generic_banner_probe(page)
                if probe and probe.get("banner"):
                    visible = True  # selectors drifted; banner is there
            result["banner_visible"] = visible
        else:
            # --- generic fallback: flag consent banners we don't have a
            # signature for (e.g. niche/vertical CMPs). Conservative on
            # purpose: requires a fixed/sticky/dialog container whose
            # text mentions cookies/consent/privacy AND that contains an
            # accept- or reject-style button. IAB APIs count as evidence
            # too. Named "Unrecognized consent banner" so buyers know a
            # mechanism exists but the vendor needs identifying.
            generic = _generic_banner_probe(page)
            if generic:
                ev = []
                if generic.get("banner"):
                    ev.append("heuristic: anchored element with consent "
                              "text + accept/reject button")
                for k, label in (("tcf", "window.__tcfapi (IAB TCF)"),
                                 ("usp", "window.__uspapi (IAB US Privacy)"),
                                 ("gpp", "window.__gpp (IAB GPP)")):
                    if generic.get(k):
                        ev.append(f"api: {label}")
                if ev:
                    notice_only = (generic.get("banner")
                                   and not generic.get("has_choice")
                                   and not (generic.get("tcf")
                                            or generic.get("usp")
                                            or generic.get("gpp")))
                    if notice_only:
                        result["cmps"].append({
                            "name": NOTICE_ONLY_CMP,
                            "evidence": ["heuristic: anchored bar with "
                                         "cookie text and an accept/OK "
                                         "button but no reject or "
                                         "preferences option"],
                            "gtm_event": None,
                            "notes": "This is an informational bar, not a "
                                     "consent mechanism - it offers no way "
                                     "to decline, so it neither gates "
                                     "pixels nor satisfies opt-out "
                                     "expectations. Often site-built "
                                     "(theme/CMS) rather than a CMP "
                                     "product.",
                        })
                    else:
                        result["cmps"].append({
                            "name": "Unrecognized consent banner",
                            "evidence": ev,
                            "gtm_event": None,
                            "notes": "A consent mechanism is present but "
                                     "the vendor isn't in the signature "
                                     "list yet. Identify the CMP before "
                                     "applying the GTM consent procedure, "
                                     "and send Vici the vendor name so a "
                                     "signature can be added.",
                        })
                    result["banner_visible"] = bool(generic.get("banner"))
        # else stays "unknown" - nothing to look for

        # --- opt-out link detection (state-law check input)
        low_html = html.lower()
        result["optout_link"] = next(
            (p for p in OPTOUT_LINK_PHRASES if p in low_html), None)

        # --- privacy policy link (universal FTC-baseline check input)
        result["privacy_policy_link"] = next(
            (p for p in ("privacy policy", "privacy notice",
                         "privacy statement", "privacy center")
             if p in low_html), None)
        if not result["privacy_policy_link"] and 'href="/privacy' in low_html:
            result["privacy_policy_link"] = "/privacy (href)"

        # --- GTM presence
        result["gtm"] = _gtm_info(html + "\n" + net_corpus)

        # --- Google Consent Mode default state
        try:
            cm = page.evaluate("""() => {
                const out = {found: false, entries: {}};
                try {
                    const dl = window.dataLayer || [];
                    for (const e of dl) {
                        if (e && e[0] === 'consent' && e[1] === 'default') {
                            out.found = true;
                            const cfg = e[2] || {};
                            for (const k of Object.keys(cfg)) out.entries[k] = cfg[k];
                        }
                    }
                } catch (err) {}
                try {
                    const ics = window.google_tag_data && window.google_tag_data.ics;
                    if (ics && ics.entries) {
                        for (const k of Object.keys(ics.entries)) {
                            const v = ics.entries[k];
                            if (v && typeof v.default !== 'undefined') {
                                out.found = true;
                                if (!(k in out.entries))
                                    out.entries[k] = v.default ? 'granted' : 'denied';
                            }
                        }
                    }
                } catch (err) {}
                return out;
            }""")
            result["consent_mode_default"] = bool(cm.get("found"))
            result["consent_defaults"] = {
                k: str(v) for k, v in (cm.get("entries") or {}).items()}
        except Exception:
            result["consent_mode_default"] = "unknown"

        # --- simulate clicking Accept, then watch what fires
        click_time = None
        if result["cmps"]:
            if result["cmps"] or result["banner_visible"] is True:
                click_time = _try_accept(
                    page, [c["name"] for c in result["cmps"]])
            else:
                click_time = None  # no CMP, no banner - nothing to click
            result["accept_clicked"] = click_time is not None
        if result["accept_clicked"]:
            try:
                page.wait_for_load_state("networkidle",
                                         timeout=NETIDLE_POST_MS)
            except Exception:
                pass
            page.wait_for_timeout(int(SETTLE_SECONDS * 1000))  # let consent-gated tags fire

        try:
            page.unroute("**/*")
        except Exception:
            pass
        context.close()

    # --- reject pass: fresh context (no cookies), load, click Reject,
    #     record what fires afterward. The actively-litigated failure is
    #     "user said no and the pixel fired anyway".
    if (site_checks and result["ok"] and result["cmps"]
            and result["banner_visible"] is True):
        rej_seen = []
        ctx2 = browser.new_context(user_agent=UA, locale="en-US",
                                   viewport={"width": 1366, "height": 900})
        pg2 = ctx2.new_page()
        pg2.on("request",
               lambda req: rej_seen.append((time.time(), req.url)))

        def _route2(route):
            if route.request.resource_type in ("image", "media", "font"):
                route.abort()
            else:
                route.continue_()
        pg2.route("**/*", _route2)
        try:
            pg2.goto(url, wait_until="domcontentloaded",
                     timeout=PAGE_TIMEOUT_MS)
            try:
                pg2.wait_for_load_state("networkidle",
                                        timeout=NETIDLE_PRE_MS)
            except Exception:
                pass
            pg2.wait_for_timeout(1000)
            rt = _try_reject(pg2, [c["name"] for c in result["cmps"]])
            if rt is not None:
                result["reject_tested"] = True
                try:
                    pg2.wait_for_load_state("networkidle",
                                            timeout=NETIDLE_POST_MS)
                except Exception:
                    pass
                pg2.wait_for_timeout(int(SETTLE_SECONDS * 1000))
                seen_rej = set()
                for t, u in rej_seen:
                    if t < rt:
                        continue
                    tracker = _classify_tracker(u)
                    if not tracker or tracker["vendor"] in seen_rej:
                        continue
                    seen_rej.add(tracker["vendor"])
                    if tracker["google"] and _gcs_denied(u):
                        continue  # denied-state ping - correct behavior
                    sev = "warn" if tracker["google"] else "violation"
                    note = ("Google request after Reject - verify the "
                            "consent state in GTM Preview."
                            if tracker["google"] else
                            "Fired AFTER the user clicked Reject.")
                    result["post_reject"].append(
                        {"vendor": tracker["vendor"], "url": u[:220],
                         "severity": sev, "note": note,
                         "src": _pixel_source(tracker["vendor"], u,
                                              raw_low)})
        except Exception:
            pass
        finally:
            try:
                pg2.unroute("**/*")
            except Exception:
                pass
            try:
                ctx2.close()
            except Exception:
                pass

    # --- GPC pass: load with the Global Privacy Control signal set and
    #     see whether ad trackers are still contacted. Runs only when a
    #     targeted state requires honoring universal opt-out signals.
    states = [s for s in (states or []) if s in STATE_CHECKS]
    result["states"] = states if site_checks else []
    result["site_checks_skipped"] = not site_checks
    if (site_checks and result["ok"]
            and any(STATE_CHECKS[s].get("gpc") for s in states)):
        gpc_seen = []
        ctx3 = browser.new_context(
            user_agent=UA, locale="en-US",
            viewport={"width": 1366, "height": 900},
            extra_http_headers={"Sec-GPC": "1"})
        pg3 = ctx3.new_page()
        pg3.add_init_script(
            "Object.defineProperty(navigator, 'globalPrivacyControl', "
            "{get: () => true});")
        pg3.on("request", lambda req: gpc_seen.append(req.url))

        def _route3(route):
            if route.request.resource_type in ("image", "media", "font"):
                route.abort()
            else:
                route.continue_()
        pg3.route("**/*", _route3)
        try:
            pg3.goto(url, wait_until="domcontentloaded",
                     timeout=PAGE_TIMEOUT_MS)
            try:
                pg3.wait_for_load_state("networkidle",
                                        timeout=NETIDLE_PRE_MS)
            except Exception:
                pass
            pg3.wait_for_timeout(int(SETTLE_SECONDS * 1000))
            result["gpc_tested"] = True
            gpc_vendors = {}
            for u in gpc_seen:
                tracker = _classify_tracker(u)
                if not tracker or tracker["vendor"] in gpc_vendors:
                    continue
                if tracker["google"] and _gcs_denied(u):
                    continue
                gpc_vendors[tracker["vendor"]] = u
            result["gpc_fires"] = [
                {"vendor": v, "url": u[:220]}
                for v, u in sorted(gpc_vendors.items())]
        except Exception:
            pass
        finally:
            try:
                pg3.unroute("**/*")
            except Exception:
                pass
            try:
                ctx3.close()
            except Exception:
                pass

    state_checks_for(result, states, site_checks)

    # --- phase split: everything before the Accept click is pre-consent;
    #     everything after is post-consent. No click => all pre-consent.
    pre_urls = [u for t, u in requests_seen
                if click_time is None or t < click_time]
    post_urls = [u for t, u in requests_seen
                 if click_time is not None and t >= click_time]

    # pre-consent tracker classification
    seen_vendors = set()
    for req_url in pre_urls:
        tracker = _classify_tracker(req_url)
        if not tracker or tracker["vendor"] in seen_vendors:
            continue
        seen_vendors.add(tracker["vendor"])

        if not result["cmps"]:
            severity, note = "ungated", ("No consent mechanism on this page, "
                                         "so this tag runs ungated. The "
                                         "finding is the missing CMP, not "
                                         "this individual tag.")
        elif tracker["google"] and _gcs_denied(req_url):
            severity, note = "info", ("Consent Mode cookieless ping in a "
                                      "denied state - expected behavior.")
        elif (tracker["google"] and _consent_signalled(req_url)
              and _defaults_all_denied(result.get("consent_defaults"))):
            # DENIED DEFAULTS PLUS A CONSENT SIGNAL IS THE ANSWER, not a
            # question. Every tracking default was declared denied before any
            # tag ran and the request carries a Consent Mode state, so this
            # is the cookieless ping the design calls for. Reporting it amber
            # told a correctly configured client to go and check eight rows
            # that were right.
            severity, note = "info", ("Consent Mode ping under denied "
                                      "defaults - expected behavior, no "
                                      "identifier is sent.")
        elif tracker["google"] and result["consent_mode_default"] is True:
            severity, note = "warn", ("Google request pre-consent and Consent "
                                      "Mode defaults are declared, but not "
                                      "every tracking type defaults to "
                                      "denied. Check ad_storage, "
                                      "analytics_storage, ad_user_data and "
                                      "ad_personalization in GTM Preview.")
        else:
            severity, note = "violation", "Fired before any consent interaction."

        # AN UNREPLACED MACRO IS A CERTAIN DEFECT, wherever it appears.
        # `gdpr_consent=${GDPR_CONSENT_755}` reaching the network means the
        # tag template was pasted without filling its values — the product
        # table already says so about the same tag, and the row a reader is
        # looking at should not make them go and find it.
        if _MACRO_RE.search(req_url or ""):
            note = (note + " Unreplaced template macro in the URL - the tag "
                           "was pasted without filling its values.").strip()
        result["pre_consent"].append({
            "vendor": tracker["vendor"],
            "url": req_url[:220],
            "severity": severity,
            "note": note,
            "src": _pixel_source(tracker["vendor"], req_url, raw_low),
        })

    result["pre_consent"].sort(
        key=lambda h: {"violation": 0, "warn": 1, "ungated": 2,
                       "info": 3}[h["severity"]])

    # trackers that fired ONLY after Accept = correctly gated + working
    post_vendors = {}
    for req_url in post_urls:
        tracker = _classify_tracker(req_url)
        if tracker and tracker["vendor"] not in post_vendors:
            post_vendors[tracker["vendor"]] = req_url
    result["post_consent"] = [
        {"vendor": v, "url": u[:220]}
        for v, u in sorted(post_vendors.items()) if v not in seen_vendors]

    products_and_containers(result, html, raw_low, pre_urls, post_urls,
                            products)
    return result


# ------------------------------------------------------- browser pool
# Launching Chromium costs 2-3s. Dedicated worker threads each own a
# persistent Playwright instance + browser (sync API is thread-affine),
# serving scans from a queue. This both removes launch overhead and
# hard-caps concurrent browsers at BROWSER_POOL (default 2).

import os as _os
import queue as _queue
import threading as _threading


class _ScanJob:
    def __init__(self, url, products, states=None, site_checks=True):
        self.url, self.products, self.states = url, products, states
        self.site_checks = site_checks
        self.done = _threading.Event()
        self.result, self.error = None, None
        self.deadline = time.time() + 110  # caller stops waiting at 120s


class _BrowserWorker(_threading.Thread):
    def __init__(self, jobs):
        super().__init__(daemon=True)
        self.jobs = jobs
        self.pw = None
        self.browser = None

    def _launch(self):
        from playwright.sync_api import sync_playwright
        if self.pw is None:
            self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(
            args=["--no-sandbox", "--disable-dev-shm-usage"])

    RECYCLE_AFTER = max(3, int(_os.environ.get("RECYCLE_AFTER", "8")))

    def run(self):
        scans = 0
        while True:
            job = self.jobs.get()
            if time.time() > job.deadline:
                job.error = TimeoutError("stale job - caller gave up")
                job.done.set()
                continue
            t0 = time.time()
            print(f"[scan] start {job.url}", flush=True)
            try:
                if self.browser is None or not self.browser.is_connected():
                    self._launch()
                job.result = _full_scan_impl(self.browser, job.url,
                                             job.products, job.states,
                                             job.site_checks)
            except Exception as first_err:
                # browser may have died - relaunch and retry once, but
                # only if the caller is still waiting; grinding through
                # abandoned work starves the queue behind it
                if time.time() < job.deadline - 30:
                    print(f"[scan] retry {job.url} after "
                          f"{first_err.__class__.__name__}", flush=True)
                    try:
                        try:
                            if self.browser:
                                self.browser.close()
                        except Exception:
                            pass
                        self.browser = None
                        self._launch()
                        job.result = _full_scan_impl(
                            self.browser, job.url, job.products,
                            job.states, job.site_checks)
                    except Exception:
                        job.error = first_err
                else:
                    job.error = first_err
            finally:
                status = (job.error.__class__.__name__ if job.error
                          else "ok" if job.result else "?")
                print(f"[scan] done  {job.url} [{status}] "
                      f"{time.time()-t0:.1f}s", flush=True)
                job.done.set()
                scans += 1
                if scans >= self.RECYCLE_AFTER:
                    print("[scan] recycling browser", flush=True)
                    try:
                        if self.browser:
                            self.browser.close()
                    except Exception:
                        pass
                    self.browser = None
                    scans = 0


class _BrowserPool:
    def __init__(self):
        self.jobs = _queue.Queue()
        self.workers = []
        self.lock = _threading.Lock()
        self.init_error = None

    def _ensure(self):
        with self.lock:
            if self.workers or self.init_error:
                return
            try:
                import playwright.sync_api  # noqa: verify availability here
            except ImportError as e:
                print(f"[scan] POOL INIT FAILED: {e!r}", flush=True)
                self.init_error = e
                return
            n = max(1, min(int(_os.environ.get("BROWSER_POOL", "2")), 4))
            for _ in range(n):
                w = _BrowserWorker(self.jobs)
                w.start()
                self.workers.append(w)

    def run(self, url, products, states=None, site_checks=True):
        self._ensure()
        if self.init_error:
            raise ImportError(str(self.init_error))
        job = _ScanJob(url, products, states, site_checks)
        self.jobs.put(job)
        if not job.done.wait(timeout=120):
            raise TimeoutError("Scan timed out in browser pool")
        if job.error:
            raise job.error
        return job.result


_pool = _BrowserPool()


def full_scan(url, products=None, states=None, site_checks=True):
    return _pool.run(url, products, states, site_checks)


# ---------------------------------------------------------------- verdict

def _dedupe_product_pixels(r):
    """A pixel already reported under a product (e.g. Floodlight inside
    BARCK+) shouldn't repeat in the general list on no-CMP pages - the
    product section carries its consent state. CMP-bypass VIOLATIONS
    stay listed even for product pixels: the bypass is the finding."""
    prod_urls = {px["sample_url"] for p in r.get("products", [])
                 for px in p.get("pixels", []) if px.get("sample_url")}
    if prod_urls:
        r["pre_consent"] = [
            h for h in r.get("pre_consent", [])
            if not (h["severity"] == "ungated" and h["url"] in prod_urls)]
    return r


def _inconclusive_reason(r):
    """A scan that found absolutely nothing is more likely a bad page
    load than a site with no tags. Reporting it as absence produces
    false 'install or repair the pixel' work, so say so instead."""
    if r.get("mode") != "full":
        return None
    if r.get("challenged"):
        return ("The site's bot protection served a challenge screen "
                "instead of the page, so nothing on it could be checked.")
    status = r.get("http_status")
    if status and status >= 400:
        return f"The page returned HTTP {status}."
    # A browser capture that recorded no network traffic at all did not
    # observe this page — a real load fetches its own stylesheet. Everything
    # downstream would otherwise read as "nothing fired", which is the same
    # words as a clean result and the opposite meaning.
    if r.get("no_requests_recorded"):
        return ("The browser returned the page's HTML but recorded no network "
                "requests on it at all, which a real page load cannot do - the "
                "request recorder did not attach. Nothing here is a "
                "measurement of the site's tags.")
    # THE LENGTH PROXY IS CALIBRATED FOR A SERVER FETCH.
    #
    # "Under 2000 characters" means a shell or a challenge page when Playwright
    # went and got it. An extension capture is the post-JavaScript DOM read in
    # a real browser on a real profile, and it is run precisely BECAUSE the
    # fetch was blocked - throwing it away for being short would discard the
    # one source that got through. The net that matters on that path is
    # `found_anything` below, and it catches a challenge screen just as well:
    # a challenge screen carries no tag manager, no trackers, no consent
    # configuration and no privacy policy link.
    if r.get("source") != "extension" and (r.get("html_len") or 0) < 2000:
        return "The page returned almost no HTML."
    found_anything = (r.get("gtm", {}).get("found")
                      or r.get("cmps")
                      or r.get("pre_consent") or r.get("post_consent")
                      or r.get("consent_defaults")
                      or r.get("privacy_policy_link")
                      or any(p.get("fired") for p in r.get("products") or []))
    if not found_anything:
        return ("No tag manager, trackers, consent configuration or "
                "privacy policy link were seen - consistent with a page "
                "that did not fully load rather than a site with none.")
    return None


def _apply_verdict(r):
    _dedupe_product_pixels(r)
    if not r["ok"]:
        r["verdict"], r["verdict_detail"] = "error", r["error"]
        return r

    reason = _inconclusive_reason(r)
    if reason:
        r["inconclusive"] = True
        r["verdict"] = "error"
        r["verdict_detail"] = ("Scan inconclusive - " + reason
                               + " Re-scan before acting on this result.")
        return r

    violations = [h for h in r["pre_consent"] if h["severity"] == "violation"]

    if not r["cmps"]:
        r["verdict"] = "no_cmp"
        r["verdict_detail"] = ("No CMP detected. Do not apply the GTM consent "
                               "update - flag this client for a consent "
                               "banner conversation first.")
    elif violations:
        r["verdict"] = "misconfigured"
        names = ", ".join(sorted({v["vendor"] for v in violations}))
        r["verdict_detail"] = (f"CMP present but trackers fire pre-consent: "
                               f"{names}. Apply the GTM consent procedure.")
    elif r["mode"] == "basic":
        r["verdict"] = "cmp_found_basic"
        r["verdict_detail"] = ("CMP detected (basic scan). Run a full scan to "
                               "verify banner, Consent Mode, and pre-consent "
                               "behavior.")
    else:
        r["verdict"] = "ok"
        r["verdict_detail"] = ("CMP detected and no non-Google trackers fired "
                               "pre-consent on this page.")

    if r["cmps"]:
        ev = next((c["gtm_event"] for c in r["cmps"] if c["gtm_event"]), None)
        if ev:
            r["verdict_detail"] += f" GTM trigger event: {ev}"
    rej_viol = [h for h in r.get("post_reject", [])
                if h["severity"] == "violation"]
    if rej_viol and r["verdict"] == "ok":
        r["verdict"] = "misconfigured"
        r["verdict_detail"] = ("Consent looks gated on Accept, but trackers "
                               "fire after the user clicks Reject.")
    state_fails = [c for c in r.get("state_checks", [])
                   if c["status"] == "fail"]
    if state_fails and r["verdict"] == "ok":
        r["verdict"] = "misconfigured"
        r["verdict_detail"] = ("Consent gating looks correct, but "
                               "state-targeting checks fail.")
    lines = [r["verdict_detail"]] if r["verdict_detail"] else []
    if state_fails:
        failed = sorted({f"{c['state']} {c['check']}" for c in state_fails})
        lines.append("State checks failing: " + ", ".join(failed) + ".")
    if r.get("reject_tested"):
        lines.append("Reject honored: no trackers fired after Reject."
                     if not rej_viol else
                     "Fired after Reject: "
                     + ", ".join(sorted({h["vendor"] for h in rej_viol}))
                     + ".")
    prods = r.get("products") or []
    if prods:
        bits = [f"{p['product']} {p['fired']}/{p['expected']}"
                if p["expected"] > 1 else p["product"] +
                (" \u2713" if p["fired"] else " \u2717")
                for p in prods]
        lines.append("Product pixels: " + ", ".join(bits) + ".")
        missing = [p["product"] for p in prods if p["fired"] == 0]
        if missing:
            lines.append("MISSING (expected but no pixels seen): "
                         + ", ".join(missing) + ".")
    r["verdict_lines"] = lines
    r["verdict_detail"] = " ".join(lines)
    return r


# ---------------------------------------------------------------- entry

CATEGORIES = ("Healthcare", "Financial services", "Children-directed")


def products_and_containers(result, html, raw_low, pre_urls, post_urls,
                            products=None):
    """
    Which bought pixels fired, and which container each tracker lives in.

    ALSO BROWSER-FREE, ALSO WAS ONLY ON ONE PATH. Everything here reads a
    list of request URLs and some HTML - both of which the extension capture
    has, and neither of which needs Playwright. "The client pays for this
    product and its pixel never fires" is the single row on the consent page
    that costs somebody money, and on a bot-protected site the capture is
    the ONLY way to see it. It had no business being Playwright-only.
    """
    # Product pixels: per selected product (or ALL products in detect-any
    # mode), which expected sub-pixels fired, pre vs post consent.
    # For pixels with NO observed request, check the page source and the
    # (publicly fetchable) GTM container JS for the vendor's fingerprints
    # to split "not seen" into "configured but silent" (firing problem)
    # vs "not found anywhere" (likely never installed).
    page_corpus = html.lower()
    _gtm = result.get("gtm", {}) or {}
    _cids = _gtm.get("container_ids") or []
    corpora = _container_corpora(_cids)
    _gtm["containers_read"] = sorted(corpora)
    _gtm["containers_unread"] = [c for c in _cids[:3] if c not in corpora]

    # THE PUBLISHED CONFIGURATION, WHERE WE HAVE THE KEYS.
    #
    # Everything above is inference from what the page fetched: the container
    # JS is public, so we can fingerprint what is IN it, but not read the tag
    # list, the triggers, or whether each tag waits for consent. The Tag
    # Manager API answers all three — and answers the ownership question by
    # existing, which is better than the form field it replaces: if one of our
    # logins can read the container, we own it. A self-declared checkbox can
    # be wrong; an API read cannot.
    #
    # OPTIONAL AND SILENT-FREE. With no credentials this reports "disabled"
    # and the page falls back to fingerprint attribution exactly as before,
    # which is the honest degradation — but a login that is configured and
    # FAILING says so, because a container we could not read and one we never
    # tried to read must not look the same.
    _audits = {}
    for _cid in _cids[:6]:
        try:
            from .gtm_api import audit as _gtm_audit
            _audits[_cid] = _gtm_audit(_cid)
        except Exception as exc:  # noqa: BLE001
            _audits[_cid] = {"status": "error", "public_id": _cid,
                             "detail": f"{type(exc).__name__}: {exc}"}
    if _audits:
        _gtm["audits"] = _audits
        # Ownership is a fact about access, so it is derived once here rather
        # than re-derived by every renderer.
        _gtm["vici_owned"] = [c for c, a_ in _audits.items()
                              if a_.get("status") == "ok"]
        _gtm["tags_read"] = sum(len(a_.get("tags") or [])
                                for a_ in _audits.values()
                                if a_.get("status") == "ok")
    result["gtm"] = _gtm

    # Same container attribution for non-product trackers. These hit
    # records are built before the containers are fetched, so annotate
    # them here rather than duplicating the fetch upstream.
    _vh = {}
    for _key in ("pre_consent", "post_reject"):
        for _h in result.get(_key) or []:
            _v = _h.get("vendor")
            if _v not in _vh:
                _vh[_v] = _containers_with(_vendor_hints(_v), corpora)
            _h["containers"] = _vh[_v]

    _ALIASES = {"Performance Max": "PMax"}  # saved clients / old payloads
    products = [_ALIASES.get(p, p) for p in products] if products else products
    selected = products if products else list(PRODUCT_PIXELS.keys())
    detect_any = not products
    for prod in selected:
        pixels = []
        for px in PRODUCT_PIXELS.get(prod, []):
            pre_hit = next((u for u in pre_urls
                            if any(p in u for p in px["patterns"])), None)
            post_hit = next((u for u in post_urls
                             if any(p in u for p in px["patterns"])), None)
            hit_url = (post_hit or pre_hit) or ""
            hints = list(px["patterns"]) + CODE_HINTS.get(px["name"], [])
            in_containers = _containers_with(hints, corpora)
            # Link this pixel to its pre-consent record by URL, not by
            # name: the two lists name the same pixel differently
            # (Floodlight vs DoubleClick / Floodlight). Carries the
            # severity onto the pixel and stamps the product onto the
            # hit so the report groups it instead of listing it twice.
            severity = severity_note = None
            if pre_hit:
                for _h in result.get("pre_consent") or []:
                    if _h.get("url") == pre_hit[:220]:
                        severity = _h.get("severity")
                        severity_note = _h.get("note")
                        _h["product"] = prod
                        break
            configured = None
            if not pre_hit and not post_hit:
                configured = bool(in_containers) or any(
                    h.lower() in page_corpus for h in hints)
            pixels.append({
                "name": px["name"],
                "fired_pre": bool(pre_hit),
                "fired_post": bool(post_hit),
                "configured": configured,
                "sample_url": hit_url[:220],
                "src": (_pixel_source(px["name"], hit_url, raw_low)
                        if hit_url else None),
                # Containers whose published JS carries this pixel's
                # fingerprint. Evidence of configuration, not proof of
                # which one fired - see _containers_with.
                "containers": in_containers,
                "severity": severity,
                "severity_note": severity_note,
                # Unreplaced trafficking macros like [ORDER] or {orderid}
                # mean the template was pasted without filling values.
                "macro_warning": bool(re.search(
                    r"(\[[A-Za-z_][A-Za-z0-9_ -]+\]|"
                    r"(?<!\$)\{[A-Za-z_][A-Za-z0-9_ -]+\})", hit_url)),
            })
        fired = sum(1 for p in pixels if p["fired_pre"] or p["fired_post"])
        if detect_any and fired == 0:
            continue  # unselected + nothing fired = not this client's product
        result["products"].append({
            "product": prod,
            "expected": len(pixels),
            "fired": fired,
            "pixels": pixels,
        })
    return result


def state_checks_for(result, states, site_checks=True):
    """
    The per-state statute rows, computed from a finished result.

    BROWSER-FREE ON PURPOSE, and now called from both paths. Every line here
    reads `result` and nothing else - which meant the extension path, whose
    whole reason for existing is that the browser half failed, was throwing
    away rows it had all the inputs for. Same rule as one classifier for two
    sources: one statute table, or the two paths eventually disagree about
    what California asks for.
    """
    # --- per-state check results
    # --- universal baseline check (every US site): privacy policy link.
    # FTC Act §5 applies nationwide - a site tracking visitors with no
    # accessible privacy policy is the baseline failure. Presence-only:
    # content accuracy needs human/counsel review.
    if site_checks and result.get("mode") == "full" and result.get("ok"):
        pp = result.get("privacy_policy_link")
        result["state_checks"].append(
            {"state": "US", "check": "Privacy policy link",
             "status": "pass" if pp else "fail",
             "detail": (f'Found "{pp}" on the page. Presence check only - '
                        "whether the policy accurately describes this "
                        "site's tracking needs human review."
                        if pp else
                        "No privacy policy link found on this page. Every "
                        "US site that tracks visitors is expected to have "
                        "an accessible, accurate privacy policy (FTC Act "
                        "\u00a75 + state laws).")})

    for s in (states if site_checks else []):
        cfg = STATE_CHECKS[s]
        if cfg.get("gpc"):
            if not result["gpc_tested"]:
                result["state_checks"].append(
                    {"state": s, "check": "GPC signal", "status": "unknown",
                     "detail": "GPC page load did not complete."})
            elif result["gpc_fires"]:
                names = ", ".join(f["vendor"] for f in result["gpc_fires"])
                result["state_checks"].append(
                    {"state": s, "check": "GPC signal", "status": "fail",
                     "detail": f"Ad trackers contacted despite the GPC "
                               f"signal: {names}. Honoring universal opt-out "
                               f"signals is required for {cfg['name']} "
                               f"targeting."})
            else:
                result["state_checks"].append(
                    {"state": s, "check": "GPC signal", "status": "pass",
                     "detail": "No ad trackers contacted on a GPC page "
                               "load."})
        # Synthesized check: no CMP + no opt-out link + GPC not honored
        # means NO mechanism for residents to opt out at all - the
        # pattern state enforcement actually targets (e.g. Sephora).
        # A banner itself isn't required under these opt-out laws, so
        # "no CMP" alone is never flagged as a state failure.
        gpc_ignored = result["gpc_tested"] and result["gpc_fires"]
        # A notice-only bar is not a mechanism - it cannot decline - so
        # it must not suppress this check the way a real CMP does.
        # "Unrecognized consent banner" DOES have choices and still does.
        real_cmp = [c for c in result["cmps"]
                    if c["name"] != NOTICE_ONLY_CMP]
        notice_only_seen = len(real_cmp) < len(result["cmps"])
        if (not real_cmp and not result["optout_link"]
                and (gpc_ignored or not cfg.get("gpc"))):
            bits = ["a notice-only banner with no reject option"
                    if notice_only_seen else "no consent banner/CMP",
                    "no opt-out link"]
            if gpc_ignored:
                bits.append("ad trackers contacted despite the GPC signal")
            result["state_checks"].append(
                {"state": s, "check": "Opt-out mechanism", "status": "fail",
                 "detail": "No mechanism for residents to opt out was "
                           "detected: " + ", ".join(bits) + ". Some "
                           f"accessible opt-out method is expected for "
                           f"{cfg['name']} targeting."})
        # THE OPT-IN HALF, WHERE THE STATUTE HAS ONE.
        #
        # California is an opt-out regime for adults and an OPT-IN one for
        # consumers known to be under 16 — and the check only ever spoke to
        # the first. On a client whose audience includes families that is not
        # a footnote, it is a different legal test with a different answer, so
        # it gets said rather than left for somebody to remember.
        if cfg.get("optin_minors"):
            result["state_checks"].append(
                {"state": s, "check": "Under-16 opt-in",
                 "status": "warn",
                 "detail": ("Opt-out is the standard for adults, but selling "
                            "or sharing the data of a consumer known to be "
                            "under 16 needs affirmative OPT-IN - from the "
                            "consumer at 13-15, from a parent under 13. A "
                            "scan cannot tell whether this audience includes "
                            "minors; if it does, a reject-by-default banner "
                            "is the floor and age signals need a human "
                            "review. " + cfg.get("optin_cite", ""))})
        if cfg.get("optout_link"):
            if result["optout_link"]:
                result["state_checks"].append(
                    {"state": s, "check": "Opt-out link", "status": "pass",
                     "detail": f'Found "{result["optout_link"]}" on the '
                               f"page."})
            else:
                result["state_checks"].append(
                    {"state": s, "check": "Opt-out link", "status": "fail",
                     "detail": "No recognizable opt-out link text found on "
                               "this page. An accessible opt-out method is "
                               f"expected for {cfg['name']} targeting."})


def _category_checks(result, category):
    """Sensitive-context checks for buyer-DECLARED categories. The
    category is a human declaration, never auto-detected - deciding a
    site's regulatory context is a judgment call; observing what fires
    there is ours. Check-based wording throughout."""
    if category not in CATEGORIES:
        return
    # product component pixels roll up under the product name (one
    # "BARCK+" instead of Beeswax/DoubleClick/TTD/Yahoo separately)
    prod_pixel_names = {px["name"] for p in result.get("products", [])
                        for px in p.get("pixels", [])}
    ad_vendors = sorted(({h["vendor"] for h in result.get("pre_consent", [])}
                         | {h["vendor"] for h in result.get("post_consent", [])
                            if isinstance(h, dict) and h.get("vendor")})
                        - prod_pixel_names
                        | {p["product"] for p in result.get("products", [])
                           if any(px.get("fired_pre") or px.get("fired_post")
                                  for px in p.get("pixels", []))})
    ungated = any(h["severity"] in ("ungated", "violation")
                  for h in result.get("pre_consent", [])) or any(
                  px.get("fired_pre") for p in result.get("products", [])
                  for px in p.get("pixels", []))
    if category == "Healthcare":
        if ad_vendors:
            result["state_checks"].append(
                {"state": "US", "check": "Health-context tracking",
                 "status": "fail" if ungated else "warn",
                 "detail": "Ad/analytics trackers observed on a declared "
                           f"health-context site: {', '.join(ad_vendors)}. "
                           "Sending health-related browsing to ad platforms "
                           "is the pattern behind FTC actions (GoodRx, "
                           "BetterHelp) and the hospital pixel litigation "
                           "wave; most state privacy laws treat health data "
                           "as sensitive, requiring OPT-IN consent, and WA "
                           "My Health My Data goes further. "
                           + ("Trackers fire without consent gating here."
                              if ungated else
                              "Trackers are consent-gated, but sensitive-"
                              "data opt-in quality needs compliance review.")
                           + " Flag for compliance review before running ad "
                           "pixels on this client."})
        else:
            result["state_checks"].append(
                {"state": "US", "check": "Health-context tracking",
                 "status": "pass",
                 "detail": "No ad/analytics trackers observed on this "
                           "declared health-context page."})
    elif category == "Children-directed":
        if ad_vendors:
            result["state_checks"].append(
                {"state": "US", "check": "Child-directed tracking",
                 "status": "fail",
                 "detail": "Trackers observed on a declared child-directed "
                           f"site: {', '.join(ad_vendors)}. COPPA requires "
                           "verifiable PARENTAL consent before collecting "
                           "personal information from under-13s - a normal "
                           "consent banner does not satisfy it. Behavioral "
                           "advertising to children is the FTC's most "
                           "actively enforced tracking rule. Flag for "
                           "compliance review immediately."})
        else:
            result["state_checks"].append(
                {"state": "US", "check": "Child-directed tracking",
                 "status": "pass",
                 "detail": "No trackers observed on this declared "
                           "child-directed page."})
    elif category == "Financial services":
        if ungated:
            result["state_checks"].append(
                {"state": "US", "check": "Financial-context tracking",
                 "status": "warn",
                 "detail": "Trackers fire without consent gating on a "
                           "declared financial-services site: "
                           f"{', '.join(ad_vendors)}. GLBA covers customer "
                           "financial data, and regulators (CFPB/FTC) have "
                           "scrutinized pixels on loan and account pages. "
                           "Recommend consent gating and a review of what "
                           "page context the pixels transmit."})


def scan_site(raw_url, prefer_full=True, products=None, states=None,
              site_checks=True, category=None, industries=None):
    url = normalize_url(raw_url)
    if not url:
        r = _empty_result(raw_url or "")
        r["error"] = "Not a valid URL."
        return _apply_verdict(r)
    _cat = category if category in CATEGORIES else None
    from .industries import derive_contexts
    _contexts = derive_contexts(industries)
    if _cat:
        _contexts.add(_cat)

    # VICI ADDITION (not upstream): carry the fallback reason on the result.
    #
    # The reason full mode failed was printed to stdout and dropped. So the
    # report said "this ran as a basic scan" and stopped there, and finding out
    # WHY meant opening the worker's log — which nobody does, and which is
    # gone by the time anyone thinks to look. Five checkpoints go unanswered
    # on a basic scan; the one sentence explaining it is worth more than all
    # five, because it is the sentence that gets them answered next time.
    why = None
    if prefer_full:
        try:
            r = _apply_verdict(full_scan(url, products=products,
                                         states=states,
                                         site_checks=site_checks))
            if site_checks:
                for _c in sorted(_contexts):
                    _category_checks(r, _c)
            return r
        except ImportError as e:
            why = f"Playwright is not importable on this worker: {e}"
            print(f"[scan] POOL UNAVAILABLE (ImportError: {e}) - basic "
                  f"fallback for {url}", flush=True)
        except Exception as e:
            import traceback
            why = f"{e.__class__.__name__}: {' '.join(str(e).split())[:300]}"
            print(f"[scan] FULL SCAN FAILED for {url}: {e!r} - basic "
                  f"fallback. Trace:", flush=True)
            traceback.print_exc()
            # Chromium missing/crashed etc. Fall back rather than fail.
            if "Executable doesn't exist" not in str(e) and \
               "playwright install" not in str(e).lower():
                r = _empty_result(url)
                r["error"] = f"Full scan failed: {e.__class__.__name__}"
                # still try basic below so the buyer gets *something*
    r = basic_scan(url)
    if why:
        r["full_scan_error"] = why
    return _apply_verdict(r)
