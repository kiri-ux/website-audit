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
from engine.report import extension_link as _ext_link

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


# ---------------------------------------------------------------- hover help
#
# THE DEFINITIONS WERE THE PROBLEM, NOT THE ABSENCE OF THEM.
#
# Every term here needed explaining and none of them needed explaining twice.
# Written out as prose under each heading they turned a page of evidence into
# a page of glossary, and the evidence — which is the only reason anyone opens
# this — stopped being findable. Same answer the audit form arrived at: put
# them on an `i`, there when somebody wants one and gone when they don't.
#
# Short on purpose. A tooltip somebody has to read twice is a paragraph in a
# small box.
_DEFS = {
    "cmp": "Consent Management Platform — the software behind the cookie "
           "banner. OneTrust, Cookiebot, Osano and the rest. It is what "
           "records a visitor's choice and tells the tags about it.",
    "gtm": "Google Tag Manager. One container script on the page that loads "
           "every other tag, so gating the container is how you gate them "
           "all at once.",
    "gtm_event": "The dataLayer event the CMP fires once a visitor chooses. "
                 "It is the trigger you hang the tags off, so it is the one "
                 "detail you need before you can gate anything.",
    "consent_mode": "Google's Consent Mode. The site declares a default "
                    "state — usually denied — before any tag loads, and "
                    "updates it when the visitor chooses. Without a default, "
                    "Google tags run as if consent was given.",
    "gpc": "Global Privacy Control. A browser signal that says 'treat me as "
           "opted out'. Twelve states require a site to honour it, and no "
           "banner click is involved — the browser sends it on every "
           "request.",
    "pre_consent": "Requests the page made before anyone agreed to anything. "
                   "This is the section that decides whether the banner is "
                   "doing its job or decorating a page that tracks anyway.",
    "denied_ping": "A Google request carrying gcs= in a denied state. It is "
                   "cookieless and carries no identifier, so it is correct "
                   "behaviour, not a violation — which is why it is marked "
                   "informational rather than counted as a fire.",
    "ungated": "Fired with no consent mechanism on the page at all. The "
               "finding is the missing banner, not this one tag.",
    "reject": "Whether the scan found a Reject control, clicked it on a "
              "fresh load, and watched what happened next. A fresh load "
              "matters: after an Accept the CMP has written a cookie, and a "
              "Reject click then tests a different state from the one a "
              "first-time visitor sees.",
    "optout": "A 'Do Not Sell or Share My Personal Information' style link. "
              "Several states expect one, and it is a text match on the "
              "rendered page — presence only, not whether it works.",
    "state": "Derived from the geographic targeting on this audit. Only the "
             "states this client actually sells in are checked, because a "
             "statute they are not subject to is not a finding.",
    "product": "A product on the client's account, and whether its pixel "
               "was seen firing. A pixel they pay for that never fires is "
               "money going nowhere, and it is invisible to a scan that only "
               "reports what it found.",
    "configured": "No request was observed, but the vendor's fingerprint is "
                  "in the page source or in the published GTM container. "
                  "That is a firing problem, not a missing install.",
    "mode": "Full means a real browser loaded the page, watched the network "
            "and clicked the banner. Basic means raw HTML only — the "
            "banner, Consent Mode and pre-consent behaviour were never "
            "tested, so their sections are empty for want of a browser, not "
            "for want of a problem.",
    "verdict": "The scanner's one-line read on what to do next. It is a "
               "description of evidence, never a statement about liability.",
}


def _t(key, label=""):
    """A term with its definition on an `i`, using the shell's .tip style."""
    d = _DEFS.get(key)
    if not d:
        return e(label)
    return (f"{e(label)}<i class='tip' tabindex='0' "
            f"data-tip=\"{e(d)}\">i</i>" if label
            else f"<i class='tip' tabindex='0' data-tip=\"{e(d)}\">i</i>")


def _copy(text, label="copy"):
    """A copy-to-clipboard button, same shape the audit page uses."""
    return (f"<button class='del' type='button' onclick=\"navigator.clipboard"
            f".writeText('{e(text)}');this.textContent='copied'\">"
            f"{e(label)}</button>")


def _sev_kind(sev):
    s = str(sev or "").lower()
    if s in ("critical", "high", "ungated"):
        return "bad"
    if s in ("medium", "warning", "low"):
        return "hold"
    return "neutral"


def _sec(title, body, note="", tip=None):
    """
    One section. Empty body means the section is not rendered at all.

    The note is ONE LINE now. Each of these was a short paragraph explaining
    both what the table is and why it matters, and stacked down the page they
    read as a wall of grey the eye learned to skip — including the two lines
    that actually changed how you read the table under them. The "what it is"
    half moved onto the heading's `i`; the line that survives is the half that
    tells you how to read the rows.
    """
    if not body:
        return ""
    # THE HEADING AND ITS LINE ARE ONE THING.
    #
    # A 34px gap above the heading, 10px below it, then another 8px below the
    # note put three separate gaps between the reader and the table — down a
    # page of nine sections that is most of the scrolling. They are one block
    # now, with the air on the OUTSIDE of it where it does the job headings
    # need air to do.
    return (f"<div class='csec'><h2>{e(title)}"
            + (_t(tip) if tip else "") + "</h2>"
            + (f"<div class='csec-note'>{note}</div>" if note else "")
            + "</div>" + body)


def _rows(headers, rows, widths=None):
    """
    A table.

    HEADERS ARE MARKUP, NOT TEXT. They were escaped, which was right when they
    were words and wrong the moment one of them carried a definition marker —
    the first header with a tooltip on it printed its own HTML across the top
    of the table. Callers pass strings they have already escaped.

    `widths` pins the column proportions. Without it the browser gives a column
    of URLs whatever the longest one asks for and squeezes the names that
    matter into two characters.
    """
    if not rows:
        return ""
    cols = ("<colgroup>"
            + "".join(f"<col style='width:{w}'>" for w in widths)
            + "</colgroup>") if widths else ""
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
                   for r in rows)
    return (f"<div style='overflow-x:auto'><table style='table-layout:fixed'>"
            f"{cols}<thead><tr>{head}</tr></thead><tbody>{body}</tbody>"
            f"</table></div>")


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
    widths = ["22%", "14%", "64%"]
    if page_col:
        heads.insert(0, "Page")
        widths = ["24%", "18%", "12%", "46%"]
    return _rows(heads, out, widths)


def _tag(items, page):
    """Stamp each tracker with the page it was seen on, for the merged table."""
    for it in items or []:
        d = dict(it)
        d["_page"] = page
        yield d


# A TOOLTIP INSIDE A CLIPPED BOX IS HALF A TOOLTIP.
#
# `.stat` carries overflow:hidden so its accent bar cannot poke out of the
# rounded corner, which also clipped every definition bubble on a tile at the
# tile's own edge — the hover worked and showed four words of it. Rounding the
# bar directly means the clip is not needed here.
_PAGE_CSS = ("<style>"
             # ---- density -------------------------------------------------
             #
             # THE OG QUOTE TOOL WAS SHARPER, AND THIS IS WHY.
             #
             # Every surface here was inheriting the dashboard's spacing, and
             # the dashboard is six cards on a screen where air IS the design.
             # This page is nine tables of evidence: 22px card padding, 15px
             # table cells and three stacked gaps per heading turned a dense
             # document into two and a half screens of mostly nothing, and
             # scrolling past white space is how you lose the row that
             # mattered. Tighter throughout, and only on this page.
             ".wrap{padding-top:12px}"
             ".card{padding:13px 16px}"
             "table{margin-top:0;font-size:13.5px}"
             "th{padding:9px 12px;font-size:12.5px}"
             "td{padding:9px 12px}"
             ".csec{margin:20px 0 7px}"
             ".csec h2{margin:0;font-size:12px}"
             ".csec-note{font-size:12.5px;color:var(--ink2);margin-top:3px;"
             "line-height:1.5}"
             ".stats{gap:10px;margin-top:10px}"
             ".stat{padding:11px 13px}"
             ".stat .n{font-size:22px}"
             # ---- the definition marker -----------------------------------
             #
             # It sat a full 6px off the word, at the same size as the body
             # text it followed, on a line of 12px uppercase — so it read as a
             # stray character rather than a control. Smaller, closer, and
             # lifted to the cap height of the text it belongs to.
             ".tip{width:13px;height:13px;font-size:9px;margin-left:4px;"
             "vertical-align:2px}"
             ".csec h2 .tip{text-transform:none;letter-spacing:0;"
             "vertical-align:1px}"
             "th .tip{border-color:rgba(255,255,255,.4);color:#fff;"
             "background:transparent}"
             "th .tip:hover{border-color:#fff;color:#fff}"
             # A TOOLTIP INSIDE A CLIPPED BOX IS HALF A TOOLTIP.
             #
             # `.stat` carries overflow:hidden so its accent bar cannot poke
             # out of the rounded corner, which also clipped every definition
             # bubble at the tile's own edge. Rounding the bar directly means
             # the clip is not needed — and the hovered tile has to paint
             # above the one beside it, or the next tile draws over the
             # bubble that just escaped.
             ".stat{overflow:visible}"
             ".stat::before{border-radius:10px 0 0 10px}"
             ".stat:hover{z-index:5}"
             ".stat .k{display:flex;align-items:center;gap:4px}"
             # ---- the steps row -------------------------------------------
             #
             # "Accept clicked: no" as a washed amber pill, three times, said
             # something true in the visual language of a warning — and two of
             # the three were not warnings, they were the correct result on a
             # site with no banner to click. Pills are for states that differ
             # from each other; these differ only by yes and no, so they get a
             # tick or a cross and no fill at all.
             ".vstep{display:inline-flex;align-items:center;gap:6px;"
             "font-size:12.5px;color:var(--ink2);margin-right:18px;"
             "white-space:nowrap}"
             ".vstep i{width:15px;height:15px;border-radius:50%;flex:none;"
             "display:inline-flex;align-items:center;justify-content:center;"
             "font-style:normal;font-size:9px;font-weight:700;color:#fff}"
             ".vstep--y i{background:var(--good)}"
             ".vstep--n i{background:#b9c4d2}"
             # ---- the standalone scanner's product cards ------------------
             #
             # Lifted from the original Site Scanner, badges and all: a
             # bordered card per product, a dashed rule under its header, and
             # every pixel a flex row whose STATUS COMES FIRST. The badge next
             # to the name is the whole trick — in the table version the
             # status sat in column three and the name in column one, so
             # joining them cost a trip across the page.
             ".vprodc{border:1px solid var(--line);border-radius:8px;"
             "background:#fff;margin:0 0 9px}"
             ".vprodh{display:flex;align-items:center;gap:9px;padding:8px 12px;"
             "border-bottom:1px dashed var(--line);font-size:14px}"
             ".vprodc ul{list-style:none;margin:0;padding:2px 12px 6px}"
             ".vprodc li{font-size:13.5px;padding:7px 0;display:flex;gap:10px;"
             "align-items:baseline;border-bottom:1px dashed var(--line)}"
             ".vprodc li:last-child{border-bottom:none}"
             ".vprodc li > div{min-width:0}"
             # BADGES, NOT PILLS. Condensed, uppercase, squared-off — the same
             # object the original used, so a screen from one tool and a
             # screen from the other read as the same product.
             ".vb{font-weight:700;font-size:11px;letter-spacing:.06em;"
             "text-transform:uppercase;border-radius:5px;padding:3px 8px;"
             "white-space:nowrap;flex:none}"
             ".vb--ok{background:#E7F4ED;color:#1F7A4D}"
             ".vb--warn{background:#FBF1D9;color:#9A6A00}"
             ".vb--bad{background:#F9E7E5;color:#B3261E}"
             ".vb--neutral{background:#E8F1F8;color:#0066B3}"
             ".vcount{background:#E8F1F8;color:#0066B3;border-radius:4px;"
             "font-size:12px;font-weight:700;padding:2px 8px}"
             ".vev{font-size:12.5px;color:var(--muted)}"
             ".vsrc{font-size:10.5px;font-weight:700;letter-spacing:.06em;"
             "border:1.5px solid var(--blue);color:var(--blue);"
             "border-radius:4px;padding:1px 6px;white-space:nowrap}"
             ".vurl{color:var(--muted);font:11.5px ui-monospace,"
             "SFMono-Regular,Menlo,monospace;word-break:break-all;"
             "margin-top:3px}"
             # A PRODUCT ROW IS A GROUP HEADER, NOT A ROW WITH EMPTY CELLS.
             #
             # It carried a name and a count and left State and Evidence
             # blank, so two thirds of every product row was white — and with
             # four products that is a lot of the section. Tinting it says
             # "heading", and the emptiness stops reading as missing data.
             "tr:has(.vprod) td{background:#f4f7fb;font-size:13px}"
             "tr:has(.vprod):hover td{background:#eef3f9}"
             "</style>")


def _steps(pairs):
    """A tick or a cross per step, on one line, with no pill anywhere."""
    out = []
    for label, ok in pairs:
        out.append(f"<span class='vstep vstep--{'y' if ok else 'n'}'>"
                   f"<i>{'&#10003;' if ok else '&#10005;'}</i>{e(label)}</span>")
    return "".join(out)


def _listy(items):
    """a, b and c — for a sentence, not a bullet list."""
    xs = [x for x in items if x]
    if not xs:
        return ""
    if len(xs) == 1:
        return xs[0]
    return ", ".join(xs[:-1]) + " and " + xs[-1]


def _tile(value, label, tip="", edge=None):
    """A `.stat` tile that can carry markup and a hover definition."""
    style = f" style='--edge:{edge}'" if edge else ""
    dot = f"<b style='background:{edge}'></b>" if edge else ""
    return (f"<div class='stat'{style}><div class='n'>{value}</div>"
            f"<div class='k'>{dot}{label}{tip}</div></div>")


def _conv_urls(audit):
    """The conversion URLs off the audit's stored options."""
    import json
    try:
        return (json.loads(audit.get("options") or "{}")
                or {}).get("conversion_urls") or []
    except Exception:  # noqa: BLE001
        return []


def _capture_panel(aid, url, why, heading="This scan ran without a browser",
                   extra_urls=()):
    """
    The handoff to the extension, on the page where it is needed.

    WHY IT BELONGS HERE.

    A basic scan is what happens when bot protection turns Playwright away, and
    the honest label for the four sections it costs us is "not tested". That
    label was the end of the page: correct, complete, and no way forward. The
    extension has been able to answer all four for builds — from the operator's
    own Chrome, on their own IP, which challenge pages let through because it
    is a person — and nothing on the page that explains what is missing said so.
    A graceful degradation needs something loud somewhere else, or it is just a
    silent failure with good manners.

    ONE BUTTON, NO COPYING. The content script finds #vici-consent, reads the
    id and the target off it and wires the button straight to the worker, the
    same way the blocked-crawl panel works. The manual instructions stay for
    the browser that does not have the extension, because a hidden button and
    a missing extension look identical from here.
    """
    return (
        f"<div class='card' id='vici-consent' data-audit-id='{e(aid)}' "
        f"data-target='{e(url)}' "
        # THE CONVERSION URLS TRAVEL WITH THE BUTTON.
        #
        # They are on the audit and the extension has no business knowing
        # which pages a client counts as conversions — but it has to scan
        # them, because that is where conversion pixels fire. A capture that
        # did the homepage alone came back reporting every bought product as
        # never firing.
        f"data-urls='{e(' '.join(extra_urls or []))}' "
        f"style='border-left:3px solid var(--gold);margin-top:16px'>"
        f"<b style='font-size:14.5px'>{e(heading)}</b>"
        f"<p class='sm' style='color:var(--ink2);margin:5px 0 0;"
        f"line-height:1.6'>{why} Site Scanner runs the same scan from your own "
        f"Chrome — your IP, your profile, which is what challenge pages let "
        f"through. It records; the server classifies it with the same tables."
        f"</p>"
        f"<p style='margin:10px 0 0'><button id='vici-consent-go' "
        f"class='btn' type='button'>Run the consent capture in this "
        f"browser</button></p>"
        f"<div id='vici-consent-manual'>"
        # NOT INSTALLED AND NOT UP TO DATE LOOK IDENTICAL FROM HERE, and the
        # second is far more common — it is the state everybody is in for the
        # ten minutes after we ship. Telling someone to download and unzip an
        # extension already sitting in their toolbar is the wrong instruction
        # in the more likely case, so the direct link goes FIRST: the id is
        # pinned in the manifest, so it opens whatever version is installed.
        f"<p class='sm' style='color:var(--ink2);margin:10px 0 0;"
        f"line-height:1.65'>"
        f"<b>The button needs the Site Scanner extension, and this browser is "
        f"not answering.</b> If it is installed, it is older than this build "
        f"&mdash; <a href='{e(_ext_link('consent', aid, url))}'><b>open it "
        f"directly</b></a> (the audit id travels with the link), then reload "
        f"it at <code>chrome://extensions</code> {_copy('chrome://extensions')} "
        f"to get the button back.</p>"
        f"<p class='sm' style='color:var(--ink2);margin:8px 0 0'>"
        f"Not installed at all? <a href='/extension.zip'>Download it</a>, "
        f"unzip it somewhere permanent, and load it unpacked with Developer "
        f"mode on. Audit id <code>{e(aid)}</code> {_copy(aid)}</p></div>"
        f"<p class='sm' style='color:var(--muted);margin:8px 0 0'>Four loads "
        f"— untouched, after Accept, after Reject, and with Global Privacy "
        f"Control on. About a minute, and this page reloads itself when it "
        f"finishes.</p>"
        f"</div>"
        f"<script>(function(){{"
        f"var el=document.getElementById('vici-consent');"
        f"var go=document.getElementById('vici-consent-go');"
        f"var man=document.getElementById('vici-consent-manual');"
        f"go.style.display='none';"
        f"setTimeout(function(){{"
        f"  if(el.dataset.extension==='present'){{"
        f"    go.style.display='inline-block';man.style.display='none';}}"
        f"}},400);}})();</script>")


def consent_html(audit: dict, detail: dict | None) -> str:
    """Render the consent detail page for one audit."""
    aid = audit.get("id") or ""
    client = audit.get("client_name") or "—"
    url = audit.get("target_url") or ""
    crumbs = [("Audits", "/"), (client, f"/audits/{aid}"),
              ("Consent scan", None)]

    if not detail or not (detail.get("scan") or {}):
        # AN EMPTY PAGE WITH A WAY FORWARD.
        #
        # "Re-run with Consent ticked" is the right advice exactly once: when
        # the phase was never asked for. On a site that turns the server away
        # it is advice to do the thing that already failed, and it was the only
        # thing here.
        body = (
            "<div class='card'><b>No consent detail was stored for this run."
            "</b><div class='sm' style='color:var(--ink2);margin-top:8px;"
            "line-height:1.65'>"
            "Either the consent scan was not ticked, or this audit predates "
            "the build that started keeping the full scan. Re-run with "
            "<b>Consent &amp; privacy</b> ticked and the detail will be here."
            "</div></div>"
            + _capture_panel(
                aid, url,
                "If the re-run comes back the same way, the site is turning "
                "the server's browser away rather than having nothing to "
                "report.",
                heading="Or capture it from your own browser",
                extra_urls=_conv_urls(audit)))
        return _shell(f"Consent — {client}", _PAGE_CSS + body,
                      heading="Consent scan", crumbs=crumbs)

    scan = detail.get("scan") or {}
    pages = detail.get("pages") or []
    want = detail.get("requested") or {}
    mode = scan.get("mode") or "unknown"
    basic = mode != "full"

    # ---------------------------------------------------------------- header
    verdict = str(scan.get("verdict") or "").replace("_", " ") or "not recorded"
    vkind = "bad" if scan.get("verdict") in ("no_cmp", "bad") else "hold"
    if scan.get("verdict") == "ok":
        vkind = "ok"
    src = scan.get("source") or ""
    scanned = scan.get("scanned_at")
    head = [
        f"<div class='card'>"
        f"<div style='display:flex;gap:9px;align-items:baseline;"
        f"flex-wrap:wrap'>"
        f"<b style='font-size:18px'>{e(client)}</b>"
        f"<span class='sm' style='color:var(--ink2)'>{e(url)}</span>"
        f"{_chip(verdict, vkind)}{_t('verdict')}"
        f"{_chip('browser' if not basic else 'basic — no browser', 'ok' if not basic else 'hold')}"
        + (_chip("your Chrome", "ok") if src == "extension" else "")
        + f"{_t('mode')}"
        f"</div>"]
    if scan.get("verdict_detail"):
        head.append(f"<div class='sm' style='color:var(--ink2);margin-top:7px;"
                    f"line-height:1.55'>{e(scan['verdict_detail'])}</div>")
    if basic:
        # A BASIC SCAN CANNOT PASS WHAT IT NEVER SAW, and the empty tables
        # below look exactly like clean ones.
        head.append(
            "<div class='sm' style='color:#8a5d05;background:#fdf6ec;"
            "border-left:3px solid var(--gold);border-radius:8px;"
            "padding:8px 11px;margin-top:9px;line-height:1.5'>"
            "This ran without a browser, so nothing below about banners, "
            "Consent Mode or what fired before consent was tested. The empty "
            "tables mean untested, not clean.</div>")
    head.append(f"<div class='sm' style='color:var(--muted);margin-top:7px;"
                f"font-size:12.5px'>"
                f"Scanned {e(scanned) if scanned else _fmt_when(audit.get('completed_at'))}"
                f" &middot; {len(pages) or 1} "
                f"{'page' if (len(pages) or 1) == 1 else 'pages'}"
                + (" &middot; captured in the operator's browser"
                   if src == "extension" else "")
                + f"</div></div>")

    # ------------------------------------------------------- the four answers
    #
    # THE PAGE OPENED WITH A WALL OF TABLES.
    #
    # Everything on it was evidence and none of it was a summary, so the first
    # thing anybody did was scroll looking for the four things the scan exists
    # to answer. They are the four things, so they go first — and each one says
    # UNTESTED where it was untested, because a tile reading "0" and a tile
    # reading "not tested" mean opposite things and looked the same.
    _cmps = scan.get("cmps") or []
    _no_cmp = not _cmps
    # THE TILE MUST COUNT THE ROWS THE TABLE PRINTS.
    #
    # This added the scan-level list to every page's list and got three where
    # the table below showed one, because the table shows one OR the other:
    # the per-page list when there is one, the merged list when there is not.
    # A headline number that disagrees with the rows under it is worse than no
    # headline number, so both now come from the same list, built once.
    _pre_all = list(scan.get("pre_consent") or [])
    _tagged = []
    for pg in pages:
        _tagged += list(_tag((pg.get("scan") or {}).get("pre_consent") or [],
                             pg.get("url")))
    if _tagged:
        _pre_all = _tagged
    _pre_real = [t for t in _pre_all
                 if str(t.get("severity") or "").lower() not in ("info",
                                                                 "informational")]
    _rej = scan.get("post_reject") or []
    _RED, _GREEN = "var(--critical)", "var(--good)"

    # An untested tile gets a GREY edge, never the default blue. The accent bar
    # is the only part of a tile you read from across the room, and blue is the
    # colour every other tile on this dashboard uses for "here is a number".
    _GREY = "var(--line-2)"

    def _untested():
        return "<span style='font-size:19px;color:var(--muted)'>not tested</span>"

    tiles = [
        _tile(e(", ".join(c.get("name") or "?" for c in _cmps)[:34])
              if _cmps else "<span style='color:var(--serious)'>none found</span>",
              "consent platform", _t("cmp"),
              _GREEN if _cmps else _RED),
        _tile("yes" if scan.get("banner_visible") is True else
              ("no" if scan.get("banner_visible") is False else _untested()),
              "banner on load",
              _t("cmp"),
              _GREEN if scan.get("banner_visible") is True else
              (_RED if scan.get("banner_visible") is False else _GREY)),
        _tile(_untested() if basic else e(len(_pre_real)),
              "fired before consent", _t("pre_consent"),
              _GREY if basic else (_RED if _pre_real else _GREEN)),
        # NO BANNER IS NOT "NOT TESTED".
        #
        # On a site with no CMP there is no Reject button, and there never
        # will be one — "not tested" reads as a gap somebody could go and
        # close, which is how the re-run panel ended up being offered on a
        # scan that had nothing left to find. Name the reason instead.
        _tile(e(len(_rej)) if scan.get("reject_tested")
              else ("<span style='font-size:19px;color:var(--muted)'>"
                    "no reject button</span>" if _no_cmp else _untested()),
              "fired after Reject", _t("reject"),
              (_RED if _rej else _GREEN) if scan.get("reject_tested")
              else _GREY),
    ]
    head.append("<div class='stats'>" + "".join(tiles) + "</div>")

    parts = [_PAGE_CSS, "".join(head)]

    # ONLY OFFER A RE-RUN THAT COULD CHANGE THE ANSWER.
    #
    # This shipped offering the capture whenever Reject was untested — and on
    # a site with NO consent banner at all, Reject can never be tested, by any
    # browser, ever. So a run that worked perfectly, from the operator's own
    # Chrome, still ended with a gold panel telling them to run it again, and
    # running it again produced the identical page. That is worse than a
    # missing button: it is a button that pretends there is more to get.
    #
    # "No Reject control on a site with no CMP" is a FINDING. It belongs in
    # the Reject section, which already says it, not in a panel headed "some
    # of this was never tested".
    _reject_gap = (not scan.get("reject_tested")) and not _no_cmp
    _gpc_gap = not scan.get("gpc_tested")
    if basic or _reject_gap or _gpc_gap:
        _gaps = []
        if basic:
            # No "and" inside a list item — _listy adds its own, and two in
            # one sentence made the list unreadable.
            _gaps.append("the banner, Consent Mode, everything that fired "
                         "before consent")
        if _reject_gap:
            _gaps.append("what fires after Reject")
        if _gpc_gap:
            _gaps.append("what fires despite Global Privacy Control")
        _why = ("Untested on this run: " + _listy(_gaps) + ". "
                + ("Bot protection turns the server's browser away on a lot "
                   "of sites, and it looks exactly like this."
                   if basic else
                   "A control the scan could not find is not the same as a "
                   "control that is not there."))
        parts.append(_capture_panel(
            aid, url, _why,
            heading=("This scan ran without a browser" if basic
                     else "Some of this was never tested"),
            extra_urls=want.get("conversion_urls") or []))

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
            "Consent platform", _rows([f"CMP{_t('cmp')}",
                                       f"GTM event{_t('gtm_event')}",
                                       "Matched on"], cmp_rows,
                                      ["26%", "26%", "48%"]),
            "The evidence column is what it matched on, so a wrong "
            "identification is checkable rather than taken on trust.",
            tip="cmp"))
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

    # WHAT THE SCAN GOT TO TRY IS NOT A PROPERTY OF THE SITE.
    #
    # Accept, Reject and GPC were three more rows in this table, each with an
    # em-dash in the Detail column, which made them read as three more findings
    # about the client. They are findings about the RUN — and they are the
    # three things that decide whether the empty tables further down mean
    # "clean" or "never looked". A chip row says that in one line instead of
    # three rows of nothing.
    steps = _steps([("Accept clicked", scan.get("accept_clicked")),
                    ("Reject clicked", scan.get("reject_tested")),
                    ("GPC signal sent", scan.get("gpc_tested"))])
    # HOW MUCH TRAFFIC THE RECORDER ACTUALLY SAW.
    #
    # A capture came back with the page's HTML and an empty request list, and
    # every section below read "nothing fired" — the same words a clean site
    # gets. The count is the difference between the two, so it is on screen
    # next to the steps rather than buried in a payload nobody opens.
    # ONE TOTAL WAS NOT ENOUGH.
    #
    # "105 requests recorded" next to "nothing fired" is a contradiction, and
    # a single total cannot say WHICH of the four passes recorded them — so it
    # proved the recorder attached and nothing else. Split by pass, the answer
    # is one glance: requests on the GPC load and none on the pre-consent load
    # is a different bug from requests everywhere and no classification.
    #
    # The split was already being stored. It was only ever a rendering
    # decision not to show it, which is the worst kind of missing diagnostic:
    # the data was on disk the whole time.
    _cc = scan.get("capture_counts") or {}
    _seen = sum(_cc.values()) if _cc else None
    _count_bit = ""
    if _seen is not None:
        _bits = " · ".join(
            f"{_lbl} {_cc.get(_k, 0):,}"
            for _k, _lbl in (("pre", "pre-consent"), ("post", "after accept"),
                             ("reject", "after reject"), ("gpc", "GPC")))
        _count_bit = (
            f"<span class='vstep vstep--{'y' if _seen else 'n'}' "
            f"style='margin-left:auto;margin-right:0' title='{e(_bits)}'>"
            f"<i>{'&#10003;' if _seen else '&#10005;'}</i>"
            f"{_seen:,} request{'s' if _seen != 1 else ''} recorded "
            f"<span style='color:var(--muted);font-weight:400'>"
            f"({e(_bits)})</span></span>")

    # RECORDED BUT NOT CLASSIFIED IS ITS OWN FAILURE.
    #
    # Traffic was captured and none of it matched a known ad or analytics
    # endpoint. On a site with a Tag Manager container that is very close to
    # impossible, and every section below reports it as "nothing fired" —
    # which is the same sentence a genuinely clean site gets. A graceful
    # degradation needs something loud somewhere else, or it is just a silent
    # failure with good manners.
    _classified = (len(scan.get("pre_consent") or [])
                   + len(scan.get("post_reject") or [])
                   + len(scan.get("gpc_fires") or [])
                   + len(scan.get("post_consent") or []))
    _mismatch = bool(_seen and not _classified
                     and (scan.get("gtm") or {}).get("found"))
    parts.append(_sec(
        "Container and configuration",
        _rows(["", "State", "Detail"], cfg_rows, ["30%", "16%", "54%"])
        + f"<div class='card' style='margin-top:10px;display:flex;"
          f"align-items:center;flex-wrap:wrap;gap:6px 0'>"
          f"<span class='sm' style='color:var(--muted);margin-right:16px'>"
          f"Steps this run completed</span>"
        + steps + _count_bit + "</div>"
        + ("<div class='card' style='margin-top:9px;border-left:3px solid "
           "var(--critical);color:#8a1c16'><b>This run watched no traffic.</b> "
           "The browser returned the page's HTML but recorded zero network "
           "requests, which a real page load cannot do &mdash; the recorder "
           "did not attach. Every &ldquo;nothing fired&rdquo; below is that, "
           "not a clean site. Run the capture again.</div>"
           if scan.get("no_requests_recorded") else "")
        + (f"<div class='card' style='margin-top:9px;border-left:3px solid "
           f"var(--critical);color:#8a1c16'><b>Traffic was recorded and none "
           f"of it was recognised.</b> {_seen:,} requests were captured on a "
           f"site running a Tag Manager container, and not one matched a "
           f"known ad or analytics endpoint. That is a fault in this run, not "
           f"a clean site &mdash; treat every &ldquo;nothing fired&rdquo; "
           f"below as unmeasured.</div>" if _mismatch else "")
        + (("<details style='margin-top:9px'><summary class='sm' "
            "style='cursor:pointer;color:var(--blue)'>What the browser "
            "recorded &mdash; one per host</summary>"
            "<div class='card' style='margin-top:6px'>"
            + "".join(f"<div class='vurl'>{e(u)}</div>"
                      for u in (scan.get("unmatched_sample") or []))
            + "</div></details>")
           if scan.get("unmatched_sample") else ""),
        "", tip="gtm"))

    # ----------------------------------------------------------- the trackers
    # Built once, at the top, so the tile and this table cannot disagree.
    # Per page where we have pages, because "which page was this on" is the
    # first question anyone asks about an ungated pixel.
    pre = _pre_all
    # AN EMPTY TABLE AND A CLEAN ONE LOOK IDENTICAL.
    #
    # "No trackers listed under Fired after Reject" reads as a pass. It is a
    # pass only if Reject was actually clicked; if there was no banner to
    # click, the same empty table means nothing was tested. Each of these
    # three sections says which of the two it is, always.
    def fired(title, items, tested, note, untested, tip=None):
        body = _trackers(items, page_col=(bool(pages) and title.endswith(
            "before consent")))
        if not body:
            body = (f"<div class='card' style='border-left:3px solid "
                    f"var(--gold)'>{untested}</div>" if not tested
                    else "<div class='card' style='border-left:3px solid "
                         "var(--good)'><b>Nothing fired.</b> The scan ran "
                         "this step and watched nothing happen, which is the "
                         "result being asked for.</div>")
        return _sec(title, body, note, tip=tip)

    parts.append(fired(
        "Fired before consent", pre, not basic,
        "Read the severity column, not the row count — an expected cookieless "
        "ping sits in the same table as a real ungated fire.",
        "Not tested: this scan ran without a browser, so nothing was watched "
        "as the page loaded.", tip="pre_consent"))

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
        "A reject button that changes nothing is worse than none — it "
        "documents the intent to honour a choice that was not honoured.",
        reject_why, tip="reject"))

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
        "Twelve states require GPC to be honoured as an opt-out, and no "
        "banner click is involved.", gpc_why, tip="gpc"))

    after = scan.get("post_consent") or []
    if after:
        # A LIST OF NAMES IS NOT A TABLE. One column under a full-width navy
        # header, for three words per row — it took the visual weight of the
        # sections that carry a problem, and this is the section where nothing
        # is wrong.
        parts.append(_sec(
            "Fired only after consent",
            "<div class='card'><div style='display:flex;gap:8px;"
            "flex-wrap:wrap'>"
            + "".join(_chip(x.get("vendor") if isinstance(x, dict) else x,
                            "ok") for x in after)
            + "</div></div>",
            "These waited for a choice, which is the behaviour being asked "
            "for."))

    # ------------------------------------------------------------- products
    #
    # THE STANDALONE SCANNER'S LAYOUT, BECAUSE IT WAS RIGHT.
    #
    # A four-column table gave a product row a name, a count and two empty
    # cells, and gave a pixel row a badge marooned in the third column with
    # its evidence in the fourth — so the eye crossed the full page width to
    # join a status to the thing it was about. The original tool puts the
    # badge FIRST, hard against the pixel name, and groups the pixels inside a
    # bordered card headed by their product. Same information, one glance.
    #
    # The wording is the original's too: "configured, not firing" is what a
    # tag in the container that never made a request is, and "never fired"
    # implied a longer observation than one page load.
    prods = scan.get("products") or []
    bought = {str(x) for x in (want.get("products") or [])}
    if prods or bought:
        def _pxbadge(px):
            if px.get("fired_pre"):
                return ("bad", "fires pre-consent") if not _no_cmp \
                    else ("neutral", "ungated")
            if px.get("fired_post"):
                return ("ok", "post-consent")
            if px.get("configured") is True:
                return ("warn", "configured, not firing")
            if px.get("configured") is False:
                return ("bad", "not found")
            return ("bad", "not seen")

        cards = []
        for p in sorted(prods, key=lambda x: str(x.get("product") or "")):
            pix = p.get("pixels") or []
            name = p.get("product") or "?"
            n_fired = int(p.get("fired") or 0)
            n_total = len(pix) or int(p.get("expected") or 0)
            head_kind, head_txt = (
                ("ok", "firing") if n_fired and n_fired == n_total
                else ("bad", "missing") if not n_fired
                else ("warn", "partial"))
            lis = []
            for px in pix:
                kind, stx = _pxbadge(px)
                bits = []
                if px.get("containers"):
                    # Just the container id. "GTM GTM-K4SZBGQZ" said GTM
                    # twice, which is what happens when a label and the thing
                    # it labels both carry the prefix.
                    bits.append(f"<span class='vsrc' title='Found in this "
                                f"published GTM container'>"
                                f"{e(', '.join(px['containers']))}</span>")
                if px.get("macro_warning"):
                    bits.append("<span class='vev' style='color:var(--critical)'>"
                                "unreplaced template macro — pasted without "
                                "filling its values</span>")
                if px.get("severity_note"):
                    bits.append(f"<span class='vev'>{e(px['severity_note'])}"
                                f"</span>")
                url = (f"<div class='vurl'>{e(px['sample_url'][:180])}</div>"
                       if px.get("sample_url") else "")
                lis.append(
                    f"<li><span class='vb vb--{kind}'>{e(stx)}</span>"
                    + (_t("configured") if px.get("configured") is True else "")
                    + f"<div><b>{e(px.get('name') or '?')}</b> "
                    + " ".join(bits) + url + "</div></li>")
            cards.append(
                f"<div class='vprodc'><div class='vprodh'><b>{e(name)}</b>"
                + (f"<span class='vcount'>{n_fired}/{n_total}</span>"
                   if n_total > 1 else "")
                + f"<span class='vb vb--{head_kind}'>{e(head_txt)}</span>"
                + (f"<span class='vev'>on the account</span>"
                   if name in bought else "")
                + "</div><ul>" + ("".join(lis) or
                                  "<li><span class='vb vb--bad'>no pixels "
                                  "seen</span><div>Nothing matching this "
                                  "product was observed.</div></li>")
                + "</ul></div>")
        # A product on the account that the scan never even listed. Absent is
        # unknown, never off — but a bought product with no record at all is
        # the one case where the absence IS the finding.
        for name in sorted(bought - {p.get("product") for p in prods}):
            cards.append(
                f"<div class='vprodc'><div class='vprodh'><b>{e(name)}</b>"
                f"<span class='vb vb--bad'>missing</span>"
                f"<span class='vev'>on the account</span></div>"
                f"<ul><li><span class='vb vb--bad'>not found</span>"
                f"<div>Nothing matching this product fired, and nothing "
                f"matching it is in the page source or the published "
                f"container.</div></li></ul></div>")
        parts.append(_sec(
            "Product pixels",
            "".join(cards),
            "Starts from what was bought, so a pixel they pay for that never "
            "fires is visible — a scan that only reports what it found cannot "
            "show you that.", tip="product"))

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
            "State law checks", _rows([f"State{_t('state')}", "Requirement",
                                       "Result", "Detail"], rows,
                                      ["9%", "20%", "11%", "60%"]),
            f"Only the states this client sells in"
            + (f" — {e(', '.join(want.get('states') or []))}."
               if want.get("states") else "."), tip="state"))
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
        parts.append(_sec(
            "Pages scanned",
            _rows(["URL", "Role", f"Mode{_t('mode')}", "Trackers"], rows,
                  ["40%", "14%", "12%", "34%"]),
            "A conversion page is where conversion pixels actually fire, so "
            "it is the page most likely to carry an ungated one."))

    # ------------------------------------------------------------ opt-out
    if scan.get("optout_link"):
        parts.append(_sec(
            "Opt-out link",
            f"<div class='card'>Matched: <b>{e(scan['optout_link'])}</b></div>",
            "Presence only — whether the link actually works is a human "
            "check.", tip="optout"))

    parts.append(
        f"<div style='margin-top:34px'><a class='btn ghost' "
        f"href='/audits/{e(aid)}'>Back to the audit</a></div>")

    return _shell(f"Consent — {client}", "".join(parts),
                  heading="Consent scan", crumbs=crumbs)
