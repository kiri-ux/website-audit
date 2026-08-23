"""
Delete and client-grouping tests.

Deleting is the one operation that can quietly destroy data, so the things
asserted here are: it removes EVERYTHING belonging to the audit (an orphaned
findings row is invisible and impossible to clear from the UI), it refuses to
touch another tenant's data, and it does not take an AI-visibility time series
down with it.

Grouping is asserted because the merge key is deliberately dumb — case and
whitespace only. Anything cleverer would eventually merge two real clients into
one row, which is worse than a long list.

Run:  python3 -m tests.test_manage
"""
from __future__ import annotations
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite:///data/test_manage.db")
os.environ.setdefault("ARTIFACT_STORE", "local://data/test_manage_art")
os.environ.setdefault("SKIP_PSI", "true")

PORT = 8016
API = f"http://127.0.0.1:{PORT}"
FAILURES = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)
    return cond


def req(method, path, timeout=30):
    r = urllib.request.Request(API + path, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main():
    for p in ("data/test_manage.db", "data/test_manage.db-wal",
              "data/test_manage.db-shm"):
        if os.path.exists(p):
            os.remove(p)
    import shutil
    shutil.rmtree("data/test_manage_art", ignore_errors=True)

    from app import db
    from app.artifacts import put_artifact, get_artifact
    import uvicorn
    db.init_db()

    print("\nGROUPING BY CLIENT")
    ids = []
    for i, (name, score) in enumerate([
            ("Grand Furniture", 76), ("grand furniture ", 72),
            ("GRAND FURNITURE", 73), ("Junk Bee Gone", 79),
            ("Grand Home Furnishings", 61)]):
        aid = db.create_audit(partner_id="vici", client_name=name,
                              target_url="https://x.test/", options={})
        db.update_audit(aid, status="ready", overall_score=score,
                        coverage="159/313", pages_crawled=10,
                        created_at=time.time() - i * 60)
        ids.append(aid)

    groups = db.group_by_client(db.list_audits("vici"))
    by_name = {g["key"]: g for g in groups}
    check("case and whitespace variants merge into one client",
          len(groups) == 3, f"{len(groups)} groups: {[g['key'] for g in groups]}")
    check("the merged client keeps every run",
          by_name["grand furniture"]["runs"] == 3,
          str(by_name["grand furniture"]["runs"]))
    check("newest run is the headline",
          by_name["grand furniture"]["latest"]["overall_score"] == 76,
          str(by_name["grand furniture"]["latest"]["overall_score"]))
    check("history excludes the headline",
          len(by_name["grand furniture"]["history"]) == 2)
    # The important negative: similar names are NOT the same client.
    check("similarly-named clients are NOT merged",
          "grand home furnishings" in by_name and "grand furniture" in by_name,
          str(sorted(by_name)))

    print("\nDELETE REMOVES EVERYTHING BELONGING TO THE AUDIT")
    target = ids[0]
    db.save_findings(target, {"TECH-01": {
        "status": "Fail", "value": {}, "evidence": "x", "affected_pages": [],
        "severity": "High", "recommendation": "y", "confidence": 1.0,
        "source": "test"}})
    db.save_scores(target, {"overall": {"score": 76, "rating": "Strong"},
                            "sections": {"TECH": {"score": 76, "rating": "Strong",
                                                  "checked": 1, "total": 1,
                                                  "failing": 1, "need_access": 0}}})
    put_artifact(target, "crawl_artifact.json", b'{"pages":{}}')
    check("fixture audit has findings", len(db.get_findings(target)) == 1)
    check("fixture audit has an artifact",
          get_artifact(target, "crawl_artifact.json") is not None)

    from app.artifacts import delete_artifacts
    delete_artifacts(target)
    check("delete_audit reports success", db.delete_audit(target, "vici") is True)
    check("audit row is gone", db.get_audit(target) is None)
    check("findings are gone", db.get_findings(target) == {})
    check("section scores are gone",
          not (db.get_scores(target) or {}).get("sections"))
    check("artifact blob is gone",
          get_artifact(target, "crawl_artifact.json") is None)

    print("\nDELETE IS SCOPED AND SAFE")
    check("deleting an unknown id returns False",
          db.delete_audit("does-not-exist", "vici") is False)
    other = db.create_audit(partner_id="someone-else", client_name="Not Yours",
                            target_url="https://y.test/", options={})
    check("another tenant's audit cannot be deleted",
          db.delete_audit(other, "vici") is False)
    check("and it is still there", db.get_audit(other) is not None)

    print("\nA MONITOR TIME SERIES SURVIVES ITS AUDIT BEING DELETED")
    aid = db.create_audit(partner_id="vici", client_name="Series Co",
                          target_url="https://z.test/", options={})
    prof = db.create_ai_profile("vici", "Series Co",
                                {"brand": "Series Co", "domain": "z.test"}, [])
    run = db.create_ai_run("vici", prof, 1, audit_id=aid)
    db.delete_audit(aid, "vici")
    r = db.get_ai_run(run)
    check("the run still exists after its audit is deleted", r is not None)
    check("and is simply unlinked, not destroyed",
          r is not None and not r.get("audit_id"), str((r or {}).get("audit_id")))

    print("\nOVER HTTP, THE WAY THE UI CALLS IT")
    server = uvicorn.Server(uvicorn.Config("app.api:app", host="127.0.0.1",
                                           port=PORT, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(40):
        try:
            urllib.request.urlopen(API + "/healthz", timeout=2)
            break
        except Exception:
            time.sleep(0.3)

    victim = ids[3]
    st, body = req("DELETE", f"/api/audits/{victim}")
    check("DELETE /api/audits/{id} returns 200", st == 200, str(st))
    check("audit really gone", db.get_audit(victim) is None)
    st, body = req("DELETE", f"/api/audits/{victim}")
    check("deleting it twice 404s rather than 500s", st == 404, str(st))

    before = len(db.list_audits("vici"))
    st, body = req("POST", "/clients/grand%20furniture/prune")
    after = db.list_audits("vici")
    remaining = [a for a in after
                 if db.client_key(a["client_name"]) == "grand furniture"]
    check("prune redirects back to the dashboard", st in (200, 303), str(st))
    check("prune keeps exactly one run for that client",
          len(remaining) == 1, f"{len(remaining)} left")
    check("prune keeps the NEWEST run",
          remaining and remaining[0]["overall_score"] == 72,
          str(remaining[0]["overall_score"] if remaining else None))
    check("prune touched nothing else",
          len(after) == before - 1, f"{before} -> {len(after)}")

    st, body = req("GET", "/")
    check("dashboard renders grouped", st == 200 and b"Clients" in body)
    check("each client exposes the settings its last run used",
          b"Settings used" in body)
    check("and can seed a new audit from them without retyping",
          b"data-prefill" in body and b"function prefill" in body)

    print("\nPHASE SELECTION — RUN ONLY WHAT YOU NEED")
    # An unticked checkbox sends nothing, which looks identical to a caller
    # that predates the feature. Getting this backwards means either silently
    # skipping the judgment layer or silently ignoring the operator's choice.
    import urllib.parse as _up
    src2 = db.create_audit(partner_id="vici-internal", client_name="Phase Co",
                           target_url="https://phase.test/", options={})
    db.update_audit(src2, status="ready")
    put_artifact(src2, "crawl_artifact.json", b'{"pages":{}}')

    def submit(extra):
        d = {"target_url": "https://phase.test/", "client_name": "Phase Co"}
        d.update(extra)
        r = urllib.request.Request(API + "/audits",
                                   data=_up.urlencode(d).encode(), method="POST")
        class _NR(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k): return None
        try:
            resp = urllib.request.build_opener(_NR).open(r, timeout=30)
            loc = resp.headers.get("Location")
        except urllib.error.HTTPError as ex:
            loc = ex.headers.get("Location")
        return json.loads(db.get_audit(loc.rsplit("/", 1)[-1])["options"])

    o = submit({"phases": "1", "run_judgment": "1", "run_collectors": "1",
                "run_screenshots": "1"})
    check("every box ticked skips nothing",
          not any(o.get(k) for k in ("skip_judgment", "skip_collectors",
                                     "skip_screenshots")), str(o))
    o = submit({"phases": "1", "run_collectors": "1"})
    check("an unticked box really does skip that phase",
          o["skip_judgment"] and o["skip_screenshots"]
          and not o["skip_collectors"], str(o))
    o = submit({})
    check("a caller with no phases field still runs everything",
          not any(o.get(k) for k in ("skip_judgment", "skip_collectors",
                                     "skip_screenshots")), str(o))
    o = submit({"phases": "1", "run_judgment": "1", "reuse_crawl": "1"})
    # Deliberately NOT resolved here. The API and the worker are separate
    # containers, and with a local ARTIFACT_STORE the API cannot see a single
    # artifact the worker wrote — so resolving on this side found nothing,
    # dropped the option, and crawled the site anyway, which is precisely what
    # ticking the box was meant to prevent.
    check("the API records the intent and leaves resolution to the worker",
          o.get("reuse_crawl") is True and "reuse_artifact_from" not in o,
          str(o))

    from app.worker import _newest_artifact_for
    check("the worker resolves it to the newest run holding an artifact",
          _newest_artifact_for("https://phase.test/") == src2,
          str(_newest_artifact_for("https://phase.test/")))
    check("a URL we have never crawled resolves to nothing",
          _newest_artifact_for("https://never-audited.test/") is None)
    # WAS: asserted the dashboard contains a POST to /rerun. It does not any
    # more, and that is the point — "Run again" fills the form instead of
    # launching, so the settings can be seen and changed before anything runs.
    # The /rerun ENDPOINT stays, for the API and the stalled-run panel.
    check("dashboard offers a re-run", b"Run again" in body
          and b"data-prefill" in body)

    print("\nRE-RUN MAKES A NEW AUDIT, IT DOES NOT OVERWRITE")
    # The reason anyone re-runs is to see whether a fix worked. Re-queuing the
    # same row would overwrite the "before" and destroy the comparison.
    src = db.list_audits("vici")[0]
    db.save_findings(src["id"], {"TECH-01": {
        "status": "Pass", "value": {}, "evidence": "before", "affected_pages": [],
        "severity": "Low", "recommendation": "", "confidence": 1.0,
        "source": "test"}})
    # Counted UNFILTERED: the API creates audits owned by the internal
    # principal ("vici-internal"), while the fixtures above are seeded as
    # "vici". Filtering by the fixture's partner id would silently miss the
    # new row and make this assertion test nothing.
    before_n = len(db.list_audits())
    st, body = req("POST", f"/api/audits/{src['id']}/rerun")
    check("rerun returns 202", st == 202, str(st))
    new_id = json.loads(body)["audit_id"]
    check("a NEW audit id is returned", new_id != src["id"])
    check("the original still exists", db.get_audit(src["id"]) is not None)
    check("the original's findings are untouched",
          db.get_findings(src["id"])["TECH-01"]["evidence"] == "before")
    after_n = len(db.list_audits())
    check("audit count went up by one", after_n == before_n + 1,
          f"{before_n} -> {after_n}")
    nw = db.get_audit(new_id)
    check("target and client are carried over",
          nw["target_url"] == src["target_url"]
          and nw["client_name"] == src["client_name"])
    check("it groups under the same client",
          db.client_key(nw["client_name"]) == db.client_key(src["client_name"]))
    check("it is queued for the worker", nw["status"] == "queued", nw["status"])
    st, body = req("POST", "/api/audits/nope/rerun")
    check("rerunning an unknown audit 404s", st == 404, str(st))

    print("\nRUN AGAIN FILLS THE FORM, IT DOES NOT LAUNCH")
    # It used to POST straight to /rerun, copying the previous audit's stored
    # options verbatim and queueing it — so the settings you were about to
    # change were invisible, and an option added after the first run could
    # never turn on. That is what left twelve consecutive runs of one client
    # with no consent phase at all.
    #
    # A second button under the settings table already did what people
    # actually wanted. That IS what "run again" means, so there is one button.
    import json as _json2, time as _t
    from types import SimpleNamespace as _N
    import app.ui as _ui
    _a = [{"id": "abc", "client_name": "Ooten", "target_url": "http://o.com/",
           "status": "ready", "overall_score": 71, "overall_rating": "Weak",
           "coverage": "321/322", "pages_crawled": 1, "vertical": "",
           "completed_at": _t.time(), "created_at": _t.time(),
           "options": _json2.dumps({
               "max_pages": 150, "consent_products": ["Meta", "PPC"],
               "conversion_urls": ["https://o.com/thanks"],
               "implementation": "vici_gtm",
               "consent_industries": ["Legal - Defense"],
               "consent_states": ["TN"]})}]
    _h = _ui.dashboard_html(_a, _N(name="V", email="e"), 0,
                            caps={"consent": True, "aivis": True})
    check("no button posts to /rerun any more", "/rerun" not in _h)
    check("and the duplicate copy button is gone",
          "Copy these settings" not in _h)
    check("Run again carries the settings to prefill with",
          "Run again" in _h and "data-prefill" in _h)

    print("\nAND EVERY SETTING IS ACTUALLY IN THAT PAYLOAD")
    # Three fields shipped on the form in -39 and were never added to the
    # settings dict, so they were stored on the audit, missing from "Settings
    # used", and dropped by the prefill. The same omission that cost states
    # and industries five builds, on three more fields two builds later.
    for k in ("consent_products", "conversion_urls", "implementation",
              "consent_states", "consent_industries", "primary_markets"):
        check(f"{k} is carried", f'\\"{k}\\"' in _h or f'&quot;{k}&quot;' in _h)
    check("and the two fields the form no longer has are not shown as used",
          ">Vertical<" not in _h and ">Primary conversion<" not in _h)

    print("\nRE-RUN MUST NOT REPLAY A PHASE THAT DID NOT EXIST YET")
    # "Run again" copies the previous audit's options, which is right — same
    # settings. But an ABSENT key is not a decision to leave a phase off; it
    # is a run from before that phase existed. Replaying it forever means a
    # newly-shipped phase can never turn on.
    #
    # Twelve consecutive re-runs of one client all descended from an audit
    # created before the consent and AI checkboxes were added. `run_consent`
    # was never in the options, the phase never ran, and nine checkpoints came
    # back empty every single time — while the form had the box ticked by
    # default the whole way, because nobody had opened the form since run one.
    import json as _j
    from app import api as _api

    def _carried(stored):
        """What rerun() would enqueue, given a stored options blob."""
        opts = _j.loads(_j.dumps(stored))
        for key, default_on in (("run_consent", True), ("run_aivis", False)):
            if key not in opts and default_on:
                opts[key] = True
        return opts

    legacy = {"max_pages": 150, "skip_psi": False, "render_js": False}
    out = _carried(legacy)
    check("a phase absent from an old audit picks up today's default",
          out.get("run_consent") is True, str(out))
    check("and a phase that is off by default stays off",
          "run_aivis" not in out, str(out))
    off_on_purpose = {"max_pages": 150, "run_consent": False}
    check("but an explicit off is a decision, and decisions survive",
          _carried(off_on_purpose)["run_consent"] is False)
    on_on_purpose = {"max_pages": 150, "run_consent": True, "run_aivis": True}
    check("and an explicit on is carried through untouched",
          _carried(on_on_purpose)["run_aivis"] is True)
    # The real handler must contain the same rule, not just this test.
    import inspect as _insp
    _src = _insp.getsource(_api.rerun_audit)
    check("the rule lives in rerun_audit, not only in this test",
          "run_consent" in _src and "did not exist" in _src.lower())

    print("\nTHE DASHBOARD'S JAVASCRIPT ACTUALLY PARSES")
    # This has broken twice, both times the same way: the script is built
    # inside a Python f-string, so `\\n` becomes a real newline before the
    # browser ever sees it. Once that closed a regex literal mid-expression
    # ("Invalid regular expression: missing /") and once it split a `//`
    # comment so its second half parsed as code. Both shipped. Neither was
    # visible in Python — the page rendered fine and the script was dead.
    #
    # `node --check` on the rendered output is the only thing that catches it,
    # so it runs here rather than in someone's memory.
    import re as _re, subprocess as _sp, shutil as _sh, tempfile as _tf
    _scripts = _re.findall(r"<script[^>]*>(.*?)</script>", _h, _re.S)
    check("the dashboard ships exactly one inline script", len(_scripts) == 1,
          f"{len(_scripts)} found")
    if _sh.which("node"):
        _bad = []
        for _i, _s in enumerate(_scripts):
            with _tf.NamedTemporaryFile("w", suffix=".js", delete=False) as _fh:
                _fh.write(_s)
                _path = _fh.name
            _r = _sp.run(["node", "--check", _path], capture_output=True, text=True)
            os.unlink(_path)
            if _r.returncode:
                _bad.append(_r.stderr.strip().splitlines()[-1][:120])
        check("and every line of it is valid JavaScript", not _bad,
              "; ".join(_bad))
    else:
        print("  SKIP  node is not installed here — rendered JS unchecked")

    print("\nACCESS STATUS IS WORN BY THE FIELD IT DESCRIBES")
    # The three access pills sat in a block above three dropdowns that already
    # named the same three properties: "https://ootenlawfirm.com/ · via
    # reporting-zone" printed twice on one screen, six inches apart.
    check("each picker carries its own status mark",
          all(f"{k}mark" in _h for k in ("gsc", "ga4", "gtm")))
    check("and its own note for the case the dropdown cannot explain",
          all(f"{k}note" in _h for k in ("gsc", "ga4", "gtm")))
    check("the separate block of access pills is gone",
          "pill('Search Console'" not in _h and 'class="vpill' not in _h
          and ".vpill{" not in _h)
    check("a match prints no note at all — the selected option IS the answer",
          "st.ok ? '' : (st.detail" in _h)
    check("all four states still reach the mark",
          "'ours to fix'" in _h and "'no quick match'" in _h
          and "'not found'" in _h and "'found'" in _h)

    # THE BADGE'S MODIFIER CLASSES MUST NOT BE GENERIC.
    #
    # The first cut styled them `.amark.good` / `.amark.warn` / `.amark.bad`,
    # and `.warn` is already a callout box in this stylesheet — 8px padding
    # and a 3px gold border. The amber badge inherited both, rendered 14px
    # taller than the green one, and pushed its entire column 22px out of line
    # with the other two. Nothing errored; it just looked broken, and only in
    # the state nobody screenshots.
    _mods = sorted(set(_re.findall(r"\.amark\.([A-Za-z0-9_-]+)\{", _h))
                   | set(_re.findall(r"\.(amark--[A-Za-z0-9_-]+)\{", _h)))
    check("the badge has its three state classes", len(_mods) == 3, str(_mods))
    _clash = [m for m in _mods
              if _re.search(r"(?:^|[\n,;}])\." + _re.escape(m) + r"\{", _h)
              and not m.startswith("amark--")]
    check("and none of them is a bare class name used elsewhere", not _clash,
          str(_clash))

    print("\nA RUN WHOSE WORKER VANISHED DOES NOT STAY 'IN FLIGHT' FOREVER")
    # THE CASE: an audit reached "collecting Search Console, Analytics and
    # backlink data", stamped a heartbeat 73 seconds in, and never wrote
    # again. `error` was still null — and that absence is the evidence, since
    # every exception path here records one. The process went away: an OOM
    # kill or a recycled instance. Nothing moved the row, so it counted under
    # "in flight" on the dashboard indefinitely for a run nobody was working
    # on.
    import time as _t3
    from app import db as _db2, worker as _wk2
    _now = _t3.time()
    _dead = _db2.create_audit("vici", "Dead Co", "https://d.test/", None, None, {})
    _db2.update_audit(_dead, status="checking",
                      progress="collecting Search Console, Analytics and "
                               "backlink data",
                      heartbeat_at=_now - 1800)
    _live = _db2.create_audit("vici", "Live Co", "https://l.test/", None, None, {})
    _db2.update_audit(_live, status="crawling", heartbeat_at=_now - 20)
    _old = _db2.create_audit("vici", "Old Co", "https://o.test/", None, None, {})
    _db2.update_audit(_old, status="checking")      # no heartbeat at all
    _wk2._reap_abandoned()
    check("the abandoned run is marked failed",
          _db2.get_audit(_dead)["status"] == "failed")
    check("and the message says it was interrupted, not that the site broke",
          "interrupted rather than failed"
          in (_db2.get_audit(_dead).get("error") or ""))
    check("and names the step it died on",
          "collecting Search Console" in (_db2.get_audit(_dead).get("error") or ""))
    check("a live run is untouched",
          _db2.get_audit(_live)["status"] == "crawling")
    # Unknown is not dead. A run from before heartbeats existed has none, and
    # guessing there would fail work that is genuinely running.
    check("a run with no heartbeat at all is left alone",
          _db2.get_audit(_old)["status"] == "checking")

    print("\nAND THE DASHBOARD COUNTS IT HONESTLY IN THE MEANTIME")
    from app.ui import _stalled as _st2
    check("the stall rule is shared, not re-implemented per page",
          _st2({"status": "checking", "heartbeat_at": _now - 1800}))
    check("a fresh heartbeat is not stalled",
          not _st2({"status": "checking", "heartbeat_at": _now - 5}))
    check("and a finished audit is never stalled",
          not _st2({"status": "ready", "heartbeat_at": _now - 999999}))
    _h2 = _ui.dashboard_html(
        [{"id": "s1", "client_name": "Stalled Co", "target_url": "https://a.test/",
          "status": "checking", "heartbeat_at": _now - 1800, "overall_score": None,
          "overall_rating": None, "coverage": None, "pages_crawled": 118,
          "created_at": _now - 2000, "options": "{}"}],
        _N(name="V", email="e"), 0, caps={"consent": True, "aivis": True})
    _t2 = _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", _h2))
    check("it is counted as stalled, not in flight",
          "0 in flight" in _t2 and "1 stalled" in _t2,
          _t2[_t2.find("clients") - 20:_t2.find("clients") + 60])
    check("and the card says stalled instead of spinning",
          "stalled" in _t2 and "<span class='spin'>" not in _h2)

    print("\nWHAT AN UNTICKED PHASE ALREADY KNEW COMES FORWARD")
    # THE BUG, REPLAYED.
    #
    # A re-run with the judgment layer and the collectors switched off - the
    # answers already existed from the run before - produced seventy-six
    # unanswered rows and a lower score. Unticking a box meant throwing the
    # earlier answer away, which makes the cheap re-run strictly worse than
    # the expensive one and moves the score for a reason nobody can see.
    import time as _t3
    from app import db as _db3, worker as _wk3
    _old = _db3.create_audit("vici", "Carry Co", "https://carry.test/",
                             None, None, {})
    _db3.save_findings(_old, {
        "EEAT-01": {"status": "Pass", "value": {}, "evidence": "measured then",
                    "affected_pages": [], "severity": "Low",
                    "recommendation": "", "confidence": 1.0,
                    "source": "llm_judgment"},
        "OFF-01": {"status": "Need Access", "value": {},
                   "evidence": "no backlink key", "affected_pages": [],
                   "severity": "Low", "recommendation": "", "confidence": 0.0,
                   "source": "dfs_missing"}})
    _db3.update_audit(_old, status="ready", completed_at=_t3.time() - 60)

    _new = _db3.create_audit("vici", "Carry Co", "https://carry.test/",
                             None, None, {})
    _a3 = _db3.get_audit(_new)
    _carried = _wk3._carry_forward(
        _a3, {"skip_judgment": True, "skip_collectors": True}, _new,
        {"TECH-01": {"status": "Pass"}})
    check("an answered row from the last run comes forward",
          "EEAT-01" in _carried, str(sorted(_carried)))
    check("and it is stamped with where it came from",
          _carried.get("EEAT-01", {}).get("value", {}).get("carried_from")
          == _old)
    check("an unanswered row is not carried - that is just an older gap",
          "OFF-01" not in _carried, str(sorted(_carried)))
    _ran = _wk3._carry_forward(_a3, {}, _new, {})
    check("nothing is carried for a phase that actually ran",
          not _ran, str(sorted(_ran)))
    # And the panel says so rather than moving the score in silence.
    from engine.report import _todo_panel as _tp3
    _html3 = "".join(_tp3({}, {}, {"extras": {
        "phases_run": {"run_consent": True, "run_aivis": True},
        "carried_forward": {"count": 44, "from": [_old], "ids": []}}}))
    check("the panel counts what was carried over",
          "Carried over from an earlier run" in _html3 and "44" in _html3)

    print("\n" + "=" * 68)
    print(f"  {len(FAILURES)} FAILED: {FAILURES}" if FAILURES
          else "  ALL CHECKS PASSED — delete is complete and scoped; grouping is safe")
    print("=" * 68 + "\n")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
