"""
DataForSEO collector — the credentials Vici already pays for.

This replaces what would otherwise be an Ahrefs or Semrush subscription, and it
fills four gaps at once:

    /backlinks/*                    -> the 29 Off-Page rows
    /dataforseo_labs/ranked_keywords -> the Keyword Rankings table
    /on_page/lighthouse             -> Core Web Vitals + Mobile SEO
                                       (and no more PSI 429s, because Google
                                        fetches the site for DataForSEO, not
                                        from our shared Render egress IP)
    /serp/screenshot                -> the supporting evidence the proposal promises

Auth and retry semantics are copied deliberately from seo-quote's `dfs_post`,
including one hard-won detail worth preserving:

    RATE LIMITS DO NOT ARRIVE AS AN HTTP STATUS. A "40202: rates limit per
    minute exceeded" comes back inside an HTTP 200, nested in the task. Their
    code notes a quote that silently priced at $0 because of exactly this. So we
    inspect the body, and we back off with a real pause rather than the 1s a
    timeout gets — retrying immediately just spends another slot on the same
    refusal.
"""
from __future__ import annotations
import base64
import json
import os
import time
import urllib.error
import urllib.request

BASE = "https://api.dataforseo.com/v3"
TIMEOUT = int(os.getenv("DFS_TIMEOUT", "30"))
RATE_WAIT = float(os.getenv("DFS_RATE_LIMIT_WAIT", "8"))
RATE_CODES = {40202, 40203, 40204, 40205}


def configured() -> bool:
    return bool(os.getenv("DFS_LOGIN") and os.getenv("DFS_PASSWORD"))


def _rate_limited(data: dict) -> bool:
    """A rate limit is reported inside a 200. Check the envelope AND the task."""
    if not isinstance(data, dict):
        return False
    if int(data.get("status_code") or 0) in RATE_CODES:
        return True
    for t in (data.get("tasks") or []):
        if isinstance(t, dict) and int(t.get("status_code") or 0) in RATE_CODES:
            return True
    return False


def dfs_post(path: str, payload, timeout: int | None = None, retries: int = 1,
             method: str = "POST"):
    """
    One DataForSEO call, with the retry and rate-limit handling.

    `method` exists for the TASK_GET half of the queued endpoints. DataForSEO's
    async pattern is POST to task_post, then GET task_get/{id} - and a GET with
    a JSON body is rejected. The reputation module's review pull was vendored
    in already calling this with method="GET"; without the parameter it raised
    TypeError on the first line of the first pull, which would have read as
    "the review counts are unavailable" rather than as a signature mismatch.
    """
    login = os.getenv("DFS_LOGIN", "")
    pw = os.getenv("DFS_PASSWORD", "")
    token = base64.b64encode(f"{login}:{pw}".encode()).decode()
    hdrs = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
    # A GET carries no body. Sending one gets a 404 from their router, which
    # looks exactly like a task id that does not exist.
    body = json.dumps(payload).encode() if payload is not None else None
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(BASE + path, data=body, headers=hdrs,
                                         method=method)
            with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as r:
                data = json.loads(r.read())
            if attempt < retries and _rate_limited(data):
                last = RuntimeError("40202: DataForSEO per-minute rate limit")
                time.sleep(RATE_WAIT)
                continue
            if _rate_limited(data):
                raise RuntimeError("40202: DataForSEO per-minute rate limit")
            return data
        except urllib.error.HTTPError as e:
            # 4xx is a real answer about the request; repeating it wastes budget.
            if e.code < 500 or attempt >= retries:
                raise
            last = e
            time.sleep(1.0 + attempt)
        except Exception as e:
            last = e
            if attempt >= retries:
                break
            time.sleep(1.0 + attempt)
    raise last


def _result(data):
    try:
        return (data["tasks"][0]["result"] or [])
    except Exception:
        return []


def _f(status, value=None, evidence="", severity="Medium", rec="", conf=1.0,
       src="dataforseo"):
    return {"status": status, "value": value or {}, "evidence": evidence,
            "affected_pages": [], "severity": severity, "recommendation": rec,
            "confidence": conf, "source": src}


def _need(ids, reason, src="dataforseo_unconfigured"):
    return {cid: _f("Need Access", {}, reason, "Medium",
                    "Set DFS_LOGIN and DFS_PASSWORD on the worker — the same "
                    "credentials the SEO quote tool already uses.", 0.0, src)
            for cid in ids}


# ============================================================== BACKLINKS
OFF_IDS = [f"OFF-{i:02d}" for i in range(1, 30)]


def collect_backlinks(domain: str) -> dict:
    if not configured():
        return _need(OFF_IDS, "DataForSEO credentials not configured.")
    try:
        summary = _result(dfs_post("/backlinks/summary/live",
                                   [{"target": domain, "internal_list_limit": 1,
                                     "backlinks_status_type": "live"}]))
    except Exception as e:
        return _need(OFF_IDS, f"DataForSEO backlinks call failed: "
                              f"{type(e).__name__}: {e}", "dataforseo_error")
    if not summary:
        return _need(OFF_IDS, "DataForSEO returned no backlink summary for this "
                              "domain.", "dataforseo_empty")

    s = summary[0]
    out = {}
    bl = s.get("backlinks")
    rd = s.get("referring_domains")
    rank = s.get("rank")
    spam = s.get("backlinks_spam_score")
    ips = s.get("referring_ips")
    subnets = s.get("referring_subnets")
    nofollow = (s.get("referring_links_attributes") or {}).get("nofollow")
    follow = bl - nofollow if (bl is not None and nofollow is not None) else None
    broken = s.get("broken_backlinks")
    lost = s.get("referring_domains_nofollow")

    def add(cid, ok, val, ev, sev="Low", rec=""):
        out[cid] = _f("Pass" if ok else "Fail", val, ev, sev, rec)

    def info(cid, val, ev):
        """
        A measurement with no threshold behind it.

        "727 total live backlinks" is context, not a verdict — there is no
        number of backlinks that is correct. Recording it as Pass meant that
        merely RETRIEVING it counted as the site doing well, and thirteen such
        rows scored Off-Page authority 94/100 Excellent for a firm with 131
        referring domains. Info is excluded from scoring entirely, so the
        section is scored on the rows that actually judge something.
        """
        out[cid] = _f("Info", val, ev, "Low", "", 1.0, "dataforseo")

    def unmapped(cid, what):
        """
        A checkpoint this endpoint does not answer.

        The previous version reached for the nearest available number, so
        "Lost backlinks" printed the nofollow percentage and "New backlinks"
        printed a count of broken outbound pages. Wrong data under a
        confident-looking label is the one failure mode this whole tool is
        built to avoid — say we do not have it.
        """
        out[cid] = _f("Need Access", {},
                      f"Not retrieved — {what} needs an additional DataForSEO "
                      f"backlinks endpoint.", "Low",
                      "Extend the collector to the backlinks history endpoint.",
                      0.0, "dataforseo_partial")

    if bl is not None:
        info("OFF-01", {"backlinks": bl}, f"{bl:,} total live backlinks.")
    if rd is not None:
        sev = "Low" if rd >= 100 else ("Medium" if rd >= 25 else "High")
        add("OFF-02", rd >= 25, {"referring_domains": rd},
            f"{rd:,} referring domains.", sev,
            "" if rd >= 25 else "Referring-domain count is low — prioritize digital "
                                "PR, resource pages and unlinked-mention reclamation.")
    if ips is not None:
        info("OFF-03", {"referring_ips": ips}, f"{ips:,} referring IPs.")
    if subnets is not None:
        info("OFF-04", {"referring_subnets": subnets},
             f"{subnets:,} referring subnets.")
    if rank is not None:
        sev = "Low" if rank >= 200 else ("Medium" if rank >= 100 else "High")
        add("OFF-05", rank >= 100, {"dfs_rank": rank},
            f"DataForSEO domain rank {rank} (0–1000 scale).", sev)
        out["OFF-06"] = _f("Pass" if rank >= 100 else "Fail", {"dfs_rank": rank},
                           f"Authority equivalent: DataForSEO rank {rank}.", sev)
    if spam is not None:
        ok = spam <= 30
        add("OFF-08", ok, {"spam_score": spam},
            f"Backlink spam score {spam}/100.",
            "Low" if ok else "High",
            "" if ok else "Review and consider disavowing the worst referring domains.")
    if broken is not None:
        add("OFF-12", broken == 0, {"broken_backlinks": broken},
            f"{broken:,} broken backlinks pointing at missing pages.",
            "Low" if not broken else "Medium",
            "" if not broken else "Redirect the target URLs to recover this equity.")
    # OFF-18 image backlinks. Tried from the summary first — see _image_links
    # for why that alone was not enough.
    _image_links(domain, out, s, bl)
    # `referring_pages` and `referring_main_domains` come back from this
    # endpoint but answer no checkpoint in the template. Parking them on the
    # nearest free row would be the same mistake in a new place, so they are
    # dropped. The numbers live in OFF-01/OFF-02's value payload if wanted.

    # These four are NOT in the summary endpoint. They are filled by the
    # history and page-intersection calls below; if either fails, they stay
    # honestly unanswered rather than borrowing a nearby number.
    unmapped("OFF-10", "lost backlinks")
    unmapped("OFF-11", "newly gained backlinks")
    unmapped("OFF-19", "backlinks pointing specifically at the homepage")
    unmapped("OFF-20", "backlinks pointing at deep pages")

    if follow is not None and nofollow is not None and bl:
        pct = round(100 * follow / bl, 1)
        add("OFF-13", pct >= 50, {"follow_pct": pct, "follow": follow,
                                  "nofollow": nofollow},
            f"{pct}% of backlinks are follow links "
            f"({follow:,} follow / {nofollow:,} nofollow).",
            "Low" if pct >= 50 else "Medium")

    # anchors are a separate endpoint; only call it if the summary succeeded
    try:
        anchors = _result(dfs_post("/backlinks/anchors/live",
                                   [{"target": domain, "limit": 40,
                                     "backlinks_status_type": "live"}]))
        items = (anchors[0].get("items") or []) if anchors else []
        if items:
            top = [(i.get("anchor") or "(empty)", i.get("backlinks", 0))
                   for i in items[:12]]
            branded = [a for a, _ in top
                       if domain.split(".")[0].lower() in (a or "").lower()]
            out["OFF-14"] = _f("Pass" if len(set(a for a, _ in top)) > 5 else "Warning",
                               {"distinct_anchors": len(set(a for a, _ in top)),
                                "top": top[:8]},
                               f"{len(set(a for a, _ in top))} distinct anchors in the "
                               f"top {len(top)}; most common: "
                               f"{', '.join(a for a, _ in top[:3])}.", "Low")
            out["OFF-15"] = _f("Pass" if branded else "Warning",
                               {"branded_anchors": len(branded)},
                               f"{len(branded)} of the top anchors are branded.", "Low")
    except Exception:
        pass   # anchors are a bonus; never fail the section over them

    _anchor_shape(domain, out)
    _history(domain, out)
    _page_split(domain, out, rd)
    _toxicity(domain, out, spam)
    # Three Search Console rows that Google publishes and does not expose. They
    # ride along here because this is where the data already is.
    _link_reports(domain, out, bl)

    # OFF-21..29 are link PROSPECTING — competitor gap, guest posting, digital
    # PR, HARO, unlinked mentions. They are not measurements of the client's
    # site; they are the outreach work of the campaign itself. Brendan left all
    # nine blank in his audit for the same reason. Reporting them as Need
    # Access implied a missing credential, and dragged the section below the
    # coverage floor so nothing in it could be scored at all.
    PROSPECTING = {f"OFF-{i}" for i in range(21, 30)}
    for cid in OFF_IDS:
        if cid in PROSPECTING:
            out.setdefault(cid, _f(
                "N/A", {},
                "Not measured.", "Low", "", 1.0, "campaign_scope"))
        else:
            out.setdefault(cid, _f(
                "Need Access", {},
                "Not retrieved — requires an additional DataForSEO backlinks "
                "endpoint.", "Medium",
                "Each endpoint is a metered call; add them deliberately rather "
                "than all at once.", 0.0, "dataforseo_not_implemented"))
    return out


# ========================================================= RANKED KEYWORDS
def collect_rankings(domain: str, location_name: str | None = None,
                     limit: int = 25) -> dict:
    """
    The Keyword Rankings & Industry Benchmarks table.

    This is the one report section with no crawler-only path — it needs a rank
    dataset. `ranked_keywords` returns the keywords the domain ALREADY ranks
    for, with volume, difficulty and position, which is exactly the table shape
    in the audit template.
    """
    if not configured():
        return {"available": False,
                "reason": "DataForSEO credentials not configured.", "rows": []}
    payload = [{"target": domain, "limit": limit,
                "order_by": ["keyword_data.keyword_info.search_volume,desc"],
                "location_name": location_name or "United States",
                "language_name": "English"}]
    try:
        res = _result(dfs_post("/dataforseo_labs/google/ranked_keywords/live",
                               payload, timeout=60))
    except Exception as e:
        return {"available": False,
                "reason": f"ranked_keywords call failed: {type(e).__name__}: {e}",
                "rows": []}
    items = (res[0].get("items") or []) if res else []
    rows = []
    for it in items[:limit]:
        kd = it.get("keyword_data") or {}
        ki = kd.get("keyword_info") or {}
        kp = kd.get("keyword_properties") or {}
        se = (it.get("ranked_serp_element") or {}).get("serp_item") or {}
        rows.append({
            "keyword": kd.get("keyword"),
            "search_volume": ki.get("search_volume"),
            "difficulty": kp.get("keyword_difficulty"),
            "position": se.get("rank_absolute"),
            "url": se.get("url"),
            # WHICH KIND of SERP result this is. Already in the response and
            # already being thrown away — it is what answers GEO-24, and it
            # meant a checkpoint sat permanently unmeasured next to a call that
            # had the answer in it.
            "serp_type": (se.get("type") or "").lower(),
        })
    rows.sort(key=lambda r: (r["position"] or 999, -(r["search_volume"] or 0)))
    top10 = [r for r in rows if (r["position"] or 999) <= 10]
    return {"available": True, "rows": rows, "total": len(rows),
            "top10": len(top10),
            "location": location_name or "United States",
            "geo": _serp_feature_rows(rows)}


# --------------------------------------------------------- GEO-24 and GEO-25
#
# Neither of these is an AI chat platform, so the AI visibility monitor
# correctly declines to answer them and they read as unmeasured on every run.
# They are GOOGLE SERP features, and the keyword call above already returns the
# SERP element type for every keyword the domain ranks for — the answer was
# sitting in a response we were parsing four fields out of.
#
# A note on the second one, because it is a proxy and must be labeled as one.
# Google has never exposed passage ranking as a SERP feature; there is no flag
# to read. What passage ranking DOES is let one section of a long page rank for
# a specific long query, so the measurable footprint is long-tail queries where
# the site ranks with a deep page. That is evidence, not proof, and the row says
# which of the two it is.

_SNIPPET_TYPES = {"featured_snippet", "answer_box"}


def _serp_feature_rows(rows: list) -> dict:
    out = {}
    if not rows:
        return out
    ranked = [r for r in rows if r.get("position")]
    if not ranked:
        return out

    snips = [r for r in ranked if r.get("serp_type") in _SNIPPET_TYPES]
    # Only count a snippet the CLIENT owns — these rows are the client's own
    # rankings, so every one here is theirs by construction.
    if snips:
        top = sorted(snips, key=lambda r: -(r.get("search_volume") or 0))[:5]
        named = ", ".join(f"\u201c{r['keyword']}\u201d" for r in top if r.get("keyword"))
        out["GEO-24"] = _f(
            "Pass", {"featured_snippets": len(snips),
                     "keywords": [r["keyword"] for r in snips][:20]},
            f"This site owns the featured snippet for {len(snips)} "
            f"{'query' if len(snips) == 1 else 'queries'}, including {named}. "
            f"That is the answer box above the normal results, and it is what "
            f"assistants most often read from.",
            "Low", "", 1.0, "dataforseo")
    else:
        out["GEO-24"] = _f(
            "Warning", {"featured_snippets": 0, "keywords_ranked": len(ranked)},
            f"This site holds no featured snippets across the "
            f"{len(ranked):,} queries it ranks for. The snippet is the answer "
            f"box above the normal results, and it is disproportionately what "
            f"AI assistants quote.",
            "Medium",
            "Answer the question directly in the first 40-60 words under a "
            "heading that matches how it is asked.", 1.0, "dataforseo")

    # Long-tail: four words or more is the conventional line, and it is where
    # passage ranking does its work.
    longtail = [r for r in ranked
                if len((r.get("keyword") or "").split()) >= 4
                and (r["position"] or 999) <= 20]
    deep = [r for r in longtail
            if (r.get("url") or "").rstrip("/").count("/") > 2]
    if longtail:
        pct = round(100 * len(deep) / len(longtail), 1)
        out["GEO-25"] = _f(
            "Pass" if deep else "Warning",
            {"longtail_ranked": len(longtail), "on_deep_pages": len(deep),
             "pct": pct, "examples": [r["keyword"] for r in deep][:10]},
            f"{len(longtail)} long questions rank in the top 20, "
            f"{len(deep)} of them on interior pages ({pct}%). Google has no "
            f"public marker for passage ranking, so this is the visible "
            f"footprint of it rather than a direct measurement: a specific "
            f"question answered by a section of a longer page."
            if deep else
            f"{len(longtail)} long questions rank in the top 20, none of them "
            f"on an interior page. Long questions are usually answered by a "
            f"section of a deeper page, not by the homepage.",
            "Low" if deep else "Medium",
            "" if deep else "Write pages that answer specific questions in "
                            "full, with headings phrased the way people ask.",
            0.7, "dataforseo")
    else:
        out["GEO-25"] = _f(
            "Warning", {"longtail_ranked": 0},
            f"None of the {len(ranked):,} queries this site ranks for is a "
            f"long, question-shaped one. That is the traffic assistants draw "
            f"on most.",
            "Medium",
            "Publish answers to the questions customers actually ask, one "
            "question per section.", 0.7, "dataforseo")
    return out


def _keys(label: str, payload) -> None:
    """
    Log the keys a DataForSEO endpoint actually returned.

    These four calls were written without live credentials to check them
    against. Rather than guess and fail silently, every one logs the field
    names it got back the first time it runs, so one real audit tells us
    whether the parsing below is right. Cheap, and it turns "the rows are still
    empty" into "the field is called X, not Y".
    """
    try:
        item = (payload or [{}])[0]
        if isinstance(item, dict):
            print(f"[dataforseo] {label} returned keys: "
                  f"{sorted(item.keys())[:24]}", flush=True)
            for k in ("items", "history", "pages"):
                row = (item.get(k) or [{}])
                if row and isinstance(row[0], dict):
                    print(f"[dataforseo] {label}.{k}[0] keys: "
                          f"{sorted(row[0].keys())[:24]}", flush=True)
                    break
    except Exception:
        pass


def _link_types(s: dict) -> dict:
    """
    The by-type breakdown of a backlink profile, wherever this account's
    response happens to put it.

    OFF-18 read `referring_links_types["image"]` and nothing else, so when the
    key was not there the row fell through to the catch-all and told us the
    collector needed "an additional DataForSEO backlinks endpoint" — which was
    not true, and sent us looking for a call to add rather than a key to read.
    """
    for k in ("referring_links_types", "referring_links_type",
              "backlinks_types", "links_types"):
        v = s.get(k)
        if isinstance(v, dict) and v:
            return {str(kk).lower(): vv for kk, vv in v.items()}
    return {}


def _image_links(domain: str, out: dict, s: dict, bl) -> None:
    """
    OFF-18 Image backlinks.

    An image backlink is a link where the clickable thing is a picture rather
    than words — a badge, a logo, an infographic embed. They still pass
    authority, but where a text link hands Google a phrase describing the
    destination, an image link hands it the alt attribute, and an image link
    with no alt text hands it nothing at all. That is the part worth reporting,
    and it is why this is not simply a count.
    """
    types = _link_types(s)
    n = types.get("image")
    if n is None:
        print(f"[dataforseo] summary has no image link-type count; "
              f"top-level keys are {sorted(s)[:24]}", flush=True)
        # The dedicated endpoint. One metered call, made only when the summary
        # did not already carry the answer.
        try:
            res = _result(dfs_post("/backlinks/backlinks/live",
                                   [{"target": domain, "limit": 1000,
                                     "backlinks_status_type": "live",
                                     "mode": "as_is"}]))
        except Exception as e:  # noqa: BLE001
            print(f"[dataforseo] backlinks/backlinks failed: "
                  f"{type(e).__name__}: {e}", flush=True)
            return
        items = (res[0].get("items") or []) if res else []
        if not items:
            return
        _keys("backlinks", res)
        imgs = [i for i in items
                if str(i.get("item_type") or i.get("type") or "").lower() == "image"]
        n = len(imgs)
        sampled = len(items)
        noalt = sum(1 for i in imgs if not _str(i, "alt", "text", "anchor"))
        pct = round(100 * n / sampled, 1)
        # A sample, and it says so — same rule as the URL Inspection rows.
        out["OFF-18"] = _f(
            "Info", {"image_backlinks": n, "sampled": sampled,
                     "pct": pct, "without_alt_text": noalt},
            f"{n:,} of the {sampled:,} most recent backlinks come through an "
            f"image rather than text ({pct}%)"
            + (f"; {noalt:,} of those carry no alt text, so they pass authority "
               f"but no description of what they point at." if noalt else "."),
            "Low", "", 1.0, "dataforseo")
        return

    n = int(n or 0)
    share = f" ({round(100 * n / bl, 1)}% of the profile)" if bl else ""
    out["OFF-18"] = _f(
        "Info", {"image_backlinks": n, "link_types": types},
        f"{n:,} backlinks come through an image rather than text{share}. "
        f"An image link passes authority, but only its alt text describes what "
        f"it points at.", "Low", "", 1.0, "dataforseo")


def _anchor_shape(domain: str, out: dict) -> None:
    """
    OFF-13 follow/nofollow ratio, OFF-16 exact-match, OFF-17 naked-URL anchors.

    All three are distributions over anchors, which is one endpoint, so they
    are answered together or not at all.
    """
    try:
        res = _result(dfs_post("/backlinks/anchors/live",
                               [{"target": domain, "limit": 200,
                                 "backlinks_status_type": "live"}]))
    except Exception as e:  # noqa: BLE001
        return
    _keys("anchors", res)
    items = (res[0].get("items") or []) if res else []
    if not items:
        return
    # THE FIELD IS NOT CALLED `dofollow`. DataForSEO reports a total and a
    # NOFOLLOW count; the followed figure is the difference between them. The
    # previous version read a `dofollow` key that does not exist in this
    # response, summed nothing, and reported 0% followed on a live profile.
    total = sum(_num(i, "referring_pages", "backlinks", "referring_domains")
                for i in items)
    nofollow = sum(_num(i, "referring_pages_nofollow", "backlinks_nofollow",
                        "referring_domains_nofollow") for i in items)
    dofollow = total - nofollow
    if nofollow == 0 and not any(
            k in items[0] for k in ("referring_pages_nofollow",
                                    "backlinks_nofollow",
                                    "referring_domains_nofollow")):
        # No nofollow field at all in the payload — we cannot compute a ratio,
        # and 100% followed would be a fabrication rather than a measurement.
        dofollow = 0
    # A ZERO FROM A FAILED PARSE IS NOT A FINDING.
    #
    # This shipped "0.0% of backlinks are followed" for a site with 727
    # backlinks, because the field is not called what I guessed and every sum
    # came out empty. An implausible zero next to a non-zero total is a parse
    # failure, and reporting it as a measurement is the same class of error as
    # putting the wrong metric under a confident label. Say we could not read
    # it, and log what the fields were actually called.
    if not total or (dofollow == 0 and total > 0):
        _unreadable(out, ["OFF-13", "OFF-16", "OFF-17"], "anchors", items[0])
        return
    pct = round(100 * dofollow / total, 1)
    out["OFF-13"] = _f("Pass" if pct >= 50 else "Warning",
                       {"dofollow_pct": pct, "backlinks": total},
                       f"{pct}% of backlinks are followed.",
                       "Low" if pct >= 50 else "Medium",
                       "" if pct >= 50 else "A profile this heavily nofollowed "
                                            "passes little authority; weight "
                                            "outreach toward editorial links.")

    bare = domain.lower().replace("www.", "")
    brand = bare.split(".")[0]
    exact, naked = 0, 0
    for i in items:
        a = _str(i, "anchor").lower()
        n = _num(i, "referring_pages", "backlinks", "referring_domains")
        if not a:
            continue
        if a.startswith(("http://", "https://", "www.")) or a.rstrip("/") == bare:
            naked += n
        elif brand not in a and 1 <= len(a.split()) <= 4:
            exact += n
    e_pct = round(100 * exact / total, 1)
    n_pct = round(100 * naked / total, 1)
    # Over-optimized anchor text is a penalty risk; the threshold is the
    # conventional one rather than anything DataForSEO computes for us.
    out["OFF-16"] = _f("Pass" if e_pct < 20 else "Warning",
                       {"exact_match_pct": e_pct},
                       f"{e_pct}% of backlinks use a short non-branded anchor.",
                       "Low" if e_pct < 20 else "Medium",
                       "" if e_pct < 20 else "A high share of keyword-exact "
                                             "anchors reads as manipulation.")
    out["OFF-17"] = _f("Info", {"naked_url_pct": n_pct},
                       f"{n_pct}% of backlinks use a bare URL as the anchor.",
                       "Low", "", 1.0, "dataforseo")


def _history(domain: str, out: dict) -> None:
    """OFF-10 lost and OFF-11 new backlinks, from the history endpoint."""
    try:
        res = _result(dfs_post("/backlinks/history/live",
                               [{"target": domain, "date_from": _months_ago(3)}]))
    except Exception:  # noqa: BLE001
        return
    _keys("history", res)
    items = (res[0].get("items") or []) if res else []
    if not items:
        return
    new = sum(int(i.get("new_backlinks") or 0) for i in items)
    lost = sum(int(i.get("lost_backlinks") or 0) for i in items)
    net = new - lost
    out["OFF-11"] = _f("Pass" if new else "Warning", {"new_backlinks": new},
                       f"{new:,} new backlinks in the last 90 days.",
                       "Low" if new else "Medium",
                       "" if new else "No new links in a quarter means the "
                                      "profile is static while competitors move.")
    out["OFF-10"] = _f("Pass" if net >= 0 else "Warning",
                       {"lost_backlinks": lost, "net": net},
                       f"{lost:,} backlinks lost in the last 90 days "
                       f"(net {net:+,}).",
                       "Low" if net >= 0 else "Medium",
                       "" if net >= 0 else "Losing links faster than earning "
                                           "them — check for removed pages and "
                                           "expired placements.")


def _page_split(domain: str, out: dict, rd) -> None:
    """
    OFF-19 homepage vs OFF-20 deep-page backlinks, and GSC-22 top linked pages.

    WHY THIS NO LONGER USES /backlinks/domain_pages/live.
    -----------------------------------------------------
    It did, and the parse failed on every run. The field names that endpoint
    actually returned were:

        content_encoding, domain, encoded_size, fetch_time, first_visited,
        ip, location, main_domain

    No backlink count. No page URL. Those are the fields of a HOST — how it was
    fetched, where it resolves, when it was first seen — which means the
    endpoint answers a different question from the one we were asking it, and no
    amount of tolerant key-matching was going to find a page count in a record
    that does not contain one. Three rounds of increasingly desperate fallbacks
    went looking for a number that was never there.

    The individual backlinks endpoint is unambiguous: every backlink names the
    URL it points AT. Grouping by that gives homepage versus interior and the
    most-linked pages in one pass, from a call this collector already makes for
    OFF-18. One request, three rows, nothing inferred.
    """
    try:
        res = _result(dfs_post("/backlinks/backlinks/live",
                               [{"target": domain, "limit": 1000,
                                 "backlinks_status_type": "live",
                                 "mode": "as_is"}]))
    except Exception as e:  # noqa: BLE001
        print(f"[dataforseo] backlinks (for page split) failed: "
              f"{type(e).__name__}: {e}", flush=True)
        return
    items = (res[0].get("items") or []) if res else []
    if not items:
        return
    _keys("backlinks_pages", res)

    # Count DISTINCT referring links per target page. A single site linking a
    # page forty times is one endorsement, not forty, and the homepage/interior
    # ratio is exactly where that distortion would land.
    from collections import defaultdict
    per_page = defaultdict(set)
    for i in items:
        tgt = _str(i, "url_to", "target_url", "page_to", "url")
        src = _str(i, "url_from", "domain_from", "page_from") or str(id(i))
        if tgt:
            per_page[tgt].add(src)
    if not per_page:
        _unreadable(out, ["OFF-19", "OFF-20", "GSC-22"], "backlinks", items[0])
        return

    def _is_home(u: str) -> bool:
        path = u.split("//")[-1].split("/", 1)
        return len(path) == 1 or path[1].strip("/") == ""

    home = sum(len(v) for u, v in per_page.items() if _is_home(u))
    deep = sum(len(v) for u, v in per_page.items() if not _is_home(u))
    total = home + deep
    if not total:
        _unreadable(out, ["OFF-19", "OFF-20", "GSC-22"], "backlinks", items[0])
        return

    sampled = len(items)
    scope = (f" (from the {sampled:,} most recent backlinks)"
             if sampled >= 1000 else "")
    d_pct = round(100 * deep / total, 1)
    out["OFF-19"] = _f("Info", {"homepage_backlinks": home, "sampled": sampled},
                       f"{home:,} referring links point at the homepage{scope}.",
                       "Low", "", 1.0, "dataforseo")
    out["OFF-20"] = _f("Pass" if d_pct >= 20 else "Warning",
                       {"deep_backlinks": deep, "deep_pct": d_pct,
                        "sampled": sampled},
                       f"{deep:,} referring links point at interior pages "
                       f"({d_pct}% of the profile){scope}.",
                       "Low" if d_pct >= 20 else "Medium",
                       "" if d_pct >= 20 else "Almost every link points at the "
                                              "homepage, so service and "
                                              "location pages have no authority "
                                              "of their own.")

    ranked = sorted(((u, len(v)) for u, v in per_page.items()),
                    key=lambda t: -t[1])
    top = ranked[0]
    out["GSC-22"] = _f(
        "Info", {"top_linked_pages": ranked[:10], "pages": len(ranked),
                 "sampled": sampled},
        f"The most-linked page is {top[0]} with {top[1]:,} referring links; "
        f"{len(ranked):,} pages on the site have links pointing at them. "
        f"{_NOT_GSC}", "Low", "", 1.0, "dataforseo")


def _toxicity(domain: str, out: dict, spam) -> None:
    """
    OFF-07 trust and OFF-09 toxic backlinks.

    DataForSEO has no "trust score" field, so OFF-07 is answered from the
    inverse of the spam score and SAYS SO rather than inventing a metric name
    the vendor does not publish.
    """
    # TRUST SCORE.
    #
    # DataForSEO publishes no trust metric. The real ones are Majestic's Trust
    # Flow and Moz's Domain Authority, and neither is in this account. Deriving
    # a number from the spam score and calling it a Trust Score is a proxy
    # wearing a vendor's name — the exact pattern that put four wrong metrics
    # under confident labels last week. So it is Info: the figure is offered as
    # context, and the row says where a real trust score would come from.
    if spam is not None:
        out["OFF-07"] = _f("Info", {"spam_score": int(spam)},
                           f"No trust score is available from this provider. "
                           f"For context, the backlink spam score is "
                           f"{int(spam)}/100. A true trust metric (Majestic "
                           f"Trust Flow, Moz Domain Authority) needs a "
                           f"subscription we do not currently hold.",
                           "Low", "", 1.0, "dataforseo")
    try:
        res = _result(dfs_post("/backlinks/referring_domains/live",
                               [{"target": domain, "limit": 200,
                                 "backlinks_status_type": "live",
                                 "order_by": ["backlinks_spam_score,desc"]}]))
    except Exception:  # noqa: BLE001
        return
    _keys("referring_domains", res)
    items = (res[0].get("items") or []) if res else []
    if not items:
        return
    toxic = [i for i in items
             if int(i.get("backlinks_spam_score") or 0) >= 60]
    pct = round(100 * len(toxic) / len(items), 1)
    out["OFF-09"] = _f("Pass" if pct < 10 else "Warning",
                       {"toxic_domains": len(toxic), "sampled": len(items),
                        "pct": pct},
                       f"{len(toxic)} of the {len(items)} highest-spam referring "
                       f"domains score 60+ ({pct}% of the sample).",
                       "Low" if pct < 10 else "Medium",
                       "" if pct < 10 else "Review the worst of these and "
                                           "consider a disavow file.")


# Every row below answers a report Search Console PUBLISHES but exposes through
# no API. We are answering it from a different index, and the numbers will not
# match what someone sees if they open Search Console and compare — ours are
# generally larger, because Google's Links report shows a sample and a backlink
# index does not. A reader who spots the discrepancy unaided stops trusting the
# whole document, so every one of these rows says where its number came from.
_NOT_GSC = ("Measured from our backlink index rather than Search Console, which "
            "publishes this report but offers no API for it; Search Console "
            "shows a sample, so its own figure will be lower.")


def _link_reports(domain: str, out: dict, bl) -> None:
    """
    GSC-20 External links and GSC-21 Top linking sites.

    These were bucketed as "an analyst opens Search Console and reads it off",
    which is the kind of plan that means it never happens — and it was never
    necessary. Both questions are answered by data this collector already pays
    for and already fetches for the Off-Page section.
    """
    if bl is not None:
        out["GSC-20"] = _f("Info", {"external_links": bl},
                           f"{bl:,} external links point at this site. {_NOT_GSC}",
                           "Low", "", 1.0, "dataforseo")
    # A second referring-domains call, ordered by link volume. The one the
    # toxicity check makes is ordered by SPAM score, so its 200 rows are the
    # worst neighbours rather than the biggest linkers — sorting that sample by
    # backlinks would confidently name a "top linking site" that is merely the
    # most linked of the 200 diciest ones.
    try:
        res = _result(dfs_post("/backlinks/referring_domains/live",
                               [{"target": domain, "limit": 50,
                                 "backlinks_status_type": "live",
                                 "order_by": ["backlinks,desc"]}]))
    except Exception as e:  # noqa: BLE001
        print(f"[dataforseo] referring_domains (by volume) failed: "
              f"{type(e).__name__}: {e}", flush=True)
        return
    items = (res[0].get("items") or []) if res else []
    if not items:
        return
    sites = [(_str(i, "domain", "referring_domain", "target", "url"),
              _num(i, "backlinks", "referring_pages")) for i in items]
    sites = [(d, n) for d, n in sites if d and n]
    if not sites:
        _unreadable(out, ["GSC-21"], "referring_domains", items[0])
        return
    named = ", ".join(f"{d} ({n:,})" for d, n in sites[:5])
    out["GSC-21"] = _f("Info", {"top_linking_sites": sites[:20]},
                       f"The sites linking most often are {named}. {_NOT_GSC}",
                       "Low", "", 1.0, "dataforseo")


def _any_num(item: dict, *contains) -> int:
    """
    Last resort: the first integer whose KEY contains one of these words.

    Used only after every named candidate has missed. It is a guess, but a
    bounded one — it will not invent a number from an unrelated field, because
    the key still has to mention what we are counting. The alternative is a
    zero, and a zero here is indistinguishable from a real answer.
    """
    for k, v in (item or {}).items():
        kl = str(k).lower()
        if any(c in kl for c in contains) and isinstance(v, (int, float)) and v:
            return int(v)
    return 0


def _num(item: dict, *names, default=0) -> int:
    """
    First key that is actually present, as an integer.

    Written after two rounds of the same bug. A parser that reads ONE guessed
    field name and silently yields zero when the guess is wrong produces a
    confident, wrong number — "0.0% of backlinks are followed" on a profile with
    727 backlinks. Naming every plausible key and taking the first one present
    costs nothing and removes the whole class of failure.
    """
    for n in names:
        v = item.get(n)
        if v is None:
            continue
        try:
            return int(float(v))
        except (TypeError, ValueError):
            continue
    return default


def _str(item: dict, *names, default="") -> str:
    for n in names:
        v = item.get(n)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default


def _unreadable(out: dict, ids: list, endpoint: str, sample: dict) -> None:
    """
    The endpoint answered, but not in the shape we parse.

    Logs the field names it DID return, so the fix is a one-line rename rather
    than another round of guessing. The rows stay Need Access — an implausible
    zero presented as a measurement is worse than an honest gap.
    """
    keys = sorted(sample.keys())[:20] if isinstance(sample, dict) else []
    print(f"[dataforseo] {endpoint} parsed to zero — field names are {keys}",
          flush=True)
    for cid in ids:
        out[cid] = _f("Need Access", {"endpoint": endpoint, "fields": keys},
                      f"The {endpoint} endpoint answered but not in the shape "
                      f"we read; the numbers would have been wrong, so nothing "
                      f"is reported.", "Low",
                      f"Field names returned: {', '.join(keys[:8])}.",
                      0.0, "dataforseo_shape")


def _months_ago(n: int) -> str:
    from datetime import date, timedelta
    d = date.today() - timedelta(days=30 * n)
    return d.isoformat()


# ============================================================== LIGHTHOUSE
LIGHTHOUSE_IDS = ["PERF-10", "PERF-11", "PERF-12", "PERF-13", "PERF-14", "PERF-19",
                  "MOB-03", "MOB-04", "MOB-05", "MOB-06"]


def lighthouse_report(url: str):
    """
    The raw Lighthouse report, for anything that wants to read audits directly.

    `collect_lighthouse` turns this into ten findings. Everything ELSE that
    reads Lighthouse — compression, minification, tap targets, font size,
    accessibility, resource weight — goes through PageSpeed Insights, which is
    unreachable from Render often enough that fourteen rows arrived in a client
    report carrying our own timeout message.

    Returning the report itself lets perf.py fall back to this provider through
    a single accessor, so every check that reads Lighthouse gets the fallback
    without knowing the fallback exists.
    """
    if not configured():
        return None, "DataForSEO credentials not configured"
    try:
        res = _result(dfs_post("/on_page/lighthouse/live/json",
                               [{"url": url, "for_mobile": True,
                                 "categories": ["performance", "accessibility",
                                                "best-practices", "seo"]}],
                               timeout=180))
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    if not res:
        return None, "Lighthouse returned no result"
    r0 = res[0] if isinstance(res[0], dict) else {}
    lh = (r0.get("lighthouse_result")
          or (r0.get("items") or [{}])[0]
          or {})
    return (lh if lh.get("audits") else None,
            None if lh.get("audits") else "Lighthouse result carried no audits")


def collect_lighthouse(url: str) -> dict:
    """
    Core Web Vitals + the Mobile rows, via DataForSEO's hosted Lighthouse.

    Two problems solved at once. PageSpeed Insights was returning 429 because
    unauthenticated calls share a per-IP pool with every other anonymous caller
    on Render's egress. And Google retired the Mobile-Friendly Test API, whose
    replacement is exactly Lighthouse — which is what MOB-03..06 now read.
    """
    if not configured():
        return _need(LIGHTHOUSE_IDS, "DataForSEO credentials not configured.")
    try:
        res = _result(dfs_post("/on_page/lighthouse/live/json",
                               [{"url": url, "for_mobile": True,
                                 "categories": ["performance", "accessibility",
                                                "best-practices", "seo"]}],
                               timeout=120))
    except Exception as e:
        return _need(LIGHTHOUSE_IDS,
                     f"Lighthouse call failed: {type(e).__name__}: {e}",
                     "dataforseo_error")
    if not res:
        return _need(LIGHTHOUSE_IDS, "Lighthouse returned no result.",
                     "dataforseo_empty")

    lh = (res[0].get("lighthouse_result") or res[0].get("items", [{}])[0]
          if isinstance(res[0], dict) else {}) or {}
    audits = lh.get("audits") or {}
    cats = lh.get("categories") or {}

    def num(key):
        a = audits.get(key) or {}
        return a.get("numericValue"), a.get("displayValue")

    def band(v, good, poor, label, cid, unit="ms"):
        if v is None:
            return _f("Need Access", {}, f"{label} not returned by Lighthouse.",
                      "Medium", "", 0.0, "dataforseo_partial")
        st = "Pass" if v <= good else ("Warning" if v <= poor else "Fail")
        return _f(st, {"value": round(v, 3), "good": good, "poor": poor},
                  f"{label}: {round(v,1)}{unit} (good ≤ {good}{unit}).",
                  {"Pass": "Low", "Warning": "Medium", "Fail": "High"}[st],
                  "" if st == "Pass" else f"Reduce {label} to at or below {good}{unit}.")

    out = {}
    lcp, _ = num("largest-contentful-paint")
    cls, _ = num("cumulative-layout-shift")
    ttfb, _ = num("server-response-time")
    tbt, _ = num("total-blocking-time")

    out["PERF-11"] = band(lcp, 2500, 4000, "Largest Contentful Paint", "PERF-11")
    out["PERF-13"] = band(cls, 0.1, 0.25, "Cumulative Layout Shift", "PERF-13", "")
    out["PERF-14"] = band(ttfb, 800, 1800, "Time to First Byte", "PERF-14")
    # INP cannot be measured in a lab run; TBT is the accepted lab proxy and we
    # say so rather than presenting it as INP.
    out["PERF-12"] = (_f("Warning" if tbt and tbt > 200 else "Pass",
                         {"total_blocking_time_ms": tbt, "proxy_for": "INP"},
                         # WAS: "a LAB PROXY for INP, which can only be
                         # measured from real user traffic" — shouted, and
                         # three clauses about our method before the reader
                         # gets to what it means for them.
                         f"Total Blocking Time is {round(tbt or 0)}ms. This "
                         f"stands in for INP, which needs real visitor data "
                         f"Google has not published for this site yet.",
                         "Medium" if tbt and tbt > 200 else "Low", "", 0.6)
                      if tbt is not None else
                      _f("Need Access", {}, "INP requires field data.", "Low", "", 0.0))

    perf = (cats.get("performance") or {}).get("score")
    if perf is not None:
        pct = round(perf * 100)
        out["PERF-10"] = _f("Pass" if pct >= 90 else ("Warning" if pct >= 50 else "Fail"),
                            {"lighthouse_performance": pct},
                            f"Lighthouse mobile performance score {pct}/100.",
                            "Low" if pct >= 90 else ("Medium" if pct >= 50 else "High"))

    img_fail = [k for k in ("uses-optimized-images", "modern-image-formats",
                            "uses-responsive-images", "efficient-animated-content")
                if (audits.get(k) or {}).get("score") not in (1, None)]
    out["PERF-19"] = _f("Fail" if img_fail else "Pass", {"failing": img_fail},
                        f"{len(img_fail)} image-optimization audits failing: "
                        f"{', '.join(img_fail)}." if img_fail
                        else "Image optimization audits pass.",
                        "Medium" if img_fail else "Low",
                        "Serve next-gen formats and correctly sized images."
                        if img_fail else "")

    # ---- Mobile rows: the documented replacement for the retired
    #      Mobile-Friendly Test is Lighthouse. These are that reroute.
    vp = (audits.get("viewport") or {}).get("score")
    out["MOB-03"] = _f("Pass" if vp == 1 else "Fail", {"viewport_audit": vp},
                       "Lighthouse mobile viewport audit passes."
                       if vp == 1 else
                       "Lighthouse reports the page is not sized for mobile viewports.",
                       "Low" if vp == 1 else "High")
    out["MOB-04"] = _f("Pass" if vp == 1 else "Fail", {"responsive": vp == 1},
                       "Responsive rendering confirmed by the mobile Lighthouse run."
                       if vp == 1 else "Mobile rendering issues detected.",
                       "Low" if vp == 1 else "High")
    tap = (audits.get("tap-targets") or {}).get("score")
    out["MOB-05"] = (_f("Pass" if tap == 1 else "Fail", {"tap_targets": tap},
                        "Touch targets are appropriately sized and spaced."
                        if tap == 1 else
                        "Touch targets are too small or too close together.",
                        "Low" if tap == 1 else "Medium",
                        "" if tap == 1 else "Increase tap-target size to at least 48x48px.")
                     if tap is not None else
                     _f("Need Access", {}, "Tap-target audit not returned.", "Low",
                        "", 0.0))
    fs = (audits.get("font-size") or {}).get("score")
    out["MOB-06"] = (_f("Pass" if fs == 1 else "Fail", {"font_size": fs},
                        "Font sizes are legible on mobile." if fs == 1 else
                        "Text is too small to read on mobile without zooming.",
                        "Low" if fs == 1 else "Medium")
                     if fs is not None else
                     _f("Need Access", {}, "Font-size audit not returned.", "Low",
                        "", 0.0))

    for cid in LIGHTHOUSE_IDS:
        out.setdefault(cid, _f("Need Access", {},
                               "Not returned by the Lighthouse run.", "Low", "", 0.0,
                               "dataforseo_partial"))
    return out


# ============================================================== SCREENSHOT
def capture_screenshot(url: str) -> dict | None:
    """Supporting evidence — the proposal promises screenshots."""
    if not configured():
        return None
    try:
        res = _result(dfs_post("/serp/screenshot", [{"url": url}], timeout=90))
        if res and res[0].get("items"):
            return {"url": url, "image_url": res[0]["items"][0].get("image_url")}
        if res and res[0].get("image_url"):
            return {"url": url, "image_url": res[0]["image_url"]}
    except Exception:
        return None
    return None
