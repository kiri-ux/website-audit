"""
Web service — thin by design.

Its entire job is: authenticate, validate, enqueue, and read results back out.
It never crawls. Every handler here returns in milliseconds.

Run:  uvicorn app.api:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations
import json
import os
import sys
import time

from urllib.parse import quote as _urlquote

from fastapi import FastAPI, HTTPException, Header, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from .config import cfg
from . import db, tenancy, version
from .queue import get_queue
from .artifacts import get_artifact, put_artifact, delete_artifacts

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.report import render_html
from engine import checks as engine_checks
from engine import scoring as engine_scoring
from .capture import artifact_from_capture
from engine.pdf_report import build_pdf, build_snapshot
from engine.summarise import build_summary, polish_with_llm, can_polish

app = FastAPI(title="Vici SEO/GEO Audit", version="1.0")
Q = get_queue()


@app.on_event("startup")
def _startup():
    db.init_db()

    from .config import warn_startup
    warn_startup()
    print(f"[api] up · {version.label()} · {cfg.summary()}", flush=True)


def principal(x_api_key: str | None):
    try:
        return tenancy.resolve(x_api_key)
    except tenancy.AuthError as e:
        raise HTTPException(401, str(e))


# ------------------------------------------------------------------ models
class AuditRequest(BaseModel):
    target_url: str
    client_name: str
    vertical: str | None = Field(None, description="ecommerce|finance_ymyl|local_service")
    business_model: str | None = None
    # Intake. Brendan's template carries these on the cover ("Business Model",
    # "Primary Markets", "Primary Conversion") and they are not guessable from a
    # crawl. `channels` is the one that changes findings rather than copy: it is
    # what makes a missing LinkedIn pixel a defect instead of a non-event.
    primary_markets: str | None = None
    primary_conversion: str | None = None
    max_pages: int | None = None
    max_depth: int | None = None
    render_js: bool | None = None
    skip_psi: bool | None = None
    user_agent: str | None = None


# ------------------------------------------------------------------ API
@app.get("/healthz")
def healthz():
    # `oauth_setup` disambiguates the two ways /oauth/google/start can 404:
    # the build is too old to have the route, or OAUTH_SETUP_TOKEN is unset or
    # mistyped. Both look identical from a browser, which is a bad place to
    # leave someone mid-setup. It reports whether the door is open, never the
    # key — the routes still refuse anything but an exact token match.
    #
    # THIS ROUTE MUST NOT DEPEND ON A DATABASE OR ON REDIS.
    #
    # It used to call Q.depth(), which is a blocking Redis round trip. Render
    # polls this endpoint continuously and pulls the instance out of service
    # when it stops answering — so a slow queue or a busy Postgres did not
    # degrade the API, it DELETED it, and the browser got a 502 from a service
    # whose own code was working perfectly. A liveness check that depends on a
    # dependency is not a liveness check; it is a way of converting every
    # dependency's bad minute into your own outage.
    #
    # Queue depth is still useful, so it is still reported — but as a
    # best-effort number that degrades to null, and never as a reason to fail.
    depth = None
    try:
        depth = Q.depth()
    except Exception:  # noqa: BLE001
        pass
    # THE WHOLE GOOGLE PICTURE, NOT A THIRD OF IT.
    #
    # This reported `google_client` — the presence of GOOGLE_CLIENT_ID — and
    # nothing else. All three values are required and any one of them missing
    # produces the same symptom, so a health check that confirms one of three
    # is worse than none: it tells you the part that is fine.
    #
    # `logins` is the count, never the labels and obviously never the tokens.
    goog = {"client_id": bool(os.getenv("GOOGLE_CLIENT_ID")),
            "client_secret": bool(os.getenv("GOOGLE_CLIENT_SECRET")),
            "tokens": False, "logins": 0}
    # Whether those tokens carry the Tag Manager scope is NOT reported here.
    # Answering it means calling Google, and healthz calling a dependency is
    # exactly what made /healthz unanswerable and got the instance pulled.
    # The access preflight answers it instead, per site, in one click.
    try:
        idx = _ga._token_index()
        goog["tokens"] = bool(idx)
        goog["logins"] = len(idx)
    except Exception:  # noqa: BLE001
        pass
    goog["ready"] = all((goog["client_id"], goog["client_secret"],
                         goog["tokens"]))
    return {"ok": True, "mode": cfg.mode, "queue_depth": depth,
            "oauth_setup": bool(os.getenv("OAUTH_SETUP_TOKEN")),
            "google": goog,
            # Kept so anything already watching this key keeps working.
            "google_client": goog["client_id"],
            **version.info()}


@app.post("/api/audits", status_code=202)
def create_audit(req: AuditRequest, x_api_key: str | None = Header(None)):
    """
    Enqueue an audit. Returns 202 immediately — the crawl has NOT run yet.
    Poll GET /api/audits/{id} for status.
    """
    p = principal(x_api_key)
    if not req.target_url.startswith(("http://", "https://")):
        raise HTTPException(400, "target_url must include a scheme")
    opts = {k: v for k, v in req.model_dump().items()
            if k in ("max_pages", "max_depth", "render_js", "skip_psi",
                     "user_agent", "primary_markets",
                     "primary_conversion") and v is not None}
    aid = db.create_audit(tenancy.owner_for_new_audit(p), req.client_name,
                          req.target_url, req.vertical, req.business_model, opts)
    Q.enqueue(aid)
    return {"audit_id": aid, "status": "queued",
            "poll": f"/api/audits/{aid}", "report": f"/audits/{aid}"}


@app.get("/api/capabilities")
def capabilities():
    """
    What the WORKER can do, as the worker last reported it.

    Not what this service can do. Every credential that matters lives on the
    worker, so an API-side `os.getenv` check would answer confidently about the
    wrong container.
    """
    return _worker_caps()


def _worker_caps() -> dict:
    from .worker import CAPS_KEY
    try:
        blob = db.get_blob(CAPS_KEY, "capabilities.json")
        if not blob:
            return {"known": False,
                    "why": "The worker has not reported in since its last "
                           "deploy. Redeploy it, or start any audit — it "
                           "publishes on startup."}
        d = json.loads(blob)
        d["known"] = True
        d["age_s"] = round(time.time() - (d.get("at") or 0))
        return d
    except Exception as exc:  # noqa: BLE001
        return {"known": False, "why": f"{type(exc).__name__}: {exc}"}


@app.get("/api/audits")
def list_audits(x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    return {"audits": db.list_audits(p.scope)}


@app.get("/api/audits/{audit_id}")
def get_audit(audit_id: str, x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    a = db.get_audit(audit_id, p.scope)
    if not a:
        raise HTTPException(404, "audit not found")
    out = dict(a)
    if a["status"] == "ready":
        out["scores"] = db.get_scores(audit_id)
    return out


@app.get("/api/audits/{audit_id}/findings")
def get_findings(audit_id: str, x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    if not db.get_audit(audit_id, p.scope):
        raise HTTPException(404, "audit not found")
    return {"findings": db.get_findings(audit_id)}


@app.get("/api/audits/{audit_id}/artifact")
def artifact(audit_id: str, x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    if not db.get_audit(audit_id, p.scope):
        raise HTTPException(404, "audit not found")
    blob = get_artifact(audit_id, "crawl_artifact.json")
    if not blob:
        raise HTTPException(404, "artifact not available")
    return Response(blob, media_type="application/json")



# ------------------------------------------------------------------ brand
from .brand import FAVICON_SVG, APPLE_ICON


def _asset(blob: bytes | None, media: str):
    if not blob:
        raise HTTPException(404, "not found")
    return Response(blob, media_type=media,
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/favicon.svg")
def favicon_svg():
    return _asset(FAVICON_SVG, "image/svg+xml")


@app.get("/favicon.ico")
def favicon_ico():
    # Browsers request /favicon.ico unprompted whatever the <link> tags say.
    # Serving the SVG here stops a 404 per page view in the logs.
    return _asset(FAVICON_SVG, "image/svg+xml")


@app.get("/apple-touch-icon.png")
def apple_touch_icon():
    return _asset(APPLE_ICON, "image/png")


# ------------------------------------------------------- Google OAuth setup
#
# A ONE-TIME, OPERATOR-FACING pair of routes. Their only job is to turn a Vici
# Google login into a refresh token you can paste into GOOGLE_TOKENS. The
# collectors have always known how to spend that token; there was simply no way
# to mint one without leaving the app, so all 38 Search Console and Analytics
# rows sat at Need Access with no route to change it.
#
# This is NOT a client-facing consent flow and must not become one. You are
# authorising a VICI login, once, and the token then inherits every property
# that login can already see — including properties added next month. A client
# grants access by adding that Vici login to their property, exactly the way
# they already do for GTM. See engine/collectors/analytics.py.
#
# Gated behind OAUTH_SETUP_TOKEN. With the variable unset both routes 404, so
# the surface does not exist at all in normal operation. Set it, mint the
# tokens, unset it.
import html as _html  # noqa: E402

from engine.collectors import analytics as _ga  # noqa: E402


def _hesc(x) -> str:
    return _html.escape(str(x if x is not None else ""))


def _setup_token() -> str:
    return os.getenv("OAUTH_SETUP_TOKEN", "")


def _redirect_uri(request: Request) -> str:
    # Must match the Authorised redirect URI in the Google Cloud console
    # EXACTLY, including scheme and trailing path. Render terminates TLS in
    # front of us, so the app sees http:// and Google would reject it.
    base = str(request.base_url).rstrip("/")
    if base.startswith("http://") and "localhost" not in base \
            and "127.0.0.1" not in base:
        base = "https://" + base[len("http://"):]
    return base + "/oauth/google/callback"


@app.get("/api/access-check")
def access_check(target_url: str = ""):
    """
    Preflight: do we have Search Console and Analytics for this site?

    Runs on the API so the answer comes back while someone is still filling in
    the form. That means GOOGLE_TOKENS has to be readable here as well as on
    the worker — see DEPLOY.md. If it is only on the worker this returns
    "not set on this service", which is accurate about the API and says
    nothing about whether the audit itself will find the data.
    """
    if not target_url.startswith(("http://", "https://")):
        raise HTTPException(400, "target_url must include a scheme")
    return _ga.probe(target_url)


@app.get("/extension.zip")
def extension_zip():
    """
    The Chrome extension, zipped on the fly.

    It is an unpacked extension, which means the operator needs the actual
    folder — and "ask someone for the folder" is not a step that survives
    contact with a Tuesday. Building it here means the download is always the
    version this deployment expects.
    """
    import io, zipfile
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "extension")
    if not os.path.isdir(root):
        raise HTTPException(404, "extension source not present in this image")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(root):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.relpath(full, root))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition":
                             'attachment; filename="vici-audit-capture.zip"'})


@app.get("/api/properties")
def list_properties():
    """
    Every Search Console and GA4 property our logins can see.

    Populates the two dropdowns on the audit form. The point is not the happy
    path — the matcher usually gets that — it is the miss: when nothing
    matches, "what IS in there?" is the only useful next question, and the
    answer decides whether to email the client or just pick the right row.
    """
    return _ga.list_properties()


@app.get("/oauth/google/start")
def oauth_start(request: Request, t: str = "", label: str = ""):
    if not _setup_token() or t != _setup_token():
        raise HTTPException(404, "not found")
    if not label:
        raise HTTPException(400, "label is required — name the Vici login, e.g. "
                                 "?label=seo-main")
    url = _ga.consent_url(_redirect_uri(request), state=f"{label}|{t}")
    if not url:
        raise HTTPException(400, "GOOGLE_CLIENT_ID is not set on this service")
    return RedirectResponse(url, status_code=302)


@app.get("/oauth/google/callback", response_class=HTMLResponse)
def oauth_callback(request: Request, code: str = "", state: str = "",
                   error: str = ""):
    label, _, tok = state.partition("|")
    if not _setup_token() or tok != _setup_token():
        raise HTTPException(404, "not found")
    if error or not code:
        raise HTTPException(400, f"Google returned: {error or 'no code'}")
    try:
        data = _ga.exchange_code(code, _redirect_uri(request))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"token exchange failed: {type(e).__name__}: {e}")
    refresh = data.get("refresh_token")
    if not refresh:
        # Google only returns a refresh token on the FIRST consent for a given
        # client/login pair. `prompt=consent` in consent_url() is what forces it
        # on repeat runs; if it is still missing, the grant already exists.
        raise HTTPException(
            400, "Google did not return a refresh token. Remove this app at "
                 "myaccount.google.com/permissions for that login and try again.")

    # Show the merged value rather than the bare token, because GOOGLE_TOKENS is
    # a JSON object of every login and hand-editing it is where the mistakes
    # happen.
    try:
        current = json.loads(os.getenv("GOOGLE_TOKENS", "") or "{}")
    except Exception:  # noqa: BLE001
        current = {}
    current[label] = refresh
    merged = json.dumps(current, indent=2)
    from .brand import HEAD_TAGS
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset='utf-8'>{HEAD_TAGS}"
        f"<title>Google access granted — {_hesc(label)}</title>"
        f"<style>body{{font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;"
        f"max-width:760px;margin:48px auto;padding:0 20px;color:#14140f}}"
        f"code,pre{{background:#f6f5f2;border:1px solid #e6e5e1;border-radius:8px}}"
        f"pre{{padding:14px;overflow:auto;font-size:13px}}"
        f"h1{{font-size:20px}}</style></head><body>"
        f"<h1>Access granted for <code>{_hesc(label)}</code></h1>"
        f"<p>Paste this as <b>GOOGLE_TOKENS</b> on <b>BOTH</b> "
        f"<b>vici-audit-worker</b> and <b>vici-audit-api</b>. It already "
        f"includes every login this service currently knows about, so replace "
        f"the whole value.</p>"
        f"<p style='background:#fdf6ec;border:1px solid #f0d9a8;"
        f"border-radius:8px;padding:11px 14px'>Both services, not just the "
        f"worker &mdash; and <b>GOOGLE_CLIENT_ID</b> and "
        f"<b>GOOGLE_CLIENT_SECRET</b> have to be on both too. The worker "
        f"collects the data; the API runs the access check on the audit form. "
        f"A refresh token is useless without the client pair, because it is "
        f"the pair that exchanges it.</p>"
        f"<pre>{_hesc(merged)}</pre>"
        f"<p>Then unset <b>OAUTH_SETUP_TOKEN</b> — these two routes disappear "
        f"when it is gone.</p>"
        f"<p style='color:#898781;font-size:13px'>This token inherits whatever "
        f"this login can already see in Search Console and Analytics, including "
        f"properties added later. It does not grant access on its own: a client "
        f"still has to add the login to their property.</p>"
        f"</body></html>")


# ------------------------------------------------------------------ UI
from .ui import dashboard_html, audit_html  # noqa: E402
from .ui_aivis import visibility_html, visibility_index_html  # noqa: E402


@app.get("/", response_class=HTMLResponse)
def home(x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    return dashboard_html(db.list_audits(p.scope), p, Q.depth(),
                          caps=_worker_caps())


@app.post("/audits")
def submit_form(target_url: str = Form(...), client_name: str = Form(...),
                vertical: str = Form(""), max_pages: int = Form(150),
                render_js: str = Form(""), browser_ua: str = Form(""),
                skip_psi: str = Form(""), primary_markets: str = Form(""),
                primary_conversion: str = Form(""),
                partner: str = Form(""),
                run_judgment: str = Form(""),
                run_collectors: str = Form(""),
                run_screenshots: str = Form(""),
                run_reputation: str = Form(""),
                run_aivis: str = Form(""),
                run_consent: str = Form(""),
                consent_states: str = Form(""),
                consent_industries: str = Form(""),
                consent_products: str = Form(""),
                conversion_urls: str = Form(""),
                implementation: str = Form(""),
                quick: str = Form(""),
                do_audit: str = Form(""),
                reuse_crawl: str = Form(""), phases: str = Form(""),
                gsc_property: str = Form(""), ga4_property_id: str = Form(""),
                gtm_container: str = Form(""),
                x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    # Phases are opt-OUT in the options dict (skip_*) but opt-IN on the form,
    # because a checkbox ticked to NOT do something is how people accidentally
    # skip the judgment layer and then wonder why E-E-A-T is empty.
    #
    # An unticked checkbox sends NOTHING, which is indistinguishable from a
    # caller that does not know about phases at all. The hidden `phases` field
    # tells them apart: present means this form owns the choice and an absent
    # box really means off; absent means an older client or a script, and
    # everything runs, which is the pre-existing behaviour.
    opts = {"max_pages": max_pages, "skip_psi": bool(skip_psi),
            "render_js": bool(render_js)}
    if phases:
        opts["skip_judgment"] = not run_judgment
        opts["skip_collectors"] = not run_collectors
        opts["skip_screenshots"] = not run_screenshots
        if run_reputation:
            opts["run_reputation"] = True
    # Opt-IN, not opt-out like the three above. This phase spends money per
    # question across several platforms, so an unticked box means off — and so
    # does a script that has never heard of it.
    if run_aivis:
        opts["run_aivis"] = True
    if run_consent:
        opts["run_consent"] = True

    # WHO THE CLIENT IS, AND WHERE THEY SELL, IS NOT A CONSENT SETTING.
    #
    # Every line below used to sit inside `if run_consent:`, which meant that
    # running a full audit with the consent box unticked threw away the
    # conversion URLs, the products, the industries, the derived states and
    # the implementation — silently, with the form showing them right up until
    # submit. The dashboard then read them back off the stored options, found
    # nothing, and printed "—", which is what "conversion urls didn't save"
    # actually was: they saved exactly as far as the guard and no further.
    #
    # These describe the CLIENT. They belong on the record whichever job ran,
    # so a re-run prefills from them and the next scan does not need them
    # retyped. The consent phase still reads them only when it runs.
    #
    # STATES AND INDUSTRIES WERE NEVER PLUMBED, AND THAT SILENTLY GUTTED
    # TWO CHECKPOINTS.
    #
    # The scanner takes both. The worker passed both. Nothing ever SET them,
    # so `states` arrived as None on every run — which meant the GPC pass
    # never ran (CONS-06 was permanently "Need Access"), the per-state loop
    # never executed, and CONS-08, titled "State privacy law requirements",
    # reported on the single universal privacy-policy-link row: "All 1 checked
    # requirements are met across US."
    #
    # Twenty states and three sensitive-industry rules were vendored, tested,
    # and unreachable.
    st = [x.strip().upper() for x in consent_states.replace(",", " ").split()
          if x.strip()]
    # DERIVE FROM THE MARKETS WHEN THE FORM DID NOT SEND A LIST.
    #
    # The states box used to be prefilled `CA CO CT TX VA OR` — a reasonable
    # guess, and wrong for every client who does not sell there. A Knoxville
    # law firm had California's law tested and Tennessee's ignored, and
    # nothing in the report said so.
    #
    # The markets already say where they sell. Reading the states off them
    # makes the guess unnecessary, and keeps a hand-typed list authoritative
    # when someone does override it. Filtered to the states we actually have
    # checks for, because listing one we cannot test is a promise the scan
    # does not keep.
    if not st and primary_markets.strip():
        try:
            from engine.geo import summarize as _geo
            st = _geo(primary_markets)["checkable"]
        except Exception:  # noqa: BLE001
            st = []
    if st:
        opts["consent_states"] = st
    ind = [x.strip() for x in consent_industries.split(",") if x.strip()]
    if ind:
        opts["consent_industries"] = ind
    # WIRED THE SAME DAY THE FIELDS SHIPPED, on purpose. Adding an input the
    # server drops is the exact failure this codebase spent a day chasing:
    # states and industries sat on the scanner's signature for five builds
    # with nothing setting them, and two checkpoints quietly answered nothing
    # the whole time.
    prods = [x.strip() for x in consent_products.split(",") if x.strip()]
    if prods:
        opts["consent_products"] = prods
    # NO CAP. The browser already harvested and de-duplicated these, and a
    # client with fourteen landing pages has fourteen pages where a conversion
    # pixel can fire ungated. Silently keeping six would be the same failure as
    # every other quiet truncation in this codebase: a list that looks complete
    # and is not.
    convs, seen = [], set()
    for u in conversion_urls.split():
        u = u.strip()
        key = u.lower().split("://")[-1].lstrip("www.").rstrip("/")
        if u and key not in seen:
            seen.add(key)
            convs.append(u)
    if convs:
        opts["conversion_urls"] = convs
    if implementation.strip():
        opts["implementation"] = implementation.strip()

    # A CONSENT CHECK IS A ONE-PAGE AUDIT.
    #
    # It could have been a separate record type with its own queue job, its own
    # status page and its own history — and every one of those would be a
    # second copy of something that already works here. A consent scan needs
    # exactly what an audit needs: a worker with a browser, a place to put the
    # answer, and a page that shows progress. So it is an audit with one page
    # and one phase, and it inherits the queue, the status page, the report,
    # the client grouping and the rerun button for free.
    # THE TWO JOBS ARE INDEPENDENT NOW.
    #
    # "What to run" used to be seven peer checkboxes mixing phases of the
    # audit with a separate product. Untick every audit phase and you still
    # got a 150-page crawl doing nothing with the result. The form asks the
    # real question — full audit, consent check, or both — and unticking the
    # audit reduces it to the one-page consent path that already existed.
    if not do_audit and run_consent:
        quick = "consent"
    if quick == "consent":
        opts.update({"max_pages": 1, "skip_judgment": True,
                     "skip_collectors": True, "skip_screenshots": True,
                     "skip_dataforseo": True, "skip_psi": True,
                     "run_consent": True, "run_aivis": False,
                     "quick": "consent"})
    # Reuse the newest crawl we still hold for this exact URL. The client's
    # server is not asked for another 150 pages just because our LLM key was
    # missing last time.
    # Resolved by the WORKER, not here. The API and the worker are separate
    # containers, and with a local ARTIFACT_STORE the API cannot see a single
    # artifact the worker wrote — so looking it up on this side silently found
    # nothing, dropped the option, and crawled the site anyway. Which is the
    # exact thing the operator ticked the box to avoid.
    if reuse_crawl:
        opts["reuse_crawl"] = True
    # Operator-chosen properties beat the automatic match. Stored on the audit
    # so a re-run keeps the choice rather than making someone find it again.
    if gsc_property.strip():
        opts["gsc_property"] = gsc_property.strip()
    if ga4_property_id.strip():
        opts["ga4_property_id"] = ga4_property_id.strip()
    if gtm_container.strip():
        opts["gtm_container"] = gtm_container.strip()
    # `vertical` and `primary_conversion` came off the form: industry says
    # what the business is far more precisely than four hardcoded verticals,
    # and the conversion was intake nobody filled in and nothing branched on.
    # Both are still accepted by the JSON API, so a script that sends them
    # keeps working and an old audit still renders what it stored.
    for k, v in (("primary_markets", primary_markets),
                 ("primary_conversion", primary_conversion),
                 ("partner", partner)):
        if v.strip():
            opts[k] = v.strip()
    if browser_ua:
        opts["user_agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    aid = db.create_audit(tenancy.owner_for_new_audit(p), client_name, target_url,
                          vertical or None, None, opts)
    Q.enqueue(aid)
    return RedirectResponse(f"/audits/{aid}", status_code=303)




@app.post("/audits/{audit_id}/rerun")
def rerun_audit(audit_id: str, reuse_crawl: str = Form(""),
                x_api_key: str | None = Header(None)):
    """
    Run the same site again, as a NEW audit.

    Not a re-queue of the same row. Findings are stored, so re-running in place
    would overwrite the old result and quietly destroy the before/after you get
    from a fix — which is the main reason anyone re-runs. A new row keeps the
    history, groups under the same client, and the prune button is there when
    the history stops being useful.
    """
    p = principal(x_api_key)
    a = db.get_audit(audit_id, p.scope)
    if not a:
        raise HTTPException(404, "audit not found")
    try:
        opts = json.loads(a.get("options") or "{}")
        opts = opts if isinstance(opts, dict) else {}
    except Exception:
        opts = {}

    # AN OPTION THAT DID NOT EXIST CANNOT HAVE BEEN A CHOICE.
    #
    # This copies the previous audit's options, which is right: "run it again"
    # means the same settings. But a key that is ABSENT is not a decision to
    # leave that phase off — it is a run from before the phase existed, and
    # replaying it forever means a newly-shipped phase can never turn on.
    #
    # That is exactly what happened. Twelve consecutive re-runs of one client
    # all descended from an audit created before the consent and AI checkboxes
    # were added, so `run_consent` was never in the options, the phase never
    # ran, and nine checkpoints came back empty on every single one. The form
    # had the box ticked by default the whole time; nobody had opened the form
    # since the first run.
    #
    # So: an absent key gets today's default, a present key is honored. Only
    # the first is a gap; the second is a decision, and decisions survive.
    for key, default_on in (("run_consent", True), ("run_aivis", False)):
        if key not in opts and default_on:
            opts[key] = True

    # Offered by the stalled-run panel. A run that died after the crawl already
    # has its pages stored, and going back out to the client's server to fetch
    # them again is both slow and rude.
    if reuse_crawl:
        opts["reuse_crawl"] = True
    new_id = db.create_audit(tenancy.owner_for_new_audit(p), a["client_name"],
                             a["target_url"], a.get("vertical"),
                             a.get("business_model"), opts)
    Q.enqueue(new_id)
    return RedirectResponse(f"/audits/{new_id}", status_code=303)


@app.post("/api/audits/{audit_id}/rerun", status_code=202)
def rerun_audit_api(audit_id: str, x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    a = db.get_audit(audit_id, p.scope)
    if not a:
        raise HTTPException(404, "audit not found")
    try:
        opts = json.loads(a.get("options") or "{}")
        opts = opts if isinstance(opts, dict) else {}
    except Exception:
        opts = {}
    new_id = db.create_audit(tenancy.owner_for_new_audit(p), a["client_name"],
                             a["target_url"], a.get("vertical"),
                             a.get("business_model"), opts)
    Q.enqueue(new_id)
    return {"audit_id": new_id, "status": "queued", "rerun_of": audit_id,
            "poll": f"/api/audits/{new_id}", "report": f"/audits/{new_id}"}


# ------------------------------------------------------------------ stop
#
# STOP IS A REQUEST, NOT A KILL.
#
# The worker is a separate container. This process cannot signal it and must
# not try - the worker may be three phases into someone else's job by the time
# a signal arrives. So a stop writes a timestamp the worker reads at every
# progress step, and the run ends at the next one: within seconds during the
# crawl or the judgment pass, at worst one phase later.
#
# The row keeps everything it had already answered. A cancelled audit with 180
# findings is more useful than no audit, and a Stop button that also destroys
# the work is one nobody presses.
_STOPPABLE = {"queued", "crawling", "checking", "scoring", "capturing"}


def _request_stop(audit_id: str, scope):
    a = db.get_audit(audit_id, scope)
    if not a:
        raise HTTPException(404, "audit not found")
    if a.get("status") not in _STOPPABLE:
        return a, False
    db.update_audit(audit_id, cancel_at=time.time(),
                    progress="stopping at the end of the current step")

    # NOTHING IS COMING FOR THIS ONE.
    #
    # Two cases where waiting for the run to notice means waiting forever:
    #
    #   * it never started - it is still in the queue, so there is no process
    #     to read the flag;
    #   * it was interrupted - a deploy mid-scan, or the instance recycled.
    #     The process that held it is gone, and the giveaway is that its
    #     heartbeat stopped moving. Somebody pressing Stop on that row would
    #     otherwise sit and watch "stopping" until the stall detector caught
    #     up, and then be told the run "stopped responding" - a fault report,
    #     for a thing they asked for.
    #
    # Both close here, immediately, as stopped.
    from .ui import STALE_AFTER_S
    hb = a.get("heartbeat_at")
    gone = bool(hb) and (time.time() - float(hb)) > STALE_AFTER_S
    if a.get("status") == "queued" or gone:
        db.update_audit(audit_id, status="cancelled", error=None,
                        progress=("stopped before it started"
                                  if a.get("status") == "queued" else
                                  "stopped - this run had already been "
                                  "interrupted, most likely by a deploy"),
                        completed_at=time.time())
    return a, True


@app.post("/api/audits/{audit_id}/stop")
def stop_audit_api(audit_id: str, x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    a, stopped = _request_stop(audit_id, p.scope)
    return {"audit_id": audit_id, "stopping": stopped,
            "status": db.get_audit(audit_id, p.scope).get("status"),
            "note": ("stops at the end of the current step" if stopped else
                     f"nothing to stop — this run is {a.get('status')}")}


@app.post("/audits/{audit_id}/stop")
def stop_audit_form(audit_id: str, x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    _request_stop(audit_id, p.scope)
    return RedirectResponse(f"/audits/{audit_id}", status_code=303)


# ------------------------------------------------------------------ delete
@app.delete("/api/audits/{audit_id}")
def delete_audit_api(audit_id: str, x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    # Ownership is checked BEFORE any blob is touched. Deleting artifacts first
    # would let one tenant wipe another tenant's storage and still get a 404.
    if not db.get_audit(audit_id, p.scope):
        raise HTTPException(404, "audit not found")
    blobs = delete_artifacts(audit_id)
    db.delete_audit(audit_id, p.scope)
    return {"deleted": audit_id, "artifacts_removed": blobs}


@app.post("/audits/{audit_id}/delete")
def delete_audit_form(audit_id: str, x_api_key: str | None = Header(None)):
    """
    Form-post delete, because an HTML form cannot issue DELETE.

    Redirects back to the dashboard so the row is simply gone — no JSON blob in
    the face of someone who clicked a button.
    """
    p = principal(x_api_key)
    if db.get_audit(audit_id, p.scope):        # scope check before deletion
        delete_artifacts(audit_id)
        db.delete_audit(audit_id, p.scope)
    return RedirectResponse("/", status_code=303)


@app.post("/clients/{client_key}/prune")
def prune_client(client_key: str, x_api_key: str | None = Header(None)):
    """
    Keep the newest audit for a client, delete the rest.

    This exists because testing a crawler against one site produces six rows of
    the same client in an afternoon, and deleting them one at a time is the
    kind of chore that ends with nobody tidying up at all.
    """
    p = principal(x_api_key)
    rows = [a for a in db.list_audits(p.scope, limit=500)
            if db.client_key(a.get("client_name")) == client_key]
    rows.sort(key=lambda r: r.get("created_at") or 0, reverse=True)
    for a in rows[1:]:
        delete_artifacts(a["id"])
        db.delete_audit(a["id"], p.scope)
    return RedirectResponse("/", status_code=303)


# ROUTE ORDER IS LOAD-BEARING. Starlette matches routes in registration order
# and a path parameter matches any character except "/", so the generic
# /audits/{audit_id} route below happily swallows "/audits/abc123.pdf" with
# audit_id="abc123.pdf" — which then 404s as "audit not found". That is exactly
# what shipped: the PDF link on every report page returned a JSON error.
# The specific route must be registered first. Guarded by tests/test_routes.py.
# REGISTERED BEFORE THE .pdf ROUTE, for the same reason that one is
# registered before /audits/{id}: FastAPI matches in declaration order, and
# "{audit_id}.pdf" would happily swallow "abc123.snapshot.pdf".
@app.get("/audits/{audit_id}.snapshot.pdf")
def audit_snapshot(audit_id: str, x_api_key: str | None = Header(None)):
    """
    The short version - three pages, for the person who will not read the
    full audit.

    Built from the SAME findings and the SAME summary as the full report, by
    the same functions. See engine.pdf_report.build_snapshot: a snapshot with
    its own private copy of the score would disagree with the full audit in
    front of a client within two builds.
    """
    p = principal(x_api_key)
    a = db.get_audit(audit_id, p.scope)
    if not a:
        raise HTTPException(404, "audit not found")
    if a["status"] not in ("ready",):
        raise HTTPException(409, f"audit is {a['status']}, not ready")
    findings, scores, cat = (db.get_findings(audit_id), db.get_scores(audit_id),
                             db.catalog())
    meta = _report_meta(a)
    summary = build_summary(findings, scores, cat, meta)
    pdf = build_snapshot(meta, scores, findings, cat, summary,
                         logo_path=os.getenv("REPORT_LOGO_PATH") or None)
    import re as _re
    import time as _t
    safe = _re.sub(r'[\\/:*?"<>|]+', "-", (a["client_name"] or "Audit")).strip()
    when = _t.strftime("%m%d%Y", _t.localtime(a.get("completed_at")
                                              or a.get("created_at")
                                              or _t.time()))
    fname = f"{safe}_Snapshot_{when}.pdf"
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition":
            f'inline; filename="{fname}"; '
            f"filename*=UTF-8''{_urlquote(fname)}"})


@app.get("/audits/{audit_id}.pdf")
def audit_pdf(audit_id: str, polish: bool = False,
              x_api_key: str | None = Header(None)):
    """The client-facing deliverable."""
    p = principal(x_api_key)
    a = db.get_audit(audit_id, p.scope)
    if not a:
        raise HTTPException(404, "audit not found")
    if a["status"] not in ("ready",):
        raise HTTPException(409, f"audit is {a['status']}, not ready")
    findings, scores, cat = (db.get_findings(audit_id), db.get_scores(audit_id),
                             db.catalog())
    meta = _report_meta(a)
    summary = build_summary(findings, scores, cat, meta)
    if polish:
        summary = polish_with_llm(summary, meta)
    pdf = build_pdf(meta, scores, findings, cat, summary,
                    logo_path=os.getenv("REPORT_LOGO_PATH") or None)
    # "The Ooten Law Firm_Website Audit_08232026.pdf" — the client's real name,
    # spaces intact, and the date it was produced. The old slug
    # ("the-ooten-law-firm-seo-geo-audit.pdf") looked like a URL in a folder of
    # documents people file by client and date.
    import re as _re
    import time as _t
    safe = _re.sub(r'[\\/:*?"<>|]+', "-", (a["client_name"] or "Audit")).strip()
    when = _t.strftime("%m%d%Y", _t.localtime(a.get("completed_at")
                                              or a.get("created_at")
                                              or _t.time()))
    fname = f"{safe}_Website Audit_{when}.pdf"
    return Response(pdf, media_type="application/pdf", headers={
        # RFC 5987, because the name now contains spaces and may contain
        # anything else a client is called. The plain `filename=` stays as the
        # fallback for readers that ignore filename*.
        "Content-Disposition":
            f'inline; filename="{fname}"; '
            f"filename*=UTF-8''{_urlquote(fname)}"})


@app.get("/audits/{audit_id}/consent", response_class=HTMLResponse)
def consent_page(audit_id: str, x_api_key: str | None = Header(None)):
    """
    The consent scan in full, rather than the nine checkpoints derived from it.

    Reads the artifact the worker stored. An audit from before that existed
    renders the page explaining exactly that, rather than a 404 — the link is
    on every consent audit and a dead link is a bug report waiting to happen.
    """
    p = principal(x_api_key)
    a = db.get_audit(audit_id, p.scope)
    if not a:
        raise HTTPException(404, "audit not found")
    detail = None
    blob = get_artifact(audit_id, "consent_scan.json")
    if blob:
        try:
            detail = json.loads(blob.decode())
        except Exception:  # noqa: BLE001
            detail = None
    from .ui_consent import consent_html
    return consent_html(a, detail)


@app.get("/api/audits/{audit_id}/consent")
def consent_detail(audit_id: str, x_api_key: str | None = Header(None)):
    """The same record as JSON, for anything that wants to read it directly."""
    p = principal(x_api_key)
    if not db.get_audit(audit_id, p.scope):
        raise HTTPException(404, "audit not found")
    blob = get_artifact(audit_id, "consent_scan.json")
    if not blob:
        raise HTTPException(404, "no consent detail stored for this audit")
    return Response(blob, media_type="application/json")


@app.get("/audits/{audit_id}", response_class=HTMLResponse)
def audit_page(audit_id: str, x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    a = db.get_audit(audit_id, p.scope)
    if not a:
        raise HTTPException(404, "audit not found")
    if a["status"] != "ready":
        return audit_html(a)                       # live status page, auto-refreshes
    findings = db.get_findings(audit_id)
    scores = db.get_scores(audit_id)
    meta = _report_meta(a)
    cat = db.catalog()
    meta["pdf_url"] = f"/audits/{audit_id}.pdf"
    meta["snapshot_url"] = f"/audits/{audit_id}.snapshot.pdf"
    # Only offered when this container can actually do it - see can_polish.
    meta["can_polish"] = can_polish()
    # Only when there is something to show. A link to an empty page is worse
    # than no link: it reads as a broken feature rather than a phase nobody
    # ticked.
    if (meta.get("extras") or {}).get("consent"):
        meta["consent_url"] = f"/audits/{audit_id}/consent"
    html = render_html(meta, scores, findings, cat,
                       summary=build_summary(findings, scores, cat, meta))
    # THE GREEN DOT, ON THE PAGE THAT MEANS IT IS DONE.
    #
    # The running page pulses amber in the tab; this is the other half. Only
    # for a run that finished in the last ten minutes - somebody who left the
    # tab open and came back. On a report from last week a green dot would be
    # decoration, and a tab full of them says nothing.
    done_at = a.get("completed_at") or 0
    if done_at and time.time() - float(done_at) < 600:
        from .ui import _tab
        html = html.replace("</body>", _tab("done") + "</body>")
    return html


def _extras(a: dict) -> dict:
    """
    Report material that is not a checkpoint finding.

    Business context is recomputed HERE, from the stored crawl artifact, when
    the audit predates it — so improving the report does not mean re-crawling
    every client. The rule this follows: anything derivable from the artifact is
    derived at render time; only what needs the network is frozen at crawl time.
    """
    extras = {}
    try:
        extras = json.loads(a.get("extras") or "{}") or {}
    except Exception:
        extras = {}

    # WHICH OPTIONAL PHASES WERE ASKED FOR — DERIVED, NOT ONLY RECORDED.
    #
    # The worker started stamping `phases_run` in build ‑32, which lets the
    # panel separate "we asked for this and got nothing" (a bug) from "nobody
    # ticked the box" (a choice). Audits that ran before ‑32 carry no stamp, so
    # they fell to the conservative branch and printed fifteen unticked
    # checkpoints as fifteen defects — the exact panel ‑32 set out to fix,
    # still there on every existing report.
    #
    # It never needed a stamp. The audit row has always stored the options it
    # was submitted with, and `run_consent` / `run_aivis` live in there. Read
    # them and the fix applies to every audit ever run, retroactively, with no
    # re-run. A key missing from options means the phase was not requested —
    # true both for a run where the box was unticked and for one that predates
    # the box existing at all.
    #
    # The worker's stamp still wins where present: it records what the run
    # actually did, and options record what was asked of it. Those agree today
    # and the stamp is the one to trust if they ever diverge.
    if "phases_run" not in extras:
        try:
            _opt = json.loads(a.get("options") or "{}")
            _opt = _opt if isinstance(_opt, dict) else {}
        except Exception:  # noqa: BLE001
            _opt = {}
        extras["phases_run"] = {"run_consent": bool(_opt.get("run_consent")),
                                "run_aivis": bool(_opt.get("run_aivis"))}

    # AI visibility, if a monitor run is linked to this audit. Read at render
    # time rather than frozen into the audit, so a monitor run that happens
    # AFTER the audit still shows up in the PDF.
    try:
        run = db.latest_ai_run_for_audit(a["id"])
        # CARRIED FROM AN EARLIER RUN OF THE SAME SITE.
        #
        # Looking this up by audit id alone means every re-run loses the AI
        # section: the monitor run stays attached to the audit that started
        # it, the new audit has none, and a whole section disappears from a
        # report for a client who had already paid for those questions. Same
        # rule as the reputation profile - same URL, newest first, and dated
        # on the page so nobody reads last week's answers as this morning's.
        carried_ai = False
        if not run:
            run = db.latest_ai_run_for_site(a.get("target_url"),
                                            exclude_audit=a["id"])
            carried_ai = bool(run)
        # DO NOT CLOBBER A NEWER CARRIED PANEL.
        #
        # Two roads lead here now: a standalone monitor run in `ai_runs`, and
        # a panel the worker carried into `extras` from the previous audit of
        # this site (the audit's own AI phase writes no ai_runs row, so that
        # is the ONLY copy of an audit-phase panel). Whichever is newer wins;
        # overwriting a fresh carried panel with an older monitor run would
        # re-introduce the bug this whole path exists to fix.
        _have = (extras.get("ai_visibility") or {})
        _have_at = _have.get("carried_at") or 0
        _run_at = (run or {}).get("completed_at") or (run or {}).get("created_at") or 0
        if run and _have.get("citation_rate") is not None and carried_ai:
            try:
                if float(_have_at or 0) >= float(_run_at or 0):
                    run = None
            except (TypeError, ValueError):
                pass
        if run:
            extras["ai_visibility"] = {
                "citation_rate": run.get("citation_rate"),
                "mention_rate": run.get("mention_rate"),
                "unprompted_citation_rate": run.get("unprompted_citation_rate"),
                "client_citations": run.get("client_citations"),
                "top_competitor_domain": run.get("top_competitor_domain"),
                "citation_gap": run.get("citation_gap"),
                "platforms": json.loads(run.get("platforms") or "[]"),
                "skipped": json.loads(run.get("skipped") or "[]"),
                "headline": run.get("headline"),
                "share_of_voice": db.get_ai_sov(run["id"])[:6],
                "carried_from_run": run["id"] if carried_ai else None,
                "carried_at": (run.get("completed_at") or run.get("created_at"))
                              if carried_ai else None,
            }
    except Exception as e:
        print(f"[api] ai visibility skipped for {a.get('id')}: "
              f"{type(e).__name__}: {e}", flush=True)

    # Evidence screenshots are stored as blobs; the renderer needs the bytes.
    shots = []
    for sh in (extras.get("screenshots") or []):
        try:
            blob = get_artifact(a["id"], sh["name"])
            if blob:
                shots.append({**sh, "png": blob})
        except Exception:
            continue
    if shots:
        extras["screenshot_blobs"] = shots

    # The reputation SERP shot, same arrangement: the name is on the audit,
    # the bytes are in the blob store, and they are married at render time so
    # a reload picks up the picture without re-running the scan.
    _rs = ((extras.get("reputation") or {}).get("shot") or {})
    if _rs.get("name") and not _rs.get("png"):
        try:
            blob = get_artifact(a["id"], _rs["name"])
            if blob:
                _rs["png"] = blob
        except Exception as exc:  # noqa: BLE001
            print(f"[api] reputation shot missing for {a.get('id')}: "
                  f"{type(exc).__name__}: {exc}", flush=True)

    if extras.get("context"):
        return extras
    try:
        blob = get_artifact(a["id"], "crawl_artifact.json")
        if blob:
            from engine.crawler import artifact_from_json
            from engine.context import extract as extract_context
            art = artifact_from_json(blob.decode())
            bc = extract_context(art)
            extras["context"] = {**bc.to_dict(), "describe": bc.describe()}
    except Exception as e:
        print(f"[api] context rebuild skipped for {a.get('id')}: "
              f"{type(e).__name__}: {e}", flush=True)
    return extras


def _report_meta(a: dict) -> dict:
    try:
        _o = json.loads(a.get("options") or "{}")
        _o = _o if isinstance(_o, dict) else {}
    except Exception:
        _o = {}
    return {"url": a["target_url"], "client": a["client_name"],
            "vertical": a.get("vertical"),
            "business_model": a.get("business_model"),
            "primary_markets": _o.get("primary_markets"),
            "primary_conversion": _o.get("primary_conversion"),
            "pages_crawled": a["pages_crawled"] or 0,
            "coverage": a["coverage"] or "",
            "generated": time.strftime("%Y-%m-%d %H:%M",
                                       time.localtime(a["completed_at"] or time.time())),
            "duration_s": round((a["completed_at"] or 0) - (a["started_at"] or 0), 1),
            "crawl_blocked": bool(a.get("crawl_blocked")),
            "crawl_note": a.get("crawl_note"),
            "truncated": a.get("crawl_truncated"),
            "capture_method": a.get("capture_method"),
            "extras": _extras(a),
            # The report page carries a Search Console capture button, and the
            # extension needs both of these off the page rather than out of a
            # person's clipboard. Copying an audit id between two tabs is
            # exactly the step that gets done wrong at 5pm.
            "audit_id": a.get("id"),
            "gsc_property": _o.get("gsc_property") or "",
            # A per-audit partner name overrides the firm from the
            # environment. White-labelled work goes out under the partner's
            # name, and that varies per client — an env var is the wrong place
            # for something that changes between two audits run in the same
            # hour. Blank falls back to the configured firm, so nothing changes
            # for audits nobody fills it in for.
            "analyst": {"name": cfg.analyst_name, "title": cfg.analyst_title,
                        "email": cfg.analyst_email,
                        "firm": (_o.get("partner") or "").strip() or cfg.firm_name},
            "partner": (_o.get("partner") or "").strip(),
            "build": version.label()}


@app.get("/api/audits/{audit_id}/summary")
def audit_summary(audit_id: str, polish: bool = False,
                  x_api_key: str | None = Header(None)):
    """Executive summary + roadmap. Deterministic by default; ?polish=1 rewrites
    the same facts as client-ready prose when an LLM key is configured."""
    p = principal(x_api_key)
    a = db.get_audit(audit_id, p.scope)
    if not a:
        raise HTTPException(404, "audit not found")
    findings, scores, cat = (db.get_findings(audit_id), db.get_scores(audit_id),
                             db.catalog())
    s = build_summary(findings, scores, cat, _report_meta(a))
    if polish:
        s = polish_with_llm(s, _report_meta(a))
    return s


# ==================================================================== BROWSER CAPTURE
@app.post("/api/audits/{audit_id}/console-capture")
def ingest_console_capture(audit_id: str, payload: dict,
                           x_api_key: str | None = Header(None)):
    """
    Accept Search Console's UI-only numbers, read from a signed-in browser.

    Eight checkpoints are published by Google in the interface and exposed
    through no API. The report has been honest about that for several builds —
    "Google publishes no API for this" — but honest and unmeasured is still
    unmeasured, and someone was retyping numbers off a screen into nothing.

    The extension already runs in the operator's own signed-in Chrome, which is
    exactly what those reports require. It reads the visible labels, shows what
    it found for confirmation, and posts it here.

    NOTHING IS INFERRED. A field the capture did not carry is not written, so a
    scrape that half-worked leaves the other half unmeasured rather than
    filling it with zeros — a zero in the exclusion reports reads as "no pages
    excluded", which is a materially wrong statement about a site.
    """
    p = principal(x_api_key)
    a = db.get_audit(audit_id, p.scope)
    if not a:
        raise HTTPException(404, "audit not found")

    from engine.console_capture import findings_from_capture
    rows = findings_from_capture(payload or {})
    if not rows:
        raise HTTPException(
            400, "capture carried no numbers we recognised — Google may have "
                 "renamed a label, or the report had not finished loading")

    # Merge over what is already stored rather than replacing it: this is a
    # supplement to an audit that has already run, not a re-run.
    findings = db.get_findings(audit_id)
    findings.update(rows)
    db.save_findings(audit_id, findings)

    cat = db.catalog()
    scores = engine_scoring.score(findings, cat, a.get("vertical"))
    db.save_scores(audit_id, scores)
    print(f"[api] {audit_id} console capture filled {len(rows)} rows: "
          f"{', '.join(sorted(rows))}", flush=True)
    return {"audit_id": audit_id, "filled": sorted(rows),
            "count": len(rows),
            "overall": (scores.get("overall") or {}).get("score")}


@app.post("/api/audits/{audit_id}/psi-capture")
def ingest_psi_capture(audit_id: str, payload: dict,
                       x_api_key: str | None = Header(None)):
    """
    Accept a Lighthouse report fetched in the operator's browser.

    THE THIRD ROUTE TO THE SAME ENDPOINT.

    PageSpeed Insights is refused from Render often enough to take out the
    whole Performance section in one go — nine checkpoints, nine identical
    "the speed-testing service did not respond" rows in the internal panel,
    and nothing about the client's site involved in any of it. The DataForSEO
    Lighthouse fallback has its own bad days, and when both miss there was no
    third option but to re-run the audit and hope.

    The operator's own Chrome is a third route to the same public Google
    endpoint, from a residential IP Google is not rate-limiting. It costs
    nothing and it needs no credential.

    THE EXTENSION GRADES NOTHING. It posts the raw PSI response; the same nine
    checkers read it here. A browser that decided what a good LCP was would
    eventually disagree with the server about the same site, with no way to
    tell which was right.
    """
    p = principal(x_api_key)
    a = db.get_audit(audit_id, p.scope)
    if not a:
        raise HTTPException(404, "audit not found")
    report = payload.get("psi") or payload.get("report") or payload
    if not (report or {}).get("lighthouseResult"):
        raise HTTPException(400, "payload carried no lighthouseResult — the "
                                 "PageSpeed call did not return a report")

    from engine.checks.perf import findings_from_psi
    rows = findings_from_psi(payload.get("url") or a["target_url"], report)
    if not rows:
        raise HTTPException(400, "the report was readable but answered none "
                                 "of the nine checkpoints")
    for f in rows.values():
        # WHERE THE NUMBER CAME FROM, ON THE ROW ITSELF.
        #
        # A report where six areas were measured on the server and one was
        # measured on somebody's laptop should say so somewhere. This is the
        # somewhere: the value block the internal panel and the findings table
        # both already read.
        f.setdefault("value", {})
        if isinstance(f["value"], dict):
            f["value"]["measured_in"] = "operator browser"
    db.save_findings(audit_id, rows)

    findings = db.get_findings(audit_id)
    cat = db.catalog()
    sc = engine_scoring.score(findings, cat, a.get("vertical"))
    db.save_scores(audit_id, sc)

    answered = sum(1 for f in rows.values() if f.get("status") != "Need Access")
    print(f"[api] {audit_id} PageSpeed capture ingested — {answered}/{len(rows)} "
          f"rows answered from the browser", flush=True)
    return {"ok": True, "answered": answered, "total": len(rows),
            "filled": sorted(rows), "report": f"/audits/{audit_id}",
            "overall": (sc.get("overall") or {}).get("score")}


@app.post("/api/audits/{audit_id}/consent-capture")
def ingest_consent_capture(audit_id: str, payload: dict,
                           x_api_key: str | None = Header(None)):
    """
    Accept a consent capture from the extension and score it.

    The escape hatch for the scanner's dead end. Bot protection means Playwright
    falls back to raw HTML, which cannot see the banner, Consent Mode,
    pre-consent fires or the reject test — three and a half of the four
    questions the scan exists to answer. The extension runs in the operator's
    own Chrome, which challenge pages let through because it is a person.

    THE EXTENSION CLASSIFIES NOTHING. It sends what happened; the same
    signature tables, `gcs=` parsing and endpoint lists that the Playwright
    path uses run here. Two classifiers would eventually disagree about the
    same site with no way to tell which was right.
    """
    p = principal(x_api_key)
    a = db.get_audit(audit_id, p.scope)
    if not a:
        raise HTTPException(404, "audit not found")
    if not payload.get("html") and not payload.get("pre_requests"):
        raise HTTPException(400, "capture contained neither HTML nor requests")

    from engine.consent.from_capture import result_from_capture
    from engine.consent.checks import findings_from_scan

    # WHAT WAS ASKED OF THE SCAN, NOT JUST WHAT CAME BACK.
    #
    # The states and the bought products are on the audit, not in the capture -
    # the extension has no business knowing which statutes a client sells
    # under. Passing them in is what lets the per-state rows and the
    # "product bought, pixel never fires" table exist on this path at all;
    # without them the browser did all the work and the page showed half of it.
    try:
        _opt = json.loads(a.get("options") or "{}") or {}
    except Exception:  # noqa: BLE001
        _opt = {}
    requested = {"states": _opt.get("consent_states") or [],
                 "industries": _opt.get("consent_industries") or [],
                 "products": _opt.get("consent_products") or [],
                 "conversion_urls": _opt.get("conversion_urls") or [],
                 "implementation": _opt.get("implementation") or ""}

    # ONE CAPTURE MAY COVER SEVERAL PAGES, and it must, because conversion
    # pixels fire on thank-you pages. The homepage decides the verdict; the
    # other pages contribute their pixels, exactly as the server path does.
    _caps = [c for c in (payload.get("pages") or []) if isinstance(c, dict)]
    if not _caps:
        _caps = [payload]
    _pages, _scans = [], []
    for _i, _cap in enumerate(_caps):
        _role = _cap.get("role") or ("homepage" if _i == 0 else "conversion")
        _u = _cap.get("url") or a["target_url"]
        if _cap.get("error"):
            # A page that failed is part of the record. Dropping it means the
            # dashboard lists two pages for a run asked to cover three, and
            # says nothing about the third.
            _pages.append({"url": _u, "role": _role, "error": _cap["error"]})
            continue
        _one = result_from_capture(
            {**_cap, "url": _u},
            states=requested["states"] if _i == 0 else [],
            products=requested["products"],
            industries=requested["industries"] if _i == 0 else [])
        _scans.append(_one)
        _pages.append({"url": _u, "role": _role, "scan": _one})

    if not _scans:
        raise HTTPException(400, "every page in the capture failed")
    scan = _scans[0]
    for _other in _scans[1:]:
        # A pixel firing pre-consent on ANY scanned page is a pre-consent
        # fire, and the nine checkpoints should say so once.
        for _key in ("pre_consent", "post_reject", "gpc_fires",
                     "post_consent"):
            if _other.get(_key):
                scan[_key] = (scan.get(_key) or []) + _other[_key]
        for _p in _other.get("products") or []:
            _mine = next((x for x in scan.get("products") or []
                          if x.get("product") == _p.get("product")), None)
            if not _mine:
                scan.setdefault("products", []).append(_p)
                continue
            # A pixel seen firing on the thank-you page is a pixel that
            # fires. Merge per-pixel rather than per-product, or the
            # homepage's "never fired" overwrites the page that saw it.
            for _px in _p.get("pixels") or []:
                _t = next((x for x in _mine.get("pixels") or []
                           if x.get("name") == _px.get("name")), None)
                if not _t:
                    _mine.setdefault("pixels", []).append(_px)
                    continue
                for _f in ("fired_pre", "fired_post"):
                    _t[_f] = bool(_t.get(_f)) or bool(_px.get(_f))
                if _px.get("sample_url") and not _t.get("sample_url"):
                    _t["sample_url"] = _px["sample_url"]
                if _t.get("fired_pre") or _t.get("fired_post"):
                    _t["configured"] = None
            _mine["fired"] = sum(1 for x in _mine.get("pixels") or []
                                 if x.get("fired_pre") or x.get("fired_post"))
    scan["pages_scanned"] = len(_scans)
    if len(_scans) > 1:
        from engine.consent.scanner import _apply_verdict
        _apply_verdict(scan)          # re-read the verdict off the merge
    rows = findings_from_scan(scan)
    db.save_findings(audit_id, rows)

    # THE SCAN IS THE PRODUCT; NINE CHECKPOINTS ARE A SUMMARY OF IT.
    #
    # The worker learned this and wrote consent_scan.json. This endpoint did
    # not, so an operator who went to the trouble of running the capture -
    # precisely because the server crawl could not - got the nine findings and
    # a consent page that said "no consent detail was stored for this run".
    # The capture is the only source of that detail on a blocked site, so it
    # is the one that most needed storing.
    #
    # A capture merges over whatever the server scan managed: the pages list
    # from a partial server run is still true, and the extension only scans
    # the one URL.
    prior = {}
    try:
        _blob = get_artifact(audit_id, "consent_scan.json")
        if _blob:
            prior = json.loads(_blob.decode()) or {}
    except Exception:  # noqa: BLE001
        prior = {}
    detail_ok = True
    try:
        # THE PAGES COME FROM THIS RUN, NEVER THE LAST ONE.
        #
        # This kept the previous scan's page list, so the page rendered one
        # run's tiles and products above another run's per-page tracker table
        # — two dates on one screen, contradicting each other, with a header
        # that claimed both were "captured in the operator's browser". If a
        # capture covered one page, the record says one page.
        put_artifact(audit_id, "consent_scan.json", json.dumps(
            {"scan": scan,
             "pages": _pages,
             "requested": {**(prior.get("requested") or {}), **requested},
             "server_scan": (prior.get("scan") or None)},
            default=str).encode())
    except Exception as exc:  # noqa: BLE001
        detail_ok = False
        print(f"[api] {audit_id} consent detail not stored: "
              f"{type(exc).__name__}: {exc}", flush=True)

    # And the summary the audit page reads. Leaving this saying "basic" after a
    # full browser capture is the same staleness bug as leaving the score
    # alone: the page would carry the browser's answers under a banner saying
    # no browser ran.
    try:
        _ex = json.loads(a.get("extras") or "{}") or {}
    except Exception:  # noqa: BLE001
        _ex = {}
    _ex["consent"] = {
        "mode": scan.get("mode"),
        "source": "extension",
        "cmps": [c.get("name") for c in (scan.get("cmps") or [])],
        "verdict": scan.get("verdict"),
        "verdict_detail": scan.get("verdict_detail"),
        "scanned_at": scan.get("scanned_at"),
        "pages_scanned": len(_scans),
        "has_detail": detail_ok,
    }
    db.update_audit(audit_id, extras=json.dumps(_ex, default=str))

    # Rescore, because nine new rows change the coverage and the Consent
    # section's score. An ingest that leaves the stored score describing the
    # run before it is the same silent-staleness bug as reusing a crawl.
    findings = db.get_findings(audit_id)
    cat = db.catalog()
    sc = engine_scoring.score(findings, cat, a.get("vertical"))
    db.save_scores(audit_id, sc)

    answered = sum(1 for f in rows.values() if f.get("status") != "Need Access")
    print(f"[api] {audit_id} consent capture ingested — {answered}/{len(rows)} "
          f"rows answered from the browser", flush=True)
    return {"ok": True, "answered": answered, "total": len(rows),
            "cmps": [c.get("name") for c in (scan.get("cmps") or [])],
            "detail_stored": detail_ok,
            "consent": f"/audits/{audit_id}/consent",
            "report": f"/audits/{audit_id}"}


@app.post("/api/audits/{audit_id}/capture")
def ingest_capture(audit_id: str, payload: dict, x_api_key: str | None = Header(None)):
    """
    Accept a browser capture and run the IDENTICAL checkers over it.

    This is the escape hatch for WAF-protected sites. The extension supplies the
    rendered DOM (which a server fetch cannot get past bot protection, and which
    is more accurate anyway on JS-rendered sites); the server still contributes
    TLS and PageSpeed Insights.
    """
    p = principal(x_api_key)
    a = db.get_audit(audit_id, p.scope)
    if not a:
        raise HTTPException(404, "audit not found")
    if not payload.get("pages"):
        raise HTTPException(400, "payload contained no pages")

    db.update_audit(audit_id, status="checking",
                    progress=f"ingesting {len(payload['pages'])} browser-captured pages")
    art = artifact_from_capture(payload)

    ctx = {"psi_key": cfg.psi_key, "skip_psi": cfg.skip_psi}
    findings = engine_checks.run_all(art, ctx)
    # Same downstream collectors as the server path — one audit, one coverage.
    from engine.judgment import run_judgment
    from engine.collectors import collect_gsc, collect_ga4, collect_backlinks
    opts = json.loads(a.get("options") or "{}")
    if not opts.get("skip_judgment"):
        findings.update(run_judgment(art, business_model=a.get("vertical"),
                                     client=a.get("client_name")))
    findings.update(collect_gsc(a["target_url"], opts.get("gsc_refresh_token")))
    findings.update(collect_ga4(opts.get("ga4_property_id"),
                                opts.get("ga4_refresh_token")))
    findings.update(collect_backlinks(art.host))
    db.save_findings(audit_id, findings)

    cat = db.catalog()
    sc = engine_scoring.score(findings, cat, a.get("vertical"))
    db.save_scores(audit_id, sc)

    from .artifacts import put_artifact
    put_artifact(audit_id, "crawl_artifact.json", art.to_json().encode())

    db.update_audit(
        audit_id, status="ready",
        progress=f"complete — captured in-browser ({len(art.pages)} pages)",
        crawl_blocked=1 if art.quality.degenerate else 0,
        crawl_note=(f"{art.quality.likely_cause} · " + "; ".join(art.quality.signals)
                    if art.quality.degenerate else None),
        crawl_truncated=None,
        overall_score=sc["overall"]["score"], overall_rating=sc["overall"]["rating"],
        pages_crawled=len(art.pages), coverage=f"{len(findings)}/{len(cat)}",
        capture_method="browser_extension", completed_at=time.time())

    return {"ok": True, "audit_id": audit_id, "pages": len(art.pages),
            "checkpoints": len(findings),
            "overall_score": sc["overall"]["score"],
            "report": f"/audits/{audit_id}"}


# ==================================================================== AI VISIBILITY
class MonitorProfile(BaseModel):
    client_name: str
    brand: str
    domain: str
    category: str
    products: list[str] = []
    locations: list[str] = []
    competitors: list[str] = []
    services: list[str] = []
    aliases: list[str] = []


class MonitorRun(BaseModel):
    repeats: int = 3
    audit_id: str | None = None


def _profile_payload(m: MonitorProfile) -> dict:
    d = m.model_dump()
    d.pop("client_name", None)
    return d


@app.post("/api/monitors", status_code=201)
def create_monitor(m: MonitorProfile, x_api_key: str | None = Header(None)):
    """
    Create a monitored profile. The query panel is generated ONCE here and
    frozen — runs replay the same questions so the time series stays comparable.
    """
    from engine.aivis import ClientProfile, build_panel
    p = principal(x_api_key)
    pd = _profile_payload(m)
    panel = [q.to_dict() for q in build_panel(ClientProfile(**pd))]
    pid = db.create_ai_profile(tenancy.owner_for_new_audit(p), m.client_name, pd, panel)
    return {"profile_id": pid, "panel_size": len(panel),
            "unprompted": sum(1 for q in panel if not q["prompted"]),
            "dashboard": f"/visibility/{pid}"}


@app.get("/api/monitors")
def list_monitors(x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    return {"profiles": db.list_ai_profiles(p.scope)}


@app.post("/api/monitors/{profile_id}/runs", status_code=202)
def start_monitor_run(profile_id: str, body: MonitorRun | None = None,
                      x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    prof = db.get_ai_profile(profile_id, p.scope)
    if not prof:
        raise HTTPException(404, "profile not found")
    body = body or MonitorRun()
    rid = db.create_ai_run(prof["partner_id"], profile_id, body.repeats,
                           body.audit_id, prof["panel_version"])
    Q.enqueue(rid, job_type="ai_monitor")
    return {"run_id": rid, "status": "queued", "poll": f"/api/monitors/runs/{rid}"}


@app.get("/api/monitors/runs/{run_id}")
def get_monitor_run(run_id: str, x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    r = db.get_ai_run(run_id, p.scope)
    if not r:
        raise HTTPException(404, "run not found")
    out = dict(r)
    if r["status"] == "ready":
        out["by_platform"] = db.get_ai_platform_stats(run_id)
        out["share_of_voice"] = db.get_ai_sov(run_id)
    return out


@app.get("/api/monitors/{profile_id}/history")
def monitor_history(profile_id: str, x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    if not db.get_ai_profile(profile_id, p.scope):
        raise HTTPException(404, "profile not found")
    runs = db.list_ai_runs(profile_id=profile_id)
    return {"history": [{"run_id": r["id"], "at": r["created_at"],
                         "citation_rate": r["citation_rate"],
                         "mention_rate": r["mention_rate"],
                         "citation_gap": r["citation_gap"]} for r in runs]}


# ---------------------------------------------------------------- UI
@app.get("/visibility", response_class=HTMLResponse)
def visibility_index(x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    profs = db.list_ai_profiles(p.scope)
    runs = {pr["id"]: db.list_ai_runs(profile_id=pr["id"]) for pr in profs}
    return visibility_index_html(profs, runs, Q.depth())


@app.post("/visibility")
def visibility_create(client_name: str = Form(...), brand: str = Form(...),
                      domain: str = Form(...), category: str = Form(...),
                      x_api_key: str | None = Header(None)):
    from engine.aivis import ClientProfile, build_panel
    p = principal(x_api_key)
    pd = {"brand": brand, "domain": domain, "category": category,
          "products": [], "locations": [], "competitors": [], "services": [],
          "aliases": []}
    panel = [q.to_dict() for q in build_panel(ClientProfile(**pd))]
    pid = db.create_ai_profile(tenancy.owner_for_new_audit(p), client_name, pd, panel)
    return RedirectResponse(f"/visibility/{pid}", status_code=303)


@app.post("/visibility/{profile_id}/run")
def visibility_run(profile_id: str, x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    prof = db.get_ai_profile(profile_id, p.scope)
    if not prof:
        raise HTTPException(404, "profile not found")
    rid = db.create_ai_run(prof["partner_id"], profile_id, 3, None,
                           prof["panel_version"])
    Q.enqueue(rid, job_type="ai_monitor")
    return RedirectResponse(f"/visibility/{profile_id}", status_code=303)


@app.get("/visibility/{profile_id}", response_class=HTMLResponse)
def visibility_page(profile_id: str, x_api_key: str | None = Header(None)):
    p = principal(x_api_key)
    prof = db.get_ai_profile(profile_id, p.scope)
    if not prof:
        raise HTTPException(404, "profile not found")
    runs = db.list_ai_runs(profile_id=profile_id)
    ready = [r for r in runs if r["status"] == "ready"]
    if not ready:
        status = runs[0]["status"] if runs else "never run"
        return visibility_index_html([prof], {prof["id"]: runs}, Q.depth())
    latest = ready[0]
    return visibility_html(prof, latest,
                           db.get_ai_platform_stats(latest["id"]),
                           db.get_ai_sov(latest["id"]),
                           list(reversed(ready)))
