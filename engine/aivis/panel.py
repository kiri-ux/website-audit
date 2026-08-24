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
import re
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
    # WHICH MARKET THIS QUESTION IS ABOUT.
    #
    # A blended visibility number is the single biggest problem with measuring
    # a local business this way: "12% of answers mention you" across Knoxville,
    # Clinton and Farragut tells a firm nothing they can act on, because the
    # answer is almost never uniform. Being invisible in one county and fine in
    # another is the finding, and averaging destroys it.
    #
    # Empty string means the question names no place — brand questions and the
    # generic open questions — and those are reported on their own rather than
    # attributed to a market they never mentioned.
    market: str = ""

    def to_dict(self):
        return asdict(self)


def _qid(text: str) -> str:
    """Stable ID from the query text, so the same question keeps its identity
    across panel regenerations and the time series stays joinable."""
    return hashlib.sha1(text.lower().strip().encode()).hexdigest()[:12]


BRAND_TEMPLATES = [
    "Is {brand} a reputable company?",
    "What do customers say about {brand}?",
    # WAS "…and what do they sell?" - retail phrasing on a law firm, and it
    # invites an answer about products that do not exist.
    "Where is {brand} located and what do they do?",
    "Is {brand} legit or a scam?",
    "What is {brand} known for?",
]

# THE TEMPLATES WERE WRITTEN FOR A FURNITURE RETAILER.
#
# With `category` falling back to the literal word "business" (see
# profile_from_audit) they produced "Which business should I use in Knoxville
# Tennessee?" and "Recommend a trustworthy business near Knoxville Tennessee."
# Nobody types those. A panel of questions nobody would ask measures nothing,
# however carefully the answers are counted.
#
# Two changes: the category itself is now a real noun phrase ("criminal
# defense attorney"), and the service-shaped templates below are preferred
# when the crawl gave us services, because "best criminal defense attorney in
# Knoxville" IS what someone types.
CATEGORY_TEMPLATES = [
    "Who is the best {category} in {location}?",
    "Who are the top-rated {category}s in {location}?",
    "How do I choose a {category} in {location}?",
    "Which {category} in {location} has the best reviews?",
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

# Retail-shaped questions ("delivery", "buying", "warranty") on a law firm
# are the same failure as the category one: a question the client's customers
# would never ask cannot measure whether the client is found.
QUESTION_TEMPLATES = [
    "What should I look for when choosing a {category}?",
    "What questions should I ask a {category} before hiring one?",
    "How much does a {category} usually cost?",
    "What are the warning signs of a bad {category}?",
]

RETAIL_QUESTION_TEMPLATES = [
    "How long does {category} delivery usually take?",
    "What should I look for when buying from a {category}?",
    "Is it worth paying more for a longer warranty?",
]

SERVICE_TEMPLATES = [
    "Who is the best {service} in {location}?",
    "How do I find a good {service} in {location}?",
    "How much does {an_service} cost in {location}?",
]

# WITHOUT A HEAD NOUN, THE SENTENCE HAS TO CHANGE SHAPE.
#
# When the industry gives us no noun, the service is the bare thing itself -
# "criminal defense", "family law" - and "Who is the best criminal defense in
# Knoxville?" is not a sentence anybody says. Asking who to HIRE FOR it is,
# and it measures the same thing.
NOUNLESS_SERVICE_TEMPLATES = [
    "Who should I hire for {service} in {location}?",
    "Who is best for {service} in {location}?",
    "How much does {service} cost in {location}?",
]


# ---------------------------------------------------------------- categories
#
# `category` is the noun a stranger would type. It has to be a real one:
# "business" produced "Which business should I use in Knoxville Tennessee?",
# which is not a search anybody performs.
#
# Vici classifies every client with an industry string like "Legal - Family
# Law" or "Automotive - Car washing", and that string was being looked up in a
# map keyed on internal ids (`local_service`, `ecommerce`) - so it never
# matched and every client fell through to "business".
_HEAD_NOUN = {
    "legal": "attorney",
    "medical": "doctor",
    "dental": "dentist",
    "veterinary": "veterinarian",
    "chiropractic": "chiropractor",
    "insurance": "insurance agency",
    "real estate": "real estate agent",
    "financial": "financial advisor",
    "banking": "bank",
    "education": "school",
    "restaurants": "restaurant",
    "fitness": "gym",
    "salon": "salon",
    "spa": "spa",
    "hotel": "hotel",
    "automotive": "auto shop",
    "hvac": "HVAC company",
    "plumbing": "plumber",
    "roofing": "roofer",
    "electrical": "electrician",
    "landscaping": "landscaper",
    "lawn care": "lawn care service",
    "pest control": "pest control company",
    "moving": "moving company",
    "storage": "storage facility",
    "cleaning": "cleaning service",
    "construction": "contractor",
    "home services": "contractor",
    "funeral": "funeral home",
    "senior living": "senior living community",
    "childcare": "daycare",
    "veterinarian": "veterinarian",
}

_VERTICAL_CATEGORY = {
    "ecommerce": "online store",
    "finance_ymyl": "financial services firm",
    "local_service": "local service company",
    "healthcare": "healthcare provider",
    "legal": "law firm",
    "saas": "software company",
}


def _category_from_industry(vertical: str) -> str:
    """
    "Legal - Family Law" -> "family law attorney". "" -> "".

    Returns an empty string rather than a guess when nothing can be derived:
    an empty category means build_panel leans on the services instead, which
    is the better question anyway.
    """
    raw = (vertical or "").strip()
    if not raw:
        return ""
    if raw in _VERTICAL_CATEGORY:
        return _VERTICAL_CATEGORY[raw]
    head, _, tail = raw.partition(" - ")
    head, tail = head.strip(), tail.strip()
    # "01 Other- No Matching Category Below" and friends carry no information.
    if head.lower().startswith("01 other") or "no matching" in raw.lower():
        return ""
    noun = _HEAD_NOUN.get(head.lower())
    if noun and tail:
        # "Family Law" + "attorney" -> "family law attorney"; but "Defense" +
        # "attorney" -> "defense attorney", and "Personal Injury" likewise.
        return f"{tail.lower()} {noun}"
    if noun:
        return noun
    if tail:
        return f"{tail.lower()} company"
    return f"{head.lower()} company"


def _service_phrase(service: str, category: str) -> str:
    """
    A URL path turned into something a person would search for.

    "criminal-defense" plus a category of "defense attorney" becomes "criminal
    defense attorney" rather than "criminal defense defense attorney" - the
    head noun is only appended when the service does not already carry it.
    """
    svc = " ".join(str(service or "").split()).strip().lower()
    if not svc:
        return category
    # "dui attorney" is not what anyone types. Short all-letter words in a
    # URL path are nearly always initialisms - dui, cpa, hvac, llc, seo.
    # THREE LETTERS, NOT FOUR. At four this shouted "JUNK removal" at five
    # platforms - "junk" is a word, not an initialism. The four-letter
    # initialisms that matter are few enough to name.
    _CAPS = {"hvac", "hipaa", "osha"}
    _WORDS = {"law", "tax", "car", "van", "pet", "spa", "gym", "eye", "ear",
              "dog", "cat", "air", "gas", "oil", "web", "app", "seo"}
    svc = " ".join(
        w.upper() if (w in _CAPS or (len(w) <= 3 and w.isalpha()
                                     and w not in _WORDS)) else w
        for w in svc.split())
    noun = (category or "").split()[-1] if category else ""
    if noun and noun.rstrip("s") in svc:
        return svc
    return f"{svc} {noun}".strip() if noun else svc


def build_panel(p: ClientProfile, target_size: int = 40) -> list[Query]:
    """
    Deterministic panel construction. Same profile in, same panel out — which is
    what makes runs comparable over time.

    The mix is weighted toward unprompted queries (category, product, question)
    because those are the ones that measure earned visibility.
    """
    qs: list[Query] = []
    seen: set[str] = set()

    def add(intent, text, prompted, market=""):
        text = " ".join(text.split())
        # THE LAST LINE OF DEFENCE AGAINST AN EMPTY SLOT.
        #
        # Every caller is guarded, and a template with a hole in it still
        # reached five platforms once. This is cheap and it cannot be
        # forgotten: a question with a missing noun has a tell - a stranded
        # article or a space before its punctuation - and none of them are
        # things a person types.
        if re.search(r"\b(a|an|the|best|top-rated)\s*[?.,]", text) or \
                re.search(r"\s[?.]", text) or "  " in text:
            return
        k = text.lower()
        if k in seen:
            return
        seen.add(k)
        qs.append(Query(_qid(text), intent, text, prompted, market))

    # NO LOCATION MEANS NO LOCATION QUESTIONS.
    #
    # "your area" was a placeholder that reached five platforms as a literal
    # question: "Who should I hire for hardin valley in your area?" Nobody
    # types that, and an assistant answering it is answering something else.
    # An empty list here means the location templates below do not run at all.
    locations = list(p.locations or [])
    # NO PRODUCT QUESTIONS WITHOUT PRODUCTS.
    #
    # This defaulted to [p.category], which asked an assistant "Where can I
    # buy defense attorney in Knoxville?" - three questions per run that no
    # human has ever typed, counted in the same rates as the real ones.
    products = p.products or []
    competitors = p.competitors or []

    for t in BRAND_TEMPLATES:
        add("brand", t.format(brand=p.brand), True)

    # An empty category is not a hole to fill with the word "business" - the
    # service questions below cover the same intent with a better noun.
    if p.category:
        for loc in locations[:4]:
            for t in CATEGORY_TEMPLATES:
                add("category", t.format(category=p.category, location=loc),
                    False, market=loc)

    for prod in products[:4]:
        _pl = locations[0] if locations else ""
        for t in PRODUCT_TEMPLATES:
            add("product", t.format(product=prod, location=_pl or "me"),
                False, market=_pl)


    for comp in competitors[:3]:
        for t in COMPARISON_TEMPLATES:
            add("comparison", t.format(brand=p.brand, competitor=comp), True)

    # AND NEITHER DO THE OPEN QUESTIONS.
    #
    # The category guard was put on the location templates and not on these,
    # so a client we could not classify was asked "What should I look for when
    # choosing a ?" and "How much does a usually cost?" - questions with a
    # hole where the noun goes, fired at five platforms and counted in the
    # rates like any other. A template with an empty slot is not a question.
    if p.category:
        for t in (RETAIL_QUESTION_TEMPLATES if p.products
                  else QUESTION_TEMPLATES):
            add("question", t.format(category=p.category), False)

    # SERVICES ARE THE BEST QUERIES WE HAVE, so they go in as their own
    # searches rather than as "the best company for family law". The crawl
    # reads them off the URL paths, which is the closest thing to a list of
    # what this business actually does.
    # SERVICES ACROSS MARKETS, NOT ALL IN THE FIRST ONE.
    #
    # `where = locations[0]` asked every service question about one city, so a
    # firm with three offices got a reading for one of them and a blended
    # number that looked like all three. Pairing each service with a different
    # market costs nothing - the panel is the same size - and turns a single
    # blended figure into a per-market one, which is the whole point of
    # measuring a local business.
    #
    # Round-robin rather than a full cross-product: services x markets would
    # multiply the panel (and the spend) by the number of offices, and the
    # target size would truncate it back down arbitrarily anyway.
    _svcs = p.services[:4]
    for _i, svc in enumerate(_svcs):
        where = locations[_i % len(locations)] if locations else ""
        if not where:
            # Without a place, ask the service question without one rather
            # than inventing a place.
            phrase = _service_phrase(svc, p.category)
            # "How much does dumpster rentals cost" - the verb has to agree
            # with the noun, and half of these services are plural.
            verb = "do" if phrase.rstrip().endswith("s") else "does"
            add("question", f"What should I look for when choosing someone "
                            f"for {phrase}?", False)
            add("question", f"How much {verb} {phrase} usually cost?", False)
            continue
        phrase = _service_phrase(svc, p.category)
        for t in (SERVICE_TEMPLATES if p.category
                  else NOUNLESS_SERVICE_TEMPLATES):
            # "a estate planning attorney" - the article has to follow the
            # word it precedes, not the template author's assumption.
            an = ("an " if phrase[:1].lower() in "aeiou" else "a ") + phrase
            add("category", t.format(service=phrase, an_service=an,
                                     location=where), False, market=where)

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
    # THE INDUSTRY STRING FIRST, THEIR OWN COPY SECOND, NEVER "business".
    #
    # This read the self-description first, and fell back to a map keyed on
    # internal vertical ids that a Vici industry string ("Legal - Family Law")
    # never matches - so the fallback fired every time and the panel asked
    # "Which business should I use in Knoxville Tennessee?"
    #
    # A meta description is marketing copy, and dropping 80 characters of it
    # into "Who is the best {category} in Knoxville?" produces a sentence, not
    # a search. The industry taxonomy is the better source, and when it gives
    # us nothing the category is left EMPTY - build_panel then asks about the
    # services instead, which is the strongest question we have.
    category = _category_from_industry(vertical or "")

    locations = []
    for loc in (ctx.get("locations") or []):
        name = ", ".join(x for x in (loc.get("city"), loc.get("region")) if x)
        if name and name not in locations:
            locations.append(name)
    locations = locations[:8] or list(ctx.get("states") or [])[:8]

    # Top-level URL paths are the closest thing a crawl has to a service list:
    # /personal-injury, /car-accidents, /workers-comp.
    services = [str(s).strip("/").replace("-", " ").replace("_", " ")
                for s in (ctx.get("sections") or [])[:10]]
    # A NAVIGATION LABEL IS NOT A SERVICE.
    #
    # /practice-areas is the index page that lists them, and it produced "Who
    # is the best practice areas attorney in Knoxville?" - a question with a
    # broken noun in it. Same for /services, /what-we-do and the rest: they
    # are containers, and the things inside them are the services.
    _NOT_A_SERVICE = {
        "blog", "news", "about", "about us", "contact", "contact us",
        "privacy", "terms", "sitemap", "search", "category", "tag", "author",
        "wp content", "practice areas", "practice area", "services",
        "our services", "service areas", "areas we serve", "what we do",
        "products", "shop", "store", "resources", "faq", "faqs", "reviews",
        "testimonials", "team", "our team", "attorneys", "staff", "careers",
        "locations", "gallery", "portfolio", "case results", "results",
    }
    # NOR IS A PLACE.
    #
    # /clinton and /farragut are city pages, and they produced "Who should I
    # hire for clinton in Knoxville, Tennessee?" - a question with a town
    # where the job should be. Every place we know about goes in the stop
    # list: the cities and regions the crawl found, and the markets the
    # client typed into the form.
    places = set()
    for loc in (ctx.get("locations") or []):
        for key in ("city", "region", "name"):
            val = str(loc.get(key) or "").strip().lower()
            if val:
                places.add(val)
    for extra in (ctx.get("states") or []):
        places.add(str(extra).strip().lower())
    for token in str(ctx.get("primary_markets") or "").replace(",", " ").split():
        token = token.strip().lower()
        if len(token) > 3 and token not in ("county", "city", "area"):
            places.add(token)
    # AND A BARE ONE-WORD PATH IS USUALLY A PLACE OR A NAV LINK.
    #
    # The crawl only finds the towns a site publishes SCHEMA for, so /clinton
    # was caught by the list above and /farragut - the next town over, with no
    # markup - was not. What separates them from a real service is shape: work
    # is described in more than one word nearly every time ("criminal
    # defense", "estate planning", "water heater repair"), while a town, a
    # person and a nav label are one. The exceptions are the trades and
    # practice areas that genuinely have single-word names, and they are
    # short, closed and worth listing.
    _ONE_WORD_SERVICES = {
        "dui", "dwi", "seo", "ppc", "hvac", "roofing", "plumbing", "painting",
        "landscaping", "remodeling", "bankruptcy", "divorce", "probate",
        "mediation", "immigration", "litigation", "arbitration", "adoption",
        "dentistry", "orthodontics", "chiropractic", "dermatology",
        "physiotherapy", "audiology", "optometry", "podiatry", "insurance",
        "mortgages", "accounting", "bookkeeping", "payroll", "catering",
        "flooring", "roofs", "windows", "siding", "gutters", "fencing",
        "decking", "masonry", "paving", "excavation", "towing", "detailing",
        "upholstery", "grooming", "boarding", "daycare", "tutoring",
        "photography", "videography", "printing", "signage", "moving",
        "storage", "cleaning", "restoration", "inspections", "appraisals",
        "surveying", "welding", "machining", "electrical", "wills", "trusts",
    }
    # A TWO-WORD PLACE NAME IS STILL A PLACE.
    #
    # /hardin-valley is a Knoxville neighbourhood, and it passed every filter
    # above: not in the schema locations, not a market the client typed, and
    # two words long, so the shape test waved it through. It produced "Who
    # should I hire for hardin valley in your area?"
    #
    # American place names end in a small, stable set of words. Matching the
    # LAST word is a narrow test - "valley" as the head noun of a service is
    # not a thing - and it catches the whole family: Oak Ridge, Powell Station,
    # Farragut Heights.
    _PLACE_TAIL = {
        "valley", "heights", "hills", "hill", "park", "ridge", "city", "town",
        "township", "springs", "spring", "beach", "lake", "lakes", "grove",
        "creek", "falls", "harbor", "island", "junction", "mills", "plains",
        "point", "shores", "station", "view", "village", "woods", "county",
        "borough", "landing", "crossing", "meadows", "estates", "acres",
    }
    services = [s for s in services
                if s and s.lower() not in _NOT_A_SERVICE
                and s.lower() not in places
                and not any(p and p in s.lower() for p in places
                            if len(p) > 4)
                and (" " in s.strip() or s.strip().lower()
                     in _ONE_WORD_SERVICES)
                and s.strip().lower().split()[-1] not in _PLACE_TAIL]

    return ClientProfile(
        brand=brand, domain=domain, category=category,
        products=services if ctx.get("has_ecommerce") else [],
        locations=locations,
        services=[] if ctx.get("has_ecommerce") else services,
        competitors=[], aliases=[])
