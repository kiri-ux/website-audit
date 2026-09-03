"""
Operator UI — dashboard and live job status.

Server-rendered HTML, no build step. For an internal tool that is the right
trade: zero frontend toolchain, and the dev team can change it without a
bundler. The finished report itself is rendered by engine/report.py.
"""
from __future__ import annotations
import html as _h
import json as _json
import os
import time as _time

from .config import cfg
from . import version
from engine.report import extension_link as _ext_link

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
 /* SAMPLED OFF AN ADTINI SCREENSHOT, NOT MATCHED BY EYE.
    Every value below is the modal pixel of the region it names. Eyeballing
    got --rail to #12356b and --gold to #f0b429, both close enough to look
    right in isolation and both visibly wrong the moment the two apps sit
    side by side in adjacent tabs, which is the only way anyone sees them. */
 --navy:#0c284c; --navy-2:#081d38; --navy-line:#1d4a8a;
 --rail-bg:#1c5ba6;                      /* the left menu, exactly */
 --blue:#1668c1; --blue-dk:#12539c;
 --gold:#e8ac3e; --gold-dk:#cf9421;
 --orange:#e2691a;
 --plane:#f1f2f4; --surface:#ffffff; --line:#dfe4ec; --line-2:#eceff4;
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
/* NOT ROBOTO. Measured, not guessed.
   "Roboto, the same face adtini uses" was an assumption written down as a
   comment and then trusted for six builds. Setting adtini's own heading next
   to candidates at matched cap height settles it: the ink box of "Workflow"
   has an aspect ratio of 6.11 in adtini, 6.09 in Arial, and 5.44 in Roboto.
   Roboto is visibly narrower — that IS the mismatch, and it is why loading a
   webfont made it worse rather than better.
   So: no webfont at all. The system stack resolves to the same face adtini
   gets on the same machine, which is match by construction rather than by
   my picking a lookalike off Google Fonts. If adtini turns out to name a
   licensed face, this one line is where it goes. */
body{margin:0;background:var(--plane);color:var(--ink);
 font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,
 "Helvetica Neue",sans-serif;
 -webkit-font-smoothing:antialiased}

/* ---- chrome: rail, top bar, breadcrumb ---- */
.rail{position:fixed;left:0;top:0;bottom:0;width:var(--rail);background:var(--rail-bg);
 display:flex;flex-direction:column;align-items:center;padding:16px 0;gap:8px;z-index:20}
.rail a,.rail span{width:40px;height:40px;border-radius:12px;display:flex;
 align-items:center;justify-content:center;color:#93aed2;font-size:19px;
 text-decoration:none}
.rail a:hover{background:rgba(255,255,255,.08);text-decoration:none}
.rail .on{background:var(--gold);color:var(--navy)}
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
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;
 padding:22px 26px;
 transition:box-shadow .15s ease, border-color .15s ease}
.card:hover{border-color:#cfdaea;box-shadow:0 4px 16px -10px rgba(18,53,107,.3)}

/* THE TOP BAR IS WHITE, because adtini's is white.
   It was a navy gradient for one build — asked for, and it did look good on
   its own. It also made this the one page in the suite whose header did not
   match the others, which is the opposite of the point: the rail and the bar
   are the two things a person recognizes before they read a word.
   The gradient did not go away, it moved. It is a 2px seam under the bar and
   the rule under every heading, where it reads as finish rather than as a
   different product. */
.topbar{background:var(--surface);border-bottom:1px solid var(--line);
 box-shadow:0 2px 0 -1px rgba(0,0,0,.03)}
.topbar:after{content:'';position:absolute;left:0;right:0;bottom:-2px;height:2px;
 background:linear-gradient(90deg,var(--rail-bg) 0%,var(--blue) 38%,
 rgba(28,91,166,0) 88%)}
.topbar h1{color:#1e1e1e;font-weight:700;letter-spacing:-.015em}
.topbar .burger{color:#5c6673}
.topbar .right{color:var(--ink2)}
.bstamp{font:11.5px ui-monospace,SFMono-Regular,Menlo,monospace;
 color:var(--muted);letter-spacing:.01em;white-space:nowrap;opacity:.75}
.bstamp:hover{opacity:1}

/* ---- hover help ----
   Every one of these lines was true and none of them was needed twice. On
   screen together they turned a nine-field form into a wall of grey prose,
   and the fields themselves stopped being findable. They are on an `i` now:
   there when someone wants them, gone when they don't. */
.tip{display:inline-flex;align-items:center;justify-content:center;
 width:14px;height:14px;border-radius:50%;border:1px solid var(--line);
 color:var(--muted);font-size:10px;font-weight:700;font-style:normal;
 margin-left:6px;cursor:help;position:relative;vertical-align:1px;
 background:var(--surface);letter-spacing:0;text-transform:none}
.tip:hover{border-color:var(--blue);color:var(--blue)}
/* THE BUBBLE LEFT THE MARKER. HERE IS WHY IT HAD TO.
   ---------------------------------------------------
   It was an ::after on .tip, absolutely positioned, 270px wide — and half
   the markers on the consent page sit inside `overflow-x:auto` table
   wrappers. Two things went wrong there, both invisible in isolation:

     1. FLICKER. The 270px bubble overflowed the scroll container, which
        grew a horizontal scrollbar, which reflowed the row, which moved the
        marker out from under the pointer, which hid the bubble, which
        removed the scrollbar, which moved the marker back. The cursor
        flipped between arrow and question mark several times a second. It
        was not a hover that failed to work; it was a hover working twice a
        frame.
     2. CLIPPING. `overflow-x:auto` makes overflow-y a scroll container too,
        so a bubble rendered ABOVE a table header was cut off at the top of
        the wrapper — the one place a header tooltip has to appear.

   No amount of z-index fixes either: an element cannot escape an ancestor
   that scrolls. So there is exactly one bubble, it lives on <body>, it is
   position:fixed, and JS moves it. It cannot reflow anything, cannot be
   clipped by anything, and cannot be hovered — which is what kills the loop. */
#tipbox{position:fixed;z-index:200;max-width:300px;padding:9px 12px;
 border-radius:12px;background:var(--navy);color:#fff;font-size:12.5px;
 font-weight:400;line-height:1.5;text-align:left;pointer-events:none;
 opacity:0;transition:opacity .1s;box-shadow:0 6px 20px rgba(11,29,51,.22);
 letter-spacing:0;text-transform:none;font-style:normal}
#tipbox.on{opacity:1}

.pfilter{width:100%;margin:0 0 5px;padding:6px 10px;font-size:13px;
 border:1px solid var(--line);border-radius:8px;background:#fff;
 color:var(--ink);display:none}
.pfilter:focus{outline:2px solid var(--blue);outline-offset:1px}

/* ---- report tabs ---- */
.ctabs{display:flex;gap:2px;border-bottom:1px solid var(--line);margin:0 0 4px;
 flex-wrap:wrap}
.ctab{padding:8px 15px;font-size:13.5px;font-weight:500;color:var(--ink2);
 border:1px solid transparent;border-bottom:0;border-radius:8px 8px 0 0;
 position:relative;top:1px}
.ctab:hover{text-decoration:none;color:var(--blue);background:var(--surface)}
.ctab.on{background:#fff;border-color:var(--line);color:var(--ink);
 font-weight:600}
.ctab--file{display:inline-flex;align-items:center;gap:6px}
.ctab-dl{opacity:.5;flex:none}
.ctab--file:hover .ctab-dl{opacity:1}
.csibs{display:flex;gap:8px;flex-wrap:wrap;align-items:baseline;
 font-size:12.5px;color:var(--muted);margin:8px 0 14px}
.csibs > span{margin-right:2px}
.csibs a{color:var(--ink2);border:1px solid var(--line);border-radius:14px;
 padding:2px 10px;background:var(--surface)}
.csibs a:hover{text-decoration:none;border-color:var(--blue);color:var(--blue)}
.csibs .k{color:var(--muted)}

/* ---- audit form layout ---- */
.fgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
 gap:12px;margin-top:12px}
.hint{color:var(--muted);margin-top:4px;line-height:1.45}
.jobs{display:flex;flex-wrap:wrap;gap:10px}
.job{display:flex;align-items:center;gap:9px;cursor:pointer;
 border:1px solid var(--line);border-radius:14px;padding:11px 16px;
 background:var(--surface);flex:1;min-width:270px;font-size:14px}
.job:hover{border-color:var(--blue)}
.job:has(input:checked){border-color:var(--blue);background:#eef5fd}
.job input{position:absolute;opacity:0;pointer-events:none}
.job b{font-weight:600;color:var(--ink)}
.job .note{color:var(--muted);font-weight:400;font-size:12.5px;flex-basis:100%;
 margin-left:29px;margin-top:-2px}
.job .tick{width:20px;height:20px;border-radius:50%;border:1.5px solid var(--line);
 display:inline-flex;align-items:center;justify-content:center;flex:none;
 color:transparent;background:var(--surface)}
.job:has(input:checked) .tick{background:var(--blue);border-color:var(--blue);
 color:#fff}
/* A settings block belongs to the job above it, so it is hidden when that job
   is off rather than sitting there inert — a control you cannot act on is
   noise, and this form had seven of them. */
.joblet{display:none;margin-top:14px;padding:14px 16px;border-radius:14px;
 background:var(--plane);border:1px solid var(--line-2)}
.joblet.on{display:block}
.ph-wrap{display:flex;flex-wrap:wrap;gap:8px}
/* Crawl settings, beside Max pages. Same control, deliberately lighter: a
   dashed edge and a smaller body so the row reads as "leave these alone"
   rather than as two more phases to decide about. */
.crawlrow{display:flex;flex-wrap:wrap;gap:22px;align-items:flex-start;
 margin-top:14px}
.ph--set{padding:6px 12px 6px 9px;border-radius:9px;font-size:12.5px;
 font-weight:400;border-style:dashed;gap:6px}
.ph--set .tick{width:13px;height:13px;border-radius:4px}
.ph--set .tick svg{width:8px;height:8px}
.ph--set .note{font-size:11.5px}
.ph--set:has(input:checked){border-style:solid}

/* ---- market pills ---- */
.geobox{display:flex;flex-wrap:wrap;gap:6px;align-items:center;
 border:1px solid var(--line);border-radius:10px;background:var(--surface);
 padding:6px 8px;min-height:41px}
.geobox:focus-within{border-color:var(--blue);
 box-shadow:0 0 0 3px rgba(28,91,166,.12)}
.geoin{flex:1;min-width:150px;border:0!important;outline:none;padding:3px 2px!important;
 font:inherit;font-size:14px;background:transparent;box-shadow:none!important}
.gp{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;
 padding:3px 5px 3px 10px;border-radius:20px;white-space:nowrap;
 background:#e8eff8;color:var(--navy);border:1px solid #cfe0f4}
/* A market with no state gets amber, not red. It is not invalid input — it is
   input we cannot attribute to a body of law, which is a smaller and more
   accurate claim, and the person may well not care about that one. */
.gp.bad{background:#fdf3e2;color:#8a6212;border-color:var(--gold)}
.gp .st{font-weight:600;opacity:.75;font-size:11px}
.gp b{font-weight:500}
.gp button{background:none;border:0;cursor:pointer;color:inherit;opacity:.55;
 font-size:15px;line-height:1;padding:0 3px;border-radius:50%}
.gp button:hover{opacity:1;background:rgba(0,0,0,.07)}
label .note{color:var(--muted);font-weight:400;font-size:12px;
 margin-left:5px;letter-spacing:0;text-transform:none}
.tgrow{display:flex;flex-wrap:wrap;gap:5px;margin-top:2px}
.tg{padding:4px 11px!important;border-radius:20px;font-size:12.5px!important;
 font-weight:500!important;border:1px solid var(--line)!important;
 background:var(--surface)!important;color:var(--ink2)!important;
 cursor:pointer;line-height:1.4}
.tg:hover{border-color:var(--blue)!important;color:var(--blue)!important;
 filter:none!important}
.tg.on{background:var(--navy)!important;border-color:var(--navy)!important;
 color:#fff!important}
/* A state the markets imply but nobody has confirmed reads as a suggestion,
   not a selection — outlined rather than filled, so "we worked this out" and
   "you chose this" never look identical. */
.tg.auto{background:#e8eff8!important;border-color:var(--blue)!important;
 color:var(--navy)!important}
.spill{display:inline-flex;align-items:center;gap:5px;font-size:12px;
 font-weight:600;padding:2px 9px;border-radius:20px;margin:0 5px 5px 0;
 background:var(--pill-green);color:var(--pill-green-ink)}
.spill.none{background:var(--surface-2,#eef1f5);color:var(--muted);
 font-weight:500}

/* ---- forms ---- */
/* The form lays ITSELF out now, in `.fgrid` rows sized to their content.
   This forced every direct child into a fixed five-column grid — fine for the
   four fields it was written for, and it turned an eleven-field form into a
   collage the moment the fields were reordered. */
form#auditform{display:block}
label{display:block;font-size:12px;color:var(--ink2);margin-bottom:4px;font-weight:600}
input,select{width:100%;padding:10px 13px;border:1px solid var(--line);border-radius:10px;
 background:var(--surface);color:var(--ink);font:inherit;font-size:14.5px}
input:focus,select:focus{outline:none;border-color:var(--blue);
 box-shadow:0 0 0 2px rgba(22,104,193,.14)}
button{padding:10px 24px;border:0;border-radius:20px;background:var(--blue);color:#fff;
 font:inherit;font-weight:500;font-size:14px;cursor:pointer;white-space:nowrap}
button:hover{filter:brightness(1.07)}
/* The secondary action on the form. Same shape as the primary so it reads as a
   sibling rather than a downgrade — they do different jobs, not the same job
   at different strengths. */
button.alt{background:var(--surface);color:var(--navy);
 border:1px solid var(--line);font-weight:600}
button.alt:hover{border-color:var(--navy);color:var(--navy);filter:none;
 background:#f2f6fb}

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
th:first-child{border-radius:10px 0 0 0} th:last-child{border-radius:0 4px 0 0}
td{padding:15px 16px;border-bottom:1px solid var(--line-2)}
tr:hover td{background:#f8fafc}
td.num{text-align:right;font-variant-numeric:tabular-nums}
table.sub{margin-top:8px;font-size:12px;border:1px solid var(--line);border-radius:10px}
table.sub td{padding:7px 9px}
td.hw{color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums}

/* ---- phase toggles: pills you press, not boxes you tick ----
   Five checkboxes in a grid read as a settings dialog. The same five as
   pressable pills read as a choice you are making about this run, which is
   what they are — and the state is legible from across the room. */
.phases{display:flex;flex-wrap:wrap;gap:8px}
.ph{position:relative;display:inline-flex;align-items:center;gap:8px;
 padding:9px 16px 9px 13px;border-radius:22px;border:1px solid var(--line);
 background:var(--surface);font-size:13.5px;font-weight:500;color:var(--ink2);
 cursor:pointer;margin:0;transition:.14s ease;user-select:none;line-height:1.2}
.ph:hover{border-color:var(--blue);color:var(--blue)}
.ph input{position:absolute;opacity:0;width:0;height:0;margin:0}
.ph .tick{width:16px;height:16px;border-radius:50%;border:1.5px solid var(--line);
 display:inline-flex;align-items:center;justify-content:center;flex:none;
 transition:.14s ease}
.ph .tick svg{width:9px;height:9px;opacity:0;transition:.14s ease;
 stroke:#fff;stroke-width:3.4;fill:none;stroke-linecap:round;stroke-linejoin:round}
.ph .note{color:var(--muted);font-weight:400;font-size:12.5px}
.ph input:checked ~ .tick{background:var(--blue);border-color:var(--blue)}
.ph input:checked ~ .tick svg{opacity:1}
.ph:has(input:checked){border-color:var(--blue);background:#eef5fd;color:var(--blue-dk)}
.ph:has(input:checked) .note{color:#4a7fbe}
.ph:has(input:focus-visible){box-shadow:0 0 0 3px rgba(22,104,193,.18)}
.ph:has(input:disabled){opacity:.55;cursor:not-allowed;background:var(--line-2)}
.ph:has(input:disabled):hover{border-color:var(--line);color:var(--ink2)}

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

/* `.vrow` / `.vpill` / `.vdet` were the access pills' own block. The status
   moved onto the field it describes, so the rules went with it — leaving dead
   CSS behind is how the next person restores the duplication by accident. */

/* ---- access badge, worn by the picker it describes ----
   The three access pills used to sit in their own block above the three
   dropdowns, naming the same property twice on the same screen. The status
   belongs to the field, so it is worn by the field: the mark and one word on
   the label, the explanation under the select when there is anything to
   explain, and nothing at all when the answer is simply yes. */
.amark{display:inline-flex;align-items:center;gap:5px;font-size:11px;
 font-weight:600;letter-spacing:.02em;padding:2px 9px;border-radius:20px;
 white-space:nowrap;vertical-align:middle;margin-left:7px;text-transform:none}
.amark b{font-size:10px;line-height:1}
/* NAMESPACED ON PURPOSE. The first cut used `.amark.good/.warn/.bad`, and
   `.warn` is already a callout box elsewhere in this stylesheet — 8px of
   padding and a 3px gold border — so the amber badge silently rendered 14px
   taller than the green one and knocked its whole column out of alignment
   with the other two. A shared generic class name is a collision waiting for
   the next person; these three cannot be reused by accident. */
.amark--ok{background:var(--pill-green);color:var(--pill-green-ink)}
.amark--hold{background:#fbecc8;color:#8a5d05}
.amark--no{background:var(--pill-pink);color:var(--pill-pink-ink)}
.anote{font-size:12.5px;color:var(--ink2);margin-top:5px;line-height:1.5}

/* ---- stat strip ---- */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;
 margin-top:14px}
/* A tile that reacts. The numbers were correct and completely inert — this is
   a screen someone looks at twenty times a day, and a surface that answers the
   cursor is the cheapest way to make a tool feel alive rather than printed. */
.stat{background:var(--surface);border:1px solid var(--line);border-radius:10px;
 padding:16px 18px;position:relative;overflow:hidden;
 transition:transform .15s ease, box-shadow .15s ease, border-color .15s ease}
.stat::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;
 background:var(--edge,var(--seq));opacity:.9}
.stat:hover{transform:translateY(-2px);border-color:#c9d6e8;
 box-shadow:0 6px 18px -8px rgba(18,53,107,.28)}
.stat:has(.n:empty){opacity:.6}
.stat .n{font-size:28px;font-weight:700;letter-spacing:-.025em;
 font-variant-numeric:tabular-nums;line-height:1.15}
.stat .k{font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;
 color:var(--muted);margin-top:2px;font-weight:600}
.stat .k b{width:6px;height:6px;border-radius:50%;display:inline-block;
 margin-right:4px;vertical-align:1px}

/* ---- score ring: one hue, length carries magnitude ---- */
.ring{display:block}
.ring text{font:500 15px -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;fill:var(--ink);
 font-variant-numeric:tabular-nums}
.ring text.sm{font-size:11px;fill:var(--muted);font-weight:500}

/* ---- client rows ---- */
.crow{display:flex;gap:18px;align-items:flex-start;background:var(--surface);
 border:1px solid var(--line);border-radius:12px;padding:18px 22px;margin-bottom:10px}
.crow:hover{border-color:#c7d2e0}
.cscore{flex:none;padding-top:2px}
.cmain{flex:1;min-width:0}
.cname{font-size:16px;font-weight:500;color:var(--blue)}
.curl{margin-top:1px}
.cmeta{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin-top:7px;
 font-size:13.5px;color:var(--ink2)}
.cact{flex:none;display:flex;gap:6px;align-items:center}
.warn{margin-top:8px;font-size:12px;color:var(--ink2);background:#fdf6ec;
 border-left:3px solid var(--gold);border-radius:10px;padding:8px 11px}
.empty{color:var(--muted);padding:24px 0;text-align:center;font-size:13px}

/* ---- disclosure: adtini uses a tab strip; a details row is the same idea ---- */
.hist{margin-top:9px}
.hist summary{cursor:pointer;font-size:13.5px;color:var(--blue);
 list-style:none;display:inline-block;font-weight:600}
.hist summary::-webkit-details-marker{display:none}
.hist summary:before{content:"▸";margin-right:5px}
.hist[open] summary:before{content:"▾";margin-right:5px}

/* ---- progress ---- */
/* AN INDETERMINATE BAR, because the run has no percentage to report.
   A progress page's only job between refreshes is to look alive, and a bar
   that sweeps does that in no words at all — which is why the paragraph
   explaining how long a consent check takes could simply go. */
.glide{height:3px;border-radius:3px;background:var(--track);overflow:hidden;
 margin:11px 0 3px}
.glide > i{display:block;width:32%;height:100%;border-radius:3px;
 background:linear-gradient(90deg,transparent,var(--blue),transparent);
 animation:glide 1.5s ease-in-out infinite}
@keyframes glide{0%{transform:translateX(-105%)}100%{transform:translateX(320%)}}
@media (prefers-reduced-motion:reduce){
 .glide > i{animation:none;width:100%;opacity:.35}}
.spin{display:inline-block;width:11px;height:11px;border:2px solid var(--track);
 border-top-color:var(--blue);border-radius:50%;animation:s .8s linear infinite;
 vertical-align:-1px}
@keyframes s{to{transform:rotate(360deg)}}
.bar{height:7px;background:var(--track);border-radius:10px;overflow:hidden;min-width:90px}
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
                "needs_capture": "var(--serious)",
                # Stopped on purpose. Grey, never red: it is not a failure and
                # it should not read like one in a list of runs.
                "canceled": "var(--muted)"}

# adtini states are pastel pills with dark text, not a dot beside grey text.
STATUS_PILL = {"ready": "ready", "failed": "stop", "queued": "",
               "crawling": "run", "checking": "run", "scoring": "run",
               "needs_capture": "hold", "canceled": ""}


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
    """
    A tile whose accent bar carries the same color as its status dot.

    Seven tiles with an identical blue edge is decoration; seven where the edge
    means what the dot means is a row you can scan without reading. The dot
    stays too — color alone must never be the only carrier.
    """
    d = f"<b style='background:{dot}'></b>" if dot else ""
    edge = f" style='--edge:{dot}'" if dot else ""
    return (f"<div class='stat'{edge}><div class='n'>{e(n)}</div>"
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
    # SITE SCANNER.
    #
    # ONE OBJECT, because every icon in adtini's rail is one object — a house,
    # a person, a briefcase, a chart. The first attempt drew a browser window
    # with a lens over it, which is the better picture of what this tool does
    # and completely illegible at 21px: three concentric strokes inside a 40px
    # gold tile came out as a smudged box. The extension icon can afford the
    # window because it also renders at 48 and 128. This one cannot, so it is
    # the lens alone — the half that carries the meaning.
    "<a href='/' class='on' title='Site Scanner'>"
    + _icon("<circle cx='10.5' cy='10.5' r='6.5'/>"
            "<path d='M15.2 15.2 20.5 20.5'/>", 20) +
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


# ---------------------------------------------------------------- tab state
#
# THE TAB IS WHERE YOU LOOK WHEN YOU ARE NOT LOOKING.
#
# A scan takes minutes, so nobody watches it - they switch tabs and come back.
# Everything on the page said "running" to someone already reading it, and
# nothing said anything to someone who was not. This paints the state into the
# favicon and the title, which is the one part of the page a background tab
# still shows: a slow amber pulse while it runs, a steady green dot when it
# lands.
#
# Drawn on a canvas rather than swapped between two files: it is a dozen
# lines, it cannot 404, and it keeps working if the brand icon changes.
# WHY THIS RAN AND DID NOTHING FOR THREE BUILDS.
#
# The script was injected into <head> ABOVE both the <title> tag and the
# brand's own favicon link, and it ran the moment it was parsed. So:
#
#   * `base = document.title` read an EMPTY string, because <title> had not
#     been parsed yet - and the browser then parsed <title> and overwrote
#     whatever the pulse had set. The dot never appeared in the tab label.
#   * it set an icon link, and `brand.HEAD_TAGS` - parsed immediately after -
#     added the real Vici favicon, which won. So the tab kept its normal icon
#     the entire time a scan was running.
#
# Nothing was wrong with the drawing code, which is why it survived review:
# it was correct code running two lines too early. It now waits for the
# document to be parsed, takes the title from the DOM at that point, and
# actively removes the other icon links rather than politely reusing the
# first one it finds.
_TAB_JS = """
<script>(function(){
 var mode=%s, base='', on=true, link=null, src=null, img=null, ready=false;
 // THE DOT SITS ON THE FAVICON, IT DOES NOT REPLACE IT.
 //
 // The first version drew its own navy square, so a running scan swapped the
 // Vici mark for a generic blob - the tab stopped being identifiable at
 // exactly the moment somebody was hunting for it among twenty others. Claude
 // does the better thing: keep the icon, put a small badge in the corner.
 // Same trick here - render the real favicon into a canvas, then overlay.
 function draw(alpha){
  var c=document.createElement('canvas'); c.width=c.height=32;
  var x=c.getContext('2d');
  if(ready){ try{ x.drawImage(img,0,0,32,32); }catch(e){ ready=false; } }
  if(!ready){ x.fillStyle='#002D58';
   x.beginPath();
   if(x.roundRect){x.roundRect(0,0,32,32,8);}else{x.rect(0,0,32,32);}
   x.fill(); }
  // Small, bottom-right, with a ring of page-background so it reads as a
  // badge on the icon rather than as part of the artwork.
  var cx=24, cy=24, r=7;
  x.globalAlpha=1; x.fillStyle='#ffffff';
  x.beginPath(); x.arc(cx,cy,r,0,6.2832); x.fill();
  x.globalAlpha=alpha;
  x.fillStyle=(mode==='running')?'#F1B434':'#1E7A45';
  x.beginPath(); x.arc(cx,cy,r-1.8,0,6.2832); x.fill();
  return c.toDataURL('image/png');
 }
 function apply(href){
  if(!link){
   link=document.createElement('link'); link.rel='icon';
   document.head.appendChild(link);
  }
  link.type='image/png'; link.href=href;
 }
 function paint(){
  if(mode==='running'){
   on=!on;
   apply(draw(on?1:0.3));
   document.title=(on?'\u25cf ':'\u25cb ')+base;
  }else{
   apply(draw(1));
   document.title=base;
  }
 }
 // ONCE YOU ARE LOOKING AT THE PAGE, THE DOT HAS DONE ITS JOB.
 //
 // The indicator exists to catch your eye in a background tab. Leaving it
 // pulsing while you are reading the page it points at is just movement in
 // your peripheral vision, so focusing the tab clears it back to the plain
 // favicon and the plain title - and blurring away starts it again.
 var timer=null;
 function stop(){
  if(timer){clearInterval(timer); timer=null;}
  document.title=base;
  var mine=document.querySelectorAll("link[rel~='icon']");
  for(var i=0;i<mine.length;i++){mine[i].parentNode.removeChild(mine[i]);}
  link=null;
  if(src){ var l=document.createElement('link'); l.rel='icon';
   if(src.type){l.type=src.type;} l.href=src.href;
   document.head.appendChild(l); }
 }
 function go(){
  if(document.hasFocus && document.hasFocus()) { stop(); return; }
  if(timer) return;
  paint();
  if(mode==='running') timer=setInterval(paint, 900);
 }
 function start(){
  base=document.title||'';
  var found=document.querySelector("link[rel~='icon']");
  if(found){ src={href:found.href, type:found.type}; }
  window.addEventListener('focus', stop);
  window.addEventListener('blur', go);
  document.addEventListener('visibilitychange', function(){
   if(document.hidden){ go(); } else { stop(); }
  });
  if(src){
   img=new Image();
   img.onload=function(){ready=true; go();};
   img.onerror=function(){ready=false; go();};
   img.src=src.href;
  } else { go(); }
 }
 if(document.readyState==='loading'){
  document.addEventListener('DOMContentLoaded', start);
 }else{ start(); }
})();</script>
"""


def _tab(mode):
    """`running` pulses amber, `done` sits green, anything else is untouched."""
    if mode not in ("running", "done"):
        return ""
    import json as _j
    return _TAB_JS % _j.dumps(mode)


def client_tabs(a: dict, active: str = "report", has_consent: bool = False,
                siblings: list | None = None) -> str:
    """
    Every report this run produced, and every other run for this client.

    THE PAGE THAT CANNOT BE LEFT.

    A consent-only run opens on the consent page, which was right — and its
    only way out was "Back to the audit", which pointed at a URL that
    redirected straight back to the consent page. A loop. Worse, a client with
    a full audit AND a consent run had no route from one to the other at all:
    Open went to the newest, and the newest was the consent scan.
    #
    Tabs on both pages fix both. The report a run did not produce is not
    offered — a tab that leads to an empty page is the same dead end wearing a
    different label.
    """
    aid = a.get("id") or ""
    tabs = [("report", "Full audit", f"/audits/{aid}?view=report")]
    if has_consent:
        tabs.append(("consent", "Consent scan", f"/audits/{aid}/consent"))
    tabs += [("pdf", "Client PDF", f"/audits/{aid}.pdf"),
             ("snapshot", "Snapshot", f"/audits/{aid}.snapshot.pdf")]
    # TWO OF THESE FOUR ARE NOT PAGES.
    #
    # "Full audit / Consent scan / Client PDF / Snapshot" read as four tabs of
    # one document, so the last two looked like somewhere the tab strip would
    # take you — and instead a PDF opened in a new tab, or downloaded, with no
    # warning that clicking was going to leave. An arrow into a tray is the
    # convention for that, and it costs twelve pixels.
    _DL = ("<svg viewBox='0 0 24 24' width='12' height='12' fill='none' "
           "stroke='currentColor' stroke-width='2.2' stroke-linecap='round' "
           "stroke-linejoin='round' aria-hidden='true' class='ctab-dl'>"
           "<path d='M12 3v11'/><path d='m7.5 10.5 4.5 4 4.5-4'/>"
           "<path d='M4 20h16'/></svg>")
    out = ["<div class='ctabs'>"]
    for key, label, href in tabs:
        _file = key in ("pdf", "snapshot")
        _ext = " target='_blank' rel='noopener'" if _file else ""
        out.append(f"<a class='ctab{' on' if key == active else ''}"
                   f"{' ctab--file' if _file else ''}' "
                   f"href='{e(href)}'{_ext}"
                   + (" title='Opens a PDF'" if _file else "")
                   + f">{e(label)}{_DL if _file else ''}</a>")
    out.append("</div>")
    # OTHER RUNS, because "the audit we did for them" is usually a different
    # row. A consent-only re-run is a new audit, so the full one it descends
    # from is only reachable through the list — or through this.
    sib = [r for r in (siblings or []) if r.get("id") != aid][:6]
    if sib:
        out.append("<div class='csibs'><span>Other runs for this client</span>")
        for r in sib:
            _bits = []
            try:
                _o = _json.loads(r.get("options") or "{}") or {}
            except Exception:  # noqa: BLE001
                _o = {}
            _bits.append("consent" if _o.get("run_consent") else "")
            _bits.append("AI" if _o.get("run_aivis") else "")
            _kind = " · ".join(x for x in _bits if x) or "audit"
            out.append(
                f"<a href='/audits/{e(r['id'])}'>{_fmt_when(r.get('created_at'))}"
                f" <span class='k'>{e(_kind)}</span></a>")
        out.append("</div>")
    return "".join(out)


def _shell(title, body, refresh=None, heading=None, crumbs=None, tab=None,
           extra_css=""):
    """
    adtini chrome: fixed navy rail, white top bar, breadcrumb, content.

    The rail is decorative here — this app has two screens — but it is what
    makes the tool read as part of adtini rather than a separate site opened
    in a new tab, which is the whole point of the exercise.
    """
    # A META REFRESH DOES NOT CARE WHAT YOU ARE DOING.
    #
    # The dashboard reloads every 8 seconds while any run is in flight, and
    # the new-audit form is on the dashboard - so typing a client name with a
    # scan running meant watching the page blink and the field empty itself
    # every eight seconds. There is no way to cancel a meta refresh.
    #
    # A timer can be canceled, so it is a timer now: same interval, same
    # behavior on an idle page, but it holds off while anything on the page
    # is focused or has been typed into, and gets out of the way of a form
    # somebody is filling in. `data-refresh` is what the audit status page
    # (which has no form) still reloads on.
    r = ""
    if refresh:
        r = (f"<script>(function(){{var S={int(refresh)}*1000;"
             "function busy(){"
             "var a=document.activeElement;"
             "if(a&&/^(INPUT|SELECT|TEXTAREA)$/.test(a.tagName))return true;"
             "var f=document.querySelectorAll("
             "'form input[type=text],form input:not([type]),"
             "form input[type=number],form textarea');"
             "for(var i=0;i<f.length;i++){"
             "if(f[i].value&&f[i].value!==f[i].defaultValue)return true;}"
             "return false;}"
             "setInterval(function(){if(!busy())location.reload();},S);"
             "})();</script>")
    trail = ""
    if crumbs:
        parts = []
        for label, href in crumbs:
            parts.append(f"<a href='{href}'>{e(label)}</a>" if href
                         else f"<span>{e(label)}</span>")
        trail = f"<div class='crumb'>{' &rsaquo; '.join(parts)}</div>"
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>{r}"
            f"{_tab(tab)}"
            f"{HEAD}"
            f"<title>{e(title)}</title><style>{CSS}</style>"
            # AFTER the shell's, so a page that brings its own stylesheet wins
            # for its own content. The chrome — rail, topbar, breadcrumb,
            # tabs — is stripped from it by the caller, so the frame stays the
            # frame no matter which page is inside it.
            + (f"<style>{extra_css}</style>" if extra_css else "")
            + "</head>"
            f"<body class='viz-root'>{RAIL}"
            f"<header class='topbar'><span class='burger'>\u2630</span>"
            f"<h1>{e(heading or title)}</h1>"
            # THE BUILD, WHERE IT IS ALWAYS VISIBLE.
            #
            # "Vici Media ●" was our own name and a dot that did nothing, on
            # every page, in the one corner people already look at. The build
            # is the thing actually worth having there: deploying and then
            # reading a stale page is an easy mistake to make and a hard one
            # to spot, because the report looks plausible either way. Quiet
            # enough to ignore, present enough to check.
            f"<div class='right'><span class='bstamp' "
            f"title='Build running on this server'>{e(version.label())}"
            f"</span></div></header>"
            f"{trail}<div class='wrap'>{body}</div>{TIP_JS}</body></html>")


# ONE BUBBLE ON THE BODY, MOVED BY SCRIPT.
#
# Delegated from the document, so it covers every [data-tip] on every page
# including ones rendered after load. It reads the marker's position from
# getBoundingClientRect and places the bubble in FIXED coordinates, which is
# what makes it immune to the scroll containers that broke the CSS version:
# a fixed element is positioned against the viewport, not against whichever
# ancestor happens to scroll.
#
# Above the marker when there is room, below it when there is not, and always
# clamped inside the viewport — the old bubble hung off the left edge for
# every marker in a first column, which is exactly where the form's are.
TIP_JS = """<div id='tipbox' role='tooltip' aria-hidden='true'></div>
<script>(function(){
  var box = document.getElementById('tipbox'), cur = null;
  function place(el){
    var t = el.getAttribute('data-tip'); if (!t) return;
    box.textContent = t; box.classList.add('on');
    box.setAttribute('aria-hidden', 'false');
    var r = el.getBoundingClientRect(), b = box.getBoundingClientRect();
    var left = Math.min(Math.max(8, r.left - 10),
                        window.innerWidth - b.width - 8);
    var top = r.top - b.height - 8;
    if (top < 8) { top = r.bottom + 8; }   // no room above: go below
    box.style.left = left + 'px'; box.style.top = top + 'px';
    cur = el;
  }
  function hide(){
    cur = null; box.classList.remove('on');
    box.setAttribute('aria-hidden', 'true');
  }
  document.addEventListener('mouseover', function(ev){
    var el = ev.target.closest && ev.target.closest('[data-tip]');
    if (el) { if (el !== cur) place(el); } else if (cur) { hide(); }
  });
  document.addEventListener('focusin', function(ev){
    var el = ev.target.closest && ev.target.closest('[data-tip]');
    if (el) place(el); else hide();
  });
  document.addEventListener('focusout', hide);
  // A bubble left behind by a scroll points at nothing.
  window.addEventListener('scroll', function(){ if (cur) hide(); }, true);
  document.addEventListener('keydown', function(ev){
    if (ev.key === 'Escape') hide();
  });
})();</script>"""


def _stalled(a) -> bool:
    """
    Has this run stopped responding?

    One rule, used by the dashboard tiles, the client cards and the audit
    page. It lived only on the audit page before, which meant the dashboard
    counted a dead run as in flight indefinitely and the only way to find out
    was to click into it.

    A run with NO heartbeat at all is from before heartbeats existed, so a
    missing value means "unknown" and never "dead".
    """
    import time as _t
    if a.get("status") not in ("queued", "crawling", "checking", "scoring"):
        return False
    hb = a.get("heartbeat_at")
    return bool(hb) and (_t.time() - float(hb)) > STALE_AFTER_S


def _fmt_when(ts):
    import time as _t
    if not ts:
        return "—"
    return _t.strftime("%m/%d/%Y %H:%M", _t.localtime(ts))


def _del_form(audit_id, label="Delete", confirm="Delete this audit?"):
    return (f"<form method='post' action='/audits/{audit_id}/delete' "
            f"style='display:inline' onsubmit=\"return confirm('{confirm}')\">"
            f"<button class='del' type='submit'>{label}</button></form>")


# ---------------------------------------------------------------------------
# WHAT A RUN WAS ASKED TO DO, as one flat dict.
#
# At module level rather than nested inside the dashboard because it is now
# the single definition of "the settings" for three readers: the panel that
# shows them, the button that replays them, and the tests that guard against
# a field being added to the form and forgotten here — which has happened
# four times and cost a phase each time.
# ---------------------------------------------------------------------------
def settings_of(a):
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
        "gtm_container": o.get("gtm_container") or "",
        # THE TWO FIELDS THAT WERE NOT SAVING.
        #
        # They were never in this dict, so "Settings used" never showed
        # them and the prefill button never restored them. Every re-run
        # started with a blank industry and blank states — and a blank
        # states box means no state requirement is checked at all, so the
        # cost of forgetting was a silently thinner audit rather than a
        # visible gap.
        "consent_states": " ".join(o.get("consent_states") or []),
        "consent_industries": ", ".join(o.get("consent_industries") or []),
        # Added to the form in ‑39 and never added here — so they were
        # stored on the audit, invisible in "Settings used", and lost by
        # the prefill. The same omission that cost states and industries
        # five builds, repeated on three more fields two builds later.
        "consent_products": ", ".join(o.get("consent_products") or []),
        "conversion_urls": " ".join(o.get("conversion_urls") or []),
        "implementation": o.get("implementation") or "",
        "render_js": bool(o.get("render_js")),
        "browser_ua": bool(o.get("user_agent")),
        # THE PHASES. THE THIRD TIME THIS EXACT OMISSION HAS SHIPPED.
        #
        # Twice already a field was added to the form and never added to
        # this dict, so "Settings used" did not show it and "Run again"
        # silently reverted it - see the two notes above. The phase
        # checkboxes made it three, and this one is the most expensive:
        # the operator ticked "Ask the AI assistants", pressed Run again on
        # a later run, and got a report with no AI section and a panel
        # saying the phase was "not requested". They had requested it. The
        # button un-ticked it on the way past.
        #
        # Opt-in phases (AI, reputation, consent) read as their own key.
        # The three opt-OUT ones are stored inverted - `skip_judgment` is
        # what gets written - so they are flipped back here, and an ABSENT
        # skip key means the phase ran, which is why the default is True.
        # THE JOB, NOT JUST THE PHASES INSIDE IT.
        #
        # "What to run" is two checkboxes above the phase list, and this
        # dict knew about the phases but not about them — so Run again on
        # a consent-only run came back with Full audit ticked, because
        # that is the form's default and nothing had overridden it. The
        # operator either noticed and un-ticked it, or got a 150-page
        # crawl they did not ask for.
        #
        # A consent-only run is stored as `quick: "consent"`, which is the
        # authority on which job ran. The phase keys underneath it are all
        # forced off by that path and cannot answer the question.
        "do_audit": str(o.get("quick") or "") != "consent",
        "run_aivis": bool(o.get("run_aivis")),
        "run_reputation": bool(o.get("run_reputation")),
        "run_consent": bool(o.get("run_consent")),
        "run_judgment": not o.get("skip_judgment"),
        "run_collectors": not o.get("skip_collectors"),
        "run_screenshots": not o.get("skip_screenshots"),
        "reuse_crawl": bool(o.get("reuse_crawl")),
    }


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

    _settings = settings_of

    def _settings_panel(a):
        st = _settings(a)
        # Vertical and Primary conversion came off the form in ‑41. Listing
        # them here as settings "used" implied they could be changed, on a
        # panel whose whole job is to be copied back into a form that no
        # longer has them.
        shown = [("Max pages", st["max_pages"]),
                 ("Geographic targeting areas",
                  st["primary_markets"] or "—"),
                 ("Partner name", st["partner"] or "—"),
                 ("Industry", st["consent_industries"] or "—"),
                 ("Products", st["consent_products"] or "—"),
                 ("Conversion URLs", st["conversion_urls"] or "—"),
                 ("Implementation", st["implementation"] or "not specified"),
                 ("Search Console property", st["gsc_property"] or "auto"),
                 ("GA4 property", st["ga4_property_id"] or "auto"),
                 ("Tag Manager container", st["gtm_container"] or "auto"),
                 ("Consent states", st["consent_states"] or "none checked"),
                 ("Render JavaScript", "yes" if st["render_js"] else "no"),
                 ("Browser user-agent", "yes" if st["browser_ua"] else "no"),
                 # Listed because this panel is the record of what a run
                 # actually did. A phase missing from here is a phase nobody
                 # can check was on, which is how the AI section went missing
                 # without anyone being able to say when.
                 ("Phases", ", ".join(
                     n for n, on in (("read and judge", st["run_judgment"]),
                                     ("collectors", st["run_collectors"]),
                                     ("screenshots", st["run_screenshots"]),
                                     ("AI assistants", st["run_aivis"]),
                                     ("consent", st["run_consent"]),
                                     ("reputation", st["run_reputation"]))
                     if on) or "none")]
        rows = "".join(f"<tr><td class='hw'>{e(k)}</td><td>{e(v)}</td></tr>"
                       for k, v in shown)
        blob = _h.escape(_json.dumps(st), quote=True)
        # The copy button is gone. "Run again" does this now — see below.
        return (f"<details class='hist'><summary>Settings used</summary>"
                f"<table class='sub'>{rows}</table></details>")

    cards = []
    for g in groups:
        a = g["latest"]
        col = STATUS_COLOR.get(a["status"], "var(--muted)")
        # A STALLED RUN IS NOT A RUNNING ONE, ANYWHERE.
        #
        # The audit page has known this rule for builds — heartbeat older than
        # STALE_AFTER_S means the container is gone — and the dashboard did
        # not. So a dead run kept its spinner and kept counting under "in
        # flight" forever, and the only place that would tell you otherwise
        # was the page you had to click into to find out.
        dead = _stalled(a)
        spin = "<span class='spin'></span> " if (a["status"] in (
            "crawling", "checking", "scoring") and not dead) else ""
        hist = ""
        if g["history"]:
            rows = "".join(
                f"<tr><td class='hw'>{_fmt_when(h.get('created_at'))}</td>"
                f"<td><a href='/audits/{h['id']}'>{e(h['status'])}</a></td>"
                f"<td class='num'>{h['overall_score'] if h['overall_score'] is not None else '—'}</td>"
                f"<td class='num'>{e(h.get('coverage') or '—')}</td>"
                f"<td class='num'>{h.get('pages_crawled') or '—'}</td>"
                f"<td style='text-align:right'>"
                f"<button class='del' type='button' style='margin-right:6px' "
                f"data-prefill=\"{_h.escape(_json.dumps(_settings(h)), quote=True)}\" "
                f"onclick='prefill(this)'>Run again</button>"
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
            f"<span class='chip {'stop' if dead else STATUS_PILL.get(a['status'], '')}'>"
            f"{spin}"
            f"{'stalled' if dead else e(a['status'].replace('_', ' '))}</span>"
            f"<span>{e(a.get('overall_rating') or 'Not Assessed')}</span>"
            f"<span>{e(a.get('coverage') or '—')} checks</span>"
            f"<span>{a.get('pages_crawled') or '—'} pages</span>"
            f"<span>{_fmt_when(a.get('created_at'))}</span>"
            f"</div>"
            + (f"<div class='warn'>⚠ Server crawl blocked. Open the site in "
               f"Chrome, launch <b>Site Scanner</b>, and paste audit id "
               f"<code>{a['id']}</code>.</div>"
               if a["status"] == "needs_capture" else "")
            + _settings_panel(a)
            + hist
            + f"</div>"
            f"<div class='cact'>"
            # RUN AGAIN FILLS THE FORM. It does not launch anything.
            #
            # It used to POST straight to /rerun, which copied the previous
            # audit's stored options verbatim and queued it — so the settings
            # you were about to change were invisible, and an option added
            # after the first run could never turn on. That is the bug that
            # left twelve consecutive Ooten runs with no consent phase.
            #
            # There was a second button underneath the settings table doing
            # exactly what people actually wanted: put these back in the form
            # so I can change one thing. That is what "Run again" means, so
            # that is what it does, and the other button is gone.
            f"<button class='btn ghost' type='button' "
            f"data-prefill=\"{_h.escape(_json.dumps(_settings(a)), quote=True)}\" "
            f"onclick='prefill(this)'>Run again</button>"
            f"<a class='btn' href='/audits/{a['id']}'>Open</a>"
            f"<a class='btn ghost' href='/audits/{a['id']}.pdf' target='_blank' "
            f"rel='noopener'>PDF</a>"
            # The short one. Same findings, three pages - for the person who
            # is never going to open the twenty-nine-page version.
            f"<a class='btn ghost' href='/audits/{a['id']}.snapshot.pdf' "
            f"target='_blank' rel='noopener' "
            f"title='Three-page summary - same findings, no appendix'"
            f">Snapshot</a>"
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
    _running = [a for a in audits if a["status"] in
                ("queued", "crawling", "checking", "scoring")]
    n_run = sum(1 for a in _running if not _stalled(a))
    # COUNTED, NOT HIDDEN. Dropping stalled runs out of "in flight" and
    # nowhere else would trade a number that overstates for a number that
    # conceals — and the whole reason this tile matters is that someone is
    # looking at it to decide whether anything needs their attention.
    n_stalled = sum(1 for a in _running if _stalled(a))
    n_blocked = sum(1 for a in audits if a["status"] == "needs_capture")
    n_failed = sum(1 for a in audits if a["status"] == "failed")
    stats = "<div class='stats'>" + "".join([
        _stat(len(groups), "clients"),
        _stat(len(audits), "audits"),
        _stat(n_run, "in flight", STATUS_COLOR["crawling"]),
        _stat(n_stalled, "stalled", STATUS_COLOR["failed"]),
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
    # One tick mark, reused in every phase pill. Inline SVG rather than a
    # character, for the same reason the report's lamp is drawn: a glyph is at
    # the mercy of whatever font actually loads.
    TICK = ("<svg viewBox='0 0 12 12' aria-hidden='true'>"
            "<path d='M2.5 6.4 4.7 8.6 9.5 3.6'/></svg>")
    caps = caps or {}
    plats = caps.get("ai_platforms") or []
    _NICE = {"chatgpt": "ChatGPT", "claude": "Claude", "gemini": "Gemini",
             "perplexity": "Perplexity", "ai_overview": "AI Overviews",
             "copilot": "Copilot"}
    if not caps.get("known"):
        AIVIS_ATTR = ""
        AIVIS_NOTE = "keys not reported yet"
    elif plats:
        # THE COUNT, NOT THE ROLL-CALL.
        #
        # "(AI Overviews, ChatGPT, Claude, Gemini, Perplexity - ~2 min - paid
        # per question)" is longer than every other pill in the row put
        # together, and the names are not a decision anyone makes here: which
        # assistants are reachable is decided by which keys the worker holds.
        # The number says the same thing in four characters, and the report
        # names them where naming them matters.
        AIVIS_ATTR = ""
        # THE TIME ESTIMATE HAD TO MOVE WITH THE SAMPLING.
        #
        # Each question is now asked three times rather than once, because a
        # single pass gives an interval too wide for the rate to support any
        # reading a client takes from it. That is three times the calls and
        # three times the spend, and a note still promising "~2 min" would be
        # the form quietly lying about what the box costs.
        AIVIS_NOTE = (f"{len(plats)} assistant"
                      f"{'s' if len(plats) != 1 else ''} &middot; asked 3&times; "
                      f"each &middot; ~5 min")
    else:
        # Disabled rather than merely discouraged. A ticked box that cannot do
        # anything is worse than one that explains why it is greyed out.
        AIVIS_ATTR = "disabled"
        AIVIS_NOTE = ("no AI platform keys set &mdash; add "
                      "OPENAI_API_KEY, ANTHROPIC_API_KEY, PERPLEXITY_API_KEY "
                      "or GEMINI_API_KEY there")

    # The state list and the industry vocabulary come from the scanner itself,
    # so the form cannot drift from what the checks actually support.
    try:
        from engine.consent.state_checks import STATE_CHECKS as _SC
        from engine.consent.industries import INDUSTRIES as _IND
    except Exception:  # noqa: BLE001
        _SC, _IND = {}, []
    NSTATES = len(_SC) or 20
    # The reputation scan spends DataForSEO credit per run, and it is the same
    # key the backlink and ranking collectors already use - so the note says
    # what it costs rather than whether it is available.
    REP_NOTE = "reviews, brand searches, page one for \u201creviews\u201d"
    # The state vocabulary goes to the browser so a market can be validated as
    # it is typed, with no round trip. Two facts per code: the full name, and
    # whether we have a law to check there. The second is the one that makes
    # the answer honest — a market in Georgia is perfectly valid and there is
    # nothing for the consent scan to test, which is a real finding rather
    # than a silent omission.
    try:
        from engine.geo import STATES as _GEO_STATES
    except Exception:  # noqa: BLE001
        _GEO_STATES = {}
    STATES_JSON = _json.dumps({c: [n, c in (_SC or {})]
                               for c, n in sorted(_GEO_STATES.items())})
    # THE SAME TABLE THE SCANNER USES, NOT A SECOND COPY OF IT.
    #
    # The pills are validated in the browser and the laws are decided in
    # Python. Two hand-maintained copies of a ZIP-to-state table would agree
    # right up until one of them was edited, and the failure would be a
    # market that looks fine on the form and gets no state checks - which is
    # silent, and legal. Generated from engine/geo.ZIP3_RANGES.
    try:
        from engine.geo import ZIP3_RANGES as _Z3
    except Exception:  # noqa: BLE001
        _Z3 = ()
    ZIP3_JSON = _json.dumps([[lo, hi, c] for lo, hi, c in _Z3])
    INDOPTS = "".join(f"<option value=\"{e(i)}\">" for i in _IND[:400])
    # ALL TWENTY, AS TOGGLES.
    #
    # The states box was free text, which is the wrong control for a closed
    # set of twenty: it cannot show what the options ARE, so a state we check
    # was invisible unless you already knew to type it. The standalone
    # scanner has always shown them as a toggle row and that is the right
    # answer — every state we can test, visible, with the ones the markets
    # imply already on.
    STATE_TOGGLES = "".join(
        f"<button type='button' class='tg' data-st='{c}' "
        f"onclick='stToggle(this)'>{c}</button>"
        for c in sorted(_SC or {}))
    try:
        from engine.consent.signatures import PRODUCT_PIXELS as _PP
    except Exception:  # noqa: BLE001
        _PP = {}
    PRODUCT_TOGGLES = "".join(
        f"<button type='button' class='tg' data-pr=\"{e(k)}\" "
        f"onclick='prToggle(this)'>{e(k)}</button>" for k in _PP)

    # The build moved to the top bar, where it is on EVERY page rather than
    # only this one. A second copy here is the same fact twice, above the
    # first number anyone came to read.
    body = f"""
    {stats}

    <h2>New audit</h2>
    <div class='card'><form method='post' action='/audits' id='auditform'>
      <input type='hidden' name='phases' value='1'>

      <!-- WHO AND WHERE ---------------------------------------------------
           Reordered to the order a person actually knows things in: who the
           client is, then their site, then the facts about their business,
           then the accounts, then what to run. The old order opened with a
           URL and asked for the vertical before the name. -->
      <div class='fgrid'>
        <div><label>Client name</label>
          <input name='client_name' id='cname' placeholder='Grand Furniture'
                 onblur='accessAuto()' required></div>
        <div><label>Client website</label>
          <input name='target_url' id='turl' onchange='accessAuto()'
                 onblur='accessAuto()'
                 placeholder='https://www.example.com/' required></div>
      </div>
      <div class='fgrid'>
        <div>
          <label>Industry<i class='tip' tabindex='0' data-tip="Also drives the health, children&#39;s and financial rules — FTC pixel enforcement, COPPA, GLBA.">i</i></label>
          <!-- One control, not a filter beside a select. A datalist IS the
               filter: type to narrow, or open it and scroll. Two boxes doing
               one job was the thing that needed removing. -->
          <input name='consent_industries' form='auditform' list='indlist'
                 placeholder='Type to search 346 industries…'>
          <datalist id='indlist'>{INDOPTS}</datalist>

        </div>
        <div><label>Partner name</label>
          <input name='partner' form='auditform' placeholder='Vici Media'></div>
      </div>

      <div style='margin-top:14px'>
        <label>Geographic targeting areas<i class='tip' tabindex='0' data-tip="Where the campaign runs. Cities, counties, states or ZIP codes - the state is what decides which privacy laws get checked, and a ZIP names its own.">i</i></label>
        <div class='geobox' id='geobox'>
          <span id='geopills'></span>
          <input id='geoinput' class='geoin' autocomplete='off'
                 placeholder='Knox County, TN — then Enter'>
        </div>
        <input type='hidden' name='primary_markets' id='primary_markets'
               form='auditform'>
        <div class='sm hint' id='geonote'></div>
      </div>

      <div style='margin-top:14px'>
        <label>Products they bought<i class='tip' tabindex='0' data-tip="Which pixels we expect to find. Without this the scan reports what IS firing; with it, it can report a product they pay for whose pixel never fires.">i</i></label>
        <div class='tgrow' id='prrow'>{PRODUCT_TOGGLES}</div>
        <input type='hidden' name='consent_products' id='consent_products'
               form='auditform'>
      </div>

      <div style='margin-top:14px'>
        <label>Conversion URLs<i class='tip' tabindex='0' data-tip="Scanned as well as the homepage. A thank-you page is where conversion pixels actually fire, so it is the page most likely to carry an ungated one. Paste a list — the URLs are picked out of it.">i</i></label>
        <div class='geobox' id='cvbox'>
          <span id='cvpills'></span>
          <input id='cvinput' class='geoin' autocomplete='off'
                 placeholder='clientsite.com/thank-you'>
        </div>
        <input type='hidden' name='conversion_urls' id='conversion_urls'
               form='auditform'>
      </div>
    </form>

    <!-- GOOGLE ACCESS ----------------------------------------------------->
    <div style='margin-top:18px;padding-top:16px;border-top:1px solid var(--line-2)'>
      <button type='button' class='btn ghost' id='ckbtn'
              onclick='checkAccess()'>Check Google access</button>
      <div id='ckout' class='sm'
           style='color:var(--muted);margin-top:8px;line-height:1.6'></div>
    </div>
    <!-- EVEN THIRDS ACROSS THE FULL WIDTH.
         auto-fit with a 255px minimum packed the three pickers into the left
         half of a wide screen, so each note wrapped to eleven lines in a
         narrow column while the right half sat empty. The notes are the
         longest thing here; giving them the width they need is what makes
         them short. -->
    <div id='pickers' style='display:none;margin-top:10px;
         grid-template-columns:repeat(3,minmax(0,1fr));gap:18px'>
      <div><label>Search Console property<span id='gscmark'></span></label>
        <input class='pfilter' id='gscq' placeholder='Filter…' autocomplete='off'>
        <select name='gsc_property' id='gscsel' form='auditform'></select>
        <div class='anote' id='gscnote'></div></div>
      <div><label>GA4 property<span id='ga4mark'></span></label>
        <input class='pfilter' id='ga4q' placeholder='Filter…' autocomplete='off'>
        <select name='ga4_property_id' id='ga4sel' form='auditform'></select>
        <div class='anote' id='ga4note'></div></div>
      <div><label>Tag Manager container<span id='gtmmark'></span></label>
        <input class='pfilter' id='gtmq' placeholder='Filter…' autocomplete='off'>
        <select name='gtm_container' id='gtmsel' form='auditform'></select>
        <div class='anote' id='gtmnote'></div></div>
      <!-- WHICH LOGIN, BY NAME.
           A picker with nothing in it is a request to the client, and the
           request needs an address. Two different ones, which is exactly why
           nobody should be recalling them from memory at the moment they are
           writing the email. Stated once, under the three fields it applies
           to, so it is on screen before the check has even been run. -->
      <div class='sm' style='grid-column:1/-1;color:var(--muted);
           line-height:1.6;margin-top:2px'>
        A property only appears here once a Vici login has been granted access
        to it. For <b>Search Console</b> and <b>GA4</b> the client adds
        <b>digital@reporting.zone</b>; for <b>Tag Manager</b> it is
        <b>tagops1@reporting.zone</b>. Read-only is enough for the audit —
        publishing a tag change needs Publish on the container.
      </div>
    </div>

    <!-- WHAT TO RUN -------------------------------------------------------
         TWO JOBS, NOT SEVEN CHECKBOXES.
         The old strip mixed a phase of the audit with a whole separate
         product and made them look like peers. They are not: one crawls the
         site and scores 322 checkpoints, the other loads pages in a browser
         and watches what fires. Either, or both. Each opens its own settings
         instead of scattering them across the form. -->
    <div style='margin-top:20px;padding-top:16px;border-top:1px solid var(--line-2)'>
      <div class='sm' style='font-weight:600;letter-spacing:.06em;
           text-transform:uppercase;color:var(--muted);margin-bottom:9px'>
        What to run</div>
      <div class='jobs'>
        <label class='job' id='jobaudit'>
          <input type='checkbox' id='do_audit' name='do_audit' value='1'
                 checked form='auditform' onchange='jobSync()'>
          <span class='tick'>{TICK}</span>
          <b>Full audit</b>
          <span class='note'>crawls the site and scores 322 checkpoints</span>
        </label>
        <label class='job' id='jobconsent'>
          <input type='checkbox' id='do_consent' name='run_consent' value='1'
                 checked form='auditform' onchange='jobSync()'>
          <span class='tick'>{TICK}</span>
          <b>Consent check</b>
          <span class='note'>cookie banner, pre-consent tags, state law</span>
        </label>
      </div>

      <div class='joblet' id='auditopts'>
        <div class='ph-wrap'>
          <label class='ph'><input type='checkbox' name='run_judgment'
            value='1' checked form='auditform'><span class='tick'>{TICK}</span>
            Read and judge the pages
            <span class='note'>E-E-A-T, on-page, AI-readiness</span></label>
          <label class='ph'><input type='checkbox' name='run_collectors'
            value='1' checked form='auditform'><span class='tick'>{TICK}</span>
            Search Console, Analytics, off-page</label>
          <label class='ph'><input type='checkbox' name='run_screenshots'
            value='1' checked form='auditform'><span class='tick'>{TICK}</span>
            Evidence screenshots <span class='note'>~30s</span></label>
          <label class='ph'><input type='checkbox' name='run_aivis' value='1'
            {AIVIS_ATTR} form='auditform'><span class='tick'>{TICK}</span>
            Ask the AI assistants <span class='note'>{AIVIS_NOTE}</span></label>
          <label class='ph'><input type='checkbox' name='run_reputation'
            value='1' form='auditform'><span class='tick'>{TICK}</span>
            Reputation profile <span class='note'>{REP_NOTE}</span></label>
          <label class='ph'><input type='checkbox' name='reuse_crawl' value='1'
            checked form='auditform'><span class='tick'>{TICK}</span>
            Reuse the last crawl</label>
        </div>

        <!-- CRAWL SETTINGS ARE NOT PHASES.
             The two override toggles sat in the same pill row as "Read and
             judge the pages" and "Ask the AI assistants", which are decisions
             about what this audit COVERS. These two are decisions about how
             the crawler talks to one server, they are both on auto, and most
             runs should never touch them - so they sit down here with Max
             pages, smaller and quieter, as settings rather than choices. -->
        <div class='crawlrow'>
          <div style='max-width:170px'>
            <label>Max pages</label>
            <input name='max_pages' type='number' value='150' min='1' max='500'
                   form='auditform'>
          </div>
          <div>
            <label>Crawl overrides</label>
            <div class='ph-wrap' style='margin-top:6px'>
              <label class='ph ph--set'><input type='checkbox' name='browser_ua'
                value='1' form='auditform'><span class='tick'>{TICK}</span>
                Browser user-agent
                <span class='note'>auto</span></label>
              <label class='ph ph--set'><input type='checkbox' name='render_js'
                value='1' form='auditform'><span class='tick'>{TICK}</span>
                Render JavaScript
                <span class='note'>auto</span></label>
            </div>
          </div>
        </div>

      </div>

      <div class='joblet' id='consentopts'>
        <div class='fgrid'>
          <div>
            <label>States to check
              <span class='note' id='cstatesrc'></span></label>
            <div class='tgrow' id='strow'>{STATE_TOGGLES}</div>
            <input type='hidden' name='consent_states' id='cstates'
                   form='auditform'>
            <div class='sm hint' id='cstatenote'>All {NSTATES} states with a
              law we check. Filled means chosen; outlined means your markets
              imply it.</div>
          </div>
          <div>
            <label>Implementation<i class='tip' tabindex='0' data-tip="Who owns the tags. A pixel firing pre-consent in a container we own is our work queue; the same pixel in the client&#39;s container is a conversation.">i</i></label>
            <select name='implementation' form='auditform'>
              <option value=''>Not specified</option>
              <option value='vici_gtm'>Vici-owned GTM</option>
              <option value='client_gtm'>Client-owned GTM</option>
              <option value='client_placement'>Client placement</option>
              <option value='hardcoded'>Hardcoded in the site</option>
            </select>

          </div>
        </div>
      </div>

      <div style='margin-top:18px;display:flex;gap:10px;align-items:center'>
        <button type='submit' form='auditform' id='gobtn'>Scan site</button>
        <span class='sm' style='color:var(--muted)' id='gonote'></span>
      </div>
    </div>
    </div>

    <h2>Clients</h2>{listing}

    <script>
    // Preflight, not a gate. It never blocks submission — a probe that is
    // wrong about GA4 (it scans by name only, for speed) must not stop a real
    // audit from running.
    // THE ACCESS CHECK RUNS ITSELF AGAIN.
    //
    // It used to fire as soon as there was a URL to check, and somewhere in
    // the move to per-dropdown pills that call was lost - so the pickers
    // stayed empty until somebody thought to press a button, which is exactly
    // the state the button exists to rescue you FROM.
    //
    // Fires on the URL field losing focus or changing, once per URL, and only
    // when the URL is plausible. The button stays for a retry after fixing a
    // login on Google's side, where nothing about this form has changed.
    var _ckFor = '';
    function accessAuto() {{
      var el = document.getElementById('turl');
      var u = (el && el.value || '').trim();
      var cn = (document.getElementById('cname') || {{value: ''}}).value.trim();
      // KEYED ON BOTH, because the name is now part of the question. Typing
      // the URL first and the client name second used to leave the check
      // answered from the URL alone and never re-asked.
      var k = u + '|' + cn;
      if (!u || !/\.[a-z]{{2,}}/i.test(u) || k === _ckFor) return;
      _ckFor = k;
      checkAccess();
    }}

    async function checkAccess() {{
      var u = document.getElementById('turl').value.trim();
      var out = document.getElementById('ckout');
      var btn = document.getElementById('ckbtn');
      if (!u) {{ out.textContent = 'Enter a URL first.'; return; }}
      if (!/^https?:\\/\\//.test(u)) {{ u = 'https://' + u; }}
      btn.disabled = true; out.style.color = 'var(--muted)';
      out.textContent = 'Checking…';
      try {{
        // The client name travels with the check — a property named after
        // the client rather than the URL is the common case, not the edge.
        var cn = (document.getElementById('cname')
                  || {{value: ''}}).value.trim();
        var r = await fetch('/api/access-check?target_url='
                            + encodeURIComponent(u)
                            + (cn ? '&client_name=' + encodeURIComponent(cn) : ''));
        var d = await r.json();
        if (!r.ok) {{ throw new Error(d.detail || r.status); }}
        // THE STATUS IS WORN BY THE FIELD IT DESCRIBES.
        //
        // This used to render three pills in a block of their own, directly
        // above three dropdowns that already named the same three properties.
        // "https://ootenlawfirm.com/ \u00b7 via reporting-zone" appeared twice
        // on one screen, six inches apart, and the reader had to work out that
        // the two halves were the same fact.
        //
        // So the mark and one word go on the label, and the sentence that
        // explains a miss goes under the select that can fix it. When the
        // answer is simply yes, the dropdown below IS the answer and nothing
        // else is printed.
        function badge(which, st) {{
          // FOUR states, not three. `ours` marks a gap on OUR side \u2014 an
          // env var we have not set, or a scope our logins have not approved.
          // It renders amber rather than red on purpose: a red cross next to
          // "Tag Manager" reads as the client withholding access, and sends
          // someone to write an email about a problem that is two minutes of
          // our own re-consent.
          st = st || {{ok: false}};
          var cls  = st.ok ? 'amark--ok'
                   : (st.ours || st.partial) ? 'amark--hold' : 'amark--no';
          var sym  = st.ok ? '\u2713'
                   : (st.ours || st.partial) ? '!' : '\u2717';
          var word = st.ok ? 'found'
                   : st.ours ? 'ours to fix'
                   : st.partial ? 'no quick match' : 'not found';
          var m = document.getElementById(which + 'mark');
          if (m) {{
            m.className = 'amark ' + cls;
            m.innerHTML = '<b>' + sym + '</b>' + word;
          }}
          // The note carries only what the dropdown cannot. On a match the
          // selected option already reads "property \u00b7 login", so saying it
          // again here would be the same duplication one level down.
          var n = document.getElementById(which + 'note');
          if (n) {{
            n.textContent = st.ok ? '' : (st.detail || (st.partial
              ? 'No quick match \u2014 the audit looks wider than this URL. '
                + 'Pick the right one below.'
              : 'Pick it below if it is listed, or ask the client for access.'));
          }}
        }}
        out.style.color = '';
        out.innerHTML = '';
        badge('gsc', d.gsc); badge('ga4', d.ga4); badge('gtm', d.gtm);
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
      // The container the PAGE loads is preselected when we hold it, because
      // that is the only container that can be the right answer — an operator
      // picking by name from an agency's several hundred is picking blind.
      fill('gtm', (ALL.gtm || []).map(function (r) {{
        return {{v: r.public_id,
                t: r.account + '  ·  ' + r.container + '  ·  ' + r.public_id}};
      }}), (probe.gtm && probe.gtm.ok) ? probe.gtm.property : null);
      applyPending();
    }}

    // A HAND-PICKED PROPERTY THAT WAS NEVER RE-APPLIED.
    //
    // `_pendingProps` has been set by Run again for several builds and read by
    // nothing — so the operator's stored choice was carried all the way to the
    // form and then dropped on the floor, and the pickers came back on the
    // automatic match or on nothing. It looked exactly like the settings not
    // being saved, because in the only sense that matters they were not.
    //
    // The operator's choice beats the automatic match on purpose: they made it
    // BECAUSE the matcher was wrong, and a re-run that quietly reverts to the
    // wrong answer is worse than one that never offered.
    function applyPending() {{
      var p = window._pendingProps;
      if (!p) return;
      var hit = [];
      [['gsc', p.gsc], ['ga4', p.ga4], ['gtm', p.gtm]].forEach(function (x) {{
        if (!x[1]) return;
        var sel = document.getElementById(x[0] + 'sel');
        if (!sel) return;
        // Only if the value is actually in the list — a property that has
        // since been revoked must not become a silently-selected blank.
        var known = (sel._rows || []).some(function (r) {{ return r.v === x[1]; }});
        if (!known) return;
        sel._sel = x[1];
        paint(x[0]);
        sel.value = x[1];
        hit.push(x[0].toUpperCase());
        var m = document.getElementById(x[0] + 'mark');
        if (m) {{ m.className = 'amark amark--ok';
                 m.innerHTML = '<b>\\u2713</b>your pick'; }}
        var n = document.getElementById(x[0] + 'note');
        if (n) n.textContent = 'Kept from the last run for this client.';
      }});
      window._pendingProps = null;
      var gn = document.getElementById('gonote');
      if (gn && hit.length) {{
        gn.textContent = 'Settings loaded — ' + hit.join(', ')
          + ' kept from the last run. Change anything, then Scan site.';
      }}
    }}

    // A NATIVE SELECT OF FOUR HUNDRED IS NOT A PICKER.
    //
    // When the matcher misses, the operator has to find one property among
    // every property four Vici logins can see — and a <select> gives them
    // type-ahead on the FIRST character only. "Belmont" finds nothing if the
    // option starts with the account name. So each picker gets a filter that
    // matches anywhere in the row, and the count says how much is hidden,
    // because a list that silently shrank is worse than a long one.
    function paint(which) {{
      var sel = document.getElementById(which + 'sel');
      var q = (document.getElementById(which + 'q').value || '')
                .trim().toLowerCase();
      var rows = sel._rows || [];
      var keep = q ? rows.filter(function (r) {{
        return (r.t || '').toLowerCase().indexOf(q) >= 0;
      }}) : rows;
      var cur = sel.value;
      sel.innerHTML = '';
      var none = document.createElement('option');
      none.value = '';
      none.textContent = q
        ? (keep.length + ' of ' + rows.length + ' match “' + q + '”')
        : (sel._sel ? 'Matched automatically — leave as is'
                    : 'No match — pick one, or leave blank');
      sel.appendChild(none);
      keep.forEach(function (r) {{
        var o = document.createElement('option');
        o.value = r.v; o.textContent = r.t;
        sel.appendChild(o);
      }});
      // Keep the current choice even when the filter would hide it — a filter
      // that silently clears a selection is a filter that loses work.
      if (cur && !keep.some(function (r) {{ return r.v === cur; }})) {{
        var k = rows.filter(function (r) {{ return r.v === cur; }})[0];
        if (k) {{
          var o2 = document.createElement('option');
          o2.value = k.v; o2.textContent = k.t + '  (selected)';
          sel.appendChild(o2);
        }}
      }}
      sel.value = cur || '';
      // The select grows while filtering so the matches are visible at once
      // rather than one at a time behind a scroll.
      sel.size = q && keep.length > 1 ? Math.min(10, keep.length + 1) : 0;
    }}

    function fill(which, rows, selected) {{
      var sel = document.getElementById(which + 'sel');
      sel._rows = rows;
      sel._sel = selected || '';
      var q = document.getElementById(which + 'q');
      q.style.display = rows.length > 8 ? 'block' : 'none';
      if (!q._wired) {{
        q._wired = true;
        q.addEventListener('input', function () {{ paint(which); }});
        // Escape clears rather than closing the form's focus trap.
        q.addEventListener('keydown', function (ev) {{
          if (ev.key === 'Escape') {{ q.value = ''; paint(which); }}
        }});
        // Picking collapses the expanded list back to one line.
        document.getElementById(which + 'sel')
          .addEventListener('change', function () {{ this.size = 0; }});
      }}
      paint(which);
      // A matched property is preselected but NOT forced: leaving the blank
      // option is the same as before this existed, and the audit re-matches.
      if (selected) {{ sel.value = selected; }}
    }}

    // Re-audit a client without retyping their intake. The button carries the
    // whole settings object, so nothing is read off an old report by eye.
    // ---- market pills, and the states they imply -------------------------
    //
    // Mirrors engine/geo.py deliberately. The server is still the authority —
    // it re-parses on submit — but a market that resolves to no state has to
    // be visible WHILE it is being typed, because that is the only moment
    // anyone can fix it. Finding out afterwards means finding out from a
    // report that quietly checked nothing.
    var GEO_STATES = {STATES_JSON};
    var ZIP3 = {ZIP3_JSON};
    var GEO_BYNAME = {{}};
    Object.keys(GEO_STATES).forEach(function (c) {{
      GEO_BYNAME[GEO_STATES[c][0].toLowerCase()] = c;
    }});
    GEO_BYNAME['washington dc'] = 'DC';
    GEO_BYNAME['district of columbia'] = 'DC';
    var MARKETS = [];
    var STATES_TOUCHED = false;

    function zipState(t) {{
      var m = String(t || '').trim().match(/^(\d{{5}})(?:-\d{{4}})?$/);
      if (!m) return null;
      var z = parseInt(m[1].slice(0, 3), 10);
      for (var i = 0; i < ZIP3.length; i++) {{
        if (z >= ZIP3[i][0] && z <= ZIP3[i][1]) return ZIP3[i][2];
      }}
      return null;
    }}

    // A NATIONAL TARGET IS EVERY STATE, NOT NO STATE.
    //
    // "US" and "united states" resolved to nothing, so a client selling
    // nationwide got a question-mark pill and an empty state list — the most
    // exposed client with the emptiest legal section. Mirrors is_national()
    // in engine/geo.py; the server re-parses on submit and is the authority.
    var GEO_NATIONAL = {{'us':1,'u.s.':1,'u.s.a.':1,'usa':1,'united states':1,
      'united states of america':1,'national':1,'nationwide':1,
      'nation-wide':1,'all 50 states':1,'50 states':1,'all states':1,
      'country-wide':1,'countrywide':1,'coast to coast':1}};

    function geoIsNational(label) {{
      var t = String(label || '').trim().replace(/[\s,\.]+$/, '').toLowerCase();
      return !!GEO_NATIONAL[t];
    }}

    function geoState(label) {{
      var t = (label || '').trim().replace(/,+$/, '');
      if (!t) return null;
      var z = zipState(t);
      if (z) return z;
      if (GEO_STATES[t.toUpperCase()]) return t.toUpperCase();
      if (GEO_BYNAME[t.toLowerCase()]) return GEO_BYNAME[t.toLowerCase()];
      var m = t.match(/[,\s]+([A-Za-z.\s]{{2,30}})$/);
      if (m) {{
        var tail = m[1].trim().replace(/\.+$/, '');
        if (GEO_STATES[tail.toUpperCase()]) return tail.toUpperCase();
        if (GEO_BYNAME[tail.toLowerCase()]) return GEO_BYNAME[tail.toLowerCase()];
      }}
      var parts = t.split(',');
      for (var i = 0; i < parts.length; i++) {{
        var p = parts[i].trim();
        if (GEO_STATES[p.toUpperCase()]) return p.toUpperCase();
        if (GEO_BYNAME[p.toLowerCase()]) return GEO_BYNAME[p.toLowerCase()];
      }}
      return null;
    }}

    function geoEsc(t) {{
      return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                      .replace(/"/g, '&quot;');
    }}

    function geoRender() {{
      var box = document.getElementById('geopills');
      if (!box) return;
      box.innerHTML = MARKETS.map(function (label, i) {{
        var st = geoIsNational(label) ? 'US' : geoState(label);
        // "Anderson County, TN" beside a TN tag says TN twice. Strip the
        // state off the label and let the tag carry it — the full string is
        // still what gets submitted and still what the tooltip shows.
        var shown = label;
        if (st) {{
          // A CHARACTER CLASS WITH NO BACKSLASH, deliberately. This string
          // passes through a Python f-string and then a JS string literal, and
          // '\s' survives neither intact — it arrived as the letter s, so the
          // class matched commas and esses and stripped nothing. A comma and
          // a space are all this needs, and they cannot be mangled.
          shown = label.replace(
            new RegExp('[, ]+(' + st + '|'
                       + GEO_STATES[st][0].replace(/ /g, '[ ]+') + ')$', 'i'),
            '').trim() || label;
        }}
        return '<span class="gp' + (st ? '' : ' bad') + '" title="'
             + geoEsc(st ? label + ' — ' + GEO_STATES[st][0]
                         : 'No state found — this market cannot be matched '
                           + 'to a privacy law') + '">'
             + '<b>' + geoEsc(shown) + '</b>'
             + (st ? '<span class="st">' + st + '</span>'
                   : '<span class="st">?</span>')
             + '<button type="button" aria-label="Remove ' + geoEsc(label)
             + '" onclick="geoDrop(' + i + ')">&times;</button></span>';
      }}).join('');
      document.getElementById('primary_markets').value = MARKETS.join(' \u00d7 ');
      geoSyncStates();
    }}

    function geoDrop(i) {{ MARKETS.splice(i, 1); geoRender(); }}

    function geoAdd(raw) {{
      // One paste can carry a whole list, so split on the same separators the
      // server does rather than making someone re-enter thirteen counties.
      // The newline escape below is DOUBLED on purpose. This JS lives
      // Python f-string, so a single backslash-n is a real newline by the
      // time the page is written — which closed the regex literal
      // mid-expression and took the whole script down with
      // "Invalid regular expression: missing /".
      var parts = (raw || '').split(/[\u00d7\u2715\u2716;|\\n]|\s[xX]\s/);
      // A COMMA IS PART OF "Knox County, TN" AND A SEPARATOR IN "37314, 37354".
      //
      // Splitting on every comma turned one market into two pills - "Knox
      // County" with no state, and a stray "TN" - which is exactly what the
      // placeholder tells people to type. Not splitting at all leaves a
      // pasted list of eighty ZIPs as a single pill. The test that tells them
      // apart is whether EVERY piece stands on its own as a market: two ZIPs
      // do, a county and its state do not.
      var out = [];
      parts.forEach(function (p) {{
        var bits = p.split(',').map(function (x) {{ return x.trim(); }})
                    .filter(Boolean);
        if (bits.length > 1 && bits.every(function (b) {{
              return geoState(b) !== null;
            }})) {{
          out = out.concat(bits);
        }} else {{
          out.push(p);
        }}
      }});
      out.forEach(function (c) {{
        var label = c.replace(/\s+/g, ' ').trim().replace(/^,|,$/g, '').trim();
        if (!label) return;
        var dupe = MARKETS.some(function (m) {{
          return m.toLowerCase() === label.toLowerCase();
        }});
        if (!dupe) MARKETS.push(label);
      }});
      geoRender();
    }}

    function geoSyncStates() {{
      var codes = [], seen = {{}}, national = false;
      MARKETS.forEach(function (m) {{
        if (geoIsNational(m)) {{ national = true; return; }}
        var st = geoState(m);
        if (st && !seen[st]) {{ seen[st] = 1; codes.push(st); }}
      }});
      if (national) {{
        // Every state in the map, because a nationwide seller is subject to
        // all of them. The ones we have no checks for are still reported as
        // unchecked rather than quietly dropped.
        Object.keys(GEO_STATES).forEach(function (c) {{
          if (GEO_STATES[c][1] && !seen[c]) {{ seen[c] = 1; codes.push(c); }}
        }});
      }}
      codes.sort();
      var check = codes.filter(function (c) {{ return GEO_STATES[c][1]; }});
      var noLaw = codes.filter(function (c) {{ return !GEO_STATES[c][1]; }});
      var src = document.getElementById('cstatesrc');
      var note = document.getElementById('cstatenote');
      // Suggest, never overwrite. A state the operator turned on or off by
      // hand stays that way; the markets only pre-light the ones nobody has
      // expressed an opinion about.
      document.querySelectorAll('#strow .tg').forEach(function (b) {{
        if (b.dataset.pinned) return;
        b.classList.toggle('auto', check.indexOf(b.dataset.st) >= 0);
      }});
      stSync();
      // NO CAPTION ABOUT WHERE THE SELECTION CAME FROM.
      // "yours, edited by hand" narrated a thing the operator had just done,
      // in a voice nobody uses. The chips already show what is on.
      if (src) src.textContent = '';
      if (!note) return;
      // WAS: "All twenty states with a law we check. Filled means chosen;
      // outlined means your markets imply it." A legend for a control the
      // reader is already operating. What is left is the only part that
      // carries information they cannot see on the chips - a market of theirs
      // that has no law to test.
      var msg = '';
      if (noLaw.length) {{
        msg += '<span style="color:var(--muted)">' + noLaw.join(', ')
             + ' ' + (noLaw.length === 1 ? 'is' : 'are')
             + ' in your markets and ' + (noLaw.length === 1 ? 'has' : 'have')
             + ' no comprehensive law in our map \u2014 nothing to test there,'
             + ' which is a real answer rather than a gap.</span>';
      }}
      note.innerHTML = msg;
    }}

    // ---- state and product toggles ---------------------------------------
    function stSync() {{
      var on = [];
      document.querySelectorAll('#strow .tg').forEach(function (b) {{
        if (b.classList.contains('on') || b.classList.contains('auto')) {{
          on.push(b.dataset.st);
        }}
      }});
      var h = document.getElementById('cstates');
      if (h) h.value = on.join(' ');
    }}
    function stToggle(b) {{
      STATES_TOUCHED = true;
      b.dataset.pinned = '1';
      // A suggested state clicked once becomes a chosen one; clicked again it
      // is off and stays off even if the markets keep implying it.
      if (b.classList.contains('auto')) {{
        b.classList.remove('auto'); b.classList.add('on');
      }} else {{
        b.classList.toggle('on');
      }}
      stSync();
      var src = document.getElementById('cstatesrc');
      if (src) src.textContent = '';
    }}
    function prToggle(b) {{
      b.classList.toggle('on');
      var on = [];
      document.querySelectorAll('#prrow .tg.on').forEach(function (x) {{
        on.push(x.dataset.pr);
      }});
      var h = document.getElementById('consent_products');
      if (h) h.value = on.join(',');
    }}

    // ---- conversion URLs, same pill pattern as the markets ---------------
    var CONVS = [];
    function cvRender() {{
      var box = document.getElementById('cvpills');
      if (!box) return;
      box.innerHTML = CONVS.map(function (u, i) {{
        return '<span class="gp" title="' + geoEsc(u) + '"><b>'
             + geoEsc(u.replace(/^https?:\/\//, '').slice(0, 42))
             + '</b><button type="button" aria-label="Remove" onclick="cvDrop('
             + i + ')">&times;</button></span>';
      }}).join('');
      document.getElementById('conversion_urls').value = CONVS.join(' ');
    }}
    function cvDrop(i) {{ CONVS.splice(i, 1); cvRender(); }}

    // HARVEST URLS OUT OF WHATEVER GETS PASTED, and drop the rest.
    //
    // Lifted from the standalone scanner, which learned this the hard way:
    // people paste a line out of an email — "thank you page is
    // clientsite.com/thanks (and the quote form)" — and splitting on
    // whitespace turns every word into a pill. A real TLD is required, so
    // "e.g." and sentence fragments never qualify, and trailing punctuation
    // is stripped so a URL at the end of a sentence survives the full stop.
    function cvExtract(chunk) {{
      var out = [];
      var re = /(https?:\/\/[^\s,]+|(?:www\.)?[a-z0-9][a-z0-9-]*(?:\.[a-z]{{2,}})+(?:\/[^\s,]*)?)/gi;
      var m;
      while ((m = re.exec(chunk || ''))) {{
        var u = m[0].replace(/[)"'\]>,;.:]+$/, '');
        if (u.replace(/^https?:\/\//i, '').split('/')[0].indexOf('.') >= 0) {{
          out.push(u);
        }}
      }}
      return out;
    }}

    // Same normalization the scanner dedupes on: scheme, www and trailing
    // slashes are noise, so /contact and https://www.site.com/contact/ are
    // one URL rather than two pills that scan the same page twice.
    function cvNorm(u) {{
      return (u || '').trim().toLowerCase()
        .replace(/^https?:\/\//, '').replace(/^www\./, '')
        .replace(/\/+$/, '');
    }}

    function cvAdd(raw) {{
      var site = cvNorm((document.getElementById('turl') || {{}}).value || '');
      cvExtract(raw).forEach(function (u) {{
        var key = cvNorm(u);
        if (!key) return;
        // The homepage is already scanned. Adding it here would scan it twice
        // and double every pixel it finds.
        if (key === site) return;
        var dupe = CONVS.some(function (x) {{ return cvNorm(x) === key; }});
        if (!dupe) CONVS.push(u);
      }});
      cvRender();
    }}

    function geoInit() {{
      var input = document.getElementById('geoinput');
      if (!input) return;
      input.addEventListener('keydown', function (ev) {{
        // NOT ON A COMMA. "Knox County, TN" is one market and the comma is
        // inside it - committing on the keystroke split it in half before the
        // state had been typed.
        if (ev.key === 'Enter' || ev.key === 'Tab') {{
          if (!input.value.trim()) return;
          ev.preventDefault();
          geoAdd(input.value);
          input.value = '';
        }} else if (ev.key === 'Backspace' && !input.value && MARKETS.length) {{
          geoDrop(MARKETS.length - 1);
        }}
      }});
      // Typing a market and submitting without pressing Enter is the obvious
      // way to lose one, so commit whatever is in the box on blur too.
      input.addEventListener('blur', function () {{
        if (input.value.trim()) {{ geoAdd(input.value); input.value = ''; }}
      }});
      input.addEventListener('paste', function (ev) {{
        var t = (ev.clipboardData || window.clipboardData).getData('text');
        if (t && /[\u00d7;|\\n]/.test(t)) {{
          ev.preventDefault(); geoAdd(t); input.value = '';
        }}
      }});
      var cv = document.getElementById('cvinput');
      if (cv) {{
        cv.addEventListener('keydown', function (ev) {{
          if (ev.key === 'Enter' || ev.key === ',') {{
            ev.preventDefault(); cvAdd(cv.value); cv.value = '';
          }} else if (ev.key === 'Backspace' && !cv.value && CONVS.length) {{
            cvDrop(CONVS.length - 1);
          }}
        }});
        cv.addEventListener('blur', function () {{
          if (cv.value.trim()) {{ cvAdd(cv.value); cv.value = ''; }}
        }});
      }}
      var box = document.getElementById('geobox');
      if (box) box.addEventListener('click', function (ev) {{
        if (ev.target === box) input.focus();
      }});
      geoRender();
    }}
    geoInit();

    // Each job's settings appear only when that job is on.
    function jobSync() {{
      var a = document.getElementById('do_audit');
      var c = document.getElementById('do_consent');
      document.getElementById('auditopts').classList.toggle('on', !!(a && a.checked));
      document.getElementById('consentopts').classList.toggle('on', !!(c && c.checked));
      var go = document.getElementById('gobtn');
      var note = document.getElementById('gonote');
      var on = (a && a.checked) + (c && c.checked ? 1 : 0);
      if (go) go.disabled = !on;
      if (!note) return;
      note.textContent = !on ? 'Pick at least one.'
        : (a && a.checked && c && c.checked) ? 'Full audit and consent check.'
        : (a && a.checked) ? 'Full audit only.' : 'Consent check only.';
    }}
    jobSync();

    function prefill(btn) {{
      var st = JSON.parse(btn.dataset.prefill);
      var f = document.getElementById('auditform');
      ['target_url', 'client_name', 'vertical', 'max_pages',
       'primary_conversion', 'partner',
       'consent_industries', 'implementation'].forEach(function (k) {{
        var el = f.querySelector('[name=' + k + ']')
              || document.querySelector('[name=' + k + ']');
        if (el && st[k] !== undefined && st[k] !== '') el.value = st[k];
      }});
      // Markets are pills now, so they are rebuilt rather than assigned. The
      // hidden field follows from them, never the other way round.
      MARKETS = [];
      var gi = document.getElementById('geoinput');
      if (gi) gi.value = '';
      if (st.primary_markets) geoAdd(st.primary_markets);
      // States last: restoring a saved list counts as a hand edit, so the
      // markets do not immediately overwrite what was chosen last time.
      // Products and conversion URLs are toggles and pills, so they are
      // rebuilt rather than assigned.
      var want = (st.consent_products || '').split(',')
                   .map(function (x) {{ return x.trim(); }}).filter(Boolean);
      document.querySelectorAll('#prrow .tg').forEach(function (b) {{
        b.classList.toggle('on', want.indexOf(b.dataset.pr) >= 0);
      }});
      var ph = document.getElementById('consent_products');
      if (ph) ph.value = want.join(',');
      CONVS = [];
      if (st.conversion_urls) cvAdd(st.conversion_urls);
      if (st.consent_states) {{
        var cs = document.getElementById('cstates');
        if (cs) {{ cs.value = st.consent_states; STATES_TOUCHED = true; }}
        geoSyncStates();
      }}
      // Every checkbox the form owns, phases included. Restoring only two of
      // them is what silently turned "Ask the AI assistants" back off; a
      // partial restore is worse than none, because it looks like it worked.
      [['render_js', st.render_js], ['browser_ua', st.browser_ua],
       ['run_judgment', st.run_judgment], ['run_collectors', st.run_collectors],
       ['run_screenshots', st.run_screenshots], ['run_aivis', st.run_aivis],
       ['run_consent', st.run_consent], ['run_reputation', st.run_reputation],
       ['reuse_crawl', st.reuse_crawl]].forEach(
        function (p) {{
          if (p[1] === undefined) return;   // a run from before that box existed
          var el = document.querySelector('[name=' + p[0] + ']');
          if (el) el.checked = !!p[1];
        }});
      // WHICH JOB, NOT JUST WHICH PHASES.
      //
      // "Full audit" and "Consent check" sit ABOVE the phase list and were
      // the two boxes this function never touched — so Run again on a
      // consent-only run came back with Full audit ticked, because that is
      // the form's default and nothing overrode it. Every re-run of a consent
      // check was one unnoticed tick away from a 150-page crawl.
      var da = document.getElementById('do_audit');
      if (da && st.do_audit !== undefined) da.checked = !!st.do_audit;
      var dc = document.getElementById('do_consent');
      if (dc && st.run_consent !== undefined) dc.checked = !!st.run_consent;
      jobSync();   // opens the right settings panel and rewrites the note
      // The chosen properties need the dropdowns populated first, so run the
      // access check and apply them when it returns.
      //
      // GTM WAS NEVER IN HERE. Two of the three pickers were stashed and the
      // third was not, so a hand-picked container was dropped on every
      // re-run — and the operator had to find it again in a list of several
      // hundred, having already done that once.
      window._pendingProps = {{ gsc: st.gsc_property, ga4: st.ga4_property_id,
                               gtm: st.gtm_container }};
      // Land on the form with the client's name in view, and say what
      // happened — a button that silently changes a form 800px up the page
      // reads as a button that did nothing.
      var f2 = document.getElementById('auditform');
      if (f2) f2.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      var nm = f2 && f2.querySelector('[name=client_name]');
      if (nm) nm.focus();
      var gn = document.getElementById('gonote');
      if (gn) {{
        gn.textContent = 'Settings loaded from ' + (st.client_name || 'that run')
          + ' — change anything, then Scan site.';
        gn.style.color = 'var(--blue)';
      }}
      if (st.gsc_property || st.ga4_property_id || st.gtm_container)
        checkAccess();
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
    # NO BREADCRUMB HERE. A one-item trail reading "Site Scanner" directly
    # under a heading reading "Site Scanner" is not navigation — it is the
    # page name printed twice with a font change. The audit detail page keeps
    # its trail, because there the first item is a link back to this one.
    return _shell("Site Scanner", body, refresh=8 if running else None,
                  heading="Site Scanner",
                  # Amber in the tab for as long as anything is in flight.
                  tab="running" if running else None)


def _ext_version() -> str:
    """
    The extension version we are actually shipping, read off the manifest.

    It was typed into the install instructions as a literal and went stale
    three releases ago — so the one step whose whole job is "check you loaded
    the right thing" was telling people to look for a version that no longer
    exists. The zip is built from this same tree, so the manifest is the
    only honest source.
    """
    import json as _j, os as _os
    p = _os.path.join(_os.path.dirname(_os.path.dirname(
        _os.path.abspath(__file__))), "extension", "manifest.json")
    try:
        with open(p) as fh:
            return str(_j.load(fh).get("version") or "")
    except Exception:  # noqa: BLE001
        return ""


def _conly_run(a) -> bool:
    """Was this run asked for as a consent scan only?"""
    import json as _j
    try:
        o = _j.loads(a.get("options") or "{}")
    except Exception:  # noqa: BLE001
        return False
    return isinstance(o, dict) and str(o.get("quick") or "") == "consent"


def _conv_urls_for(a) -> list:
    """The client's conversion URLs, for a capture that has to visit them."""
    import json as _j
    try:
        o = _j.loads(a.get("options") or "{}")
    except Exception:  # noqa: BLE001
        return []
    return list((o or {}).get("conversion_urls") or []) if isinstance(o, dict) else []


def audit_html(a):
    """Live status page shown while an audit is still running."""
    import json as _json
    order = ["queued", "crawling", "checking", "scoring", "ready"]
    cur = a["status"]
    idx = order.index(cur) if cur in order else 0
    # The rail keeps the same five stops for a consent-only run — the states
    # are real — but "crawling" describes fetching one page in a browser, and
    # naming it that had the reader waiting for 150.
    try:
        _oq = _json.loads(a.get("options") or "{}")
        if isinstance(_oq, dict) and str(_oq.get("quick") or "") == "consent":
            order = ["queued", "loading", "checking", "scoring", "ready"]
    except Exception:  # noqa: BLE001
        pass
    marks = "".join(
        f"<span class='{'on' if i == idx else ('done' if i < idx else '')}'>{s}</span>"
        for i, s in enumerate(order))

    if cur == "failed":
        inner = (f"<div class='card'><b style='color:var(--critical)'>Audit failed</b>"
                 f"<p class='sub'>{e(a.get('error'))}</p>"
                 f"</div>")
        refresh = None
    elif cur == "canceled":
        # Not an error page. Nothing went wrong; somebody decided this run was
        # not worth finishing, and the offer is to start it again cheaply -
        # from the stored pages, so the client's server is left alone.
        done = a.get("pages_crawled") or 0
        inner = (f"<div class='card'><b>Stopped</b>"
                 f"<p class='sub'>{e(a.get('progress') or 'stopped on request')}"
                 + (f" {done} pages were crawled before it stopped, and every "
                    f"checkpoint answered up to that point is kept."
                    if done else "")
                 + f"</p>"
                 f"<form method='post' action='/audits/{e(a['id'])}/rerun' "
                 f"style='margin-top:12px'>"
                 f"<input type='hidden' name='reuse_crawl' value='1'>"
                 f"<button class='btn' type='submit'>Run it again from the "
                 f"stored pages</button></form></div>")
        refresh = None
    elif cur == "needs_capture" and _conly_run(a):
        # A CONSENT RUN THAT GOT BLOCKED NEEDS THE CONSENT CAPTURE.
        #
        # This page offered the CRAWL capture to every blocked run, including
        # the consent-only ones — and that button runs the wrong job: it posts
        # pages to an endpoint that scores 322 checkpoints, so a consent scan
        # came back as a full audit nobody selected with the nine consent rows
        # still empty. Same screen, same handoff, the right button on it.
        from .ui_consent import _capture_panel as _cp, _PAGE_CSS as _pcss
        inner = (
            _pcss
            + f"<div class='card' style='border-left:3px solid var(--serious)'>"
              f"<b style='color:var(--serious)'>Server crawl blocked</b>"
              f"<p class='sub'>{e(a.get('crawl_note') or a.get('progress'))}</p>"
              f"<p class='sub'>Nothing has been reported as a defect — a "
              f"blocked crawl is a handoff, not a result. This run asked for "
              f"the consent scan only, so the capture below is the consent "
              f"one: four loads in your own Chrome, and the nine consent "
              f"rows come back answered.</p></div>"
            + _cp(a["id"], a["target_url"],
                  "The server's browser was turned away before it could load "
                  "the banner.",
                  heading="Capture it from your own browser",
                  extra_urls=_conv_urls_for(a)))
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
            f"<p class='sub'><b>The Site Scanner extension is not installed in this "
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
            f"You should see <b>Site Scanner {e(_ext_version())}</b>.</li>"
            f"<li>Reload this page — the Start capture button appears once "
            f"the extension is detected.</li></ol>"
            f"<p class='sub' style='margin-top:10px'>"
            f"<a href='{e(_ext_link('crawl', a['id'], a['target_url']))}'>"
            f"<b>Open the extension directly</b></a> &mdash; the id travels "
            f"with the link, and it works on whatever version is installed. "
            f"Or drive it by hand: open the site, click the extension, and "
            f"paste audit id <code>{e(a['id'])}</code> "
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
        if stale and a.get("cancel_at"):
            # ASKED TO STOP, AND THEN INTERRUPTED.
            #
            # Without this the stall detector wins and the page reports "this
            # run has stopped responding" - which reads as a fault, on a run
            # the person deliberately ended. Pressing Stop again closes the
            # row outright; the API sees the dead heartbeat and does not wait.
            inner = (f"<div class='card'><b>Stopping</b>"
                     f"<p class='sub'>This run was interrupted before it could "
                     f"stop cleanly - most often a deploy going out mid-scan. "
                     f"Everything answered before that point is kept.</p>"
                     f"<form method='post' action='/audits/{e(a['id'])}/stop' "
                     f"style='margin-top:12px'>"
                     f"<button class='btn' type='submit'>Close it out"
                     f"</button></form></div>")
            refresh = None
        elif stale:
            mins = int((_time.time() - float(hb)) // 60)
            inner = (rail + f"<div class='marks'>{marks}</div>"
                     f"<div class='card' style='margin-top:16px'>"
                     f"<b>This run has stopped responding.</b>"
                     f"<p class='sub'>The last progress update was {mins} minutes "
                     f"ago, at &ldquo;{e(a.get('progress') or cur)}&rdquo;. That "
                     f"usually means the run was interrupted — a deploy, "
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
            # STOP, WHERE THE RUN IS.
            #
            # There was no way to end a run except waiting for it or deleting
            # the row, and deleting takes the findings with it. The button
            # writes a flag the worker reads at its next progress step; the
            # copy says that rather than implying an instant kill, because a
            # control that claims to be immediate and takes ten seconds reads
            # as broken.
            stopping = bool(a.get("cancel_at"))
            act = ("<p class='sub' style='margin-top:12px'><b>Stopping.</b> "
                   "It stops at the end of the step it is on; everything "
                   "answered so far is kept.</p>" if stopping else
                   f"<form method='post' action='/audits/{e(a['id'])}/stop' "
                   f"style='margin-top:12px'>"
                   f"<button class='btn ghost' type='submit'>Stop this run"
                   f"</button>"
                   f"<span class='sm' style='color:var(--muted);"
                   f"margin-left:9px'>keeps whatever has been answered"
                   f"</span></form>")
            # HOW LONG IT HAS BEEN SAYING THAT.
            #
            # "been stuck on this page a while - does something seem broken?"
            # The message was true, the run was alive, and the page still could
            # not answer the question - because a status with no age on it
            # reads the same at ten seconds and at nine minutes. Until the
            # stall detector fires at STALE_AFTER_S there was NOTHING on screen
            # that changed, so the only way to tell a working run from a dead
            # one was to wait out the ten minutes and see.
            #
            # The age is always shown, so the reader can watch it reset instead
            # of inferring progress from a spinner that spins either way. Past
            # a couple of minutes it also says what long looks like for this
            # phase, because "4 minutes" only means something next to a normal.
            _age = int(_time.time() - float(hb)) if hb else None
            if _age is None:
                since = ""
            elif _age < 90:
                since = (f"<span class='sm' style='color:var(--muted)'>"
                         f"updated {_age}s ago</span>")
            else:
                _m = _age // 60
                since = (f"<span class='sm' style='color:var(--warning)'>"
                         f"updated {_m} minute{'s' if _m != 1 else ''} ago"
                         f"</span>")
            # WHAT THIS RUN IS DOING, NOT WHAT A RUN DOES.
            #
            # "A full crawl of 150 pages typically takes 2-5 minutes" was
            # printed under every run including the consent-only ones, which
            # load one page in a browser and take well under a minute. A
            # normal is the whole value of this line: quoting the wrong one
            # makes a finished-in-40-seconds job look stalled and a genuinely
            # slow one look early. The options say which job this is, so it
            # says which job this is.
            try:
                _o = _json.loads(a.get("options") or "{}")
                _o = _o if isinstance(_o, dict) else {}
            except Exception:  # noqa: BLE001
                _o = {}
            _conly = str(_o.get("quick") or "") == "consent"
            _mp = int(_o.get("max_pages") or 150)
            # A SENTENCE NOBODY READS TWICE.
            #
            # "A consent check loads the site in a browser, clicks the banner
            # and watches what fires — usually under a minute, longer on a
            # site with many pages to walk" is true, and it is three lines of
            # explanation under a status line that already says what is
            # happening. Somebody watching a progress page wants one thing:
            # to know it is alive. The bar below says that in no words.
            _eta = ("This page refreshes automatically."
                    if _conly else
                    f"This page refreshes automatically. A full crawl of "
                    f"{_mp} page{'s' if _mp != 1 else ''} typically takes "
                    f"2–5 minutes.")
            _slow = ("<p class='sub'>Steps that take a few minutes on their "
                     "own: the AI assistants, the reputation scan, and the "
                     "evidence screenshots. This page marks the run as "
                     "stopped if nothing moves for "
                     f"{STALE_AFTER_S // 60} minutes.</p>"
                     if _age is not None and _age >= 120 and not _conly else
                     ("<p class='sub'>Still going. A consent check waits for "
                      "each page to fall quiet rather than counting seconds, "
                      "so a slow site takes longer. Marked as stopped if "
                      f"nothing moves for {STALE_AFTER_S // 60} minutes.</p>"
                      if _age is not None and _age >= 120 else ""))
            inner = (rail + f"<div class='marks'>{marks}</div>"
                     f"<div class='card' style='margin-top:16px'>"
                     f"<span class='spin'></span> <b>{e(a.get('progress') or cur)}</b>"
                     f"&nbsp; {since}"
                     f"<div class='glide'><i></i></div>"
                     f"<p class='sub'>{_eta}</p>"
                     f"{_slow}{act}</div>")
            # Six seconds, not four. Every refresh is a full page render and a
            # fresh database connection, and the phase this page is most often
            # watching is now the longest one in the run.
            refresh = 6

    body = (f"<div class='sub'><code>{e(a['target_url'])}</code> · "
            f"audit <code>{e(a['id'])}</code></div>{inner}")
    return _shell(f"{a['client_name']} — running", body, refresh=refresh,
                  heading=a["client_name"],
                  crumbs=[("Site Scanner", "/"), (a["client_name"], None)],
                  tab="running" if cur in ("queued", "crawling", "checking",
                                           "scoring") and not stale else None)
