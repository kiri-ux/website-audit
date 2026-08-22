"""
End-to-end test for the AI visibility monitor.

Uses the recorded replay corpus (AI_REPLAY_CORPUS), so it needs no API keys, no
network, and no spend — and it is deterministic, so it can gate CI.

    POST /api/monitors -> frozen panel
    POST /api/monitors/{id}/runs -> queue -> worker -> platforms -> analysis
    -> DB time series -> GET run -> dashboard HTML
    -> GEO-23..30 merged onto the linked audit
"""
from __future__ import annotations
import json
import os
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite:///data/test_aivis.db")
os.environ.setdefault("ARTIFACT_STORE", "local://data/test_aivis_art")
os.environ.setdefault("SKIP_PSI", "true")
os.environ.setdefault("AI_REPLAY_CORPUS", "fixture/ai_corpus.json")

API_PORT, FIXTURE_PORT = 8011, 8089
API = f"http://127.0.0.1:{API_PORT}"
FIXTURE = f"http://localhost:{FIXTURE_PORT}/"
FAILURES = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)
    return cond


def GET(path):
    with urllib.request.urlopen(API + path, timeout=20) as r:
        return r.status, json.loads(r.read())


def GET_RAW(path):
    with urllib.request.urlopen(API + path, timeout=30) as r:
        return r.status, r.read().decode()


def POST(path, payload=None):
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(API + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, json.loads(r.read())


def wait_for(url, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def poll(path, key="status", done=("ready", "failed"), timeout=180):
    t0, seen = time.time(), []
    d = {}
    while time.time() - t0 < timeout:
        _, d = GET(path)
        if d.get(key) not in seen:
            seen.append(d.get(key))
            print(f"    t+{time.time()-t0:5.1f}s  {d.get(key):<9} {d.get('progress') or ''}")
        if d.get(key) in done:
            break
        time.sleep(1)
    return d, seen


def main():
    for p in ("data/test_aivis.db", "data/test_aivis.db-wal", "data/test_aivis.db-shm"):
        if os.path.exists(p):
            os.remove(p)

    from app import db, worker
    from app.config import cfg

    # fixture site, so we can link a real audit to the monitor run
    import http.server, socketserver, functools
    from tests._fixture import serve, stop as stop_server
    httpd, root = serve(FIXTURE_PORT)

    import uvicorn
    db.init_db()
    server = uvicorn.Server(uvicorn.Config("app.api:app", host="127.0.0.1",
                                           port=API_PORT, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    threading.Thread(target=worker.main, daemon=True).start()

    print(f"\nCONFIG: {cfg.summary()} · replay corpus\n")
    print("BOOT")
    check("API reachable", wait_for(API + "/healthz"))

    # ---------- create profile ----------
    print("\nPROFILE")
    truth = json.load(open("fixture/ai_truth.json"))
    prof_payload = dict(truth["profile"])
    prof_payload["client_name"] = "Grand Home Furnishings"
    st, prof = POST("/api/monitors", prof_payload)
    check("POST /api/monitors returns 201", st == 201, f"status={st}")
    pid = prof.get("profile_id")
    check("panel generated and frozen", prof.get("panel_size", 0) >= 30,
          f"{prof.get('panel_size')} queries")
    check("panel is majority unprompted (earned-visibility queries)",
          prof.get("unprompted", 0) > prof.get("panel_size", 0) / 2,
          f"{prof.get('unprompted')}/{prof.get('panel_size')} unprompted")

    # ---------- start a run ----------
    print("\nRUN 1")
    st, run = POST(f"/api/monitors/{pid}/runs", {"repeats": 1})
    check("POST run returns 202 (does NOT block)", st == 202, f"status={st}")
    rid = run["run_id"]
    d, seen = poll(f"/api/monitors/runs/{rid}")
    check("run reached ready", d.get("status") == "ready",
          d.get("error") or d.get("status"))
    check("citation rate computed", d.get("citation_rate") is not None,
          f"{d.get('citation_rate')}%")
    check("mention rate computed", d.get("mention_rate") is not None,
          f"{d.get('mention_rate')}%")
    check("mention rate exceeds citation rate (the core insight)",
          (d.get("mention_rate") or 0) > (d.get("citation_rate") or 0),
          f"{d.get('mention_rate')}% mentioned vs {d.get('citation_rate')}% cited")
    check("per-platform stats persisted", len(d.get("by_platform", {})) >= 4,
          f"{len(d.get('by_platform', {}))} platforms")
    check("share of voice persisted", len(d.get("share_of_voice", [])) >= 3,
          f"{len(d.get('share_of_voice', []))} domains")

    sov = d.get("share_of_voice", [])
    client = [s for s in sov if s["is_client"]]
    check("client domain identified in share of voice", len(client) == 1,
          client[0]["domain"] if client else "not found")
    check("competitor citations tracked",
          any(not s["is_client"] for s in sov))
    check("citation gap computed", d.get("citation_gap") is not None,
          f"gap={d.get('citation_gap')} vs {d.get('top_competitor_domain')}")

    # ---------- traps did not inflate the numbers ----------
    print("\nACCURACY (traps must not inflate)")
    exp_m = sum(1 for pl in truth["truth"].values() for t in pl.values() if t["mentioned"])
    exp_c = sum(1 for pl in truth["truth"].values() for t in pl.values() if t["cited"])
    tot = sum(len(pl) for pl in truth["truth"].values())
    check("mention rate matches ground truth",
          abs(d["mention_rate"] - round(100 * exp_m / tot, 1)) < 0.2,
          f"got {d['mention_rate']}%, expected {round(100*exp_m/tot,1)}%")
    check("citation rate matches ground truth",
          abs(d["citation_rate"] - round(100 * exp_c / tot, 1)) < 0.2,
          f"got {d['citation_rate']}%, expected {round(100*exp_c/tot,1)}%")

    # ---------- dashboard ----------
    print("\nDASHBOARD")
    st, html = GET_RAW(f"/visibility/{pid}")
    check("visibility dashboard renders", st == 200 and "Share of voice" in html,
          f"{len(html)//1024}KB")
    check("dashboard shows the mentioned-vs-cited distinction",
          "Mentioned ≠ cited" in html or "merely mentioned" in html)
    st, idx = GET_RAW("/visibility")
    check("visibility index renders", st == 200 and "Grand Home" in idx)

    # ---------- second run -> time series ----------
    print("\nRUN 2 (time series)")
    st, run2 = POST(f"/api/monitors/{pid}/runs", {"repeats": 1})
    rid2 = run2["run_id"]
    d2, _ = poll(f"/api/monitors/runs/{rid2}")
    check("second run completed", d2.get("status") == "ready")
    check("frozen panel reused — runs are comparable",
          d2.get("panel_version") == d.get("panel_version"),
          f"v{d.get('panel_version')} == v{d2.get('panel_version')}")
    check("replay is deterministic across runs",
          d2.get("citation_rate") == d.get("citation_rate"),
          f"{d.get('citation_rate')}% == {d2.get('citation_rate')}%")
    st, hist = GET(f"/api/monitors/{pid}/history")
    check("history exposes the time series", len(hist["history"]) == 2,
          f"{len(hist['history'])} runs")
    st, html2 = GET_RAW(f"/visibility/{pid}")
    check("trend line rendered once 2+ runs exist", "<svg" in html2)

    # ---------- GEO merge onto an audit ----------
    print("\nGEO CHECKPOINT MERGE")
    st, aud = POST("/api/audits", {"target_url": FIXTURE,
                                   "client_name": "Grand Home Furnishings",
                                   "vertical": "ecommerce", "max_pages": 60,
                                   "skip_psi": True})
    aid = aud["audit_id"]
    a, _ = poll(f"/api/audits/{aid}")
    check("linked audit completed", a.get("status") == "ready")
    _, f_before = GET(f"/api/audits/{aid}/findings")
    geo_before = {k: v for k, v in f_before["findings"].items()
                  if k in ("GEO-23", "GEO-27", "GEO-28", "GEO-30")}
    check("GEO-23..30 absent before the monitor runs", len(geo_before) == 0,
          f"{len(geo_before)} present")

    st, run3 = POST(f"/api/monitors/{pid}/runs", {"repeats": 1, "audit_id": aid})
    d3, _ = poll(f"/api/monitors/runs/{run3['run_id']}")
    check("linked monitor run completed", d3.get("status") == "ready")

    _, f_after = GET(f"/api/audits/{aid}/findings")
    fa = f_after["findings"]
    geo_ids = ["GEO-23", "GEO-24", "GEO-25", "GEO-26", "GEO-27", "GEO-28",
               "GEO-29", "GEO-30"]
    present = [g for g in geo_ids if g in fa]
    check("all 8 GEO visibility rows merged onto the audit", len(present) == 8,
          f"{len(present)}/8")
    check("GEO-28 (Perplexity) carries a measured rate",
          fa.get("GEO-28", {}).get("value", {}).get("citation_rate") is not None,
          str(fa.get("GEO-28", {}).get("value", {}).get("citation_rate")))
    check("GEO-26 (Copilot) honestly reports Need Access — not measured",
          fa.get("GEO-26", {}).get("status") == "Need Access",
          fa.get("GEO-26", {}).get("status"))
    check("GEO-24/25 (SERP features) not faked from chatbot data",
          fa.get("GEO-24", {}).get("status") in ("Need Access", "Warning"),
          fa.get("GEO-24", {}).get("status"))
    check("unmeasured rows carry confidence 0",
          fa.get("GEO-26", {}).get("confidence") == 0.0,
          str(fa.get("GEO-26", {}).get("confidence")))

    _, a2 = GET(f"/api/audits/{aid}")
    check("audit coverage increased after merge",
          int(a2["coverage"].split("/")[0]) > int(a["coverage"].split("/")[0]),
          f"{a['coverage']} -> {a2['coverage']}")

    # ---------- scheduler ----------
    print("\nSCHEDULER")
    from app.schedule import due_profiles
    check("recently-run profile is NOT due", len(due_profiles(30)) == 0,
          f"{len(due_profiles(30))} due")
    check("profile IS due under a zero-day interval", len(due_profiles(0)) == 1,
          f"{len(due_profiles(0))} due")

    print("\nA PLATFORM THAT FAILED EVERY QUERY SAYS WHY")
    # THE BUG: `by_platform` is built from SUCCESSFUL answers, so a platform
    # where every call errored vanished from it entirely and the checkpoint
    # read "Google AI Overviews visibility not measured: no successful
    # responses collected." The provider had raised something specific and
    # useful; it reached a counter and stopped there. Same shape as every
    # other bug here — an error carried inside a success needs unwrapping, or
    # it is not an error to anyone downstream.
    from engine.aivis.geo_checks import findings_from_run as _ffr
    from types import SimpleNamespace as _NS
    _prof = _NS(domain="ootenlawfirm.com", competitors=[], brand="Ooten")
    _agg = {"by_platform": {}, "skipped_platforms": [], "repeats": 1,
            "platform_errors": {"ai_overview": {
                "errors": 8, "successes": 0,
                "messages": ["DataForSEO SERP returned 40401: invalid "
                             "credentials"]}}}
    _rows = _ffr(_agg, _prof)
    check("the provider's own message reaches the row",
          "40401" in _rows["GEO-23"]["evidence"],
          _rows["GEO-23"]["evidence"][:100])
    check("and it is named as ours, not a client permission",
          "our error" in _rows["GEO-23"]["recommendation"].lower())
    check("the message is kept as structured evidence too",
          bool(_rows["GEO-23"]["value"].get("provider_messages")))
    # A platform nobody configured is a different statement and keeps its own.
    _skipped = _ffr({"by_platform": {}, "skipped_platforms": ["chatgpt"],
                     "repeats": 1, "platform_errors": {}}, _prof)
    check("an unconfigured platform still reads as a missing credential",
          "no API credentials" in _skipped["GEO-27"]["evidence"])
    # And silence with no recorded error is called what it is: our bug.
    _silent = _ffr({"by_platform": {}, "skipped_platforms": [], "repeats": 1,
                    "platform_errors": {}}, _prof)
    check("silence with no error recorded is reported as a bug on our side",
          "bug on our side" in _silent["GEO-23"]["recommendation"])

    print("\nA SKIPPED PLATFORM IS NOT A FAILED ONE")
    # THE BUG: `run_panel` computed `skipped` only when it had to build the
    # provider list itself. The audit worker calls `active_providers()` first
    # so it can log the platform names, then passes the providers in — so
    # `skipped` stayed empty, the aggregate said nothing was skipped, and four
    # checkpoints for four UNCONFIGURED platforms reported "no successful
    # responses collected". Not configured and configured-but-broken are
    # different problems, and they were printing the same sentence.
    import inspect as _i3
    from engine.aivis.monitor import run_panel as _rp
    check("run_panel accepts a skipped list from its caller",
          "skipped" in _i3.signature(_rp).parameters)
    _wsrc = _i3.getsource(__import__("app.worker", fromlist=["x"])._ai_visibility)
    check("and the audit worker actually hands over the one it computed",
          "skipped=skipped" in _wsrc)
    _sk = _ffr({"by_platform": {}, "skipped_platforms": ["ai_overview"],
                "repeats": 1, "platform_errors": {}}, _prof)
    check("an unconfigured platform reads as a credential, not a failure",
          "no API credentials" in _sk["GEO-23"]["evidence"])

    print("\nAND THE SERP ROWS STOP GUESSING WHICH IT WAS")
    # This row has now been wrong in both directions: first "Configure
    # SERP_ENDPOINT / SERP_API_KEY" long after DataForSEO could answer it,
    # then "DataForSEO is already configured here, so nothing else is needed"
    # printed on a run where the box HAD been ticked and the provider was
    # skipped as unavailable. Three states, three sentences.
    check("a skipped SERP provider names the credential to set",
          "not configured on this worker" in _sk["GEO-24"]["evidence"]
          and "DFS_LOGIN" in _sk["GEO-24"]["recommendation"])
    check("and does not claim DataForSEO is ready when it is not",
          "already configured" not in _sk["GEO-24"]["recommendation"])
    _fail = _ffr({"by_platform": {}, "skipped_platforms": [], "repeats": 1,
                  "platform_errors": {"ai_overview": {
                      "errors": 4, "successes": 0,
                      "messages": ["DataForSEO SERP returned 40402: balance"]}}},
                 _prof)
    check("a SERP query that ran and failed says so, with the message",
          "ran and failed" in _fail["GEO-25"]["evidence"]
          and "40402" in _fail["GEO-25"]["recommendation"])
    _off = _ffr({"by_platform": {}, "skipped_platforms": [], "repeats": 1,
                 "platform_errors": {}}, _prof)
    check("and a phase nobody asked for still says to tick the box",
          "no SERP query ran" in _off["GEO-24"]["evidence"])

    print("\nAN HTTP ERROR BODY IS READ, NOT CLOSED UNREAD")
    # `HTTPError: HTTP Error 404: Not Found` is what the Gemini row printed:
    # a status line and nothing else. Google answers that 404 with a JSON body
    # naming the exact problem — "models/gemini-2.0-flash is not found for API
    # version v1beta" — and `_post` was closing it unread. Same shape as every
    # other bug here: the cause exists one layer down and nothing unwraps it.
    import io as _io, json as _js, urllib.error as _ue, urllib.request as _ur
    from engine.aivis.providers import Provider as _Prov, GeminiProvider as _Gem
    _real_open = _ur.urlopen

    class _Err(_ue.HTTPError):
        def __init__(self):
            _body = _js.dumps({"error": {"code": 404, "message":
                "models/gemini-2.0-flash is not found for API version "
                "v1beta, or is not supported for generateContent."}}).encode()
            super().__init__("https://generativelanguage.googleapis.com/v1beta/"
                             "models/x:generateContent", 404, "Not Found", {},
                             _io.BytesIO(_body))

    _ur.urlopen = lambda *a, **k: (_ for _ in ()).throw(_Err())
    try:
        _msg = ""
        try:
            _Prov()._post("https://generativelanguage.googleapis.com/v1beta/"
                          "models/x:generateContent", {}, {})
        except Exception as _e:
            _msg = str(_e)
    finally:
        _ur.urlopen = _real_open
    check("the provider's real message survives the exception",
          "not found for API version" in _msg, _msg[:110])
    check("and the status and host are still there to place it",
          "404" in _msg and "generativelanguage.googleapis.com" in _msg)
    check("the bare urllib status line is gone",
          "HTTP Error 404: Not Found" not in _msg)

    print("\nAND THE GEMINI MODEL IS DISCOVERED, NOT HARDCODED")
    # A hardcoded model name is a time bomb with Google's hand on the timer:
    # the row dies silently the day they retire it and stays dead until
    # somebody reads a checkpoint.
    _g = _Gem()
    _Gem._resolved = None
    _g._models = lambda: ["gemini-1.5-flash", "gemini-2.5-flash", "embedding-001"]
    check("it picks the best model the key can actually call",
          _g._model() == "gemini-2.5-flash", _g._model())
    _Gem._resolved = None
    _g._models = lambda: ["gemini-9.9-experimental-flash"]
    check("an unknown-but-usable model beats failing",
          _g._model() == "gemini-9.9-experimental-flash")
    _Gem._resolved = None
    _g._models = lambda: []
    _why = ""
    try:
        _g._model()
    except Exception as _e:
        _why = str(_e)
    check("and a key that lists nothing says what that usually means",
          "GEMINI_API_KEY" in _why and "not enabled" in _why, _why[:90])
    _Gem._resolved = None
    os.environ["GEMINI_MODEL"] = "gemini-set-by-hand"
    try:
        check("an explicit GEMINI_MODEL still wins over discovery",
              _g._model() == "gemini-set-by-hand")
    finally:
        os.environ.pop("GEMINI_MODEL", None)
        _Gem._resolved = None

    print("\n" + "=" * 68)
    if FAILURES:
        print(f"  {len(FAILURES)} FAILED: {', '.join(FAILURES)}")
    else:
        print("  ALL CHECKS PASSED — AI visibility monitor verified end to end")
    print("=" * 68 + "\n")
    stop_server(httpd)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
