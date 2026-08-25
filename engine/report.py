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
    "OFF": "Off-Page & Authority", "CONS": "Consent & Privacy",
}
ORDER = ["ANA", "GSC", "GA4", "TECH", "URL", "SEC", "CANON", "PERF", "ONP",
         "MOB", "SCHEMA", "INTL", "HTML", "EEAT", "GEO", "OFF", "CONS"]



# NO EM DASHES ANYWHERE IN THE OUTPUT.
#
# House style, and it has to be enforced HERE rather than by editing strings.
# Plenty of this copy is not ours to edit: the judgment layer writes evidence
# at scan time, and a rule in a prompt is a request, not a guarantee. One
# substitution at the escape boundary catches every path into the document,
# including text that has not been written yet.
#
# En dashes go too. They are the same typographic gesture and read as an
# inconsistency when only half of them are converted.
def _dashes(t: str) -> str:
    return (t.replace("\u2014", "-").replace("\u2013", "-")
             .replace("&mdash;", "-").replace("&ndash;", "-"))


# ---------------------------------------------------------------- extension
#
# THE ID IS PINNED, WHICH IS THE ONLY REASON A LINK CAN EXIST.
#
# An unpacked Chrome extension normally gets a different id on every machine,
# derived from the folder path — so no page could ever link to it. Putting a
# `key` in the manifest fixes the id everywhere, and popup.html is declared
# web-accessible, so this href works from any page on any of our machines.
#
# It is the FALLBACK, not the main path. When the extension's content script
# is present it reveals a real button that starts the job in one click and
# needs no id at all. The link is for the case that button cannot cover: an
# extension that is installed but out of date, so the script that would have
# revealed the button is not in it yet. That is precisely the state somebody
# is in right after we ship a change, and it used to leave them reading
# "download it and unzip it" about an extension already in their toolbar.
EXTENSION_ID = "pllpocohmdkjddlhneimecdhfdhelnce"


def extension_link(run: str, audit_id: str = "", url: str = "") -> str:
    """A link that opens the Site Scanner popup in a tab, pre-filled."""
    from urllib.parse import urlencode
    q = urlencode({k: v for k, v in
                   (("run", run), ("audit", audit_id), ("url", url)) if v})
    return f"chrome-extension://{EXTENSION_ID}/popup.html?{q}"


def e(x):
    return _dashes(_h.escape(str(x if x is not None else "")))


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
.vbox{margin:7px 0 0;display:grid;grid-template-columns:auto 1fr;gap:3px 12px;
 font-size:12.5px;align-items:baseline}
.vk{color:var(--muted);white-space:nowrap}
.vv{color:var(--ink2);word-break:break-word}
.vc{display:inline-block;background:var(--track);border-radius:4px;
 padding:1px 6px;margin:0 4px 3px 0;font-size:11.5px;word-break:break-all;
 max-width:100%}
.vlist{grid-column:1/-1;margin:2px 0 0 16px;padding:0;color:var(--ink2)}
.vlist li{margin-bottom:5px}
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


# ---- the evidence that was being collected and thrown away ------------------
#
# Every finding carries a `value` dict — the vendors that fired, the request
# URLs, the Consent Mode defaults, the failing state requirements with their
# statute context, the container ids. The collectors fill it, the database
# stores it, the API returns it, and until this build NOTHING RENDERED IT.
# Grepping report.py, pdf_report.py, ui.py and summarize.py for "value" found
# nothing at all.
#
# So the reader got one `evidence` sentence per row — "3 trackers fired before
# any consent interaction: Meta, GA4, TikTok" — while the eight example request
# URLs proving it sat in the database unread. That is the difference between a
# claim and evidence, and it is the whole reason someone opens a detail row.
#
# Deliberately narrow: a value dict can hold anything, so this renders the
# shapes it recognizes and skips the rest rather than dumping JSON at a client.
_VALUE_LABELS = {
    "vendors": "Vendors", "examples": "Requests", "defaults": "Consent Mode",
    "failures": "Failing requirements", "states": "States checked",
    "containers": "Containers", "gtag_ids": "gtag ids", "evidence": "Matched on",
    "notes": "Notes", "by_source": "Where they load from",
    "cmps": "Platforms", "link_text": "Link text",
}
_VALUE_SKIP = {"pre_consent", "informational", "count", "checks", "failing",
               "visible", "universal_only", "notice_only", "gtag_only",
               "event", "gtm_event"}


def _value_block(val: dict) -> str:
    """Render the structured evidence under a finding, or nothing."""
    if not isinstance(val, dict) or not val:
        return ""
    rows = []
    for key, label in _VALUE_LABELS.items():
        v = val.get(key)
        if not v or key in _VALUE_SKIP:
            continue
        if key == "failures":
            # The one shape worth its own treatment: state, requirement, and
            # the scanner's own explanation of why it applies.
            items = "".join(
                f"<li><b>{e(x.get('state'))} &middot; {e(x.get('check'))}</b>"
                + (f"<div class='rec' style='font-style:normal'>"
                   f"{e(' '.join(str(x.get('detail')).split())[:400])}</div>"
                   if x.get("detail") else "") + "</li>"
                for x in v[:12] if isinstance(x, dict))
            rows.append(f"<div class='vk'>{label}</div>"
                        f"<ul class='vlist'>{items}</ul>")
            continue
        if key == "by_source":
            human = {"page": "hardcoded in the page template",
                     "runtime": "injected by Tag Manager",
                     "unknown": "source not determined"}
            body = "; ".join(f"{', '.join(vv)} &mdash; {human.get(k, k)}"
                             for k, vv in v.items() if vv)
            rows.append(f"<div class='vk'>{label}</div><div class='vv'>{body}</div>")
            continue
        if isinstance(v, dict):
            body = ", ".join(f"{e(k)}: {e(x)}" for k, x in list(v.items())[:10])
        elif isinstance(v, (list, tuple)):
            body = "".join(f"<code class='vc'>{e(x)}</code>" for x in v[:8]
                           if x) or ""
            if len(v) > 8:
                body += f"<span class='vv'> +{len(v) - 8} more</span>"
        else:
            body = e(v)
        if body:
            rows.append(f"<div class='vk'>{label}</div><div class='vv'>{body}</div>")
    return f"<div class='vbox'>{''.join(rows)}</div>" if rows else ""


def _brand_head() -> str:
    """Icon tags, inlined so they do not depend on a static route."""
    try:
        from app.brand import HEAD_TAGS
        return HEAD_TAGS
    except Exception:
        return "<meta name='theme-color' content='#002D58'>"


def _listy(items) -> str:
    """a, b and c - so a list of areas reads as a sentence, not a column."""
    items = [str(i) for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _same_day(a, b) -> bool:
    try:
        import datetime as _dt
        return (_dt.date.fromtimestamp(float(a))
                == _dt.date.fromtimestamp(float(b)))
    except (TypeError, ValueError, OSError):
        return False


def _stamp(ts, with_time: bool) -> str:
    """A date, or a date and time when the date alone would be ambiguous."""
    try:
        import datetime as _dt
        d = _dt.datetime.fromtimestamp(float(ts))
        # US format, matching every other date in the deliverable. ISO reads
        # as a log line, which is what the block this replaced looked like.
        return d.strftime("%m/%d/%Y %I:%M %p" if with_time else "%m/%d/%Y")
    except (TypeError, ValueError, OSError):
        return str(ts)[:16]


def _now() -> float:
    import time as _t
    return _t.time()


def _fmt_when(ts) -> str:
    """A stored epoch or ISO string as a plain date. Local to this module:
    app/ui has its own, and the report must not import the web layer."""
    try:
        import datetime as _dt
        return _dt.date.fromtimestamp(float(ts)).isoformat()
    except (TypeError, ValueError, OSError):
        return str(ts)[:10]


def _todo_panel(findings: dict, catalog: dict, meta: dict | None = None) -> list:
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
    _ex = ((meta or {}).get("extras") or {})
    stale = _ex.get("stale_crawl")
    # Answers taken from an earlier run belong in this panel for the same
    # reason a stale crawl does: they are why a run looks different from the
    # last one, and this is the only place anyone would look for that reason.
    carried = _ex.get("carried_forward") or {}
    # A reused crawl too old for the current checks is worth saying even when
    # nothing else is outstanding — it is the reason a run looks thinner than
    # the last one, and the only place anyone would look for that reason.
    if not (b["client"] or b["vendor"] or b["manual"] or stale
            or carried.get("count") or _ex.get("screenshot_note")):
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
        from engine.access import owner
        c, detail, longest = Counter(), {}, {}
        # WHICH CHECKS. THE ONE THING THE PANEL NEVER SAID.
        #
        # "2 - Search Console produced no result for this run" is a count and
        # a subsystem, and the reader's next question is always the same one:
        # WHICH two? Without the ids there is nothing to look up, nothing to
        # grep the appendix for, and no way to tell a real regression from the
        # same two rows that have been unanswerable for a month. The ids cost
        # a few characters and turn every bullet into something checkable.
        who = {}
        for cid in ids:
            f = findings.get(cid) or {}
            # A checkpoint with NO finding has no evidence to quote, and the
            # placeholder said so: "Not run." six times over. True, unhelpful,
            # and identical for six different failures. Name the subsystem
            # instead — that is the sentence someone can act on.
            own = owner(cid)
            fallback = (f"{own} produced no result for this run"
                        if own else "no check produced a result")
            # GROUP ON A SHORT KEY, DISPLAY THE WHOLE THING.
            #
            # This truncated to 110 characters for both jobs at once, and the
            # diagnosis is at the END of the sentence — so the moment the
            # scanner started reporting WHY the browser failed, the panel cut
            # it off mid-clause and printed the identical unhelpful line it
            # had printed for three builds. It looked like nothing had been
            # fixed. Everything had been fixed except the last 40 characters
            # of the string, which were the only ones that mattered.
            full = " ".join(str(f.get("evidence") or fallback).split())
            ev = full[:110]
            c[ev] += 1
            longest[ev] = max(longest.get(ev, ""), full, key=len)
            who.setdefault(ev, []).append(cid)
            rec = " ".join(str(f.get("recommendation") or "").split())
            if rec and ev not in detail:
                # NOT TRUNCATED, for the same reason the evidence is not.
                # The fix line now carries provider messages verbatim, and a
                # 180-character cut lands mid-sentence on exactly the clause
                # that says what to change. Three separate caps in this file
                # have each removed the end of the only useful sentence.
                detail[ev] = rec
        return [(longest.get(why, why), n, detail.get(why, ""),
                 sorted(who.get(why, []))) for why, n in c.most_common()]

    def bullets(rows, limit=6, fix=True):
        """
        Render grouped reasons, and NEVER drop one silently.

        `reasons()` used to end in `most_common(4)` and the caller printed the
        heading count from the full list — so a panel headed "Ours to fix · 7"
        rendered four bullets and threw three away with nothing on screen
        saying so. A reader counting the bullets against the heading either
        distrusts the number or, worse, does not notice.

        The cap is still right: this is a summary and a wall of forty distinct
        one-off reasons is not one. What was wrong is that it was silent.
        """
        shown, rest = rows[:limit], rows[limit:]

        def _ids(cids):
            """The checkpoints behind the count, so the bullet is checkable."""
            if not cids:
                return ""
            shown_ids = ", ".join(cids[:8])
            if len(cids) > 8:
                shown_ids += f" and {len(cids) - 8} more"
            return (f"<div class='sm' style='color:var(--muted)'>"
                    f"<code>{e(shown_ids)}</code></div>")

        out = "".join(
            f"<li><b>{n}</b> — {e(why)}" + _ids(cids)
            + (f"<div class='sm' style='color:var(--muted)'>{e(f_)}</div>"
               if fix and f_ else "") + "</li>"
            for why, n, f_, cids in shown)
        if rest:
            out += (f"<li style='color:var(--muted)'>and {len(rest)} more "
                    f"{'reason' if len(rest) == 1 else 'reasons'} covering "
                    f"{sum(n for _w, n, _f, _c in rest)} "
                    f"{'checkpoint' if sum(n for _w, n, _f, _c in rest) == 1 else 'checkpoints'}"
                    f" — every one is in the findings table below.</li>")
        return out

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

    # SPLIT OFF THE PHASES NOBODY ASKED FOR — before counting anything.
    #
    # Consent and AI visibility are opt-in checkboxes, and most runs leave them
    # off deliberately: one drives a browser, the other pays several platforms
    # per question. With both unticked, fifteen rows produced no findings and
    # got printed as fifteen defects under "a credential we have not set".
    # Nothing was broken. That is the analyst-list mistake again — a list that
    # fills with no-action items is a list people stop reading, and the one
    # real failure hiding in the fifteen goes with it.
    from engine.access import unrequested
    skipped, vendor = unrequested(
        b["vendor"], ((meta or {}).get("extras") or {}).get("phases_run"))

    # A PERMANENT BOUNDARY IS NOT A FIX LIST ITEM.
    #
    # Eight rows sat under "a credential we have not set, or a call we have
    # not written": Index Coverage, Core Web Vitals and the rest that Google
    # publishes in the Search Console UI and exposes through no API. There is
    # no credential and no call. They will be there on every run forever, and
    # a permanent entry on a to-do list is how the whole list stops being
    # read — the same failure as the analyst section and the unticked phases.
    #
    # They still belong in the document, because someone has to know the
    # number came from a person opening a browser. They just do not belong
    # under a heading that promises they will go away.
    _NO_API = {"gsc_ui_only", "ga4_admin_only"}
    boundary = [c for c in vendor
                if (findings.get(c) or {}).get("source") in _NO_API]
    vendor = [c for c in vendor if c not in set(boundary)]

    # A PLATFORM WE DO NOT SUBSCRIBE TO IS NOT AN ACTION ITEM.
    #
    # Three rows — ChatGPT, Perplexity, Copilot — sat under "a credential we
    # have not set". True, and never going to change: there is no intention to
    # set one, and Microsoft publishes no consumer Copilot API to set it for.
    # They would be on that list on every run forever, which is exactly how the
    # analyst section and the unticked phases each broke the list before them.
    #
    # NOT SILENT. The checkpoint still renders in the body of the report saying
    # it was not measured and why — a graceful degradation needs something loud
    # somewhere else, or it is just a silent failure with good manners. What
    # changes is only that it stops claiming to be work. A platform we DO hold
    # a key for that fails keeps its old source and stays on the fix list,
    # which is the case that actually needs someone.
    # Same argument for two more: a consent row that cannot be measured
    # BECAUSE there is no consent platform is not a second finding — it is
    # CONS-01 restated, and CONS-01 is already on the report. And a check that
    # does not apply to the states this client sells in is an answer, not an
    # omission: Global Privacy Control is not law in Tennessee, so skipping it
    # for a Knoxville firm is the scan being right.
    _NOT_WORK = {"ai_platform_absent", "consent_no_cmp",
                 "consent_not_applicable"}
    vendor = [c for c in vendor
              if (findings.get(c) or {}).get("source") not in _NOT_WORK]

    # AND A PAGE WITH NOTHING ON IT IS NOT A MISSING CREDENTIAL EITHER.
    #
    # The row said "This page carried no readable text for this check" and sat
    # under a heading reading "A credential we have not set, or a call we have
    # not written". Both sentences were on screen at once and they contradict
    # each other - which is the same fault as the platform rows above, one
    # bucket further along: a list headed "ours to fix" that fills with things
    # that are not that stops being read.
    #
    # It IS still ours to look at, so it keeps a group of its own rather than
    # disappearing, with the fix line the finding already carries.
    _NO_TEXT = {"page_unreadable", "no_material"}
    unreadable = [c for c in vendor
                  if (findings.get(c) or {}).get("source") in _NO_TEXT]
    vendor = [c for c in vendor if c not in set(unreadable)]

    # THE ONE FAILURE HERE THAT HAS A BUTTON.
    #
    # Nine rows are one HTTP call. PageSpeed Insights refuses our host often
    # enough to take out the whole Performance section in a single go, and the
    # reader is then looking at nine bullets whose only fix is to run the audit
    # again and hope the pool is less busy. The operator's browser reaches the
    # same endpoint on an IP Google is not throttling, so the fix is a click.
    #
    # OFFERED WHEN THE ROWS ARE CARRIED, TOO. Those nine now carry forward
    # from the last run that got a number rather than overwriting it with a
    # gap — which is right, and which also means they leave the "ours to fix"
    # list entirely. A month-old LCP with no way to refresh it is a quieter
    # version of the same problem, so the button follows the rows.
    from engine.checks.perf import PSI_CHECK_IDS
    _aid = (meta or {}).get("audit_id") or ""
    _url = (meta or {}).get("url") or ""
    _psi_out = [c for c in vendor if c in set(PSI_CHECK_IDS)]
    _psi_old = [c for c in PSI_CHECK_IDS
                if ((findings.get(c) or {}).get("value") or {}).get("carried_at")
                and c not in set(_psi_out)]
    _stale = _psi_out + _psi_old
    _btn = ""
    if _stale and _aid:
        _btn = (
            f"<div id='vici-fix' style='margin-top:11px'"
            f" data-audit-id='{e(_aid)}' data-target='{e(_url)}'>"
            f"<button id='vici-fix-go' type='button' class='btn ghost'>"
            f"{'Re-run' if _psi_out else 'Refresh'} the speed test from this "
            f"browser ({len(_stale)} row{'s' if len(_stale) != 1 else ''})"
            f"</button>"
            f"<span id='vici-fix-note' class='sm' "
            f"style='color:var(--muted);margin-left:10px'>"
            f"Same Google endpoint, from your IP instead of the server's. "
            f"Needs the Site Scanner extension &mdash; "
            f"<a href='{e(extension_link('perf', _aid, _url))}'>open it "
            f"directly</a>, or <a href='/extension.zip'>download</a> and "
            f"reload it at chrome://extensions.</span></div>")

    # THE COVERAGE GAP GETS A BUTTON TOO.
    #
    # Four checkpoints say "this check needs full-site coverage, but only 1 of
    # 9 known URLs were crawled" and then "re-run with max_pages >= 9". True,
    # actionable, and it still left the reader to open the form, remember the
    # number and type it in. Every other fixable thing in this panel now has a
    # control; this is the last one that did not.
    _cov = [(c, ((findings.get(c) or {}).get("value") or {}).get("needs_pages"))
            for c in (vendor + list(b["manual"]))
            if ((findings.get(c) or {}).get("value") or {}).get("needs_pages")]
    _cov_btn = ""
    if _cov and _aid:
        _need = max(int(n) for _c, n in _cov)
        _cov_btn = (
            f"<form method='post' action='/audits/{e(_aid)}/rerun' "
            f"style='margin-top:11px;display:flex;align-items:center;gap:10px;"
            f"flex-wrap:wrap'>"
            f"<input type='hidden' name='max_pages' value='{_need}'>"
            f"<button class='btn ghost' type='submit'>Re-crawl this site with "
            f"{_need} pages ({len(_cov)} row"
            f"{'s' if len(_cov) != 1 else ''})</button>"
            f"<span class='sm' style='color:var(--muted)'>Starts a new run at "
            f"the coverage these checks need. The stored pages are not reused "
            f"&mdash; a bigger crawl is the point.</span></form>")

    if vendor:
        items = bullets(reasons(vendor))
        out.append(
            f"<div style='margin-top:12px'>"
            f"<b style='color:var(--critical)'>Ours to fix &middot; "
            f"{len(vendor)}</b>"
            f"<div class='sm' style='color:var(--ink2);margin-top:2px'>"
            f"A credential we have not set, or a call we have not written. "
            f"Nothing to ask anyone for.</div>"
            f"<ul style='margin:6px 0 0 18px'>{items}</ul>"
            + (_btn if _psi_out else "")
            + (_cov_btn if any(c in vendor for c, _n in _cov) else "")
            + "</div>")
    # AN ACTION YOU HAVE TO GO LOOKING FOR IS NOT AN OFFER.
    #
    # The consent capture button lives on the consent page, so the only way to
    # learn there was something left to test was to click into a sub-page and
    # read it. This panel is where somebody checks what a run still owes, so
    # anything actionable has to be reachable FROM here — every other fixable
    # thing in this list already is.
    _con = _ex.get("consent") or {}
    _con_gap = ""
    if _aid and _con.get("has_detail"):
        _why = ("it ran without a browser, so the banner, Consent Mode and "
                "everything that fired before consent were never tested"
                if _con.get("mode") != "full" else "")
        if _why:
            _con_gap = (
                f"<div style='margin-top:12px'>"
                f"<b style='color:var(--ink2)'>The consent scan has more to "
                f"give</b>"
                f"<div class='sm' style='color:var(--ink2);margin-top:2px'>"
                f"On this run {_why}. It can be captured from your own "
                f"browser in about a minute.</div>"
                f"<p style='margin:9px 0 0'>"
                f"<a class='btn ghost' href='/audits/{e(_aid)}/consent'>"
                f"Open the consent scan</a></p></div>")

    if _con_gap:
        out.append(_con_gap)

    if _btn and not _psi_out:
        # Nothing is wrong, so this gets no heading and no color — it is an
        # offer, not a finding.
        out.append(
            f"<div style='margin-top:12px'>"
            f"<div class='sm' style='color:var(--ink2)'>"
            f"<b>Performance came from an earlier run.</b> PageSpeed would "
            f"not answer this host, so the last real measurement was kept "
            f"rather than replaced with a gap.</div>{_btn}</div>")

    # THE CARRIED-FORWARD GROUP AND THE "NOT MEASURED TODAY" GROUP HAVE
    # BEEN MERGED INTO ONE DATED LIST - see the end of this function.
    #
    # They were two blocks answering the same question from opposite ends:
    # one counted carried CHECKPOINTS and printed an audit id, the other
    # listed the two extras SECTIONS and printed a different audit id. The
    # reader had to assemble "which parts of this report are old" out of both.

    if unreadable:
        rows = bullets(reasons(unreadable))
        out.append(
            f"<div style='margin-top:12px'>"
            f"<b style='color:var(--ink2)'>Nothing on the page to read "
            f"&middot; {len(unreadable)}</b>"
            f"<div class='sm' style='color:var(--ink2);margin-top:2px'>"
            f"The check ran and found no text to judge - usually a page that "
            f"builds itself in the browser, or a kind of page this site does "
            f"not publish. Neither is a credential and neither is the "
            f"client's to fix.</div>"
            f"<ul style='margin:6px 0 0 18px'>{rows}</ul></div>")

    if boundary:
        rows = bullets(reasons(boundary), fix=False)
        out.append(
            f"<div style='margin-top:12px'>"
            f"<b style='color:var(--ink2)'>Google publishes no API for this "
            f"&middot; {len(boundary)}</b>"
            f"<div class='sm' style='color:var(--ink2);margin-top:2px'>"
            f"Read from the Search Console interface by hand, or skipped. "
            f"Nothing to configure and nothing that will change — this is a "
            f"limit of Google's API, not a gap in the run."
            f"</div><ul style='margin:6px 0 0 18px'>{rows}</ul>"
            # ONE BUTTON, NO COPYING.
            #
            # The extension can read these reports from a signed-in browser,
            # and it needs an audit id and a property to do it. Both are on
            # this page already. Asking someone to copy an id out of the URL
            # bar and a property string out of Search Console, into a popup in
            # another tab, is three chances to get it wrong before anything
            # has been measured.
            #
            # The button stays hidden until the extension's content script
            # marks the element present, so a browser without it sees the
            # honest instruction rather than a control that does nothing.
            # VISIBLE ALWAYS, WITH AN HONEST STATE.
            #
            # This shipped hidden until the extension's content script
            # revealed it, which is tidy and useless: someone told the button
            # exists, looking at a page with no button, has no way to tell a
            # missing extension from a broken build. The control is always
            # here now, and without the extension it says so and links to it.
            + (f"<div id='vici-console' style='margin-top:11px'"
               f" data-audit-id='{e((meta or {}).get('audit_id') or '')}'"
               f" data-gsc-property="
               f"'{e((meta or {}).get('gsc_property') or '')}'>"
               f"<button id='vici-console-go' type='button' class='btn ghost'>"
               f"Capture all of these from Search Console</button>"
               f"<span id='vici-console-note' class='sm' "
               f"style='color:var(--muted);margin-left:10px'>"
               f"Needs the Site Scanner extension &mdash; "
               f"<a href='"
               + e(extension_link("console",
                                  (meta or {}).get("audit_id") or "",
                                  (meta or {}).get("url") or ""))
               + f"'>open it directly</a>, or "
               f"<a href='/extension.zip'>download</a> and reload it at "
               f"chrome://extensions.</span></div>"
               if (meta or {}).get("audit_id") else "")
            + "</div>")

    # THE "NOT REQUESTED" GROUP HAS BEEN REMOVED.
    #
    # It listed the optional phases somebody had just chosen to switch off,
    # and told them to switch them on. That is the panel narrating a decision
    # the reader made thirty seconds earlier, and it is the third time a group
    # here has filled with items nobody can act on - the same failure as the
    # permanent boundary rows and the platforms we do not subscribe to. The
    # rows themselves still say "not measured" in the body of the report,
    # where a reader meets them; they no longer need a summary of their own.
    #
    # `skipped` is still computed above, because it is what keeps those rows
    # OUT of "ours to fix", which was the whole reason it exists.

    # ---- WHERE THIS REPORT'S DATA CAME FROM ----------------------------
    #
    # Every area of the report and the date its data was pulled. Areas
    # measured on this run say today; areas carried forward say when they
    # were really measured, and are marked.
    #
    # NO AUDIT IDS. Both of the blocks this replaces printed one, and nobody
    # has ever needed to type a run id into anything - a hex string beside
    # every row made the panel read like a log file rather than like an
    # answer to a question somebody asked.
    def _section_dates():
        """
        [(label, when, is_carried, answered_anything)] per area.

        "MEASURED" HAS TO MEAN A NUMBER CAME BACK.

        Having rows was the test, and every area has rows — so a run where
        PageSpeed refused every call still listed Performance & CWV under
        "Measured on this run", directly above nine bullets in the same panel
        saying it could not be measured. The panel contradicted itself on one
        screen, and the half a reader believes is the confident half.

        A section where nothing answered is not measured and it is not
        carried. It is attempted, and it gets said as that.
        """
        _run_at = (meta or {}).get("generated_at") or _now()
        by_prefix, answered = {}, {}
        for cid, f in (findings or {}).items():
            pref = str(cid).split("-")[0]
            val = f.get("value") if isinstance(f.get("value"), dict) else {}
            when = (val or {}).get("carried_at")
            if pref not in by_prefix:
                by_prefix[pref] = None
            answered[pref] = answered.get(pref, False) or (
                f.get("status") not in ("Need Access", None))
            if when:
                by_prefix[pref] = when
        rows = [(SECTION_NAMES.get(pref, pref), by_prefix[pref] or _run_at,
                 bool(by_prefix[pref]), answered.get(pref, False))
                for pref in ORDER if pref in by_prefix]
        for key, label in (("reputation", "Reputation"),
                           ("ai_visibility", "AI Search Visibility")):
            blob = _ex.get(key)
            if not isinstance(blob, dict) or not blob:
                continue
            at = blob.get("carried_at")
            rows.append((label, at or _run_at, bool(at), True))
        return rows

    _fresh_rows = _section_dates()
    if _fresh_rows:
        # ---- CONDENSED, AND THE DATE ONLY WHERE IT DIFFERS ----------------
        #
        # The first version printed nineteen table rows, every one of them the
        # same date, most of them tagged "carried forward" - so it filled half
        # a screen to say something that fits on two lines, and the tag looked
        # wrong: if the carried run was ALSO today, what does carried mean?
        #
        # It means the data was measured by a different run. That is a real
        # distinction and it does not stop being real when both runs happen on
        # the same day - but it is not worth a row each. So: two sentences,
        # areas named inline, and the date shown ONLY on the carried group,
        # where it is the thing being reported. When a carried date matches
        # this run's date the time is added, because "carried from today" with
        # no clock reads as a contradiction.
        _run_at = (meta or {}).get("generated_at") or _now()
        _today = _stamp(_run_at, False)
        _fresh = [l for l, _w, c, ok in _fresh_rows if not c and ok]
        _empty = [l for l, _w, c, ok in _fresh_rows if not c and not ok]
        _stale_rows = [(l, w) for l, w, c, _ok in _fresh_rows if c]
        _bits = []
        if _fresh:
            _bits.append(
                f"<b>Measured on this run</b> ({e(_today)}): "
                f"{e(_listy([_l for _l in _fresh]))}.")
        if _empty:
            # Named separately rather than dropped. An area that vanishes from
            # this list looks like an area nobody thought to run, and the whole
            # point of the sentence is to account for every section in the
            # report.
            _bits.append(
                f"<b>Attempted, nothing came back</b> ({e(_today)}): "
                f"{e(_listy(_empty))} &mdash; every row in "
                f"{'those areas is' if len(_empty) != 1 else 'that area is'} "
                f"in the list above.")
        if _stale_rows:
            # Group by the date they came from - usually one date, sometimes
            # two, never nineteen.
            _by = {}
            for _l, _w in _stale_rows:
                _by.setdefault(_stamp(_w, _same_day(_w, _run_at)), []).append(_l)
            for _when_s, _labels in sorted(_by.items()):
                _bits.append(
                    f"<b>Carried from an earlier run</b> ({e(_when_s)}): "
                    f"{e(_listy(_labels))}.")
        out.append(
            f"<div style='margin-top:12px'>"
            f"<b style='color:var(--ink2)'>Where this report's data came from"
            f"</b>"
            f"<div class='sm' style='color:var(--ink2);margin-top:2px;"
            f"line-height:1.55'>" + " ".join(_bits)
            + ("<br/>Carried areas were measured by an earlier run of this "
               "site and are scored as measured. Re-tick that phase to "
               "refresh them." if _stale_rows else "")
            + "</div></div>")

    # NO EVIDENCE PICTURES, AND THE REASON.
    #
    # The client PDF omits an empty evidence section, which is right - nobody
    # wants a heading over nothing. But that omission was TOTAL: an audit came
    # back with no red-outline shots at all and there was no way, from any
    # screen, to tell whether the phase had been skipped, had failed, or had
    # simply found nothing worth outlining. The worker knows which; this is
    # where it gets said.
    _sn = ((meta or {}).get("extras") or {}).get("screenshot_note") or {}
    if _sn:
        out.append(
            f"<div style='margin-top:12px'>"
            f"<b style='color:var(--ink2)'>No evidence screenshots</b>"
            f"<div class='sm' style='color:var(--ink2);margin-top:2px'>"
            f"{e(_sn.get('why') or '')} Tried {_sn.get('tried', 0)} of "
            f"{_sn.get('candidates', 0)} candidate page(s)"
            + (f": {e(', '.join(_sn.get('unmarked') or []))}."
               if _sn.get("unmarked") else ".")
            + f" The homepage shot on page 2 is unaffected.</div></div>")

    if b["client"]:
        # NAMED, LIKE EVERY OTHER GROUP.
        #
        # This printed a bare count with a generic sentence, and when a row
        # MOVED into it - ANA-03, which had been misfiled under "ours to fix"
        # - the only visible change was the number going from 0 to 1. The
        # reasonable reaction was "why is there something that needs access
        # now?", and the panel had no answer on it anywhere. A group that can
        # gain members has to say which.
        out.append(
            f"<div style='margin-top:12px'>"
            f"<b style='color:var(--warning)'>Ask the client &middot; "
            f"{len(b['client'])}</b>"
            f"<div class='sm' style='color:var(--ink2);margin-top:2px'>"
            f"Search Console or Analytics rows we could not read. Ask them to "
            f"add the Vici login as a user on the property.</div>"
            f"<ul style='margin:6px 0 0 18px'>"
            + bullets(reasons(b["client"]), fix=False) + "</ul></div>")

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
                   "each AI tool and records whether the brand is cited.",
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

    if stale:
        out.append(
            f"<div style='margin-top:12px'>"
            f"<b style='color:var(--warning)'>This run reused an older "
            f"crawl</b>"
            f"<div class='sm' style='color:var(--ink2);margin-top:2px'>"
            f"It came from <code>{e(stale.get('from'))}</code>, taken before "
            f"the crawler recorded the page footer, stylesheet URLs, "
            f"pagination links and meta refresh (schema "
            f"{e(stale.get('have'))} of {e(stale.get('want'))}). The checks "
            f"that read those fields are unanswered — re-run without "
            f"&lsquo;reuse the last crawl&rsquo; to fill them."
            f"</div></div>")

    # NO PANEL WHEN THERE IS NOTHING IN IT.
    #
    # This used to print the header and a "Nothing outstanding" line, on the
    # argument that silence looks like a render failure. It does not: it looks
    # like a clean run. What it actually produced was a box at the top of
    # every good report headed "Before this goes out", which trains the reader
    # to scroll past the one place we put things that need doing.
    #
    # `out` starts with the header alone, so anything longer than one element
    # means a section rendered and the panel has a reason to exist.
    if len(out) == 1:
        return []
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
         "Site Scanner</a></div>"]

    # WHAT THIS RUN STILL OWES, at the top, before anything else.
    #
    # The client PDF says "88 checks are ours to finish". Nothing told US what
    # those were. A promise printed in a deliverable with no worklist behind it
    # is how a report ships with a section quietly empty for the third run in a
    # row. This panel is the worklist, and it is internal-only — the client PDF
    # never carries it.
    P.extend(_todo_panel(findings, catalog, meta))

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
                 # AN ENHANCEMENT OF THE BUTTON BESIDE IT, NOT A FOURTH
                 # DOCUMENT.
                 #
                 # It produces the SAME PDF with the prose rewritten by a
                 # model - same findings, same numbers - so a full-width
                 # button of its own in the row overstated it, and the text
                 # link that replaced that understated it into a footnote.
                 # A sparkle button tucked against the PDF button says what
                 # it is in the one place people already understand: this is
                 # the AI version of the thing to its left.
                 + (f"<a href='{e(meta['pdf_url'])}?polish=1' target='_blank' "
                    f"rel='noopener' title='The same PDF with the wording "
                    f"rewritten by AI. Same findings, same numbers.' "
                    f"style='display:inline-block;margin-left:6px;"
                    f"padding:9px 12px;border:1px solid var(--line);"
                    f"border-radius:7px;font-size:14px;line-height:1;"
                    f"text-decoration:none'>\u2728</a>"
                    # NOT DRAWN WHEN IT CANNOT RUN. With no model key on this
                    # container the route returns the identical PDF, silently
                    # - which is how a button ends up in a deliverable review
                    # with the question "what does this actually change?"
                    # attached to it. The answer was "nothing, here".
                    if meta.get("can_polish") else "")
                 # THREE BUTTONS, ONE ROW. The snapshot and the consent scan
                 # were link text beside a button, so the two things somebody
                 # actually opens after the PDF looked like footnotes to it.
                 + (f"<a href='{e(meta['snapshot_url'])}' target='_blank' "
                    f"rel='noopener' title='Three pages - same findings, no "
                    f"appendix' style='display:inline-block;margin-left:10px;"
                    f"padding:9px 16px;border:1px solid var(--line);"
                    f"border-radius:7px;font-weight:600;font-size:13px;"
                    f"color:var(--ink);text-decoration:none'>Snapshot</a>"
                    if meta.get("snapshot_url") else "")

                 # THE CONSENT SCAN IS BIGGER THAN THE NINE ROWS BELOW.
                 #
                 # Every CMP signature and its evidence, container ids,
                 # Consent Mode defaults, each tracker with the moment it
                 # fired, the per-state statute results and the product
                 # pixels — all of it is on the record now, and none of it
                 # fits in a checkpoint row. The link is only drawn when a
                 # consent scan actually ran.
                 + (f"<a href='{e(meta.get('consent_url'))}' "
                    f"style='display:inline-block;margin-left:10px;"
                    f"padding:9px 16px;border:1px solid var(--line);"
                    f"border-radius:7px;font-weight:600;font-size:13px;"
                    f"color:var(--ink);text-decoration:none'>Full consent "
                    f"scan</a>"
                    if meta.get("consent_url") else "")
                 + "</div>")

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
                 + _value_block(f.get("value"))
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
                     + _value_block(f.get("value"))
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
