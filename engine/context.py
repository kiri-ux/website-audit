"""
Business context — what the crawl learned about the client, not about their SEO.

Why this file exists: an audit that opens "This audit evaluated 159 checkpoints
across 13 areas" could have been produced for any website on earth. An audit
that opens "Grand Home Furnishings sells furniture from 17 stores across
Virginia and Tennessee" could only have been produced by someone who looked.
The facts are already sitting in the crawl artifact; nothing here is new data
collection, it is reading what we already have with a different question in mind.

THE RULE: every field returned must be traceable to something on the site. If
we did not find it, the field is empty and the prose simply omits that clause.
Inventing plausible business context is worse than having none — a client
notices a wrong store count immediately, and then disbelieves everything else
in the document.
"""
from __future__ import annotations
import re
from collections import Counter
from dataclasses import dataclass, field, asdict

# US state names and abbreviations, for turning a pile of addresses into
# "Virginia and Tennessee". Kept explicit rather than pulling in a dependency.
STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin",
    "WY": "Wyoming", "DC": "District of Columbia",
}

LOCATION_HINTS = ("/store", "/stores", "/location", "/locations", "/branch",
                  "/showroom", "/office")
BLOG_HINTS = ("/blog", "/news", "/articles", "/insights", "/resources", "/guides")

# Nav paths that are plumbing, not business. Excluded from "what they sell".
NOT_A_CATEGORY = {
    "about", "about-us", "contact", "contact-us", "privacy", "privacy-policy",
    "terms", "terms-of-service", "terms-and-conditions", "sitemap", "search",
    "login", "signin", "sign-in", "register", "account", "cart", "checkout",
    "careers", "jobs", "faq", "faqs", "help", "support", "blog", "news",
    "returns", "shipping", "financing", "warranty", "accessibility", "legal",
    "locations", "stores", "store", "location", "home", "index", "wishlist",
}


@dataclass
class BusinessContext:
    brand: str = ""
    self_description: str = ""     # THEIR words, quoted — never our inference
    legal_name: str = ""
    phone: str = ""
    founded: str = ""
    locations: list = field(default_factory=list)      # [{name, city, region}]
    states: list = field(default_factory=list)
    sections: list = field(default_factory=list)   # top-level URL paths
    product_pages: int = 0
    location_pages: int = 0
    blog_pages: int = 0
    has_ecommerce: bool = False
    has_blog: bool = False
    entity_types: list = field(default_factory=list)   # schema @types seen sitewide
    evidence: dict = field(default_factory=dict)       # field -> where we saw it

    def to_dict(self):
        return asdict(self)

    @property
    def is_useful(self) -> bool:
        """Enough to say something specific? Otherwise prose stays generic."""
        return bool(self.brand or self.locations or self.sections
                    or self.product_pages)

    def describe(self) -> str:
        """
        One sentence about the business, in the site's OWN words where possible.

        An earlier version built this from URL path segments and produced, for a
        junk-removal company in Tennessee: "Junk Bee Gone publishes pages
        covering service, clinton and knoxville." Those are a service page and
        two city pages — the sentence is not merely clumsy, it is wrong, and a
        client reads it in the first line of a report they paid for.

        A URL slug is not a description of a business. So the order is now:
        quote their own copy, else state a fact schema markup asserts, else say
        nothing. Saying nothing is a perfectly good outcome here; the paragraph
        that follows still names the domain, the date and the score.
        """
        name = self.brand or "This site"
        # THEIR MARKETING COPY IS NOT AN OPENING LINE.
        #
        # This quoted the site's meta description behind a frame — first "X
        # describes itself as", then "X's own copy:". Both were rejected, and
        # rightly: a meta description is written to win a click, so quoting it
        # opens a report the client paid for with their own advertising read
        # back to them. It also collided with punctuation ("cases..") and put
        # the brand name twice in one line.
        #
        # What is left is what we OBSERVED — locations they publish, product
        # pages we could reach — and when there is nothing observed worth
        # saying, nothing. The next sentence names the domain, the page count
        # and the score, which is a better first line than either version of
        # this one.
        if self.locations:
            n = len(self.locations)
            where = ""
            if self.states:
                st = self.states[:3]
                where = (" in " + (", ".join(st[:-1]) + " and " + st[-1]
                                   if len(st) > 1 else st[0]))
            return (f"{name} lists {n} location{'s' if n != 1 else ''}{where} "
                    f"in its own markup.")
        if self.has_ecommerce and self.product_pages:
            return (f"{name} publishes {self.product_pages} product pages we "
                    f"could reach.")
        return ""


def _nodes(page) -> list:
    """Flatten JSON-LD: bare objects, arrays, and @graph all become one list."""
    out = []
    for blob in (page.schema_raw or []):
        items = blob if isinstance(blob, list) else [blob]
        for node in items:
            if not isinstance(node, dict):
                continue
            out.append(node)
            for g in (node.get("@graph") or []):
                if isinstance(g, dict):
                    out.append(g)
    return out


def _types(node) -> list:
    t = node.get("@type")
    return [x for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)]


def _text(v) -> str:
    """Schema values are strings, dicts or lists depending on the plugin."""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        return str(v.get("name") or v.get("@value") or "").strip()
    if isinstance(v, list) and v:
        return _text(v[0])
    return ""


def _slug_words(seg: str) -> str:
    words = re.split(r"[-_]+", seg.strip("/").lower())
    return " ".join(w for w in words if w).title()


def extract(art) -> BusinessContext:
    """Read business context out of an already-collected SiteArtifact."""
    ctx = BusinessContext()
    pages = [p for p in art.pages.values() if not p.error]
    if not pages:
        return ctx

    org_types = {"Organization", "LocalBusiness", "Store", "Corporation",
                 "FurnitureStore", "HomeAndConstructionBusiness", "Restaurant",
                 "MedicalBusiness", "ProfessionalService", "AutoDealer",
                 "RealEstateAgent", "LegalService", "Dentist"}
    seen_types = Counter()
    locations, states = [], Counter()

    for p in pages:
        for node in _nodes(p):
            ts = _types(node)
            for t in ts:
                seen_types[t] += 1
            if not (set(ts) & org_types):
                continue
            name = _text(node.get("name"))
            if name and not ctx.brand:
                ctx.brand = name
                ctx.evidence["brand"] = p.url
            if not ctx.legal_name:
                ln = _text(node.get("legalName"))
                if ln:
                    ctx.legal_name = ln
            if not ctx.phone:
                ph = _text(node.get("telephone"))
                if ph:
                    ctx.phone, ctx.evidence["phone"] = ph, p.url
            if not ctx.founded:
                fd = _text(node.get("foundingDate"))
                if fd:
                    ctx.founded, ctx.evidence["founded"] = fd[:4], p.url
            addr = node.get("address")
            for a in (addr if isinstance(addr, list) else [addr]):
                if not isinstance(a, dict):
                    continue
                city = _text(a.get("addressLocality"))
                region = _text(a.get("addressRegion"))
                if not (city or region):
                    continue
                full = STATES.get(region.upper(), region)
                loc = {"name": name or city, "city": city, "region": full}
                if loc not in locations:
                    locations.append(loc)
                if full:
                    states[full] += 1

    ctx.locations = locations[:40]
    ctx.states = [s for s, _ in states.most_common(5)]
    ctx.entity_types = [t for t, _ in seen_types.most_common(12)]

    # ---- page-shape signals ------------------------------------------------
    ctx.product_pages = sum(1 for p in pages if "Product" in (p.schema_types or []))
    ctx.location_pages = sum(1 for p in pages
                             if any(h in p.url.lower() for h in LOCATION_HINTS))
    ctx.blog_pages = sum(1 for p in pages
                         if any(h in p.url.lower() for h in BLOG_HINTS))
    ctx.has_ecommerce = ctx.product_pages > 0
    ctx.has_blog = ctx.blog_pages > 0

    # ---- what they sell, from the site's own first-level structure ---------
    # Counting the FIRST path segment across internal links approximates the
    # primary nav without needing to identify a <nav> element, which every CMS
    # marks up differently.
    seg_count, seg_label = Counter(), {}
    for p in pages:
        for link in (p.links_internal or []):
            href = (link.get("href") or "")
            path = href.split("//")[-1]
            path = path[path.find("/"):] if "/" in path else "/"
            seg = path.strip("/").split("/")[0].split("?")[0].split("#")[0]
            if not seg or "." in seg or seg.lower() in NOT_A_CATEGORY:
                continue
            if len(seg) > 40 or seg.isdigit():
                continue
            seg_count[seg.lower()] += 1
            seg_label.setdefault(seg.lower(), _slug_words(seg))
    # A category must (a) be linked from more than one place and (b) actually
    # resolve to a working page we crawled. Link count alone let a broken link
    # named "broken-page" surface as a business section in the client-facing
    # summary — wrong in a way the client notices immediately, which costs more
    # credibility than the whole box earns.
    healthy = set()
    for p in pages:
        if not (200 <= p.status_code < 300):
            continue
        path = p.url.split("//")[-1]
        path = path[path.find("/"):] if "/" in path else "/"
        seg = path.strip("/").split("/")[0].split("?")[0].split("#")[0].lower()
        if seg:
            healthy.add(seg)
    ctx.sections = [seg_label[s] for s, n in seg_count.most_common(12)
                    if n > 1 and s in healthy][:6]
    if ctx.sections:
        ctx.evidence["sections"] = "internal navigation"

    # ---- the site's own words ---------------------------------------------
    # Preferred over anything we could infer, because it is unarguable: it is
    # the sentence they chose to describe themselves with. Schema `description`
    # first (hand-authored), then the homepage meta description (also written
    # by a person), then the H1.
    home = next((p for p in pages if p.url.rstrip("/") ==
                 art.start_url.rstrip("/")), pages[0])
    for node in _nodes(home):
        if set(_types(node)) & org_types:
            d = _text(node.get("description"))
            if d:
                ctx.self_description = d
                ctx.evidence["self_description"] = f"{home.url} (schema description)"
                break
    if not ctx.self_description:
        for cand, where in ((home.meta_description, "meta description"),
                            (home.h1[0] if home.h1 else "", "H1")):
            cand = (cand or "").strip()
            # Too short to be a description, or so long it is a paragraph that
            # would swamp the opening line.
            if 25 <= len(cand) <= 180:
                ctx.self_description = re.sub(r"\s+", " ", cand).rstrip(" .")
                ctx.evidence["self_description"] = f"{home.url} ({where})"
                break

    # ---- brand fallbacks ---------------------------------------------------
    if not ctx.brand:
        title = (home.title or "").strip()
        # "Sofas & Sectionals | Grand Home Furnishings" -> the branded half is
        # whichever side repeats across pages; the last segment is the common
        # convention and a safe default.
        if title:
            parts = re.split(r"\s[|\-–—]\s", title)
            cand = parts[-1].strip() if len(parts) > 1 else title
            if 2 < len(cand) <= 60:
                ctx.brand = cand
                ctx.evidence["brand"] = f"{home.url} (page title)"
    return ctx


# --------------------------------------------------------------- plain English
# Schema.org type names are developer vocabulary. "BreadcrumbList, ImageObject,
# WebPage" printed in a client deliverable is the report showing its working
# rather than telling the reader anything — a business owner cannot act on it
# and will not ask, they will just decide this page is not for them.
#
# Brendan's template never printed raw type names; it asked whether the right
# markup was present, in words. So do we.
ENTITY_WORDS = {
    "organization": "business details",
    "localbusiness": "local business listing",
    "website": "site identity",
    "webpage": "page markup",
    "webpageelement": "page markup",
    "breadcrumblist": "breadcrumb trail",
    "imageobject": "images",
    "logo": "logo",
    "sitenavigationelement": "navigation",
    "article": "articles",
    "blogposting": "blog posts",
    "newsarticle": "articles",
    "faqpage": "FAQ answers",
    "question": "FAQ answers",
    "howto": "how-to steps",
    "product": "products",
    "offer": "pricing",
    "aggregaterating": "star ratings",
    "review": "reviews",
    "service": "services",
    "person": "people",
    "videoobject": "video",
    "event": "events",
    "recipe": "recipes",
    "jobposting": "job listings",
    "postaladdress": "address",
    "openinghoursspecification": "opening hours",
    "contactpoint": "contact details",
    "searchaction": "site search",
    "attorney": "legal services",
    "legalservice": "legal services",
    "medicalbusiness": "medical practice",
    "physician": "medical practice",
    "dentist": "dental practice",
    "restaurant": "restaurant listing",
    "hotel": "hotel listing",
    "realestateagent": "property listings",
    "professionalservice": "professional services",
    "homeandconstructionbusiness": "trade services",
    "collectionpage": "category pages",
    "itemlist": "listings",
    "speakablespecification": "voice-assistant text",
}


def describe_entities(types, limit: int = 6) -> str:
    """
    Turn schema @type names into something a client can read.

    Deduplicated after translation, because several type names collapse to the
    same idea — Organization and LocalBusiness both mean "we told Google who
    this business is", and printing both looks like two findings when it is one.
    An unrecognized type is title-cased rather than dropped: an unknown word is
    better than a silently shorter list.
    """
    out = []
    for t in types or []:
        w = ENTITY_WORDS.get(str(t).strip().lower())
        if not w:
            # CamelCase to spaced words: "MedicalClinic" -> "Medical clinic".
            w = re.sub(r"(?<!^)(?=[A-Z])", " ", str(t).strip()).strip().lower()
            w = w[:1].upper() + w[1:] if w else ""
        if w and w not in out:
            out.append(w)
        if len(out) >= limit:
            break
    return ", ".join(out)
