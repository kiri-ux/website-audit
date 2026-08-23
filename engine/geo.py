"""
US geography, for the one question this tool actually asks of it:

    which states does this client sell into?

Everything here exists to answer that. It is not a geocoder and does not try
to be — there is no county database, no city gazetteer, no lat/long. A market
is validated on the ONE part that carries consequence: the state. "Anderson
County, TN" is accepted because TN is real; whether Anderson County exists is
not something the consent checks care about, and pretending to verify it would
mean shipping a 3,143-row county table to reject typos in a label nobody reads.

Why the state matters and the rest does not
-------------------------------------------
The consent scan checks state privacy law. Twenty states have a law we check;
the other thirty do not. A client selling in twelve Tennessee counties needs
TN's requirements tested, and testing California's tells them nothing — it was
the generic default and it was wrong for every client who is not in California.

So the state list feeding the scan is DERIVED from the markets, and the markets
are the thing a person actually types.
"""
from __future__ import annotations
import re

# 50 states, DC, and the inhabited territories. Territories are here because a
# client selling into Puerto Rico is a real thing and silently dropping it
# would be worse than saying "no privacy law we check applies there".
STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida",
    "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico", "VI": "US Virgin Islands", "GU": "Guam",
    "AS": "American Samoa", "MP": "Northern Mariana Islands",
}

_BY_NAME = {v.lower(): k for k, v in STATES.items()}
# The ones people type differently from the postal name.
_BY_NAME.update({
    "washington dc": "DC", "washington d.c.": "DC", "d.c.": "DC",
    "district of columbia": "DC", "puerto rico": "PR",
    "us virgin islands": "VI", "u.s. virgin islands": "VI",
    "virgin islands": "VI", "n. carolina": "NC", "s. carolina": "SC",
    "n. dakota": "ND", "s. dakota": "SD", "w. virginia": "WV",
})

# The separators a person actually uses between markets. The × comes from the
# existing data — something upstream joined with a multiplication sign — and
# semicolons, pipes and newlines all show up in pasted lists.
#
# ASCII "x" is a separator ONLY with whitespace on BOTH sides. Accepting a
# bare `x\s` cut "Knox County, TN" into "Kno" and "County, TN" — and the same
# would have happened to Fairfax, Essex, Lennox and every other county whose
# name ends in x. A separator that eats real data is worse than one that
# misses; a market that stays whole is still readable, one that is cut in half
# is neither readable nor attributable to a state.
_SPLIT = re.compile(r"[×✕✖]|\sx\s|[;|\n\r]+|\s{2,}")

# "Knox County, TN" / "Knoxville TN" / "Nashville, Tennessee"
_TRAILING = re.compile(r"[,\s]+([A-Za-z.\s]{2,30})$")


# ---------------------------------------------------------------- ZIP codes
#
# A ZIP IS A MARKET, AND IT NAMES ITS OWN STATE.
#
# Pasting a media plan's targeting list produces eighty ZIP codes, and every
# one of them came back with a "?" against it - no state, so no privacy law,
# so a scan that skipped the state checks entirely and said nothing about it.
# The operator's reaction was the right one: we should be able to work out
# which state a ZIP is in.
#
# The first three digits are the sectional center facility, and USPS assigns
# those in contiguous per-state ranges. That is a table, not a lookup service:
# forty lines, no network call, no key, and it does not go stale in any way
# that matters (a new ZIP lands inside an existing range).
ZIP3_RANGES = (
    (5, 5, "NY"), (10, 27, "MA"), (28, 29, "RI"), (30, 38, "NH"),
    (39, 49, "ME"), (50, 59, "VT"), (60, 69, "CT"), (70, 89, "NJ"),
    (100, 149, "NY"), (150, 196, "PA"), (197, 199, "DE"), (200, 200, "DC"),
    (201, 201, "VA"), (202, 205, "DC"), (206, 219, "MD"), (220, 246, "VA"),
    (247, 268, "WV"), (270, 289, "NC"), (290, 299, "SC"), (300, 319, "GA"),
    (320, 349, "FL"), (350, 369, "AL"), (370, 385, "TN"), (386, 397, "MS"),
    (398, 399, "GA"), (400, 427, "KY"), (430, 459, "OH"), (460, 479, "IN"),
    (480, 499, "MI"), (500, 528, "IA"), (530, 549, "WI"), (550, 567, "MN"),
    (570, 577, "SD"), (580, 588, "ND"), (590, 599, "MT"), (600, 629, "IL"),
    (630, 658, "MO"), (660, 679, "KS"), (680, 693, "NE"), (700, 714, "LA"),
    (716, 729, "AR"), (730, 749, "OK"), (750, 799, "TX"), (800, 816, "CO"),
    (820, 831, "WY"), (832, 838, "ID"), (840, 847, "UT"), (850, 865, "AZ"),
    (870, 884, "NM"), (889, 898, "NV"), (900, 961, "CA"), (967, 968, "HI"),
    (970, 979, "OR"), (980, 994, "WA"), (995, 999, "AK"),
)


def zip_state(text: str) -> str | None:
    """The state a five-digit ZIP is in, or None if it is not a ZIP."""
    s = (text or "").strip()
    m = re.match(r"^(\d{5})(?:-\d{4})?$", s)
    if not m:
        return None
    z3 = int(m.group(1)[:3])
    for lo, hi, code in ZIP3_RANGES:
        if lo <= z3 <= hi:
            return code
    return None


def state_of(market: str) -> str | None:
    """
    The two-letter state code a market string names, or None.

    Reads the END of the string, because that is where the state goes in every
    natural way of writing one: "Knox County, TN", "Nashville, Tennessee",
    "Memphis TN". A bare state — "Tennessee", "TN" — is also a market, and a
    common one for a client who sells statewide.
    """
    s = (market or "").strip().strip(",")
    if not s:
        return None
    # A ZIP code names a state without naming it.
    z = zip_state(s)
    if z:
        return z
    # The whole string is a state.
    if s.upper() in STATES:
        return s.upper()
    if s.lower() in _BY_NAME:
        return _BY_NAME[s.lower()]
    # Otherwise the tail of it is.
    m = _TRAILING.search(s)
    if m:
        tail = m.group(1).strip().strip(".")
        if tail.upper() in STATES:
            return tail.upper()
        if tail.lower() in _BY_NAME:
            return _BY_NAME[tail.lower()]
    # Last resort: any comma-separated fragment that is a state, so
    # "TN, Knox County" reads as well as "Knox County, TN".
    for part in re.split(r"[,]", s):
        p = part.strip()
        if p.upper() in STATES:
            return p.upper()
        if p.lower() in _BY_NAME:
            return _BY_NAME[p.lower()]
    return None


def split_markets(text: str) -> list:
    """Raw market labels out of one typed or pasted string."""
    if not text:
        return []
    out, seen = [], set()
    for chunk in _SPLIT.split(text):
        label = " ".join((chunk or "").split()).strip(" ,")
        if not label:
            continue
        key = label.lower()
        if key not in seen:
            seen.add(key)
            out.append(label)
    return out


def parse_markets(text: str) -> list:
    """
    [{label, state, state_name, ok}] — one entry per market, in typed order.

    `ok` is False only when no state can be found. That is the single failure
    worth surfacing, because it is the one that silently costs the client a
    whole body of law: a market nobody can attribute to a state contributes
    nothing to the consent scan, and before this it did so without a word.
    """
    rows = []
    for label in split_markets(text):
        st = state_of(label)
        rows.append({"label": label, "state": st,
                     "state_name": STATES.get(st or "", ""),
                     "ok": bool(st)})
    return rows


def states_from_markets(text: str) -> list:
    """Sorted, de-duplicated state codes the markets name."""
    return sorted({r["state"] for r in parse_markets(text) if r["state"]})


def checkable(codes) -> tuple:
    """
    Split state codes into (we check this, we do not).

    Thirty states have no comprehensive privacy law in the scanner's map. A
    client in one of them should be told that plainly — "we looked and there is
    nothing here to check" is a real answer, and it is a very different answer
    from a silent empty list, which is what they got before.
    """
    try:
        from engine.consent.state_checks import STATE_CHECKS
    except Exception:  # noqa: BLE001
        STATE_CHECKS = {}
    have = [c for c in codes if c in STATE_CHECKS]
    lack = [c for c in codes if c not in STATE_CHECKS]
    return have, lack


def summarize(text: str) -> dict:
    """Everything the form needs to describe a markets string in one call."""
    rows = parse_markets(text)
    codes = sorted({r["state"] for r in rows if r["state"]})
    have, lack = checkable(codes)
    return {"markets": rows, "states": codes, "checkable": have,
            "unchecked": lack,
            "unparsed": [r["label"] for r in rows if not r["ok"]]}
