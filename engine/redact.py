"""
What a client's copy of the report is allowed to say.

TWO THINGS KEEP LEAKING INTO A DELIVERABLE, AND BOTH LEAK THE SAME WAY.

Every rule about the wording of a finding has lived in one of two places: a
line in a model prompt, or the collector that wrote the string. Both are
correct and neither is a guarantee.

  * A prompt is a request. "Never mention that part of a page was omitted"
    was in RULES for weeks, and the top of one client's report still read
    "The middle sections are omitted from the material" - our page slicing,
    printed under Top Issue, with the client asking us what it meant.

  * A collector fix only applies to runs that happen AFTER the fix. Findings
    are stored; the PDF renders fresh from the store on every request. So a
    report that has already been produced keeps saying whatever it said when
    it ran - including the list of demand-side platforms that CONS-04 stopped
    naming three builds ago.

This module is the boundary that catches both, at RENDER time, in the one
document that leaves the building. It is deliberately blunt: it drops whole
sentences rather than editing them, because a half-edited sentence about our
own tooling is worse than no sentence.

The internal HTML report, the operator dashboard and the consent dashboard do
NOT go through this. They are ours, they need the vendor names to be useful,
and hiding our own plumbing from ourselves is how a problem stays invisible.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- our process
#
# Any sentence containing one of these is about how we read the site rather
# than about the site.
_META_PHRASES = (
    "the material", "provided material", "material provided", "the excerpt",
    "the sample", "the snippet", "the content provided", "provided content",
    "was omitted", "are omitted", "is omitted", "were omitted", "omitted from",
    "truncated", "not retrieved", "were retrieved", "was retrieved",
    "not provided", "no content was provided", "the text supplied",
    "in the supplied", "our crawl", "the crawl", "this excerpt",
    # WHERE OUR NUMBER CAME FROM IS OUR PROBLEM.
    #
    # "727 external links point at this site. Measured from our backlink index
    # rather than Search Console, which publishes this report but offers no
    # API for it; Search Console shows a sample, so its own figure will be
    # lower." The first sentence is the finding. The rest is a tour of our
    # data sources and an apology for a discrepancy the client had not
    # noticed, in a document they are paying us to make simpler than this.
    #
    # It stays on the internal report, where whoever is checking the number
    # needs to know which index it came from.
    "measured from our", "from our backlink index", "our backlink index",
    "offers no api", "no api for it", "shows a sample", "its own figure",
    "our index", "our own index", "rather than search console",
    "third-party estimate", "we could not read", "our tooling",
)


def scrub(text: str) -> str:
    """Evidence with any sentence about our own input removed."""
    t = (text or "").strip()
    if not t:
        return t
    parts = re.split(r"(?<=[.!?])\s+", t)
    keep = [s for s in parts
            if not any(p in s.lower() for p in _META_PHRASES)]
    return " ".join(keep).strip()


# ------------------------------------------------------------ our media stack
#
# The demand-side platforms Vici buys through. A client seeing "Beeswax, The
# Trade Desk, xAd/GroundTruth" in their audit is being handed the buying stack,
# which is not theirs to have and not information they asked for. The COUNT is
# the finding either way - "13 marketing pixels fired before consent" is the
# same fact and a better sentence.
_DSP_NAMES = (
    "beeswax", "the trade desk", "tradedesk", "adsrvr", "xad", "groundtruth",
    "doubleclick", "floodlight", "bidr.io", "yahoo", "amazon ad tag",
    "amazon-adsystem", "verizon media", "criteo", "stackadapt", "simpli.fi",
    "simplifi", "adtheorent", "basis", "centro", "el toro", "eltoro",
)


def _has_dsp(s: str) -> bool:
    low = s.lower()
    return any(n in low for n in _DSP_NAMES)


def pixels(text: str) -> str:
    """
    Drop an enumerated list of ad platforms, keep the sentence and the count.

    "13 trackers fired before any consent interaction: Beeswax conversion,
    Beeswax segment, DoubleClick / Floodlight, Floodlight, Google Ads, Google
    Analytics, Meta Pixel, The Trade Desk, Yahoo, xAd/GroundTruth."
                                        becomes
    "13 marketing pixels fired before any consent interaction."

    The list has to be enumerated after a colon or a dash for this to fire. A
    sentence that merely mentions one vendor in passing is left alone - this
    removes a roll-call, not a word.
    """
    t = text or ""
    if not _has_dsp(t):
        return t

    def cut(m):
        return "" if _has_dsp(m.group(1)) else m.group(0)

    # ": a, b, c." or " - a, b, c." up to the sentence end.
    t = re.sub(r"\s*[:—-]\s*([^.;]*,[^.;]*)(?=\.|$)", cut, t)
    # A bare list with no lead-in ("Beeswax, Yahoo and The Trade Desk fired
    # before consent") has no count to keep, so the whole sentence goes.
    parts = re.split(r"(?<=[.!?])\s+", t)
    kept = []
    for s in parts:
        if _has_dsp(s):
            continue
        # A lead-in whose list was just removed ("Trackers seen.") is a stub,
        # not a sentence. It survives only if it still carries the count -
        # which is the part worth keeping.
        if len(s.split()) < 5 and not re.search(r"\d", s):
            continue
        kept.append(s)
    t = " ".join(kept).strip()
    # "trackers" is our word and it sounds like an accusation. Same fact.
    t = re.sub(r"\b(\d+)\s+trackers\b", r"\1 marketing pixels", t)
    t = re.sub(r"\b(\d+)\s+tracker\b", r"\1 marketing pixel", t)
    return t


def client(text: str) -> str:
    """Everything a finding's prose has to survive before a client reads it."""
    return pixels(scrub(text))
