/**
 * Content script — extracts the SAME page shape the Python crawler produces.
 *
 * Why this exists: a WAF fingerprints the TLS handshake, HTTP/2 frame order and
 * JS environment. Python `requests` fails all of them regardless of user-agent.
 * This runs inside real Chrome, so there is nothing to fake.
 *
 * It also reads the POST-JavaScript DOM, which is strictly more accurate than
 * raw HTML on any site that renders content client-side.
 *
 * Field names here must match engine/crawler.py :: Page exactly. The server
 * reconstructs an artifact from this and runs the identical 159 checkers.
 */

function absolutise(u) {
  try { return new URL(u, location.href).href; } catch { return ""; }
}

function isInternal(href) {
  try {
    const h = new URL(href).hostname.toLowerCase().replace(/^www\./, "");
    const here = location.hostname.toLowerCase().replace(/^www\./, "");
    return h === here;
  } catch { return false; }
}

function collectSchema() {
  const types = new Set(), raw = [];
  document.querySelectorAll('script[type*="ld+json" i]').forEach(s => {
    try {
      const data = JSON.parse(s.textContent || "{}");
      raw.push(data);
      const walk = node => {
        if (!node || typeof node !== "object") return;
        if (Array.isArray(node)) return node.forEach(walk);
        const t = node["@type"];
        (Array.isArray(t) ? t : [t]).forEach(x => x && types.add(x));
        (node["@graph"] || []).forEach(walk);
      };
      walk(data);
    } catch { types.add("__INVALID_JSONLD__"); }
  });
  document.querySelectorAll("[itemtype]").forEach(el => {
    const t = el.getAttribute("itemtype");
    if (t) types.add(t.split("/").pop());
  });
  return { schema_types: [...types].sort(), schema_raw: raw.slice(0, 20) };
}

function capturePage() {
  const headings = [], h1 = [];
  document.querySelectorAll("h1,h2,h3,h4,h5,h6").forEach(h => {
    const lvl = parseInt(h.tagName[1], 10);
    const txt = (h.innerText || "").trim().slice(0, 300);
    headings.push([lvl, txt]);
    if (lvl === 1) h1.push(txt);
  });

  const images = [...document.images].map(img => ({
    src: absolutise(img.getAttribute("src") || img.getAttribute("data-src") || ""),
    alt: img.getAttribute("alt"),
    loading: img.getAttribute("loading"),
    width: img.getAttribute("width"),
    height: img.getAttribute("height"),
    srcset: !!img.getAttribute("srcset")
  }));

  const links_internal = [], links_external = [];
  document.querySelectorAll("a[href]").forEach(a => {
    const href = absolutise(a.getAttribute("href"));
    if (!href || /^(mailto:|tel:|javascript:)/i.test(a.getAttribute("href"))) return;
    const rec = { href: href.split("#")[0],
                  anchor: (a.innerText || "").trim().slice(0, 120),
                  rel: a.getAttribute("rel") || "" };
    (isInternal(href) ? links_internal : links_external).push(rec);
  });

  // Scripts: src URLs plus inline bodies. This alone answers all 12 analytics
  // checkpoints, and inline JS is where most tag managers actually live.
  const scripts = [], inline = [];
  document.querySelectorAll("script").forEach(s => {
    if (s.src) scripts.push(absolutise(s.src));
    else if (s.textContent) inline.push(s.textContent.slice(0, 4000));
  });

  const canonEl = document.querySelector('link[rel~="canonical" i]');
  const metaDesc = document.querySelector('meta[name="description" i]');
  const metaRobots = document.querySelector('meta[name="robots" i]');
  const viewport = document.querySelector('meta[name="viewport" i]');
  const charsetEl = document.querySelector("meta[charset]");
  const httpEquiv = document.querySelector('meta[http-equiv="content-type" i]');

  const bodyText = (document.body?.innerText || "").replace(/\s+/g, " ").trim();
  const html = document.documentElement.outerHTML;

  return {
    url: location.href.split("#")[0],
    final_url: location.href.split("#")[0],
    status_code: 200,                    // the server fills the true status
    content_type: document.contentType || "text/html",
    bytes_html: new Blob([html]).size,
    title: (document.title || "").trim() || null,
    meta_description: metaDesc ? (metaDesc.content || "").trim() : null,
    meta_robots: metaRobots ? (metaRobots.content || "").trim() : null,
    canonical: canonEl ? absolutise(canonEl.getAttribute("href")) : null,
    viewport: viewport ? (viewport.content || "").trim() : null,
    charset: charsetEl ? charsetEl.getAttribute("charset")
             : (httpEquiv && /charset=/i.test(httpEquiv.content)
                ? httpEquiv.content.split(/charset=/i)[1].trim() : null),
    doctype: document.doctype
             ? (document.doctype.name === "html" && !document.doctype.publicId
                ? "html5" : "other")
             : null,
    lang: document.documentElement.getAttribute("lang"),
    hreflang: [...document.querySelectorAll("link[hreflang]")].map(l => ({
      lang: l.getAttribute("hreflang"), href: absolutise(l.getAttribute("href"))
    })),
    h1, headings,
    word_count: bodyText ? bodyText.split(" ").length : 0,
    text_html_ratio: html.length ? +(bodyText.length / html.length).toFixed(4) : 0,
    rendered_text: bodyText.slice(0, 20000),
    images, links_internal, links_external,
    scripts,
    inline_script_text: inline.join("\n").slice(0, 40000),
    ...collectSchema(),
    // Provenance: these findings came from a real browser render, not a fetch.
    capture_method: "browser_extension",
    js_rendered: true
  };
}

/** Trigger lazy-loaded content, then settle. */
async function primePage() {
  const h = document.body ? document.body.scrollHeight : 0;
  for (let y = 0; y < h; y += window.innerHeight * 0.9) {
    window.scrollTo(0, y);
    await new Promise(r => setTimeout(r, 120));
  }
  window.scrollTo(0, 0);
  await new Promise(r => setTimeout(r, 300));
}

chrome.runtime.onMessage.addListener((msg, _sender, respond) => {
  if (msg?.type !== "VICI_CAPTURE") return;
  (async () => {
    try {
      if (msg.scroll !== false) await primePage();
      respond({ ok: true, page: capturePage() });
    } catch (e) {
      respond({ ok: false, error: String(e) });
    }
  })();
  return true;   // async response
});


// ---------------------------------------------------------------------------
// TWO EXTRAS THE BACKGROUND WORKER ASKS FOR.
//
// VICI_LINKS  — internal links from the current page, used when a site's
//               sitemap turns out to be an index we could not follow or is
//               simply absent. Without it a thin sitemap meant a two-page
//               audit.
//
// The audit page hook — when this script lands on a Vici audit page that is
// waiting for a capture, it wires that page's button straight to the worker.
// The operator was otherwise copying an audit id out of one tab and into a
// popup in another, which is exactly the kind of step that gets done wrong at
// 5pm.
// ---------------------------------------------------------------------------
chrome.runtime.onMessage.addListener((msg, _s, respond) => {
  if (msg?.type === "VICI_LINKS") {
    const links = [...document.querySelectorAll("a[href]")]
      .map(a => a.href)
      .filter(h => /^https?:/i.test(h))
      .map(h => h.split("#")[0]);
    respond({ links: [...new Set(links)] });
    return true;
  }
});

(function wireConsoleCapture() {
  // The finished report carries the audit id and the Search Console property
  // it used. Reading them off the page is the difference between one click
  // and two copy-pastes between tabs.
  const el = document.getElementById("vici-console");
  if (!el) return;
  const btn = document.getElementById("vici-console-go");
  if (!btn) return;
  // The button is always on the page; this removes the "you need the
  // extension" caveat beside it, because we ARE the extension.
  const note = document.getElementById("vici-console-note");
  if (note) note.remove();
  btn.addEventListener("click", () => {
    let prop = el.dataset.gscProperty || "";
    if (!prop) {
      // No property was pinned on this audit, so ask once rather than guess —
      // reading the wrong property is worse than reading none.
      prop = window.prompt(
        "Search Console property to read.\n\nCopy it exactly as Search " +
        "Console shows it — usually the site URL with its trailing slash, " +
        "or sc-domain:example.com for a domain property.", location.origin + "/");
      if (!prop) return;
    }
    btn.disabled = true;
    btn.textContent = "Reading Search Console — watch the extension popup";
    chrome.runtime.sendMessage({
      type: "VICI_CONSOLE", auditId: el.dataset.auditId, property: prop
    });
  });
})();

(function wireConsentPage() {
  // Same hook, different run. The consent page is where somebody is looking
  // at a scan that says "not tested: this ran without a browser" — which is
  // exactly the moment the capture is worth offering, and exactly the moment
  // it was not.
  const el = document.getElementById("vici-consent");
  if (!el) return;
  el.dataset.extension = "present";
  const btn = document.getElementById("vici-consent-go");
  if (!btn) return;
  btn.addEventListener("click", () => {
    btn.disabled = true;
    btn.textContent = "Consent capture started — watch the extension popup";
    chrome.runtime.sendMessage({
      type: "VICI_CONSENT_FOR",
      auditId: el.dataset.auditId,
      url: el.dataset.target
    });
  });
})();

(function wireAuditPage() {
  const el = document.getElementById("vici-capture");
  if (!el) return;
  el.dataset.extension = "present";        // page reveals the button only then
  const btn = document.getElementById("vici-capture-go");
  if (!btn) return;
  btn.addEventListener("click", () => {
    btn.disabled = true;
    btn.textContent = "Capture started — watch the extension popup";
    chrome.runtime.sendMessage({
      type: "VICI_START_FOR",
      auditId: el.dataset.auditId,
      url: el.dataset.target
    });
  });
})();
