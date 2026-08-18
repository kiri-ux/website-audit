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
form{display:grid;grid-template-columns:2fr 1.4fr 1fr .7fr auto;gap:10px;align-items:end}
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
"""

STATUS_COLOR = {"ready": "var(--good)", "failed": "var(--critical)",
                "queued": "var(--muted)", "crawling": "var(--warning)",
                "checking": "var(--warning)", "scoring": "var(--warning)"}


def e(x):
    return _h.escape(str(x if x is not None else ""))


def _shell(title, body, refresh=None):
    r = f"<meta http-equiv='refresh' content='{refresh}'>" if refresh else ""
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>{r}"
            f"<title>{e(title)}</title><style>{CSS}</style></head>"
            f"<body class='viz-root'><div class='wrap'>{body}</div></body></html>")


def dashboard_html(audits, principal, queue_depth):
    rows = []
    for a in audits:
        col = STATUS_COLOR.get(a["status"], "var(--muted)")
        score = a["overall_score"]
        bar = (f"<div class='bar'><i style='width:{score}%'></i></div>"
               if score is not None else "<span style='color:var(--muted)'>—</span>")
        spin = "<span class='spin'></span> " if a["status"] in (
            "crawling", "checking", "scoring") else ""
        rows.append(
            f"<tr><td><a href='/audits/{a['id']}'>{e(a['client_name'])}</a><br>"
            f"<code>{e(a['target_url'])[:58]}</code></td>"
            f"<td><span class='chip'><b style='background:{col}'></b>{spin}{e(a['status'])}</span>"
            + (f"<br><span style='color:var(--muted);font-size:11.5px'>{e(a['progress'])}</span>"
               if a["status"] not in ("ready", "failed") and a.get("progress") else "")
            + f"</td><td>{bar}</td>"
            f"<td class='num'>{score if score is not None else '—'}</td>"
            f"<td class='num'>{e(a['coverage'] or '—')}</td>"
            f"<td class='num'>{a['pages_crawled'] or '—'}</td></tr>")

    table = ("<table><tr><th>Client</th><th>Status</th><th>Score</th>"
             "<th class='num'>/100</th><th class='num'>Coverage</th>"
             "<th class='num'>Pages</th></tr>" + "".join(rows) + "</table>"
             ) if rows else "<div class='empty'>No audits yet — submit one above.</div>"

    running = any(a["status"] in ("queued", "crawling", "checking", "scoring")
                  for a in audits)

    body = f"""
    <h1>SEO &amp; GEO Audit Engine</h1>
    <div class='sub'>{e(principal.name)} · mode <code>{e(cfg.mode)}</code>
      · queue depth {queue_depth}</div>
    <div style='margin-top:10px'>
      <span class='chip' style='background:var(--seq);color:#fff;border-color:var(--seq);
        font-size:12px;padding:4px 12px'>{e(version.label())}</span>
      <span style='color:var(--muted);font-size:12px;margin-left:8px'>
        {e(version.BUILD_NOTES)}</span></div>

    <h2>New audit</h2>
    <div class='card'><form method='post' action='/audits' id='auditform'>
      <div><label>Target URL</label>
        <input name='target_url' placeholder='https://www.example.com/' required></div>
      <div><label>Client name</label>
        <input name='client_name' placeholder='Grand Furniture' required></div>
      <div><label>Vertical</label><select name='vertical'>
        <option value=''>generic</option><option value='ecommerce'>ecommerce</option>
        <option value='finance_ymyl'>finance / YMYL</option>
        <option value='local_service'>local service</option></select></div>
      <div><label>Max pages</label><input name='max_pages' type='number' value='150'></div>
      <div><button type='submit'>Run audit</button></div>
    </form>
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
    <form style='display:none'>
    </form></div>

    <h2>Audits</h2>{table}
    """
    return _shell("Vici Audit Engine", body, refresh=8 if running else None)


def audit_html(a):
    """Live status page shown while an audit is still running."""
    order = ["queued", "crawling", "checking", "scoring", "ready"]
    cur = a["status"]
    idx = order.index(cur) if cur in order else 0
    steps = "".join(
        f"<div class='{'on' if i == idx else ('done' if i < idx else '')}'>{s}</div>"
        for i, s in enumerate(order))

    if cur == "failed":
        inner = (f"<div class='card'><b style='color:var(--critical)'>Audit failed</b>"
                 f"<p class='sub'>{e(a.get('error'))}</p>"
                 f"<p><a href='/'>← back to dashboard</a></p></div>")
        refresh = None
    else:
        inner = (f"<div class='steps'>{steps}</div>"
                 f"<div class='card'><span class='spin'></span> "
                 f"<b>{e(a.get('progress') or cur)}</b>"
                 f"<p class='sub'>This page refreshes automatically. A full crawl of "
                 f"150 pages typically takes 2–5 minutes.</p></div>")
        refresh = 4

    body = (f"<h1>{e(a['client_name'])}</h1>"
            f"<div class='sub'><code>{e(a['target_url'])}</code> · "
            f"audit <code>{e(a['id'])}</code></div>{inner}"
            f"<p style='margin-top:22px'><a href='/'>← all audits</a></p>")
    return _shell(f"{a['client_name']} — running", body, refresh=refresh)
