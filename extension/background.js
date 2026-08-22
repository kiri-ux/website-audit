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

// The API is a fixed deployment, not a per-user setting. Asking for it on every
// capture was a field nobody ever changed and everybody had to fill in. It is
// still overridable in storage for a local run — there is just no reason to put
// it in front of an operator.
const API_BASE = "https://vici-audit-api.onrender.com";

const DEFAULTS = {
  apiBase: API_BASE,
  token: "",
  auditId: "",
  dwellMs: 2500,        // time on page after load before capture
  jitterMs: 900,        // randomised so the cadence is not metronomic
  maxPages: 30,         // template sampling: 83% of checks need no more
  scroll: true
};

let state = { running: false, done: 0, total: 0, log: [], pages: [], extras: {} };

const sleep = ms => new Promise(r => setTimeout(r, ms));

// ---------------------------------------------------------------------------
// KEEP THE SERVICE WORKER ALIVE FOR THE LENGTH OF A RUN.
//
// An MV3 service worker is evicted after ~30 seconds of no extension-API
// activity. A capture spends most of its time waiting — for a page to load,
// then dwelling on it — and those gaps are exactly what Chrome reads as idle.
// So the run would stop partway through, and it looked like "it stops when I
// switch tabs" because switching away is when you notice.
//
// Two belts. A cheap API call every 20s resets the idle timer directly, and an
// alarm is the backstop for the case where the worker died anyway: alarms
// survive eviction and wake it back up.
// ---------------------------------------------------------------------------
let keepAliveTimer = null;

function keepAlive(on) {
  if (on) {
    if (keepAliveTimer) return;
    keepAliveTimer = setInterval(() => {
      chrome.runtime.getPlatformInfo().catch(() => {});
    }, 20000);
    chrome.alarms.create("vici-keepalive", { periodInMinutes: 0.5 });
  } else {
    if (keepAliveTimer) { clearInterval(keepAliveTimer); keepAliveTimer = null; }
    chrome.alarms.clear("vici-keepalive").catch(() => {});
  }
}

chrome.alarms.onAlarm.addListener(() => {
  // Nothing to do — being called at all is the point. If the worker had been
  // evicted mid-run this is what brings it back.
});
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

const sameHost = (a, b) => {
  try {
    return new URL(a).hostname.replace(/^www\./, "")
        === new URL(b).hostname.replace(/^www\./, "");
  } catch { return false; }
};

/**
 * Pull every <loc> out of a sitemap, following ONE level of sitemap index.
 *
 * /sitemap.xml is very often an index — <sitemapindex> pointing at
 * post-sitemap.xml, page-sitemap.xml and so on — not a list of pages. The
 * regex matched its <loc> elements happily and came back with "1 URL", so a
 * 150-page capture captured two. Follow the children.
 */
async function sitemapUrls(origin, sm, cap) {
  const locs = t => [...t.matchAll(/<loc>\s*([^<\s]+)\s*<\/loc>/gi)].map(m => m[1]);
  let urls = locs(sm.body);
  if (/<sitemapindex/i.test(sm.body)) {
    const children = urls.filter(u => sameHost(u, origin)).slice(0, 25);
    say(`sitemap index: ${children.length} child sitemaps`);
    urls = [];
    for (const child of children) {
      const t = await fetchText(child);
      if (t.status === 200) urls.push(...locs(t.body));
      if (urls.length > cap * 20) break;   // plenty to sample from
    }
  }
  return urls;
}

/** Internal links from the homepage — the fallback when the sitemap is thin. */
async function homepageLinks(origin, tabId, cap) {
  try {
    await chrome.tabs.update(tabId, { url: origin + "/" });
    await sleep(2500);
    const res = await chrome.tabs.sendMessage(tabId, { type: "VICI_LINKS" });
    const links = (res?.links || []).filter(u => sameHost(u, origin));
    return [...new Set(links)].slice(0, cap);
  } catch (e) {
    return [];
  }
}

async function discoverUrls(origin, limit) {
  const out = [origin.replace(/\/$/, "") + "/"];
  const sm = await fetchText(origin + "/sitemap.xml");
  state.extras.sitemap = sm;
  state.extras.robots = await fetchText(origin + "/robots.txt");
  state.extras.llms = await fetchText(origin + "/llms.txt");

  if (sm.status === 200 && /<loc>/i.test(sm.body)) {
    const locs = await sitemapUrls(origin, sm, limit);
    // Sample ACROSS the sitemap rather than taking the first N — the first N
    // are usually one template (all products, or all blog posts), which would
    // leave most page types unaudited.
    const internal = locs.filter(u => sameHost(u, origin));
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
  keepAlive(true);
  const origin = new URL(startUrl).origin;
  say(`starting capture of ${origin}`);

  let urls = await discoverUrls(origin, c.maxPages);
  // Seed additional URLs from the homepage's own links if the sitemap was thin.
  state.total = urls.length;

  const tab = await chrome.tabs.create({ url: "about:blank", active: false });
  try {
    // A sitemap that yielded almost nothing is not a small site — it is usually
    // an index we could not follow, or a CMS that never wrote one. Reading the
    // homepage's own links costs one page load and is the difference between
    // auditing two pages and auditing the site.
    if (urls.length < Math.min(8, c.maxPages)) {
      const extra = await homepageLinks(origin, tab.id, c.maxPages);
      for (const u of extra) if (!urls.includes(u)) urls.push(u);
      urls = urls.slice(0, c.maxPages);
      state.total = urls.length;
      say(`sitemap was thin — homepage links bring it to ${urls.length} pages`);
    }
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

  if (!state.pages.length) {
    say("nothing captured — aborting upload");
    state.running = false; keepAlive(false); return;
  }

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
  keepAlive(false);
  chrome.runtime.sendMessage({ type: "VICI_STATE", state }).catch(() => {});
}

chrome.runtime.onMessage.addListener((msg, _s, respond) => {
  if (msg?.type === "VICI_START") { run(msg.url); respond({ ok: true }); }
  if (msg?.type === "VICI_CONSENT") { consentRun(msg.url); respond({ ok: true }); }
  // Launched from the audit page's own button: the page already knows the
  // audit id and the target, so nothing needs copying into the popup.
  if (msg?.type === "VICI_START_FOR") {
    chrome.storage.local.set({ auditId: msg.auditId, apiBase: API_BASE })
      .then(() => run(msg.url));
    respond({ ok: true });
  }
  if (msg?.type === "VICI_STOP") {
    state.running = false; keepAlive(false); respond({ ok: true });
  }
  if (msg?.type === "VICI_GET_STATE") respond({ state });
  return true;
});


// ===================================================================
// CONSENT CAPTURE
//
// The standalone scanner's dead end is bot protection: a challenge page means
// Playwright falls back to raw HTML, which cannot see the banner, Consent Mode,
// pre-consent fires or the reject test. That is three and a half of the four
// questions it exists to answer.
//
// This is the same trick the crawl capture uses, applied to consent. The
// operator's own Chrome, their own IP, their own cookies — which challenge
// pages let through, because it is a person.
//
// The extension CLASSIFIES NOTHING. It records what happened and posts it; the
// server runs the same signature matching, gcs= parsing and endpoint tables the
// Playwright path uses. Two classifiers would eventually disagree about the
// same site and there would be no way to know which was right.
// ===================================================================

const ACCEPT_TEXT = /\b(accept|agree|allow|got it|ok|i understand|continue)\b/i;
const REJECT_TEXT = /\b(reject|decline|refuse|deny|necessary only|essential only)\b/i;

let recorder = null;   // { bucket: [urls], filter: tabId }

function recStart(tabId) {
  recStop();
  const bucket = [];
  const onBefore = d => {
    if (d.tabId === tabId && d.url && !d.url.startsWith("chrome-")) bucket.push(d.url);
  };
  chrome.webRequest.onBeforeRequest.addListener(
    onBefore, { urls: ["<all_urls>"], tabId });
  recorder = { bucket, onBefore };
  return bucket;
}

function recStop() {
  if (recorder) {
    try { chrome.webRequest.onBeforeRequest.removeListener(recorder.onBefore); }
    catch (e) { /* already gone */ }
    recorder = null;
  }
}

async function inTab(tabId, fn, args = []) {
  const [res] = await chrome.scripting.executeScript(
    { target: { tabId }, func: fn, args, world: "MAIN" });
  return res?.result;
}

// Runs INSIDE the page. Reads what only the page can know: whether anything
// that looks like a consent banner is actually visible, and what Consent Mode
// defaults the dataLayer was given before the tags loaded.
function _probe() {
  const out = { visible: false, defaults: {}, read: false, html: "",
                scripts: [] };
  try {
    out.html = document.documentElement.outerHTML.slice(0, 400000);
    out.scripts = [...document.querySelectorAll("script[src]")]
      .map(s => s.src).slice(0, 200);
  } catch (e) { /* nothing */ }
  try {
    const rx = /(cookie|consent|gdpr|ccpa|privacy|onetrust|cmp)/i;
    const nodes = [...document.querySelectorAll(
      "div,section,aside,dialog,[role=dialog],[aria-modal]")].slice(0, 4000);
    for (const n of nodes) {
      const id = (n.id || "") + " " + (n.className || "");
      if (typeof id !== "string" || !rx.test(id)) continue;
      const r = n.getBoundingClientRect();
      const st = getComputedStyle(n);
      // Visible means ON SCREEN and painted. A banner rendered off-canvas or
      // at zero opacity is exactly the failure mode this row is looking for.
      if (r.width > 120 && r.height > 40 && r.bottom > 0 && r.top < innerHeight
          && st.visibility !== "hidden" && st.display !== "none"
          && parseFloat(st.opacity || "1") > 0.05) { out.visible = true; break; }
    }
  } catch (e) { /* leave false */ }
  try {
    const dl = window.dataLayer || [];
    out.read = Array.isArray(dl);
    for (const row of dl) {
      // gtag pushes arguments objects: ["consent","default",{...}]
      const a = row && row.length ? [...row] : null;
      if (a && a[0] === "consent" && a[1] === "default" && a[2]) {
        Object.assign(out.defaults, a[2]);
      }
    }
  } catch (e) { /* leave empty */ }
  return out;
}

function _click(patternSource) {
  const rx = new RegExp(patternSource, "i");
  const els = [...document.querySelectorAll(
    "button,a,[role=button],input[type=button],input[type=submit]")];
  for (const el of els) {
    const t = (el.innerText || el.value || el.getAttribute("aria-label") || "").trim();
    if (!t || t.length > 40 || !rx.test(t)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    el.click();
    return t;
  }
  return null;
}

async function settle(ms) { await new Promise(r => setTimeout(r, ms)); }

async function consentRun(startUrl) {
  const c = await cfg();
  if (!c.apiBase || !c.auditId) { say("ERROR: set API URL and audit ID first"); return; }
  state = { running: true, done: 0, total: 4, log: state.log, pages: [], extras: {} };
  keepAlive(true);
  say(`consent capture of ${startUrl}`);

  const tab = await chrome.tabs.create({ url: "about:blank", active: false });
  const cap = { url: startUrl, accept_clicked: false, reject_clicked: false };
  try {
    // ---- 1. pre-consent: load and watch, touching nothing ----------------
    let bucket = recStart(tab.id);
    await chrome.tabs.update(tab.id, { url: startUrl });
    await settle(6000);
    const probe = await inTab(tab.id, _probe);
    cap.pre_requests = [...bucket];
    cap.html = probe?.html || "";
    cap.scripts = probe?.scripts || [];
    cap.banner_visible = !!probe?.visible;
    cap.consent_defaults = probe?.defaults || {};
    cap.consent_defaults_read = !!probe?.read;
    state.done = 1; say(`pre-consent: ${cap.pre_requests.length} requests, ` +
                        `banner ${cap.banner_visible ? "visible" : "not seen"}`);

    // ---- 2. accept, then watch again -------------------------------------
    const hit = await inTab(tab.id, _click, [ACCEPT_TEXT.source]);
    if (hit) {
      cap.accept_clicked = true;
      await settle(5000);
      cap.post_requests = [...bucket];
      say(`clicked “${hit}” — ${cap.post_requests.length} requests total`);
    } else {
      say("no Accept control found");
    }
    state.done = 2;

    // ---- 3. reject, on a FRESH load --------------------------------------
    // A fresh load matters: once Accept has been clicked the CMP has written
    // its cookie, and a Reject click after that is testing a different state
    // from the one a first-time visitor sees.
    recStop();
    bucket = recStart(tab.id);
    await chrome.tabs.update(tab.id, { url: startUrl + (startUrl.includes("?") ? "&" : "?") + "vici=1" });
    await settle(5000);
    const rej = await inTab(tab.id, _click, [REJECT_TEXT.source]);
    if (rej) {
      cap.reject_clicked = true;
      bucket.length = 0;             // only what fires AFTER the click counts
      await settle(5000);
      cap.reject_requests = [...bucket];
      say(`clicked “${rej}” — ${cap.reject_requests.length} requests after`);
    } else {
      say("no Reject control found");
    }
    state.done = 3;
  } catch (e) {
    say("ERROR: " + (e?.message || e));
  } finally {
    recStop();
    chrome.tabs.remove(tab.id).catch(() => {});
  }

  say("uploading consent capture…");
  try {
    const res = await fetch(
      `${c.apiBase.replace(/\/$/, "")}/api/audits/${c.auditId}/consent-capture`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cap) });
    say(res.ok ? "done — consent capture uploaded"
               : `upload failed: HTTP ${res.status}`);
  } catch (e) {
    say("upload failed: " + (e?.message || e));
  }
  state.done = 4; state.running = false;
  keepAlive(false);
  chrome.runtime.sendMessage({ type: "VICI_STATE", state }).catch(() => {});
}
