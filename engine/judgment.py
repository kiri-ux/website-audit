"""
Phase 3 — the judgment layer.

The 29 E-E-A-T and GEO checkpoints that genuinely need assessment rather than
measurement.

THE DESIGN RULE, and the reason this file is shaped the way it is:

    ONE NARROW CALL PER CHECKPOINT, each fed a targeted slice of the crawl
    artifact, each returning a strict structured object.

Do NOT write a single "assess E-E-A-T" prompt over the whole site. A broad
prompt produces confident mush that any competent SEO spots in seconds, and it
discredits the other 276 rows on the page. Narrow calls are also cheaper to
debug: when one row is wrong you fix one prompt, not a monolith.

The orchestrator does the RETRIEVAL. The model only judges what it is handed.
That is what keeps it from inventing pages that do not exist.

Cost: ~29 calls x ~6k input tokens. A few dollars per audit against $2,950.
Do not optimize it; optimize accuracy.

No API key -> every row returns Need Access with confidence 0. Same rule as
everywhere else: unmeasured is never reported as a defect.
"""
from __future__ import annotations
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

OK = lambda a: [p for p in a.pages.values()
                if not p.error and 200 <= p.status_code < 300]

CONTRACT = (
    'Return ONLY JSON: {"status": "Pass"|"Fail"|"Warning"|"Not Implemented", '
    '"evidence": "1-2 sentences citing specific URLs or quotes", '
    '"severity": "Critical"|"High"|"Medium"|"Low"|"Opportunity", '
    '"recommendation": "specific and actionable", "confidence": 0.0-1.0}'
)

RULES = (
    "RULES:\n"
    "- Judge ONLY what is in the material below. Never infer a page, credential "
    "or claim that is not present.\n"
    "- If the material is insufficient to judge, return status "
    '"Not Implemented" with a low confidence and say what was missing.\n'
    "- Cite specific URLs in evidence.\n"
    "- Do not soften or dramatise. No marketing language.\n"
)


# ---------------------------------------------------------------- retrieval
def _pages_matching(art, pattern, limit=6):
    rx = re.compile(pattern, re.I)
    return [p for p in OK(art) if rx.search(p.url)][:limit]


def _headtail(text: str, chars: int) -> str:
    """
    Head AND tail of the page, not the first N characters.

    This was a straight `[:chars]` truncation, and it produced a false negative
    that reached a client: "no physical address or business hours are present"
    on a site whose address is in the footer of every page. The footer is the
    LAST thing in the text, so a head-only slice can never contain it — and the
    checkpoints that most need it (address, hours, legal entity, support
    channels) are exactly the ones whose answer lives down there.

    Two thirds from the top, one third from the bottom, with the cut marked so
    the model knows material is missing rather than assuming it saw everything.
    """
    text = text or ""
    if len(text) <= chars:
        return text
    head = int(chars * 0.66)
    tail = chars - head
    return f"{text[:head]}\n…[middle of page omitted]…\n{text[-tail:]}"


def _slice(pages, chars=1400):
    out = []
    for p in pages:
        out.append(f"URL: {p.url}\nTITLE: {p.title or '(none)'}\n"
                   f"H1: {'; '.join(p.h1) or '(none)'}\n"
                   f"TEXT: {_headtail(p.rendered_text, chars)}\n---")
    return "\n".join(out) or "(no matching pages found in the crawl)"


def _homepage(art):
    ok = OK(art)
    return min(ok, key=lambda p: p.depth) if ok else None


def _all_text(art, limit=8, chars=900):
    return _slice(sorted(OK(art), key=lambda p: p.depth)[:limit], chars)


# ---------------------------------------------------------------- checkpoints
# (checkpoint_id, label, retrieval fn, question)
SPECS = [
    # ---- E-E-A-T -------------------------------------------------------
    ("EEAT-01", "First-hand experience",
     lambda a: _all_text(a),
     "Does this site demonstrate genuine first-hand experience of the products or "
     "services it sells — original photography described in text, specific "
     "operational detail, named staff, real store or project accounts? Generic "
     "marketing copy is NOT first-hand experience."),
    ("EEAT-02", "Real examples",
     lambda a: _all_text(a),
     "Does the content include concrete real-world examples — case studies, named "
     "customer stories, specific projects — as opposed to generic claims?"),
    ("EEAT-03", "Original insights",
     lambda a: _all_text(a),
     "Does the content offer original insight, proprietary data or a distinctive "
     "point of view, rather than restating what every competitor says?"),
    ("EEAT-04", "Subject matter expertise",
     lambda a: _all_text(a),
     "Does the writing demonstrate real subject-matter expertise — accurate "
     "terminology, specific guidance, depth beyond surface level?"),
    ("EEAT-05", "Expert-written content",
     lambda a: _slice(_pages_matching(a, r"/blog|/guide|/resource|/article|/learn|/advice")),
     "Is editorial content attributed to a named person with relevant expertise?"),
    ("EEAT-06", "Expert review process",
     lambda a: _slice(_pages_matching(a, r"/about|/editorial|/review|/our-")),
     "Is there any stated expert or editorial review process — 'reviewed by', "
     "'medically reviewed', a named editor, or a published editorial policy?"),
    ("EEAT-08", "Author credentials",
     lambda a: _slice(_pages_matching(a, r"/author|/team|/staff|/about|/bio|/our-people")),
     "For any named author or team member, are professional credentials stated — "
     "certifications, licenses, titles, years of experience? Do not infer "
     "credentials that are not explicitly written."),
    ("EEAT-09", "Organization authority",
     lambda a: _slice(_pages_matching(a, r"/about|/company|/our-story|/history")),
     "Does the site establish organizational authority — years in business, scale, "
     "locations, accreditations, industry memberships?"),
    ("EEAT-10", "Industry mentions",
     lambda a: _all_text(a),
     "Does the site reference third-party recognition — press coverage, awards, "
     "industry association membership, media mentions?"),
    ("EEAT-11", "Brand authority",
     lambda a: _all_text(a),
     "Does the site present a coherent, established brand identity with clear "
     "positioning, or does it read as generic and interchangeable?"),
    ("EEAT-14", "Editorial policy",
     lambda a: _slice(_pages_matching(a, r"/editorial|/policy|/about|/standards")),
     "Is there a published editorial policy, content standards page, or statement "
     "of how content is produced and fact-checked?"),
    ("EEAT-20", "Business information",
     lambda a: _slice(_pages_matching(a, r"/contact|/about|/location|/store")) ,
     "Is complete business information available — physical address, phone number, "
     "business hours, legal entity name?"),
    ("EEAT-21", "Customer support information",
     lambda a: _slice(_pages_matching(a, r"/contact|/support|/help|/faq|/service")),
     "Are customer support channels clearly presented — phone, email, chat, hours, "
     "expected response times?"),
    ("EEAT-22", "Testimonials",
     lambda a: _all_text(a),
     "Does the site display customer testimonials with attribution (name, location "
     "or photo), rather than anonymous or clearly fabricated quotes?"),
    ("EEAT-23", "Reviews",
     lambda a: _all_text(a),
     "Are customer reviews or ratings present, ideally with volume and average "
     "score, or linked to a third-party review platform?"),

    # ---- GEO -----------------------------------------------------------
    ("GEO-05", "AI-friendly site architecture",
     lambda a: "SITE STRUCTURE:\n" + "\n".join(
         f"{p.url}  (depth {p.depth}, {len(p.links_internal)} internal links)"
         for p in sorted(OK(a), key=lambda x: x.depth)[:40]),
     "Is the site organized into a clear topical hierarchy that an AI system could "
     "follow to understand what the business does and how its content relates?"),
    ("GEO-07", "AI-friendly content formatting",
     lambda a: _all_text(a),
     "Is content formatted for machine extraction — short self-contained "
     "paragraphs, descriptive subheadings, lists and tables — rather than long "
     "undifferentiated prose?"),
    ("GEO-09", "Question-answer content",
     lambda a: _all_text(a),
     "Does the site answer specific customer questions in a question-and-answer "
     "format that an AI system could lift directly as an answer?"),
    ("GEO-11", "Conversational content",
     lambda a: _all_text(a),
     "Is the content written in natural, conversational language matching how "
     "people actually ask questions, rather than keyword-stuffed copy?"),
    ("GEO-12", "Entity optimization",
     lambda a: _all_text(a),
     "Are the key entities — brand, products, services, locations, people — named "
     "explicitly and consistently, so a machine can resolve them?"),
    ("GEO-13", "Knowledge Graph optimization",
     lambda a: (_slice(_pages_matching(a, r"/about|/contact|/location")) +
                "\n\nSCHEMA TYPES FOUND: " +
                ", ".join(sorted({t for p in OK(a) for t in p.schema_types}) ) or "(none)"),
     "Does the site provide the consistent name, address, identity and "
     "relationship signals a knowledge graph would need to model this business?"),
    ("GEO-14", "Semantic relationships",
     lambda a: _all_text(a),
     "Does the content make explicit the relationships between services, products, "
     "locations and topics, or are they left implicit?"),
    ("GEO-15", "Citation-worthy content",
     lambda a: _all_text(a),
     "Is there content another site or an AI system would consider worth citing as "
     "a source — original data, definitive guides, reference material? Promotional "
     "pages are not citation-worthy."),
    ("GEO-16", "Original research",
     lambda a: _all_text(a),
     "Does the site publish original research, surveys or proprietary data?"),
    ("GEO-17", "Statistics & data usage",
     lambda a: _all_text(a),
     "Does the content use specific statistics and data points with sources, "
     "rather than vague claims?"),
    ("GEO-18", "Expert quotes",
     lambda a: _all_text(a),
     "Does the content include quotes or commentary attributed to named experts?"),
    ("GEO-20", "Author entity optimization",
     lambda a: _slice(_pages_matching(a, r"/author|/team|/about|/bio")),
     "Are authors established as resolvable entities — consistent naming, bio "
     "pages, links to profiles, Person schema?"),
    ("GEO-21", "Organization entity optimization",
     lambda a: (_slice(_pages_matching(a, r"/about|/contact")) +
                "\n\nSCHEMA TYPES FOUND: " +
                ", ".join(sorted({t for p in OK(a) for t in p.schema_types})) ),
     "Is the organization established as a clear entity — consistent name, "
     "address, description, Organization schema, external profile links?"),
    ("GEO-22", "Brand entity optimization",
     lambda a: _all_text(a),
     "Is the brand presented consistently enough across the site that an AI system "
     "would treat it as a single recognizable entity?"),
]

CHECKPOINT_IDS = [s[0] for s in SPECS]


# ---------------------------------------------------------------- model call
def _call_model(prompt: str, timeout: int = 90) -> str:
    import urllib.request
    if os.getenv("ANTHROPIC_API_KEY"):
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps({
                "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
                "max_tokens": 700,
                "messages": [{"role": "user", "content": prompt}]}).encode(),
            headers={"Content-Type": "application/json",
                     "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
                     "anthropic-version": "2023-06-01"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        return "".join(b.get("text", "") for b in d.get("content", [])
                       if b.get("type") == "text")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps({
            "model": os.getenv("OPENAI_MODEL", "gpt-4.1"),
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"]["content"]


def _finding(status, evidence, severity="Medium", rec="", conf=1.0, src="llm_judgment"):
    return {"status": status, "value": {}, "evidence": evidence,
            "affected_pages": [], "severity": severity, "recommendation": rec,
            "confidence": conf, "source": src}


def _judge_one(cid, label, material, question, business_model, client):
    prompt = (
        f"You are auditing a website checkpoint for a professional SEO audit.\n\n"
        f"CHECKPOINT {cid}: {label}\n"
        f"CLIENT: {client or 'the site'}\n"
        f"BUSINESS TYPE: {business_model or 'general'}\n\n"
        f"QUESTION: {question}\n\n"
        f"{RULES}\n"
        f"MATERIAL FROM THE SITE:\n{material}\n\n"
        f"{CONTRACT}")
    try:
        raw = _call_model(prompt)
        start, end = raw.find("{"), raw.rfind("}")
        d = json.loads(raw[start:end + 1])
        status = d.get("status")
        if status not in ("Pass", "Fail", "Warning", "Not Implemented"):
            status = "Not Implemented"
        return cid, _finding(status, d.get("evidence", "")[:600],
                             d.get("severity", "Medium"),
                             d.get("recommendation", "")[:400],
                             float(d.get("confidence", 0.7)))
    except Exception as e:
        return cid, _finding("Need Access",
                             f"Judgment call failed: {type(e).__name__}: {e}",
                             "Medium", "", 0.0, "llm_error")


def run_judgment(art, business_model=None, client=None,
                 max_workers: int = 6, progress=None) -> dict:
    """
    Run all judgment checkpoints. Returns {checkpoint_id: finding}.

    With no API key configured every row is Need Access at confidence 0 — the
    same rule the rest of the system follows. An unmeasured checkpoint is never
    reported as a defect.
    """
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")):
        return {cid: _finding(
            "Need Access",
            "Not assessed — no LLM credentials configured for the judgment layer.",
            "Medium", "Set ANTHROPIC_API_KEY or OPENAI_API_KEY on the worker to "
            "enable E-E-A-T and GEO assessment.", 0.0, "llm_unconfigured")
            for cid in CHECKPOINT_IDS}

    if not OK(art):
        return {cid: _finding(
            "Need Access",
            "Not assessed — no page content was retrieved to judge.",
            "Medium", "", 0.0, "no_content") for cid in CHECKPOINT_IDS}

    out, done = {}, 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {}
        for cid, label, retrieve, question in SPECS:
            try:
                material = retrieve(art)
            except Exception as e:
                out[cid] = _finding("Need Access",
                                    f"retrieval failed: {type(e).__name__}: {e}",
                                    "Medium", "", 0.0, "retrieval_error")
                continue
            futs[ex.submit(_judge_one, cid, label, material, question,
                           business_model, client)] = cid
        for fut in as_completed(futs):
            cid, f = fut.result()
            out[cid] = f
            done += 1
            if progress and done % 5 == 0:
                progress(done, len(futs))
    return out
