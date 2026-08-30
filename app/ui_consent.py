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
# ordering and for the chip color; anything unrecognized sorts last and reads
# as informational, because inventing a severity for a word we do not know is
# how a scanner starts overstating its case.
# A real middle dot, so it survives escaping. "&middot;" inside a string that
# then goes through e() comes out as the literal five characters.
_DOT = " \u00b7 "

_SEV = {"critical": 0, "high": 1, "ungated": 1, "medium": 2, "warning": 2,
        "low": 3, "info": 4, "informational": 4}


def _gpc_states(states) -> list:
    """Which of these states require Global Privacy Control to be honored."""
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
    # THE TILE ASKED A DIFFERENT QUESTION FROM THE ONE THE DEFINITION
    # ANSWERED. "Banner on load" borrowed the CMP definition, so hovering it
    # explained what a consent platform is — true, already said one tile to
    # the left, and not the thing the number under the cursor means.
    "banner": "Whether a consent banner was actually VISIBLE when the page "
              "finished loading. A platform can be installed and still show "
              "nobody a banner — wrong trigger, a geo rule, a broken "
              "script — and a banner nobody sees gates nothing.",
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
           "opted out'. Twelve states require a site to honor it, and no "
           "banner click is involved — the browser sends it on every "
           "request.",
    "pre_consent": "Requests the page made before anyone agreed to anything. "
                   "This is the section that decides whether the banner is "
                   "doing its job or decorating a page that tracks anyway.",
    "denied_ping": "A Google request carrying gcs= in a denied state. It is "
                   "cookieless and carries no identifier, so it is correct "
                   "behavior, not a violation — which is why it is marked "
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
            "banner, Consent Mode and pre-consent behavior were never "
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


def _sec(title, body, note="", tip=None, fold=False, count=""):
    """
    One section. Empty body means the section is not rendered at all.

    `fold=True` renders the whole thing as a closed <details>. THIS IS THE
    PAGE'S ORGANIZING RULE, not a styling option: everything below the work
    order is EVIDENCE — the URLs, the per-page walk, the container contents —
    and evidence is what you open when you doubt a conclusion, not what you
    read on the way to one. Nine tables printed flat made a reader who knows
    nothing about tag management scroll past all of it looking for "so what do
    I do", which is the only question they came with.

    A folded section still says how many rows are inside, because a closed box
    with an unknown quantity behind it is a box nobody opens. `count` is
    markup, so a summary can carry a badge as well as a number.

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
    if fold:
        return (f"<details class='cfold'><summary>"
                f"<span class='cfold-t'>{e(title)}</span>"
                # `count` is MARKUP, not text. It carries the container id
                # and the ownership badge, and escaping it printed the badge's
                # HTML across the summary line. Callers escape what they pass.
                + (f"<span class='cfold-n'>{count}</span>" if count else "")
                + (_t(tip) if tip else "")
                + "</summary><div class='cfold-b'>"
                + (f"<div class='csec-note'>{note}</div>" if note else "")
                + body + "</div></details>")
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
    """
    The fired-tag list, in the standalone scanner's shape.

    BADGE FIRST, EVIDENCE ATTACHED.

    As a four-column table the severity sat in column three and the URL in
    column four, so reading "is this a problem" meant crossing the row and
    back. The original tool puts the badge hard against the vendor name with
    the request underneath it, which is one glance instead of three — and it
    is the same object the product cards already use, so the two halves of
    this page stop looking like two different products.
    """
    # THE SAME TAG TWICE IS ONE FINDING.
    #
    # A page that loads fbevents.js three times produced three identical rows
    # — same vendor, same URL, same page — and a reader's first question was
    # "what are these", which is the right question about a list that repeats
    # itself for no stated reason. One row, with the count, says the same
    # thing and can be read.
    seen = {}
    for t in items:
        k = (t.get("_page"), t.get("vendor"), (t.get("url") or "")[:220])
        if k in seen:
            seen[k]["_n"] = seen[k].get("_n", 1) + 1
        else:
            seen[k] = {**t, "_n": 1}
    out = []
    for t in sorted(seen.values(), key=lambda x: (_SEV.get(
            str(x.get("severity") or "").lower(), 9),
            str(x.get("_page") or ""), str(x.get("vendor") or ""))):
        sev = str(t.get("severity") or "recorded").lower()
        kind = {"bad": "bad", "hold": "warn"}.get(_sev_kind(sev), "neutral")
        bits = []
        if t.get("_page"):
            bits.append(f"<span class='vsrc'>{e(t['_page'])}</span>")
        if t.get("note"):
            bits.append(f"<span class='vev'>{e(t['note'])}</span>")
        out.append(
            f"<li><span class='vb vb--{kind}'>"
            f"{e(sev if sev != 'recorded' else 'recorded')}</span>"
            f"<div><b>{e(t.get('vendor') or '?')}</b>"
            + (f"<span class='vcount'>&times;{t['_n']}</span>"
               if t.get("_n", 1) > 1 else "") + " "
            + " ".join(bits)
            + (f"<div class='vurl'>{e((t.get('url') or '')[:220])}</div>"
               if t.get("url") else "")
            + "</div></li>")
    if not out:
        return ""
    return f"<div class='vprodc'><ul>{''.join(out)}</ul></div>"


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
             # ---- two columns where one was half empty -------------------
             #
             # A list of five short rows was rendered at the full width of a
             # 1400px screen, so two thirds of the block was white and the
             # sections either side of it drifted a screen apart. These lists
             # are narrow by nature — a badge, a name, a URL — so they get a
             # column that fits them and pair up when there is room.
             ".vgrid{display:grid;gap:12px;"
             "grid-template-columns:repeat(auto-fit,minmax(430px,1fr));"
             "align-items:start}"
             ".vgrid > *{min-width:0}"
             # ---- ownership ----------------------------------------------
             ".vown{font-weight:700;font-size:10.5px;letter-spacing:.06em;"
             "text-transform:uppercase;border-radius:4px;padding:2px 7px;"
             "white-space:nowrap}"
             ".vown--vici{background:var(--navy);color:#fff}"
             ".vown--client{background:#EDE3F5;color:#5B2B77}"
             # ---- per-page detail ----------------------------------------
             ".vpage{border:1px solid var(--line);border-radius:8px;"
             "background:#fff;margin:0 0 8px}"
             ".vpage > summary{cursor:pointer;padding:9px 12px;"
             "display:flex;align-items:center;gap:9px;flex-wrap:wrap;"
             "font-size:13.5px;list-style:none}"
             ".vpage > summary::-webkit-details-marker{display:none}"
             ".vpage > summary::before{content:'\\25b8';color:var(--muted);"
             "font-size:11px;transition:transform .12s}"
             ".vpage[open] > summary::before{transform:rotate(90deg)}"
             ".vpage[open] > summary{border-bottom:1px dashed var(--line)}"
             ".vpage .vbody{padding:4px 12px 8px}"
             ".vpage .vprodc{border:0;margin:0}"
             # A PRODUCT ROW IS A GROUP HEADER, NOT A ROW WITH EMPTY CELLS.
             #
             # It carried a name and a count and left State and Evidence
             # blank, so two thirds of every product row was white — and with
             # four products that is a lot of the section. Tinting it says
             # "heading", and the emptiness stops reading as missing data.
             "tr:has(.vprod) td{background:#f4f7fb;font-size:13px}"
             "tr:has(.vprod):hover td{background:#eef3f9}"
             # ---- folded evidence sections --------------------------------
             #
             # A closed section has to look like a thing you can open, and it
             # has to say how much is behind it. A bare triangle next to a
             # heading reads as decoration.
             ".cfold{border:1px solid var(--line);border-radius:9px;"
             "background:#fff;margin:9px 0}"
             ".cfold > summary{cursor:pointer;padding:11px 14px;display:flex;"
             "align-items:center;gap:9px;list-style:none;font-size:12px;"
             "font-weight:700;letter-spacing:.07em;text-transform:uppercase;"
             "color:var(--ink2)}"
             ".cfold > summary::-webkit-details-marker{display:none}"
             ".cfold > summary::before{content:'\\25b8';color:var(--muted);"
             "font-size:11px;transition:transform .12s;flex:none}"
             ".cfold[open] > summary::before{transform:rotate(90deg)}"
             ".cfold[open] > summary{border-bottom:1px solid var(--line-2)}"
             ".cfold > summary:hover{background:#f7f9fc}"
             ".cfold-t{flex:1 1 auto;min-width:0}"
             ".cfold-n{font-weight:600;font-size:11px;letter-spacing:.02em;"
             "text-transform:none;color:var(--muted);background:var(--bg-2);"
             "border-radius:20px;padding:2px 9px;flex:none}"
             ".cfold-b{padding:10px 14px 13px}"
             ".cfold-b > .csec-note{margin:0 0 8px}"
             # ---- the issue list ------------------------------------------
             #
             # THE ONE BLOCK SOMEBODY WHO KNOWS NOTHING CAN READ.
             #
             # Severity as a colored rail down the left, the problem in a
             # plain sentence, who fixes it as a badge, and the technical
             # detail behind a disclosure. Nobody has to know what a container
             # or a pre-consent fire is to work out what is wrong and whose
             # job it is — which is the entire ask.
             #
             # THREE TO A ROW. Full-width rows put one short sentence across
             # 1900 pixels and pushed the fifth item off the bottom of the
             # screen, so a list of five problems read as a scroll rather than
             # as a set you can take in at once. Three columns fit the whole
             # work order above the fold and give each sentence a comfortable
             # measure instead of a 200-character line.
             ".vissues{display:grid;gap:10px;margin-top:9px;align-items:start;"
             "grid-template-columns:repeat(3,minmax(0,1fr))}"
             "@media (max-width:1080px){.vissues{"
             "grid-template-columns:repeat(2,minmax(0,1fr))}}"
             "@media (max-width:720px){.vissues{grid-template-columns:1fr}}"
             ".vi{border:1px solid var(--line);border-left:4px solid "
             "var(--line-2);border-radius:9px;background:#fff;padding:0;"
             "display:flex;flex-direction:column;height:100%}"
             ".vi--bad{border-left-color:var(--critical)}"
             ".vi--warn{border-left-color:var(--gold)}"
             ".vi--info{border-left-color:var(--blue)}"
             # The owner badge sat to the RIGHT of the text, which works on a
             # full-width row and strands it in a card. It goes above the
             # title now: who owns this is the first thing to know about an
             # item, and it is the only part of the card that is the same
             # shape every time, so it reads as a column when they line up.
             ".vi-h{display:flex;flex-direction:column;align-items:flex-start;"
             "gap:0;padding:11px 14px;flex:1 1 auto}"
             ".vi-h .vown{margin-bottom:7px}"
             ".vi-x{min-width:0;width:100%}"
             ".vi-t{font-size:14.5px;font-weight:700;line-height:1.35;"
             "color:var(--ink);text-wrap:balance}"
             ".vi-s{font-size:13px;color:var(--ink2);line-height:1.55;"
             "margin-top:3px}"
             ".vi-w{font-size:13px;line-height:1.55;margin-top:6px;"
             "color:var(--ink)}"
             ".vi-w b{font-weight:700}"
             ".vi-d{margin:0 14px 11px;font-size:12.5px;flex:none}"
             ".vi-d > summary{cursor:pointer;color:var(--blue);"
             "font-weight:600;list-style:none;padding:2px 0}"
             ".vi-d > summary::-webkit-details-marker{display:none}"
             ".vi-d > summary::before{content:'\\25b8 ';font-size:10px}"
             ".vi-d[open] > summary::before{content:'\\25be '}"
             ".vi-d .vi-dd{color:var(--ink2);line-height:1.6;padding:6px 0 2px;"
             "border-top:1px solid var(--line-2);margin-top:5px}"
             ".vi-d code{font-size:11.5px;word-break:break-all}"
             # The state, as a pill, at the head of the sentence it is the
             # subject of. "Certain states require…" made the reader ask
             # which, when the answer was three words away.
             ".vstate{display:inline-block;font-weight:700;font-size:11px;"
             "letter-spacing:.07em;background:var(--navy);color:#fff;"
             "border-radius:4px;padding:1px 7px;margin-right:5px;"
             "vertical-align:1px}"
             ".vi-none{border:1px solid var(--line);border-left:4px solid "
             "var(--good);border-radius:9px;background:#fff;padding:13px 15px;"
             "font-size:13.5px;line-height:1.6;margin-top:9px}"
             # ---- the state-law panel -------------------------------------
             #
             # One card per state rather than one flat table of every row for
             # every state. A reader asks "are we OK in California", and the
             # answer to that question is a card, not four rows they have to
             # gather themselves out of twenty.
             # THREE PER ROW. auto-fit gave two fat cards on a wide screen
             # and pushed the third onto a row of its own, so the panel read
             # as "two states matter and one is an afterthought".
             ".vlaws{display:grid;gap:10px;margin-top:9px;"
             "grid-template-columns:repeat(3,minmax(0,1fr))}"
             "@media (max-width:1080px){.vlaws{"
             "grid-template-columns:repeat(2,minmax(0,1fr))}}"
             "@media (max-width:720px){.vlaws{grid-template-columns:1fr}}"
             ".vlaw{border:1px solid var(--line);border-radius:10px;"
             "background:#fff;overflow:hidden}"
             ".vlaw-h{padding:10px 13px;border-bottom:1px solid var(--line-2);"
             "display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}"
             ".vlaw-h b{font-size:14.5px}"
             ".vlaw-h .law{font-size:12px;color:var(--ink2);flex:1 1 auto;"
             "min-width:0}"
             ".vlaw--bad .vlaw-h{background:#fdf1f0}"
             ".vlaw--warn .vlaw-h{background:#fdf6ec}"
             ".vlaw--ok .vlaw-h{background:#f0f8f2}"
             ".vlaw ul{list-style:none;margin:0;padding:4px 13px 9px}"
             ".vlaw li{display:flex;gap:9px;align-items:flex-start;"
             "font-size:13px;padding:6px 0;border-bottom:1px dashed "
             "var(--line-2);line-height:1.5}"
             ".vlaw li:last-child{border-bottom:none}"
             ".vlaw .m{flex:none;width:15px;font-weight:700;text-align:center}"
             ".vlaw .m--ok{color:var(--good)}"
             ".vlaw .m--no{color:var(--critical)}"
             ".vlaw .m--w{color:var(--gold)}"
             ".vlaw .m--u{color:var(--muted)}"
             ".vlaw .rq{flex:1 1 auto;min-width:0}"
             ".vlaw .rq i{font-style:normal;color:var(--ink2);display:block;"
             "font-size:12px;margin-top:1px}"
             ".vlaw-f{padding:8px 13px;border-top:1px solid var(--line-2);"
             "background:var(--bg-2);font-size:11.5px;color:var(--muted);"
             "line-height:1.5}"
             "</style>")


def _steps(pairs):
    """A tick or a cross per step, on one line, with no pill anywhere."""
    out = []
    for row in pairs:
        label, ok = row[0], row[1]
        note = row[2] if len(row) > 2 else ""
        out.append(f"<span class='vstep vstep--{'y' if ok else 'n'}'>"
                   f"<i>{'&#10003;' if ok else '&#10005;'}</i>{e(label)}"
                   + (f"<span style='color:var(--muted)'>{e(note)}</span>"
                      if note else "") + "</span>")
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


def consent_html(audit: dict, detail: dict | None, tabs: str = "") -> str:
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
        return _shell(f"Consent — {client}", _PAGE_CSS + tabs + body,
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
    # color every other tile on this dashboard uses for "here is a number".
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
              _t("banner"),
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

    parts = [_PAGE_CSS, tabs, "".join(head)]

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

    # ------------------------------------------------- what is wrong, and whose
    #
    # THE ONE BLOCK FOR SOMEBODY WHO KNOWS NOTHING ABOUT ANY OF THIS.
    #
    # This page is written for a reader who does not know what a container is,
    # has never heard of Consent Mode, and needs to leave knowing three
    # things: what is wrong, what has to happen, and who does it. Everything
    # else on the page is the evidence behind those three, and evidence is
    # what you open when you doubt a conclusion — not what you wade through on
    # the way to one. So this is first, it is in plain sentences, and every
    # technical fact behind it is one disclosure triangle away.
    #
    # THE FIX AND THE OWNER TRAVEL TOGETHER. "A pixel fires pre-consent" is
    # our work queue in a container we own and a conversation in the client's,
    # and the badge is what tells those apart before anybody starts typing.
    # The facts read here are established further down the page — hoisted, not
    # duplicated, so there is still one definition of each.
    gtm = scan.get("gtm") or {}
    bought = {str(x) for x in (want.get("products") or [])}
    _impl = str(want.get("implementation") or "").lower()
    _ours = ("vici" in _impl or _impl == "gtm")
    VICI = "<span class='vown vown--vici'>Vici does this</span>"
    CLIENT = "<span class='vown vown--client'>Client does this</span>"
    _owner = VICI if _ours else CLIENT
    _issues = []

    def _issue(kind, title, plain, fix, owner, detail=""):
        """
        One problem, in four parts a non-specialist can act on.

        `title`   what is wrong, as a sentence, no jargon
        `plain`   why it matters, in the terms a business owner thinks in
        `fix`     the thing that has to happen
        `owner`   who does it
        `detail`  the technical evidence, folded away
        """
        _issues.append(
            f"<div class='vi vi--{kind}'><div class='vi-h'>{owner}"
            f"<div class='vi-x'>"
            f"<div class='vi-t'>{title}</div>"
            f"<div class='vi-s'>{plain}</div>"
            f"<div class='vi-w'><b>Fix:</b> {fix}</div></div></div>"
            + (f"<details class='vi-d'><summary>Show the evidence</summary>"
               f"<div class='vi-dd'>{detail}</div></details>" if detail else "")
            + "</div>")

    # Ordered by dependency, because that is the order the work has to happen
    # in: a mechanism has to exist before anything can be gated on it, and
    # gating has to exist before Consent Mode means anything.
    _mech_fail = [c for c in (scan.get("state_checks") or [])
                  if str(c.get("check")) == "Opt-out mechanism"
                  and str(c.get("status", "")).lower() == "fail"]
    if _mech_fail and not basic:
        _sts = sorted({str(c.get("state")) for c in _mech_fail})
        _issue("bad",
               "Visitors have no way to opt out of tracking",
               f"Residents of {e(', '.join(_sts))} have a legal right to tell "
               f"this site to stop selling or sharing their data. There is "
               f"nothing on the site that lets them.",
               "Install a consent banner (a CMP). One install delivers the "
               "opt-out link, the browser opt-out signal and the ability to "
               "hold tags back until someone chooses. The law asks for the "
               "opt-out, not the banner — the banner is just the cheapest way "
               "to deliver all of it at once."
               + (" Once it is in, Vici wires the tags to it." if _ours else ""),
               CLIENT,
               "No CMP signature matched, no opt-out link text was found on "
               "the page, and " + ("the GPC signal was ignored"
                                   if scan.get("gpc_fires") else
                                   "this state has no universal-signal rule "
                                   "to fall back on") + ".")
    # EVERY FAILING STATE REQUIREMENT GETS A LINE OF ITS OWN.
    #
    # California asks for three separate things and the page reported one, so
    # a site missing all three read as a site missing the famous one. Each is
    # a different section of the statute with a different fix, and lumping
    # them loses which is which.
    # NAME THE STATE, DO NOT SAY "CERTAIN STATES".
    #
    # "Certain states require a clearly labeled link" makes the reader ask
    # which — and the answer is sitting three words away in the same object.
    # The states go in as a pill, colored, where the eye lands first, and the
    # sentence that used to append "Applies here because this client targets
    # CA" comes out, because that is the pill saying itself again.
    #
    # And "The scan could not find one" comes out of every row. The heading
    # already says there is no link; a scan reporting an absence it did not
    # observe is not a thing that happens here.
    def _sp(states):
        return "".join(f"<span class='vstate'>{e(x)}</span>" for x in states)

    def _subj(states, verb):
        """
        The pills, then a verb that agrees with how many of them there are.

        "CA CO TX requires a clearly labeled link" is the sentence this
        produced before the pills went in, and it is the kind of thing a
        client notices in a document about their legal exposure. The verbs
        are stored singular and bent here, because the caller does not know
        how many states will end up on the row.
        """
        one = len(states) == 1
        if not one:
            verb = {"requires": "require", "gives": "give", "flips": "flip",
                    "expects": "expect", "treats": "treat"}.get(verb, verb)
        return _sp(states) + " " + verb

    _law_titles = {
        "Opt-out link": ("There is no \u201cDo Not Sell or Share\u201d link",
                         "requires", "a clearly labeled link letting visitors "
                         "refuse the sale or sharing of their data.",
                         "Add a footer link reading \u201cYour Privacy "
                         "Choices\u201d or \u201cDo Not Sell or Share My "
                         "Personal Information\u201d that opens a working "
                         "opt-out. A CMP normally provides it."),
        "Sensitive info link": ("There is no sensitive-information link",
                                "gives", "visitors a SEPARATE right from the "
                                "opt-out above, needing its own link. It "
                                "covers precise location, health, race or "
                                "ethnicity and message contents.",
                                "Add a \u201cLimit the Use of My Sensitive "
                                "Personal Information\u201d link, or a "
                                "combined \u201cYour Privacy Choices\u201d "
                                "page that offers both rights."),
        "Notice at collection": ("There is no notice at the point of "
                                 "collection",
                                 "requires", "the categories of data collected "
                                 "and what they are used for to be disclosed "
                                 "where the collecting happens \u2014 a "
                                 "privacy policy in the footer is not by "
                                 "itself that notice.",
                                 "Add a short notice at collection (often a "
                                 "line plus a link inside the banner and on "
                                 "forms) listing the categories collected and "
                                 "the purposes."),
        "GPC signal": ("The browser's opt-out signal is being ignored",
                       "treats", "ignoring the automatic \u201cdo not sell my "
                       "data\u201d signal some browsers send as the same "
                       "thing as ignoring somebody who clicked opt out.",
                       "Configure the CMP to read Global Privacy Control and "
                       "suppress advertising tags when it is present."),
        "Under-16 opt-in": ("Under-16 visitors need to opt IN, not opt out",
                            "flips", "the rule for a visitor known to be under "
                            "16: their data cannot be sold or shared unless "
                            "they say yes first \u2014 the visitor at "
                            "13\u201315, a parent under 13.",
                            "If this audience includes families or minors, "
                            "the banner has to default to REJECT rather than "
                            "accept, and any age signal the site collects "
                            "needs a human review."),
        "Privacy policy link": ("There is no privacy policy link",
                                "expects", "every site that tracks visitors to "
                                "have an accessible privacy policy.",
                                "Publish a privacy policy and link it in the "
                                "footer of every page."),
    }
    _seen_law = set()
    # Failures before warnings. A "check whether your audience includes
    # minors" note printed above three outright missing links reads as the
    # most urgent thing on the page, and it is not.
    _law_order = {"fail": 0, "unknown": 1, "warn": 2}
    # WITHIN A SEVERITY, THE ORDER IS THE STATUTE'S, NOT THE ALPHABET'S.
    # Sorting the failures by name put "Notice at collection" above "Do Not
    # Sell or Share", which is the one everybody has heard of and the one a
    # CMP install fixes first.
    _law_rank = {"Privacy policy link": 0, "Opt-out link": 1,
                 "Sensitive info link": 2, "Notice at collection": 3,
                 "GPC signal": 4, "Under-16 opt-in": 5}
    for c in sorted((scan.get("state_checks") or []),
                    key=lambda x: (_law_order.get(
                        str(x.get("status") or "").lower(), 3),
                        _law_rank.get(str(x.get("check") or ""), 9),
                        str(x.get("check") or ""))):
        _ck = str(c.get("check") or "")
        _stt = str(c.get("status") or "").lower()
        if _ck == "Opt-out mechanism" or _stt in ("pass", "ok", "met"):
            continue
        if _ck not in _law_titles or _ck in _seen_law:
            continue
        _seen_law.add(_ck)
        _states_for = sorted({str(x.get("state")) for x in
                              (scan.get("state_checks") or [])
                              if str(x.get("check")) == _ck
                              and str(x.get("status") or "").lower()
                              not in ("pass", "ok", "met")})
        _ttl, _vb, _pl, _fx = _law_titles[_ck]
        # The pill IS the subject of the sentence: "CA requires a clearly
        # labeled link…". Nothing has to be appended to explain why the row
        # is on the page.
        _issue("warn" if _stt in ("warn", "unknown") else "bad", _ttl,
               _subj(_states_for, _vb) + " " + _pl,
               _fx, CLIENT,
               "<br>".join(e(str(x.get("detail") or "")) for x in
                           (scan.get("state_checks") or [])
                           if str(x.get("check")) == _ck
                           and str(x.get("status") or "").lower()
                           not in ("pass", "ok", "met")))
    # THE OBSERVED FACT, not only the statute row.
    #
    # Trackers contacted on a GPC page load is something the scan WATCHED
    # happen. The per-state rows say which states care; this says it occurred.
    # Reading it only off the state rows meant a scan whose states were never
    # recorded watched the signal being ignored and said nothing.
    if (scan.get("gpc_tested") and scan.get("gpc_fires")
            and "GPC signal" not in _seen_law):
        _gv = sorted({str(f.get("vendor")) for f in scan["gpc_fires"]})
        _issue("bad",
               "The browser's opt-out signal is being ignored",
               f"Some browsers send an automatic \u201cdo not sell my "
               f"data\u201d signal on every page. {e(_listy(_gv))} "
               f"{'were' if len(_gv) != 1 else 'was'} contacted anyway. "
               f"Several states treat that the same as ignoring somebody who "
               f"clicked opt out.",
               "Configure the consent platform to read Global Privacy Control "
               "and hold advertising tags back when it is present.",
               CLIENT,
               _trackers(scan["gpc_fires"][:10]))
        _seen_law.add("GPC signal")
    if _no_cmp and _pre_real and not basic:
        _vend = sorted({str(h.get("vendor")) for h in _pre_real})
        _issue("bad",
               f"{len(_vend)} tracking tag{'s' if len(_vend) != 1 else ''} "
               f"fire{'' if len(_vend) != 1 else 's'} before anyone agrees",
               f"{e(_listy(_vend))} "
               f"{'start' if len(_vend) != 1 else 'starts'} collecting the "
               f"moment a page loads, and there is no way for a visitor to "
               f"decline first. This is the pattern state regulators have "
               f"actually brought cases about.",
               "Hold these tags behind the consent banner so they only fire "
               "after someone accepts."
               + ("" if _ours else " Vici supplies the exact procedure; the "
                                   "client's team applies it in their "
                                   "container."),
               _owner,
               _trackers(_pre_real[:12], page_col=any(
                   t.get("_page") for t in _pre_real)))
    if scan.get("consent_mode_default") is False and (gtm or {}).get("found"):
        _issue("warn",
               "Google tags are not told to wait",
               "Google Consent Mode is the switch that tells Google's tags to "
               "run in a limited, cookieless way until someone chooses. It is "
               "not set here, so Google tags run at full capability from the "
               "first page load and the banner has nothing to flip.",
               "Declare Consent Mode defaults as denied in the container, "
               "then let the banner grant them.",
               _owner,
               "No <code>gtag('consent','default',...)</code> call was seen "
               "in the dataLayer before the first tag fired.")
    _miss = [p.get("product") for p in (scan.get("products") or [])
             if not int(p.get("fired") or 0)]
    _miss += sorted(bought - {p.get("product") for p in (scan.get("products") or [])})
    _miss = sorted(set(x for x in _miss if x))
    if _miss and not basic:
        _issue("warn",
               f"{e(_listy(_miss))} "
               f"{'products are' if len(_miss) != 1 else 'product is'} "
               f"running but not firing",
               "The campaign is live on the account and its tracking pixel "
               "was not seen on any page the scan visited, so it is running "
               "without the data it is supposed to collect.",
               "Install or repair the pixel, then re-run this scan to "
               "confirm it fires.",
               _owner,
               "Checked every page in the scan for each product's known "
               "pixel signatures; none matched.")
    if _issues:
        parts.append(_sec(
            "What needs fixing",
            f"<div class='vissues'>{''.join(_issues)}</div>",
            "In the order the work has to happen \u2014 a way to opt out "
            "first, then gating the tags, then Consent Mode. Open "
            "<b>Show the evidence</b> on any row for the technical detail "
            "behind it."))
    else:
        parts.append(_sec(
            "What needs fixing",
            "<div class='vi-none'><b>Nothing outstanding from this scan.</b> "
            "A consent platform was found, tags waited for a choice, and "
            "every state requirement the scan can test came back clean. The "
            "sections below are the evidence for that.</div>"))

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
            tip="cmp", fold=True,
            count=e(", ".join(c.get("name") or "?" for c in _cmps))))
    else:
        parts.append(_sec(
            "Consent platform",
            "<div class='card'><b>No recognized consent platform.</b>"
            "<div class='sm' style='color:var(--ink2);margin-top:6px'>"
            "Either there is none, or the banner is custom-built and carries "
            "no signature the scanner knows. Worth thirty seconds in a "
            "browser before it goes in a deck.</div></div>",
            fold=True, count="none found"))

    cm = scan.get("consent_mode_default")
    defaults = scan.get("consent_defaults") or {}
    cfg_rows = []
    # Defined outside the branch because the collapsed section header uses it
    # too, and a name that only exists on the happy path is a NameError
    # waiting for a scan with no container.
    _own = ""
    if gtm:
        ids = gtm.get("container_ids") or []
        # WHOSE CONTAINER IT IS — ESTABLISHED, NOT DECLARED.
        #
        # This started as the Implementation field off the form, which is a
        # person's answer to a question. With Tag Manager credentials it is a
        # fact instead: if one of our logins can read the container through
        # the API, we own it. The form value is the fallback for a run with no
        # credentials configured, and it says which of the two you are looking
        # at rather than presenting a guess as a reading.
        _vici = set(gtm.get("vici_owned") or [])
        _impl = str(want.get("implementation") or "").lower()
        if _vici:
            _own = ("<span class='vown vown--vici' title='One of our Google "
                    "logins can read this container through the Tag Manager "
                    "API'>Vici owned</span>")
        elif gtm.get("audits"):
            _own = ("<span class='vown vown--client' title='No authorized "
                    "Vici login can see this container'>Client owned</span>")
        elif "vici" in _impl or _impl == "gtm":
            _own = ("<span class='vown vown--vici' title='From the "
                    "Implementation field on the audit, not an API read'"
                    ">Vici owned<span style='opacity:.7'> (stated)</span>"
                    "</span>")
        elif "client" in _impl:
            _own = ("<span class='vown vown--client' title='From the "
                    "Implementation field on the audit, not an API read'"
                    ">Client owned<span style='opacity:.7'> (stated)</span>"
                    "</span>")
        else:
            _own = ""
        _read = int(gtm.get("tags_read") or 0)
        _readbit = (f" <span class='vsrc' title='Read through the Tag Manager "
                    f"API — this is the published configuration, not an "
                    f"inference from the page'>&#10003; {_read} tags read via "
                    f"API</span>" if _read else "")
        cfg_rows.append([
            "Google Tag Manager" + (f" {_own}" if _own else ""),
            _chip("found", "ok") if gtm.get("found") else _chip("not found", "hold"),
            ", ".join(f"<code>{e(i)}</code>" for i in ids) + _readbit or "—"])
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
    # A CARRIED STEP IS A TICK WITH A DATE ON IT, NOT A PLAIN TICK.
    #
    # Carrying the GPC result forward stops us asking for a re-run we do not
    # need, and it must never read as though this run did the work. The date
    # is the whole difference.
    def _when(key):
        w = scan.get(key)
        return f" (from {str(w)[:16]})" if w else ""
    steps = _steps([
        ("Accept clicked", scan.get("accept_clicked"), ""),
        ("Reject clicked", scan.get("reject_tested"),
         _when("reject_carried_at")),
        ("GPC signal sent", scan.get("gpc_tested"), _when("gpc_carried_at"))])
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
           f"of it was recognized.</b> {_seen:,} requests were captured on a "
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
        "", tip="gtm", fold=True,
        # WHOSE CONTAINER, ON THE LINE THAT NAMES IT.
        #
        # Ownership decides who does the work, and it was only visible after
        # opening the section — so the collapsed line gave you an id and left
        # the one operational question about it unanswered. The badge is the
        # same one the work order uses, so the two read as the same fact.
        count=((e(", ".join((scan.get("gtm") or {}).get("container_ids") or []))
                or "no container")
               + ((" " + _own) if _own else ""))))

    # -------------------------------------------------- container contents
    #
    # WHAT IS IN THE CONTAINER, not what the page happened to fetch.
    #
    # Every other section on this page is observation: we watched a page load
    # and recorded what it contacted. This one is configuration — the tag
    # list, the triggers, and whether each tag declares that it waits for
    # consent. Those are different questions, and the gap between them is
    # where the work is: a tag configured and never firing, a tag firing that
    # nobody knew was there, a container where Consent Mode is set and twelve
    # non-Google tags have no consent check at all.
    #
    # Only appears when the API answered. A fingerprint guess dressed up in
    # this shape would be the worst of both.
    _auds = [a_ for a_ in (gtm.get("audits") or {}).values()
             if a_.get("status") == "ok"]
    if _auds:
        _ccards = []
        for a_ in _auds:
            _tags = a_.get("tags") or []
            _gated = [t for t in _tags
                      if str(t.get("consent_status")) == "NEEDED"]
            _live = [t for t in _tags if not t.get("paused")]
            # Group by vendor, because a work order is per vendor and a tag
            # list of twenty-nine is not readable as a list of twenty-nine.
            _byv = {}
            for t in _tags:
                _byv.setdefault(t.get("vendor") or "Unidentified", []).append(t)
            _rows2 = []
            for _v, _ts in sorted(_byv.items(),
                                  key=lambda kv: (-len(kv[1]), kv[0])):
                _g = [t for t in _ts if str(t.get("consent_status")) == "NEEDED"]
                _p = [t for t in _ts if t.get("paused")]
                _trigs = {}
                for t in _ts:
                    for d in t.get("trigger_detail") or []:
                        _trigs[str(d.get("type") or "?").lower()] = \
                            _trigs.get(str(d.get("type") or "?").lower(), 0) + 1
                _kind, _lbl = (("ok", "gated") if _g and len(_g) == len(_ts)
                               else ("warn", f"{len(_g)} of {len(_ts)} gated")
                               if _g else ("bad", "not gated"))
                _bits = [f"{len(_ts)} tag{'s' if len(_ts) != 1 else ''}"]
                if _p:
                    _bits.append(f"{len(_p)} paused")
                _bits += [f"{n} {k}" for k, n in sorted(_trigs.items())]
                _rows2.append(
                    f"<li><span class='vb vb--{_kind}'>{e(_lbl)}</span>"
                    f"<div><b>{e(_v)}</b> "
                    f"<span class='vev'>{e(_DOT.join(_bits))}</span>"
                    + "".join(
                        f"<div class='vurl'>{e(t.get('name') or '?')}"
                        + (" — paused" if t.get("paused") else "")
                        + (f" — {e(', '.join(t.get('firing_triggers') or []))}"
                           if t.get("firing_triggers") else "")
                        + "</div>" for t in _ts[:12])
                    + "</div></li>")
            _ccards.append(
                f"<div class='vprodc'><div class='vprodh'>"
                f"<b>{e(a_.get('public_id') or '?')}</b>"
                f"<span class='vcount'>{len(_tags)} tags</span>"
                f"<span class='vb vb--{'ok' if len(_gated) == len(_tags) and _tags else ('warn' if _gated else 'bad')}'>"
                f"{len(_gated)} with a consent check</span>"
                + (f"<span class='vev'>{e(a_.get('account_name') or '')}"
                   f"</span>" if a_.get("account_name") else "")
                + f"</div><ul>{''.join(_rows2)}</ul></div>")
        _tags_total = sum(len(a_.get("tags") or []) for a_ in _auds)
        _cm_note = ""
        if scan.get("consent_mode_default") is True:
            _ungated_n = sum(1 for a_ in _auds for t in (a_.get("tags") or [])
                             if str(t.get("consent_status")) != "NEEDED")
            if _ungated_n:
                _cm_note = (
                    f"<div class='card' style='margin-top:9px;border-left:"
                    f"3px solid var(--gold);color:#8a5d05'>Consent Mode covers "
                    f"Google tags only. {_ungated_n} other tag"
                    f"{'s' if _ungated_n != 1 else ''} in "
                    f"{'these containers' if len(_auds) != 1 else 'this container'} "
                    f"have no per-tag consent check, so the defaults do not "
                    f"gate them.</div>")
        parts.append(_sec(
            "Container configuration",
            "".join(_ccards) + _cm_note,
            "The published configuration, read through the Tag Manager API — "
            "what is set up, as against what the page was observed doing.",
            tip="gtm", fold=True,
            count=f"{_tags_total} tag{'s' if _tags_total != 1 else ''}"))

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
        # EVERY ONE OF THESE IS EVIDENCE, so it folds. The count on the
        # closed summary is what makes that safe: "Fired before consent (0)"
        # is an answer, and nobody has to open it to get one.
        return _sec(title, body, note, tip=tip, fold=True,
                    count=(f"{len(items)} tag{'s' if len(items) != 1 else ''}"
                           if tested else "not tested"))

    parts.append(fired(
        "Fired before consent", pre, not basic,
        "Read the badge, not the row count — an expected cookieless ping sits "
        "in the same list as a real ungated fire.",
        "Not tested: this scan ran without a browser, so nothing was watched "
        "as the page loaded.", tip="pre_consent"))

    reject_why = ("Not tested: this scan ran without a browser."
                  if basic else
                  "Not tested: no Reject control was found to click — there "
                  "is no consent banner on this site."
                  if not (scan.get("cmps") or []) else
                  "Not tested: a consent platform was found but the scan "
                  "could not locate a Reject control on its banner.")
    _rej_block = fired(
        "Fired after Reject", scan.get("post_reject") or [],
        scan.get("reject_tested"),
        "A reject button that changes nothing is worse than none — it "
        "documents the intent to honor a choice that was not honored.",
        reject_why, tip="reject")

    gpc_states = _gpc_states(want.get("states") or scan.get("states") or [])
    gpc_why = ("Not tested: this scan ran without a browser." if basic else
               f"Not applicable: none of the states this client sells in "
               f"({e(', '.join(want.get('states') or scan.get('states') or [])) or 'none recorded'}) "
               f"require Global Privacy Control to be honored."
               if not gpc_states else
               f"Not tested, although {e(', '.join(gpc_states))} "
               f"{'requires' if len(gpc_states) == 1 else 'require'} it. "
               f"That is ours to fix, not the client's.")
    # SIDE BY SIDE. Both are short lists about what a refusal did or did not
    # stop, and each was taking a full-width block of a wide screen to say
    # four things — so the two halves of one question sat a screen apart.
    _gpc_block = fired(
        "Fired despite Global Privacy Control", scan.get("gpc_fires") or [],
        scan.get("gpc_tested"),
        "Twelve states require GPC to be honored as an opt-out, and no "
        "banner click is involved.", gpc_why, tip="gpc")
    parts.append(f"<div class='vgrid'><div>{_rej_block}</div>"
                 f"<div>{_gpc_block}</div></div>")

    # SEVENTEEN PAGES, ELEVEN VENDORS, ONE HUNDRED AND EIGHTY-SEVEN CHIPS.
    #
    # `post_consent` is merged across every scanned page, and this printed the
    # merged list verbatim — so a clean seventeen-page site produced the same
    # eleven names sixteen times over, filling a screen and a half to say
    # "eleven vendors waited for a choice". The page count is the interesting
    # part of the repetition, so it is kept as a number on the chip and the
    # rest goes.
    _after_raw = [(x.get("vendor") if isinstance(x, dict) else x)
                  for x in (scan.get("post_consent") or [])]
    _after_n = {}
    for _v in _after_raw:
        if _v:
            _after_n[_v] = _after_n.get(_v, 0) + 1
    after = sorted(_after_n)
    if after:
        # A LIST OF NAMES IS NOT A TABLE. One column under a full-width navy
        # header, for three words per row — it took the visual weight of the
        # sections that carry a problem, and this is the section where nothing
        # is wrong.
        parts.append(_sec(
            "Fired only after consent",
            "<div class='card'><div style='display:flex;gap:8px;"
            "flex-wrap:wrap'>"
            + "".join(
                f"<span class='amark amark--ok'>{e(v)}"
                + (f"<span style='opacity:.65;font-weight:400'> &times;"
                   f"{_after_n[v]}</span>" if _after_n[v] > 1 else "")
                + "</span>" for v in after)
            + "</div></div>",
            f"{len(after)} vendor{'s' if len(after) != 1 else ''} waited for a "
            f"choice, which is the behavior being asked for. The count is how "
            f"many scanned pages each was seen on.",
            fold=True,
            count=f"{len(after)} vendor{'s' if len(after) != 1 else ''}"))

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
            "show you that.", tip="product", fold=True,
            count=f"{len(cards)} product{'s' if len(cards) != 1 else ''}"))

    # ---------------------------------------------------------- state laws
    #
    # ONE CARD PER STATE, NOT ONE TABLE OF EVERY ROW FOR EVERY STATE.
    #
    # The question a reader arrives with is "are we OK in California" — and
    # the answer to that is a card: the law's name, what it asks for, and how
    # each requirement came out. As a flat four-column table sorted by state
    # they had to gather four rows out of twenty themselves, and the state
    # column repeated the same two letters down the page while the thing that
    # differed sat in a 60%-wide Detail cell.
    #
    # This is also where the count comes from. California asks for three
    # separate things and the old table gave each of them a row indistinguish-
    # able from Colorado's one, so a site failing all three CA requirements
    # and passing everywhere else looked like a site with a scattering of
    # problems rather than one state going badly wrong.
    st = scan.get("state_checks") or []
    if st:
        from engine.consent.state_checks import (STATE_CHECKS as _SC,
                                                 LAST_REVIEWED as _REV)
        _by_state = {}
        for c in st:
            _by_state.setdefault(str(c.get("state") or "—"), []).append(c)
        _MARK = {"pass": ("m--ok", "\u2713"), "fail": ("m--no", "\u2717"),
                 "warn": ("m--w", "!"), "unknown": ("m--u", "?")}
        cards = []
        # US first — it is the baseline everything else sits on top of — then
        # the worst-off states, because a card that is all ticks is not the
        # one anybody needs to read first.
        def _rank(k):
            rows = _by_state[k]
            bad = sum(1 for r in rows
                      if str(r.get("status") or "").lower() == "fail")
            return (0 if k == "US" else 1, -bad, k)
        for stt in sorted(_by_state, key=_rank):
            rows = _by_state[stt]
            cfg = _SC.get(stt) or {}
            _n_bad = sum(1 for r in rows
                         if str(r.get("status") or "").lower() == "fail")
            _n_warn = sum(1 for r in rows
                          if str(r.get("status") or "").lower() == "warn")
            kind = "bad" if _n_bad else ("warn" if _n_warn else "ok")
            lis = []
            for c in sorted(rows, key=lambda x: (
                    {"fail": 0, "warn": 1, "unknown": 2}.get(
                        str(x.get("status") or "").lower(), 3),
                    str(x.get("check") or ""))):
                cls, sym = _MARK.get(str(c.get("status") or "").lower(),
                                     ("m--u", "?"))
                lis.append(f"<li><span class='m {cls}'>{sym}</span>"
                           f"<span class='rq'>{e(c.get('check') or '—')}"
                           f"<i>{e(c.get('detail') or '')}</i></span></li>")
            _nm = cfg.get("name") or ("Every US site" if stt == "US" else stt)
            _lw = cfg.get("law") or ("FTC Act \u00a75 baseline"
                                     if stt == "US" else "")
            _head = (f"<b>{e(_nm)}</b>"
                     f"<span class='law'>{e(_lw)}</span>"
                     + (f"<span class='vb vb--bad'>{_n_bad} failing</span>"
                        if _n_bad else
                        (f"<span class='vb vb--hold'>{_n_warn} to check</span>"
                         if _n_warn else
                         "<span class='vb vb--ok'>clear</span>")))
            _foot = ""
            if cfg.get("cite") or cfg.get("verify") or cfg.get("notes"):
                _bits = []
                if cfg.get("notes"):
                    _bits.append(e(cfg["notes"]))
                if cfg.get("verify"):
                    _bits.append("Sources conflicted on the effective date at "
                                 "last review \u2014 confirm with counsel.")
                if cfg.get("cite"):
                    _bits.append(e(cfg["cite"]))
                _foot = f"<div class='vlaw-f'>{' '.join(_bits)}</div>"
            cards.append(f"<div class='vlaw vlaw--{kind}'>"
                         f"<div class='vlaw-h'>{_head}</div>"
                         f"<ul>{''.join(lis)}</ul>{_foot}</div>")
        # A STATE WE DO NOT CHECK MUST BE SAID OUT LOUD, or a client in
        # Georgia cannot tell "we looked and there is nothing to check" from
        # "we forgot to look".
        _asked = [x for x in (want.get("states") or [])]
        _unchecked = [x for x in _asked if x not in _by_state]
        _note = ("Checked against the states this client targets"
                 + (f" \u2014 {e(', '.join(_asked))}." if _asked else ".")
                 + (f" No comprehensive law in our map for "
                    f"{e(', '.join(_unchecked))}, so nothing was tested "
                    f"there." if _unchecked else "")
                 + f" Law map last reviewed {e(_REV)}. These are technical "
                   f"checks, not legal advice.")
        parts.append(_sec("State privacy law",
                          f"<div class='vlaws'>{''.join(cards)}</div>",
                          _note, tip="state"))
    elif want.get("states"):
        parts.append(_sec(
            "State privacy law",
            f"<div class='card'>No per-state results were recorded for "
            f"{e(', '.join(want['states']))}.</div>"))

    # ------------------------------------------------------------ every page
    #
    # EXPANDABLE, BECAUSE "WHICH PAGE" IS THE FIRST QUESTION.
    #
    # The table said "3 before consent" and stopped, so finding out WHICH
    # three meant scrolling back to a merged list and matching URLs by eye.
    # The standalone tool opens each page and shows its own pixels; this is
    # that, from the per-page scans we have been storing all along and
    # rendering as two numbers.
    if len(pages) > 1:
        cards = []
        for pg in pages:
            sc = pg.get("scan") or {}
            _u = pg.get("url") or "?"
            _role = pg.get("role") or ""
            if pg.get("error"):
                cards.append(
                    f"<details class='vpage'><summary>"
                    f"<span class='vb vb--bad'>scan failed</span>"
                    f"<b>{e(_u)}</b><span class='vev'>{e(_role)}</span>"
                    f"</summary><div class='vbody'><div class='vev'>"
                    f"{e(pg['error'])}</div></div></details>")
                continue
            _pre = sc.get("pre_consent") or []
            _rej = sc.get("post_reject") or []
            _real = [h for h in _pre
                     if str(h.get("severity") or "").lower() not in
                     ("info", "informational")]
            _kind = "bad" if _real else ("warn" if _pre else "ok")
            _lbl = (f"{len(_real)} before consent" if _real
                    else ("nothing before consent" if sc.get("mode") == "full"
                          else "not tested"))
            body = _trackers(_pre) if _pre else (
                "<div class='vev' style='padding:4px 0'>No known ad or "
                "analytics endpoint was contacted before consent on this "
                "page.</div>")
            if _rej:
                body += ("<div class='csec'><h2>After reject</h2></div>"
                         + _trackers(_rej))
            cards.append(
                f"<details class='vpage'><summary>"
                f"<span class='vb vb--{_kind}'>{e(_lbl)}</span>"
                f"<b>{e(_u)}</b>"
                + (f"<span class='vev'>{e(_role)}</span>" if _role else "")
                + (f"<span class='vsrc'>{e(sc.get('mode') or '?')}</span>")
                + f"</summary><div class='vbody'>{body}</div></details>")
        parts.append(_sec(
            "Pages scanned",
            "".join(cards),
            "A conversion page is where conversion pixels actually fire, so "
            "it is the page most likely to carry an ungated one. Open one to "
            "see what fired on it.",
            fold=True, count=f"{len(pages)} pages"))

    # ------------------------------------------------------------ opt-out
    if scan.get("optout_link"):
        parts.append(_sec(
            "Opt-out link",
            f"<div class='card'>Matched: <b>{e(scan['optout_link'])}</b></div>",
            "Presence only — whether the link actually works is a human "
            "check.", tip="optout"))

    return _shell(f"Consent — {client}", "".join(parts),
                  heading="Consent scan", crumbs=crumbs)
