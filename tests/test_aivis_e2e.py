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
import re
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

    # ---------- the questions are ones a person would type ----------
    print("\nTHE PANEL ASKS REAL SEARCHES")
    # THE BUG, REPLAYED.
    #
    # A law firm's panel contained "Which business should I use in Knoxville
    # Tennessee?", "Recommend a trustworthy business near Knoxville
    # Tennessee." and "Where can I buy defense attorney in Knoxville?" -
    # because the industry string "Legal - Defense" never matched a map keyed
    # on internal vertical ids, so `category` fell back to the literal word
    # "business", and product templates ran with no products.
    from engine.aivis.panel import profile_from_audit, build_panel as _bp
    _ctx = {"brand": "The Ooten Law Firm",
            "locations": [{"city": "Knoxville", "region": "Tennessee"}],
            "sections": ["/practice-areas", "/criminal-defense",
                         "/family-law", "/dui"]}
    prof = profile_from_audit("The Ooten Law Firm", "https://ootenlawfirm.com/",
                              _ctx, "Legal - Defense")
    check("the industry string becomes a searchable noun",
          prof.category == "defense attorney", prof.category)
    texts = [q.text for q in _bp(prof)]
    check("no question calls the client 'a business'",
          not [t for t in texts if " business" in t.lower()],
          str([t for t in texts if " business" in t.lower()][:2]))
    check("nothing asks where to BUY a service",
          not [t for t in texts if "buy" in t.lower() or "sells" in t.lower()],
          str([t for t in texts if "buy" in t.lower()][:2]))
    check("the services become their own searches",
          any("criminal defense attorney" in t for t in texts)
          and any("family law attorney" in t for t in texts))
    check("an index page is not treated as a service",
          not [t for t in texts if "practice areas" in t.lower()],
          str([t for t in texts if "practice areas" in t.lower()][:1]))
    check("an initialism is capitalised the way it is typed",
          any("DUI attorney" in t for t in texts),
          str([t for t in texts if "dui" in t.lower()][:1]))
    check("and the articles agree with the words after them",
          not [t for t in texts if " a estate" in t or " a attorney" in t])
    # A TEMPLATE WITH AN EMPTY SLOT IS NOT A QUESTION.
    #
    # "What should I look for when choosing a ?" and "How much does a usually
    # cost?" were fired at five platforms and counted in the rates like any
    # other answer, because the guard was on the location templates and not on
    # the open ones.
    _hole = profile_from_audit("Someone", "https://someone.test/",
                               {"locations": [{"city": "Knoxville",
                                               "region": "Tennessee"}],
                                "sections": ["/criminal-defense"]}, "")
    holes = [q.text for q in _bp(_hole)]
    check("no question is left with a hole where a noun goes",
          not [t for t in holes
               if " a ?" in t or " a usually" in t or "  " in t
               or " the ?" in t], str(holes[:3]))
    # A PLACE NAME IS STILL A PLACE WHEN IT HAS TWO WORDS.
    #
    # /hardin-valley is a Knoxville neighbourhood and it passed every filter:
    # not in the schema locations, not a typed market, two words long. It
    # produced "Who should I hire for hardin valley in your area?"
    _hv = profile_from_audit(
        "Junk Bee Gone", "https://junkbeegone.biz/",
        {"brand": "Junk Bee Gone", "locations": [],
         "sections": ["/junk-removal", "/hardin-valley", "/powell-station",
                      "/dumpster-rentals"]}, "")
    _hvq = [q.text for q in _bp(_hv)]
    check("a neighbourhood is not asked about as a service",
          not [t for t in _hvq if "hardin valley" in t.lower()], str(_hvq[-2:]))
    check("and neither is a station or a ridge",
          not [t for t in _hvq if "powell station" in t.lower()])
    check("with no location, no question invents one",
          not [t for t in _hvq if "your area" in t.lower()
               or "my area" in t.lower()], str(_hvq[-2:]))
    check("a four-letter word is not shouted as an initialism",
          not [t for t in _hvq if "JUNK" in t], str(_hvq[-2:]))
    check("and the verb agrees with a plural service",
          not [t for t in _hvq if "does dumpster rentals" in t.lower()],
          str([t for t in _hvq if "dumpster" in t.lower()][:2]))

    check("and the services still carry the panel on their own",
          any("criminal defense" in t for t in holes), str(holes[-2:]))
    # A TOWN IS NOT A SERVICE.
    #
    # /clinton and /farragut are city pages. They produced "Who should I hire
    # for clinton in Knoxville, Tennessee?" - a question with a town where
    # the job goes. Places we know about are filtered; the rest is shape,
    # because work is described in more than one word and a town is not.
    _towns = profile_from_audit(
        "The Ooten Law Firm", "https://ootenlawfirm.com/",
        {"brand": "The Ooten Law Firm",
         "locations": [{"city": "Knoxville", "region": "Tennessee"},
                       {"city": "Clinton", "region": "Tennessee"}],
         "primary_markets": "Anderson County, TN",
         "sections": ["/clinton", "/farragut", "/criminal-defense",
                      "/estate-planning", "/dui"]}, "Legal - Defense")
    check("a town with schema is dropped from the services",
          "clinton" not in [x.lower() for x in _towns.services],
          str(_towns.services))
    check("and so is the town next to it that had none",
          "farragut" not in [x.lower() for x in _towns.services],
          str(_towns.services))
    check("while the real practice areas survive",
          {"criminal defense", "estate planning"}
          <= {x.lower() for x in _towns.services}, str(_towns.services))
    check("including the one-word ones that are genuinely services",
          "dui" in [x.lower() for x in _towns.services], str(_towns.services))
    # A client we cannot classify gets service questions, never "business".
    bare = profile_from_audit("Someone", "https://someone.test/",
                              {"sections": ["/roof-repair"]},
                              "01 Other- No Matching Category Below")
    check("an unclassifiable client gets no category questions, not bad ones",
          bare.category == "" and
          not [t for t in (q.text for q in _bp(bare)) if "business" in t.lower()],
          bare.category)

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
    # AND IT IS NOT CUT OFF. A 160-character cap landed on "Please update your
    # code t." — the third time in this codebase a truncation has removed the
    # only part of a sentence worth reading.
    _long = ("HTTP 404 from generativelanguage.googleapis.com: This model "
             "models/gemini-2.5-flash is no longer available to new users. "
             "Please update your code to use a different model.")
    _lr = _ffr({"by_platform": {}, "skipped_platforms": [], "repeats": 1,
                "platform_errors": {"gemini": {"errors": 24, "successes": 0,
                                               "messages": [_long]}}}, _prof)
    check("and the end of the message survives, where the fix always is",
          _lr["GEO-29"]["evidence"].rstrip(".").endswith(
              "use a different model"),
          _lr["GEO-29"]["evidence"][-46:])
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
    _Gem._dead = set()
    _g._models = lambda: ["gemini-1.5-flash", "gemini-2.5-flash", "embedding-001"]
    check("it tries the best model the key can actually call first",
          _g._model_order()[0] == "gemini-2.5-flash", str(_g._model_order()))
    check("and keeps the others as fallbacks rather than one guess",
          len(_g._model_order()) > 1, str(_g._model_order()))
    _Gem._resolved = None
    _g._models = lambda: ["gemini-9.9-experimental-flash"]
    check("an unknown-but-usable model beats failing",
          _g._model_order() == ["gemini-9.9-experimental-flash"])
    print("\n  A LISTED MODEL IS NOT A PROMISE")
    # `GET /models` returned gemini-2.5-flash, the picker took it, and every
    # call came back "no longer available to new users". Google lists models
    # it will not serve to a project that has never called them, so resolving
    # to ONE name turned a recoverable condition into 24 identical failures.
    _Gem._resolved = None
    _Gem._dead = set()
    _tried = []

    def _post_stub(self, url, payload, headers, timeout=90):
        m = url.split("/models/")[1].split(":")[0]
        _tried.append(m)
        if m == "gemini-2.5-flash":
            raise RuntimeError("HTTP 404 from generativelanguage.googleapis."
                               "com: This model models/gemini-2.5-flash is no "
                               "longer available to new users.")
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    _real_post = _Gem._post
    _Gem._post = _post_stub
    _g._models = lambda: ["gemini-2.5-flash", "gemini-2.0-flash",
                          "gemini-1.5-flash"]
    try:
        _a1 = _g.ask("q1", "who")
        check("a refused model falls through to the next one",
              _a1.ok and _tried == ["gemini-2.5-flash", "gemini-2.0-flash"],
              str(_tried))
        _n = len(_tried)
        _g.ask("q2", "who")
        check("and the working one is remembered, not rediscovered per query",
              len(_tried) == _n + 1 and _tried[-1] == "gemini-2.0-flash")
    finally:
        _Gem._post = _real_post
        _Gem._resolved = None
        _Gem._dead = set()

    print("\n  TWO TOOL SHAPES, AND THE MODEL DECIDES WHICH")
    # "HTTP 400: Search as tool is not enabled for this model" is Gemini
    # asking for the OLDER grounding shape — 1.5-era models take
    # `google_search_retrieval` where 2.x takes `google_search`. Same
    # capability, renamed. One extra request is the difference between a
    # measured platform and a checkpoint reporting a 400.
    from engine.aivis.providers import _tool_mismatch as _tm
    check("the tool-shape 400 is recognised",
          _tm("HTTP 400 from x: Search as tool is not enabled for this model."))
    check("and a plain bad request is NOT — it must not burn every model",
          not _tm("HTTP 400 from x: Invalid JSON payload received."))
    _Gem._resolved = None
    _Gem._dead = set()
    _Gem._tool_for = {}
    _shapes = []

    def _shape_stub(self, url, payload, headers, timeout=90):
        m = url.split("/models/")[1].split(":")[0]
        tool = list(payload["tools"][0].keys())[0]
        _shapes.append((m, tool))
        if tool == "google_search":
            raise RuntimeError("HTTP 400 from generativelanguage.googleapis."
                               "com: Search as tool is not enabled for this "
                               "model.")
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    _Gem._post = _shape_stub
    _g._models = lambda: ["gemini-2.5-flash", "gemini-1.5-flash"]
    try:
        _a3 = _g.ask("q3", "who")
        check("a model that wants the older shape is asked with it",
              _a3.ok and _shapes[-1][1] == "google_search_retrieval",
              str(_shapes))
        check("and it is NOT written off as a dead model",
              "gemini-2.5-flash" not in _Gem._dead, str(_Gem._dead))
        _k = len(_shapes)
        _g.ask("q4", "who")
        check("the working shape is remembered, so it costs one request",
              len(_shapes) == _k + 1)
    finally:
        _Gem._post = _real_post
        _Gem._resolved = None
        _Gem._dead = set()
        _Gem._tool_for = {}

    _Gem._resolved = None
    _Gem._dead = set()
    _g._models = lambda: []
    _why = ""
    try:
        # Nothing listed and every fallback already refused -> the honest
        # message about the key, not a shrug.
        _Gem._dead = set(_Gem._PREFER)
        _g._model_order()
    except Exception as _e:
        _why = str(_e)
    finally:
        _Gem._dead = set()
    check("a key whose every model refuses names them",
          "refused" in _why, _why[:90])
    _Gem._resolved = None
    os.environ["GEMINI_MODEL"] = "gemini-set-by-hand"
    try:
        check("an explicit GEMINI_MODEL still wins over discovery",
              _g._model_order() == ["gemini-set-by-hand"])
    finally:
        os.environ.pop("GEMINI_MODEL", None)
        _Gem._resolved = None

    print("\nA PLATFORM WE DO NOT BUY IS NOT AN ACTION ITEM")
    # ChatGPT, Perplexity and Copilot sat under "Ours to fix — a credential we
    # have not set". True, and never going to change: there is no intention to
    # set one, and Microsoft publishes no consumer Copilot API to set it for.
    # They would be on that list on every run forever, which is exactly how the
    # analyst section and the unticked phases each broke the list before them.
    import re as _re2
    from engine.report import _todo_panel as _panel
    from engine.scoring import load_catalog as _cat
    _agg2 = {"by_platform": {}, "repeats": 1,
             "skipped_platforms": ["chatgpt", "perplexity", "copilot"],
             "platform_errors": {"gemini": {
                 "errors": 24, "successes": 0,
                 "messages": ["HTTP 404 from generativelanguage.googleapis.com:"
                              " models/gemini-2.0-flash is not found"]}}}
    _rows2 = _ffr(_agg2, _prof)
    check("an unconfigured platform is tagged as absent, not as a gap",
          _rows2["GEO-27"]["source"] == "ai_platform_absent")
    check("and dropped to Low, because nothing about it is urgent",
          _rows2["GEO-27"]["severity"] == "Low")
    check("a platform we DO hold a key for keeps the normal source",
          _rows2["GEO-29"]["source"] == "ai_visibility")
    _c2 = {k: v for k, v in _cat("seed/checkpoints.csv").items()
           if k.startswith("GEO-2")}
    _txt = _re2.sub(r"\s+", " ", _re2.sub(r"<[^>]+>", " ", "".join(
        _panel(_rows2, _c2,
               {"extras": {"phases_run": {"run_aivis": True,
                                          "run_consent": True}}}))))
    for _p in ("ChatGPT", "Perplexity", "Copilot"):
        check(f"{_p} is off the fix list", _p not in _txt)
    check("but Gemini's real failure is still on it, with its message",
          "Gemini" in _txt and "404" in _txt)
    # NOT SILENT: the row itself still says it was not measured.
    check("the checkpoint still reports itself unmeasured",
          _rows2["GEO-27"]["status"] == "Need Access"
          and "not configured" in _rows2["GEO-27"]["evidence"])

    print("\nAND THE PANEL STOPS DROPPING REASONS ON THE FLOOR")
    # `reasons()` ended in `most_common(4)` while the heading counted the full
    # list — so "Ours to fix · 7" rendered four bullets and threw three away
    # with nothing on screen saying so.
    # One distinct reason per checkpoint in the catalog slice, so the
    # arithmetic has nothing to hide behind.
    _ids = sorted(_c2)
    _many = {cid: {"status": "Need Access", "value": {},
                   "evidence": f"distinct reason for {cid}",
                   "affected_pages": [], "severity": "Medium",
                   "recommendation": "", "confidence": 0.0,
                   "source": "ai_visibility"} for cid in _ids}
    _t2 = _re2.sub(r"\s+", " ", _re2.sub(r"<[^>]+>", " ", "".join(
        _panel(_many, _c2, {"extras": {"phases_run": {"run_aivis": True,
                                                      "run_consent": True}}}))))
    _shown = len(_re2.findall(r"distinct reason for", _t2))
    _head = int(_re2.search(r"Ours to fix &middot; (\d+)", _t2).group(1))
    _over = _re2.search(r"and \d+ more reasons? covering (\d+) checkpoint", _t2)
    check("more reasons than fit are summarised, never dropped",
          bool(_over), f"{_shown} of {_head} shown")
    # THE ARITHMETIC IS THE POINT. A reader counting bullets against the
    # heading must be able to reach it: shown + summarised == the heading.
    # Before, the heading said 7 and four bullets appeared.
    check("and bullets plus overflow add up to the heading",
          bool(_over) and _shown + int(_over.group(1)) == _head,
          f"{_shown} + {_over.group(1) if _over else '?'} vs {_head}")

    print("\nPERPLEXITY RESTRUCTURED, SO BOTH SHAPES ARE TRIED")
    # `chat/completions` with a `sonar` model WAS the whole API. The console
    # now presents Search, Agent and Embeddings, and the web-grounded answer
    # moved to POST /v1/agent with a different request and response shape.
    # Which one a given key can call is not knowable from here, so hardcoding
    # either would produce "not measured" on a key that works fine.
    from engine.aivis.providers import PerplexityProvider as _Px
    os.environ["PERPLEXITY_API_KEY"] = "test-key"
    _AGENT = {"output": [{"type": "message", "role": "assistant", "content": [
        {"type": "output_text", "text": "Ooten Law Firm is a Knoxville firm.",
         "annotations": [{"type": "url_citation",
                          "url": "https://ootenlawfirm.com/",
                          "title": "Ooten"}]}]}]}
    _SONAR = {"choices": [{"message": {"content": "Answer via sonar"}}],
              "search_results": [{"url": "https://x.test/", "title": "X"}]}
    _real_px = _Px._post
    _hits = []
    try:
        _Px._endpoint = None
        _Px._post = lambda self, url, p, h, timeout=90: (
            _hits.append(url) or (_AGENT if url.endswith("/v1/agent") else _SONAR))
        _a = _Px().ask("q1", "who")
        check("the current Agent endpoint is used when it answers",
              _a.ok and _a.citation_shape == "agent.annotations",
              _a.citation_shape)
        check("and its url_citation annotations become citations",
              [c["domain"] for c in _a.citations] == ["ootenlawfirm.com"])
        _n = len(_hits)
        _Px().ask("q2", "who")
        check("the working endpoint is remembered, not re-probed per query",
              len(_hits) == _n + 1 and _hits[-1].endswith("/v1/agent"))

        _Px._endpoint = None
        _hits.clear()

        def _p404(self, url, p, h, timeout=90):
            _hits.append(url)
            if url.endswith("/v1/agent"):
                raise RuntimeError("HTTP 404 from api.perplexity.ai: Not Found")
            return _SONAR

        _Px._post = _p404
        _b = _Px().ask("q3", "who")
        check("a 404 on the new endpoint falls back to the Sonar shape",
              _b.ok and _b.citation_shape == "search_results", _b.citation_shape)
        check("and it tried them in order", len(_hits) == 2)

        # THE IMPORTANT NEGATIVE. A bad key fails the same way on every
        # endpoint, so hunting through them turns one clear "invalid API key"
        # into a vague "neither endpoint answered".
        _Px._endpoint = None
        _hits.clear()

        def _p401(self, url, p, h, timeout=90):
            _hits.append(url)
            raise RuntimeError("HTTP 401 from api.perplexity.ai: Invalid API key")

        _Px._post = _p401
        _c = _Px().ask("q4", "who")
        check("an auth failure is reported, not treated as a wrong endpoint",
              "401" in (_c.error or "") and len(_hits) == 1,
              f"{len(_hits)} endpoint(s) tried")
    finally:
        _Px._post = _real_px
        _Px._endpoint = None
        os.environ.pop("PERPLEXITY_API_KEY", None)

    # ---------- the examples the CLIENT reads ----------
    #
    # Three complaints, all from the same reading of one report, all about the
    # six example cards rather than the numbers above them:
    #
    #   * a platform the client has never opened, named in their report;
    #   * the same question printed twice;
    #   * and "is X legit or a scam?" beside "is X a reputable company?",
    #     which is one question about trust taking two of six slots.
    #
    # The first two are exact rules. The third is the one that will rot: it
    # depends on a bucket list, and a new phrasing that lands outside every
    # bucket comes back as a near-repeat. So it is tested on the real pairs.
    print("\nEXAMPLE CARDS")
    from engine import pdf_report as _P
    _S = _P._styles()
    _brand = "Ooten Law Firm"
    _v = {"citation_rate": 10.8, "mention_rate": 18.5,
          "unprompted_citation_rate": 4.2, "client_citations": 7,
          "citation_gap": 12, "questions": 24,
          "top_competitor_domain": "knoxvillelaw.com",
          "platforms": "ai_overview, chatgpt, claude, gemini, perplexity",
          "cited_examples": [
              {"question": f"Is {_brand} legit or a scam?", "platform": "gemini"},
              {"question": f"Is {_brand} a reputable company?", "platform": "chatgpt"},
              {"question": f"Is {_brand} legit or a scam?", "platform": "perplexity"},
              {"question": f"What is {_brand} known for?", "platform": "chatgpt"}],
          "missed_examples": [
              {"question": "Who is the best DUI attorney in Knoxville, Tennessee?",
               "platform": "claude", "cited_instead": ["avvo.com"]},
              {"question": "Who is the top DUI lawyer in Knoxville?",
               "platform": "gemini", "cited_instead": []},
              {"question": "How much does a family law attorney cost in "
                           "Knoxville, Tennessee?", "platform": "gemini",
               "cited_instead": []}]}
    _txt = []

    def _walk(f):
        t = getattr(f, "text", None)
        if isinstance(t, str):
            _txt.append(t)
        for kid in (getattr(f, "_content", None) or []):
            _walk(kid)
        for row in (getattr(f, "_cellvalues", None) or []):
            for cell in row:
                for kid in (cell if isinstance(cell, list) else [cell]):
                    _walk(kid)

    for _f in _P._ai_examples(_v, _S, _brand):
        _walk(_f)
    _all = " ".join(_txt).lower()
    _qs = re.findall(r"“([^”]+)”", " ".join(_txt))
    check("no platform the client has never opened is named",
          "perplexity" not in _all and "claude" not in _all)
    check("no question printed twice", len(_qs) == len(set(_qs)), str(_qs))
    check("legit/scam and reputable are one question, not two",
          sum(1 for q in _qs if "legit" in q.lower()
              or "reputable" in q.lower()) == 1, str(_qs))
    check("best and top DUI are one question, not two",
          sum(1 for q in _qs if "dui" in q.lower()) == 1, str(_qs))
    check("both halves still shown", any("cost" in q.lower() for q in _qs)
          and any("known for" in q.lower() for q in _qs), str(_qs))

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
