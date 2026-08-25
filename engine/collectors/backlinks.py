"""
Off-page authority collector — 29 checkpoints, the whole OFF section.

One interface, two vendors. The template cites "Ahrefs / Semrush" for every row,
meaning either satisfies it — so this picks whichever is configured and records
which one answered, in `source`.

That choice is a real cost decision, not a preference. From the §9.1 spike:
Semrush's irreplaceable value in this audit is the keyword and backlink data,
NOT the 94 site-audit rows your own crawler already covers. If you are paying
for Semrush at all, it is for this file.

No credentials -> all 29 rows Need Access at confidence 0.
"""
from __future__ import annotations
import json
import os
import urllib.parse
import urllib.request

OFF_IDS = [f"OFF-{i:02d}" for i in range(1, 30)]


def _f(status, value=None, evidence="", severity="Medium", rec="", conf=1.0,
       src="backlinks"):
    return {"status": status, "value": value or {}, "evidence": evidence,
            "affected_pages": [], "severity": severity, "recommendation": rec,
            "confidence": conf, "source": src}


def _need(reason, src="backlinks_unconfigured"):
    return {cid: _f("Need Access", {}, reason, "Medium",
                    "Configure AHREFS_API_KEY or SEMRUSH_API_KEY on the worker to "
                    "populate the off-page section.", 0.0, src) for cid in OFF_IDS}


def _get(url, timeout=60, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


# ---------------------------------------------------------------- Ahrefs
def _ahrefs(domain: str) -> dict:
    key = os.getenv("AHREFS_API_KEY")
    base = "https://api.ahrefs.com/v3/site-explorer"
    hdr = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    q = urllib.parse.urlencode({"target": domain, "mode": "domain",
                                "protocol": "both"})
    metrics = json.loads(_get(f"{base}/domain-rating?{q}", headers=hdr))
    backlinks = json.loads(_get(f"{base}/backlinks-stats?{q}", headers=hdr))
    return {"vendor": "ahrefs",
            "domain_rating": (metrics.get("domain_rating") or {}).get("domain_rating"),
            "backlinks": (backlinks.get("metrics") or {}).get("live"),
            "referring_domains": (backlinks.get("metrics") or {}).get("live_refdomains"),
            "raw": {"metrics": metrics, "backlinks": backlinks}}


# ---------------------------------------------------------------- Semrush
def _semrush(domain: str) -> dict:
    key = os.getenv("SEMRUSH_API_KEY")
    q = urllib.parse.urlencode({
        "type": "backlinks_overview", "key": key, "target": domain,
        "target_type": "root_domain",
        "export_columns": "ascore,total,domains_num,ips_num,follows_num,"
                          "nofollows_num,texts_num,images_num"})
    txt = _get(f"https://api.semrush.com/?{q}")
    lines = [l for l in txt.strip().splitlines() if l]
    if len(lines) < 2:
        raise RuntimeError(f"unexpected Semrush response: {txt[:200]}")
    cols = lines[0].split(";")
    vals = lines[1].split(";")
    d = dict(zip(cols, vals))
    def num(k):
        try: return int(float(d.get(k, 0)))
        except (TypeError, ValueError): return None
    return {"vendor": "semrush",
            "authority_score": num("Authority Score") or num("ascore"),
            "backlinks": num("Total") or num("total"),
            "referring_domains": num("Domains Num") or num("domains_num"),
            "referring_ips": num("Ips Num") or num("ips_num"),
            "follows": num("Follows Num") or num("follows_num"),
            "nofollows": num("Nofollows Num") or num("nofollows_num"),
            "raw": d}


# ---------------------------------------------------------------- public
def collect_backlinks(domain: str) -> dict:
    """Fill the OFF section from whichever vendor is configured."""
    if not (os.getenv("AHREFS_API_KEY") or os.getenv("SEMRUSH_API_KEY")):
        return _need("No backlink data provider is configured.")

    try:
        data = _ahrefs(domain) if os.getenv("AHREFS_API_KEY") else _semrush(domain)
    except Exception as e:
        return _need(f"Backlink API request failed: {type(e).__name__}: {e}",
                     "backlinks_error")

    vendor = data["vendor"]
    out = {}
    bl = data.get("backlinks")
    rd = data.get("referring_domains")
    auth = data.get("domain_rating") or data.get("authority_score")

    if bl is not None:
        out["OFF-01"] = _f("Pass", {"backlinks": bl},
                           f"{bl:,} total backlinks ({vendor}).", "Low", src=vendor)
    if rd is not None:
        sev = "Low" if rd >= 100 else ("Medium" if rd >= 25 else "High")
        out["OFF-02"] = _f("Pass" if rd >= 25 else "Fail", {"referring_domains": rd},
                           f"{rd:,} referring domains ({vendor}).", sev,
                           "" if rd >= 25 else "Referring-domain count is low; "
                                               "prioritize digital PR and "
                                               "resource-page link building.",
                           src=vendor)
    if data.get("referring_ips") is not None:
        out["OFF-03"] = _f("Pass", {"referring_ips": data["referring_ips"]},
                           f"{data['referring_ips']:,} referring IPs.", "Low", src=vendor)
    if auth is not None:
        label = "Domain Rating" if vendor == "ahrefs" else "Authority Score"
        key = "OFF-05" if vendor == "ahrefs" else "OFF-06"
        sev = "Low" if auth >= 40 else ("Medium" if auth >= 20 else "High")
        out[key] = _f("Pass" if auth >= 20 else "Fail", {"authority": auth},
                      f"{label} {auth} ({vendor}).", sev, src=vendor)
    if data.get("follows") is not None and data.get("nofollows") is not None:
        tot = data["follows"] + data["nofollows"]
        pct = round(100 * data["follows"] / tot, 1) if tot else 0
        out["OFF-13"] = _f("Pass" if pct >= 50 else "Warning",
                           {"follow_pct": pct, "follow": data["follows"],
                            "nofollow": data["nofollows"]},
                           f"{pct}% of backlinks are follow links.",
                           "Low" if pct >= 50 else "Medium", src=vendor)

    # Everything the overview endpoint does not cover stays honest.
    for cid in OFF_IDS:
        out.setdefault(cid, _f(
            "Need Access", {},
            f"Not retrieved — requires an additional {vendor} endpoint "
            f"(anchors, toxic links, competitor gap, or link-prospecting data).",
            "Medium",
            f"Extend the {vendor} adapter to the relevant endpoint; each is a "
            f"metered call, so add them deliberately rather than all at once.",
            0.0, f"{vendor}_not_implemented"))
    return out
