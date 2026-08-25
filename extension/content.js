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
    btn.textContent = "Reading Search Console…";
    chrome.runtime.sendMessage({
      type: "VICI_CONSOLE", auditId: el.dataset.auditId, property: prop
    });
    // Same watcher as the other three. This one has always ended in a draft
    // the operator reviews in the popup, so the log is the thing that tells
    // them the draft is ready rather than the run being silent.
    viciWatch(el, "Search Console");
  });
})();

// ---------------------------------------------------------------------------
// PROGRESS BELONGS ON THE PAGE YOU ARE LOOKING AT.
//
// Three buttons here used to say "started — watch the extension popup", and a
// web page CANNOT open the toolbar popup: nothing pops up, and the operator
// sits watching a tab open and close with no idea whether it worked. Then the
// run finishes, the page still shows the old scan because nothing told it to
// reload, and the only honest reading is that the button is broken.
//
// The service worker already keeps a log. This polls it and prints it right
// under the button, then reloads the page when the run finishes — which is
// the moment the new answers exist and the panel that started all this
// should be gone.
// ---------------------------------------------------------------------------
function viciWatch(host, label) {
  let box = host.querySelector(".vici-log");
  if (!box) {
    box = document.createElement("div");
    box.className = "vici-log";
    box.style.cssText =
      "margin-top:10px;padding:9px 11px;border-radius:8px;background:#0f2744;"
      + "color:#cfe0f5;font:12px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace;"
      + "white-space:pre-wrap;max-height:190px;overflow:auto";
    host.appendChild(box);
  }
  let sawRunning = false;
  const tick = async () => {
    let st;
    try {
      ({ state: st } = await chrome.runtime.sendMessage({ type: "VICI_GET_STATE" }));
    } catch (e) { return; }              // worker asleep between messages
    if (!st) return;
    if (st.running) sawRunning = true;
    const pct = st.total ? Math.round(100 * st.done / st.total) : 0;
    box.textContent = (st.running ? `${label} — step ${st.done} of ${st.total} (${pct}%)\n\n`
                                  : `${label} — finished\n\n`)
                    + (st.log || []).slice(0, 12).join("\n");
    if (sawRunning && !st.running) {
      clearInterval(timer);
      box.textContent += "\n\nreloading this page with the new answers…";
      // A SHORT WAIT, NOT ZERO. The upload resolves a moment before the
      // server has finished rescoring and rewriting the stored scan, and a
      // reload that beats it shows the old page and looks like a failure.
      setTimeout(() => location.reload(), 2500);
    }
  };
  const timer = setInterval(tick, 1000);
  tick();
}

function viciStart(elId, btnId, msgType, label) {
  const el = document.getElementById(elId);
  if (!el) return;
  el.dataset.extension = "present";
  el.dataset.version = chrome.runtime.getManifest().version;
  const btn = document.getElementById(btnId);
  if (!btn) return;
  btn.addEventListener("click", () => {
    btn.disabled = true;
    btn.textContent = label + " running…";
    chrome.runtime.sendMessage({
      type: msgType, auditId: el.dataset.auditId, url: el.dataset.target,
      // The extra pages come off the audit, via the page. A conversion URL is
      // where conversion pixels fire, so a capture that skips them reports a
      // client's bought products as never firing.
      urls: (el.dataset.urls || "").split(/\s+/).filter(Boolean) });
    viciWatch(el, label);
  });
}

viciStart("vici-fix", "vici-fix-go", "VICI_PSI_FOR", "Speed test");
viciStart("vici-consent", "vici-consent-go", "VICI_CONSENT_FOR", "Consent capture");
viciStart("vici-capture", "vici-capture-go", "VICI_START_FOR", "Site capture");


