"""
The consent scan, in full.

WHY THIS EXISTS
---------------
Nine checkpoints are a summary of the consent scan. They are not the scan. The
scanner learns which CMP is installed and what evidence matched it, which GTM
containers are on the page, what Consent Mode defaults to, every tracker that
fired and exactly when relative to consent, which of the client's bought
products are actually present, and how each targeted state's law comes out —
and until this build every bit of that was computed and thrown away the moment
nine findings were derived from it.

That is most of what the standalone scanner puts on screen. This page is that
screen, reading the stored scan.

WHAT IT WILL NOT DO
-------------------
It will not say "compliant". The scanner's own README is right about this: a
scan sees one browser, one location, one moment. It reports what fired and what
the law asks for, and a human decides. Every heading here is a description of
evidence, not a verdict on liability.

An absent field renders as absent. A scan that ran in basic mode says so at the
top and the browser-only sections say why they are empty, because a blank
"Pre-consent tags" table and a clean one look identical and mean opposite
things.
"""
from __future__ import annotations

from .ui import _shell, e, _fmt_when

# Severity words the scanner uses on a pre-consent row, worst first. Used for
# ordering and for the chip colour; anything unrecognised sorts last and reads
# as informational, because inventing a severity for a word we do not know is
# how a scanner starts overstating its case.
_SEV = {"critical": 0, "high": 1, "ungated": 1, "medium": 2, "warning": 2,
        "low": 3, "info": 4, "informational": 4}


def _gpc_states(states) -> list:
    """Which of these states require Global Privacy Control to be honoured."""
    try:
        from engine.consent.state_checks import STATE_CHECKS
    except Exception:  # noqa: BLE001
        return []
    return [str(s).upper() for s in states
            if (STATE_CHECKS.get(str(s).upper()) or {}).get("gpc")]


def _chip(text, kind="neutral"):
    cls = {"bad": "amark--no", "hold": "amark--hold",
           "ok": "amark--ok"}.get(kind, "")
    return f"<span class='amark {cls}'>{e(text)}</span>"


def _sev_kind(sev):
    s = str(sev or "").lower()
    if s in ("critical", "high", "ungated"):
        return "bad"
    if s in ("medium", "warning", "low"):
        return "hold"
    return "neutral"


def _sec(title, body, note=""):
    """One section. Empty body means the section is not rendered at all."""
    if not body:
        return ""
    return (f"<h2 style='margin-top:34px'>{e(title)}</h2>"
            + (f"<div class='sm' style='color:var(--ink2);margin-bottom:6px'>"
               f"{note}</div>" if note else "")
            + body)


def _rows(headers, rows):
    if not rows:
        return ""
    head = "".join(f"<th>{e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
                   for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _trackers(items, page_col=False):
    """A tracker table. `when` is the whole point — a vendor name alone says
    nothing about whether it is a problem."""
    out = []
    for t in sorted(items, key=lambda x: (_SEV.get(
            str(x.get("severity") or "").lower(), 9),
            str(x.get("vendor") or ""))):
        row = [e(t.get("vendor") or "?"),
               _chip(t.get("severity") or "recorded",
                     _sev_kind(t.get("severity"))),
               f"<code style='font-size:11.5px;word-break:break-all'>"
               f"{e((t.get('url') or '')[:160])}</code>"]
        if t.get("note"):
            row[2] += (f"<div class='sm' style='color:var(--muted)'>"
                       f"{e(t['note'])}</div>")
        if page_col:
            row.insert(0, e(t.get("_page") or "—"))
        out.append(row)
    heads = ["Vendor", "Severity", "Request"]
    if page_col:
        heads.insert(0, "Page")
    return _rows(heads, out)


def _tag(items, page):
    """Stamp each tracker with the page it was seen on, for the merged table."""
    for it in items or []:
        d = dict(it)
        d["_page"] = page
        yield d


def consent_html(audit: dict, detail: dict | None) -> str:
    """Render the consent detail page for one audit."""
    aid = audit.get("id") or ""
    client = audit.get("client_name") or "—"
    url = audit.get("target_url") or ""
    crumbs = [("Audits", "/"), (client, f"/audits/{aid}"),
              ("Consent scan", None)]

    if not detail or not (detail.get("scan") or {}):
        body = (
            "<div class='card'><b>No consent detail was stored for this run."
            "</b><div class='sm' style='color:var(--ink2);margin-top:8px'>"
            "Either the consent scan was not ticked, or this audit predates "
            "the build that started keeping the full scan. Re-run with "
            "<b>Consent &amp; privacy</b> ticked and the detail will be here."
            "</div></div>")
        return _shell(f"Consent — {client}", body, heading="Consent scan",
                      crumbs=crumbs)

    scan = detail.get("scan") or {}
    pages = detail.get("pages") or []
    want = detail.get("requested") or {}
    mode = scan.get("mode") or "unknown"
    basic = mode != "full"

    # ---------------------------------------------------------------- header
    verdict = str(scan.get("verdict") or "").replace("_", " ") or "not recorded"
    vkind = "bad" if scan.get("verdict") in ("no_cmp", "bad") else "hold"
    head = [
        f"<div class='card'>"
        f"<div style='display:flex;gap:14px;align-items:baseline;"
        f"flex-wrap:wrap'>"
        f"<b style='font-size:18px'>{e(client)}</b>"
        f"<span class='sm' style='color:var(--ink2)'>{e(url)}</span>"
        f"{_chip(verdict, vkind)}"
        f"{_chip('browser' if not basic else 'basic — no browser', 'ok' if not basic else 'hold')}"
        f"</div>"]
    if scan.get("verdict_detail"):
        head.append(f"<div class='sm' style='color:var(--ink2);margin-top:10px;"
                    f"line-height:1.6'>{e(scan['verdict_detail'])}</div>")
    if basic:
        # A BASIC SCAN CANNOT PASS WHAT IT NEVER SAW, and the empty tables
        # below look exactly like clean ones.
        head.append(
            "<div class='sm' style='color:#8a5d05;background:#fdf6ec;"
            "border-left:3px solid var(--gold);border-radius:10px;"
            "padding:9px 12px;margin-top:12px'>"
            "This ran without a browser, so nothing below about banners, "
            "Consent Mode or what fired before consent was tested. The empty "
            "tables mean untested, not clean.</div>")
    scanned = scan.get("scanned_at")
    head.append(f"<div class='sm' style='color:var(--muted);margin-top:10px'>"
                f"Scanned {e(scanned) if scanned else _fmt_when(audit.get('completed_at'))}"
                f" &middot; {len(pages) or 1} "
                f"{'page' if (len(pages) or 1) == 1 else 'pages'}</div></div>")

    parts = ["".join(head)]

    # ------------------------------------------------------- CMP + container
    cmp_rows = []
    for c in (scan.get("cmps") or []):
        ev = c.get("evidence") or []
        cmp_rows.append([
            f"<b>{e(c.get('name') or '?')}</b>"
            + (f"<div class='sm' style='color:var(--muted)'>{e(c['notes'])}</div>"
               if c.get("notes") else ""),
            e(c.get("gtm_event") or "—"),
            "".join(f"<div><code style='font-size:11.5px;word-break:break-all'>"
                    f"{e(str(x)[:150])}</code></div>" for x in ev[:6])
            + (f"<div class='sm' style='color:var(--muted)'>"
               f"and {len(ev) - 6} more</div>" if len(ev) > 6 else "")])
    if cmp_rows:
        parts.append(_sec(
            "Consent platform", _rows(["CMP", "GTM event", "Matched on"],
                                      cmp_rows),
            "What the scanner matched, and the evidence it matched on — so a "
            "wrong identification is checkable rather than taken on trust."))
    else:
        parts.append(_sec(
            "Consent platform",
            "<div class='card'><b>No recognised consent platform.</b>"
            "<div class='sm' style='color:var(--ink2);margin-top:6px'>"
            "Either there is none, or the banner is custom-built and carries "
            "no signature the scanner knows. Worth thirty seconds in a "
            "browser before it goes in a deck.</div></div>"))

    gtm = scan.get("gtm") or {}
    cm = scan.get("consent_mode_default")
    defaults = scan.get("consent_defaults") or {}
    cfg_rows = []
    if gtm:
        ids = gtm.get("container_ids") or []
        cfg_rows.append([
            "Google Tag Manager",
            _chip("found", "ok") if gtm.get("found") else _chip("not found", "hold"),
            ", ".join(f"<code>{e(i)}</code>" for i in ids) or "—"])
    cfg_rows.append([
        "Consent Mode default",
        _chip("set", "ok") if cm is True else
        (_chip("not set", "bad") if cm is False else _chip("unknown", "hold")),
        ", ".join(f"<code>{e(k)}={e(v)}</code>"
                  for k, v in sorted(defaults.items())) or "—"])
    cfg_rows.append([
        "Banner appears on load",
        _chip("yes", "ok") if scan.get("banner_visible") is True else
        (_chip("no", "bad") if scan.get("banner_visible") is False
         else _chip("not tested", "hold")),
        "—"])
    for label, key in (("Accept clicked", "accept_clicked"),
                       ("Reject tested", "reject_tested"),
                       ("GPC signal tested", "gpc_tested")):
        cfg_rows.append([label,
                         _chip("yes", "ok") if scan.get(key)
                         else _chip("no", "hold"), "—"])
    parts.append(_sec("Container and configuration",
                      _rows(["", "State", "Detail"], cfg_rows)))

    # ----------------------------------------------------------- the trackers
    pre = list(scan.get("pre_consent") or [])
    if pages:
        # Per page, because "which page was this on" is the first question
        # anyone asks about an ungated pixel, and the merged list cannot say.
        tagged = []
        for pg in pages:
            sc = pg.get("scan") or {}
            tagged += list(_tag(sc.get("pre_consent") or [], pg.get("url")))
        if tagged:
            pre = tagged
    # AN EMPTY TABLE AND A CLEAN ONE LOOK IDENTICAL.
    #
    # "No trackers listed under Fired after Reject" reads as a pass. It is a
    # pass only if Reject was actually clicked; if there was no banner to
    # click, the same empty table means nothing was tested. Each of these
    # three sections says which of the two it is, always.
    def fired(title, items, tested, note, untested):
        body = _trackers(items, page_col=(bool(pages) and title.endswith(
            "before consent")))
        if not body:
            body = (f"<div class='card'>{untested}</div>" if not tested
                    else "<div class='card'>Nothing fired.</div>")
        return _sec(title, body, note)

    parts.append(fired(
        "Fired before consent", pre, not basic,
        "Requests the page made before anyone agreed to anything. The "
        "scanner separates a real ungated fire from an expected cookieless "
        "ping carrying a denied consent signal — the severity column is its "
        "classification, not a row count.",
        "Not tested: this scan ran without a browser, so nothing was watched "
        "as the page loaded."))

    reject_why = ("Not tested: this scan ran without a browser."
                  if basic else
                  "Not tested: no Reject control was found to click — there "
                  "is no consent banner on this site."
                  if not (scan.get("cmps") or []) else
                  "Not tested: a consent platform was found but the scan "
                  "could not locate a Reject control on its banner.")
    parts.append(fired(
        "Fired after Reject", scan.get("post_reject") or [],
        scan.get("reject_tested"),
        "A reject button that changes nothing is worse than none: it "
        "documents the intent to honour a choice that was not honoured.",
        reject_why))

    gpc_states = _gpc_states(want.get("states") or scan.get("states") or [])
    gpc_why = ("Not tested: this scan ran without a browser." if basic else
               f"Not applicable: none of the states this client sells in "
               f"({e(', '.join(want.get('states') or scan.get('states') or [])) or 'none recorded'}) "
               f"require Global Privacy Control to be honoured."
               if not gpc_states else
               f"Not tested, although {e(', '.join(gpc_states))} "
               f"{'requires' if len(gpc_states) == 1 else 'require'} it. "
               f"That is ours to fix, not the client's.")
    parts.append(fired(
        "Fired despite Global Privacy Control", scan.get("gpc_fires") or [],
        scan.get("gpc_tested"),
        "Twelve states require GPC to be honoured as an opt-out.", gpc_why))

    after = scan.get("post_consent") or []
    if after:
        parts.append(_sec(
            "Fired only after consent", _rows(
                ["Vendor"], [[e(x.get("vendor") if isinstance(x, dict) else x)]
                             for x in after]),
            "These waited, which is the behaviour being asked for."))

    # ------------------------------------------------------------- products
    prods = scan.get("products") or []
    if prods or want.get("products"):
        rows = []
        for p in prods:
            pix = p.get("pixels") or []
            fired = p.get("fired")
            rows.append([
                f"<b>{e(p.get('product') or '?')}</b>",
                _chip("bought", "ok") if p.get("expected") else _chip("not bought"),
                _chip("firing", "ok") if fired else _chip("not seen", "bad"),
                "".join(f"<div class='sm'>{e(str(x)[:120])}</div>"
                        for x in pix[:4]) or "—"])
        if not rows:
            for name in want.get("products") or []:
                rows.append([f"<b>{e(name)}</b>", _chip("bought", "ok"),
                             _chip("not seen", "bad"), "—"])
        parts.append(_sec(
            "Products bought against what fires", _rows(
                ["Product", "On the account", "On the site", "Evidence"], rows),
            "A pixel the client pays for and that never fires is money going "
            "nowhere, and it is invisible to a scan that only reports what it "
            "found."))

    # ---------------------------------------------------------- state checks
    st = scan.get("state_checks") or []
    if st:
        rows = []
        for c in sorted(st, key=lambda x: (str(x.get("state") or ""),
                                           str(x.get("check") or ""))):
            ok = str(c.get("status") or "").lower() in ("pass", "ok", "met")
            rows.append([e(c.get("state") or "—"),
                         e(c.get("check") or "—"),
                         _chip(c.get("status") or "?", "ok" if ok else "bad"),
                         e(c.get("detail") or "")])
        parts.append(_sec(
            "State law checks", _rows(["State", "Requirement", "Result",
                                       "Detail"], rows),
            f"Derived from the markets on this audit"
            + (f": {e(', '.join(want.get('states') or []))}."
               if want.get("states") else ".")))
    elif want.get("states"):
        parts.append(_sec(
            "State law checks",
            f"<div class='card'>No per-state results were recorded for "
            f"{e(', '.join(want['states']))}.</div>"))

    # ------------------------------------------------------------ every page
    if len(pages) > 1:
        rows = []
        for pg in pages:
            sc = pg.get("scan") or {}
            if pg.get("error"):
                rows.append([e(pg.get("url")), e(pg.get("role") or ""),
                             _chip("scan failed", "bad"), e(pg["error"])])
                continue
            rows.append([
                e(pg.get("url")), e(pg.get("role") or ""),
                _chip(sc.get("mode") or "?",
                      "ok" if sc.get("mode") == "full" else "hold"),
                f"{len(sc.get('pre_consent') or [])} before consent &middot; "
                f"{len(sc.get('post_reject') or [])} after reject"])
        parts.append(_sec("Pages scanned",
                          _rows(["URL", "Role", "Mode", "Trackers"], rows)))

    # ------------------------------------------------------------ opt-out
    if scan.get("optout_link"):
        parts.append(_sec(
            "Opt-out link",
            f"<div class='card'>Matched: <b>{e(scan['optout_link'])}</b></div>"))

    parts.append(
        f"<div style='margin-top:34px'><a class='btn ghost' "
        f"href='/audits/{e(aid)}'>Back to the audit</a></div>")

    return _shell(f"Consent — {client}", "".join(parts),
                  heading="Consent scan", crumbs=crumbs)
