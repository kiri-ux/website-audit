"""
Vici SEO/GEO Audit — Crawler
=============================
The keystone collector. Runs ONCE per audit and produces the crawl artifact
that ~190 of the 313 checkpoints are answered from.

Design principles (see spec §3):
  * Crawl once, answer many. Nothing here evaluates a checkpoint; it only
    captures facts. All judgment lives in checks/.
  * Everything a checkpoint might need is captured on the first pass, because
    re-crawling to answer a forgotten question is the main cost sink.
  * Politeness is non-negotiable: robots.txt respected, per-host rate limit,
    honest user-agent.
"""
from __future__ import annotations

import re
import time
import json
import gzip
import socket
import ssl
from dataclasses import dataclass, field, asdict, fields
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

USER_AGENT = "ViciAuditBot/0.1 (+https://vicimediainc.com/bot; SEO audit crawler)"

SKIP_EXT = re.compile(
    r"\.(jpg|jpeg|png|gif|webp|avif|svg|ico|css|js|pdf|zip|gz|mp4|webm|mp3|"
    r"woff2?|ttf|eot|dmg|exe|xlsx?|docx?|pptx?)(\?|$)", re.I)


# --------------------------------------------------------------------------
# Artifact records
# --------------------------------------------------------------------------
@dataclass
class Page:
    url: str
    final_url: str = ""
    status_code: int = 0
    depth: int = 0
    elapsed_ms: int = 0
    content_type: str = ""
    bytes_html: int = 0

    # response-level
    headers: dict = field(default_factory=dict)
    redirect_chain: list = field(default_factory=list)

    # head
    title: str | None = None
    meta_description: str | None = None
    meta_robots: str | None = None
    x_robots_tag: str | None = None
    canonical: str | None = None
    viewport: str | None = None
    charset: str | None = None
    doctype: str | None = None
    lang: str | None = None
    hreflang: list = field(default_factory=list)

    # body
    h1: list = field(default_factory=list)
    headings: list = field(default_factory=list)      # [(level, text)]
    word_count: int = 0
    text_html_ratio: float = 0.0
    rendered_text: str = ""
    footer_text: str = ""      # site-wide footer — where NAP lives

    # assets & relationships
    images: list = field(default_factory=list)        # {src, alt, loading, width, height}
    links_internal: list = field(default_factory=list)  # {href, anchor, rel}
    links_external: list = field(default_factory=list)
    scripts: list = field(default_factory=list)       # src URLs + inline snippets
    inline_script_text: str = ""

    # structured data
    schema_types: list = field(default_factory=list)
    schema_raw: list = field(default_factory=list)

    # computed post-crawl
    inbound_internal_links: int = 0

    error: str | None = None


@dataclass
class CrawlQuality:
    """
    Was the crawl actually usable?

    This exists because of a real production failure: a bot-protected site
    returned a near-empty 200 shell, and the checkers dutifully reported ~20
    confident findings — no title, no H1, no images, no links — describing a
    site that does not look like that at all. Every one of those findings was
    false, and a partner reading them would have (correctly) concluded the tool
    was broken.

    A crawler that cannot see the page must SAY SO. It must never let downstream
    checks turn "we were blocked" into "your site is broken". This is the same
    rule the scoring engine already enforces for Need Access; it just needs to
    apply one layer earlier.
    """
    degenerate: bool = False
    reason: str = ""
    signals: list = field(default_factory=list)
    homepage_bytes: int = 0
    likely_cause: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class SiteArtifact:
    start_url: str
    host: str
    scheme: str
    pages: dict = field(default_factory=dict)          # url -> Page
    robots_txt: str | None = None
    robots_status: int = 0
    robots_served_html: bool = False
    llms_served_html: bool = False
    sitemap_served_html: bool = False
    sitemap_urls: list = field(default_factory=list)
    sitemap_status: dict = field(default_factory=dict)
    llms_txt: str | None = None
    llms_txt_status: int = 0
    tls: dict = field(default_factory=dict)
    broken_links: list = field(default_factory=list)   # {from, to, status}
    external_checked: dict = field(default_factory=dict)
    quality: CrawlQuality = field(default_factory=CrawlQuality)
    www_resolve: dict = field(default_factory=dict)
    http_to_https: dict = field(default_factory=dict)
    crawled_at: float = 0.0
    # `truncated` means ONE thing: we did not reach every page we intended to,
    # so coverage-dependent findings must be gated. It is NOT set when a
    # post-crawl verification pass runs out of time — that costs us link
    # sampling, not pages, and flagging the whole report as a partial crawl for
    # it over-claims a problem that isn't there.
    truncated: str | None = None          # page crawl cut short → gate coverage
    link_check_truncated: str | None = None   # link sampling cut short only

    @property
    def coverage_ratio(self) -> float:
        """
        Fraction of the site actually crawled, measured against the sitemap.

        Checks whose answer depends on the WHOLE corpus — orphan detection,
        duplicate sweeps, sitewide totals — are meaningless below 1.0 and must
        say so rather than reporting the shortfall as a defect. A 50-page crawl
        of a 3,108-URL sitemap will always "find" 3,058 orphans; that is
        subtraction, not analysis.
        """
        known = len(self.sitemap_status.get("_all_urls", []) or [])
        crawled = sum(1 for p in self.pages.values()
                      if not p.error and 200 <= p.status_code < 300)
        if not known:
            return 1.0 if crawled else 0.0
        return min(1.0, crawled / known)

    @property
    def is_sample(self) -> bool:
        return self.coverage_ratio < 0.9

    def to_json(self) -> str:
        d = asdict(self)
        d["pages"] = {k: asdict(v) if not isinstance(v, dict) else v
                      for k, v in self.pages.items()}
        return json.dumps(d, indent=1, default=str)


# --------------------------------------------------------------------------
# Crawler
# --------------------------------------------------------------------------
class Crawler:
    def __init__(self, start_url: str, max_pages: int = 150, max_depth: int = 4,
                 delay: float = 0.3, render_js: bool = False, timeout: int = 15,
                 respect_robots: bool = True, verbose: bool = True,
                 user_agent: str | None = None, max_seconds: int = 600,
                 progress=None):
        self.start_url = start_url.rstrip("/") + "/" if start_url.count("/") < 3 else start_url
        p = urlparse(self.start_url)
        self.host, self.scheme = p.netloc, p.scheme
        self.max_pages, self.max_depth = max_pages, max_depth
        self.delay, self.timeout = delay, timeout
        self.render_js, self.verbose = render_js, verbose
        self.respect_robots = respect_robots

        self.art = SiteArtifact(start_url=self.start_url, host=self.host, scheme=self.scheme)
        self.sess = requests.Session()
        self.ua = user_agent or USER_AGENT
        self.sess.headers.update({
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br"})
        # Hard wall-clock budget. Without it a slow or hostile host can hold a
        # worker for 45+ minutes (50 pages x 15s, then up to 180 link probes),
        # which is indistinguishable from a hang to whoever is watching.
        self.max_seconds = max_seconds
        self._deadline = None
        self.progress = progress or (lambda *_: None)
        self.rp: RobotFileParser | None = None
        self._browser = None
        self._pw = None

    # ---------------- infrastructure probes ----------------
    @staticmethod
    def _is_html(body: str) -> bool:
        """
        Is this response HTML rather than the plain-text file we asked for?

        Bot protection commonly answers EVERY path with an HTML challenge page
        and a 200 status. Without this check the crawler happily parses that page
        as robots.txt (producing imaginary Disallow rules) or reports it as a
        valid llms.txt. Both were observed in production against the same site
        minutes apart, with contradictory results — the tell that the responses
        were synthetic.
        """
        head = (body or "").lstrip()[:400].lower()
        return head.startswith(("<!doctype", "<html", "<?xml-stylesheet")) or \
            "<html" in head or "<head" in head or "<script" in head

    def _fetch_text(self, url, **kw):
        """Fetch a plain-text resource. HTML in the body means we were served a
        challenge/error page, not the file — report it as unavailable."""
        try:
            r = self.sess.get(url, timeout=self.timeout, **kw)
            if r.status_code == 200 and self._is_html(r.text):
                return -1, "", r          # -1 == "answered with HTML, not the file"
            return r.status_code, r.text, r
        except Exception as e:
            return 0, "", e

    def probe_robots(self):
        url = f"{self.scheme}://{self.host}/robots.txt"
        code, text, _ = self._fetch_text(url)
        self.art.robots_status = code
        self.art.robots_txt = text if code == 200 else None
        if code == -1:
            self.art.robots_served_html = True
        self.rp = RobotFileParser()
        if code == 200:
            self.rp.parse(text.splitlines())
        else:
            self.rp.parse([])
        # sitemap discovery from robots
        for line in (text or "").splitlines():
            if line.lower().startswith("sitemap:"):
                self.art.sitemap_urls.append(line.split(":", 1)[1].strip())

    def probe_llms_txt(self):
        code, text, _ = self._fetch_text(f"{self.scheme}://{self.host}/llms.txt")
        self.art.llms_txt_status = code
        self.art.llms_txt = text if code == 200 else None
        if code == -1:
            self.art.llms_served_html = True

    def probe_sitemaps(self):
        if not self.art.sitemap_urls:
            self.art.sitemap_urls = [f"{self.scheme}://{self.host}/sitemap.xml"]
        found = []
        for sm in list(self.art.sitemap_urls)[:5]:
            code, text, r = self._fetch_text(sm)
            size = len(text.encode()) if text else 0
            entry = {"status": code, "bytes": size, "urls": [], "format_error": False,
                     "served_html": code == -1}
            if code == -1:
                # An HTML page returned for sitemap.xml is bot protection, not a
                # malformed sitemap. Do not report it as a format error.
                self.art.sitemap_served_html = True
                self.art.sitemap_status[sm] = entry
                continue
            if code == 200:
                try:
                    soup = BeautifulSoup(text, "xml")
                    if soup.find("sitemapindex"):
                        for loc in soup.find_all("loc")[:5]:
                            self.art.sitemap_urls.append(loc.text.strip())
                    entry["urls"] = [l.text.strip() for l in soup.find_all("loc")]
                    if not entry["urls"]:
                        entry["format_error"] = True
                except Exception:
                    entry["format_error"] = True
            self.art.sitemap_status[sm] = entry
            found.extend(entry["urls"])
        self.art.sitemap_status["_all_urls"] = sorted(set(found))

    def probe_tls(self):
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((self.host, 443), timeout=self.timeout) as s:
                with ctx.wrap_socket(s, server_hostname=self.host) as ss:
                    cert = ss.getpeercert()
                    self.art.tls = {
                        "version": ss.version(),
                        "cipher": ss.cipher()[0] if ss.cipher() else None,
                        "not_after": cert.get("notAfter"),
                        "subject": dict(x[0] for x in cert.get("subject", [])).get("commonName"),
                        "san": [v for k, v in cert.get("subjectAltName", []) if k == "DNS"],
                        "valid": True,
                    }
        except Exception as e:
            self.art.tls = {"valid": False, "error": str(e)}

    def probe_www_and_http(self):
        """URL-01 (www resolve) and URL-06 / SEC-01 (HTTP→HTTPS)."""
        bare = self.host[4:] if self.host.startswith("www.") else self.host
        for label, u in (("www", f"https://www.{bare}/"), ("nonwww", f"https://{bare}/")):
            try:
                r = self.sess.get(u, timeout=self.timeout, allow_redirects=True)
                self.art.www_resolve[label] = {"final": r.url, "status": r.status_code,
                                               "hops": len(r.history)}
            except Exception as e:
                self.art.www_resolve[label] = {"error": str(e)}
        try:
            r = self.sess.get(f"http://{self.host}/", timeout=self.timeout, allow_redirects=True)
            self.art.http_to_https = {"final": r.url, "status": r.status_code,
                                      "upgraded": r.url.startswith("https://"),
                                      "hops": len(r.history)}
        except Exception as e:
            self.art.http_to_https = {"error": str(e)}

    # ---------------- page parsing ----------------
    def _is_internal(self, url: str) -> bool:
        n = urlparse(url).netloc.lower()
        h = self.host.lower()
        return n == h or n == h.replace("www.", "") or n == "www." + h.replace("www.", "")

    def parse(self, url: str, resp, html: str, depth: int, rendered: str = "") -> Page:
        soup = BeautifulSoup(html, "html.parser")
        pg = Page(url=url, final_url=resp.url, status_code=resp.status_code, depth=depth,
                  elapsed_ms=int(resp.elapsed.total_seconds() * 1000),
                  content_type=resp.headers.get("Content-Type", ""),
                  bytes_html=len(html.encode("utf-8", "ignore")),
                  headers={k.lower(): v for k, v in resp.headers.items()},
                  redirect_chain=[{"url": h.url, "status": h.status_code} for h in resp.history])

        pg.x_robots_tag = pg.headers.get("x-robots-tag")
        pg.doctype = "html5" if re.match(r"\s*<!doctype html>", html[:200], re.I) else (
            "other" if re.match(r"\s*<!doctype", html[:200], re.I) else None)

        # charset
        m = soup.find("meta", attrs={"charset": True})
        if m:
            pg.charset = m.get("charset")
        else:
            m = soup.find("meta", attrs={"http-equiv": re.compile("content-type", re.I)})
            if m and "charset=" in (m.get("content") or ""):
                pg.charset = m["content"].split("charset=")[-1].strip()

        if soup.title and soup.title.string:
            pg.title = soup.title.string.strip()
        md = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        pg.meta_description = (md.get("content") or "").strip() if md else None
        mr = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
        pg.meta_robots = (mr.get("content") or "").strip() if mr else None
        cn = soup.find("link", attrs={"rel": lambda v: v and "canonical" in [x.lower() for x in (v if isinstance(v, list) else [v])]})
        pg.canonical = urljoin(url, cn["href"]) if cn and cn.get("href") else None
        vp = soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
        pg.viewport = (vp.get("content") or "").strip() if vp else None
        html_tag = soup.find("html")
        pg.lang = html_tag.get("lang") if html_tag else None
        pg.hreflang = [{"lang": l.get("hreflang"), "href": urljoin(url, l.get("href", ""))}
                       for l in soup.find_all("link", attrs={"hreflang": True})]

        # headings
        for lvl in range(1, 7):
            for h in soup.find_all(f"h{lvl}"):
                t = h.get_text(" ", strip=True)
                pg.headings.append((lvl, t))
                if lvl == 1:
                    pg.h1.append(t)

        # text
        for bad in soup(["script", "style", "noscript"]):
            bad.decompose()

        # THE FOOTER, CAPTURED SEPARATELY.
        #
        # The name, address, phone and hours live in the footer on almost every
        # small-business site, and it is the last thing in the DOM. Body text is
        # capped and then sliced head-and-tail before it reaches the judgment
        # layer, so on a long page the footer is exactly what falls out of the
        # middle — which is how a report told a client twice that no physical
        # address was visible on a site that prints one on every page.
        #
        # Pulling it out here means it can be attached to every judgment prompt
        # in full, whatever happens to the body slice. It is short, it is the
        # same on every page, and it is where the answer usually is.
        foot = (soup.find("footer")
                or soup.find(attrs={"role": "contentinfo"})
                or soup.find(id=lambda v: v and "footer" in v.lower())
                or soup.find(class_=lambda v: v and "footer" in " ".join(
                    v if isinstance(v, list) else [v]).lower()))
        if foot is not None:
            pg.footer_text = foot.get_text(" ", strip=True)[:1200]

        text = soup.get_text(" ", strip=True)
        pg.rendered_text = (rendered or text)[:20000]
        pg.word_count = len(text.split())
        pg.text_html_ratio = round(len(text) / max(1, len(html)), 4)

        # images
        for img in BeautifulSoup(html, "html.parser").find_all("img"):
            pg.images.append({"src": urljoin(url, img.get("src") or img.get("data-src") or ""),
                              "alt": img.get("alt"), "loading": img.get("loading"),
                              "width": img.get("width"), "height": img.get("height"),
                              "srcset": bool(img.get("srcset"))})

        # links
        s2 = BeautifulSoup(html, "html.parser")
        for a in s2.find_all("a", href=True):
            href = urldefrag(urljoin(url, a["href"]))[0]
            if href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            rec = {"href": href, "anchor": a.get_text(" ", strip=True)[:120],
                   "rel": " ".join(a.get("rel", []))}
            (pg.links_internal if self._is_internal(href) else pg.links_external).append(rec)

        # scripts  → powers all ANA tag-detection rows
        inline = []
        for sc in s2.find_all("script"):
            if sc.get("src"):
                pg.scripts.append(urljoin(url, sc["src"]))
            elif sc.string:
                inline.append(sc.string[:4000])
        pg.inline_script_text = "\n".join(inline)[:40000]

        # structured data
        for sc in s2.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
            try:
                data = json.loads(sc.string or "{}")
                pg.schema_raw.append(data)
                for node in (data if isinstance(data, list) else [data]):
                    if isinstance(node, dict):
                        t = node.get("@type")
                        for tt in (t if isinstance(t, list) else [t]):
                            if tt:
                                pg.schema_types.append(tt)
                        for g in node.get("@graph", []) or []:
                            gt = g.get("@type") if isinstance(g, dict) else None
                            for tt in (gt if isinstance(gt, list) else [gt]):
                                if tt:
                                    pg.schema_types.append(tt)
            except Exception:
                pg.schema_types.append("__INVALID_JSONLD__")
        # microdata / RDFa signal
        for el in s2.find_all(attrs={"itemtype": True}):
            pg.schema_types.append(el["itemtype"].rsplit("/", 1)[-1])
        pg.schema_types = sorted(set(pg.schema_types))
        return pg

    # ---------------- main loop ----------------
    def crawl(self) -> SiteArtifact:
        self.art.crawled_at = time.time()
        self._deadline = time.time() + self.max_seconds
        self.progress("probing robots.txt / sitemap / TLS", 0, self.max_pages)
        self.probe_robots()
        self.probe_llms_txt()
        self.probe_sitemaps()
        self.probe_tls()
        self.probe_www_and_http()

        if self.render_js:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch()

        # Seed from the start URL AND the sitemap. Sitemap seeding is what makes
        # orphan detection (TECH-25/36) meaningful: a URL that is in the sitemap
        # but never reached by following links is by definition orphaned.
        self.progress("starting crawl", 0, self.max_pages)
        queue = [(self.start_url, 0)]
        seen = {self.start_url}
        for u in self.art.sitemap_status.get("_all_urls", []):
            if u not in seen and self._is_internal(u) and not SKIP_EXT.search(u):
                seen.add(u)
                queue.append((u, 1))
        while queue and len(self.art.pages) < self.max_pages:
            if self._out_of_time():
                self.art.truncated = (
                    f"the crawl reached {len(self.art.pages)} pages before hitting "
                    f"the time budget")
                break
            url, depth = queue.pop(0)
            if self.respect_robots and self.rp and not self.rp.can_fetch(self.ua, url):
                continue
            try:
                r = self.sess.get(url, timeout=self.timeout, allow_redirects=True)
                ctype = r.headers.get("Content-Type", "")
                if "html" not in ctype.lower():
                    continue
                rendered = ""
                if self.render_js and self._browser:
                    try:
                        p = self._browser.new_page(user_agent=self.ua)
                        p.goto(url, timeout=self.timeout * 1000, wait_until="domcontentloaded")
                        rendered = p.inner_text("body")[:20000]
                        p.close()
                    except Exception:
                        pass
                pg = self.parse(url, r, r.text, depth, rendered)
            except Exception as e:
                pg = Page(url=url, depth=depth, error=str(e))
            self.art.pages[url] = pg
            n = len(self.art.pages)
            if n % 5 == 0 or n <= 3:
                self.progress(f"crawled {n} pages", n, self.max_pages)
            if self.verbose:
                print(f"  [{len(self.art.pages):3}] d{depth} {pg.status_code} {url[:88]}")

            if depth < self.max_depth and not pg.error:
                for l in pg.links_internal:
                    h = l["href"]
                    if h not in seen and not SKIP_EXT.search(h) and self._is_internal(h):
                        seen.add(h)
                        queue.append((h, depth + 1))
            time.sleep(self.delay)

        self._post_process(seen)
        self.art.quality = self._assess_quality()
        if self._browser:
            self._browser.close()
            self._pw.stop()
        return self.art

    def _assess_quality(self) -> "CrawlQuality":
        """
        Detect a crawl that produced structurally empty pages.

        Deliberately conservative: it takes THREE independent signals to call a
        crawl degenerate, so a genuinely minimal-but-real page (a one-page
        brochure site) is not falsely flagged.
        """
        ok = [p for p in self.art.pages.values()
              if not p.error and 200 <= p.status_code < 300]
        if not ok:
            return CrawlQuality(True, "no successful page responses",
                                ["all requests failed or returned an error status"],
                                0, "site unreachable, or blocking this host outright")

        home = min(ok, key=lambda p: p.depth)
        sig = []
        if home.bytes_html < 2048:
            sig.append(f"homepage HTML is only {home.bytes_html} bytes")
        if not home.title:
            sig.append("homepage has no <title>")
        if not home.h1:
            sig.append("homepage has no <h1>")
        if not home.links_internal:
            sig.append("homepage exposes no internal links")
        if home.word_count < 50:
            sig.append(f"homepage has {home.word_count} words of text")
        if not home.images:
            sig.append("homepage contains no images")

        if (self.art.robots_served_html or self.art.llms_served_html
                or self.art.sitemap_served_html):
            sig.append("plain-text paths (robots.txt / llms.txt) answered with HTML")

        if len(sig) < 3:
            return CrawlQuality(False, "crawl looks healthy", [],
                                home.bytes_html, "")

        # Distinguish the two plausible causes, because the remedy differs.
        body = (home.rendered_text or "").lower()
        challenge_words = ("just a moment", "enable javascript", "checking your browser",
                           "access denied", "captcha", "cloudflare", "are you a robot",
                           "unusual traffic", "request unsuccessful")
        if any(w in body for w in challenge_words):
            cause = ("bot protection — the server returned a challenge/interstitial "
                     "page instead of the site")
        elif home.bytes_html < 2048 and len(home.scripts) <= 2:
            cause = ("bot protection or an empty shell — a real page this small is "
                     "very unlikely")
        else:
            cause = ("client-side rendering — content is built by JavaScript and is "
                     "absent from the raw HTML")

        return CrawlQuality(True,
                            "crawled pages are structurally empty; results are not "
                            "trustworthy",
                            sig, home.bytes_html, cause)

    def _out_of_time(self) -> bool:
        return self._deadline is not None and time.time() > self._deadline

    def _post_process(self, seen):
        # inbound internal link counts (ONP-15, ONP-48, TECH-36)
        counts = {u: 0 for u in self.art.pages}
        for pg in self.art.pages.values():
            for l in pg.links_internal:
                t = l["href"].rstrip("/")
                for cand in (l["href"], t, t + "/"):
                    if cand in counts and cand != pg.url:
                        counts[cand] += 1
                        break
        for u, c in counts.items():
            self.art.pages[u].inbound_internal_links = c

        # broken internal links (TECH-06)
        # (a) targets we already crawled that returned an error status
        linked_targets = set()
        for pg in self.art.pages.values():
            linked_targets.update(l["href"] for l in pg.links_internal)
        for u in linked_targets:
            tgt = self.art.pages.get(u)
            if tgt and tgt.status_code >= 400:
                self.art.broken_links.append({"to": u, "status": tgt.status_code,
                                              "kind": "internal"})
        # (b) targets we never crawled — HEAD-check them
        to_check = {u for u in linked_targets if u not in self.art.pages}
        self.progress(f"verifying {min(len(to_check), 120)} internal links",
                      len(self.art.pages), self.max_pages)
        for u in list(to_check)[:120]:
            if SKIP_EXT.search(u):
                continue
            if self._out_of_time():
                self.art.link_check_truncated = (
                    f"internal link checking stopped after "
                    f"{len(self.art.external_checked) or 'some'} of "
                    f"{len(to_check)} targets")
                break
            try:
                r = self.sess.head(u, timeout=6, allow_redirects=True)
                if r.status_code >= 400:
                    r = self.sess.get(u, timeout=6, allow_redirects=True)
                if r.status_code >= 400:
                    self.art.broken_links.append({"to": u, "status": r.status_code,
                                                  "kind": "internal"})
            except Exception as e:
                self.art.broken_links.append({"to": u, "status": 0, "kind": "internal",
                                              "error": str(e)[:80]})

        # external link sampling (TECH-07, ONP-22)
        ext = []
        for pg in self.art.pages.values():
            ext.extend(l["href"] for l in pg.links_external)
        self.progress("verifying external links", len(self.art.pages), self.max_pages)
        for u in sorted(set(ext))[:60]:
            if self._out_of_time():
                self.art.link_check_truncated = (
                    f"outbound link checking stopped after "
                    f"{len(self.art.external_checked)} of "
                    f"{min(len(set(ext)), 60)} sampled links")
                break
            try:
                r = self.sess.head(u, timeout=5, allow_redirects=True)
                self.art.external_checked[u] = r.status_code
                if r.status_code >= 400:
                    self.art.broken_links.append({"to": u, "status": r.status_code,
                                                  "kind": "external"})
            except Exception:
                self.art.external_checked[u] = 0


def artifact_from_json(blob: str) -> "SiteArtifact":
    """
    Rebuild a SiteArtifact from a stored crawl_artifact.json.

    Exists so the report can be improved without re-crawling. Anything that can
    be derived from the artifact — business context, new checks over already-
    collected data — is derived at render time from this; only work that needs
    the network stays frozen at crawl time.

    Unknown keys are dropped rather than raising, because an artifact written by
    an older build must still load into a newer one.
    """
    d = json.loads(blob) if isinstance(blob, str) else blob
    page_fields = {f.name for f in fields(Page)}
    art_fields = {f.name for f in fields(SiteArtifact)}

    pages = {}
    for url, pd in (d.get("pages") or {}).items():
        if isinstance(pd, dict):
            pages[url] = Page(**{k: v for k, v in pd.items() if k in page_fields})

    kwargs = {k: v for k, v in d.items() if k in art_fields and k != "pages"}
    q = kwargs.pop("quality", None)
    art = SiteArtifact(**kwargs)
    art.pages = pages
    if isinstance(q, dict):
        art.quality = CrawlQuality(**{k: v for k, v in q.items()
                                      if k in {f.name for f in fields(CrawlQuality)}})
    return art
