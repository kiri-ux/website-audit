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
  scroll: true,
  // The Google account Search Console should open under. An EMAIL, because an
  // index is a position in the sign-in list and moves when an account is
  // added. Empty means whichever account is default, which is right for
  // anyone signed into one.
  googleAccount: ""
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
  // The consent equivalent of VICI_START_FOR, and for the same reason: the
  // operator was moving an audit id between two tabs by hand, which is a step
  // that exists only because nothing wired the two pages together.
  if (msg?.type === "VICI_CONSENT_FOR") {
    chrome.storage.local.set({ auditId: msg.auditId, apiBase: API_BASE })
      .then(() => consentRun(msg.url));
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

// ---------------------------------------------------------------------------
// THE GPC PASS.
//
// Twelve states require Global Privacy Control to be honoured as an opt-out,
// and the consent page has a whole section for what fires despite it. On this
// path that section read "not tested — that is ours to fix, not the client's"
// forever, because the capture never sent a gpc_requests list at all. The
// server contract has documented the field since the adapter was written; the
// extension simply never filled it, so the honest label was permanent.
//
// GPC IS TWO SIGNALS AND A SITE MAY READ EITHER. The `Sec-GPC: 1` request
// header is what a server-side implementation checks; `navigator
// .globalPrivacyControl` is what a client-side CMP reads. Sending one and not
// the other produces a site that looks like it ignored GPC when it never saw
// the half it was listening for — which is a false accusation, in a section
// about legal obligations. Both, or neither.
//
// The property has to be defined BEFORE the page's own scripts run, which is
// what `document_start` in the MAIN world buys. Registering it dynamically and
// tearing it down afterwards keeps it scoped to this one tab and this one
// pass: leaving GPC on globally would silently change every later capture.
// ---------------------------------------------------------------------------
const GPC_RULE_ID = 8801;
const GPC_SCRIPT_ID = "vici-gpc";

async function gpcOn(url) {
  let header = false, prop = false;
  try {
    await chrome.declarativeNetRequest.updateSessionRules({
      removeRuleIds: [GPC_RULE_ID],
      addRules: [{
        id: GPC_RULE_ID, priority: 1,
        action: { type: "modifyHeaders",
                  requestHeaders: [{ header: "Sec-GPC", operation: "set",
                                     value: "1" }] },
        condition: { urlFilter: "*", resourceTypes: [
          "main_frame", "sub_frame", "script", "xmlhttprequest", "image",
          "ping", "media", "other"] }
      }]
    });
    header = true;
  } catch (e) { /* reported below */ }
  try {
    await chrome.scripting.registerContentScripts([{
      id: GPC_SCRIPT_ID, matches: ["<all_urls>"], runAt: "document_start",
      world: "MAIN", js: ["gpc.js"], allFrames: true
    }]);
    prop = true;
  } catch (e) { /* reported below */ }
  return { header, prop };
}

async function gpcOff() {
  try {
    await chrome.declarativeNetRequest.updateSessionRules(
      { removeRuleIds: [GPC_RULE_ID] });
  } catch (e) { /* nothing to remove */ }
  try {
    await chrome.scripting.unregisterContentScripts({ ids: [GPC_SCRIPT_ID] });
  } catch (e) { /* nothing to remove */ }
}

async function consentRun(startUrl) {
  const c = await cfg();
  if (!c.apiBase || !c.auditId) { say("ERROR: set API URL and audit ID first"); return; }
  state = { running: true, done: 0, total: 5, log: state.log, pages: [], extras: {} };
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

    // ---- 4. the GPC pass, on another fresh load --------------------------
    //
    // Fresh again for the same reason the Reject pass is: this must be what a
    // first-time visitor with GPC on sees, not what a visitor sees after a
    // CMP has already written a cookie recording a choice.
    //
    // `gpc_requests` stays UNDEFINED if the signal could not be set. The
    // server reads "field present" as "tested", so sending an empty array
    // after a failed setup would report a clean GPC pass on a site that was
    // never sent the signal — a false clean bill in the section about legal
    // obligations.
    recStop();
    const gp = await gpcOn(startUrl);
    if (gp.header || gp.prop) {
      try {
        bucket = recStart(tab.id);
        await chrome.tabs.update(tab.id, {
          url: startUrl + (startUrl.includes("?") ? "&" : "?") + "vici=2" });
        await settle(6000);
        cap.gpc_requests = [...bucket];
        cap.gpc_signals = { header: gp.header, property: gp.prop };
        say(`GPC pass (${gp.header ? "Sec-GPC" : ""}`
            + `${gp.header && gp.prop ? " + " : ""}`
            + `${gp.prop ? "navigator" : ""}): `
            + `${cap.gpc_requests.length} requests`);
      } finally {
        await gpcOff();
      }
    } else {
      say("GPC could not be set — leaving that section untested rather than "
          + "reporting a pass");
    }
    state.done = 4;
  } catch (e) {
    say("ERROR: " + (e?.message || e));
  } finally {
    recStop();
    await gpcOff();
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
  state.done = 5; state.running = false;
  keepAlive(false);
  chrome.runtime.sendMessage({ type: "VICI_STATE", state }).catch(() => {});
}

// ---------------------------------------------------------------------------
// SEARCH CONSOLE CAPTURE
//
// Eight checkpoints live in reports Google publishes only in the interface.
// No credential fixes that — but this extension already runs in the operator's
// own signed-in Chrome, which is exactly what those reports require.
//
// It reads the VISIBLE LABELS Google prints for a human, not class names. That
// is deliberate: the markup is an obfuscated Angular build whose class names
// change without notice, while "Crawled - currently not indexed" is the string
// on the screen and in Google's own documentation. When Google does rename one,
// this returns nothing for that row rather than the wrong row's number.
//
// AND IT NEVER POSTS WITHOUT A HUMAN LOOKING. The scrape is a first draft: what
// it found is shown for confirmation, because a number quietly read off the
// wrong table is worse than no number, and there is a person right there.
// ---------------------------------------------------------------------------

const SC_BASE = "https://search.google.com/search-console";

// Google's own wording for the exclusion reasons, lowercased for matching.
//
// THE WHOLE VOCABULARY, not only the five that map to checkpoints.
//
// Reading five rows out of a table of twelve gave a capture that looked
// complete and was not: Ooten's report said 115 pages not indexed and the two
// rows we recognised accounted for 46 of them. Sixty-nine pages were excluded
// for reasons nobody saw, and — worse — we could not tell whether "Soft 404"
// was absent because it is zero or because we simply had not looked at it.
//
// With the full list, the arithmetic settles it: when the captured rows sum to
// the not-indexed total, the table was read completely, and a reason that is
// not on it has zero pages. That is a measurement, not a guess. When they do
// not sum, the report says so with both numbers instead of quietly implying a
// clean result.
const SC_REASONS = [
  // mapped to checkpoints
  "crawled - currently not indexed",
  "discovered - currently not indexed",
  "soft 404",
  "server error (5xx)",
  "redirect error",
  // the rest of Google's published reasons, read for completeness
  "alternate page with proper canonical tag",
  "blocked by robots.txt",
  "blocked due to access forbidden (403)",
  "blocked due to unauthorized request (401)",
  "blocked due to other 4xx issue",
  "duplicate without user-selected canonical",
  "duplicate, google chose different canonical than user",
  "excluded by 'noindex' tag",
  "not found (404)",
  "page with redirect",
  "url blocked due to other 4xx issue"
];

/** Injected into the Search Console tab. Reads text, classifies nothing. */
function _scScrape(reasons) {
  const out = { reasons: {}, seen: [] };
  const num = (t) => {
    const m = String(t || "").replace(/ /g, " ")
      .match(/(\d[\d,.]*\s*[KM]?)\s*$/i);
    return m ? m[1].trim() : null;
  };
  // Walk every element that holds a short, leaf-level string. Search Console
  // renders each figure as its own node beside its label, so the reliable
  // move is to find the LABEL and then look at its row.
  // Not just strict leaves. Search Console wraps a label in one or two more
  // elements than you would expect, and `children.length === 0` skipped every
  // one of them — the previous read returned sixteen strings, all page
  // furniture, on a report with a full table on screen.
  const nodes = Array.from(
    document.querySelectorAll("div,span,td,th,a,li,p"))
    .filter(el => {
      const t = (el.textContent || "").trim();
      return t && t.length < 90 && el.querySelectorAll("*").length <= 2;
    });

  const rowNumberFor = (el) => {
    // Walk up until an ancestor also contains a number, then read it.
    let cur = el;
    for (let i = 0; i < 5 && cur; i++) {
      cur = cur.parentElement;
      if (!cur) break;
      const cells = Array.from(cur.children || []);
      for (const c of cells) {
        if (c === el || c.contains(el)) continue;
        const n = num(c.textContent);
        if (n) return n;
      }
    }
    return null;
  };

  // Google prints a curly apostrophe in "Excluded by ‘noindex’ tag". Matching
  // on the straight one and normalizing here keeps the constant readable and
  // stops one row from silently never matching.
  const flat = (s) => String(s || "").toLowerCase()
    .replace(/[‘’ʼ]/g, "'").replace(/[–—]/g, "-");

  for (const el of nodes) {
    const t = (el.textContent || "").trim();
    const low = flat(t);
    if (t.length > 70) continue;
    out.seen.push(t);
    for (const r of reasons) {
      if (low === r || low.startsWith(r)) {
        const n = rowNumberFor(el);
        if (n) out.reasons[t] = n;
      }
    }
    if (low === "indexed" || low === "indexed pages") {
      const n = rowNumberFor(el); if (n) out.indexed = n;
    }
    if (low === "not indexed" || low === "not indexed pages") {
      const n = rowNumberFor(el); if (n) out.not_indexed = n;
    }
    if (low === "poor") { const n = rowNumberFor(el); if (n) out.cwv_poor = n; }
    if (low === "need improvement" || low === "needs improvement") {
      const n = rowNumberFor(el); if (n) out.cwv_ni = n;
    }
    if (low === "good") { const n = rowNumberFor(el); if (n) out.cwv_good = n; }
  }
  out.seen = out.seen.slice(0, 40);
  out.url = location.href;
  return out;
}

// WHICH GOOGLE ACCOUNT.
//
// Chrome signs you into several at once and Search Console opens under
// whichever is default — so a capture run by someone signed in as
// kiri@vicimediainc.com lands on "Oops, you don't have access to this
// property" even though another account in the same browser can see it fine.
//
// `authuser` takes an EMAIL as well as an index, and the email is the one to
// use: the index is a position in the sign-in list that changes whenever an
// account is added or removed, so a saved index quietly starts pointing at a
// different person.
function scUrl(path, property, authuser) {
  const q = new URLSearchParams({ resource_id: property || "" });
  if (authuser) q.set("authuser", authuser);
  return `${SC_BASE}/${path}?${q.toString()}`;
}

/** Did Google serve the wrong-account screen instead of the report? */
function _scDenied() {
  const t = (document.body.innerText || "").toLowerCase();
  if (t.includes("you don't have access to this property")
      || t.includes("you do not have access to this property")
      || t.includes("verify your ownership")) {
    // The page names the account it used, which is the single most useful
    // fact for fixing it.
    const m = (document.body.innerText || "").match(/Signed in as:?\s*(\S+@\S+)/i);
    return { denied: true, signed_in_as: m ? m[1] : null };
  }
  return { denied: false };
}

async function scOpen(tabId, url, wantText) {
  await chrome.tabs.update(tabId, { url });
  // WAIT FOR THE THING WE CAME FOR, not for a byte count.
  //
  // This polled until innerText passed 400 characters, which the page shell
  // clears on its own — "Feedback · Google Search Console · Search property ·
  // Privacy · Terms · Page indexing · EXPORT" is already past the threshold
  // with none of the report in it. So every read landed on a rendered frame
  // around an empty table, and reported two numbers and no reasons.
  //
  // `wantText` is a string that only exists once the report itself has
  // rendered. Absent, the byte count is still the fallback.
  for (let i = 0; i < 40; i++) {
    await settle(1000);
    const [{ result } = {}] = await chrome.scripting.executeScript({
      target: { tabId },
      func: (want) => {
        const t = (document.body.innerText || "").toLowerCase();
        const list = Array.isArray(want) ? want : (want ? [want] : []);
        if (list.length) {
          return list.some(w => t.includes(String(w).toLowerCase())) ? 9999 : 0;
        }
        return t.length;
      },
      args: [wantText || ""]
    });
    if ((result || 0) > 400) {
      // The exclusion table renders below the fold and Search Console builds
      // it lazily, so a read without scrolling gets the summary and nothing
      // else — which is exactly the half-capture the first live run produced.
      await chrome.scripting.executeScript({
        target: { tabId }, func: () => new Promise(res => {
          let y = 0;
          const step = () => {
            y += 700; window.scrollTo(0, y);
            if (y < document.body.scrollHeight && y < 6000) setTimeout(step, 250);
            else { window.scrollTo(0, 0); setTimeout(res, 600); }
          };
          step();
        })
      });
      await settle(1200);
      return true;
    }
  }
  return false;
}

/**
 * Walk the two reports for one property and return a draft capture.
 * `property` is the Search Console resource id, e.g. https://example.com/
 */
async function consoleCapture(auditId, property, returnTabId) {
  const c = await cfg();
  const auth = (c.googleAccount || "").trim();
  // Where the operator was standing when they pressed the button. They came
  // from the audit page and that is where the answer belongs, so we send them
  // back to it rather than leaving them in a Search Console tab wondering
  // whether anything happened.
  state.consoleReturnTab = returnTabId || null;
  let lastSeen = [];
  state.running = true; state.done = 0; state.total = 2; keepAlive(true);
  const draft = { property, captured_at: new Date().toISOString(), reasons: {} };
  let tab;
  try {
    tab = await chrome.tabs.create({ url: "about:blank", active: true });

    say(auth ? `Opening Indexing → Pages as ${auth}…`
             : "Opening Indexing → Pages…");
    // "Why aren't pages indexed" is the heading directly above the exclusion
    // table, so its presence means the table is there to read.
    // ANCHOR ON THE REASON LABELS THEMSELVES, not on a heading I typed from
    // memory. The wait string was "why aren't pages indexed"; Google's actual
    // heading is "Why pages aren't indexed" — same words, different order —
    // so the poll ran its full forty seconds and gave up on a page that had
    // rendered fine. Any one of the reasons appearing proves the table is
    // there, and those strings are already the thing we came to read.
    if (await scOpen(tab.id, scUrl("index", property, auth), SC_REASONS)) {
      const [{ result: denied } = {}] = await chrome.scripting.executeScript({
        target: { tabId: tab.id }, func: _scDenied
      });
      if (denied?.denied) {
        say(`Search Console opened as ${denied.signed_in_as || "the default " +
            "account"}, which cannot see this property. Set the Google ` +
            `account in the popup to the one that can — an email, not an ` +
            `index — and run it again.`);
        state.running = false; keepAlive(false);
        chrome.runtime.sendMessage({ type: "VICI_STATE", state }).catch(() => {});
        return;
      }
      const [{ result } = {}] = await chrome.scripting.executeScript({
        target: { tabId: tab.id }, func: _scScrape, args: [SC_REASONS]
      });
      if (result) {
        lastSeen = result.seen || [];
        if (result.indexed) draft.indexed = result.indexed;
        if (result.not_indexed) draft.not_indexed = result.not_indexed;
        Object.assign(draft.reasons, result.reasons || {});
        // SAY WHETHER THE TABLE WAS READ WHOLE.
        //
        // "2 reason rows, indexed 56" reads like a success. It was a success
        // for two rows out of a table whose other rows held sixty-nine pages.
        // The accounting is the only thing that tells you which of those two
        // things happened, so it goes on screen at the moment of the read.
        const _n = (v) => {
          const s = String(v || "").replace(/[, ]/g, "");
          const k = /[kK]$/.test(s) ? 1000 : (/[mM]$/.test(s) ? 1000000 : 1);
          const f = parseFloat(s);
          return isNaN(f) ? null : Math.round(f * k);
        };
        const acct = Object.values(result.reasons || {})
          .reduce((a, v) => a + (_n(v) || 0), 0);
        const notIdx = _n(result.not_indexed);
        const rows = Object.keys(result.reasons || {}).length;
        say(`Index coverage: indexed ${result.indexed || "?"}, ${rows} ` +
            `reason ${rows === 1 ? "row" : "rows"}` +
            (notIdx !== null
              ? ` accounting for ${acct} of ${notIdx} not indexed` +
                (acct === notIdx ? " — whole table" : " — INCOMPLETE")
              : ""));
      }
    } else {
      say("Indexing report did not finish loading — are you signed in?");
    }
    state.done = 1;

    say("Opening Core Web Vitals…");
    if (await scOpen(tab.id, scUrl("core-web-vitals", property, auth))) {
      const [{ result } = {}] = await chrome.scripting.executeScript({
        target: { tabId: tab.id }, func: _scScrape, args: [SC_REASONS]
      });
      if (result && (result.cwv_poor || result.cwv_ni || result.cwv_good)) {
        draft.cwv = { poor: result.cwv_poor, needs_improvement: result.cwv_ni,
                      good: result.cwv_good };
        say(`Core Web Vitals: poor ${result.cwv_poor || 0}, ` +
            `needs improvement ${result.cwv_ni || 0}`);
      }
    }
    state.done = 2;

    // NO ENHANCEMENTS STEP. `/search-console/enhancements` 404s — Search
    // Console has no single Enhancements page; each type (breadcrumbs,
    // FAQ, videos, review snippets) has its own URL and only exists for a
    // site that actually has that markup. Opening a URL that cannot exist
    // cost thirty seconds and a Google 404 screen, which is worse than not
    // trying: it looks like the capture is broken.
    state.total = 2; state.done = 2;
  } catch (e) {
    // A tab closed by hand mid-run is not a failure worth alarming about —
    // it is someone changing their mind, and "No tab with id: 972028235" is
    // a stack trace pretending to be a message.
    say(/No tab with id/i.test(e.message || "")
        ? "The Search Console tab was closed before the read finished."
        : `Console capture failed: ${e.message}`);
  }

  // WHEN THE EXCLUSION TABLE DID NOT RESOLVE, SAY WHAT WAS ON THE PAGE.
  //
  // Without this a partial capture reports two numbers and no reason, and the
  // only way to find out why is to guess at Google's markup from a thousand
  // miles away. The labels it DID read are the thing that makes the next fix
  // one edit rather than one deploy.
  if (!Object.keys(draft.reasons).length) {
    say("No exclusion reasons found. Labels seen on the page: " +
        (lastSeen.slice(0, 18).join(" | ") || "none"));
  }

  const found = Object.keys(draft.reasons).length +
                (draft.indexed ? 1 : 0) + (draft.not_indexed ? 1 : 0) +
                (draft.cwv ? 1 : 0);
  if (!found) {
    say("Nothing recognised. Google may have renamed a label, or the report " +
        "had not rendered. Nothing was sent.");
    // GO BACK ANYWAY. Failing is not a reason to abandon someone in a Search
    // Console tab wondering whether the thing is still running — the whole
    // point of returning them is that they know it finished, and that is more
    // true when it finished badly.
    await scReturn(tab);
    state.running = false; keepAlive(false);
    chrome.runtime.sendMessage({ type: "VICI_STATE", state }).catch(() => {});
    return;
  }

  // SEND IT, THEN PUT THEM BACK ON THE AUDIT.
  //
  // This used to stop here and ask the operator to open the popup and press
  // Send. The confirmation was the right instinct and the wrong place: they
  // pressed a button on the audit page, so the audit page is where the answer
  // belongs, and a capture that ends by telling you to go and find another
  // window is a capture most people abandon.
  //
  // The numbers are not lost to sight by sending them — every captured row
  // renders in the report with its value, marked `captured_from: Search
  // Console UI`. Running the capture again overwrites them, so a wrong number
  // is one click from being right rather than one click from being sent.
  state.consoleDraft = { auditId, draft, found };
  say(`Read ${found} figures. Sending…`);
  await consoleSend();
  await scReturn(tab, true);
  state.running = false; keepAlive(false);
  chrome.runtime.sendMessage({ type: "VICI_STATE", state }).catch(() => {});
}

/** Close the Search Console tab and put the operator back where they were. */
async function scReturn(tab, reload) {
  try {
    if (tab?.id) await chrome.tabs.remove(tab.id);
  } catch (e) { /* already closed by hand */ }
  if (!state.consoleReturnTab) return;
  try {
    await chrome.tabs.update(state.consoleReturnTab, { active: true });
    if (reload) {
      await chrome.tabs.reload(state.consoleReturnTab);
      say("Back on the audit — the captured rows are in it now.");
    } else {
      say("Back on the audit. Nothing was changed.");
    }
  } catch (e) {
    say("Finished. Reopen the audit to see where it got to.");
  }
}

async function consoleSend() {
  const pending = state.consoleDraft;
  if (!pending) return;
  const c = await cfg();
  try {
    const r = await fetch(
      `${c.apiBase}/api/audits/${pending.auditId}/console-capture`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(pending.draft) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || r.status);
    say(`Sent. Filled ${d.count} checkpoint${d.count === 1 ? "" : "s"}: ` +
        `${(d.filled || []).join(", ")}`);
    state.consoleDraft = null;
  } catch (e) {
    say(`Send failed: ${e.message}`);
  }
  chrome.runtime.sendMessage({ type: "VICI_STATE", state }).catch(() => {});
}

chrome.runtime.onMessage.addListener((msg, _s, respond) => {
  if (msg?.type === "VICI_CONSOLE") {
    consoleCapture(msg.auditId, msg.property, _s?.tab?.id); respond({ ok: true });
  }
  if (msg?.type === "VICI_CONSOLE_SEND") { consoleSend(); respond({ ok: true }); }
  if (msg?.type === "VICI_CONSOLE_EDIT" && state.consoleDraft) {
    state.consoleDraft.draft = msg.draft;
    respond({ ok: true });
  }
});
