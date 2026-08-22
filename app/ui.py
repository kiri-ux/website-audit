"""
Operator UI — dashboard and live job status.

Server-rendered HTML, no build step. For an internal tool that is the right
trade: zero frontend toolchain, and the dev team can change it without a
bundler. The finished report itself is rendered by engine/report.py.
"""
from __future__ import annotations
import html as _h
import os
import time as _time

from .config import cfg
from . import version

# How long a run may go without a progress update before the page stops
# pretending it is still working. Generous on purpose: the judgment layer can sit
# quiet for a while between steps, and calling a live run dead is a worse error
# than taking a few extra minutes to notice a dead one.
STALE_AFTER_S = int(os.getenv("STALE_AFTER_S", "600"))

CSS = """
/*
 * adtini design system.
 *
 * This tool is going to live inside adtini, so it should not arrive looking
 * like a different product bolted on. Everything here is read off the
 * workflow and forecast screens: the navy rail, the navy table header with
 * white type, soft pastel status pills with dark text, fully-rounded action
 * buttons in gold / orange / navy, and a pale blue-grey page behind white
 * cards.
 *
 * Two deliberate departures. Severity keeps its ordinal blue ramp, because a
 * ranked scale must not be recolored into adtini's categorical pastels — the
 * ordering is the information. And the score ring keeps one hue, for the same
 * reason it always has: length carries magnitude.
 */
:root{
 --navy:#12356b; --navy-2:#0e2a56; --navy-line:#1d4a8a;
 --blue:#1668c1; --blue-dk:#12539c;
 --gold:#f0b429; --gold-dk:#d99e17;
 --orange:#e2691a;
 --plane:#f4f6f9; --surface:#ffffff; --line:#dfe4ec; --line-2:#eceff4;
 --ink:#1b2733; --ink2:#48566b; --muted:#7d8a9c; --track:#e8ecf2;
 --seq:#1668c1;
 --good:#1a7f4b; --warning:#b7791f; --serious:#c05621; --critical:#c53030;
 --pill-green:#d4ecd9; --pill-green-ink:#1a6b3c;
 --pill-blue:#d3e5f7; --pill-blue-ink:#12539c;
 --pill-pink:#fad4d4; --pill-pink-ink:#9b2c2c;
 --pill-purple:#e8d5f2; --pill-purple-ink:#6b2f8f;
 --pill-grey:#e6eaf0; --pill-grey-ink:#48566b;
 --rail:64px;
}
*{box-sizing:border-box}
/* Roboto, the same face adtini uses, and NOT a stack that quietly falls
   through to the system font — the two look similar enough at a glance that a
   fallback would go unnoticed and read as a different product up close. */
body{margin:0;background:var(--plane);color:var(--ink);
 font:15px/1.55 Roboto,"Helvetica Neue",Arial,sans-serif;
 -webkit-font-smoothing:antialiased}

/* ---- chrome: rail, top bar, breadcrumb ---- */
.rail{position:fixed;left:0;top:0;bottom:0;width:var(--rail);background:var(--navy);
 display:flex;flex-direction:column;align-items:center;padding:16px 0;gap:8px;z-index:20}
.rail a,.rail span{width:40px;height:40px;border-radius:6px;display:flex;
 align-items:center;justify-content:center;color:#93aed2;font-size:19px;
 text-decoration:none}
.rail a:hover{background:rgba(255,255,255,.08);text-decoration:none}
.rail .on{background:var(--gold);color:var(--navy-2)}
.rail .sp{flex:1}
.topbar{position:sticky;top:0;z-index:15;background:var(--surface);
 border-bottom:1px solid var(--line);height:60px;display:flex;align-items:center;
 gap:18px;padding:0 30px;margin-left:var(--rail)}
.topbar .burger{color:var(--ink2);font-size:20px;line-height:1}
.topbar h1{font-size:22px;font-weight:500;margin:0;letter-spacing:-.01em;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.topbar .right{margin-left:auto;display:flex;align-items:center;gap:16px;
 font-size:14px;color:var(--ink2)}
.crumb{margin-left:var(--rail);padding:14px 30px 0;font-size:12.5px;color:var(--muted)}
.crumb a{color:var(--muted);text-decoration:underline}
.crumb a:hover{color:var(--blue)}
/* Full width, the way adtini runs. A 1180px column inside a 2500px window
   rendered this at half scale next to the app it is meant to sit inside. */
.wrap{margin-left:var(--rail);padding:18px 30px 70px}

h2{font-size:13px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
 margin:26px 0 10px;font-weight:700}
h3{font-size:16px;margin:0 0 8px;font-weight:600}
.sub{color:var(--ink2);font-size:13.5px}
.sm{font-size:13px}
a{color:var(--blue);text-decoration:none}
a:hover{text-decoration:underline}
code{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--ink2)}

/* ---- cards ---- */
.card{background:var(--surface);border:1px solid var(--line);border-radius:6px;
 padding:22px 26px}

/* ---- forms ---- */
form#auditform{display:grid;grid-template-columns:2fr 1.4fr 1fr .7fr auto;
 gap:10px;align-items:end}
label{display:block;font-size:12px;color:var(--ink2);margin-bottom:4px;font-weight:600}
input,select{width:100%;padding:10px 13px;border:1px solid var(--line);border-radius:4px;
 background:var(--surface);color:var(--ink);font:inherit;font-size:14.5px}
input:focus,select:focus{outline:none;border-color:var(--blue);
 box-shadow:0 0 0 2px rgba(22,104,193,.14)}
button{padding:10px 24px;border:0;border-radius:20px;background:var(--blue);color:#fff;
 font:inherit;font-weight:500;font-size:14px;cursor:pointer;white-space:nowrap}
button:hover{filter:brightness(1.07)}

/* Action buttons, adtini's rounded pill family. */
.btn{display:inline-block;padding:8px 20px;border-radius:20px;background:var(--blue);
 color:#fff;font-size:13.5px;font-weight:500;border:1px solid transparent}
.btn:hover{text-decoration:none;filter:brightness(1.07)}
.btn.ghost{background:var(--surface);color:var(--blue);border-color:var(--line)}
.btn.ghost:hover{border-color:var(--blue);filter:none}
.btn.navy{background:var(--navy);color:#fff}
.btn.gold{background:var(--gold);color:var(--navy-2)}
.btn.orange{background:var(--orange);color:#fff}
.del{background:var(--surface);color:var(--muted);border:1px solid var(--line);
 padding:7px 18px;border-radius:20px;font-size:13.5px;font-weight:500}
.del:hover{color:#fff;background:var(--critical);border-color:var(--critical);filter:none}
.del.wide{margin-top:8px;width:100%}

/* ---- tables: navy header, white body ---- */
table{width:100%;border-collapse:collapse;font-size:14px;margin-top:8px;
 background:var(--surface)}
th{text-align:left;font-weight:500;color:#fff;background:var(--navy);font-size:14px;
 padding:15px 16px;white-space:nowrap}
th:first-child{border-radius:4px 0 0 0} th:last-child{border-radius:0 4px 0 0}
td{padding:15px 16px;border-bottom:1px solid var(--line-2)}
tr:hover td{background:#f8fafc}
td.num{text-align:right;font-variant-numeric:tabular-nums}
table.sub{margin-top:8px;font-size:12px;border:1px solid var(--line);border-radius:4px}
table.sub td{padding:7px 9px}
td.hw{color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums}

/* ---- pills ---- */
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:500;
 padding:5px 15px;border-radius:20px;background:var(--pill-grey);
 color:var(--pill-grey-ink);border:0;white-space:nowrap}
.chip b{width:6px;height:6px;border-radius:50%;display:inline-block}
.chip.ready{background:var(--pill-green);color:var(--pill-green-ink)}
.chip.run{background:var(--pill-blue);color:var(--pill-blue-ink)}
.chip.stop{background:var(--pill-pink);color:var(--pill-pink-ink)}
.chip.hold{background:var(--pill-purple);color:var(--pill-purple-ink)}
.chip.build{background:var(--navy);color:#fff}

.vrow{display:flex;gap:9px;align-items:baseline;margin-top:6px;flex-wrap:wrap}
.vpill{display:inline-flex;align-items:center;gap:7px;font-size:12.5px;font-weight:500;
 padding:5px 14px;border-radius:20px;white-space:nowrap}
.vpill b{font-size:11px;line-height:1}
.vpill.good{background:var(--pill-green);color:var(--pill-green-ink)}
.vpill.warn{background:#fbecc8;color:#8a5d05}
.vpill.bad{background:var(--pill-pink);color:var(--pill-pink-ink)}
.vdet{font-size:13.5px;color:var(--ink2)}

/* ---- stat strip ---- */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;
 margin-top:14px}
.stat{background:var(--surface);border:1px solid var(--line);border-radius:6px;
 padding:16px 18px}
.stat .n{font-size:26px;font-weight:700;letter-spacing:-.02em;
 font-variant-numeric:tabular-nums;line-height:1.15}
.stat .k{font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;
 color:var(--muted);margin-top:2px;font-weight:600}
.stat .k b{width:6px;height:6px;border-radius:50%;display:inline-block;
 margin-right:4px;vertical-align:1px}

/* ---- score ring: one hue, length carries magnitude ---- */
.ring{display:block}
.ring text{font:500 15px Roboto,"Helvetica Neue",Arial,sans-serif;fill:var(--ink);
 font-variant-numeric:tabular-nums}
.ring text.sm{font-size:11px;fill:var(--muted);font-weight:500}

/* ---- client rows ---- */
.crow{display:flex;gap:18px;align-items:flex-start;background:var(--surface);
 border:1px solid var(--line);border-radius:6px;padding:18px 22px;margin-bottom:10px}
.crow:hover{border-color:#c7d2e0}
.cscore{flex:none;padding-top:2px}
.cmain{flex:1;min-width:0}
.cname{font-size:16px;font-weight:500;color:var(--blue)}
.curl{margin-top:1px}
.cmeta{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin-top:7px;
 font-size:13.5px;color:var(--ink2)}
.cact{flex:none;display:flex;gap:6px;align-items:center}
.warn{margin-top:8px;font-size:12px;color:var(--ink2);background:#fdf6ec;
 border-left:3px solid var(--gold);border-radius:4px;padding:8px 11px}
.empty{color:var(--muted);padding:24px 0;text-align:center;font-size:13px}

/* ---- disclosure: adtini uses a tab strip; a details row is the same idea ---- */
.hist{margin-top:9px}
.hist summary{cursor:pointer;font-size:13.5px;color:var(--blue);
 list-style:none;display:inline-block;font-weight:600}
.hist summary::-webkit-details-marker{display:none}
.hist summary:before{content:"▸";margin-right:5px}
.hist[open] summary:before{content:"▾";margin-right:5px}

/* ---- progress ---- */
.spin{display:inline-block;width:11px;height:11px;border:2px solid var(--track);
 border-top-color:var(--blue);border-radius:50%;animation:s .8s linear infinite;
 vertical-align:-1px}
@keyframes s{to{transform:rotate(360deg)}}
.bar{height:7px;background:var(--track);border-radius:4px;overflow:hidden;min-width:90px}
.bar>i{display:block;height:100%;background:var(--blue);border-radius:0 4px 4px 0}
.rail-p{position:relative;height:5px;background:var(--track);border-radius:3px;
 margin:18px 0 4px;overflow:hidden}
.rail-p>i{display:block;height:100%;background:var(--blue);border-radius:3px;
 transition:width .4s ease}
.rail-p.indet>i{width:38%;animation:slide 1.5s ease-in-out infinite}
@keyframes slide{0%{margin-left:-38%}100%{margin-left:100%}}
.steps{display:flex;gap:0;margin:20px 0 8px}
.steps div{flex:1;padding:8px 11px;font-size:12px;border-top:3px solid var(--track);
 color:var(--muted)}
.steps div.on{border-top-color:var(--gold);color:var(--ink);font-weight:600}
.steps div.done{border-top-color:var(--blue);color:var(--ink2)}
.marks{display:flex;justify-content:space-between;font-size:10.5px;color:var(--muted);
 letter-spacing:.03em}
.marks span.on{color:var(--ink);font-weight:700}
.marks span.done{color:var(--ink2)}
"""

from .brand import HEAD_TAGS as HEAD

STATUS_COLOR = {"ready": "var(--good)", "failed": "var(--critical)",
                "queued": "var(--muted)", "crawling": "var(--warning)",
                "checking": "var(--warning)", "scoring": "var(--warning)",
                "needs_capture": "var(--serious)"}

# adtini states are pastel pills with dark text, not a dot beside grey text.
STATUS_PILL = {"ready": "ready", "failed": "stop", "queued": "",
               "crawling": "run", "checking": "run", "scoring": "run",
               "needs_capture": "hold"}


def e(x):
    return _h.escape(str(x if x is not None else ""))


def _ring(score, size=44, stroke=5):
    """
    Score as a donut. Same encoding decision as the PDF gauge: length carries
    magnitude, one hue only. A None score draws an empty dashed ring and a dash
    — never a full ring at zero, which would read as "scored zero".
    """
    import math
    r = (size - stroke) / 2
    circ = 2 * math.pi * r
    c = size / 2
    if score is None:
        return (f"<svg class='ring' width='{size}' height='{size}' "
                f"viewBox='0 0 {size} {size}' role='img' aria-label='not scored'>"
                f"<circle cx='{c}' cy='{c}' r='{r}' fill='none' stroke='var(--line)' "
                f"stroke-width='{stroke}' stroke-dasharray='3 3'/>"
                f"<text class='sm' x='{c}' y='{c}' text-anchor='middle' "
                f"dominant-baseline='central'>—</text></svg>")
    off = circ * (1 - max(0.0, min(1.0, score / 100.0)))
    return (f"<svg class='ring' width='{size}' height='{size}' "
            f"viewBox='0 0 {size} {size}' role='img' aria-label='score {score} of 100'>"
            f"<circle cx='{c}' cy='{c}' r='{r}' fill='none' stroke='var(--track)' "
            f"stroke-width='{stroke}'/>"
            f"<circle cx='{c}' cy='{c}' r='{r}' fill='none' stroke='var(--seq)' "
            f"stroke-width='{stroke}' stroke-linecap='round' "
            f"stroke-dasharray='{circ:.2f}' stroke-dashoffset='{off:.2f}' "
            f"transform='rotate(-90 {c} {c})'/>"
            f"<text x='{c}' y='{c}' text-anchor='middle' "
            f"dominant-baseline='central'>{score}</text></svg>")


def _stat(n, label, dot=None):
    d = f"<b style='background:{dot}'></b>" if dot else ""
    return (f"<div class='stat'><div class='n'>{e(n)}</div>"
            f"<div class='k'>{d}{e(label)}</div></div>")


def _icon(path: str, size: int = 21) -> str:
    return (f"<svg width='{size}' height='{size}' viewBox='0 0 24 24' "
            f"fill='none' stroke='currentColor' stroke-width='1.9' "
            f"stroke-linecap='round' stroke-linejoin='round' "
            f"aria-hidden='true'>{path}</svg>")


# Inline SVG rather than Unicode glyphs. The glyph version rendered at wildly
# different sizes depending on which font happened to carry each codepoint —
# one icon came out full-size and the next as a 6px speck. A path is a path.
RAIL = (
    "<nav class='rail' aria-label='sections'>"
    "<a href='/' class='on' title='Audits'>"
    + _icon("<rect x='3' y='3' width='18' height='18' rx='2'/>"
            "<path d='M3 9h18M9 21V9'/>") +
    "</a>"
    "<a href='/visibility' title='AI visibility'>"
    + _icon("<circle cx='12' cy='12' r='9'/><path d='M12 3a9 9 0 0 1 0 18z'/>") +
    "</a>"
    "<span class='sp'></span>"
    "<span title='settings'>"
    + _icon("<circle cx='12' cy='12' r='3'/>"
            "<path d='M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 "
            "2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 "
            "2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06"
            ".06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 "
            "0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 "
            "0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 "
            "4.6 1.65 1.65 0 0 0 10 3.09V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 "
            "1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A"
            "1.65 1.65 0 0 0 19.4 9v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 "
            "4h-.09a1.65 1.65 0 0 0-1.51 1z'/>", 19) +
    "</span>"
    "</nav>")


def _shell(title, body, refresh=None, heading=None, crumbs=None):
    """
    adtini chrome: fixed navy rail, white top bar, breadcrumb, content.

    The rail is decorative here — this app has two screens — but it is what
    makes the tool read as part of adtini rather than a separate site opened
    in a new tab, which is the whole point of the exercise.
    """
    r = f"<meta http-equiv='refresh' content='{refresh}'>" if refresh else ""
    trail = ""
    if crumbs:
        parts = []
        for label, href in crumbs:
            parts.append(f"<a href='{href}'>{e(label)}</a>" if href
                         else f"<span>{e(label)}</span>")
        trail = f"<div class='crumb'>{' &rsaquo; '.join(parts)}</div>"
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>{r}"
            f"{HEAD}"
            f"<link rel='preconnect' href='https://fonts.googleapis.com'>"
            f"<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
            f"<link rel='stylesheet' href='https://fonts.googleapis.com/css2?"
            f"family=Roboto:wght@400;500;600;700&display=swap'>"
            f"<title>{e(title)}</title><style>{CSS}</style></head>"
            f"<body class='viz-root'>{RAIL}"
            f"<header class='topbar'><span class='burger'>\u2630</span>"
            f"<h1>{e(heading or title)}</h1>"
            f"<div class='right'><span>Vici Media</span>"
            f"<span title='notifications'>\u25cf</span></div></header>"
            f"{trail}<div class='wrap'>{body}</div></body></html>")


def _fmt_when(ts):
    import time as _t
    if not ts:
        return "—"
    return _t.strftime("%m/%d/%Y %H:%M", _t.localtime(ts))


def _del_form(audit_id, label="Delete", confirm="Delete this audit?"):
    return (f"<form method='post' action='/audits/{audit_id}/delete' "
            f"style='display:inline' onsubmit=\"return confirm('{confirm}')\">"
            f"<button class='del' type='submit'>{label}</button></form>")


def dashboard_html(audits, principal, queue_depth, caps=None):
    """
    Grouped by CLIENT, not one row per run.

    Testing a crawler against a single site produces six rows of the same
    client in an afternoon, which buries every other client in the list. The
    unit of this page is now the client: newest run on the headline row, older
    runs folded underneath, and a one-click way to drop the rest.
    """
    from . import db
    groups = db.group_by_client(audits)

    import json as _json

    def _settings(a):
        """
        The intake that is NOT recoverable from the crawl: vertical, markets,
        conversion, page cap, and any hand-picked GA4 / Search Console
        property. Someone re-auditing a client was reading these off an old
        report and retyping them, which is how a re-run silently loses the
        property you picked last month.
        """
        o = a.get("options") or {}
        for _ in range(2):
            if isinstance(o, str):
                try: o = _json.loads(o)
                except Exception: o = {}
        return {
            "target_url": a.get("target_url") or "",
            "client_name": a.get("client_name") or "",
            "vertical": a.get("vertical") or "",
            "max_pages": o.get("max_pages") or 150,
            "primary_markets": o.get("primary_markets") or "",
            "primary_conversion": o.get("primary_conversion") or "",
            "partner": o.get("partner") or "",
            "gsc_property": o.get("gsc_property") or "",
            "ga4_property_id": o.get("ga4_property_id") or "",
            "render_js": bool(o.get("render_js")),
            "browser_ua": bool(o.get("user_agent")),
        }

    def _settings_panel(a):
        st = _settings(a)
        shown = [("Vertical", st["vertical"] or "generic"),
                 ("Max pages", st["max_pages"]),
                 ("Primary markets", st["primary_markets"] or "—"),
                 ("Primary conversion", st["primary_conversion"] or "—"),
                 ("Prepared by", st["partner"] or "—"),
                 ("Search Console property", st["gsc_property"] or "auto"),
                 ("GA4 property", st["ga4_property_id"] or "auto"),
                 ("Render JavaScript", "yes" if st["render_js"] else "no"),
                 ("Browser user-agent", "yes" if st["browser_ua"] else "no")]
        rows = "".join(f"<tr><td class='hw'>{e(k)}</td><td>{e(v)}</td></tr>"
                       for k, v in shown)
        blob = _h.escape(_json.dumps(st), quote=True)
        return (f"<details class='hist'><summary>Settings used</summary>"
                f"<table class='sub'>{rows}</table>"
                f"<button class='btn ghost' type='button' style='margin-top:9px;"
                f"width:100%' data-prefill=\"{blob}\" onclick='prefill(this)'>"
                f"Start a new audit with these settings</button></details>")

    cards = []
    for g in groups:
        a = g["latest"]
        col = STATUS_COLOR.get(a["status"], "var(--muted)")
        spin = "<span class='spin'></span> " if a["status"] in (
            "crawling", "checking", "scoring") else ""
        hist = ""
        if g["history"]:
            rows = "".join(
                f"<tr><td class='hw'>{_fmt_when(h.get('created_at'))}</td>"
                f"<td><a href='/audits/{h['id']}'>{e(h['status'])}</a></td>"
                f"<td class='num'>{h['overall_score'] if h['overall_score'] is not None else '—'}</td>"
                f"<td class='num'>{e(h.get('coverage') or '—')}</td>"
                f"<td class='num'>{h.get('pages_crawled') or '—'}</td>"
                f"<td style='text-align:right'>"
                f"<form method='post' action='/audits/{h['id']}/rerun' "
                f"style='display:inline;margin-right:6px'>"
                f"<button class='del' type='submit'>Re-run</button></form>"
                f"{_del_form(h['id'], 'Delete')}</td></tr>"
                for h in g["history"])
            hist = (
                f"<details class='hist'><summary>{len(g['history'])} earlier "
                f"run{'s' if len(g['history']) != 1 else ''}</summary>"
                f"<table class='sub'>{rows}</table>"
                f"<form method='post' action='/clients/{e(g['key'])}/prune' "
                f"onsubmit=\"return confirm('Delete {len(g['history'])} older "
                f"run(s) for {e(g['client'])}? The newest is kept.')\">"
                f"<button class='del wide' type='submit'>Keep newest, delete "
                f"the other {len(g['history'])}</button></form></details>")

        cards.append(
            f"<div class='crow'>"
            f"<div class='cscore'>{_ring(a['overall_score'])}</div>"
            f"<div class='cmain'>"
            f"<a class='cname' href='/audits/{a['id']}'>{e(g['client'])}</a>"
            f"<div class='curl'><code>{e(a['target_url'])[:70]}</code></div>"
            f"<div class='cmeta'>"
            f"<span class='chip {STATUS_PILL.get(a['status'], '')}'>{spin}"
            f"{e(a['status'].replace('_', ' '))}</span>"
            f"<span>{e(a.get('overall_rating') or 'Not Assessed')}</span>"
            f"<span>{e(a.get('coverage') or '—')} checks</span>"
            f"<span>{a.get('pages_crawled') or '—'} pages</span>"
            f"<span>{_fmt_when(a.get('created_at'))}</span>"
            f"</div>"
            + (f"<div class='warn'>⚠ Server crawl blocked. Open the site in "
               f"Chrome, launch <b>Vici Audit Capture</b>, and paste audit id "
               f"<code>{a['id']}</code>.</div>"
               if a["status"] == "needs_capture" else "")
            + _settings_panel(a)
            + hist
            + f"</div>"
            f"<div class='cact'>"
            f"<form method='post' action='/audits/{a['id']}/rerun' "
            f"style='display:inline'>"
            f"<button class='btn ghost' type='submit'>Re-run</button></form>"
            f"<a class='btn' href='/audits/{a['id']}'>Open</a>"
            f"<a class='btn ghost' href='/audits/{a['id']}.pdf' target='_blank' "
            f"rel='noopener'>PDF</a>"
            f"{_del_form(a['id'], 'Delete', 'Delete the newest run for ' + g['client'].replace(chr(39), '') + '?')}"
            f"</div></div>")

    listing = ("".join(cards) if cards else
               "<div class='empty'>No audits yet — submit one above.</div>")

    running = any(a["status"] in ("queued", "crawling", "checking", "scoring")
                  for a in audits)

    # ---- fleet strip -----------------------------------------------------
    # Averaged over SCORED audits only. Counting an unscored audit as zero
    # would drag the average down for the crime of not having finished yet.
    scored = [a["overall_score"] for a in audits if a["overall_score"] is not None]
    n_run = sum(1 for a in audits if a["status"] in
                ("queued", "crawling", "checking", "scoring"))
    n_blocked = sum(1 for a in audits if a["status"] == "needs_capture")
    n_failed = sum(1 for a in audits if a["status"] == "failed")
    stats = "<div class='stats'>" + "".join([
        _stat(len(groups), "clients"),
        _stat(len(audits), "audits"),
        _stat(n_run, "in flight", STATUS_COLOR["crawling"]),
        _stat(n_blocked, "need capture", STATUS_COLOR["needs_capture"]),
        _stat(n_failed, "failed", STATUS_COLOR["failed"]),
        _stat(round(sum(scored) / len(scored)) if scored else "—", "mean score"),
        _stat(queue_depth, "queue depth"),
    ]) + "</div>"

    # CAN THE WORKER ACTUALLY RUN THIS?
    #
    # Every AI platform key lives on the worker; this page is served by the API.
    # Offering a checkbox the worker has no keys for is how you find out by
    # running an audit and reading eight unanswered rows afterwards. The worker
    # publishes what it holds on startup, so the box can say up front which
    # assistants will answer — and disable itself when the answer is none.
    caps = caps or {}
    plats = caps.get("ai_platforms") or []
    _NICE = {"chatgpt": "ChatGPT", "claude": "Claude", "gemini": "Gemini",
             "perplexity": "Perplexity", "ai_overview": "AI Overviews",
             "copilot": "Copilot"}
    if not caps.get("known"):
        AIVIS_ATTR = ""
        AIVIS_NOTE = "(asks each assistant; the worker has not reported its keys)"
    elif plats:
        names = ", ".join(_NICE.get(x, x) for x in plats)
        AIVIS_ATTR = ""
        AIVIS_NOTE = f"({names} &middot; ~2 min &middot; paid per question)"
    else:
        # Disabled rather than merely discouraged. A ticked box that cannot do
        # anything is worse than one that explains why it is greyed out.
        AIVIS_ATTR = "disabled"
        AIVIS_NOTE = ("no AI platform keys on the worker &mdash; set "
                      "OPENAI_API_KEY, ANTHROPIC_API_KEY, PERPLEXITY_API_KEY "
                      "or GEMINI_API_KEY there")

    body = f"""
    <div class='sub'>{e(principal.name)} · mode <code>{e(cfg.mode)}</code>
      <span class='chip build' style='margin-left:6px'>{e(version.label())}</span></div>
    <div style='color:var(--muted);font-size:11.5px;margin-top:4px'>
      {e(version.BUILD_NOTES)}</div>
    {stats}

    <h2>New audit</h2>
    <div class='card'><form method='post' action='/audits' id='auditform'>
      <input type='hidden' name='phases' value='1'>
      <div><label>Target URL</label>
        <input name='target_url' id='turl'
               placeholder='https://www.example.com/' required></div>
      <div><label>Client name</label>
        <input name='client_name' placeholder='Grand Furniture' required></div>
      <div><label>Vertical</label><select name='vertical'>
        <option value=''>generic</option><option value='ecommerce'>ecommerce</option>
        <option value='finance_ymyl'>finance / YMYL</option>
        <option value='local_service'>local service</option></select></div>
      <div><label>Max pages</label><input name='max_pages' type='number' value='150'></div>
      <div><button type='submit'>Run audit</button></div>
    </form>
    <div style='margin-top:12px'>
      <button type='button' class='btn ghost' id='ckbtn'
              onclick='checkAccess()'>Check GA4 / Search Console access</button>
      <!-- Own line, full width. Beside the button it inherited whatever narrow
           column the button sat in, and a sentence like "No property matching
           this site in 1 login(s)" came out one word per line. -->
      <div id='ckout' class='sm'
           style='color:var(--muted);margin-top:8px;line-height:1.6'></div>
    </div>
    <div id='pickers' style='display:none;margin-top:10px;
         grid-template-columns:1fr 1fr;gap:12px'>
      <div>
        <label>Search Console property</label>
        <input id='gscfilter' placeholder='filter…' oninput='filterSel("gsc")'
               style='margin-bottom:4px;font-size:12.5px'>
        <select name='gsc_property' id='gscsel' form='auditform'></select>
      </div>
      <div>
        <label>GA4 property</label>
        <input id='ga4filter' placeholder='filter…' oninput='filterSel("ga4")'
               style='margin-bottom:4px;font-size:12.5px'>
        <select name='ga4_property_id' id='ga4sel' form='auditform'></select>
      </div>
    </div>

    <div style='margin-top:14px;display:grid;
                grid-template-columns:1fr 1fr;gap:10px'>
      <div><label>Primary markets</label>
        <input name='primary_markets' form='auditform'
               placeholder='Roanoke VA, Knoxville TN'></div>
      <div><label>Primary conversion</label>
        <input name='primary_conversion' form='auditform'
               placeholder='Book an appointment'></div>
    </div>

    <div style='margin-top:14px'>
      <label>Prepared by</label>
      <input name='partner' form='auditform'
             placeholder='Vici Media'>
      <div style='font-size:12px;color:var(--muted);margin-top:4px'>
        Name on the report cover. Leave blank to use the default.</div>
    </div>
    <div style='margin-top:12px;display:flex;gap:20px;font-size:12.5px;color:var(--ink2)'>
      <label style='display:flex;gap:6px;align-items:center;margin:0;font-weight:400'>
        <input type='checkbox' name='browser_ua' value='1' form='auditform'
               style='width:auto'> Use a browser user-agent
        <span style='color:var(--muted)'>(if the site blocks bots)</span></label>
      <label style='display:flex;gap:6px;align-items:center;margin:0;font-weight:400'>
        <input type='checkbox' name='render_js' value='1' form='auditform'
               style='width:auto'> Render JavaScript
        <span style='color:var(--muted)'>(slower; for SPA sites)</span></label>
    </div>

    <div style='margin-top:14px;padding-top:12px;border-top:1px solid var(--line)'>
      <div style='font-size:12.5px;font-weight:640;margin-bottom:6px'>
        What to run</div>
      <div style='font-size:12.5px;color:var(--ink2);display:grid;
                  grid-template-columns:1fr 1fr;gap:6px 20px'>
        <label style='display:flex;gap:6px;align-items:center;margin:0;font-weight:400'>
          <input type='checkbox' name='run_judgment' value='1' checked
                 form='auditform' style='width:auto'> E-E-A-T and AI Search
          <span style='color:var(--muted)'>(needs the LLM key)</span></label>
        <label style='display:flex;gap:6px;align-items:center;margin:0;font-weight:400'>
          <input type='checkbox' name='run_collectors' value='1' checked
                 form='auditform' style='width:auto'> Search Console, Analytics,
          off-page</label>
        <label style='display:flex;gap:6px;align-items:center;margin:0;font-weight:400'>
          <input type='checkbox' name='run_screenshots' value='1' checked
                 form='auditform' style='width:auto'> Evidence screenshots
          <span style='color:var(--muted)'>(~30s)</span></label>
        <label style='display:flex;gap:6px;align-items:center;margin:0;font-weight:400'>
          <input type='checkbox' name='run_aivis' value='1' {AIVIS_ATTR}
                 form='auditform' style='width:auto'> AI visibility
          <span style='color:var(--muted)'>{AIVIS_NOTE}</span></label>
        <label style='display:flex;gap:6px;align-items:center;margin:0;font-weight:400'>
          <input type='checkbox' name='reuse_crawl' value='1'
                 form='auditform' style='width:auto'> Reuse the last crawl of
          this URL
          <span style='color:var(--muted)'>(no new requests to their site)</span>
        </label>
      </div>
      <div class='sm' style='color:var(--muted);margin-top:6px'>
        Reusing a crawl re-scores the pages we already have. Sitewide counts
        then describe the site as of that crawl, so use a fresh one to check
        whether a fix has landed.</div>
    </div>
    </div>

    <h2>Clients</h2>{listing}

    <script>
    // Preflight, not a gate. It never blocks submission — a probe that is
    // wrong about GA4 (it scans by name only, for speed) must not stop a real
    // audit from running.
    async function checkAccess() {{
      var u = document.getElementById('turl').value.trim();
      var out = document.getElementById('ckout');
      var btn = document.getElementById('ckbtn');
      if (!u) {{ out.textContent = 'Enter a URL first.'; return; }}
      if (!/^https?:\\/\\//.test(u)) {{ u = 'https://' + u; }}
      btn.disabled = true; out.style.color = 'var(--muted)';
      out.textContent = 'Checking…';
      try {{
        var r = await fetch('/api/access-check?target_url=' + encodeURIComponent(u));
        var d = await r.json();
        if (!r.ok) {{ throw new Error(d.detail || r.status); }}
        // Pills, so the shape of the answer reads before the words do. Three
        // states, three colors: found, ours to fix, and "the quick check
        // could not tell" — which is NOT the same as no.
        function esc(t) {{
          return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;');
        }}
        function pill(name, st) {{
          var cls  = st.ok ? 'good' : (st.partial ? 'warn' : 'bad');
          var mark = st.ok ? '\u2713' : (st.partial ? '?' : '\u2717');
          var text = st.ok
            ? (st.name ? st.name + ' \u00b7 ' + st.property : st.property)
              + ' \u00b7 via ' + st.login
            : (st.partial ? 'no quick match \u2014 the audit looks wider'
                          : (st.detail || 'not found'));
          return '<div class="vrow"><span class="vpill ' + cls + '"><b>' + mark +
                 '</b>' + esc(name) + '</span><span class="vdet">' + esc(text) +
                 '</span></div>';
        }}
        out.style.color = '';
        out.innerHTML = pill('Search Console', d.gsc) + pill('GA4', d.ga4);
        loadProperties(d);
      }} catch (e) {{
        out.style.color = 'var(--serious)';
        out.textContent = 'Check failed: ' + e.message;
      }} finally {{ btn.disabled = false; }}
    }}

    // Every property we can see, so a miss is checkable rather than final.
    // The matcher is right most of the time and wrong in ways it cannot know
    // about — a property named nothing like its domain, a client on a
    // subdomain, a GSC entry that is a domain property. When it misses, the
    // question is "what IS in there", and the answer is one click away.
    var ALL = null;
    async function loadProperties(probe) {{
      var box = document.getElementById('pickers');
      box.style.display = 'grid';
      if (!ALL) {{
        try {{ ALL = await (await fetch('/api/properties')).json(); }}
        catch (e) {{ ALL = {{gsc: [], ga4: []}}; }}
      }}
      fill('gsc', ALL.gsc.map(function (r) {{
        return {{v: r.site, t: r.site + '  ·  ' + r.login}};
      }}), probe.gsc.ok ? probe.gsc.property : null);
      fill('ga4', ALL.ga4.map(function (r) {{
        return {{v: r.id, t: r.name + '  ·  ' + r.id + '  ·  ' + r.login}};
      }}), probe.ga4.ok ? probe.ga4.property : null);
    }}

    function fill(which, rows, selected) {{
      var sel = document.getElementById(which + 'sel');
      sel.innerHTML = '';
      var none = document.createElement('option');
      none.value = '';
      none.textContent = selected ? 'Matched automatically — leave as is'
                                  : 'No match — pick one, or leave blank';
      sel.appendChild(none);
      sel._rows = rows;
      rows.forEach(function (r) {{
        var o = document.createElement('option');
        o.value = r.v; o.textContent = r.t;
        if (selected && r.v === selected) {{ o.selected = true; }}
        sel.appendChild(o);
      }});
      // A matched property is preselected but NOT forced: leaving the blank
      // option is the same as before this existed, and the audit re-matches.
      if (selected) {{ sel.value = selected; }}
    }}

    // Re-audit a client without retyping their intake. The button carries the
    // whole settings object, so nothing is read off an old report by eye.
    function prefill(btn) {{
      var st = JSON.parse(btn.dataset.prefill);
      var f = document.getElementById('auditform');
      ['target_url', 'client_name', 'vertical', 'max_pages',
       'primary_markets', 'primary_conversion', 'partner'].forEach(function (k) {{
        var el = f.querySelector('[name=' + k + ']')
              || document.querySelector('[name=' + k + ']');
        if (el && st[k] !== undefined && st[k] !== '') el.value = st[k];
      }});
      [['render_js', st.render_js], ['browser_ua', st.browser_ua]].forEach(
        function (p) {{
          var el = document.querySelector('[name=' + p[0] + ']');
          if (el) el.checked = !!p[1];
        }});
      // The chosen properties need the dropdowns populated first, so run the
      // access check and apply them when it returns.
      window._pendingProps = {{ gsc: st.gsc_property, ga4: st.ga4_property_id }};
      document.getElementById('turl').scrollIntoView(
        {{ behavior: 'smooth', block: 'center' }});
      document.getElementById('turl').focus();
      if (st.gsc_property || st.ga4_property_id) checkAccess();
    }}

    function filterSel(which) {{
      var q = document.getElementById(which + 'filter').value.toLowerCase();
      var sel = document.getElementById(which + 'sel');
      var keep = sel.value;
      var rows = (sel._rows || []).filter(function (r) {{
        return !q || r.t.toLowerCase().indexOf(q) >= 0;
      }});
      fill(which, rows, keep);
      sel.size = q && rows.length > 1 ? Math.min(8, rows.length + 1) : 0;
    }}
    </script>
    """
    return _shell("Vici Audit Engine", body, refresh=8 if running else None,
                  heading="SEO & AI Search Audit Engine",
                  crumbs=[("Audits", None)])


def audit_html(a):
    """Live status page shown while an audit is still running."""
    import json as _json
    order = ["queued", "crawling", "checking", "scoring", "ready"]
    cur = a["status"]
    idx = order.index(cur) if cur in order else 0
    marks = "".join(
        f"<span class='{'on' if i == idx else ('done' if i < idx else '')}'>{s}</span>"
        for i, s in enumerate(order))

    if cur == "failed":
        inner = (f"<div class='card'><b style='color:var(--critical)'>Audit failed</b>"
                 f"<p class='sub'>{e(a.get('error'))}</p>"
                 f"</div>")
        refresh = None
    elif cur == "needs_capture":
        # One button, no copying. The extension's content script finds
        # #vici-capture, reads the id and target off it, and wires the button
        # straight to the worker — so the operator never moves an audit id
        # between two tabs by hand. If the extension is not installed the
        # button stays hidden and the manual instructions are what is left.
        inner = (
            f"<div class='card' id='vici-capture' "
            f"data-audit-id='{e(a['id'])}' data-target='{e(a['target_url'])}'>"
            f"<b style='color:var(--serious)'>Server crawl blocked</b>"
            f"<p class='sub'>{e(a.get('crawl_note') or a.get('progress'))}</p>"
            f"<p class='sub'>Nothing has been reported as a defect — a blocked "
            f"crawl is a handoff, not a result. Open "
            f"<a href='{e(a['target_url'])}' target='_blank' rel='noopener'>"
            f"{e(a['target_url'])}</a> in a tab, then start the capture.</p>"
            f"<p><button id='vici-capture-go' class='btn' type='button'>"
            f"Start capture with the Chrome extension</button></p>"
            f"<div id='vici-capture-manual'>"
            f"<p class='sub'><b>Vici Audit Capture is not installed in this "
            f"browser.</b> It is an unpacked Chrome extension, so it lives in a "
            f"folder rather than the Web Store — and it disappears if that "
            f"folder moves or is deleted, which is the usual reason it is "
            f"suddenly gone.</p>"
            f"<ol class='sub' style='margin:8px 0 0 18px;line-height:1.75'>"
            f"<li><a href='/extension.zip'>Download the extension</a> and "
            f"unzip it somewhere permanent — not Downloads, which gets "
            f"cleared.</li>"
            f"<li>Open <code>chrome://extensions</code> "
            f"<button class='del' type='button' onclick=\"navigator.clipboard"
            f".writeText('chrome://extensions');this.textContent='copied'\">"
            f"copy</button> — Chrome will not let a page link there.</li>"
            f"<li>Turn on <b>Developer mode</b>, top right.</li>"
            f"<li><b>Load unpacked</b>, and choose the folder you unzipped. "
            f"You should see <b>Vici Audit Capture 1.1.0</b>.</li>"
            f"<li>Reload this page — the Start capture button appears once "
            f"the extension is detected.</li></ol>"
            f"<p class='sub' style='margin-top:10px'>Or drive it by hand: open "
            f"the site, click the extension, and paste audit id "
            f"<code>{e(a['id'])}</code> "
            f"<button class='del' type='button' onclick=\"navigator.clipboard"
            f".writeText('{e(a['id'])}');this.textContent='copied'\">copy</button>"
            f"</p></div></div>"
            f"<script>"
            f"(function(){{var el=document.getElementById('vici-capture');"
            f"var go=document.getElementById('vici-capture-go');"
            f"go.style.display='none';"
            f"setTimeout(function(){{"
            f"  if(el.dataset.extension==='present'){{"
            f"    go.style.display='inline-block';"
            f"    document.getElementById('vici-capture-manual')"
            f"      .style.display='none';}}}},300);}})();"
            f"</script>")
        refresh = None
    else:
        # Determinate where we can be, honest where we can't. Page counts only
        # exist during the crawl; once checks start there is no meaningful
        # fraction to show, so the rail goes indeterminate rather than
        # inventing a percentage that creeps.
        # Options have been double-encoded by a caller before now, so a decode
        # can legitimately hand back a string. Anything that isn't a dict means
        # "no page target" — the rail goes indeterminate, which is correct.
        opts = a.get("options") or {}
        for _ in range(2):
            if isinstance(opts, str):
                try:
                    opts = _json.loads(opts)
                except Exception:
                    opts = {}
        if not isinstance(opts, dict):
            opts = {}
        done = a.get("pages_crawled") or 0
        target = int(opts.get("max_pages") or 0)
        if cur == "crawling" and target and done:
            pct = max(3, min(97, round(100 * done / target)))
            rail = (f"<div class='rail-p'><i style='width:{pct}%'></i></div>"
                    f"<div class='marks' style='margin-bottom:14px'>"
                    f"<span class='on'>{done} of up to {target} pages</span>"
                    f"<span>{pct}%</span></div>")
        else:
            rail = "<div class='rail-p indet'><i></i></div>"
        # Is anything still working on this?
        #
        # The worker stamps heartbeat_at on every step. If that stopped moving
        # several minutes ago, the run is not slow — its container is gone, and
        # the honest thing is to say so and offer the rerun rather than spin a
        # spinner at someone indefinitely. Runs from before this build have no
        # heartbeat at all, so a missing value means "unknown", never "dead".
        hb = a.get("heartbeat_at")
        stale = bool(hb) and (_time.time() - float(hb)) > STALE_AFTER_S
        if stale:
            mins = int((_time.time() - float(hb)) // 60)
            inner = (rail + f"<div class='marks'>{marks}</div>"
                     f"<div class='card' style='margin-top:16px'>"
                     f"<b>This run has stopped responding.</b>"
                     f"<p class='sub'>The last progress update was {mins} minutes "
                     f"ago, at &ldquo;{e(a.get('progress') or cur)}&rdquo;. That "
                     f"usually means the worker was restarted mid-run — a deploy, "
                     f"or the instance being recycled — rather than anything wrong "
                     f"with the site. Rerunning picks up the stored pages, so it "
                     f"will not go back out to the client's server.</p>"
                     f"<form method='post' action='/audits/{e(a['id'])}/rerun' "
                     f"style='margin-top:12px'>"
                     f"<input type='hidden' name='reuse_crawl' value='1'>"
                     f"<button class='btn' type='submit'>Rerun from the stored "
                     f"pages</button></form></div>")
            refresh = None
        else:
            inner = (rail + f"<div class='marks'>{marks}</div>"
                     f"<div class='card' style='margin-top:16px'>"
                     f"<span class='spin'></span> <b>{e(a.get('progress') or cur)}</b>"
                     f"<p class='sub'>This page refreshes automatically. A full crawl "
                     f"of 150 pages typically takes 2–5 minutes.</p></div>")
            # Six seconds, not four. Every refresh is a full page render and a
            # fresh database connection, and the phase this page is most often
            # watching is now the longest one in the run.
            refresh = 6

    body = (f"<div class='sub'><code>{e(a['target_url'])}</code> · "
            f"audit <code>{e(a['id'])}</code></div>{inner}")
    return _shell(f"{a['client_name']} — running", body, refresh=refresh,
                  heading=a["client_name"],
                  crumbs=[("Audits", "/"), (a["client_name"], None)])
