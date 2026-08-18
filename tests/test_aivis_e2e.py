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
