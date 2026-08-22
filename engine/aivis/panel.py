"""
Query panel generation.

A "panel" is the fixed set of questions we fire at every AI platform, every run.
Fixed is the important word: the panel must be **stable across runs**, because
the product is a time series. If the questions change between March and April,
the March→April delta is meaningless.

Panels are therefore generated once, versioned, and stored. Regenerating creates
a new panel version rather than mutating the old one.

Five intents, because they answer different commercial questions:

  brand       "is <brand> reputable"          — do AI systems know you exist?
  category    "best <category> in <location>" — do you appear in the consideration set?
  product     "<product> near me"             — do you appear at purchase intent?
  comparison  "<brand> vs <competitor>"       — how are you framed against rivals?
  question    "how long does <x> take"        — do you own the informational long tail?

Category and question queries matter most: they are the ones where the client is
NOT named in the prompt, so appearing is earned rather than given. A brand query
that mentions you by name and gets a mention back proves very little.
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field, asdict


@dataclass
class ClientProfile:
    brand: str
    domain: str
    category: str                       # "furniture and mattress retailer"
    products: list = field(default_factory=list)
    locations: list = field(default_factory=list)
    competitors: list = field(default_factory=list)
    services: list = field(default_factory=list)
    aliases: list = field(default_factory=list)   # other names the brand goes by

    def to_dict(self):
        return asdict(self)


@dataclass
class Query:
    id: str
    intent: str
    text: str
    # Whether the brand name appears in the prompt. Unprompted queries are the
    # ones that carry real signal — see module docstring.
    prompted: bool

    def to_dict(self):
        return asdict(self)


def _qid(text: str) -> str:
    """Stable ID from the query text, so the same question keeps its identity
    across panel regenerations and the time series stays joinable."""
    return hashlib.sha1(text.lower().strip().encode()).hexdigest()[:12]


BRAND_TEMPLATES = [
    "Is {brand} a reputable company?",
    "What do customers say about {brand}?",
    "Where is {brand} located and what do they sell?",
    "Is {brand} legit or a scam?",
    "What is {brand} known for?",
]

CATEGORY_TEMPLATES = [
    "What are the best {category} options in {location}?",
    "Who are the top-rated {category} companies in {location}?",
    "Which {category} should I use in {location}?",
    "Recommend a trustworthy {category} near {location}.",
]

PRODUCT_TEMPLATES = [
    "Where can I buy {product} in {location}?",
    "What's the best place to get {product}?",
    "Who sells affordable {product} near me?",
]

COMPARISON_TEMPLATES = [
    "{brand} vs {competitor}: which is better?",
    "How does {brand} compare to {competitor}?",
    "Is {brand} or {competitor} cheaper?",
]

QUESTION_TEMPLATES = [
    "How long does {category} delivery usually take?",
    "What should I look for when choosing a {category} company?",
    "What questions should I ask a {category} before buying?",
    "Is it worth paying more for a {category} with a warranty?",
]


def build_panel(p: ClientProfile, target_size: int = 40) -> list[Query]:
    """
    Deterministic panel construction. Same profile in, same panel out — which is
    what makes runs comparable over time.

    The mix is weighted toward unprompted queries (category, product, question)
    because those are the ones that measure earned visibility.
    """
    qs: list[Query] = []
    seen: set[str] = set()

    def add(intent, text, prompted):
        text = " ".join(text.split())
        k = text.lower()
        if k in seen:
            return
        seen.add(k)
        qs.append(Query(_qid(text), intent, text, prompted))

    locations = p.locations or ["your area"]
    products = p.products or [p.category]
    competitors = p.competitors or []

    for t in BRAND_TEMPLATES:
        add("brand", t.format(brand=p.brand), True)

    for loc in locations[:4]:
        for t in CATEGORY_TEMPLATES:
            add("category", t.format(category=p.category, location=loc), False)

    for prod in products[:4]:
        for t in PRODUCT_TEMPLATES:
            add("product", t.format(product=prod,
                                    location=locations[0] if locations else "me"), False)

    for comp in competitors[:3]:
        for t in COMPARISON_TEMPLATES:
            add("comparison", t.format(brand=p.brand, competitor=comp), True)

    for t in QUESTION_TEMPLATES:
        add("question", t.format(category=p.category), False)

    for svc in p.services[:4]:
        add("category", f"Who is the best company for {svc} in "
                        f"{locations[0] if locations else 'my area'}?", False)
        add("question", f"How much does {svc} typically cost?", False)

    return qs[:target_size]


def panel_summary(qs: list[Query]) -> dict:
    from collections import Counter
    by = Counter(q.intent for q in qs)
    unprompted = sum(1 for q in qs if not q.prompted)
    return {"total": len(qs), "by_intent": dict(by),
            "unprompted": unprompted, "prompted": len(qs) - unprompted}


# ---------------------------------------------------------------- from an audit
#
# WHY THIS EXISTS.
#
# The monitor was built as a standalone product — a monthly time series, its own
# profile, its own frozen question panel — and that is still what it is. But
# being standalone meant GEO-23 to GEO-30 sat unanswered in every audit, on a
# list headed "needs a person", waiting for someone to go and set up a profile
# by hand before the audit could say anything about AI visibility at all.
#
# The audit already knows the brand, the domain, what the business sells and
# where. Rebuilding that by hand to start a monitor run is data entry, not
# judgment. This turns what the crawl learned into a profile good enough for a
# first run, which both fills those eight rows and seeds the series the retainer
# is sold on.
#
# It does NOT replace a hand-built profile. Competitors and aliases are the two
# things a crawl cannot infer and a human supplies in seconds, and a profile
# saved for a client should be edited to include them before the second run.

_VERTICAL_CATEGORY = {
    "ecommerce": "online retailer",
    "finance_ymyl": "financial services firm",
    "local_service": "local service business",
    "healthcare": "healthcare provider",
    "legal": "law firm",
    "saas": "software company",
}


def profile_from_audit(client_name: str, url: str, context: dict | None = None,
                       vertical: str | None = None) -> "ClientProfile":
    """Build a first-run ClientProfile from what the audit already learned."""
    ctx = context or {}
    domain = (url or "").split("//")[-1].split("/")[0].lower()
    domain = domain[4:] if domain.startswith("www.") else domain
    brand = (ctx.get("brand") or client_name or domain.split(".")[0]).strip()

    # Category, in the words the business used about itself where possible.
    # `self_description` is quoted from their own copy, which beats anything we
    # would infer from a URL pattern.
    desc = (ctx.get("self_description") or "").strip()
    category = (desc[:80] if 8 <= len(desc) <= 120
                else _VERTICAL_CATEGORY.get(vertical or "", "business"))

    locations = []
    for loc in (ctx.get("locations") or []):
        name = " ".join(x for x in (loc.get("city"), loc.get("region")) if x)
        if name and name not in locations:
            locations.append(name)
    locations = locations[:8] or list(ctx.get("states") or [])[:8]

    # Top-level URL paths are the closest thing a crawl has to a service list:
    # /personal-injury, /car-accidents, /workers-comp.
    services = [str(s).strip("/").replace("-", " ").replace("_", " ")
                for s in (ctx.get("sections") or [])[:10]]
    services = [s for s in services
                if s and s.lower() not in
                ("blog", "news", "about", "contact", "privacy", "terms",
                 "sitemap", "search", "category", "tag", "author", "wp content")]

    return ClientProfile(
        brand=brand, domain=domain, category=category,
        products=services if ctx.get("has_ecommerce") else [],
        locations=locations,
        services=[] if ctx.get("has_ecommerce") else services,
        competitors=[], aliases=[])
