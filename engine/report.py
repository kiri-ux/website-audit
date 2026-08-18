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
STATUS_ORDER = ["Fail", "Not Implemented", "Warning", "Pass", "Need Access", "N/A"]

SECTION_NAMES = {
    "ANA": "Analytics & Tracking", "GSC": "Search Console", "GA4": "Google Analytics 4",
    "TECH": "Technical SEO", "URL": "URL Structure", "SEC": "HTTPS & Security",
    "CANON": "Canonicalization", "PERF": "Performance & CWV", "ONP": "On-Page SEO",
    "MOB": "Mobile SEO", "SCHEMA": "Structured Data", "INTL": "International SEO",
    "HTML": "HTML & Code Quality", "EEAT": "E-E-A-T", "GEO": "AI SEO / GEO",
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
              f"{v['rating']:<20}{v['checked']:>8}{v['failing']:>6}  {bar}")
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
.note{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--seq);
 border-radius:8px;padding:14px 18px;font-size:13.5px;color:var(--ink2);margin:14px 0}
"""

STATUS_COLOR = {"Pass": "var(--good)", "Warning": "var(--warning)",
                "Fail": "var(--critical)", "Not Implemented": "var(--serious)",
                "Need Access": "var(--muted)", "N/A": "var(--muted)"}
SEV_RAMP = {"Critical": "var(--o4)", "High": "var(--o3)",
            "Medium": "var(--o2)", "Low": "var(--o1)", "Opportunity": "var(--track)"}


def render_html(meta, sc, findings, catalog):
    st = Counter(f["status"] for f in findings.values())
    sev = Counter(f["severity"] for f in findings.values()
                  if f["status"] in {"Fail", "Not Implemented", "Warning"})
    o = sc["overall"]
    total_sev = sum(sev.values()) or 1

    P = [f"<!doctype html><html><head><meta charset='utf-8'>",
         "<meta name='viewport' content='width=device-width,initial-scale=1'>",
         f"<title>SEO/GEO Audit — {e(meta['client'])}</title><style>{CSS}</style>",
         "</head><body class='viz-root'><div class='wrap'>"]

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
    P.append("<h2>At a glance</h2><div class='kpis'>")
    for v, l in ((st["Pass"], "Passing"),
                 (st["Fail"], "Failing"),
                 (st["Not Implemented"], "Not implemented"),
                 (st["Need Access"], "Need access"),
                 (meta["pages_crawled"], "Pages crawled")):
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
             "<th class='num'>Checked</th><th class='num'>Failing</th></tr>")
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
                 f"<td class='num'>{v['checked']}/{v['total']}</td>"
                 f"<td class='num'>{v['failing']}</td></tr>")
    P.append("</table>")

    # PRIORITY ISSUES
    from .scoring import top_issues
    P.append("<h2>Priority issues</h2><table><tr><th>ID</th><th>Checkpoint</th>"
             "<th>Severity</th><th>Finding</th></tr>")
    for cid, f in top_issues(findings, catalog, 12):
        m = catalog[cid]
        P.append(f"<tr><td><code>{cid}</code></td><td>{e(m['checkpoint'])}</td>"
                 f"<td><span class='chip'><b style='background:"
                 f"{SEV_RAMP.get(f['severity'], 'var(--muted)')}'></b>"
                 f"{e(f['severity'])}</span></td>"
                 f"<td><div class='ev'>{e(f['evidence'])}</div>"
                 + (f"<div class='rec'>→ {e(f['recommendation'])}</div>"
                    if f['recommendation'] else "") + "</td></tr>")
    P.append("</table>")

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
        P.append("<table><tr><th style='width:78px'>ID</th><th>Checkpoint</th>"
                 "<th style='width:135px'>Status</th><th>Evidence</th></tr>")
        for cid, f in rows:
            m = catalog[cid]
            col = STATUS_COLOR.get(f["status"], "var(--muted)")
            P.append(f"<tr><td><code>{cid}</code></td><td>{e(m['checkpoint'])}</td>"
                     f"<td><span class='chip'><b style='background:{col}'></b>"
                     f"{e(f['status'])}</span></td>"
                     f"<td><div class='ev'>{e(f['evidence'])}</div>"
                     + (f"<div class='rec'>→ {e(f['recommendation'])}</div>"
                        if f['recommendation'] else "") + "</td></tr>")
        P.append("</table>")

    P.append("</div></body></html>")
    return "\n".join(P)
