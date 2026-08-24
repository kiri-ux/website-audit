"""
Response analysis — turning raw AI answers into the metrics that matter.

Four measurements, in increasing order of commercial value:

  mentioned    the brand name appears in the answer
  cited        the client's DOMAIN appears in the answer's sources  ← the real metric
  prominence   how early in the answer the brand appears
  share of voice  which brands/domains got cited INSTEAD

"Mentioned" is the vanity metric. An AI system can name a brand from training
data while citing five competitors as sources — the citation is what drives
referral traffic and what a content/PR retainer can actually move.

The hard part is false positives. A brand like "Grand Home Furnishings" must not
match the word "grand" in "a grand total". Everything below is built around
avoiding that, because an inflated mention rate is worse than no metric: it tells
the client they're fine when they aren't.
"""
from __future__ import annotations
import math
import re
from collections import Counter, defaultdict
from urllib.parse import urlparse

# Words that make a token useless as a brand signal on its own.
STOPWORDS = {
    "the", "and", "for", "with", "your", "our", "best", "top", "home", "group",
    "company", "co", "inc", "llc", "ltd", "corp", "store", "shop", "online",
    "services", "service", "solutions", "grand", "first", "national", "american",
    "quality", "value", "center", "centre", "direct", "plus", "pro", "prime",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).strip()


def _domain(u: str) -> str:
    try:
        h = urlparse(u).netloc.lower()
    except Exception:
        return ""
    return h[4:] if h.startswith("www.") else h


def brand_patterns(brand: str, aliases: list[str] | None = None) -> list[re.Pattern]:
    """
    Build match patterns for a brand, ordered strongest first.

    Rules that prevent the false positives:
      * The full brand name always matches (word-bounded).
      * A shortened form is only allowed if it is >= 2 tokens, OR a single token
        that is long and not a stopword. "Grand Home" is allowed; bare "Grand"
        is not. "Wayfair" is allowed because it is distinctive.
      * Everything is word-bounded, so "Wayfairish" does not match.
    """
    names = [brand] + list(aliases or [])
    pats, seen = [], set()

    def add(text):
        t = _norm(text)
        if not t or t in seen:
            return
        seen.add(t)
        pats.append(re.compile(r"\b" + r"[\s\-]+".join(map(re.escape, t.split())) + r"\b",
                               re.I))

    for n in names:
        add(n)
        toks = _norm(n).split()
        # drop trailing corporate suffixes: "Acme Furniture Inc" -> "Acme Furniture"
        while len(toks) > 2 and toks[-1] in STOPWORDS:
            toks = toks[:-1]
            add(" ".join(toks))
        if len(toks) >= 2:
            add(" ".join(toks[:2]))
        elif len(toks) == 1 and len(toks[0]) >= 6 and toks[0] not in STOPWORDS:
            add(toks[0])
    return pats


def detect_mention(text: str, pats: list[re.Pattern]) -> dict:
    if not text:
        return {"mentioned": False, "hits": 0, "first_at": None, "prominence": 0.0}
    hits, first = 0, None
    for p in pats:
        for m in p.finditer(text):
            hits += 1
            if first is None or m.start() < first:
                first = m.start()
    # Prominence: 1.0 = first sentence, decaying to 0 at the end of the answer.
    prom = 0.0
    if first is not None and len(text):
        prom = round(max(0.0, 1.0 - (first / max(1, len(text)))), 3)
    return {"mentioned": hits > 0, "hits": hits, "first_at": first, "prominence": prom}


def analyse_answer(ans, profile) -> dict:
    """
    One answer -> one structured result row.

    `profile` needs .brand, .domain, .aliases, .competitors.
    """
    pats = brand_patterns(profile.brand, profile.aliases)
    m = detect_mention(ans.text, pats)

    client_domain = _domain("http://" + profile.domain) or profile.domain.lower()
    cited_domains = [c["domain"] for c in ans.citations if c.get("domain")]
    cited = any(d == client_domain or d.endswith("." + client_domain)
                for d in cited_domains)

    # Competitors: named ones matched in text, plus every OTHER domain cited.
    # The second half is what surfaces rivals the client never listed.
    comp_mentions = {}
    for comp in profile.competitors or []:
        cm = detect_mention(ans.text, brand_patterns(comp))
        if cm["mentioned"]:
            comp_mentions[comp] = cm["hits"]

    other_domains = [d for d in cited_domains
                     if d != client_domain and not d.endswith("." + client_domain)]

    return {
        "platform": ans.platform,
        "query_id": ans.query_id,
        "ok": ans.ok,
        "error": ans.error,
        "mentioned": m["mentioned"],
        "mention_hits": m["hits"],
        "prominence": m["prominence"],
        "cited": cited,
        "citation_count": len(ans.citations),
        "cited_domains": cited_domains,
        "other_domains": other_domains,
        "competitor_mentions": comp_mentions,
        "citation_shape": ans.citation_shape,
        "latency_ms": ans.latency_ms,
        "answer_chars": len(ans.text or ""),
    }


def aggregate(results: list[dict], queries_by_id: dict, profile) -> dict:
    """
    Roll per-answer rows into the report numbers.

    Rates are computed over SUCCESSFUL answers only. Counting a provider error as
    "not mentioned" would silently depress the metric and make an outage look
    like a visibility collapse.
    """
    ok = [r for r in results if r["ok"]]
    errs = [r for r in results if not r["ok"]]

    def rate(rows, key):
        return round(100 * sum(1 for r in rows if r[key]) / len(rows), 1) if rows else None

    # ---- HOW MUCH OF THAT NUMBER IS REAL --------------------------------
    #
    # THE RATE WITHOUT AN INTERVAL IS THE MOST MISLEADING FIGURE WE PRINT.
    #
    # These are stochastic systems answering a small panel. Ask the same forty
    # questions twice and the mention rate moves several points on its own,
    # with nothing about the client having changed. Reported as a bare "12%"
    # it invites exactly the reading it cannot support: that next month's 18%
    # is progress. Most of the market ships the bare number; Evertune samples
    # each prompt up to a hundred times precisely because of this.
    #
    # A Wilson score interval is the right tool for a proportion on a small n:
    # unlike the textbook normal approximation it stays inside 0-100 and does
    # not collapse to zero width when the count is 0 or n, which is exactly
    # where a local panel spends most of its time. What it buys us is the
    # honest sentence - "12%, give or take 6 points" - and the ability to
    # refuse a comparison that sits inside the noise.
    def interval(rows, key, z=1.96):
        n = len(rows)
        if not n:
            return None
        k = sum(1 for r in rows if r[key])
        ph = k / n
        d = 1 + z * z / n
        centre = (ph + z * z / (2 * n)) / d
        half = (z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))) / d
        return {"n": n, "hits": k,
                "low": round(100 * max(0.0, centre - half), 1),
                "high": round(100 * min(1.0, centre + half), 1),
                "plus_minus": round(100 * half, 1)}

    by_platform = {}
    for p in sorted({r["platform"] for r in ok}):
        rows = [r for r in ok if r["platform"] == p]
        by_platform[p] = {
            "answers": len(rows),
            "mention_rate": rate(rows, "mentioned"),
            "citation_rate": rate(rows, "cited"),
            "avg_prominence": round(sum(r["prominence"] for r in rows) / len(rows), 3),
            "avg_citations": round(sum(r["citation_count"] for r in rows) / len(rows), 1),
            "errors": sum(1 for r in errs if r["platform"] == p),
        }

    # WHY A PLATFORM RETURNED NOTHING, NOT JUST THAT IT DID.
    #
    # `by_platform` is built from SUCCESSFUL answers, so a platform where every
    # call failed does not appear in it at all — and the checkpoint row then
    # said "no successful responses collected" and stopped. The provider had
    # raised something specific ("DataForSEO SERP returned 40401: invalid
    # credentials"); it reached a counter and died there.
    #
    # This is the same shape as every other bug in this codebase: an error
    # carried inside a success needs unwrapping, or it is not an error to
    # anyone downstream. The messages travel now, deduplicated, so the row can
    # name the cause instead of describing the silence.
    platform_errors = {}
    for p in sorted({r["platform"] for r in errs}):
        msgs, seen_msg = [], set()
        for r in errs:
            if r["platform"] != p:
                continue
            m = str(r.get("error") or "").strip()
            if m and m not in seen_msg:
                seen_msg.add(m)
                msgs.append(m)
        platform_errors[p] = {
            "errors": sum(1 for r in errs if r["platform"] == p),
            "successes": sum(1 for r in ok if r["platform"] == p),
            "messages": msgs[:3],
        }

    # ---- PER MARKET, NEVER BLENDED --------------------------------------
    #
    # The single biggest measurement problem with a local business: one number
    # across Knoxville, Clinton and Farragut is an average of three different
    # answers, and the average is true of none of them. A firm invisible in
    # one county and fine in another reads as "moderately visible everywhere",
    # which is both wrong and unactionable - there is no campaign you can run
    # against an average.
    #
    # Questions that name no place (brand questions, generic open questions)
    # are deliberately excluded rather than pooled into a market they never
    # mentioned. `n` travels with every row so the reader can see which
    # markets have enough answers behind them to be worth reading.
    by_market = {}
    _mkts = {getattr(queries_by_id.get(r["query_id"]), "market", "")
             for r in ok}
    for mkt in sorted(m for m in _mkts if m):
        rows = [r for r in ok
                if getattr(queries_by_id.get(r["query_id"]), "market", "") == mkt]
        by_market[mkt] = {
            "answers": len(rows),
            "questions": len({r["query_id"] for r in rows}),
            "mention_rate": rate(rows, "mentioned"),
            "citation_rate": rate(rows, "cited"),
        }

    by_intent = {}
    for intent in sorted({queries_by_id[r["query_id"]].intent for r in ok
                          if r["query_id"] in queries_by_id}):
        rows = [r for r in ok if r["query_id"] in queries_by_id
                and queries_by_id[r["query_id"]].intent == intent]
        by_intent[intent] = {"answers": len(rows),
                             "mention_rate": rate(rows, "mentioned"),
                             "citation_rate": rate(rows, "cited")}

    # Unprompted = the brand was NOT named in the question. This is the number
    # that actually measures earned visibility.
    unp = [r for r in ok if r["query_id"] in queries_by_id
           and not queries_by_id[r["query_id"]].prompted]

    # Share of voice across every cited domain.
    dom = Counter()
    for r in ok:
        for d in set(r["cited_domains"]):
            dom[d] += 1
    total_cites = sum(dom.values()) or 1
    client_domain = _domain("http://" + profile.domain) or profile.domain.lower()
    sov = [{"domain": d, "citations": n,
            "share": round(100 * n / total_cites, 1),
            "is_client": d == client_domain}
           for d, n in dom.most_common(25)]

    comp = Counter()
    for r in ok:
        for c, n in r["competitor_mentions"].items():
            comp[c] += 1

    client_cites = dom.get(client_domain, 0)
    top_rival = next((s for s in sov if not s["is_client"]), None)

    return {
        "answers_total": len(results),
        "answers_ok": len(ok),
        "answers_error": len(errs),
        "mention_rate": rate(ok, "mentioned"),
        "citation_rate": rate(ok, "cited"),
        "unprompted_mention_rate": rate(unp, "mentioned"),
        "unprompted_citation_rate": rate(unp, "cited"),
        # Printed beside the rates they belong to. A rate with no interval
        # reads as a measurement; with one it reads as an estimate, which is
        # what it is.
        "mention_ci": interval(ok, "mentioned"),
        "citation_ci": interval(ok, "cited"),
        "unprompted_citation_ci": interval(unp, "cited"),
        "by_platform": by_platform,
        "platform_errors": platform_errors,
        "by_intent": by_intent,
        "by_market": by_market,
        "share_of_voice": sov,
        "competitor_mention_counts": dict(comp.most_common(15)),
        "client_citations": client_cites,
        "top_competitor_domain": top_rival["domain"] if top_rival else None,
        "top_competitor_citations": top_rival["citations"] if top_rival else 0,
        # Signed on purpose: positive = how far BEHIND the most-cited rival the
        # client is; negative = the client leads. Consumers that render a
        # "gap to close" must guard on > 0 (the dashboard does).
        "citation_gap": (top_rival["citations"] - client_cites) if top_rival else 0,
        "client_leads": bool(top_rival and client_cites > top_rival["citations"]),
    }


def headline(agg: dict, profile) -> str:
    """The one sentence a client actually reads."""
    if not agg["answers_ok"]:
        return "No AI platform responses were collected."
    cr = agg["citation_rate"]
    top, topn = agg["top_competitor_domain"], agg["top_competitor_citations"]
    s = (f"Across {agg['answers_ok']} AI answers, {profile.brand} was mentioned in "
         f"{agg['mention_rate']}% and cited as a source in {cr}%.")
    if top and topn > agg["client_citations"]:
        s += (f" {top} was cited {topn} times versus {agg['client_citations']} for "
              f"{profile.domain} — a gap of {agg['citation_gap']} citations.")
    return s
