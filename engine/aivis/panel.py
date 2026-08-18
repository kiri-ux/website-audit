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
