/**
 * Service worker — the auto-walk queue.
 *
 * The operator does NOT click through the site. They press Start; this opens
 * each URL in one reused tab, waits for the content script to capture, and
 * moves on. It is still real Chrome, on a real IP, with a real profile — the
 * things a WAF actually fingerprints — so it gets through where the server
 * crawler is refused.
 *
 * Pacing is deliberate: 150 tabs in 60 seconds looks scripted even from real
 * Chrome. ~3s/page with jitter reads as a fast human.
 */

const DEFAULTS = {
  apiBase: "",
  token: "",
  auditId: "",
  dwellMs: 2500,        // time on page after load before capture
  jitterMs: 900,        // randomised so the cadence is not metronomic
  maxPages: 30,         // template sampling: 83% of checks need no more
  scroll: true
};

let state = { running: false, done: 0, total: 0, log: [], pages: [], extras: {} };

const sleep = ms => new Promise(r => setTimeout(r, ms));
const jitter = cfg => cfg.dwellMs + Math.floor(Math.random() * cfg.jitterMs);

function say(msg) {
  state.log.unshift(`${new Date().toLocaleTimeString()}  ${msg}`);
  state.log = state.log.slice(0, 60);
  chrome.runtime.sendMessage({ type: "VICI_STATE", state }).catch(() => {});
}

async function cfg() {
  const s = await chrome.storage.local.get(DEFAULTS);
  return { ...DEFAULTS, ...s };
}

/**
 * Fetch text resources from the BROWSER, not the server.
 * robots.txt / sitemap.xml / llms.txt were also being blocked server-side, so
 * pulling them here closes that gap too.
 */
async function fetchText(url) {
  try {
    const r = await fetch(url, { credentials: "omit", redirect: "follow" });
    const body = await r.text();
    return { status: r.status, body: body.slice(0, 500000) };
  } catch (e) {
    return { status: 0, body: "", error: String(e) };
  }
}

async function discoverUrls(origin, limit) {
  const out = [origin.replace(/\/$/, "") + "/"];
  const sm = await fetchText(origin + "/sitemap.xml");
  state.extras.sitemap = sm;
  state.extras.robots = await fetchText(origin + "/robots.txt");
  state.extras.llms = await fetchText(origin + "/llms.txt");

  if (sm.status === 200 && /<loc>/i.test(sm.body)) {
    const locs = [...sm.body.matchAll(/<loc>\s*([^<\s]+)\s*<\/loc>/gi)].map(m => m[1]);
    // Sample ACROSS the sitemap rather than taking the first N — the first N
    // are usually one template (all products, or all blog posts), which would
    // leave most page types unaudited.
    const internal = locs.filter(u => {
      try { return new URL(u).hostname.replace(/^www\./, "")
                    === new URL(origin).hostname.replace(/^www\./, ""); }
      catch { return false; }
    });
    const step = Math.max(1, Math.floor(internal.length / limit));
    for (let i = 0; i < internal.length && out.length < limit; i += step) {
      if (!out.includes(internal[i])) out.push(internal[i]);
    }
    say(`sitemap: ${internal.length} URLs, sampling ${out.length}`);
  } else {
    say("no usable sitemap — will follow links from the homepage");
  }
  return out.slice(0, limit);
}

async function capture(tabId, url, c) {
  await chrome.tabs.update(tabId, { url });
  // wait for load
  await new Promise(resolve => {
    const listener = (id, info) => {
      if (id === tabId && info.status === "complete") {
        chrome.tabs.onUpdated.removeListener(listener); resolve();
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(() => { chrome.tabs.onUpdated.removeListener(listener); resolve(); }, 20000);
  });
  await sleep(jitter(c));
  try {
    const res = await chrome.tabs.sendMessage(tabId, {
      type: "VICI_CAPTURE", scroll: c.scroll });
    return res?.ok ? res.page : null;
  } catch (e) {
    return null;
  }
}

async function run(startUrl) {
  const c = await cfg();
  if (!c.apiBase || !c.auditId) { say("ERROR: set API URL and audit ID first"); return; }

  state = { running: true, done: 0, total: 0, log: state.log, pages: [], extras: {} };
  const origin = new URL(startUrl).origin;
  say(`starting capture of ${origin}`);

  const urls = await discoverUrls(origin, c.maxPages);
  // Seed additional URLs from the homepage's own links if the sitemap was thin.
  state.total = urls.length;

  const tab = await chrome.tabs.create({ url: "about:blank", active: false });
  try {
    for (const url of urls) {
      if (!state.running) { say("stopped by operator"); break; }
      const page = await capture(tab.id, url, c);
      if (page) {
        state.pages.push(page);
        say(`captured ${page.title ? "“" + page.title.slice(0, 40) + "”" : url}`);
      } else {
        say(`FAILED ${url}`);
      }
      state.done++;
      chrome.runtime.sendMessage({ type: "VICI_STATE", state }).catch(() => {});
    }
  } finally {
    chrome.tabs.remove(tab.id).catch(() => {});
  }

  if (!state.pages.length) { say("nothing captured — aborting upload"); state.running = false; return; }

  say(`uploading ${state.pages.length} pages…`);
  try {
    const r = await fetch(
      `${c.apiBase.replace(/\/$/, "")}/api/audits/${c.auditId}/capture`,
      { method: "POST",
        headers: { "Content-Type": "application/json",
                   ...(c.token ? { "x-api-key": c.token } : {}) },
        body: JSON.stringify({
          start_url: origin + "/",
          pages: state.pages,
          robots: state.extras.robots,
          sitemap: state.extras.sitemap,
          llms: state.extras.llms,
          capture_method: "browser_extension"
        }) });
    const body = await r.json().catch(() => ({}));
    say(r.ok ? `DONE — ${body.checkpoints || "?"} checkpoints evaluated. Open the report.`
             : `upload failed (${r.status}): ${body.detail || ""}`);
  } catch (e) {
    say(`upload error: ${e}`);
  }
  state.running = false;
  chrome.runtime.sendMessage({ type: "VICI_STATE", state }).catch(() => {});
}

chrome.runtime.onMessage.addListener((msg, _s, respond) => {
  if (msg?.type === "VICI_START") { run(msg.url); respond({ ok: true }); }
  if (msg?.type === "VICI_STOP") { state.running = false; respond({ ok: true }); }
  if (msg?.type === "VICI_GET_STATE") respond({ state });
  return true;
});
