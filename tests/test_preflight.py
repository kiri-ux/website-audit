"""
Deciding two settings from evidence instead of asking someone to predict them.

"Browser user-agent — if the site blocks bots" and "Render JavaScript — for SPA
sites" were checkboxes on the run form. Both ask the operator to know something
about a site they have not crawled yet, and both are expensive to get wrong in
ways that do not announce themselves: the wrong user-agent turns "we were
blocked" into "your site is broken", and JS rendering left off on an app
produces 118 empty shells scored as 118 pages with no content.

What this file guards is the part that makes it safe to automate:

  1. It escalates ONLY on evidence, and says what the evidence was.
  2. It does not escalate on a network error — a site that is down is not a
     site that blocks bots.
  3. It does not claim the browser user-agent worked when it did not.
  4. A ticked box still wins. Someone who knows the site beats a probe.

Run:  python3 -m tests.test_preflight
"""
from __future__ import annotations
import http.server
import os
import socketserver
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PORT = 8098
FAILED: list[str] = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILED.append(label)


REAL = ("<html><head><title>Ooten Law Firm</title></head><body>"
        "<h1>Knoxville criminal defense</h1>"
        + "<p>We represent clients across thirteen counties in East Tennessee "
          "and have done so for twenty years. Call for a consultation.</p>" * 6
        + "</body></html>")

CHALLENGE = ("<html><head><title>Just a moment...</title></head><body>"
             "<h1>Checking your browser before accessing the site.</h1>"
             "<p>DDoS protection by Cloudflare</p></body></html>")

SPA = ('<html><head><script src="/a.js"></script><script src="/b.js"></script>'
       '</head><body><div id="root"></div></body></html>')

MODE = {"mode": "real"}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        ua = self.headers.get("User-Agent", "")
        browser = "Mozilla/5.0" in ua and "Vici" not in ua
        m = MODE["mode"]
        if m == "real":
            body, code = REAL, 200
        elif m == "spa":
            body, code = SPA, 200
        elif m == "waf_ua":
            # Blocks our bot, serves a browser. The case a UA switch fixes.
            body, code = (REAL, 200) if browser else (CHALLENGE, 200)
        elif m == "waf_403":
            body, code = (REAL, 200) if browser else ("Forbidden", 403)
        elif m == "waf_hard":
            # Blocks everything. A UA switch must NOT be claimed as a fix.
            body, code = CHALLENGE, 200
        elif m == "waf_then_spa":
            body, code = (SPA, 200) if browser else (CHALLENGE, 200)
        else:
            body, code = REAL, 200
        raw = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main():
    from engine.preflight import decide, BROWSER_UA

    # allow_reuse_address must be set on the CLASS, before bind — setting it
    # on the instance afterwards does nothing, and the leftover socket then
    # collides with whichever suite runs next.
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{PORT}/"

    try:
        print("\nA HEALTHY SITE IS LEFT ALONE")
        # The expensive mistake in the other direction: rendering JavaScript
        # when it was not needed is a browser per page, minutes of wall clock,
        # and memory on a 2GB instance for nothing.
        MODE["mode"] = "real"
        d = decide(url)
        check("nothing is escalated", not d["user_agent"] and not d["render_js"],
              str(d["why"]))
        check("and the probe reports that it ran", d["checked"])

        print("\nA BOT-PROTECTED SITE GETS THE BROWSER USER-AGENT")
        MODE["mode"] = "waf_ua"
        d = decide(url)
        check("the user-agent is switched", d["user_agent"] == BROWSER_UA)
        check("and it says what gave it away",
              any("bot-protection screen" in w for w in d["why"]), str(d["why"]))
        check("and that the browser request actually worked",
              any("returned the page" in w for w in d["why"]))

        MODE["mode"] = "waf_403"
        d = decide(url)
        check("an HTTP 403 to our crawler counts too",
              d["user_agent"] == BROWSER_UA
              and any("HTTP 403" in w for w in d["why"]), str(d["why"]))

        print("\nBUT IT NEVER CLAIMS A FIX THAT DID NOT WORK")
        # A site that blocks both is not fixed by pretending to be Chrome, and
        # saying so buries the real finding — the crawl was blocked — under a
        # setting that did nothing.
        MODE["mode"] = "waf_hard"
        d = decide(url)
        check("a site that blocks everything gets no user-agent change",
              d["user_agent"] is None)
        check("and the run is told it will report being blocked",
              any("did not get past it" in w for w in d["why"]), str(d["why"]))

        print("\nAN APP THAT RENDERS ITSELF GETS JAVASCRIPT")
        MODE["mode"] = "spa"
        d = decide(url)
        check("rendering is turned on", d["render_js"] is True)
        check("and the reason names the mount point and the word count",
              any("mount point" in w for w in d["why"]), str(d["why"]))

        print("\nAND THE TWO STACK, BECAUSE A SITE CAN BE BOTH")
        MODE["mode"] = "waf_then_spa"
        d = decide(url)
        check("a WAF-protected app gets both",
              d["user_agent"] == BROWSER_UA and d["render_js"] is True,
              str(d["why"]))

        print("\nA SITE THAT IS DOWN IS NOT A SITE THAT BLOCKS BOTS")
        # Escalating here sends someone to argue with a client about a WAF
        # that is not there.
        d = decide("http://127.0.0.1:9/")
        check("nothing is decided", not d["user_agent"] and not d["render_js"])
        check("the probe reports that it could NOT run", d["checked"] is False)
        check("and carries the error rather than a guess", bool(d["error"]),
              str(d["error"])[:60])

        print("\nA TICKED BOX STILL WINS")
        import inspect
        from app import worker
        src = inspect.getsource(worker._crawl)
        check("a forced user-agent is not overwritten",
              'forced_ua = bool(opts.get("user_agent"))' in src
              and "not forced_ua" in src)
        check("a forced render_js is not overwritten",
              'forced_js = bool(opts.get("render_js"))' in src
              and "not forced_js" in src)
        check("and the probe is skipped entirely when both are forced",
              "if not (forced_ua and forced_js):" in src)
        check("what it decided is recorded on the audit, not just logged",
              'extras["preflight"]' in inspect.getsource(worker._after_crawl))
    finally:
        srv.shutdown()
        srv.server_close()

    print("\n" + "=" * 68)
    if FAILED:
        print(f"  {len(FAILED)} FAILED: {FAILED}")
    else:
        print("  ALL CHECKS PASSED — the crawl settings are decided from "
              "evidence, and say what the evidence was")
    print("=" * 68 + "\n")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
