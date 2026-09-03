"""
Markets, and the states they imply.

The consent scan checks state privacy law, and until now the state list was a
hardcoded guess — `CA CO CT TX VA OR`, prefilled on the form. For a Knoxville
law firm selling in thirteen Tennessee counties that guess tested California's
law and ignored Tennessee's, and nothing in the report said so.

The markets field already knew the answer. These tests hold the two things
that make reading it off safe: a market must never be silently mangled, and a
state we have no checks for must be reported as such rather than dropped.

Run:  python3 -m tests.test_geo
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILED: list[str] = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILED.append(label)


OOTEN = ("Anderson County, TN × Blount County, TN × Knox County, TN × "
         "Loudon County, TN × Roane County, TN × Sevier County, TN × "
         "Campbell County, TN × Jefferson County, TN × Scott County, TN × "
         "Morgan County, TN × Union County, TN × Cocke County, TN × "
         "Meigs County, TN")


def main():
    from engine.geo import (state_of, split_markets, summarize,
                            states_from_markets, STATES)

    print("\nA SEPARATOR MUST NEVER EAT A REAL NAME")
    # The first cut treated a bare "x" as a separator, so "Knox County, TN"
    # became "Kno" and "County, TN" — and the same would have happened to
    # Fairfax, Essex, Lennox and every other name ending in x. A separator
    # that misses is recoverable; one that cuts a market in half leaves
    # something neither readable nor attributable to a state.
    for name in ("Knox County, TN", "Fairfax County, VA", "Essex County, NJ",
                 "Lennox, SD", "Bronx, NY"):
        got = split_markets(name)
        check(f"{name!r} stays one market", got == [name], str(got))
    check("but a spaced x still separates",
          len(split_markets("Knoxville, TN x Nashville, TN")) == 2)
    check("and so does the multiplication sign the data actually uses",
          len(split_markets("Knoxville, TN × Nashville, TN")) == 2)

    print("\nTHE REAL CLIENT'S MARKETS, PARSED WHOLE")
    s = summarize(OOTEN)
    check("all thirteen markets survive", len(s["markets"]) == 13,
          str(len(s["markets"])))
    check("none of them fails to resolve", s["unparsed"] == [],
          str(s["unparsed"]))
    check("and they name exactly one state", s["states"] == ["TN"],
          str(s["states"]))
    check("which we do have checks for", s["checkable"] == ["TN"])
    # The point of the whole exercise.
    check("so the scan tests Tennessee, not the old CA CO CT TX VA OR guess",
          states_from_markets(OOTEN) == ["TN"])

    print("\nEVERY WAY A PERSON WRITES A STATE")
    for text, want in (("Knoxville, TN", "TN"), ("Nashville, Tennessee", "TN"),
                       ("Memphis TN", "TN"), ("TN", "TN"), ("Tennessee", "TN"),
                       ("Washington DC", "DC"), ("Puerto Rico", "PR"),
                       ("Portland, OR", "OR"), ("New York, NY", "NY")):
        check(f"{text!r} -> {want}", state_of(text) == want, str(state_of(text)))
    check("a market with no state is None, not a guess",
          state_of("Boise") is None and state_of("somewhere") is None)
    check("the vocabulary covers 50 states, DC and the territories",
          len(STATES) >= 56, str(len(STATES)))

    print("\nA STATE WITH NO LAW WE CHECK IS SAID OUT LOUD")
    # Thirty states have no comprehensive law in the scanner's map. Dropping
    # them silently would leave a client in Georgia unable to tell "we looked
    # and there is nothing to check" from "we forgot to look".
    s = summarize("Atlanta, GA × Boise, ID × Knoxville, TN")
    check("all three states are recognized", s["states"] == ["GA", "ID", "TN"],
          str(s["states"]))
    check("only the one we can test is sent to the scan",
          s["checkable"] == ["TN"], str(s["checkable"]))
    check("and the other two are reported, not dropped",
          s["unchecked"] == ["GA", "ID"], str(s["unchecked"]))
    none = summarize("Atlanta, GA")
    check("a client wholly in an unchecked state gets an empty check list",
          none["checkable"] == [] and none["unchecked"] == ["GA"])

    print("\nAN UNRESOLVED MARKET IS FLAGGED, NOT DISCARDED")
    s = summarize("Knoxville, TN × Boise × Springfield")
    check("it is still carried as a market",
          len(s["markets"]) == 3, str(len(s["markets"])))
    check("named in `unparsed` so the form can flag it",
          s["unparsed"] == ["Boise", "Springfield"], str(s["unparsed"]))
    check("and it contributes no state rather than a wrong one",
          s["states"] == ["TN"], str(s["states"]))

    print("\nMESSY INPUT STILL PARSES")
    s = summarize("Los Angeles, CA; Miami, FL | Boise, ID\nAtlanta, GA")
    check("semicolons, pipes and newlines all separate",
          s["states"] == ["CA", "FL", "GA", "ID"], str(s["states"]))
    check("duplicates collapse",
          len(summarize("Knoxville, TN × knoxville, tn")["markets"]) == 1)
    check("empty input is empty, not an error", summarize("")["markets"] == [])

    print("\nTHE FORM AND THE SERVER AGREE")
    # The browser validates as you type; the server re-parses on submit. If
    # they disagree, the pills are decoration.
    import app.ui as ui
    from types import SimpleNamespace as N
    html = ui.dashboard_html([], N(name="V", email="e"), 0,
                             caps={"consent": True, "aivis": True})
    check("the state vocabulary is shipped to the browser",
          '"TN"' in html and "Tennessee" in html)
    check("the markets field submits a hidden canonical string",
          "id='primary_markets'" in html and "type='hidden'" in html)
    # Assert on the INPUT, not the page. The old guess is still named in a
    # comment explaining why it went — searching the whole document for it
    # fails on the explanation rather than on the behavior.
    import re as _re
    _m = _re.search(r"id='cstates'[^>]*", html)
    check("the states box ships with no value at all",
          _m is not None and "value=" not in _m.group(0),
          _m.group(0) if _m else "field not found")
    import inspect
    from app import api
    src = inspect.getsource(api.submit_form)
    check("and the server derives states from markets when none are sent",
          "from engine.geo import summarize" in src)

    print("\nA PROPERTY NAMED AFTER THE CLIENT IS STILL A MATCH")
    # An account manager names a property after the client, not the URL, far
    # more often than not — and the matcher took only the domain's first
    # label, so it reported "no property" about estates that held one.
    from engine.collectors.analytics import _name_keys
    _k = _name_keys("https://www.belmontpark.com/", "Belmont Park")
    check("the domain still contributes its slug", "belmontpark" in _k)
    check("and the client name contributes a distinctive word", "belmont" in _k)
    check("but not a word that would match half the estate",
          "park" not in _k and "firm" not in
          _name_keys("https://ootenlawfirm.com/", "The Ooten Law Firm"))
    check("a two-word client name yields its whole squashed form",
          "junkbeegone" in _name_keys("https://junkbeegone.biz/", "Junk Bee Gone"))
    check("and nothing under five characters gets through",
          all(len(x) > 4 for x in _name_keys("https://a.com/", "A B Co")))
    import inspect as _i2
    from app import api as _api2
    check("the form sends the client name with the access check",
          "client_name" in _i2.signature(_api2.access_check).parameters)
    check("and the probe accepts it",
          "client_name" in _i2.signature(
              __import__("engine.collectors.analytics", fromlist=["probe"])
              .probe).parameters)

    print("\nA LIST OF FOUR HUNDRED NEEDS A FILTER")
    _h = ui.dashboard_html([], N(name="V", email="e"), 0,
                           caps={"consent": True, "aivis": True})
    for _w in ("gsc", "ga4", "gtm"):
        check(f"the {_w} picker has a filter box", f"id='{_w}q'" in _h)
    check("which matches anywhere in the row, not just the first letter",
          ".toLowerCase().indexOf(q) >= 0" in _h)
    check("and says how much it hid rather than shrinking silently",
          "match \u201c' + q + '\u201d" in _h)
    check("a selection the filter would hide is kept, not cleared",
          "(selected)" in _h)

    print("\nEVERY CONSENT INPUT REACHES THE SERVER")
    # The rule this file exists to hold: an input the server drops is worse
    # than no input. `states` and `industries` sat on the scanner's signature
    # for five builds with nothing setting them, and two checkpoints answered
    # nothing the whole time while the form looked complete.
    import inspect as _i
    from app import api as _api, worker as _wk
    _sig = set(_i.signature(_api.submit_form).parameters)
    for f in ("consent_states", "consent_industries", "consent_products",
              "conversion_urls", "implementation"):
        check(f"the form accepts {f}", f in _sig)
    _src = _i.getsource(_api.submit_form)
    for k in ("consent_products", "conversion_urls", "implementation"):
        check(f"and stores {k} in the audit options", f'opts["{k}"]' in _src)
    _w = _i.getsource(_wk._consent)
    check("products reach the scanner", "products=opts.get" in _w)
    check("and the conversion pages are scanned too",
          "conversion_urls" in _w and "site_checks=False" in _w)
    check("with site-level checks run once, on the homepage",
          _w.count("site_checks=False") == 1)

    print("\nTHE STATE CONTROL OFFERS EVERY STATE WE CAN CHECK")
    from engine.consent.state_checks import STATE_CHECKS as _SC
    check("all twenty are on the form as toggles",
          all(f"data-st='{c}'" in html for c in _SC), str(len(_SC)))
    check("and it is no longer a text field someone has to guess into",
          "id='cstates'" in html and "type='hidden'" in html)
    from engine.consent.signatures import PRODUCT_PIXELS as _PP
    check("every product the scanner knows is offered",
          all(f'data-pr="{k}"' in html for k in _PP), str(len(_PP)))

    print("\nCONVERSION URLS ARE HARVESTED, NOT SPLIT")
    # Lifted from the standalone scanner, which learned it the hard way:
    # people paste a line out of an email, and splitting on whitespace turns
    # every word into a pill. Verified in a real browser (tests/README notes
    # the playwright run); asserted here on the pieces the server owns.
    _src = _i.getsource(_api.submit_form)
    check("the six-URL cap is gone",
          "[:6]" not in _src.split("conversion_urls")[1][:400])
    check("and the server de-duplicates on a normalized key",
          "seen" in _src and "conversion_urls" in _src)
    _w2 = _i.getsource(_wk._consent)
    check("the worker scans every one of them, not the first six",
          '(opts.get("conversion_urls") or [])' in _w2 and "[:6]" not in _w2)
    check("the browser harvests URLs out of prose",
          "cvExtract" in html and "requires a real TLD" not in html.lower()
          or "cvExtract" in html)
    check("and normalizes before de-duplicating",
          "cvNorm" in html)
    check("the homepage is never added twice",
          "key === site" in html)

    print("\nA PERMANENT API BOUNDARY IS NOT A FIX LIST ITEM")
    # Eight rows sat under "a credential we have not set, or a call we have
    # not written": Index Coverage, Core Web Vitals and the rest Google
    # publishes only in the Search Console UI. There is no credential and no
    # call, and they will be there on every run forever. A permanent entry on
    # a to-do list is how the whole list stops being read.
    from engine.report import _todo_panel as _tp
    from engine.scoring import load_catalog as _lc
    _cat2 = _lc("seed/checkpoints.csv")
    _F2 = {c: {"status": "Pass", "value": {}, "evidence": "ok",
               "affected_pages": [], "severity": "Low", "recommendation": "",
               "confidence": 1.0, "source": "crawl"} for c in _cat2}
    for cid in [c for c in _cat2 if c.startswith("GSC-")][:8]:
        _F2[cid] = {"status": "Need Access", "value": {},
                    "evidence": "Not available through the Search Console API.",
                    "affected_pages": [], "severity": "Low",
                    "recommendation": "Read it from the UI.",
                    "confidence": 0.0, "source": "gsc_ui_only"}
    _F2["OFF-19"] = {"status": "Need Access", "value": {},
                     "evidence": "DataForSEO returned no rows",
                     "affected_pages": [], "severity": "Low",
                     "recommendation": "", "confidence": 0.0, "source": "dfs"}
    _h2 = "".join(_tp(_F2, _cat2,
                      {"extras": {"phases_run": {"run_consent": True,
                                                 "run_aivis": True}}}))
    check("they get their own heading",
          "Google publishes no API for this" in _h2)
    check("and leave only the real miss on the fix list",
          "Ours to fix &middot; 1" in _h2, "fix count")
    check("phrased as a limit rather than a task",
          "not a gap in the run" in _h2)

    print("\nTHE FORM ASKS THE REAL QUESTION")
    check("the primary action says what it does", "Scan site" in html)
    check("full audit and consent check are independent jobs",
          "do_audit" in html and 'name=\'run_consent\'' in html)
    _s2 = _i.getsource(_api.submit_form)
    check("and unticking the audit runs the one-page consent path",
          "if not do_audit and run_consent" in _s2)
    check("target URL is named for what it is",
          "Client website" in html and ">Target URL<" not in html)
    check("vertical is gone from the form",
          "name='vertical'" not in html)
    check("and so is primary conversion",
          "name='primary_conversion'" not in html)
    check("industry is one control, not a filter beside a select",
          html.count("id='indlist'") == 1 and "gscfilter" not in html)

    print("\nA BOUNDARY CARRIES A ROUTE THROUGH IT")
    # "Read this from the Search Console UI" is true and is not an
    # instruction: it does not say which of eleven reports, or where, and the
    # property is already known.
    from engine.collectors import analytics as _an
    _asrc = _i.getsource(_an)
    check("each UI-only row names its report",
          "Indexing \u2192 Pages" in _asrc and "Core Web Vitals" in _asrc)
    check("and carries a deep link to the property",
          "search.google.com/search-console/index" in _asrc
          and "resource_id=" in _asrc)
    check("with what to record once it opens",
          "exclusion reasons by page count" in _asrc)

    print("\nA ZIP CODE NAMES ITS OWN STATE")
    # THE BUG, REPLAYED.
    #
    # A media plan's targeting list is eighty ZIP codes. Every one came back
    # with a "?" against it - no state, so no privacy law, so a scan that
    # skipped the state checks and said nothing about having done so. USPS
    # assigns the first three digits in contiguous per-state ranges, which is
    # a forty-line table rather than a lookup service.
    from engine.geo import zip_state, state_of
    for z, want in (("37314", "TN"), ("37901", "TN"), ("90210", "CA"),
                    ("10001", "NY"), ("99501", "AK"), ("02134", "MA"),
                    ("60601", "IL"), ("37314-1234", "TN")):
        check(f"{z} resolves to {want}", zip_state(z) == want, str(zip_state(z)))
    check("a market that is only a ZIP still gets its state",
          state_of("37314") == "TN")
    check("and a written market still works",
          state_of("Knox County, TN") == "TN")
    check("something that is not a ZIP is not guessed at",
          zip_state("Knoxville") is None and zip_state("123") is None)
    # The browser validates the pills and Python decides the laws; two copies
    # of this table would agree until one was edited.
    from app import ui as _ui2
    import inspect as _in2
    check("the form builds its copy from the scanner's table",
          "ZIP3_RANGES" in _in2.getsource(_ui2.dashboard_html))

    print("\nA NATIONAL TARGET IS EVERY STATE, NOT NO STATE")
    # "US" and "united states" landed in unparsed - no state, so no state law
    # checked at all - on a client selling nationwide, which is the one case
    # where EVERY state's law applies. The most exposed client got the
    # emptiest legal section, and the pill showed a question mark.
    from engine.geo import is_national, national_states
    for _w in ("US", "us", "U.S.", "USA", "united states", "United States",
               "nationwide", "National", "all 50 states"):
        check(f"{_w!r} reads as national", is_national(_w))
    check("a real market does not", not is_national("Knoxville, TN"))
    check("and neither does a state that happens to be two letters",
          not is_national("TN") and not is_national("CA"))
    _n = summarize("US")
    check("a national market is not 'unparsed'", _n["unparsed"] == [],
          str(_n["unparsed"]))
    check("it is flagged as national", _n["national"] is True)
    check("and expands to every state in the map",
          _n["checkable"] == national_states(), str(_n["checkable"])[:80])
    check("which is more than a handful", len(_n["checkable"]) >= 20,
          str(len(_n["checkable"])))
    check("states_from_markets agrees",
          states_from_markets("united states") == national_states())
    # It is the CHECKABLE set on purpose - a nationwide seller is subject to
    # Georgia too, and there is no Georgia law in the map to check against.
    check("a state we have no checks for is not invented",
          "GA" not in _n["checkable"])
    _mix = summarize("Knoxville, TN \u00d7 US")
    check("one national market covers the whole list",
          _mix["checkable"] == national_states())
    check("naming states without a national marker still narrows",
          summarize("Knoxville, TN")["checkable"] == ["TN"]
          and summarize("Knoxville, TN")["national"] is False)
    import app.ui as _ui5
    from types import SimpleNamespace as _N5
    _dsrc = _ui5.dashboard_html([], _N5(name="V", email="e"), 0,
                                caps={"consent": True, "aivis": True})
    check("the browser mirrors the same vocabulary",
          "geoIsNational" in _dsrc and "'nationwide':1" in _dsrc)
    check("and lights every checkable chip for it",
          "national = true" in _dsrc)
    check("a national market is its own branch, not a fake state code",
          "var nat = geoIsNational(label)" in _dsrc
          and "GEO_STATES[st][0]" not in _dsrc)
    check("and every state-table read is guarded",
          "(st && GEO_STATES[st]) || null" in _dsrc)

    print("\nONE UNKNOWN CODE MUST NOT BLANK THE WHOLE BOX")
    # Every pill is built inside one .map(), so a lookup that throws takes
    # down the entire list: not one broken pill but NO pills, for any market,
    # with nothing in the console to say why. That is exactly what shipped
    # when a national market was given the state code "US" and looked up in a
    # table of real states.
    #
    # Driven in a real browser, because this failure is invisible to Python:
    # the page rendered perfectly and the script was dead.
    try:
        import asyncio as _aio
        from playwright.sync_api import sync_playwright as _spw
    except ImportError:
        print("  SKIP  playwright is not installed here")
    else:
        import tempfile as _tf, os as _os
        _p = _os.path.join(_tf.mkdtemp(), "dash.html")
        with open(_p, "w") as _fh:
            _fh.write(_dsrc)
        with _spw() as _pw:
            _b = _pw.chromium.launch()
            _pg = _b.new_page()
            _errs = []
            _pg.on("pageerror", lambda e: _errs.append(str(e)))
            _pg.goto("file://" + _p)
            for _m in ("united states", "Knox County, TN", "Boise"):
                _pg.fill("#geoinput", _m)
                _pg.press("#geoinput", "Enter")
            _pg.wait_for_timeout(200)
            _tags = _pg.eval_on_selector_all("#geopills .st",
                                             "e=>e.map(x=>x.textContent)")
            _lit = _pg.eval_on_selector_all("#strow .tg.auto,#strow .tg.on",
                                            "e=>e.map(x=>x.dataset.st)")
            _hid = _pg.input_value("#primary_markets")
            _b.close()
        check("no script error while adding markets", not _errs, str(_errs[:2]))
        check("three markets, three pills", len(_tags) == 3, str(_tags))
        check("the national one is tagged ALL, not a state",
              _tags and _tags[0] == "ALL", str(_tags))
        check("a real state still tags itself", "TN" in _tags)
        check("and an unresolvable market still shows its question mark",
              "?" in _tags)
        check("the hidden field carries every label",
              "united states" in _hid and "Knox County, TN" in _hid)
        check("a national market lights every checkable state",
              len(_lit) == len(national_states()), str(len(_lit)))

    print("\nRUN AGAIN MEANS THE SAME RUN")
    # "'full audit' keeps getting checked when i only did a consent check".
    # The two job boxes sit above the phase list and prefill never touched
    # them, so every re-run of a consent check was one unnoticed tick away
    # from a 150-page crawl of the client's server.
    from app.ui import settings_of as _st
    import json as _j
    _c = _st({"options": _j.dumps({"quick": "consent", "run_consent": True,
                                   "max_pages": 1, "skip_judgment": True})})
    check("a consent-only run reports the audit job as off",
          _c["do_audit"] is False)
    check("and the consent job as on", _c["run_consent"] is True)
    _f = _st({"options": _j.dumps({"run_consent": True, "max_pages": 150})})
    check("a full run reports the audit job as on", _f["do_audit"] is True)
    _old = _st({"options": "{}"})
    check("a run from before the two-job form still reads as a full audit",
          _old["do_audit"] is True)
    _src = _in2.getsource(_ui2.dashboard_html)
    check("prefill restores the job checkboxes",
          "do_audit'); \n" in _src or "getElementById('do_audit')" in _src)
    check("and re-syncs the panels after it does", "jobSync();" in _src)

    print("\nONE BAR, AND IT MEANS SOMETHING")
    # Two bars swept at once and neither said anything. A sweeping bar answers
    # "is it alive"; the question people have is "how far through".
    from app.ui import _progress_pct as _pp
    check("the second sweeping bar is gone", ".glide{" not in _src)
    check("queued sits at the floor", _pp("queued", "", 0, 0)[0] <= 5)
    _c = _pp("crawling", "crawling site", 12, 40)
    check("a crawl interpolates on pages actually crawled",
          10 < _c[0] < 40 and _c[1] == "12 of up to 40 pages", str(_c))
    check("and the caption names the measurement, not the phase",
          "pages" in _c[1])
    # Monotonic: the number can never go backwards through the pipeline.
    _seq = [_pp("queued", "", 0, 0)[0],
            _pp("crawling", "crawling site", 1, 40)[0],
            _pp("crawling", "crawling site", 39, 40)[0],
            _pp("checking", "assessing E-E-A-T and GEO checkpoints", 0, 40)[0],
            _pp("checking", "collecting Search Console data", 0, 40)[0],
            _pp("checking", "asking 4 AI assistants about x", 0, 40)[0],
            _pp("scoring", "scoring", 0, 40)[0]]
    check("it only ever moves forward", _seq == sorted(_seq), str(_seq))
    check("and never claims to be finished", max(_seq) <= 99, str(max(_seq)))
    # The consent walk counts its own pages, and on a consent-only run that
    # walk IS the checking phase.
    _p1 = _pp("checking", "consent scan \u2014 page 1 of 4", 0, 1, True)
    _p4 = _pp("checking", "consent scan \u2014 page 4 of 4", 0, 1, True)
    check("a consent walk moves page by page", _p1[0] < _p4[0],
          f"{_p1[0]} -> {_p4[0]}")
    check("and says which page", _p1[1] == "page 1 of 4", str(_p1))
    check("the same walk inside a full audit takes a slice, not the band",
          _pp("checking", "consent scan \u2014 page 4 of 4",
              0, 40, False)[0] < 90)
    check("a status we have no band for gets the honest indeterminate bar",
          _pp("ready", "", 0, 0) == (None, ""))
    check("as does a phase with nothing countable in it",
          _pp("checking", "doing something new", 0, 0)[1] == "checking")
    # And the worker has to emit the line this reads.
    from app import worker as _wk
    _wsrc = _in2.getsource(_wk)
    check("the consent walk reports which page it is on",
          'f"consent scan \u2014 page {_i} of {_total}"' in _wsrc
          or "consent scan \u2014 page " in _wsrc)

    print("\nA HAND-PICKED PROPERTY SURVIVES THE RE-RUN")
    # _pendingProps was set by Run again and read by nothing at all, so the
    # operator's chosen property was carried to the form and dropped.
    check("the stash is actually consumed", "function applyPending()" in _src)
    check("and consumed where the dropdowns finish loading",
          _src.index("applyPending();") < _src.index("function applyPending()"))
    check("the container is stashed too, not just GSC and GA4",
          "gtm: st.gtm_container" in _src)
    check("a revoked property is not force-selected",
          "if (!known) return;" in _src)

    print("\nWHICH LOGIN THE CLIENT HAS TO ADD, BY NAME")
    from engine.collectors import analytics as _an
    check("Search Console names the login", "digital@" in _an.VICI_GSC_LOGIN)
    check("GA4 names the same one", _an.VICI_GA4_LOGIN == _an.VICI_GSC_LOGIN)
    check("Tag Manager names a different one",
          "tagops1@" in _an.VICI_GTM_LOGIN
          and _an.VICI_GTM_LOGIN != _an.VICI_GSC_LOGIN)
    check("and the form says so before any check is run",
          "digital@reporting.zone" in _src
          and "tagops1@reporting.zone" in _src)

    print("\nAN ACCOUNT WE COULD NOT READ IS NOT A NO")
    # The GTM API is 0.25 QPS per project and shared, so accounts drop out of
    # the enumeration routinely. Asserting "no Vici login can see that
    # container" off a half-read list sends someone to email a client about
    # access they already granted.
    _probe_src = _in2.getsource(_an._gtm_probe)
    check("the unreadable accounts reach the verdict", "unread" in _probe_src)
    check("and make it ours rather than theirs",
          '"ours": True,\n                "installed": installed,\n'
          '                "unread": unread' in _probe_src
          or ('"unread": unread' in _probe_src
              and '"ours": True' in _probe_src))
    check("a near-miss container under the client's name is named",
          "near" in _probe_src and "_name_keys" in _probe_src)
    _cont_src = _in2.getsource(_an._gtm_containers)
    check("a rate-limited account is retried before being given up on",
          "429" in _cont_src and "sleep" in _cont_src)
    check("and counted when it still fails", "unread.append" in _cont_src)

    print("\nTHE ETA DESCRIBES THIS RUN")
    _psrc = _in2.getsource(_ui2.audit_html)
    check("a consent-only run does not quote the 150-page crawl time",
          'quick") or "") == "consent"' in _psrc)
    check("the page count comes from the options, not a constant",
          "_o.get(\"max_pages\") or 150" in _psrc)
    check("and the rail does not call one browser page a crawl",
          '"loading"' in _psrc)

    print("\n" + "=" * 68)
    if FAILED:
        print(f"  {len(FAILED)} FAILED: {FAILED}")
    else:
        print("  ALL CHECKS PASSED — markets decide which laws get checked")
    print("=" * 68 + "\n")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
