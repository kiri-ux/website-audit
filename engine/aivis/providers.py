"""
Platform adapters.

Every provider returns the same `Answer` shape so the analysis layer never knows
which platform it is reading. Adding a platform means adding one class.

Two things worth knowing before you extend this:

1. **Citation extraction is deliberately defensive.** These APIs change their
   response shapes. Each adapter tries several known locations for source URLs
   and falls back to scraping URLs out of the answer text. A provider that
   silently returns zero citations because a field was renamed would quietly
   destroy the headline metric, so `citation_shape` records where the URLs were
   actually found — check it when numbers look wrong.

2. **These systems are non-deterministic.** The same query returns different
   answers run to run. Never report a single-shot boolean; the monitor runs each
   query `repeats` times and reports RATES. See monitor.py.

Config: every provider is constructed from env vars and reports `available`.
Absent keys mean the platform is skipped and recorded as such — not a crash, and
not a silent zero.
"""
from __future__ import annotations
import json
import os
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

URL_RE = re.compile(r"https?://[^\s\)\]\>\"',]+")


@dataclass
class Answer:
    platform: str
    query_id: str
    text: str = ""
    citations: list = field(default_factory=list)   # [{"url","title","domain"}]
    citation_shape: str = ""                        # where URLs were found
    latency_ms: int = 0
    error: str | None = None
    raw: dict | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _domain(url: str) -> str:
    try:
        h = urlparse(url).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def _mk(urls, titles=None, shape=""):
    titles = titles or {}
    out, seen = [], set()
    for u in urls:
        u = u.rstrip(".,);]")
        d = _domain(u)
        if not d or u in seen:
            continue
        seen.add(u)
        out.append({"url": u, "title": titles.get(u, ""), "domain": d})
    return out, shape


def _from_text(text):
    return _mk(URL_RE.findall(text or ""), shape="answer_text")


class Provider:
    name = "base"
    #: whether this platform natively returns sources. Platforms that do not
    #: (a plain chat completion with no retrieval) measure *training-data
    #: recall*, which is a different and weaker signal than citation.
    grounded = True

    def __init__(self, **kw):
        self.cfg = kw

    @property
    def available(self) -> bool:
        return False

    def ask(self, query_id: str, prompt: str) -> Answer:
        raise NotImplementedError

    # shared HTTP helper — stdlib only, so the engine has no new hard deps
    def _post(self, url, payload, headers, timeout=90):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **headers}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            # AN ERROR BODY THAT NOBODY READS IS NOT AN ERROR MESSAGE.
            #
            # `HTTPError: HTTP Error 404: Not Found` is what this used to raise
            # and what the checkpoint printed — a status line and nothing else.
            # Every one of these APIs answers a 4xx with a JSON body that says
            # exactly what is wrong ("models/gemini-2.0-flash is not found for
            # API version v1beta"), and the body was being closed unread.
            #
            # The same shape as every other bug here: the cause exists, it is
            # one layer down, and nothing unwraps it.
            body = ""
            try:
                body = (e.read() or b"").decode("utf-8", "replace").strip()
            except Exception:  # noqa: BLE001
                body = ""
            detail = ""
            if body:
                try:
                    j = json.loads(body)
                    err = j.get("error") if isinstance(j, dict) else None
                    if isinstance(err, dict):
                        detail = str(err.get("message") or "").strip()
                    elif isinstance(err, str):
                        detail = err.strip()
                except Exception:  # noqa: BLE001
                    pass
                detail = detail or body[:300]
            # The host, so a 404 from the wrong base URL is distinguishable
            # from a 404 for a model name.
            host = url.split("//", 1)[-1].split("/", 1)[0]
            raise RuntimeError(
                f"HTTP {e.code} from {host}"
                + (f": {detail}" if detail else "")) from None

    def _timed(self, query_id, fn):
        t0 = time.time()
        try:
            text, cites, shape, raw = fn()
            return Answer(self.name, query_id, text, cites, shape,
                          int((time.time() - t0) * 1000), None, raw)
        except Exception as e:
            return Answer(self.name, query_id, "", [], "",
                          int((time.time() - t0) * 1000), f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------- Perplexity
class PerplexityProvider(Provider):
    """Sonar models are search-grounded and return sources natively."""
    name = "perplexity"

    @property
    def available(self):
        return bool(os.getenv("PERPLEXITY_API_KEY"))

    def ask(self, query_id, prompt):
        def go():
            d = self._post(
                "https://api.perplexity.ai/chat/completions",
                {"model": os.getenv("PERPLEXITY_MODEL", "sonar"),
                 "messages": [{"role": "user", "content": prompt}]},
                {"Authorization": f"Bearer {os.getenv('PERPLEXITY_API_KEY')}"})
            text = d["choices"][0]["message"]["content"]
            # Perplexity has used several field names over time; try each.
            for key, shape in (("search_results", "search_results"),
                               ("citations", "citations"),
                               ("sources", "sources")):
                v = d.get(key)
                if v:
                    urls = [x["url"] if isinstance(x, dict) else x for x in v]
                    titles = {x["url"]: x.get("title", "")
                              for x in v if isinstance(x, dict) and x.get("url")}
                    c, s = _mk(urls, titles, shape)
                    return text, c, s, d
            c, s = _from_text(text)
            return text, c, s, d
        return self._timed(query_id, go)


# ---------------------------------------------------------------- Anthropic
class AnthropicProvider(Provider):
    """Claude with the server-side web_search tool enabled."""
    name = "claude"

    @property
    def available(self):
        return bool(os.getenv("ANTHROPIC_API_KEY"))

    def ask(self, query_id, prompt):
        def go():
            d = self._post(
                "https://api.anthropic.com/v1/messages",
                {"model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
                 "max_tokens": 1024,
                 "messages": [{"role": "user", "content": prompt}],
                 "tools": [{"type": "web_search_20250305", "name": "web_search",
                            "max_uses": 5}]},
                {"x-api-key": os.getenv("ANTHROPIC_API_KEY"),
                 "anthropic-version": "2023-06-01"})
            text, urls, titles = [], [], {}
            for blk in d.get("content", []):
                t = blk.get("type")
                if t == "text":
                    text.append(blk.get("text", ""))
                    for cit in blk.get("citations", []) or []:
                        u = cit.get("url")
                        if u:
                            urls.append(u)
                            titles[u] = cit.get("title", "")
                elif t == "web_search_tool_result":
                    for r in blk.get("content", []) or []:
                        u = r.get("url")
                        if u:
                            urls.append(u)
                            titles[u] = r.get("title", "")
            body = "\n".join(text)
            if urls:
                c, s = _mk(urls, titles, "web_search_tool_result+citations")
            else:
                c, s = _from_text(body)
            return body, c, s, d
        return self._timed(query_id, go)


# ---------------------------------------------------------------- OpenAI
class OpenAIProvider(Provider):
    """GPT via the Responses API with the hosted web_search tool."""
    name = "chatgpt"

    @property
    def available(self):
        return bool(os.getenv("OPENAI_API_KEY"))

    def ask(self, query_id, prompt):
        def go():
            d = self._post(
                "https://api.openai.com/v1/responses",
                {"model": os.getenv("OPENAI_MODEL", "gpt-4.1"),
                 "input": prompt,
                 "tools": [{"type": "web_search"}]},
                {"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"})
            text, urls, titles = [], [], {}

            def walk(node):
                if isinstance(node, dict):
                    if node.get("type") == "output_text":
                        text.append(node.get("text", ""))
                        for a in node.get("annotations", []) or []:
                            u = a.get("url")
                            if u:
                                urls.append(u)
                                titles[u] = a.get("title", "")
                    for v in node.values():
                        walk(v)
                elif isinstance(node, list):
                    for v in node:
                        walk(v)
            walk(d.get("output", d))
            body = "\n".join(text) or d.get("output_text", "")
            if urls:
                c, s = _mk(urls, titles, "output_text.annotations")
            else:
                c, s = _from_text(body)
            return body, c, s, d
        return self._timed(query_id, go)


# ---------------------------------------------------------------- Gemini
class GeminiProvider(Provider):
    """Gemini with Google Search grounding."""
    name = "gemini"

    @property
    def available(self):
        return bool(os.getenv("GEMINI_API_KEY"))

    # A HARDCODED MODEL NAME IS A TIME BOMB WITH GOOGLE'S HAND ON THE TIMER.
    #
    # The default was `gemini-2.0-flash` on `v1beta`, and every query came back
    # `HTTP Error 404: Not Found` — a model name that is not served to this key
    # on this API version. Which model is current changes on Google's schedule,
    # not ours, and hardcoding one means the row silently dies the day they
    # retire it and stays dead until somebody reads a checkpoint.
    #
    # So: ask what this key can actually call, and pick from that. An explicit
    # GEMINI_MODEL still wins — an operator who sets one has expressed a
    # preference, and a preference beats a default.
    _PREFER = ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash",
               "gemini-2.0-flash-001", "gemini-1.5-flash", "gemini-1.5-pro")
    _resolved = None

    def _models(self):
        """Model ids this key may call generateContent on. [] if unlistable."""
        import urllib.request
        url = ("https://generativelanguage.googleapis.com/v1beta/models"
               f"?key={os.getenv('GEMINI_API_KEY')}&pageSize=200")
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                d = json.loads(r.read().decode())
        except Exception:  # noqa: BLE001
            return []
        out = []
        for m in (d.get("models") or []):
            if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                continue
            name = str(m.get("name") or "")
            out.append(name.split("/")[-1] if "/" in name else name)
        return out

    def _model(self):
        env = os.getenv("GEMINI_MODEL", "").strip()
        if env:
            return env
        if GeminiProvider._resolved:
            return GeminiProvider._resolved
        have = self._models()
        pick = next((m for m in self._PREFER if m in have), None)
        if not pick:
            # Anything flash-shaped beats nothing, and a plain gemini model
            # beats guessing a name Google has never heard of.
            pick = next((m for m in have if "flash" in m and "vision" not in m),
                        None) or next((m for m in have
                                       if m.startswith("gemini")), None)
        if not pick:
            raise RuntimeError(
                "No Gemini model on this key supports generateContent"
                + (f" (listed: {', '.join(have[:6])})" if have else
                   " — and the model list could not be read, which usually "
                   "means GEMINI_API_KEY is wrong or the Generative Language "
                   "API is not enabled on that project"))
        GeminiProvider._resolved = pick
        return pick

    def ask(self, query_id, prompt):
        def go():
            model = self._model()
            d = self._post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={os.getenv('GEMINI_API_KEY')}",
                {"contents": [{"parts": [{"text": prompt}]}],
                 "tools": [{"google_search": {}}]}, {})
            cand = (d.get("candidates") or [{}])[0]
            body = "".join(p.get("text", "")
                           for p in cand.get("content", {}).get("parts", []))
            urls, titles = [], {}
            gm = cand.get("groundingMetadata", {}) or {}
            for ch in gm.get("groundingChunks", []) or []:
                w = ch.get("web") or {}
                if w.get("uri"):
                    urls.append(w["uri"])
                    titles[w["uri"]] = w.get("title", "")
            if urls:
                c, s = _mk(urls, titles, "groundingMetadata.groundingChunks")
            else:
                c, s = _from_text(body)
            return body, c, s, d
        return self._timed(query_id, go)


# ------------------------------------------------------- Google AI Overviews
class AIOverviewProvider(Provider):
    """
    Google AI Overviews has no official API, so this goes through a SERP
    provider. Two transports, and the order matters.

    DATAFORSEO FIRST, BECAUSE IT IS ALREADY PAID FOR.
    -------------------------------------------------
    This adapter only spoke SerpApi's dialect — GET, `api_key=` in the query
    string — so an install with DataForSEO credentials already set reported
    "not measured" and told the operator to go and configure a SERP provider.
    They had one. AI Overviews are part of DataForSEO's standard SERP API at
    $0.0006 a request, on the same login already answering backlinks,
    rankings and Lighthouse.

    Recommending a second subscription to replace something already bought is
    a worse failure than not measuring at all: it costs money and it makes the
    tool look like it does not know what it is holding.

    SerpApi stays supported and stays FIRST when explicitly configured — an
    operator who sets SERP_ENDPOINT has expressed a preference, and a
    preference beats a default.
    """
    name = "ai_overview"

    @property
    def available(self):
        if os.getenv("SERP_API_KEY") and os.getenv("SERP_ENDPOINT"):
            return True
        try:
            from engine.collectors.dataforseo import configured
            return configured()
        except Exception:  # noqa: BLE001
            return False

    # ---------------------------------------------------------- DataForSEO
    def _ask_dataforseo(self, prompt):
        """
        One `serp/google/organic/live/advanced` call, read for three things.

        The same response carries the AI Overview, the featured snippet and
        the other SERP features, so the three GEO rows that were each waiting
        on "a SERP data provider" are all answered by this one request.
        """
        from engine.collectors.dataforseo import dfs_post, _result
        # THE FAILURE HAS TO NAME ITSELF.
        #
        # "no successful responses collected" is what the GEO row says when
        # every ask returned nothing, and it is the third message today that
        # describes an absence without naming a cause. DataForSEO reports its
        # own errors INSIDE a 200 — a bad keyword, an unpaid balance and a
        # wrong location code all arrive as status_code fields in the
        # envelope — so an exception is not raised and nothing is logged.
        raw = dfs_post("/serp/google/organic/live/advanced",
                               [{"keyword": prompt,
                                 "location_code": int(
                                     os.getenv("SERP_LOCATION_CODE", "2840")),
                                 "language_code": os.getenv("SERP_LANGUAGE",
                                                            "en"),
                                 "device": "desktop",
                                 "load_async_ai_overview": True}],
                               timeout=90)
        env = raw if isinstance(raw, dict) else {}
        task = ((env.get("tasks") or [{}])[0]) or {}
        code = int(task.get("status_code") or env.get("status_code") or 0)
        if code and code != 20000:
            raise RuntimeError(
                f"DataForSEO SERP returned {code}: "
                f"{task.get('status_message') or env.get('status_message') or ''}"
                .strip())
        res = _result(env)
        items = (res[0].get("items") or []) if res else []
        body, urls, titles = "", [], {}
        features = set()
        for it in items:
            t = (it.get("type") or "").lower()
            if t:
                features.add(t)
            if t != "ai_overview":
                continue
            # The overview's prose lives in nested elements, and the citations
            # in a references array carrying domain, url and title.
            for el in (it.get("items") or it.get("elements") or []):
                txt = el.get("text") or el.get("snippet") or ""
                if txt:
                    body += ("\n" if body else "") + txt
            for ref in (it.get("references") or []):
                u = ref.get("url") or ref.get("link")
                if u:
                    urls.append(u)
                    titles[u] = ref.get("title") or ref.get("source") or ""
        return body, urls, titles, {"items": items, "features": sorted(features)}

    def ask(self, query_id, prompt):
        if not (os.getenv("SERP_API_KEY") and os.getenv("SERP_ENDPOINT")):
            def go_dfs():
                body, urls, titles, raw = self._ask_dataforseo(prompt)
                if urls:
                    c, s = _mk(urls, titles, "ai_overview.references")
                else:
                    c, s = _from_text(body)
                return body, c, s, raw
            return self._timed(query_id, go_dfs)

        def go():
            import urllib.request, urllib.parse
            url = (os.getenv("SERP_ENDPOINT") + "?" + urllib.parse.urlencode({
                "q": prompt, "api_key": os.getenv("SERP_API_KEY"),
                "engine": "google", "gl": os.getenv("SERP_COUNTRY", "us")}))
            with urllib.request.urlopen(url, timeout=90) as r:
                d = json.loads(r.read().decode())
            ov = d.get("ai_overview") or d.get("answer_box") or {}
            body = ov.get("text") or ov.get("snippet") or ""
            if not body and ov.get("text_blocks"):
                body = "\n".join(b.get("snippet", "") for b in ov["text_blocks"])
            urls, titles = [], {}
            for ref in (ov.get("references") or ov.get("sources") or []):
                u = ref.get("link") or ref.get("url")
                if u:
                    urls.append(u)
                    titles[u] = ref.get("title", "")
            if urls:
                c, s = _mk(urls, titles, "ai_overview.references")
            else:
                c, s = _from_text(body)
            return body, c, s, d
        return self._timed(query_id, go)


# ---------------------------------------------------------------- Copilot
class CopilotProvider(Provider):
    """
    Microsoft Copilot has no public consumer API. Route via Azure OpenAI with
    Bing grounding, or a SERP provider for Bing. Left explicitly unavailable
    rather than faking it — a platform we cannot measure must report that, not
    quietly return zeros.
    """
    name = "copilot"

    @property
    def available(self):
        return bool(os.getenv("COPILOT_ENDPOINT") and os.getenv("COPILOT_API_KEY"))

    def ask(self, query_id, prompt):
        def go():
            d = self._post(os.getenv("COPILOT_ENDPOINT"),
                           {"messages": [{"role": "user", "content": prompt}]},
                           {"api-key": os.getenv("COPILOT_API_KEY")})
            body = d["choices"][0]["message"]["content"]
            ctx = d["choices"][0]["message"].get("context", {}) or {}
            urls, titles = [], {}
            for c_ in ctx.get("citations", []) or []:
                u = c_.get("url")
                if u:
                    urls.append(u)
                    titles[u] = c_.get("title", "")
            if urls:
                c, s = _mk(urls, titles, "message.context.citations")
            else:
                c, s = _from_text(body)
            return body, c, s, d
        return self._timed(query_id, go)


# ---------------------------------------------------------------- Replay
class ReplayProvider(Provider):
    """
    Deterministic provider backed by a recorded corpus.

    Two jobs:
      * makes the whole pipeline runnable and demoable with no API keys
      * gives the analysis layer a ground-truth corpus, so detection accuracy is
        measurable rather than assumed

    Record real responses with `monitor.record_corpus()` and replay them in CI.
    """
    name = "replay"

    def __init__(self, corpus: dict, platform: str = "replay", **kw):
        super().__init__(**kw)
        self.corpus = corpus
        self.name = platform

    @property
    def available(self):
        return True

    def ask(self, query_id, prompt):
        rec = (self.corpus.get(self.name, {}) or {}).get(query_id)
        if rec is None:
            return Answer(self.name, query_id, "", [], "replay_miss", 0,
                          "no recorded response for this query")
        text = rec.get("text", "")
        cites = rec.get("citations")
        if cites is None:
            c, s = _from_text(text)
        else:
            c, s = _mk([x["url"] for x in cites],
                       {x["url"]: x.get("title", "") for x in cites}, "recorded")
        return Answer(self.name, query_id, text, c, s, rec.get("latency_ms", 0), None)


PROVIDERS = {
    "perplexity": PerplexityProvider,
    "claude": AnthropicProvider,
    "chatgpt": OpenAIProvider,
    "gemini": GeminiProvider,
    "ai_overview": AIOverviewProvider,
    "copilot": CopilotProvider,
}


def active_providers(only: list[str] | None = None) -> tuple[list, list]:
    """Returns (available, skipped) so the report can state honestly which
    platforms were measured and which were not configured."""
    avail, skipped = [], []
    for key, cls in PROVIDERS.items():
        if only and key not in only:
            continue
        p = cls()
        (avail if p.available else skipped).append(p if p.available else key)
    return avail, skipped
