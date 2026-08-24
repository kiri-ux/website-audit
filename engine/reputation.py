"""
Reputation profile — what the world says about this client, in public.

VENDORED FROM THE QUOTE BUILDER, ON PURPOSE.

This is `rep_scan.py` out of seo-quote, made a phase of the audit. The same
argument as the consent scanner: the hard part is not the idea, it is the
accumulated knowledge - which DataForSEO endpoint answers which question, that
`keywords_for_keywords` merges close variants and undercounts "{brand}
lawsuit", that Google's related-searches block is topical rather than
brand-scoped and will happily hand you a COMPETITOR's complaints phrase to
print in your client's report. A second implementation would be a second thing
to keep right, and the two would drift on exactly those cases.

What changed on the way in: the module took its HTTP client by injection so it
could avoid a circular import in that app. Here it imports the audit's own
DataForSEO client directly - same credentials, same retry and rate-limit
handling as the backlink and ranking collectors, one place to configure.

NOT SCORED. Reputation does not become checkpoints. The template is 322 rows
and every one of them is a thing we can pass or fail on the client's own site;
what other people say about them on other people's sites is a different kind of
fact. It renders as its own section, from `extras`, exactly like AI visibility.
"""

import os
import re
import time

from .collectors.dataforseo import dfs_post as _post, configured

# ---------------------------------------------------------------- negatives
def _squash(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


# A LEADING ARTICLE IS NOT PART OF THE NAME ANYWHERE THAT MATTERS.
#
# The client signs their contract as "The Ooten Law Firm". Their Google
# listing says "Ooten Law Firm", their reviews page says "Ooten Law Firm",
# and every brand search anyone types leaves the article off. Requiring it
# means the listing lookup finds nothing and the section prints a firm with
# no reviews, which is the worst possible failure here: it looks like an
# answer. Both the listing gate and the phrase filter use the trimmed name.
_ARTICLES = ("the ", "a ", "an ")


def _bare(brand):
    b = (brand or "").strip().lower()
    for art in _ARTICLES:
        if b.startswith(art):
            return b[len(art):].strip()
    return b


def brand_tokens(brand):
    """The words a title has to contain to be this client's listing."""
    return [w for w in _bare(brand).split() if len(w) > 1]


def names_client(phrase, brand, domain=""):
    """Does this search phrase actually name THIS client?

    Google's related-searches and People-Also-Search-For blocks are topical, not
    brand-scoped: a scan of "hot tubs etc reviews" returns "Hot Springs hot tub
    reviews complaints" and "Bullfrog hot tub reviews" — a manufacturer and a
    competitor. Those were rendered into the client's proposal visual, and the
    Hot Springs "complaints" phrase was counted as a NEGATIVE SIGNAL against a
    client it has nothing to do with, which both recommends a cleanup campaign
    and prices one (2026-08-05).

    Matching is on the squashed brand and the bare domain, so punctuation and
    spacing don't matter ("Hot Tubs Etc." -> hottubsetc). When neither yields a
    usable key the filter stands down rather than emptying the panel.
    """
    keys = []
    b = _squash(_bare(brand))
    if len(b) > 3:
        keys.append(b)
    host = (domain or "").split("//")[-1].split("/")[0].replace("www.", "")
    d = _squash(host.rsplit(".", 1)[0] if "." in host else host)
    if len(d) > 3 and d not in keys:
        keys.append(d)
    if not keys:
        return True
    p = _squash(phrase)
    return any(k in p for k in keys)


NEG_MODIFIERS = {
    "lawsuit", "lawsuits", "complaint", "complaints", "scam", "scams",
    "fraud", "ripoff", "rip-off", "sue", "sued", "suing", "settlement",
    "class action", "recall", "arrest", "arrested", "controversy",
    "scandal", "investigation", "warning", "problem", "problems",
    "horror", "worst", "avoid", "shut down", "closing", "bankrupt",
    "bankruptcy", "bbb",
}
WATCH_MODIFIERS = {"reviews", "review", "legit", "rating", "ratings",
                   "is it good", "safe"}

def classify_term(term, brand):
    t = term.lower()
    b = _bare(brand)
    if b not in t:
        return None                       # not a brand term
    rest = t.replace(b, " ")
    for m in NEG_MODIFIERS:
        if m in rest:
            return "negative"
    for m in WATCH_MODIFIERS:
        if m in rest:
            return "watch"
    return "neutral"


PROBE_MODIFIERS = ["lawsuit", "complaints", "scam", "fraud", "class action",
                   "settlement", "reviews", "legit"]

def scan_terms(brand):
    """Brand term universe via keywords_for_keywords (US national), PLUS an
    exact-match probe of the canonical negative/watch variants. KFK returns
    GROUPED volumes that merge close variants (the same quirk the SEO tool
    works around) — so '{brand} lawsuit' can vanish into the parent term and
    silently undercount negative volume. The probe re-pulls those terms from
    the Labs keyword database, which returns per-term exact volume."""
    b = _bare(brand)
    payload = [{"keywords": [b], "location_code": 2840,
                "language_code": "en", "sort_by": "search_volume"}]
    data = _post("/keywords_data/google_ads/keywords_for_keywords/live",
                 payload, timeout=90)
    by_term = {}
    for it in (data["tasks"][0]["result"] or []):
        kw = (it.get("keyword") or "").lower()
        vol = it.get("search_volume") or 0
        cls = classify_term(kw, brand)
        if cls:
            by_term[kw] = {"term": kw, "volume": vol, "class": cls, "src": "kfk"}

    # exact-match probe: canonical variants + any flagged KFK terms
    probes = [f"{b} {m}" for m in PROBE_MODIFIERS]
    probes += [t for t, r in by_term.items() if r["class"] != "neutral"]
    probes = sorted(set(probes))
    try:
        pdata = _post("/dataforseo_labs/google/keyword_overview/live",
                      [{"keywords": probes, "location_code": 2840,
                        "language_code": "en"}], timeout=45)
        for block in (pdata["tasks"][0]["result"] or []):
            for it in (block.get("items") or []):
                kw = (it.get("keyword") or "").lower()
                vol = ((it.get("keyword_info") or {}).get("search_volume")) or 0
                cls = classify_term(kw, brand)
                if not cls:
                    continue
                # exact volume overrides the grouped KFK number
                by_term[kw] = {"term": kw, "volume": vol, "class": cls,
                               "src": "exact"}
    except Exception:
        pass                      # probe is enrichment — never fail the scan

    rows = sorted(by_term.values(), key=lambda r: -r["volume"])
    tot = {c: sum(r["volume"] for r in rows if r["class"] == c)
           for c in ("neutral", "watch", "negative")}
    return {"terms": rows[:120],
            "total_volume": sum(tot.values()),
            "negative_volume": tot["negative"],
            "watch_volume": tot["watch"]}


# --------------------------------------------------------------------- serp
def _domain(d):
    """Normalize a domain or full URL: strip scheme, path, query, port, www."""
    d = (d or "").strip().lower()
    d = re.sub(r"^[a-z]+://", "", d)
    d = d.split("/")[0].split("?")[0].split(":")[0]
    return d[4:] if d.startswith("www.") else d

# Domain -> recommended tactic for the SERP threat table. Review counts in
# the removal quote are GOOGLE Business reviews only; these third-party pages
# route to other tactics (Visions precedent: complaint boards / Reddit /
# Trustpilot pages can be removed at the PAGE level via Website Removal).
ROUTES = [
    (("yelp.", "glassdoor.", "indeed.", "bbb.",
      "facebook.", "instagram.", "x.com", "twitter.", "tiktok.",
      "linkedin."), "suppression"),
    (("trustpilot.", "complaintsboard.", "pissedconsumer.", "scampulse.",
      "ripoffreport.", "gripeo.", "reddit.", "quora."), "site removal"),
]

def route_tactic(domain, owned=False, forum=False, rating=None):
    if owned:
        return "owned \u2014 boost"
    # Sentiment gate: a third-party result showing a strong rating is an
    # asset working in the client's favor \u2014 suppressing it would bury
    # the brand's own good reviews. Leave it (and let it help push down
    # the actual negatives).
    if rating is not None and rating >= 4.0:
        return "positive \u2014 leave"
    d = (domain or "").lower()
    for prefixes, tactic in ROUTES:
        if any(p in d for p in prefixes):
            return tactic
    return "site removal" if forum else "suppression"


def _rating_from_text(*texts):
    """Google rarely returns structured star snippets now — the rating usually
    lives in the description text ('average rating of 2.6 from 90 reviews',
    '1.4 / 5', 'Rated 3.1 out of 5'). Regex it out; None if absent."""
    pat = re.compile(
        r"(?:rated\s+|rating(?:\s+of)?[:\s]+|average rating of\s+)?"
        r"([0-5]\.\d)\s*(?:/\s*5|out of 5|stars?|\u2605|from\s+[\d,]+\s+reviews)",
        re.I)
    for t in texts:
        if not t:
            continue
        m = pat.search(t)
        if m:
            try:
                v = float(m.group(1))
                if 0 < v <= 5:
                    return v
            except ValueError:
                pass
    return None


def scan_serp(brand, domain=""):
    """Top-10 for '{brand} reviews': organic results (with ratings parsed from
    snippet text when Google omits star markup), the Reddit/forums block, the
    AI Overview, related searches — owned tagging against the client domain."""
    kw = f"{_bare(brand)} reviews"
    payload = [{"keyword": kw, "location_code": 2840,
                "language_code": "en", "depth": 10}]
    data = _post("/serp/google/organic/live/advanced", payload, timeout=45)
    own = _domain(domain)
    organic, related, forums, pasf = [], [], [], []
    ai_text = ""
    for it in (data["tasks"][0]["result"] or [{}])[0].get("items") or []:
        t = it.get("type")
        if t == "organic":
            rat = (it.get("rating") or {})
            organic.append({
                "pos": it.get("rank_absolute"),
                "title": it.get("title"),
                "domain": _domain(it.get("domain")),
                "snippet": (it.get("description") or "")[:200],
                "rating": rat.get("value") or _rating_from_text(
                    it.get("description"), it.get("title")),
                "votes": rat.get("votes_count"),
                "owned": bool(own) and own == _domain(it.get("domain")),
                "tactic": route_tactic(_domain(it.get("domain")),
                                       bool(own) and own == _domain(it.get("domain")),
                                       rating=rat.get("value") or _rating_from_text(
                                           it.get("description"), it.get("title"))),
            })
        elif t in ("discussions_and_forums", "found_on_web"):
            for el in (it.get("items") or [])[:6]:
                dom = _domain(el.get("domain") or el.get("source"))
                forums.append({
                    "pos": it.get("rank_absolute"),
                    "domain": dom,
                    "title": el.get("title"),
                    "tactic": route_tactic(dom, forum=True),
                })
        elif t == "ai_overview":
            parts = []
            for el in (it.get("items") or []):
                for k in ("text", "title", "snippet"):
                    if el.get(k):
                        parts.append(el[k])
            if it.get("markdown"):
                parts.append(it["markdown"])
            ai_text = " ".join(parts)[:1200]
        elif t == "related_searches":
            related = [x for x in (it.get("items") or []) if x][:10]
        elif t == "people_also_search":
            pasf += [x for x in (it.get("items") or []) if isinstance(x, str)][:8]
    # Drop phrases that name a different company BEFORE anything counts them.
    off_brand = [x for x in (related + pasf) if not names_client(x, brand, domain)]
    related = [x for x in related if names_client(x, brand, domain)]
    pasf = [x for x in pasf if names_client(x, brand, domain)]
    neg_related = [x for x in related
                   if any(m in x.lower() for m in NEG_MODIFIERS)]
    neg_pasf = [x for x in pasf if any(m in x.lower() for m in NEG_MODIFIERS)]
    ai_negative = [m for m in NEG_MODIFIERS if m in ai_text.lower()]
    owned_top10 = sum(1 for o in organic if o["owned"])
    return {"query": kw, "organic": organic[:10], "forums": forums,
            "ai_overview": ai_text, "ai_negative": ai_negative,
            "related": related, "negative_related": neg_related,
            "pasf": pasf, "negative_pasf": neg_pasf,
            "off_brand_phrases": off_brand,
            "owned_in_top10": owned_top10}


def scan_autocomplete(brand):
    """Auto-suggest for the brand and '{brand} reviews' — negative flags.
    Uses client=gws-wiz (the actual Google search-box client; the DFS default
    returns a thinner set). Terms that come back empty get a fallback pass:
    trailing-space (next-word suggestions, matching Brendan's screenshots)
    then last-char-trimmed prefix. Extra calls only fire for empty terms."""
    kws = [_bare(brand), f"{_bare(brand)} reviews"]

    def _pull(keywords):
        payload = [{"keyword": k, "location_code": 2840, "language_code": "en",
                    "client": "gws-wiz"} for k in keywords]
        data = _post("/serp/google/autocomplete/live/advanced", payload,
                     timeout=30)
        res = {}
        for task in data.get("tasks") or []:
            kw = ((task.get("data") or {}).get("keyword") or "")
            sugg = []
            for block in task.get("result") or []:
                for it in (block or {}).get("items") or []:
                    if it.get("type") == "autocomplete" and it.get("suggestion"):
                        sugg.append(it["suggestion"])
            res[kw] = sugg
        return res

    out = {}
    try:
        first = _pull(kws)
        for k in kws:
            out[k] = {"suggestions": first.get(k, []) or first.get(k.strip(), [])}
        # fallback pass for empties: "kw " (next-word) then "kw"[:-1] (prefix)
        empties = [k for k in kws if not out[k]["suggestions"]]
        if empties:
            variants = {}
            for k in empties:
                variants[k + " "] = (k, "next-word")
                variants[k[:-1]] = (k, "prefix")
            fb = _pull(list(variants.keys()))
            for vkey, sugg in fb.items():
                orig, how = variants.get(vkey) or variants.get(vkey.strip(), (None, None))
                if orig and sugg and not out[orig]["suggestions"]:
                    # keep only suggestions still about the original term
                    keep = [x for x in sugg if orig.split()[0] in x.lower()]
                    if keep:
                        out[orig]["suggestions"] = keep
                        out[orig]["via"] = how
        for k in kws:
            out[k]["negative"] = [x for x in out[k]["suggestions"]
                                  if any(m in x.lower() for m in NEG_MODIFIERS)]
    except Exception as e:
        for k in kws:
            out.setdefault(k, {"error": str(e)})
    return out


# ---------------------------------------------------------------- locations
def scan_locations(brand, limit=200, domain=None):
    """Google Business location discovery via the Business Listings database
    (instant, no scrape). Tries the `title` search field, filter fallbacks,
    and — when the client website is known — a domain match, which finds the
    listing even when its name differs from the client name."""
    dom = (domain or "").lower().strip()
    dom = re.sub(r"^https?://", "", dom).split("/")[0].replace("www.", "")
    attempts = [
        {"title": brand, "limit": limit,
         "order_by": ["rating.votes_count,desc"]},
        {"filters": [["title", "like", f"%{brand.title()}%"]], "limit": limit,
         "order_by": ["rating.votes_count,desc"]},
        {"filters": [["title", "like", f"%{brand.lower()}%"]], "limit": limit,
         "order_by": ["rating.votes_count,desc"]},
    ]
    if dom:
        attempts += [
            {"filters": [["domain", "=", dom]], "limit": limit,
             "order_by": ["rating.votes_count,desc"], "_via_domain": True},
            {"filters": [["url", "like", f"%{dom}%"]], "limit": limit,
             "order_by": ["rating.votes_count,desc"], "_via_domain": True},
        ]
    last_err = None
    b_tokens = brand_tokens(brand)
    for payload in attempts:
        via_domain = payload.pop("_via_domain", False)
        try:
            data = _post("/business_data/business_listings/search/live",
                         [payload], timeout=90)
            task = (data.get("tasks") or [{}])[0]
            if task.get("status_code") != 20000:
                last_err = task.get("status_message") or "unknown DFS error"
                continue
            items = ((task.get("result") or [{}])[0] or {}).get("items") or []
            locs = []
            for it in items:
                title = (it.get("title") or "")
                # Title searches must contain the brand tokens; domain matches
                # skip that gate — a name mismatch is exactly what they solve.
                if not via_domain and not all(tok in title.lower() for tok in b_tokens):
                    continue
                rat = it.get("rating") or {}
                locs.append({
                    "title": title,
                    "address": it.get("address"),
                    "place_id": it.get("place_id"),
                    "cid": it.get("cid"),
                    "rating": rat.get("value"),
                    "reviews": rat.get("votes_count") or 0,
                })
            if locs:
                return {"locations": locs,
                        "total_reviews": sum(l["reviews"] for l in locs),
                        "strategy": "domain" if via_domain
                                    else ("title" if "title" in payload else "filter")}
        except Exception as e:
            last_err = str(e)
    if last_err:
        return {"locations": [], "total_reviews": 0,
                "error_detail": f"Listings lookup failed: {last_err}"}
    return {"locations": [], "total_reviews": 0}


# ------------------------------------------------------------- review pulls
def reviews_submit(place_ids, depth=200):
    """Queue worst-first review pulls (priority 2, ~1 min). Returns task ids.
    depth=200 => $0.03/location at priority pricing."""
    depth = max(10, min(4490, int(depth)))
    payload = [{"place_id": pid, "location_code": 2840, "language_code": "en",
                "depth": depth, "sort_by": "lowest_rating", "priority": 2,
                "tag": pid}
               for pid in place_ids]
    data = _post("/business_data/google/reviews/task_post", payload, timeout=60)
    tasks = []
    for t in data.get("tasks") or []:
        tasks.append({"id": t.get("id"),
                      "place_id": (t.get("data") or {}).get("tag"),
                      "ok": t.get("status_code") in (20000, 20100)})
    return {"tasks": tasks, "depth": depth}


def reviews_collect(task_ids):
    """Poll queued pulls. Counts 1-2 star (negative) and 3 star (weak) per
    task; flags when negatives hit the pull depth (=> more exist)."""
    done, pending = [], []
    for tid in task_ids:
        try:
            data = _post(f"/business_data/google/reviews/task_get/{tid}",
                         None, timeout=30, method="GET")
            task = (data.get("tasks") or [{}])[0]
            res = (task.get("result") or [None])[0]
            if task.get("status_code") == 20000 and res:
                items = res.get("items") or []
                vals = [((i.get("rating") or {}).get("value") or 5) for i in items]
                n1 = sum(1 for v in vals if v <= 1)
                n2 = sum(1 for v in vals if v == 2)
                n12 = n1 + n2
                n3 = sum(1 for v in vals if v == 3)
                done.append({
                    "id": tid,
                    "place_id": (task.get("data") or {}).get("tag"),
                    "title": res.get("title"),
                    "profile_rating": (res.get("rating") or {}).get("value"),
                    "profile_reviews": res.get("reviews_count"),
                    "pulled": len(items),
                    "neg_1": n1, "neg_2": n2, "neg_1_2": n12, "weak_3": n3,
                    "truncated": n12 >= len(items) and len(items) > 0,
                })
            else:
                pending.append(tid)
        except Exception:
            pending.append(tid)
    return {"done": done, "pending": pending,
            "total_negatives": sum(d["neg_1_2"] for d in done),
            "total_weak": sum(d["weak_3"] for d in done)}


# ---------------------------------------------------------------- the phase
#
# One entry point, so the worker does not have to know which of the four calls
# answers what - and so a failure in any one of them costs that panel rather
# than the section.
def profile(brand: str, domain: str = "", locations_limit: int = 50,
            progress=None, stars: bool = True, stars_limit: int = 3,
            shot: bool = True) -> dict:
    """
    Everything the reputation section renders, or an honest empty.

    Each scan is wrapped on its own. DataForSEO answers four different
    databases here and they do not fail together: the listings database can be
    fine while autocomplete is rate-limited. Losing one panel is a smaller
    error than losing the section, and a panel that failed says so rather than
    rendering as "nothing found", which is the difference between "no
    complaints exist" and "we did not look".

    `progress(name)` is called before each scan. It is not decoration: four
    scans, each able to spend a 90-second timeout and a rate-limit wait on top
    of it, sit behind a single status message otherwise - and a phase that can
    run longer than the stall detector's patience without saying a word gets
    reported to the operator as a dead worker. Same lesson as the screenshot
    block; see the note there.
    """
    out = {"brand": brand, "domain": domain, "ok": False, "errors": {}}
    if not configured():
        out["error"] = ("DataForSEO credentials are not set on this worker, "
                        "so the reputation scan did not run.")
        return out

    for name, fn in (("locations", lambda: scan_locations(
                          brand, limit=locations_limit, domain=domain)),
                     ("serp", lambda: scan_serp(brand, domain)),
                     ("terms", lambda: scan_terms(brand)),
                     ("autocomplete", lambda: scan_autocomplete(brand))):
        try:
            if progress:
                progress(name)
            out[name] = fn()
        except Exception as exc:  # noqa: BLE001
            out["errors"][name] = f"{type(exc).__name__}: {exc}"
    out["ok"] = any(k in out for k in ("locations", "serp", "terms"))

    # ---- how many of those reviews are the bad ones --------------------
    #
    # "4.8 from 227 reviews" is the number the client already knows and feels
    # fine about. "Ten one-star reviews" is the number that starts the
    # conversation, and it is invisible in the average - which is the whole
    # argument of this section, one level down. The listings database gives
    # the average and the count; only the review pull gives the distribution.
    #
    # QUEUED, NOT LIVE. task_post returns immediately and the results appear a
    # minute or so later, so this polls with a hard ceiling and gives up
    # cleanly. A star breakdown is worth ~60 seconds of an audit and is worth
    # ZERO minutes of holding one hostage - the section renders without it.
    if stars and out.get("locations", {}).get("locations"):
        try:
            if progress:
                progress("reviews")
            out["stars"] = _star_bands(out["locations"]["locations"],
                                       limit=stars_limit, progress=progress)
        except Exception as exc:  # noqa: BLE001
            out["errors"]["stars"] = f"{type(exc).__name__}: {exc}"

    # ---- and a picture of the page we have just described --------------
    if shot:
        try:
            if progress:
                progress("screenshot")
            out["shot"] = serp_shot(brand, progress=progress)
        except Exception as exc:  # noqa: BLE001
            out["errors"]["shot"] = f"{type(exc).__name__}: {exc}"
    return out


# How long to wait for the queued review pulls, and how often to look.
STAR_WAIT_S = float(os.getenv("REP_STAR_WAIT_S", "90"))
STAR_POLL_S = 6.0
SHOT_WAIT_S = float(os.getenv("REP_SHOT_WAIT_S", "75"))


def serp_shot(brand: str, width=1200, height=1400, progress=None):
    """
    A real picture of page one for "<brand> reviews".

    THE ARGUMENT FOR AN IMAGE RATHER THAN THE TABLE WE ALREADY HAVE.

    The table is the analysis and the picture is the evidence, and they do
    different jobs on a client call. A row saying yelp.com sits at #2 is a
    claim about their search results; a screenshot of their search results
    showing Yelp above their own website is the thing itself, and nobody
    argues with it. The quote builder leads with this shot for exactly that
    reason.

    Two-step and queued, like the review pull: task_post returns an id, then
    /serp/screenshot renders it. The endpoint answers with an error while the
    task is still running, so a failure here is "not ready yet" far more often
    than it is a real fault - which is why it polls rather than raising, and
    why running out of patience costs a picture and nothing else.
    """
    import base64
    import urllib.request

    kw = f"{_bare(brand)} reviews"
    tp = _post("/serp/google/organic/task_post",
               [{"keyword": kw, "location_code": 2840, "language_code": "en",
                 "device": "desktop", "priority": 2}], timeout=45)
    task = (tp.get("tasks") or [{}])[0]
    tid = task.get("id")
    if not tid:
        return {"ok": False, "why": task.get("status_message")
                or "DataForSEO did not accept the screenshot task."}

    waited = 0.0
    while waited < SHOT_WAIT_S:
        time.sleep(6.0)
        waited += 6.0
        if progress:
            progress("screenshot")
        try:
            sc = _post("/serp/screenshot",
                       [{"task_id": tid, "browser_preset": "desktop",
                         "browser_screen_width": int(width),
                         "browser_screen_height": int(height)}], timeout=60)
        except Exception:  # noqa: BLE001
            continue          # still rendering; the endpoint 4xxs until it is
        try:
            url = sc["tasks"][0]["result"][0]["items"][0]["image"]
        except (KeyError, IndexError, TypeError):
            url = None
        if not url:
            continue
        # The image lives behind the same basic auth as the API.
        login = os.getenv("DFS_LOGIN", "")
        pw = os.getenv("DFS_PASSWORD", "")
        tok = base64.b64encode(f"{login}:{pw}".encode()).decode()
        req = urllib.request.Request(
            url, headers={"Authorization": f"Basic {tok}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            png = r.read()
        return {"ok": True, "keyword": kw, "png": png, "bytes": len(png)}
    return {"ok": False, "keyword": kw,
            "why": f"The screenshot was still rendering after "
                   f"{int(SHOT_WAIT_S)}s."}


def _star_bands(locations, limit=3, progress=None):
    """
    1, 2 and 3-star counts for the listings with the most to say.

    Worst-rated first, not biggest first: the point of the block is the
    listing dragging the average down, and a 4.9 with 400 reviews has nothing
    to add that the average has not already said.
    """
    rated = [l for l in locations if l.get("place_id") and l.get("rating")]
    rated.sort(key=lambda l: float(l["rating"]))
    picked = rated[:max(1, int(limit))]
    if not picked:
        return {}
    sub = reviews_submit([l["place_id"] for l in picked])
    ids = [t["id"] for t in (sub.get("tasks") or []) if t.get("ok") and t.get("id")]
    if not ids:
        return {"queued": 0,
                "note": "The review pull was not accepted by DataForSEO."}
    by_place = {l["place_id"]: l for l in picked}
    done, waited = {}, 0.0
    pending = list(ids)
    while pending and waited < STAR_WAIT_S:
        time.sleep(STAR_POLL_S)
        waited += STAR_POLL_S
        if progress:
            progress("reviews")
        res = reviews_collect(pending)
        for d in res.get("done") or []:
            loc = by_place.get(d.get("place_id")) or {}
            done[d.get("place_id") or d.get("id")] = {
                "title": d.get("title") or loc.get("title"),
                "address": loc.get("address"),
                # Kept so the report can link the row straight to the Google
                # profile rather than making the reader search for it.
                "place_id": d.get("place_id") or loc.get("place_id"),
                "rating": d.get("profile_rating") or loc.get("rating"),
                "reviews": d.get("profile_reviews") or loc.get("reviews"),
                "one": d.get("neg_1") or 0, "two": d.get("neg_2") or 0,
                "three": d.get("weak_3") or 0,
                # The pull is depth-limited and sorted worst-first, so hitting
                # the depth means there are MORE bad ones we did not see. A
                # count printed as exact when it is a floor is the kind of
                # number that gets quoted back at you.
                "at_least": bool(d.get("truncated")),
            }
        pending = res.get("pending") or []
    return {"listings": list(done.values()), "queued": len(ids),
            "pending": len(pending),
            "note": ("Still processing when the audit finished."
                     if pending else "")}


def summarize(rep: dict) -> dict:
    """
    The four numbers the section leads with.

    Derived here rather than in the renderer, so the HTML report, the PDF and
    anything later all read the same arithmetic - the rule this codebase keeps
    relearning about a figure that appears twice.
    """
    locs = (rep.get("locations") or {}).get("locations") or []
    rated = [l for l in locs if l.get("rating")]
    reviews = sum(int(l.get("reviews") or 0) for l in locs)
    avg = (round(sum(float(l["rating"]) * int(l.get("reviews") or 1)
                     for l in rated)
                 / max(1, sum(int(l.get("reviews") or 1) for l in rated)), 2)
           if rated else None)
    serp = rep.get("serp") or {}
    organic = serp.get("organic") or []
    terms = rep.get("terms") or {}
    auto = rep.get("autocomplete") or {}
    neg_suggest = []
    for _k, v in auto.items():
        if isinstance(v, dict):
            neg_suggest += v.get("negative") or []
    return {
        "locations": len(locs),
        "reviews": reviews,
        "rating": avg,
        # Weakest listing first: an average of 4.8 hides the one at 3.1, and
        # the one at 3.1 is the reason anyone reads this section.
        "worst": min(([l for l in rated] or []),
                     key=lambda l: float(l["rating"]), default=None),
        "owned_in_top10": serp.get("owned_in_top10") or 0,
        "third_party_in_top10": max(0, len(organic)
                                    - (serp.get("owned_in_top10") or 0)),
        "negative_volume": terms.get("negative_volume") or 0,
        "watch_volume": terms.get("watch_volume") or 0,
        "brand_volume": terms.get("total_volume") or 0,
        "negative_terms": [t for t in (terms.get("terms") or [])
                           if t.get("class") == "negative"][:8],
        "negative_suggestions": neg_suggest[:8],
        "negative_related": (serp.get("negative_related") or [])
                            + (serp.get("negative_pasf") or []),
        "forums": serp.get("forums") or [],
        "ai_negative": serp.get("ai_negative") or [],
        # ---- the visuals -------------------------------------------------
        #
        # THE FULL LISTS, NOT ONLY THE NEGATIVE ONES.
        #
        # Everything above is the ANALYSIS: what is wrong and how big. The
        # panels below are the EXHIBIT - Google's own suggestion drop-down,
        # reproduced, with the bad one picked out among the ordinary ones.
        # That contrast is the whole point of showing it: "complaints" sitting
        # seventh in a list of six harmless suggestions is a fact about what
        # real people type, and it lands in a way "1 negative suggestion"
        # never does. Filtering to the negatives first would throw the exhibit
        # away and keep the summary of it.
        "suggestions": [
            {"keyword": k,
             "items": list(v.get("suggestions") or []),
             "negative": list(v.get("negative") or [])}
            for k, v in auto.items()
            if isinstance(v, dict) and (v.get("suggestions") or v.get("negative"))],
        "pasf": list(serp.get("pasf") or []),
        "related": list(serp.get("related") or []),
        "pasf_negative": list(serp.get("negative_pasf") or []),
        "related_negative": list(serp.get("negative_related") or []),
        # How many phrases we dropped because they name somebody else. Printed
        # internally, never to the client - see the note in names_client. A
        # filter that silently eats input is one nobody can audit.
        "off_brand_dropped": len(serp.get("off_brand_phrases") or []),
        "stars": rep.get("stars") or {},
        "shot": bool((rep.get("shot") or {}).get("ok")),
    }
