"""
AI visibility dashboard.

Viz decisions, in the order the dataviz method requires:

1. FORM.
   * Citation rate = the single headline number  -> hero figure, not a chart.
   * Rate by platform = magnitude across ~6 named categories -> horizontal bars.
   * Share of voice = "one series is the point, the rest are context"
     -> EMPHASIS, not categorical. The client is one accent bar; every
     competitor is de-emphasis gray. Giving 25 domains 25 hues would bury the
     one bar the reader came for, and no palette survives 25 categories anyway.
   * Trend across runs = change over time -> line, single series.

2. COLOR BY JOB. Sequential single hue for magnitude; accent-vs-gray for
   emphasis; the validated ordinal ramp for intent bands. No categorical palette
   is used anywhere here, so there is no adjacent-pair CVD gate to clear.

3. Status colors appear only as chips WITH text labels, never as the sole
   carrier of meaning.
"""
from __future__ import annotations
import html as _h
import json

from .ui import CSS, e, _shell

EXTRA_CSS = """
.hero2{background:var(--surface);border:1px solid var(--line);border-radius:12px;
 padding:24px 26px;display:flex;gap:34px;flex-wrap:wrap;align-items:flex-start}
.hero2 .big{font-size:54px;font-weight:680;letter-spacing:-.045em;line-height:1}
.hero2 .cap{font-size:12px;color:var(--ink2);margin-top:4px}
.hbar{display:flex;align-items:center;gap:10px;margin:0 0 3px}
.hbar .lab{width:186px;font-size:12.5px;color:var(--ink2);text-align:right;flex:none;
 overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hbar .tr{flex:1;height:16px;background:var(--track);border-radius:4px;position:relative}
.hbar .tr>i{position:absolute;left:0;top:0;bottom:0;border-radius:0 4px 4px 0;display:block}
.hbar .v{width:96px;font-size:12.5px;font-variant-numeric:tabular-nums;flex:none;
 white-space:nowrap}
.sov i{background:var(--muted) !important;opacity:.55}
.sov .me i{background:var(--seq) !important;opacity:1}
.sov .me .lab{color:var(--ink);font-weight:640}
.note2{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--seq);
 border-radius:8px;padding:13px 17px;font-size:13.5px;color:var(--ink2);margin:14px 0}
.warn{border-left-color:var(--warning)}
svg .grid{stroke:var(--line);stroke-width:1}
svg .ln{fill:none;stroke:var(--seq);stroke-width:2}
svg .dot{fill:var(--seq)}
svg text{fill:var(--muted);font:11px ui-sans-serif,system-ui}
"""

PLATFORM_LABEL = {"perplexity": "Perplexity", "chatgpt": "ChatGPT", "claude": "Claude",
                  "gemini": "Gemini", "ai_overview": "AI Overviews",
                  "copilot": "Copilot", "replay": "Replay"}


def _hbar(label, pct, value_text, cls="", accent="var(--seq)"):
    w = max(0.0, min(100.0, pct or 0))
    return (f"<div class='hbar {cls}'><div class='lab'>{e(label)}</div>"
            f"<div class='tr'><i style='width:{w:.1f}%;background:{accent}'></i></div>"
            f"<div class='v'>{e(value_text)}</div></div>")


def _sparkline(points, w=520, h=90, pad=22):
    """Trend across runs. Single series, so no legend — the title names it."""
    if len(points) < 2:
        return ("<div class='note2'>A trend line appears once this profile has at "
                "least two completed runs. The time series is the product — a single "
                "run tells you where you stand, the series tells you whether the work "
                "is moving the number.</div>")
    ys = [p[1] for p in points]
    lo, hi = min(ys), max(ys)
    flat = (hi - lo) < 0.05          # identical runs: render a mid-height line
    span = (hi - lo) or 1
    n = len(points)
    def X(i): return pad + i * (w - 2 * pad) / (n - 1)
    def Y(v):
        if flat:
            return h / 2
        return h - pad - (v - lo) * (h - 2 * pad) / span
    d = " ".join(f"{'M' if i == 0 else 'L'}{X(i):.1f},{Y(v):.1f}"
                 for i, (_, v) in enumerate(points))
    dots = "".join(f"<circle class='dot' cx='{X(i):.1f}' cy='{Y(v):.1f}' r='3.5'/>"
                   for i, (_, v) in enumerate(points))
    return (f"<svg viewBox='0 0 {w} {h}' width='100%' height='{h}'>"
            f"<line class='grid' x1='{pad}' y1='{h-pad}' x2='{w-pad}' y2='{h-pad}'/>"
            f"<path class='ln' d='{d}'/>{dots}"
            + (f"<text x='{pad}' y='{h/2-10:.0f}'>{hi:.1f}% — unchanged across "
               f"{n} runs</text>" if flat else
               f"<text x='{pad}' y='14'>{hi:.1f}%</text>"
               f"<text x='{pad}' y='{h-6}'>{lo:.1f}%</text>")
            + "</svg>")


def visibility_html(profile_row, run, platform_stats, sov, history):
    prof = json.loads(profile_row["profile"])
    brand, domain = prof["brand"], prof["domain"]
    skipped = json.loads(run.get("skipped") or "[]")

    cr = run.get("citation_rate")
    mr = run.get("mention_rate")
    ucr = run.get("unprompted_citation_rate")

    body = [f"<style>{EXTRA_CSS}</style>",
            f"<h1>AI Visibility — {e(profile_row['client_name'])}</h1>",
            f"<div class='sub'><code>{e(domain)}</code> · run "
            f"<code>{e(run['id'])}</code> · {run.get('answers_ok') or 0} answers "
            f"across {len(platform_stats)} platforms · {run.get('repeats')} repeats "
            f"per query</div>"]

    # HERO — the citation rate is the product's headline number
    body.append(
        f"<div class='hero2' style='margin-top:20px'>"
        f"<div><div class='big'>{cr if cr is not None else '—'}"
        f"<span style='font-size:20px;color:var(--muted)'>%</span></div>"
        f"<div class='cap'>cited as a source</div></div>"
        f"<div><div class='big' style='font-size:38px;color:var(--ink2)'>"
        f"{mr if mr is not None else '—'}<span style='font-size:16px'>%</span></div>"
        f"<div class='cap'>merely mentioned</div></div>"
        f"<div><div class='big' style='font-size:38px;color:var(--ink2)'>"
        f"{ucr if ucr is not None else '—'}<span style='font-size:16px'>%</span></div>"
        f"<div class='cap'>cited on unprompted queries</div></div>"
        f"<div style='flex:1;min-width:260px;color:var(--ink2);font-size:13.5px'>"
        f"{e(run.get('headline') or '')}</div></div>")

    body.append("<div class='note2'><b>Mentioned ≠ cited.</b> A model can name a "
                "brand from training data while citing competitors as its sources. "
                "The citation rate is what drives referral traffic and what content "
                "and digital-PR work can actually move.</div>")

    if skipped:
        body.append(f"<div class='note2 warn'><b>Not measured:</b> "
                    f"{', '.join(PLATFORM_LABEL.get(s, s) for s in skipped)} — no API "
                    f"credentials configured. These are reported as unmeasured rather "
                    f"than counted as zero visibility.</div>")

    # BY PLATFORM — magnitude, sequential single hue
    body.append("<h2>Citation rate by platform</h2>")
    for p, st in sorted(platform_stats.items(),
                        key=lambda kv: -(kv[1]["citation_rate"] or 0)):
        body.append(_hbar(PLATFORM_LABEL.get(p, p), st["citation_rate"],
                          f"{st['citation_rate']}% · n={st['answers']}"))

    body.append("<h2>Mention rate by platform</h2>")
    for p, st in sorted(platform_stats.items(),
                        key=lambda kv: -(kv[1]["mention_rate"] or 0)):
        body.append(_hbar(PLATFORM_LABEL.get(p, p), st["mention_rate"],
                          f"{st['mention_rate']}%"))

    # SHARE OF VOICE — emphasis: client accent, everyone else gray
    body.append("<h2>Share of voice — who gets cited instead</h2>")
    body.append("<div class='sov'>")
    mx = max((s["citations"] for s in sov), default=1)
    for s in sov[:14]:
        body.append(_hbar(s["domain"], 100 * s["citations"] / mx,
                          f"{s['citations']}  ({s['share']}%)",
                          cls="me" if s["is_client"] else ""))
    body.append("</div>")
    if run.get("top_competitor_domain") and (run.get("citation_gap") or 0) > 0:
        body.append(
            f"<div class='note2'><b>Citation gap:</b> "
            f"{e(run['top_competitor_domain'])} was cited "
            f"{run.get('citation_gap')} more times than {e(domain)} across this panel. "
            f"Those citations are the concrete target for a content and digital-PR "
            f"programme — each one is a page an AI system chose to trust over yours.</div>")

    # TREND
    body.append("<h2>Citation rate over time</h2>")
    body.append(_sparkline([(h["created_at"], h["citation_rate"]) for h in history
                            if h.get("citation_rate") is not None]))

    body.append(f"<p style='margin-top:26px'><a href='/visibility'>← all profiles</a></p>")
    return _shell(f"AI Visibility — {profile_row['client_name']}", "".join(body))


def visibility_index_html(profiles, runs_by_profile, queue_depth):
    rows = []
    for p in profiles:
        runs = runs_by_profile.get(p["id"], [])
        last = runs[0] if runs else None
        cr = last.get("citation_rate") if last else None
        prev = runs[1].get("citation_rate") if len(runs) > 1 else None
        delta = ""
        if cr is not None and prev is not None:
            d = round(cr - prev, 1)
            arrow = "▲" if d > 0 else ("▼" if d < 0 else "—")
            col = "var(--good)" if d > 0 else ("var(--critical)" if d < 0 else "var(--muted)")
            delta = f"<span style='color:{col};font-size:12px'> {arrow} {abs(d)}pt</span>"
        link = f"/visibility/{p['id']}"
        rows.append(
            f"<tr><td><a href='{link}'>{e(p['client_name'])}</a><br>"
            f"<code>{e(p['domain'])}</code></td>"
            f"<td>{e(last['status']) if last else 'never run'}</td>"
            f"<td class='num'>{cr if cr is not None else '—'}%{delta}</td>"
            f"<td class='num'>{last.get('mention_rate') if last else '—'}%</td>"
            f"<td class='num'>{len(runs)}</td>"
            f"<td><form method='post' action='/visibility/{p['id']}/run' "
            f"style='display:block'><button type='submit'>Run now</button></form></td></tr>")

    table = ("<table><tr><th>Client</th><th>Last run</th><th class='num'>Cited</th>"
             "<th class='num'>Mentioned</th><th class='num'>Runs</th><th></th></tr>"
             + "".join(rows) + "</table>") if rows else \
            "<div class='empty'>No monitored profiles yet.</div>"

    body = f"""
    <style>{EXTRA_CSS}</style>
    <h1>AI Visibility Monitor</h1>
    <div class='sub'>Scheduled tracking of whether AI platforms cite your clients
      · queue depth {queue_depth}</div>
    <h2>New monitored profile</h2>
    <div class='card'><form method='post' action='/visibility'>
      <div><label>Client name</label><input name='client_name' required
        placeholder='Grand Home Furnishings'></div>
      <div><label>Brand</label><input name='brand' required
        placeholder='Grand Home Furnishings'></div>
      <div><label>Domain</label><input name='domain' required placeholder='grandhf.com'></div>
      <div><label>Category</label><input name='category' required
        placeholder='furniture retailer'></div>
      <div><button type='submit'>Create</button></div>
    </form>
    <div style='margin-top:10px;font-size:12px;color:var(--muted)'>
      Locations, products and competitors can be added after creation; they expand
      the query panel.</div></div>
    <h2>Monitored profiles</h2>{table}
    <p style='margin-top:24px'><a href='/'>← audits</a></p>
    """
    return _shell("AI Visibility Monitor", body)
