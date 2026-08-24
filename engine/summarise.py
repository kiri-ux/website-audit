"""
Executive summary and prioritized roadmap.

The only page most clients read. Everything here is generated from the SCORED
findings, never from raw crawl data — the scoring pass has already decided what
matters, and re-deciding it in a prompt would produce a summary that disagrees
with the table underneath it.

Two modes:
  * deterministic (default) — assembled from the findings by plain code. Free,
    instant, and it cannot hallucinate. Good enough to ship.
  * LLM polish (optional)   — rewrites the deterministic draft into client-ready
    prose. Enabled when an API key is present; the FACTS still come from the
    deterministic pass, so the model is editing, not deciding.

That split matters. Letting a model choose the findings would let it invent one.
Letting it only rephrase pre-selected findings bounds the damage to tone.
"""
from __future__ import annotations
import json
import os
import re

from .scoring import FAILING, top_issues

# Sentence-start form. Written out rather than derived, because .capitalize()
# turns "E-E-A-T" into "E-e-a-t" and "HTTPS" into "Https".
SECTION_NAMES = {
    "ANA": "Analytics and tracking", "GSC": "Search Console", "GA4": "Google Analytics",
    "TECH": "Technical SEO", "URL": "URL structure", "SEC": "HTTPS and security",
    "CANON": "Canonicalization", "PERF": "Site performance and Core Web Vitals",
    "ONP": "On-page SEO", "MOB": "Mobile SEO", "SCHEMA": "Structured data",
    "INTL": "International SEO", "HTML": "HTML and code quality",
    "EEAT": "E-E-A-T and trust signals", "GEO": "AI Search (GEO)",
    "OFF": "Off-page authority",
    # CONS WAS MISSING, so a client read "CONS has the most ground to make up."
    # Every prefix in the catalog needs an entry here; the `.get(code, code)`
    # fallback is a safety net, not a design, and it fails by printing an
    # internal code in the first paragraph of a paid report.
    "CONS": "Consent and privacy",
}

VERTICAL_NOTE = {
    "ecommerce": ("Product and Review schema, page speed and mobile experience carry "
                  "disproportionate weight for a retailer."),
    "finance_ymyl": ("As a YMYL brand, author credentials, expert review and "
                     "organizational trust signals matter far more than they would "
                     "in most sectors."),
    "local_service": ("LocalBusiness schema, location pages and call tracking are the "
                      "highest-leverage signals for a service business."),
}


# ---------------------------------------------------------------------------
# WHY IT MATTERS — the sentence a checklist cannot write for itself.
#
# A generated report gives you the finding and the fix and stops there. What
# makes a report read as consultancy rather than as tool output is the middle
# step: why this matters TO THIS BUSINESS. That judgment is editorial, so it is
# written here, once, by a human, and selected by evidence — not generated per
# run and not invented by a model.
# ---------------------------------------------------------------------------
WHY_IT_MATTERS = {
    "SEC": "Browsers mark insecure pages with a warning, and Google has used "
           "HTTPS as a ranking signal for a decade.",
    "TECH": "Crawl and indexing problems cap everything downstream: content you "
            "cannot get indexed cannot rank, however good it is.",
    "GEO": "AI tools are increasingly answering questions that used to start "
           "as searches. Being uncitable there removes you from that channel "
           "entirely, and it is a channel your competitors are already in.",
    "SCHEMA": "Structured data is how you get rich results and how AI tools "
              "understand what a page is about. It is one of the few changes "
              "that alters how you appear, not just where you rank.",
    "PERF": "Speed is both a ranking input and a conversion input. The second "
            "effect is usually the larger one and it shows up in revenue first.",
    "ONP": "Titles and headings are the cheapest ranking lever available and the "
           "one most often left to a CMS default.",
    "MOB": "Google indexes the mobile version of your site. A mobile problem is "
           "not a subset of your traffic, it is the version that gets ranked.",
    "CANON": "Duplicate URLs split ranking signals between copies, so the site "
             "competes with itself for its own terms.",
    "EEAT": "For anything involving money, health or expertise, visible authorship "
            "and credentials are what separate a page that ranks from one that "
            "merely exists.",
    "URL": "Architecture decides how authority flows through the site. Deep or "
           "orphaned pages are the ones that quietly never rank.",
    "OFF": "Links remain the strongest off-site signal of authority, and the "
           "hardest to fake. This is the slowest thing to fix, so it is the "
           "first thing to start.",
    "ANA": "Without correct measurement, none of the other work can be proven to "
           "have paid off — which is how budgets get cut.",
    "HTML": "Markup errors rarely cost rankings directly, but they make every "
            "other diagnosis harder and can break rendering in ways that do.",
    "INTL": "Wrong language or region targeting sends the right visitor to the "
            "wrong page, which reads as a bounce rather than as a bug.",
    "GSC": "Search Console is the only source of what people actually typed to "
           "reach you. Nothing else substitutes for it.",
    "GA4": "Behavior data is what turns a ranking into a decision about where to "
           "spend next.",
}

# Overrides where the vertical genuinely changes the argument.
WHY_BY_VERTICAL = {
    "ecommerce": {
        "SCHEMA": "Product and Review markup drive the price, stock and star "
                  "ratings that appear beside a retail listing. Without it you "
                  "compete against listings that show all three.",
        "PERF": "For a retailer this is measured in cart abandonment before it is "
                "measured in rankings.",
    },
    "local_service": {
        "SCHEMA": "LocalBusiness markup is what ties your pages to your physical "
                  "locations. It is the difference between ranking nationally for "
                  "nothing and locally for everything.",
        "ONP": "Location and service terms in titles are the highest-yield change "
               "available to a service business.",
    },
    "finance_ymyl": {
        "EEAT": "For a YMYL brand this is the single largest factor. Google holds "
                "financial content to a standard that no amount of technical work "
                "compensates for.",
    },
}

EFFORT = {
    "SEC": "one server change", "CANON": "one server change",
    "TECH": "developer, hours", "HTML": "developer, hours",
    "PERF": "developer, days", "MOB": "developer, days",
    "SCHEMA": "developer, days", "URL": "developer, days",
    "ONP": "content, ongoing", "EEAT": "content, ongoing",
    "GEO": "content plus one config change", "OFF": "outreach, months",
    "ANA": "analytics, hours", "GSC": "access request", "GA4": "access request",
}


def _pct(v):
    return "—" if v is None else f"{v}"


def _listy(items) -> str:
    """
    a, b and c — the way a person writes it, not 'a, b, c'.

    Takes the Oxford comma when an item already contains "and", because
    "HTML and code quality and International SEO" parses wrong on first read.
    Section names are never case-folded here: .lower() turns "HTTPS" into
    "https" and "AI search visibility (GEO)" into nonsense.
    """
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    oxford = "," if any(" and " in i for i in items) and len(items) > 2 else ""
    return ", ".join(items[:-1]) + oxford + " and " + items[-1]


# ---------------------------------------------------------------------------
# ROOT-CAUSE THEMES.
#
# Written after reading a draft that listed, as its four most important
# findings: "HTTPS consistency", "Entire website uses HTTPS", "No redirect or
# canonical to HTTPS homepage", and "Homepage does not use HTTPS encryption".
# Four rows, one problem — the site is not on HTTPS — and the same "why it
# matters" paragraph printed twice.
#
# That is the single loudest signal that a document was assembled by a machine.
# A person writes that up once. The checkpoint framework is right to hold four
# separate rows (they are separately verifiable), but the summary must speak in
# problems, not rows.
#
# Matched against the checkpoint NAME, in order — first match wins, so put the
# specific before the general.
# ---------------------------------------------------------------------------
THEMES = [
    ("https",       ("https", "ssl", "tls", "certificate", "mixed content"), "SEC"),
    ("canonical",   ("canonical", "duplicate url", "www resolve"),           "CANON"),
    ("indexing",    ("robots.txt", "noindex", "sitemap", "crawl budget",
                     "index coverage"),                                      "TECH"),
    ("redirects",   ("redirect", "301", "302", "redirect chain"),            "TECH"),
    ("schema",      ("schema", "structured data", "rich result", "json-ld"), "SCHEMA"),
    ("titles",      ("title tag", "meta description", "h1", "heading"),      "ONP"),
    ("images",      ("image", "alt text", "next-gen", "webp"),               "PERF"),
    ("speed",       ("core web vital", "largest contentful", "cumulative "
                     "layout", "time to first byte", "page speed", "lcp",
                     "cls", "inp", "lighthouse"),                            "PERF"),
    ("mobile",      ("mobile", "viewport", "tap target", "responsive"),      "MOB"),
    ("ai_access",   ("ai crawler", "llms.txt", "gptbot", "citation",
                     "ai overview", "generative"),                           "GEO"),
    ("authority",   ("backlink", "referring domain", "anchor", "domain "
                     "rating", "authority score"),                           "OFF"),
    ("eeat",        ("author", "about page", "credential", "expertise",
                     "trust", "review policy"),                              "EEAT"),
    ("hreflang",    ("hreflang", "language", "international"),               "INTL"),
    ("architecture", ("internal link", "orphan", "click depth", "breadcrumb",
                      "url structure"),                                      "URL"),
]

THEME_TITLE = {
    "https": "The site is not fully served over HTTPS",
    "canonical": "Duplicate URLs are competing with each other",
    "indexing": "Crawling and indexing are not fully under control",
    "redirects": "Redirects are losing signal",
    "schema": "Structured data is thin or missing",
    # A title should name the problem in terms of the job the thing is failing
    # at, not assert that it is failing. "Not doing their job" makes the reader
    # ask what the job was.
    "titles": "Page titles don't say what each page is about",
    "images": "Images are unoptimized",
    "speed": "The site is slower than the Core Web Vitals thresholds",
    "mobile": "The mobile experience has defects",
    "ai_access": "AI tools cannot properly cite the site",
    "authority": "Off-site authority is behind",
    "eeat": "Trust and expertise signals are weak",
    "hreflang": "Language and region targeting is misconfigured",
    "architecture": "Site architecture is limiting how authority flows",
}


# When no theme matches, the group falls back to its section. The section still
# needs a PROBLEM title rather than the exemplar checkpoint's name — "Meta
# Pixel" is a row, "Measurement has gaps" is a finding a client can act on.
SECTION_PROBLEM_TITLE = {
    "ANA": "Measurement and conversion tracking have gaps",
    "TECH": "Technical foundations need attention",
    "URL": "Site architecture is limiting how authority flows",
    "SEC": "The site is not fully served over HTTPS",
    "CANON": "Duplicate URLs are competing with each other",
    "PERF": "Pages are heavier and slower than they need to be",
    "ONP": "On-page fundamentals are inconsistent",
    "MOB": "The mobile experience has defects",
    "SCHEMA": "Structured data is thin or missing",
    "INTL": "Language and region targeting is misconfigured",
    "HTML": "Markup quality is holding diagnostics back",
    "EEAT": "Trust and expertise signals are weak",
    "GEO": "The site is not set up to be cited by AI search tools",
    "OFF": "Off-site authority is behind",
    "GSC": "Search Console data is not available to us",
    # WAS "Analytics data is not available to us", printed above evidence
    # reading "No conversions recorded for organic search". Those are two
    # different statements and the pair reads as neither: the finding is that
    # nothing is being counted, and the reason is that the events are not set
    # up. "Not available to us" is our access problem, and it belongs on the
    # rows that are actually about access.
    "GA4": "Conversions are not being counted",
}


def _theme_of(checkpoint_name: str, prefix: str) -> tuple:
    """(theme_key, prefix_for_why). Falls back to the section when nothing matches."""
    name = (checkpoint_name or "").lower()
    for key, needles, why_prefix in THEMES:
        if any(n in name for n in needles):
            return key, why_prefix
    return f"section:{prefix}", prefix


# Plain-English names for what each area actually examines. The section titles
# are correct but internal ("On-Page SEO"); these are what you would say out
# loud to the person paying for the audit.
PLAIN_AREA = {
    "TECH": "how search engines read the site",
    "PERF": "page speed",
    "MOB": "how the site renders on a phone",
    "SCHEMA": "the structured data behind your listings",
    "ONP": "page titles and headings",
    "SEC": "whether every page is served securely",
    "GEO": "whether AI search tools can find and cite you",
    "EEAT": "the trust signals Google looks for",
    "URL": "how the site is put together",
    "CANON": "duplicate versions of the same page",
    "OFF": "the links pointing at you from other sites",
    "ANA": "whether your tracking is set up properly",
    "INTL": "language and region targeting",
    "HTML": "the quality of the page code",
    "GSC": "your Search Console data",
    "GA4": "your Analytics data",
}

# Named in this order when several qualify, so the list spans different kinds
# of work rather than three flavours of the same thing.
PLAIN_ORDER = ["PERF", "MOB", "SCHEMA", "GEO", "ONP", "TECH", "SEC", "EEAT",
               "URL", "ANA", "CANON", "OFF", "INTL", "HTML"]


def _plain_areas(assessed: dict, n: int = 3) -> str:
    """
    "everything from page speed and mobile rendering to structured data".

    Note the from/TO construction rather than a comma list. "everything from a,
    b and c" is not English — the phrase needs both ends of the range.
    """
    picked = [PLAIN_AREA[k] for k in PLAIN_ORDER
              if k in assessed and k in PLAIN_AREA][:n]
    if not picked:
        return ""
    if len(picked) == 1:
        return picked[0]
    return f"everything from {_listy(picked[:-1])} to {picked[-1]}"


def _nice_date(stamp) -> str:
    """2026-08-18 14:00 -> 18 August. Nobody says 'on 2026-08-18'."""
    try:
        from datetime import datetime
        d = datetime.strptime(str(stamp).split(" ")[0], "%Y-%m-%d")
        return f"{d.day} {d.strftime('%B')}"
    except Exception:
        return str(stamp).split(" ")[0]


def _midsentence(name: str) -> str:
    """
    Lowercase a section name for use mid-sentence, but only when it is safe.

    "Structured data" -> "structured data". "Mobile SEO", "HTML and code
    quality" and "AI search visibility (GEO)" are left alone, because an
    internal capital means an acronym and lowercasing it is the exact tell we
    are trying to remove.
    """
    if not name:
        return name
    return name.lower() if name[1:] == name[1:].lower() else name


def _why(prefix: str, vertical: str | None) -> str:
    return (WHY_BY_VERTICAL.get(vertical or "", {}).get(prefix)
            or WHY_IT_MATTERS.get(prefix, ""))



# ---------------------------------------------------------------------------
# WHAT WE'LL DO — scope, not instructions.
#
# The audit is a sales document as well as a diagnostic. A step-by-step fix
# ("Add a sitewide 301 from HTTP to HTTPS") is the deliverable we are selling;
# printing it means the client can hand the report to anyone. So the client PDF
# states the WORK, and the specific remediation stays in the internal view and
# in the scope of the engagement.
#
# This is not vagueness for its own sake — each line still names the work
# precisely enough to be quoted and scheduled. It just isn't a how-to.
# ---------------------------------------------------------------------------
SERVICE_ACTION = {
    "https": "Included in the technical phase — we handle the HTTPS migration "
             "and the redirect map end to end.",
    "canonical": "We consolidate the duplicate URLs and set the canonical "
                 "structure during technical setup.",
    "indexing": "We take control of what search engines can reach and index "
                "technical foundation work.",
    "redirects": "We build and implement the redirect map so existing ranking "
                 "value carries across.",
    "schema": "We design and deploy structured data for your key page types, "
              "then monitor how it renders in results.",
    # "Priority templates" is agency shorthand for "the page types that get the
    # most traffic". A client hears a word they cannot picture and stops
    # reading. Name the pages instead.
    "titles": "We rewrite the titles and headings, starting with the pages that "
              "bring in the most traffic, as part of the on-page optimization.",
    "images": "Image optimization and alt text are handled in the on-page and "
              "performance work.",
    "speed": "Performance work — server response, asset delivery and Core Web "
             "Vitals — runs through the technical phase.",
    "mobile": "We resolve the mobile rendering issues alongside the performance "
              "work.",
    # THE DIRECTORY PLAY BELONGS IN THE SCOPE LINE.
    #
    # This described a config change and a wait. For a local service business
    # that is the smaller half: the assistants build their answers out of the
    # directories that list every firm in the county, so the fastest route
    # into an answer is a complete profile on the ones they actually read -
    # which the report now names, per question. Opening up crawler access is
    # the precondition, not the plan.
    # "get you listed on the directories these tools read" was true of the
    # claimable half and a promise nobody can keep about the rest - Super
    # Lawyers refuses self-nominations outright, Best Lawyers is peer review
    # only. The scope line now separates the two the same way the report does.
    "ai_access": "We open the site up to these tools, claim and complete your "
                 "profiles on the directories these tools read, put you "
                 "forward for the peer-selected ones, build the pages that "
                 "answer the questions your buyers are asking, and track "
                 "which answers start citing you.",
    "authority": "Link acquisition and digital PR run continuously through the "
                 "campaign.",
    "eeat": "We build out authorship, credentials and trust signals as part of "
            "the content optimization.",
    "hreflang": "Language and region targeting is corrected during technical "
                "setup.",
    "architecture": "We restructure internal linking so authority reaches the "
                    "pages that earn money.",
}

SERVICE_BY_SECTION = {
    "SEC": SERVICE_ACTION["https"], "CANON": SERVICE_ACTION["canonical"],
    "TECH": SERVICE_ACTION["indexing"], "SCHEMA": SERVICE_ACTION["schema"],
    "ONP": SERVICE_ACTION["titles"], "PERF": SERVICE_ACTION["speed"],
    "MOB": SERVICE_ACTION["mobile"], "GEO": SERVICE_ACTION["ai_access"],
    "OFF": SERVICE_ACTION["authority"], "EEAT": SERVICE_ACTION["eeat"],
    "INTL": SERVICE_ACTION["hreflang"], "URL": SERVICE_ACTION["architecture"],
    "HTML": "Code quality cleanup is folded into the technical phase.",
    "ANA": "We implement and QA the tracking setup so every channel is "
           "measurable before campaign work begins.",
    "GSC": "We get access set up and reporting configured during onboarding.",
    "GA4": "We get access set up and reporting configured during onboarding.",
    # CONSENT IS A TAG CHANGE, AND SAYING SO IS THE POINT.
    #
    # It fell through to the generic "We handle this as part of the build. It
    # is scoped into the engagement, not billed separately." - which answers a
    # billing question nobody asked, under a heading that promises to say what
    # we DO. The work is in the tag container, and naming it is what makes the
    # line worth reading.
    # AND IT IS THREE PIECES OF WORK, NOT ONE.
    #
    # The container change is the last of them and the only one this line
    # named, which undersold the engagement to the point of being wrong: a
    # container cannot hold pixels back until somebody has chosen a consent
    # platform and configured what each category is allowed to do. So the line
    # now covers the review, the recommendation and the implementation, in the
    # order they actually happen.
    "CONS": "We review how the site collects and fires tracking today, "
            "recommend a consent platform and the consent settings to run "
            "with it, and make the container tag changes that hold the "
            "marketing pixels until consent is given.",
}


def service_action(theme_key: str, prefix: str) -> str:
    """The scope line for the client PDF. Never the remediation steps."""
    return (SERVICE_ACTION.get(theme_key)
            or SERVICE_BY_SECTION.get(prefix)
            # WAS: "Covered in the campaign scope - we'll walk you through
            # the sequencing on the kickoff call." A promise to explain later,
            # in the column headed "How we handle it", which is where the
            # explanation was supposed to be.
            or "We handle this as part of the build. It is scoped into the "
               "engagement, not billed separately.")



# ---------------------------------------------------------------------------
# ROADMAP ITEM WORDING.
#
# Two problems, one function.
#
# 1. Checkpoint names arrive in whatever grammar each was written in — "Pages
#    have more than one H1 tag", "Issues with duplicate title tags", "Title
#    length optimized". Printed as a list they read as four documents.
#
# 2. A noun phrase does not say what we are going to DO. "Duplicate meta
#    descriptions" leaves the reader asking whether we are removing them,
#    rewriting them, or merely reporting them. Every line now starts with a
#    verb, because the plan is a list of work, not a list of symptoms.
#
# The verb is scope, not instructions: "Rewrite duplicate page titles" says
# what we take on without handing over the how.
# ---------------------------------------------------------------------------

# The defects we actually see, written as the work. Several checkpoints map to
# the SAME action on purpose — "Titles not unique" and "Duplicate title tags"
# are one job, and the dedupe below then collapses them into one line.

# ---------------------------------------------------------------------------
# The 29 judgment-layer checkpoints. Their catalog names are diagnostic labels
# ("First-hand experience demonstrated"), not work, so the generic fallback
# produced a plan reading "Address first-hand experience demonstrated" twelve
# times over. Every one of these is real content work with a verb attached.
# ---------------------------------------------------------------------------
_JUDGMENT_ACTIONS = {
    "first-hand experience demonstrated":
        "Add first-hand detail — your own cases, photos and specifics",
    "real examples included": "Write up real client examples and outcomes",
    "original insights included":
        "Publish a point of view competitors are not offering",
    "subject matter expertise":
        "Deepen the content so it reads as written by a practitioner",
    "expert-written content": "Put your specialists' knowledge into the copy",
    "expert review process": "Show who reviewed each page, and when",
    "author pages": "Publish author pages for the people behind the work",
    "author credentials": "State each author's qualifications on the page",
    "organization authority": "Build out the case for the firm's standing",
    "industry mentions": "Earn and surface mentions in your industry",
    "brand authority": "Strengthen how the brand is presented across the site",
    "editorial policy": "Publish how content is written, reviewed and updated",
    "business information":
        "Put the full address, hours and legal name where they can be found",
    "customer support information":
        "Make support channels and response times obvious",
    "testimonials": "Add attributed testimonials from real clients",
    "reviews": "Surface reviews on site and keep them current",
    "ai-friendly site architecture":
        "Restructure so AI tools can follow the site",
    "ai-friendly content formatting":
        "Reformat pages so AI tools can extract answers cleanly",
    "question-answer content": "Answer the questions clients actually ask",
    "conversational content": "Write the way people ask, not the way we index",
    "entity optimization": "Make clear who and what each page is about",
    "knowledge graph optimization":
        "Connect the brand to the entities Google already knows",
    "semantic relationships": "Link related topics so the coverage reads whole",
    "citation-worthy content": "Create material worth quoting",
    # "Publish data only you have" read as a riddle, and "Publish a number
    # only you have" was the same riddle with a number in it. What this
    # actually asks for is a page built from the firm's own records - how long
    # their cases take, what they cost, how often they settle - because that
    # is the one kind of page a competitor cannot copy and an AI assistant has
    # to cite rather than paraphrase.
    "original research": "Publish figures from your own records - typical "
                         "timelines, costs and outcomes",
    "statistics & data usage": "Support claims with figures worth citing",
    "expert quotes": "Quote named experts, including your own",
    "author entity optimization": "Establish your authors as recognized names",
    "organization entity optimization":
        "Establish the firm as a recognized entity",
    "brand entity optimization": "Make the brand legible to search and AI",
}

_ACTIONS = {
    # titles & meta
    "issues with duplicate title tags": "Rewrite duplicate page titles",
    "unique title on every page": "Rewrite duplicate page titles",
    "title length optimized": "Bring page titles to the right length",
    "pages have too much text within the title tags":
        "Bring page titles to the right length",
    "unique meta description": "Rewrite duplicate meta descriptions",
    "pages have duplicate meta descriptions": "Rewrite duplicate meta descriptions",
    "pages don't have meta descriptions": "Write the missing meta descriptions",
    "proper length": "Bring meta descriptions to the right length",
    # headings
    "one h1 per page": "Reduce each page to a single H1",
    "pages have more than one h1 tag": "Reduce each page to a single H1",
    "clear heading hierarchy": "Restructure the heading hierarchy",
    "logical h2-h6 hierarchy": "Restructure the heading hierarchy",
    # images
    "images don't have alt attributes": "Write alt text for every image",
    "descriptive filenames": "Rename image files descriptively",
    "responsive images": "Serve responsive image sizes",
    "lazy loading": "Enable lazy loading on below-the-fold images",
    # crawl & indexing
    "pages are blocked from crawling": "Open up the pages search engines cannot reach",
    "pages returned 4xx status code": "Fix or redirect the pages returning errors",
    "internal links are broken": "Repair the broken internal links",
    "orphan pages identified": "Link the orphaned pages into the site",
    "no orphan pages": "Link the orphaned pages into the site",
    "orphaned pages in sitemap": "Link the orphaned pages into the site",
    "pages have only one incoming internal link": "Strengthen internal linking",
    "links have no anchor text": "Add anchor text to bare links",
    "links have non-descriptive anchor text": "Rewrite vague anchor text",
    # https & redirects
    "https consistency": "Move every page onto HTTPS",
    "entire website uses https": "Move every page onto HTTPS",
    "homepage does not use https encryption": "Move every page onto HTTPS",
    "no redirect or canonical to https homepage from http version":
        "Add the sitewide HTTP to HTTPS redirect",
    "links on https pages lead to http pages": "Update internal links to HTTPS",
    "redirect chains and loops": "Clean up redirect chains",
    "redirect consistency": "Standardize redirect behavior",
    # content & code
    "pages have duplicate content issues": "Resolve the duplicate content",
    "pages have low semantic html usage": "Improve the semantic HTML",
    # speed
    "largest contentful paint (lcp)": "Improve Largest Contentful Paint",
    "cumulative layout shift (cls)": "Reduce Cumulative Layout Shift",
    "core web vitals evaluated": "Bring Core Web Vitals into the green",
    "gzip/brotli compression": "Turn on compression at the server",
    "uncompressed pages": "Turn on compression at the server",
    "browser caching": "Set browser caching headers",
    "issues with uncached javascript and css files": "Set browser caching headers",
    # schema
    "website schema": "Add Website schema",
    "article schema": "Add Article schema",
    "product schema": "Add Product schema",
    "faq schema": "Add FAQ schema",
    "organization schema": "Add Organization schema",
    "breadcrumb schema": "Add Breadcrumb schema",
    "structured data completeness": "Complete the structured data",
    # trust & policy pages
    "author pages": "Publish author pages",
    "trust badges": "Add trust and accreditation badges",
    "terms & conditions": "Publish a Terms & Conditions page",
    "disclosure pages": "Publish the required disclosure pages",
    "refund policy": "Publish a refund policy",
    "editorial policy": "Publish an editorial policy",
    # measurement & AI
    "cookie consent implementation": "Add a cookie consent banner",
    "microsoft bing webmaster tools": "Connect Bing Webmaster Tools",
    "ai crawler accessibility": "Unblock the AI crawlers",
    "llms.txt file has formatting issues": "Correct the llms.txt formatting",
    "llms.txt implementation": "Publish an llms.txt file",
    "llms.txt not found": "Publish an llms.txt file",
}

# Fallback rules, applied to the raw checkpoint name when it is not in the map
# above. Each produces a verb-led phrase.
_ACTION_RULES = [
    (r"^pages?\s+(?:do not|don't|dont)\s+have\s+(.+)$", "Add {0}"),
    (r"^pages?\s+have\s+no\s+(.+)$", "Add {0}"),
    (r"^pages?\s+have\s+more than one\s+(.+)$", "Reduce to one {0} per page"),
    (r"^pages?\s+have\s+duplicate\s+(.+)$", "Resolve duplicate {0}"),
    (r"^pages?\s+have\s+too much\s+(.+)$", "Shorten {0}"),
    (r"^pages?\s+have\s+low\s+(.+)$", "Improve {0}"),
    (r"^pages?\s+are\s+(.+)$", "Fix pages that are {0}"),
    (r"^issues?\s+with\s+(.+)$", "Fix {0}"),
    (r"^links?\s+have\s+no\s+(.+)$", "Add {0} to links"),
    (r"^links?\s+have\s+(.+)$", "Fix links with {0}"),
    (r"^images?\s+(?:do not|don't|dont)\s+have\s+(.+)$", "Add image {0}"),
    (r"^missing\s+(.+)$", "Add {0}"),
    (r"^no\s+(.+)$", "Add {0}"),
    (r"^broken\s+(.+)$", "Repair broken {0}"),
    (r"^duplicate\s+(.+)$", "Resolve duplicate {0}"),
]


def roadmap_item(name: str) -> str:
    """One line of the plan: a verb, then the work."""
    s = re.sub(r"\s*\(if applicable\)\s*$", "", str(name or "").strip())
    key = s.lower()
    if key in _ACTIONS:
        return _ACTIONS[key]
    if key in _JUDGMENT_ACTIONS:
        return _JUDGMENT_ACTIONS[key]
    for pat, tmpl in _ACTION_RULES:
        m = re.match(pat, s, flags=re.I)
        if m:
            body = m.group(1).strip().rstrip(".")
            # Lower-case the first letter unless it is an acronym, so
            # "Add Meta descriptions" does not appear mid-phrase.
            if body[1:2].islower():
                body = body[0].lower() + body[1:]
            return tmpl.format(body)
    # Nothing matched: it is already a bare noun phrase from the template.
    body = s[0].lower() + s[1:] if s[1:2].islower() else s
    return f"Address {body}"


SEV_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Opportunity": 4}

# What each score band actually buys them, in the reader's terms. Keyed on the
# band names in engine/scoring.BANDS.
SCORE_MEANS = {
    "Excellent": "the fundamentals are in place and the work from here is "
                 "competitive rather than corrective",
    "Strong": "the site is in good shape, with a short list of specific gaps",
    "Needs Improvement": "the site works, but enough is missing that it is "
                         "not competing on equal footing",
    "Weak": "several of the basics search engines and AI tools rely on "
            "are missing",
    "Critical": "the foundations are not in place, and that is holding back "
                "everything built on top of them",
}


def _group_issues(findings: dict, catalog: dict, meta: dict, limit: int = 5) -> list:
    """
    Collapse the top findings into distinct PROBLEMS, worst first.

    Draws from a wide pool (40 findings) rather than the top 5, because after
    grouping, four of the top five can turn out to be one problem — and taking
    only five inputs would then leave two items on the page.

    Each group keeps its full membership, and the write-up says how many
    checkpoints it covers. Nothing is hidden: the individual rows are all still
    in the appendix, they are just not each given a headline.
    """
    groups = {}
    for cid, f in top_issues(findings, catalog, 40):
        m = catalog.get(cid, {})
        name = m.get("checkpoint", cid)
        prefix = (m.get("prefix") or cid.split("-")[0])
        key, why_prefix = _theme_of(name, prefix)
        g = groups.setdefault(key, {"members": [], "why_prefix": why_prefix,
                                    "prefix": prefix})
        g["members"].append((cid, name, f))

    # MERGE GROUPS THAT WOULD PRINT THE SAME TITLE.
    #
    # A group keyed on the theme "eeat" and a group that matched no theme and
    # fell back to the section "EEAT" are different keys with identical titles,
    # so the report printed "Trust and expertise signals are weak" as both
    # finding 2 and finding 3, with different evidence under each. Two headline
    # slots spent on one problem, and it reads as a bug because it is one.
    def _title_for(key, g):
        return (THEME_TITLE.get(key) or SECTION_PROBLEM_TITLE.get(g["prefix"])
                or (g["members"][0][1] if g["members"] else key))

    merged = {}
    for key, g in groups.items():
        t = _title_for(key, g)
        if t in merged:
            merged[t][1]["members"].extend(g["members"])
        else:
            merged[t] = (key, g)
    groups = {k: g for k, g in merged.values()}

    # AND MERGE GROUPS THAT WOULD PRINT THE SAME SENTENCE.
    #
    # The pass above catches identical titles. It does not catch two DIFFERENT
    # titles resting on the same observation, which is what shipped: findings 2
    # and 3 read "On-page fundamentals are inconsistent" and "Page titles don't
    # say what each page is about", and underneath both, word for word, "83
    # pages share 25 duplicated title tags." Two of the client's five headline
    # slots spent on one measurement, with the same rationale and the same
    # remedy printed twice.
    #
    # If the exemplar evidence is the same, it is the same problem however the
    # theme matcher keyed it. The earlier group wins the title because the
    # ordering it arrived in is the scoring engine's own priority.
    def _norm_ev(members):
        if not members:
            return ""
        ev = (members[0][2].get("evidence") or "").strip().lower()
        return " ".join(ev.split())

    by_ev, kept = {}, {}
    for key, g in groups.items():
        g["members"].sort(key=lambda t: SEV_RANK.get(t[2].get("severity"), 5))
        ev = _norm_ev(g["members"])
        # Short evidence is not distinctive enough to merge on — "Not detected."
        # is shared by a dozen unrelated checkpoints.
        if len(ev) >= 40 and ev in by_ev:
            kept[by_ev[ev]]["members"].extend(g["members"])
            continue
        if len(ev) >= 40:
            by_ev[ev] = key
        kept[key] = g
    groups = kept

    out = []
    for key, g in groups.items():
        # Exemplar = worst member; ties broken by the order top_issues gave us,
        # which is already the scoring engine's own priority.
        g["members"].sort(key=lambda t: SEV_RANK.get(t[2].get("severity"), 5))
        cid, name, f = g["members"][0]
        short = (f.get("evidence") or "").strip().rstrip(".") + "."
        finding = short
        if len(g["members"]) > 1:
            # No list of checkpoint names. They are template strings written for
            # us, and several of them end in "included", so the sentence came
            # out as "including Real examples included, ... and Original
            # insights included." The count is the part that carries meaning —
            # this is systemic, not a one-off.
            #
            # "Checks", not "signals". The cover says "we measured 237 of 313
            # checks" and the appendix is headed "Full Checkpoint Detail", so a
            # third word for the same object left the reader working out
            # whether a signal was a page, a check, or something new.
            # WAS: "The same gap shows up across 5 separate checks." Our
            # bookkeeping, phrased as a finding. The number matters - it is
            # what makes this systemic rather than a one-off - so it stays,
            # attached to the thing it describes instead of standing alone.
            finding += (f" Found on {len(g['members'])} separate checks.")
        action = (f.get("recommendation") or "").strip()
        if not action:
            action = next((x.get("recommendation", "").strip()
                           for _, _, x in g["members"]
                           if x.get("recommendation")), "")
        out.append({
            "id": cid,
            "ids": [c for c, _, _ in g["members"]],
            "title": (THEME_TITLE.get(key)
                      or SECTION_PROBLEM_TITLE.get(g["prefix"]) or name),
            "severity": f.get("severity", "Medium"),
            "count": len(g["members"]),
            "finding": finding,
            "finding_short": short,
            "why": _why(g["why_prefix"], meta.get("vertical")),
            "action": action,                     # internal: the actual fix
            "service": service_action(key, g["prefix"]),   # client-facing scope
            "effort": EFFORT.get(g["why_prefix"], ""),
            "area": SECTION_NAMES.get(g["why_prefix"], g["why_prefix"]),
        })
    out.sort(key=lambda d: (SEV_RANK.get(d["severity"], 5), -d["count"]))
    return out[:limit]


def build_summary(findings: dict, scores: dict, catalog: dict,
                  meta: dict | None = None) -> dict:
    """Deterministic executive summary. No model required."""
    meta = meta or {}
    secs = scores.get("sections") or {}
    assessed = {k: v for k, v in secs.items() if v.get("score") is not None}

    strong = sorted(assessed.items(), key=lambda kv: -kv[1]["score"])[:4]

    # ---- THE BIGGEST OPPORTUNITY IS NOT THE LOWEST SCORE ----------------
    #
    # It was, and it produced the wrong answer on a real audit: consent and
    # privacy scored 30, won the slot, and the single most prominent
    # paragraph in a document sold to a law firm was about cookie banners.
    # The operator's reaction was the correct one - "fixing the consent of
    # the site doesn't drive business."
    #
    # Both facts matter. A 30 is worse than a 55, and being invisible when
    # somebody searches for a DUI attorney is worth more than either. So the
    # ranking multiplies HOW BAD by HOW MUCH IT IS WORTH, rather than
    # pretending the second half does not exist.
    #
    # The weights are a claim about revenue, not about severity, and they are
    # deliberately blunt:
    #
    #   * 1.0 - areas where the money is. Whether people can find them, what
    #     the pages say, whether they are trusted, whether they get cited.
    #   * 0.75 - the plumbing those depend on. Real work, one step removed
    #     from a lead.
    #   * 0.4 - correctness and compliance. Genuinely important, occasionally
    #     urgent, and never the reason a client's phone rings. Consent lives
    #     here, and a 30 in consent still beats a 75 in on-page, which is the
    #     escape hatch that keeps a real emergency visible.
    #
    # Nothing is hidden by this: every area keeps its score, its own section
    # and its place on the roadmap. What changes is only which one gets the
    # headline.
    IMPACT = {
        "GEO": 1.0, "ONP": 1.0, "EEAT": 1.0, "OFF": 1.0, "SCHEMA": 0.95,
        "TECH": 0.75, "PERF": 0.75, "MOB": 0.75, "URL": 0.6, "CANON": 0.6,
        "SEC": 0.6, "GSC": 0.5, "GA4": 0.5, "ANA": 0.5,
        "CONS": 0.4, "HTML": 0.4, "INTL": 0.35,
    }

    def _opportunity_rank(kv):
        code, v = kv
        gap = 100 - (v.get("score") or 0)
        return -(gap * IMPACT.get(code, 0.7))

    weak = sorted(assessed.items(), key=_opportunity_rank)[:4]
    # NOTE: nothing else consumed the old worst-score list, so there is no
    # second ordering to keep in sync. The roadmap builds its own ordering
    # from the findings and the appendix prints every area regardless.

    # ---------- What's Working ----------
    # Deliberately NOT one bullet per section in identical grammar. Four
    # consecutive sentences of the form "X scores N/100 (R) — a of b passing"
    # is the single loudest tell that a document was assembled rather than
    # written. Clean areas get grouped into one sentence; only an area with
    # something specific to say earns its own.
    clean, notable = [], []
    for code, v in strong:
        if v["score"] < 75:
            continue
        passes = sum(1 for cid, f in findings.items()
                     if (catalog.get(cid, {}) or {}).get("prefix") == code
                     and f["status"] == "Pass")
        # Count against ASSESSED checkpoints, not the section total. Saying
        # "1 of 4 passing" next to a 94/100 Excellent rating reads as a
        # contradiction; the other 3 were Need Access or N/A, not failures.
        if v["score"] >= 95 and v.get("failing", 0) == 0:
            clean.append((SECTION_NAMES.get(code, code), passes))
        else:
            notable.append((code, v, passes))

    # ONE AREA, ONE CARD.
    #
    # These used to be grouped into a single sentence - "Canonicalization,
    # International SEO and Mobile SEO came back clean" - to avoid four
    # identical-looking bullets. That reasoning holds for PROSE and not for
    # what the renderer actually does with them: it draws each entry as a
    # card with a plain-English line about the area underneath, so grouping
    # produced one wide card naming three areas and explaining none of them.
    # Three areas that came back clean are three pieces of good news.
    # SAME FACT, THREE TIMES, IN THE SAME WORDS.
    #
    # "X came back clean - all N checks passing" under three cards in a row
    # reads as one sentence stamped out with the nouns swapped, which is
    # exactly the machine-assembled tell the rest of this file exists to
    # avoid. The area name is the card's own subject, so the line under it
    # should be the NUMBER, not a sentence repeating the heading.
    working = []
    for name, passes in clean:
        working.append(f"{name}: {passes} of {passes} checks passed."
                       if passes != 1 else
                       f"{name}: the one check here passed.")
    for code, v, passes in notable[:2]:
        working.append(
            f"{SECTION_NAMES.get(code, code)}: {passes} of {passes + v['failing']} "
            f"checks passed, scoring {v['score']} out of 100.")
    # NO STRENGTHS MEANS NO STRENGTHS SECTION.
    #
    # This filled the gap with "No area came back Strong. That's unusual, and
    # it means the fixes below are foundations rather than tuning." Under a
    # heading that says Current Strengths, on a document going to a paying
    # client, that is a section whose only content is that they have none -
    # and the reader has to get past it to reach the work. An empty list is
    # left empty; the renderer skips the heading.

    # ---------- Priority Issues ----------
    issues = []
    for cid, f in top_issues(findings, catalog, 5):
        m = catalog.get(cid, {})
        issues.append(f"{m.get('checkpoint', cid)} ({f['severity']}): "
                      f"{f.get('evidence','').rstrip('.')}.")

    # ---------- Biggest Opportunity ----------
    opp = ""
    if weak:
        code, v = weak[0]
        gaps = [cid for cid, f in findings.items()
                if (catalog.get(cid, {}) or {}).get("prefix") == code
                and f["status"] in FAILING]
        names = [catalog.get(c, {}).get("checkpoint", c) for c in gaps[:5]]
        # "6 of the 6 checks we could run need work" — "we could run" is our
        # plumbing showing through, and "6 of the 6" reads like a typo rather
        # than the point, which is that EVERY check in the area failed.
        n_fail, n_done = v["failing"], v["checked"]
        if n_fail and n_fail == n_done:
            count = (f"every one of the {n_done} checks here needs work"
                     if n_done > 1 else "the one check here needs work")
        else:
            count = f"{n_fail} of {n_done} checks need work"
        opp = (f"{SECTION_NAMES.get(code, code)} has the most ground to make "
               f"up. It scores {v['score']} out of 100, and {count}"
               + (f" — {_listy(names[:3])} among them." if names else "."))
        why = _why(code, meta.get("vertical"))
        if why:
            opp += " " + why
        note = VERTICAL_NOTE.get(meta.get("vertical") or "")
        if note and not WHY_BY_VERTICAL.get(meta.get("vertical") or "", {}).get(code):
            opp += " " + note
        # AND WHAT WE WOULD DO ABOUT IT.
        #
        # The block named the area, the score, and the failing checks, then
        # stopped - so the single most prominent paragraph in the document was
        # all diagnosis and no offer. Every finding further down already
        # carries its scope line; the one place a client actually reads in
        # full did not. "This isn't the full picture" was exactly right: the
        # picture was missing the half we get paid for.
        act = service_action("", code)
        if act:
            opp += " " + act

    # ---------- the five things that matter ----------
    # A ranked shortlist with a stated reason, rather than 313 rows at equal
    # weight. Clients do not act on a checklist; they act on an argument.
    five = _group_issues(findings, catalog, meta, limit=5)

    # ---------- overview ----------
    o = scores.get("overall", {}) or {}
    n_fail = sum(1 for f in findings.values() if f["status"] in FAILING)
    n_na = sum(1 for f in findings.values() if f["status"] == "Need Access")
    ctx = (meta.get("extras") or {}).get("context") or {}
    client = meta.get("client") or ctx.get("brand") or "the site"

    # Sentence 1 is about the BUSINESS, not the audit. It is the only part of
    # this document that could not have been written about any other client,
    # and it comes first for exactly that reason.
    # RECOMPUTE, DO NOT REPLAY.
    #
    # `describe` was written into extras at scan time, so every wording fix to
    # that sentence used to require a re-crawl to see — on a report that is
    # rendered fresh from stored findings on every request. The raw context
    # fields are stored beside it, so the sentence can be rebuilt here and an
    # old audit picks up the current wording the moment the page is reloaded.
    #
    # The stored string stays as the fallback: a context dict from an older
    # schema may not carry the fields describe() reads.
    lead = ""
    try:
        from engine.context import BusinessContext as _BC
        import dataclasses as _dc
        fields = {f.name for f in _dc.fields(_BC)}
        if fields & set(ctx):
            lead = _BC(**{k: v for k, v in ctx.items()
                          if k in fields}).describe().strip()
    except Exception:  # noqa: BLE001
        lead = ""
    lead = lead or (ctx.get("describe") or "").strip()
    parts = []
    if lead:
        # The quoted form ends with a closing quote, so the sentence-ending
        # period has to go inside it or the next sentence runs on.
        parts.append(lead[:-1] + '."' if lead.endswith('"')
                     else lead.rstrip(".") + ".")
    # WHAT WE CHECKED, in words that mean something.
    #
    # The previous line read "worked through 159 checkpoints across 13 areas",
    # which tells a business owner nothing — it is a unit only we use. Name the
    # actual subjects instead, drawn from the areas we really assessed, so the
    # sentence is both meaningful and specific to this run.
    checked = _plain_areas(assessed)
    # "Crawled" is our word for our machinery. To a client it reads as a robot
    # ran and printed this, which undercuts the one sentence where we say what
    # we looked at. "Reviewed" is the same claim in their language — and it is
    # accurate, because a person reads this before it goes out.
    # NAME THE CLIENT IN THE FIRST SENTENCE.
    #
    # The opener used to quote their meta description, which carried the brand
    # name by accident. Dropping that quote — twice rejected — left a first
    # line that could have been about anybody, on a document with their name
    # on the cover but not in the copy.
    _brand = (ctx.get("brand") or meta.get("client") or "").strip()
    _who = f" for {_brand}" if _brand else ""
    parts.append(
        f"We reviewed {meta.get('pages_crawled') or 0} pages of "
        f"{_host(meta.get('url'))}{_who}"
        + (f" and looked at {checked}." if checked else "."))
    if o.get("score") is not None:
        urgent = sum(1 for f in findings.values()
                     if f["status"] in FAILING
                     and f.get("severity") in ("Critical", "High"))
        # SAY WHAT THE NUMBER MEANS, NOT ITS LABEL.
        #
        # "It scores 69 out of 100 (needs improvement)." puts our internal
        # band name in brackets and leaves the reader to work out what it
        # buys them. The band is still what decides the sentence - it is just
        # written out as a consequence instead of a tag.
        parts.append(
            f"It scores {o['score']} out of 100, which means "
            f"{SCORE_MEANS.get(str(o['rating']), 'there is work to do here')}. "
            + (f"{n_fail} things are worth fixing, and {urgent} of those should "
               f"be resolved within 30 days."
               if urgent else
               f"{n_fail} things are worth fixing, none of them urgent."))
    else:
        parts.append(f"We are not publishing an overall score: too few areas "
                     f"could be assessed for the number to mean anything. "
                     f"{n_fail} things are worth fixing in the areas we could "
                     f"check.")
    # Count what the CLIENT is actually blocked on, over the whole catalog —
    # the same denominator the coverage strip uses. The old line counted every
    # Need Access row against the client and used a different denominator from
    # the chart three inches above it, so one page carried two numbers for the
    # same fact and the larger one was an accusation.
    try:
        from engine.access import counts as _access_counts
        n_client = _access_counts(findings, catalog)["client"]
    except Exception:  # noqa: BLE001
        n_client = n_na
    if n_client:
        parts.append(f"Another {n_client} checks read from your Search Console "
                     f"and Analytics, which we need read-only access to. Those "
                     f"are left out of the score rather than counted against "
                     f"you.")
    overview = " ".join(parts)

    # The single most consequential finding, said plainly and once.
    headline = ""
    if five:
        top = five[0]
        # The SHORT form here on purpose: the pull quote sits a few inches
        # above the same item written out in full, and repeating the grouping
        # clause verbatim in both places is its own kind of machine tell.
        headline = (f"Top issue: {top['title']} — "
                    f"{top.get('finding_short', top['finding']).rstrip('.')}.")

    return {"overview": overview, "headline": headline, "working": working,
            "issues": issues, "five_things": five, "opportunity": opp,
            "context": ctx, "roadmap": build_roadmap(findings, catalog),
            "generated_by": "deterministic"}


def _host(url) -> str:
    if not url:
        return "the site"
    h = str(url).split("//")[-1].split("/")[0]
    return h or "the site"


def build_roadmap(findings: dict, catalog: dict) -> list:
    """
    Group actionable findings into phases by severity.

    Sequenced by severity rather than by section, because that is the order a
    client should actually work in — and it makes the roadmap fall out of the
    scoring rubric instead of being invented separately.
    """
    buckets = {"Critical": [], "High": [], "Medium": [], "Low": [], "Opportunity": []}
    for cid, f in findings.items():
        if f["status"] not in FAILING:
            continue
        sev = f.get("severity", "Medium")
        if sev in buckets:
            m = catalog.get(cid, {})
            item = roadmap_item(m.get("checkpoint", cid))
            # Two checkpoints often describe one defect ("One H1 per page" and
            # "Pages have more than one H1 tag"). Once normalized they collide,
            # and a plan that lists the same job twice looks careless.
            if item not in buckets[sev]:
                buckets[sev].append(item)

    phases = []
    if buckets["Critical"] or buckets["High"]:
        phases.append({
            "phase": "Phase 1 — Immediate (0–30 days)",
            "rationale": "Blocking issues. These come before any content work.",
            "actions": (buckets["Critical"] + buckets["High"])[:10]})
    if buckets["Medium"]:
        phases.append({
            "phase": "Phase 2 — Short term (30–90 days)",
            "rationale": "Meaningful gains for moderate effort.",
            "actions": buckets["Medium"][:12]})
    if buckets["Low"]:
        phases.append({
            "phase": "Phase 3 — Ongoing (90+ days)",
            "rationale": "Cleanup, folded into normal release work.",
            "actions": buckets["Low"][:10]})
    if buckets["Opportunity"]:
        phases.append({
            "phase": "Growth initiatives",
            "rationale": "Growth work, not repairs.",
            "actions": buckets["Opportunity"][:8]})
    return phases


# --------------------------------------------------------------------------
def polish_with_llm(summary: dict, meta: dict) -> dict:
    """
    Optional: rewrite the deterministic draft as client-ready prose.

    The model receives the ALREADY-SELECTED facts and is told to rephrase only.
    It cannot add findings, and on any failure the deterministic version is
    returned unchanged — a summary that silently degrades to plain English is
    far better than one that invents a problem.
    """
    key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        return summary

    prompt = (
        "You are writing the executive summary of a professional SEO audit for a "
        "paying client.\n\n"
        f"Client: {meta.get('client')}\nWebsite: {meta.get('url')}\n"
        f"Business type: {meta.get('vertical') or 'general'}\n\n"
        "Below are the findings ALREADY SELECTED by the scoring engine. Rewrite "
        "them as clear, confident, non-hyperbolic prose suitable for a business "
        "owner.\n\n"
        "STRICT RULES:\n"
        "- Do NOT add any finding, number, or claim that is not below.\n"
        "- Do NOT soften or dramatize the severity.\n"
        "- Keep every number exactly as given.\n"
        "- Do NOT merge or split the items you are given.\n"
        "\n"
        "VOICE — this is sold as expert analysis and must not read as generated "
        "text. These are the tells to avoid, and tests check for them:\n"
        "- Never write consecutive sentences with the same grammatical shape "
        "(e.g. 'X scores N/100 (R) — a of b passing' repeated). Vary the "
        "construction and the sentence length.\n"
        "- Never repeat the same rationale twice on a page.\n"
        "- Banned words and phrases: leverage, unlock, delve, seamless, "
        "cutting-edge, game-changing, harness, elevate, supercharge, "
        "best-in-class, robust solution, landscape, tapestry, navigate the, "
        "in today's, it is important/worth noting, furthermore, moreover.\n"
        "- Do not open with 'This audit'. Lead with the client's business.\n"
        "- Keep acronyms cased correctly: HTTPS, SEO, GEO, HTML, E-E-A-T.\n"
        "- British or American spelling is fine, but be consistent.\n\n"
        f"OVERVIEW: {summary['overview']}\n\n"
        f"WHAT'S WORKING:\n" + "\n".join(f"- {x}" for x in summary["working"]) + "\n\n"
        f"PRIORITY ISSUES:\n" + "\n".join(f"- {x}" for x in summary["issues"]) + "\n\n"
        f"BIGGEST OPPORTUNITY: {summary['opportunity']}\n\n"
        "Return JSON only: {\"overview\": str, \"working\": [str], "
        "\"issues\": [str], \"opportunity\": str}"
    )

    try:
        import urllib.request
        if os.getenv("ANTHROPIC_API_KEY"):
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps({
                    "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
                    "max_tokens": 1500,
                    "messages": [{"role": "user", "content": prompt}]}).encode(),
                headers={"Content-Type": "application/json",
                         "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
                         "anthropic-version": "2023-06-01"}, method="POST")
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read())
            text = "".join(b.get("text", "") for b in d.get("content", [])
                           if b.get("type") == "text")
        else:
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=json.dumps({
                    "model": os.getenv("OPENAI_MODEL", "gpt-4.1"),
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"}}).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
                method="POST")
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read())
            text = d["choices"][0]["message"]["content"]

        start, end = text.find("{"), text.rfind("}")
        polished = json.loads(text[start:end + 1])
        for k in ("overview", "working", "issues", "opportunity"):
            if k in polished and polished[k]:
                summary[k] = polished[k]
        summary["generated_by"] = "llm_polished"
    except Exception as e:
        summary["polish_error"] = f"{type(e).__name__}: {e}"
    return summary
