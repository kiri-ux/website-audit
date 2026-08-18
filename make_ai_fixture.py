"""
Build a deterministic AI-visibility replay corpus with known ground truth.

The interesting cases here are the TRAPS, not the happy paths. An AI-visibility
tool that over-reports is worse than none — it tells a client they're visible
when they aren't. So the corpus deliberately includes:

  * "a grand total of"      — the word "grand" must NOT match "Grand Home Furnishings"
  * "Grand Rapids Michigan" — a place name sharing the first token
  * "Grandiose Furniture"   — a different brand with a prefix collision
  * notgrandhf.com          — a domain that ENDS with the client domain string
  * blog.grandhf.com        — a real subdomain that MUST count
  * www.grandhf.com         — www normalisation

Each recorded answer carries `_expect` flags. verify_ai.py asserts the analyser
reproduces them exactly.
"""
import json
import pathlib
import sys

sys.path.insert(0, ".")
from engine.aivis import ClientProfile, build_panel

PROFILE = dict(
    brand="Grand Home Furnishings",
    domain="grandhf.com",
    category="furniture and mattress retailer",
    products=["sectional sofa", "queen mattress", "dining table"],
    locations=["Roanoke VA", "Virginia", "Bristol TN"],
    competitors=["Wayfair", "Ashley Furniture", "Rooms To Go"],
    aliases=["Grand Home", "Grand Furniture"],
)

def cite(*urls):
    return [{"url": u, "title": "", "domain": u.split("/")[2].replace("www.", "")}
            for u in urls]

# (text, citations, expect_mentioned, expect_cited, note)
CASES = [
    # ---- true positives -------------------------------------------------
    ("Grand Home Furnishings is a well-established furniture retailer operating "
     "18 stores across Virginia, West Virginia and Tennessee.",
     cite("https://www.grandhf.com/about/", "https://www.bbb.org/x"),
     True, True, "full brand name + own domain cited"),

    ("Grand Home has a solid reputation locally, with a 30-day trial on mattresses.",
     cite("https://blog.grandhf.com/mattress-guide"),
     True, True, "alias + SUBDOMAIN must count as cited"),

    ("For furniture in Roanoke, options include Grand Furniture and a few "
     "regional independents.",
     cite("https://grandhf.com/roanoke/"),
     True, True, "alias + bare domain"),

    ("Top picks: Wayfair, Ashley Furniture, and Rooms To Go dominate online.",
     cite("https://www.wayfair.com/", "https://www.ashleyfurniture.com/",
          "https://www.roomstogo.com/"),
     False, False, "competitors only — brand absent"),

    # ---- TRAPS: must NOT register a mention -----------------------------
    ("The showroom had a grand total of forty sofas on display that weekend.",
     cite("https://www.reddit.com/r/furniture/x"),
     False, False, "TRAP: the word 'grand' alone"),

    ("Grand Rapids, Michigan has a thriving furniture manufacturing history.",
     cite("https://en.wikipedia.org/wiki/Grand_Rapids"),
     False, False, "TRAP: place name sharing the first token"),

    ("Grandiose Furniture Co is an unrelated boutique retailer in Ohio.",
     cite("https://grandiosefurniture.example/"),
     False, False, "TRAP: prefix collision with a different brand"),

    ("A home furnishings buyer should compare warranty terms carefully.",
     cite("https://www.consumerreports.org/x"),
     False, False, "TRAP: 'home furnishings' as a generic phrase"),

    # ---- TRAP: domain suffix collision ----------------------------------
    ("Several regional retailers serve the area.",
     cite("https://notgrandhf.com/listing"),
     False, False, "TRAP: domain ENDS with client domain but is not it"),

    ("Reviews are mixed across retailers in the region.",
     cite("https://grandhf.com.evil.example/phish"),
     False, False, "TRAP: client domain as a subdomain of another host"),

    # ---- mentioned but NOT cited (the common real-world case) -----------
    ("Grand Home Furnishings is often recommended for budget sectionals, though "
     "most detailed reviews live on third-party sites.",
     cite("https://www.reddit.com/r/furniture/comments/x",
          "https://www.furniturereviews.example/grand-home"),
     True, False, "mentioned from training data, cited nowhere — the key gap"),

    ("You might consider Grand Home Furnishings alongside Ashley Furniture.",
     cite("https://www.ashleyfurniture.com/", "https://www.wayfair.com/"),
     True, False, "mentioned but rivals cited instead"),

    # ---- www normalisation ---------------------------------------------
    ("Grand Home Furnishings lists delivery options on their site.",
     cite("https://www.grandhf.com/delivery"),
     True, True, "www must normalise to the bare domain"),

    # ---- no citations at all (ungrounded answer) ------------------------
    ("I don't have specific information about furniture retailers in that area.",
     [], False, False, "empty answer, no sources"),
]

PLATFORMS = ["perplexity", "chatgpt", "claude", "gemini", "ai_overview"]
# Different platforms cite at different rates in reality; rotate the case list
# so each platform gets a distinct but deterministic mix.
OFFSETS = {"perplexity": 0, "chatgpt": 3, "claude": 5, "gemini": 7, "ai_overview": 9}


def main():
    p = ClientProfile(**PROFILE)
    queries = build_panel(p)
    corpus, truth = {}, {}
    for plat in PLATFORMS:
        corpus[plat] = {}
        truth[plat] = {}
        off = OFFSETS[plat]
        for i, q in enumerate(queries):
            text, cites, exp_m, exp_c, note = CASES[(i + off) % len(CASES)]
            corpus[plat][q.id] = {"text": text, "citations": cites}
            truth[plat][q.id] = {"mentioned": exp_m, "cited": exp_c, "note": note}

    pathlib.Path("fixture").mkdir(exist_ok=True)
    pathlib.Path("fixture/ai_corpus.json").write_text(json.dumps(corpus, indent=1))
    pathlib.Path("fixture/ai_truth.json").write_text(json.dumps(
        {"profile": PROFILE, "truth": truth}, indent=1))

    n = sum(len(v) for v in corpus.values())
    exp_m = sum(1 for pl in truth.values() for t in pl.values() if t["mentioned"])
    exp_c = sum(1 for pl in truth.values() for t in pl.values() if t["cited"])
    print(f"corpus: {len(PLATFORMS)} platforms x {len(queries)} queries = {n} answers")
    print(f"  expected mentions : {exp_m} ({100*exp_m//n}%)")
    print(f"  expected citations: {exp_c} ({100*exp_c//n}%)")
    print(f"  trap cases        : {sum(1 for c in CASES if 'TRAP' in c[4])} distinct")


if __name__ == "__main__":
    main()
