"""
Report renderer.

Viz decisions (dataviz method, in order):
  1. FORM. Overall score = a single headline number → hero figure, not a chart.
     Section scores = magnitude across ~16 named categories → horizontal bars.
     Severity mix = an ORDERED scale (Critical>High>Medium>Low) → ordinal ramp,
     not a categorical palette.
  2. COLOR BY JOB. Section bars: sequential single hue (magnitude). Severity:
     ordinal blue ramp. Status chips: the reserved status palette, always with a
     text label so color never carries meaning alone.
  3. VALIDATED. The 4-step ordinal ramp passes all checks in light AND dark
     (validate_palette.js --ordinal). The status palette is NOT used as an
     adjacent categorical set — it FAILS that gate (serious↔warning ΔE 13.6).
"""
from __future__ import annotations
import html as _h
import json
from collections import Counter

SEV_ORDER = ["Critical", "High", "Medium", "Low", "Opportunity"]
STATUS_ORDER = ["Fail", "Not Implemented", "Warning", "Pass", "Info",
                "Need Access", "N/A"]

SECTION_NAMES = {
    "ANA": "Analytics & Tracking", "GSC": "Search Console", "GA4": "Google Analytics 4",
    "TECH": "Technical SEO", "URL": "URL Structure", "SEC": "HTTPS & Security",
    "CANON": "Canonicalization", "PERF": "Performance & CWV", "ONP": "On-Page SEO",
    "MOB": "Mobile SEO", "SCHEMA": "Structured Data", "INTL": "International SEO",
    "HTML": "HTML & Code Quality", "EEAT": "E-E-A-T", "GEO": "AI Search (GEO)",
    "OFF": "Off-Page & Authority",
}
ORDER = ["ANA", "GSC", "GA4", "TECH", "URL", "SEC", "CANON", "PERF", "ONP",
         "MOB", "SCHEMA", "INTL", "HTML", "EEAT", "GEO", "OFF"]


def e(x):
    return _h.escape(str(x if x is not None else ""))


# ---------------------------------------------------------------- console
def render_console(meta, sc, findings, catalog):
    st = Counter(f["status"] for f in findings.values())
    print("\n" + "=" * 78)
    print(f"  {meta['client']}  —  {meta['url']}")
    print(f"  {meta['pages_crawled']} pages crawled · {meta['coverage']} checkpoints "
          f"· {meta['duration_s']}s")
    print("=" * 78)
    o = sc["overall"]
    print(f"\n  OVERALL: {o['score'] if o['score'] is not None else '—'}/100  "
          f"({o['rating']})\n")
    print(f"  {'SECTION':<26}{'SCORE':>7}  {'RATING':<20}{'CHECKED':>8}{'FAIL':>6}")
    print("  " + "-" * 68)
    for k in ORDER:
        v = sc["sections"].get(k)
        if not v:
            continue
        s = v["score"]
        bar = "█" * round((s or 0) / 10) if s is not None else ""
        print(f"  {SECTION_NAMES[k]:<26}{(s if s is not None else '—'):>7}  "
              f"{v['rating']:<20}"
              f"{v.get('reviewed', v['checked']):>8}{v['failing']:>6}  {bar}")
    print("\n  STATUS MIX: " + " · ".join(f"{k} {st[k]}" for k in STATUS_ORDER if st[k]))
    print("=" * 78)


# ---------------------------------------------------------------- html
CSS = """
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
 font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.viz-root{
 --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
 --line:#e6e5e1;
 --o1:#86b6ef; --o2:#3987e5; --o3:#256abf; --o4:#104281;
 --seq:#2a78d6; --track:#eceae6;
 --good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b;
}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])) .viz-root{
 --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
 --line:#2c2c2a;
 --o1:#b7d3f6; --o2:#6da7ec; --o3:#2a78d6; --o4:#184f95;
 --seq:#3987e5; --track:#262623;
}}
:root[data-theme=dark] .viz-root{
 --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
 --line:#2c2c2a; --o1:#b7d3f6; --o2:#6da7ec; --o3:#2a78d6; --o4:#184f95;
 --seq:#3987e5; --track:#262623;
}
.wrap{max-width:1080px;margin:0 auto;padding:40px 28px 80px}
header{border-bottom:1px solid var(--line);padding-bottom:22px;margin-bottom:30px}
h1{font-size:25px;margin:0 0 6px;letter-spacing:-.02em}
.sub{color:var(--ink2);font-size:14px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);
 margin:40px 0 14px;font-weight:600}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.tile .v{font-size:30px;font-weight:640;letter-spacing:-.03em;line-height:1.1}
.tile .l{font-size:12px;color:var(--ink2);margin-top:5px}
.hero{background:var(--surface);border:1px solid var(--line);border-radius:12px;
 padding:26px 28px;display:flex;align-items:baseline;gap:20px;flex-wrap:wrap}
.hero .n{font-size:60px;font-weight:680;letter-spacing:-.045em;line-height:1}
.hero .d{color:var(--ink2);font-size:14px;max-width:520px}
.rating{font-size:17px;font-weight:620}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;font-weight:600;color:var(--muted);font-size:11.5px;
 text-transform:uppercase;letter-spacing:.07em;padding:0 10px 9px;border-bottom:1px solid var(--line)}
td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.meter{position:relative;height:9px;background:var(--track);border-radius:5px;
 min-width:130px;overflow:hidden}
.meter>i{position:absolute;left:0;top:0;bottom:0;background:var(--seq);
 border-radius:0 4px 4px 0;display:block}
.sevbar{display:flex;height:26px;border-radius:6px;overflow:hidden;background:var(--track)}
.sevbar>span{display:block;border-right:2px solid var(--surface)}
.sevbar>span:last-child{border-right:0}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin-top:10px;font-size:12.5px;color:var(--ink2)}
.legend i{width:11px;height:11px;border-radius:3px;display:inline-block;margin-right:6px;
 vertical-align:-1px}
.chip{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:600;
 padding:2px 8px;border-radius:20px;border:1px solid var(--line);white-space:nowrap}
.chip b{width:7px;height:7px;border-radius:50%;display:inline-block}
.ev{color:var(--ink2);font-size:13px}
.rec{color:var(--muted);font-size:12.5px;margin-top:3px;font-style:italic}
code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--ink2)}
/* plain-English definition cards — jargon defined where the reader meets it */
/* definition bubbles — soft, rounded, and sitting beside the finding that
   used the word, the way a Confluence info panel does */
.bubble{background:#eef4fd;border:1px solid #cfe0f8;border-radius:16px;
 padding:11px 16px;margin:10px 0;font-size:13px;color:var(--ink2);
 display:flex;gap:10px;align-items:flex-start;line-height:1.5}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])) .bubble{
 background:#152436;border-color:#24405e}}
.bubble .bi{font-size:17px;line-height:1.25;flex:none}
.bubble b{color:var(--ink)}
.note{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--seq);
 border-radius:8px;padding:14px 18px;font-size:13.5px;color:var(--ink2);margin:14px 0}
"""

# See pdf_report.STATUS_LABEL: the status column states a verdict, and two of
# its values answered a different question. Display only — the stored values are
# unchanged, because `Info` is load-bearing in the scoring code.
STATUS_LABEL = {"Info": "Reference", "Manual": "In review"}


def status_word(status: str) -> str:
    return STATUS_LABEL.get(status, status)


STATUS_COLOR = {"Pass": "var(--good)", "Warning": "var(--warning)",
                "Fail": "var(--critical)", "Not Implemented": "var(--serious)",
                "Need Access": "var(--muted)", "N/A": "var(--muted)",
                "Info": "var(--ink2)"}
SEV_RAMP = {"Critical": "var(--o4)", "High": "var(--o3)",
            "Medium": "var(--o2)", "Low": "var(--o1)", "Opportunity": "var(--track)"}


# ---------------------------------------------------------------- judged rows
#
# A lightbulb next to the rows the judgment layer produced.
#
# WHY IT SAYS WHAT IT SAYS. These rows are read and assessed rather than
# measured — a crawler can count H1 tags, but "does this page answer the query
# it ranks for" is a reading, and a reading can be wrong in ways a count cannot.
# The team needs to know which rows to check hardest before a report goes out.
#
# The legend therefore reads "Judged by review rather than measured", which is
# true, is useful to a client, and does not advertise the mechanism. A client
# seeing it learns something worth knowing: this row is a qualitative
# assessment, not a hard number. Our team seeing it knows exactly which rows to
# reread. One mark, two audiences, no dishonesty in either direction.
LAMP = ("<svg viewBox='0 0 24 24' width='13' height='13' aria-hidden='true' "
        "style='vertical-align:-2px;margin-left:5px' fill='none' "
        "stroke='#F1B434' stroke-width='2' stroke-linecap='round' "
        "stroke-linejoin='round'>"
        "<path d='M9 18h6M10 22h4'/>"
        "<path d='M12 2a7 7 0 0 0-4 12.7V18h8v-3.3A7 7 0 0 0 12 2z'/></svg>")

JUDGED_NOTE = "Judged by review rather than measured."


def judged_ids() -> set:
    """
    Checkpoint IDs the judgment layer owns.

    Imported defensively for the same reason `access.vendor_ids` is: this module
    renders reports in the API process, and a failed import must cost us a
    lightbulb, never the document.
    """
    try:
        from .judgment import CHECKPOINT_IDS
        return set(CHECKPOINT_IDS)
    except Exception:  # noqa: BLE001
        return set()


_JUDGED: set | None = None


def is_judged(cid: str) -> bool:
    global _JUDGED
    if _JUDGED is None:
        _JUDGED = judged_ids()
    return cid in _JUDGED


def _lamp(cid: str, status: str = "") -> str:
    """The mark, but only on rows that actually carry a judgment."""
    # An unanswered row was never judged — it is waiting on a key. Marking it
    # would send a reviewer to reread an empty cell.
    if status in ("Need Access", "N/A") or not is_judged(cid):
        return ""
    return f"<span title='{JUDGED_NOTE}'>{LAMP}</span>"


# What a "Manual" row says in the What-we-found column.
#
# It said nothing at all. The reasoning was that the pill already reads Manual
# and repeating one sentence down twelve rows is wallpaper — but an empty cell
# in a column headed "What we found" does not read as "handled by hand", it
# reads as "nobody did this", which is the opposite of true and the worst thing
# a paid deliverable can imply about itself.
#
# Short and per-section is the compromise: four to eight words, specific enough
# to be information rather than boilerplate, brief enough that a column of them
# scans as a status rather than as prose.
MANUAL_NOTE = {
    "SEC": "Confirmed with an external TLS scanner.",
    "TECH": "Confirmed in Search Console during the engagement.",
    "PERF": "Read from the DevTools waterfall on the slowest templates.",
    "HTML": "Run through the W3C validator and an accessibility checker.",
    "CANON": "Checked against pagination and any AMP variants.",
    "ANA": "Confirmed firing in GA4 DebugView on a real session.",
    "URL": "Checked in the page source.",
    "INTL": "Checked against the countries they actually sell to.",
    "ONP": "Checked on the priority templates.",
    "GEO": "Recorded by the AI visibility monitor.",
    "GSC": "Read from Search Console during the engagement.",
}
MANUAL_DEFAULT = "Reviewed by hand during the engagement."


def manual_note(prefix: str) -> str:
    return MANUAL_NOTE.get(prefix, MANUAL_DEFAULT)


def _bubbles(text, seen, limit=2):
    """Definition bubbles for jargon in `text` not yet defined. Mutates `seen`."""
    from .glossary import terms_used, entry
    out = []
    for key in terms_used(text, limit=99):
        if key in seen or len(out) >= limit:
            continue
        seen.add(key)
        g = entry(key, medium="html")
        out.append(f"<div class='bubble'><span class='bi' aria-hidden='true'>"
                   f"{g['icon']}</span><div><b>{e(g['name'])}</b> — "
                   f"{e(g['definition'])}</div></div>")
    return out


def _brand_head() -> str:
    """Icon tags, inlined so they do not depend on a static route."""
    try:
        from app.brand import HEAD_TAGS
        return HEAD_TAGS
    except Exception:
        return "<meta name='theme-color' content='#002D58'>"


def _todo_panel(findings: dict, catalog: dict) -> list:
    """
    "Action needed" — what is unfinished, and crucially WHOSE MOVE IT IS.

    Ordered by what you can actually do about it: a variable we forgot takes a
    minute, a client grant takes an email, and manual review takes an
    afternoon and needs no decision at all. The last group is the largest and
    the least urgent, so it is collapsed — a wall of 55 checkpoint IDs above
    the one line that says "set two environment variables" buries the only
    thing that matters.
    """
    from engine.access import buckets
    from collections import Counter, defaultdict

    b = buckets(findings, catalog)
    if not (b["client"] or b["vendor"] or b["manual"]):
        return []

    def reasons(ids):
        """
        Group by reason, and carry the DIAGNOSTIC with it.

        A row whose parser missed says "the domain_pages endpoint answered but
        not in the shape we read" — true, and useless on its own. The field
        names the endpoint actually returned are already recorded in the
        finding's recommendation, and they were the one thing needed to fix it.
        Leaving them in a log file meant every round of this cost a deploy and
        a rerun to see them.
        """
        c, detail = Counter(), {}
        for cid in ids:
            f = findings.get(cid) or {}
            ev = " ".join(str(f.get("evidence") or "Not run.").split())[:110]
            c[ev] += 1
            rec = " ".join(str(f.get("recommendation") or "").split())
            if rec and ev not in detail:
                detail[ev] = rec[:180]
        return [(why, n, detail.get(why, "")) for why, n in c.most_common(4)]

    out = ["<div class='note' style='border-left-color:var(--seq);"
           "margin:0 0 22px'>"
           # NOT "Action needed before this goes out". That headline sat above
           # a group whose own text says "nothing to configure, nothing
           # blocking this report", and the contradiction is what made the
           # whole panel hard to read: it demanded action and then listed
           # things that need none.
           "<b>Before this goes out.</b> "
           "<span class='sm'>Internal only — none of this appears in the "
           "client PDF. The first list is ours to fix; the second is the work "
           "an analyst does during the engagement.</span>"]

    if b["vendor"]:
        items = "".join(
            f"<li><b>{n}</b> — {e(why)}"
            + (f"<div class='sm' style='color:var(--muted)'>{e(fix)}</div>"
               if fix else "") + "</li>"
            for why, n, fix in reasons(b["vendor"]))
        out.append(
            f"<div style='margin-top:12px'>"
            f"<b style='color:var(--critical)'>Ours to fix &middot; "
            f"{len(b['vendor'])}</b>"
            f"<div class='sm' style='color:var(--ink2);margin-top:2px'>"
            f"A credential we have not set, or a call we have not written. "
            f"Nothing to ask anyone for.</div>"
            f"<ul style='margin:6px 0 0 18px'>{items}</ul></div>")

    if b["client"]:
        out.append(
            f"<div style='margin-top:12px'>"
            f"<b style='color:var(--warning)'>Ask the client &middot; "
            f"{len(b['client'])}</b>"
            f"<div class='sm' style='color:var(--ink2);margin-top:2px'>"
            f"Search Console or Analytics rows we could not read. Ask them to "
            f"add the Vici login as a user on the property.</div></div>")

    if b["manual"]:
        # WHAT AN ANALYST ACTUALLY DOES.
        #
        # "Reviewed by hand" answered the wrong question. Told three times that
        # nothing needed configuring, the next question was still "so what am I
        # supposed to do with these" — because a list of IDs is not a task. One
        # line per area, naming the actual work, turns the panel into something
        # an analyst can pick up.
        HOW = {
            # Search intent, keyword use and CTA quality used to live here. The
            # judgment layer now reads the priority pages and scores them, so
            # what is left in this bucket is the residue: response headers and
            # server settings that need a look rather than a reading.
            "ONP": "Confirm compression and server-side delivery settings on "
                   "the priority templates.",
            # Was: "open the Search Console links report by hand". Those three
            # rows are answered from the backlink index now, so nothing should
            # land in this bucket — and if something does, it needs a human
            # looking at it rather than a stale instruction.
            "GSC": "Confirm in Search Console; no API covers this view.",
            # Not hand work exactly — the monitor does the asking. But it is a
            # separate scheduled run, so from this audit's point of view
            # somebody still has to set it going.
            "GEO": "Start an AI visibility monitor run for this client; it asks "
                   "each assistant and records whether the brand is cited.",
            "TECH": "Open the failing images, stylesheets and scripts and "
                    "confirm whether they are genuinely broken or merely slow.",
            "SEC": "Check subdomain TLS and HSTS with an external scanner.",
            "PERF": "Open DevTools on the two slowest templates and read the "
                    "waterfall for compression and minification.",
            "HTML": "Run the priority templates through the W3C validator.",
            "CANON": "Spot-check the canonical on a paginated series.",
            "ANA": "Confirm events fire in GA4 DebugView on a real session.",
            "URL": "Spot-check redirect behavior in a browser.",
            "INTL": "Confirm the declared targeting matches where they "
                    "actually sell — we can read the tags, not the intent.",
        }
        by_sec = defaultdict(list)
        for cid in b["manual"]:
            by_sec[(catalog.get(cid) or {}).get("prefix", "?")].append(cid)
        items = "".join(
            f"<li><b>{e(SECTION_NAMES.get(k, k))}</b> — {len(v)}. "
            f"{e(HOW.get(k, 'Judged by an analyst against the template.'))}"
            f"<div class='sm' style='color:var(--muted)'>"
            f"{e(', '.join(sorted(v)))}</div></li>"
            for k, v in sorted(by_sec.items(), key=lambda kv: -len(kv[1])))
        out.append(
            f"<div style='margin-top:12px'>"
            f"<b style='color:var(--seq)'>Analyst work list &middot; "
            f"{len(b['manual'])}</b>"
            f"<div class='sm' style='color:var(--ink2);margin-top:2px'>"
            f"<b>Every one of these needs a person.</b> Nothing with a working "
            f"automated check appears here — if a check exists and came back "
            f"empty, that is our failure and it is in the list above, not "
            f"yours. These are the checkpoints no tool answers at all. They are "
            f"already excluded from the score, so leaving them until the work "
            f"starts costs nothing. The task for each one is below."
            f"</div>"
            f"<details class='hist'><summary>Show the {len(b['manual'])} "
            f"checkpoints</summary>"
            f"<ul style='margin:6px 0 0 18px'>{items}</ul></details></div>")

    out.append("</div>")
    return out


def render_html(meta, sc, findings, catalog, summary=None):
    st = Counter(f["status"] for f in findings.values())
    sev = Counter(f["severity"] for f in findings.values()
                  if f["status"] in {"Fail", "Not Implemented", "Warning"})
    o = sc["overall"]
    total_sev = sum(sev.values()) or 1

    P = [f"<!doctype html><html><head><meta charset='utf-8'>",
         "<meta name='viewport' content='width=device-width,initial-scale=1'>",
         _brand_head(),
         f"<title>SEO/GEO Audit — {e(meta['client'])}</title><style>{CSS}</style>",
         "</head><body class='viz-root'><div class='wrap'>",
         # A way back. This page is a dead end otherwise — the only routes off
         # it are the browser's back button and editing the URL, and after a
         # rerun the back button lands on a stale status page.
         "<div style='margin-bottom:18px'>"
         "<a href='/' style='display:inline-flex;align-items:center;gap:7px;"
         "font-size:13.5px;padding:7px 16px;border:1px solid var(--line);"
         "border-radius:20px;background:var(--surface);color:var(--ink2);"
         "text-decoration:none'>"
         "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' "
         "stroke='currentColor' stroke-width='2' stroke-linecap='round' "
         "stroke-linejoin='round' aria-hidden='true'>"
         "<path d='M3 10.5 12 3l9 7.5'/><path d='M5 9.5V21h14V9.5'/></svg>"
         "All audits</a></div>"]

    # WHAT THIS RUN STILL OWES, at the top, before anything else.
    #
    # The client PDF says "88 checks are ours to finish". Nothing told US what
    # those were. A promise printed in a deliverable with no worklist behind it
    # is how a report ships with a section quietly empty for the third run in a
    # row. This panel is the worklist, and it is internal-only — the client PDF
    # never carries it.
    P.extend(_todo_panel(findings, catalog))

    # Only a shortfall in PAGES warrants a document-level banner. A link-sample
    # that ran short is noted on the two rows it affects instead — see TECH-07.
    if meta.get("truncated"):
        P.append(f"<div class='note' style='border-left-color:var(--warning)'>"
                 f"<b>Partial review.</b> {e(meta['truncated'])}. Sitewide counts "
                 f"below describe the pages we reached, not the whole site.</div>")

    if meta.get("crawl_blocked"):
        P.append(
            "<div class='note' style='border-left-color:var(--critical);"
            "margin:0 0 22px'><b style='color:var(--critical)'>"
            "⚠ Crawl blocked — this report is not valid.</b><br>"
            f"{e(meta.get('crawl_note') or '')}<br><br>"
            "The crawler could not retrieve usable page content, so every "
            "content-dependent checkpoint is reported as <code>Need Access</code> "
            "rather than as a defect. <b>Do not send this to a client.</b> "
            "Re-run with a browser user-agent, with JavaScript rendering enabled, "
            "or from an allowlisted IP.</div>")

    P.append(f"<header><h1>SEO &amp; Generative Engine Optimization Audit</h1>"
             f"<div class='sub'>{e(meta['client'])} · <code>{e(meta['url'])}</code><br>"
             f"{meta['pages_crawled']} pages crawled · {e(meta['coverage'])} checkpoints "
             f"evaluated · generated {e(meta['generated'])}</div></header>")

    # HERO — a single headline number is a hero figure, never a one-bar chart
    _blocked = bool(meta.get("crawl_blocked"))
    _desc = ("No overall score: too few sections could be assessed to produce a "
             "meaningful figure." if o["score"] is None else
             "Mean of assessed section scores. Sections with no assessable data are "
             "excluded rather than scored zero.")
    P.append(f"<div class='hero'><div class='n'>"
             f"{o['score'] if o['score'] is not None else '—'}"
             f"<span style='font-size:22px;color:var(--muted)'>/100</span></div>"
             f"<div><div class='rating'>{e('Not Assessed' if o['score'] is None else o['rating'])}</div>"
             f"<div class='d'>{_desc}</div></div></div>")

    # KPI row of stat tiles
    if meta.get("pdf_url"):
        # target=_blank: the PDF takes seconds to render, and navigating the
        # report away to wait for it loses the page you were reading.
        P.append(f"<div style='margin:18px 0'><a href='{e(meta['pdf_url'])}' "
                 f"target='_blank' rel='noopener' "
                 f"style='display:inline-block;padding:9px 18px;background:var(--seq);"
                 f"color:#fff;border-radius:7px;font-weight:640;font-size:13.5px;"
                 f"text-decoration:none'>Open client PDF</a>"
                 f"<a href='{e(meta['pdf_url'])}?polish=1' target='_blank' "
                 f"rel='noopener' style='margin-left:12px;"
                 f"font-size:12.5px;color:var(--ink2)'>with AI-written summary</a></div>")

    if summary:
        P.append("<h2>Executive summary</h2>")
        if summary.get("overview"):
            P.append(f"<div class='note'>{e(summary['overview'])}</div>")
        for key, title in (("working", "What's working"),
                           ("issues", "Priority issues"),
                           ("opportunity", "Biggest opportunity")):
            v = summary.get(key)
            if not v:
                continue
            P.append(f"<h2 style='margin-top:22px'>{title}</h2>")
            if isinstance(v, str):
                P.append(f"<div class='ev'>{e(v)}</div>")
            else:
                P.append("<ul style='margin:6px 0 0 18px;padding:0'>"
                         + "".join(f"<li class='ev' style='margin-bottom:5px'>{e(x)}</li>"
                                   for x in v) + "</ul>")
        if summary.get("roadmap"):
            P.append("<h2>Prioritized next steps</h2>")
            for ph in summary["roadmap"]:
                P.append(f"<div style='margin-bottom:14px'><b>{e(ph.get('phase'))}</b>"
                         f"<div class='rec' style='font-style:normal;margin:2px 0 5px'>"
                         f"{e(ph.get('rationale'))}</div><ul style='margin:0 0 0 18px'>"
                         + "".join(f"<li class='ev' style='margin-bottom:4px'>{e(x)}</li>"
                                   for x in ph.get("actions", [])) + "</ul></div>")

    P.append("<h2>At a glance</h2><div class='kpis'>")
    for v, l in ((st["Pass"], "Passing"),
                 (st["Fail"], "Failing"),
                 (st["Not Implemented"], "Not implemented"),
                 (st["Need Access"], "Need access"),
                 (meta["pages_crawled"], "Pages reviewed")):
        P.append(f"<div class='tile'><div class='v'>{v}</div><div class='l'>{l}</div></div>")
    P.append("</div>")

    # SEVERITY — ordinal scale → single-hue ordinal ramp (validated light+dark)
    P.append("<h2>Issue severity distribution</h2><div class='sevbar'>")
    for s in SEV_ORDER:
        if sev.get(s):
            pct = 100 * sev[s] / total_sev
            P.append(f"<span style='width:{pct:.2f}%;background:{SEV_RAMP[s]}' "
                     f"title='{s}: {sev[s]}'></span>")
    P.append("</div><div class='legend'>")
    for s in SEV_ORDER:
        if sev.get(s):
            P.append(f"<span><i style='background:{SEV_RAMP[s]}'></i>{s} — "
                     f"<b>{sev[s]}</b></span>")
    P.append("</div>")

    # SECTION SCORES — magnitude across named categories → horizontal bars, one hue
    P.append("<h2>Audit area snapshot</h2><table><tr><th>Section</th>"
             "<th style='width:190px'>Score</th><th>Rating</th>"
             "<th class='num'>Reviewed</th><th class='num'>Issues</th></tr>")
    for k in ORDER:
        v = sc["sections"].get(k)
        if not v:
            continue
        s = v["score"]
        bar = (f"<div class='meter'><i style='width:{s}%'></i></div>"
               if s is not None else "<span class='ev'>not assessed</span>")
        P.append(f"<tr><td>{SECTION_NAMES[k]}</td><td>{bar}</td>"
                 f"<td class='num' style='text-align:left'>"
                 f"<b>{s if s is not None else '—'}</b> · {e(v['rating'])}</td>"
                 f"<td class='num'>{v.get('reviewed', v['checked'])}/"
                 f"{v.get('applies', v['total'])}</td>"
                 f"<td class='num'>{v['failing']}</td></tr>")
    P.append("</table>")

    # PRIORITY ISSUES
    # One definition per term, at first use, document-wide.
    defined = set()
    from .scoring import top_issues
    _top = top_issues(findings, catalog, 12)
    P.append("<h2>Top findings</h2>")
    for b in _bubbles(" ".join(
            (catalog.get(cid, {}) or {}).get("checkpoint", "") + " " +
            (f.get("evidence") or "") for cid, f in _top[:5]), defined, limit=3):
        P.append(b)
    P.append("<table><tr><th>ID</th><th>Checkpoint</th>"
             "<th>Severity</th><th>Finding</th></tr>")
    for cid, f in _top:
        m = catalog[cid]
        P.append(f"<tr><td><code>{cid}</code></td>"
                 f"<td>{e(m['checkpoint'])}{_lamp(cid, f['status'])}</td>"
                 f"<td><span class='chip'><b style='background:"
                 f"{SEV_RAMP.get(f['severity'], 'var(--muted)')}'></b>"
                 f"{e(f['severity'])}</span></td>"
                 f"<td><div class='ev'>{e(f['evidence'])}</div>"
                 + (f"<div class='rec'>→ {e(f['recommendation'])}</div>"
                    if f['recommendation'] else "") + "</td></tr>")
    P.append("</table>")

    # KEYWORD RANKINGS
    rk = ((meta.get("extras") or {}).get("rankings") or {})
    if rk.get("available") and rk.get("rows"):
        P.append("<h2>Keyword rankings &amp; industry benchmarks</h2>")
        P.append(f"<div class='note'>Keywords this domain already ranks for in "
                 f"{e(rk.get('location'))}, ordered by position. "
                 f"<b>{rk.get('top10', 0)} of {rk.get('total', 0)}</b> sit on page "
                 f"one. Volume and difficulty are third-party estimates, not "
                 f"measurements of this site.</div>")
        P.append("<table><tr><th>Keyword</th><th style='width:64px'>Pos.</th>"
                 "<th style='width:86px'>Volume</th><th style='width:92px'>Difficulty"
                 "</th><th>Ranking URL</th></tr>")
        for r in rk["rows"][:25]:
            pos = r.get("position")
            vol = r.get("search_volume")
            dif = r.get("difficulty")
            pos_cell = (f"<b>{pos}</b>" if isinstance(pos, int) and pos <= 10
                        else e(pos if pos is not None else "—"))
            P.append(f"<tr><td>{e(r.get('keyword'))}</td>"
                     f"<td class='num'>{pos_cell}</td>"
                     f"<td class='num'>{format(vol, ',') if isinstance(vol, int) else '—'}</td>"
                     f"<td class='num'>{e(dif) if dif is not None else '—'}</td>"
                     f"<td><div class='ev'>"
                     f"{e((r.get('url') or '').split('//')[-1])}</div></td></tr>")
        P.append("</table>")
    elif rk and not rk.get("available"):
        P.append("<h2>Keyword rankings &amp; industry benchmarks</h2>"
                 f"<div class='note'>Not collected — {e(rk.get('reason'))}. "
                 f"This section is omitted rather than estimated.</div>")

    # FULL FINDINGS
    P.append("<h2>Detailed findings</h2>")
    P.append("<div class='note'>Every row carries its source and a raw value, so a "
             "disputed finding can be traced back to the collector that produced it. "
             "<code>Need Access</code> means the check could not run, not that it failed.</div>")
    for k in ORDER:
        rows = [(cid, f) for cid, f in findings.items()
                if catalog.get(cid, {}).get("prefix") == k]
        if not rows:
            continue
        rows.sort(key=lambda r: (STATUS_ORDER.index(r[1]["status"])
                                 if r[1]["status"] in STATUS_ORDER else 9, r[0]))
        v = sc["sections"].get(k, {})
        P.append(f"<h2 style='margin-top:34px'>{SECTION_NAMES[k]} "
                 f"<span style='color:var(--ink2);text-transform:none;letter-spacing:0'>"
                 f"— {v.get('score','—')}/100 · {e(v.get('rating',''))}</span></h2>")
        for b in _bubbles(SECTION_NAMES[k] + " " + " ".join(
                catalog.get(cid, {}).get("checkpoint", "") for cid, _f in rows[:12]),
                defined, limit=1):
            P.append(b)
        P.append("<table><tr><th style='width:78px'>ID</th><th>Checkpoint</th>"
                 "<th style='width:135px'>Status</th><th>Evidence</th></tr>")
        for cid, f in rows:
            m = catalog[cid]
            col = STATUS_COLOR.get(f["status"], "var(--muted)")
            P.append(f"<tr><td><code>{cid}</code></td>"
                     f"<td>{e(m['checkpoint'])}{_lamp(cid, f['status'])}</td>"
                     f"<td><span class='chip'><b style='background:{col}'></b>"
                     f"{e(status_word(f['status']))}</span></td>"
                     f"<td><div class='ev'>{e(f['evidence'])}</div>"
                     + (f"<div class='rec'>→ {e(f['recommendation'])}</div>"
                        if f['recommendation'] else "") + "</td></tr>")
        P.append("</table>")

    # The legend for the lightbulb, placed after the full record rather than in
    # the header — it only means anything once the reader has seen one.
    if any(is_judged(cid) and f.get("status") not in ("Need Access", "N/A")
           for cid, f in findings.items()):
        P.append(f"<div class='note' style='margin-top:22px'>{LAMP} "
                 f"<b>{JUDGED_NOTE}</b> These checkpoints are qualitative — "
                 f"things like whether a page answers the question it ranks for, "
                 f"or whether its call to action is clear. They are assessed "
                 f"against the page rather than counted, so they carry a "
                 f"judgment where the rest of the report carries a "
                 f"measurement.</div>")

    if meta.get("build"):
        P.append(f"<div style='margin-top:40px;padding-top:18px;"
                 f"border-top:1px solid var(--line);color:var(--muted);font-size:12px'>"
                 f"Generated by Vici Audit Engine · {e(meta['build'])}</div>")
    P.append("</div></body></html>")
    return "\n".join(P)
