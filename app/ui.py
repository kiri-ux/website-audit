"""
Operator UI — dashboard and live job status.

Server-rendered HTML, no build step. For an internal tool that is the right
trade: zero frontend toolchain, and the dev team can change it without a
bundler. The finished report itself is rendered by engine/report.py.
"""
from __future__ import annotations
import html as _h

from .config import cfg
from . import version

CSS = """
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
 font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.viz-root{--plane:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;
 --muted:#898781;--line:#e6e5e1;--seq:#2a78d6;--track:#eceae6;
 --good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])) .viz-root{
 --plane:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;
 --line:#2c2c2a;--seq:#3987e5;--track:#262623}}
.wrap{max-width:1080px;margin:0 auto;padding:36px 26px 70px}
h1{font-size:23px;margin:0 0 4px;letter-spacing:-.02em}
.sub{color:var(--ink2);font-size:13.5px}
h2{font-size:12.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);
 margin:34px 0 12px;font-weight:600}
.card{background:var(--surface);border:1px solid var(--line);border-radius:11px;padding:20px 22px}
form#auditform{display:grid;grid-template-columns:2fr 1.4fr 1fr .7fr auto;
 gap:10px;align-items:end}
label{display:block;font-size:11.5px;color:var(--ink2);margin-bottom:5px;font-weight:600}
input,select{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:7px;
 background:var(--plane);color:var(--ink);font:inherit;font-size:13.5px}
button{padding:9px 20px;border:0;border-radius:7px;background:var(--seq);color:#fff;
 font:inherit;font-weight:620;font-size:13.5px;cursor:pointer;white-space:nowrap}
button:hover{filter:brightness(1.08)}
table{width:100%;border-collapse:collapse;font-size:13.5px;margin-top:6px}
th{text-align:left;font-weight:600;color:var(--muted);font-size:11px;text-transform:uppercase;
 letter-spacing:.07em;padding:0 10px 9px;border-bottom:1px solid var(--line)}
td{padding:10px;border-bottom:1px solid var(--line)}
td.num{text-align:right;font-variant-numeric:tabular-nums}
a{color:var(--seq);text-decoration:none}a:hover{text-decoration:underline}
.chip{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:600;
 padding:2px 9px;border-radius:20px;border:1px solid var(--line);white-space:nowrap}
.chip b{width:7px;height:7px;border-radius:50%;display:inline-block}
.bar{height:8px;background:var(--track);border-radius:4px;overflow:hidden;min-width:90px}
.bar>i{display:block;height:100%;background:var(--seq);border-radius:0 4px 4px 0}
.empty{color:var(--muted);padding:26px 0;text-align:center;font-size:13.5px}
.spin{display:inline-block;width:13px;height:13px;border:2px solid var(--track);
 border-top-color:var(--seq);border-radius:50%;animation:s .8s linear infinite;vertical-align:-2px}
@keyframes s{to{transform:rotate(360deg)}}
code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--ink2)}
.steps{display:flex;gap:0;margin:22px 0 8px}
.steps div{flex:1;padding:9px 12px;font-size:12.5px;border-top:3px solid var(--track);
 color:var(--muted)}
.steps div.on{border-top-color:var(--seq);color:var(--ink);font-weight:620}
.steps div.done{border-top-color:var(--seq);color:var(--ink2)}
/* --- stat strip: the fleet at a glance, above the per-audit detail --- */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:10px;
 margin-top:14px}
.stat{background:var(--surface);border:1px solid var(--line);border-radius:10px;
 padding:12px 14px}
.stat .n{font-size:23px;font-weight:680;letter-spacing:-.02em;
 font-variant-numeric:tabular-nums;line-height:1.15}
.stat .k{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
 margin-top:2px}
.stat .k b{width:7px;height:7px;border-radius:50%;display:inline-block;
 margin-right:4px;vertical-align:0}
/* --- ring: score as an arc so the number has context, not just a value --- */
.ring{display:block}
.ring text{font:600 13px ui-sans-serif,system-ui,sans-serif;fill:var(--ink);
 font-variant-numeric:tabular-nums}
.ring text.sm{font-size:11px;fill:var(--muted);font-weight:500}
/* --- client cards: the list is grouped by CLIENT, not by run --- */
.crow{display:flex;gap:16px;align-items:flex-start;background:var(--surface);
 border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:10px}
.cscore{flex:none;padding-top:2px}
.cmain{flex:1;min-width:0}
.cname{font-size:15.5px;font-weight:640}
.curl{margin-top:2px}
.cmeta{display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin-top:8px;
 font-size:12.5px;color:var(--ink2)}
.cact{flex:none;display:flex;gap:8px;align-items:center}
.btn{display:inline-block;padding:7px 14px;border-radius:7px;background:var(--seq);
 color:#fff;font-size:12.5px;font-weight:620}
.btn:hover{text-decoration:none;filter:brightness(1.08)}
.btn.ghost{background:transparent;color:var(--seq);border:1px solid var(--line)}
.del{background:transparent;color:var(--muted);border:1px solid var(--line);
 padding:6px 12px;font-size:12.5px;font-weight:600}
.del:hover{color:#fff;background:var(--critical);border-color:var(--critical);
 filter:none}
.del.wide{margin-top:8px;width:100%}
.warn{margin-top:8px;font-size:12.5px;color:var(--ink2);background:var(--plane);
 border-left:3px solid var(--serious);border-radius:6px;padding:8px 12px}
.hist{margin-top:10px}
.hist summary{cursor:pointer;font-size:12.5px;color:var(--seq);
 list-style:none;display:inline-block}
.hist summary::-webkit-details-marker{display:none}
.hist summary:before{content:"▸ ";}
.hist[open] summary:before{content:"▾ ";}
table.sub{margin-top:8px;font-size:12.5px}
table.sub td{padding:7px 8px;border-bottom:1px solid var(--line)}
td.hw{color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums}
/* --- live progress rail --- */
.rail{position:relative;height:6px;background:var(--track);border-radius:3px;
 margin:20px 0 4px;overflow:hidden}
.rail>i{display:block;height:100%;background:var(--seq);border-radius:3px;
 transition:width .4s ease}
.rail.indet>i{width:38%;animation:slide 1.5s ease-in-out infinite}
@keyframes slide{0%{margin-left:-38%}100%{margin-left:100%}}
.marks{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);
 letter-spacing:.04em}
.marks span.on{color:var(--ink);font-weight:640}
.marks span.done{color:var(--ink2)}
"""

from .brand import HEAD_TAGS as HEAD

STATUS_COLOR = {"ready": "var(--good)", "failed": "var(--critical)",
                "queued": "var(--muted)", "crawling": "var(--warning)",
                "checking": "var(--warning)", "scoring": "var(--warning)",
                "needs_capture": "var(--serious)"}


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


def _shell(title, body, refresh=None):
    r = f"<meta http-equiv='refresh' content='{refresh}'>" if refresh else ""
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>{r}"
            f"{HEAD}"
            f"<title>{e(title)}</title><style>{CSS}</style></head>"
            f"<body class='viz-root'><div class='wrap'>{body}</div></body></html>")


def _fmt_when(ts):
    import time as _t
    if not ts:
        return "—"
    return _t.strftime("%m/%d/%Y %H:%M", _t.localtime(ts))


def _del_form(audit_id, label="Delete", confirm="Delete this audit?"):
    return (f"<form method='post' action='/audits/{audit_id}/delete' "
            f"style='display:inline' onsubmit=\"return confirm('{confirm}')\">"
            f"<button class='del' type='submit'>{label}</button></form>")


def dashboard_html(audits, principal, queue_depth):
    """
    Grouped by CLIENT, not one row per run.

    Testing a crawler against a single site produces six rows of the same
    client in an afternoon, which buries every other client in the list. The
    unit of this page is now the client: newest run on the headline row, older
    runs folded underneath, and a one-click way to drop the rest.
    """
    from . import db
    groups = db.group_by_client(audits)

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
            f"<span class='chip'><b style='background:{col}'></b>{spin}"
            f"{e(a['status'])}</span>"
            f"<span>{e(a.get('overall_rating') or 'Not Assessed')}</span>"
            f"<span>{e(a.get('coverage') or '—')} checks</span>"
            f"<span>{a.get('pages_crawled') or '—'} pages</span>"
            f"<span>{_fmt_when(a.get('created_at'))}</span>"
            f"</div>"
            + (f"<div class='warn'>⚠ Server crawl blocked. Open the site in "
               f"Chrome, launch <b>Vici Audit Capture</b>, and paste audit id "
               f"<code>{a['id']}</code>.</div>"
               if a["status"] == "needs_capture" else "")
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

    body = f"""
    <h1>SEO &amp; AI Search Audit Engine</h1>
    <div class='sub'>{e(principal.name)} · mode <code>{e(cfg.mode)}</code></div>
    <div style='margin-top:10px'>
      <span class='chip' style='background:var(--seq);color:#fff;border-color:var(--seq);
        font-size:12px;padding:4px 12px'>{e(version.label())}</span>
      <span style='color:var(--muted);font-size:12px;margin-left:8px'>
        {e(version.BUILD_NOTES)}</span></div>
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
        var bits = [];
        bits.push(d.gsc.ok
          ? '\\u2713 Search Console: ' + d.gsc.property + ' (via ' + d.gsc.login + ')'
          : '\\u2717 Search Console: ' + (d.gsc.detail || 'not found'));
        bits.push(d.ga4.ok
          ? '\\u2713 GA4: ' + d.ga4.name + ' (' + d.ga4.property + ', via ' + d.ga4.login + ')'
          : (d.ga4.partial ? '? GA4: no quick match — the audit looks wider'
                           : '\\u2717 GA4: ' + (d.ga4.detail || 'not found')));
        out.style.color = (d.gsc.ok && d.ga4.ok) ? 'var(--good)'
                        : (d.gsc.ok || d.ga4.ok) ? 'var(--warning)' : 'var(--serious)';
        out.innerHTML = bits.map(function (b) {{
          return b.replace(/&/g, '&amp;').replace(/</g, '&lt;');
        }}).join('<br>');
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
    return _shell("Vici Audit Engine", body, refresh=8 if running else None)


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
                 f"<p><a href='/'>← back to dashboard</a></p></div>")
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
            f"<p class='sub' id='vici-capture-manual'>Extension not detected. "
            f"Install <b>Vici Audit Capture</b>, then use audit id "
            f"<code id='vici-audit-id'>{e(a['id'])}</code> "
            f"<button class='del' type='button' onclick=\"navigator.clipboard"
            f".writeText('{e(a['id'])}');this.textContent='copied'\">copy</button>"
            f"</p></div>"
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
            rail = (f"<div class='rail'><i style='width:{pct}%'></i></div>"
                    f"<div class='marks' style='margin-bottom:14px'>"
                    f"<span class='on'>{done} of up to {target} pages</span>"
                    f"<span>{pct}%</span></div>")
        else:
            rail = "<div class='rail indet'><i></i></div>"
        inner = (rail + f"<div class='marks'>{marks}</div>"
                 f"<div class='card' style='margin-top:16px'>"
                 f"<span class='spin'></span> <b>{e(a.get('progress') or cur)}</b>"
                 f"<p class='sub'>This page refreshes automatically. A full crawl of "
                 f"150 pages typically takes 2–5 minutes.</p></div>")
        refresh = 4

    body = (f"<h1>{e(a['client_name'])}</h1>"
            f"<div class='sub'><code>{e(a['target_url'])}</code> · "
            f"audit <code>{e(a['id'])}</code></div>{inner}"
            f"<p style='margin-top:22px'><a href='/'>← all audits</a></p>")
    return _shell(f"{a['client_name']} — running", body, refresh=refresh)
