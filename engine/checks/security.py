"""Section 04 — HTTPS & Security (SEC-*). TLS probe + header inspection."""
from __future__ import annotations
import re
from datetime import datetime, timezone
from . import check, finding

OK = lambda a: [p for p in a.pages.values() if not p.error and 200 <= p.status_code < 300]


def _https_origin(a) -> bool:
    """Is this origin served over HTTPS at all?"""
    return a.scheme == "https"


def _cascade(a, dependent_label):
    """
    Dependency cascade. If the origin is plain HTTP there is no certificate to
    inspect, so the TLS detail rows are Not Applicable — reporting six separate
    'could not retrieve certificate' failures would triple-count a single root
    cause and bury the one finding that matters (SEC-01).
    """
    if _https_origin(a):
        return None
    return finding("N/A", {"reason": "origin is not HTTPS"},
                   f"{dependent_label} not applicable — the site is not served over "
                   f"HTTPS. See SEC-01, which captures this as the root issue.",
                   [], "Low", confidence=1.0)


@check("SEC-01")
def sec01(a, c):
    ok = a.start_url.startswith("https://") and a.http_to_https.get("upgraded", False)
    return finding("Pass" if ok else "Fail", {"https": ok},
                   "Homepage is served over HTTPS and HTTP upgrades correctly." if ok
                   else "Homepage does not enforce HTTPS.", [],
                   "Low" if ok else "Critical")


@check("SEC-02")
@check("SEC-11")
def sec02(a, c):
    _c = _cascade(a, "TLS version check")
    if _c: return _c
    v = (a.tls or {}).get("version")
    good = v in ("TLSv1.3", "TLSv1.2")
    return finding("Pass" if good else "Fail", {"tls_version": v},
                   f"Connection negotiated {v}." if good
                   else f"Weak or unknown TLS version negotiated: {v}.", [],
                   "Low" if good else "High",
                   "" if good else "Disable TLS 1.0/1.1 and require TLS 1.2+.")


@check("SEC-03")
def sec03(a, c):
    _c = _cascade(a, "Certificate name check")
    if _c: return _c
    t = a.tls or {}
    san, host = t.get("san") or [], a.host.lower()
    match = any(host == s.lower() or (s.startswith("*.") and host.endswith(s[1:].lower()))
                for s in san)
    return finding("Pass" if match else "Fail",
                   {"subject": t.get("subject"), "san_count": len(san)},
                   f"Certificate covers {a.host} (SAN entries: {len(san)})." if match
                   else f"Certificate does not appear to cover {a.host}.", [],
                   "Low" if match else "Critical")


@check("SEC-04")
@check("SEC-09")
def sec04(a, c):
    _c = _cascade(a, "Certificate expiry check")
    if _c: return _c
    na = (a.tls or {}).get("not_after")
    if not na:
        return finding("Fail", {"error": (a.tls or {}).get("error")},
                       "Could not retrieve TLS certificate.", [], "High")
    try:
        exp = datetime.strptime(na, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        days = (exp - datetime.now(timezone.utc)).days
    except Exception:
        return finding("Warning", {"not_after": na}, f"Certificate expiry: {na}.", [], "Low")
    ok = days > 21
    return finding("Pass" if ok else "Fail", {"days_remaining": days, "not_after": na},
                   f"TLS certificate valid, expires in {days} days ({na})." if ok
                   else f"TLS certificate expires in {days} days — renewal required.", [],
                   "Low" if ok else ("Critical" if days < 7 else "High"))


@check("SEC-05")
@check("SEC-12")
def sec05(a, c):
    _c = _cascade(a, "Mixed-content check")
    if _c: return _c
    bad = []
    for p in OK(a):
        if not p.final_url.startswith("https://"):
            continue
        for s in p.scripts:
            if s.startswith("http://"):
                bad.append(p.url)
                break
        else:
            if any(i["src"].startswith("http://") for i in p.images):
                bad.append(p.url)
    bad = sorted(set(bad))
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} HTTPS pages load insecure HTTP subresources (mixed content)."
                   if bad else "No mixed content detected on HTTPS pages.", bad[:30],
                   "High" if bad else "Low",
                   "Serve all subresources over HTTPS." if bad else "")


@check("SEC-10")
def sec10(a, c):
    _c = _cascade(a, "HSTS check")
    if _c: return _c
    hdrs = {}
    for p in OK(a):
        hdrs.update(p.headers or {})
        break
    hsts = hdrs.get("strict-transport-security")
    return finding("Pass" if hsts else "Fail", {"hsts": hsts},
                   f"HSTS enabled: {hsts}" if hsts else "Strict-Transport-Security header absent.",
                   [], "Low" if hsts else "Medium",
                   "" if hsts else "Add Strict-Transport-Security with a max-age of at least 31536000.")


@check("SEC-08")
def sec08(a, c):
    http = [p.url for p in OK(a) if p.final_url.startswith("http://")]
    return finding("Fail" if http else "Pass", {"http_pages": len(http)},
                   f"{len(http)} pages are not served over HTTPS." if http
                   else f"All {len(OK(a))} crawled pages served over HTTPS.", http[:20],
                   "Critical" if http else "Low")


@check("SEC-14")
def sec14(a, c):
    bad = sorted({l["href"] for p in OK(a) for l in p.links_internal
                  if l["href"].startswith("http://")})
    return finding("Fail" if bad else "Pass", {"count": len(bad)},
                   f"{len(bad)} links on HTTPS pages point to HTTP URLs." if bad
                   else "No HTTPS→HTTP internal links found.", list(bad)[:30],
                   "Medium" if bad else "Low")
