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
