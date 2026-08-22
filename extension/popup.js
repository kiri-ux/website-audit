// apiBase and token are gone from the UI. The API is one fixed deployment, and
// partner mode is not in use — two fields that were never changed and always
// had to be filled in.
const F = ["auditId", "maxPages", "dwellMs", "googleAccount"];
const $ = id => document.getElementById(id);

chrome.storage.local.get(null).then(s => F.forEach(k => { if (s[k] != null) $(k).value = s[k]; }));

// READ THE AUDIT ID OFF THE TAB YOU ARE LOOKING AT.
//
// "Paste the audit id" was asking someone to copy a sixteen-character hex
// string out of the URL bar of the tab next door. If that tab IS an audit
// page, the id is right there — and the report and PDF URLs are the two
// shapes it appears in.
(async () => {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const m = (tab?.url || "").match(/\/audits\/([0-9a-f]{8,})(?:\.pdf)?(?:[?#]|$)/i);
    if (!m) return;
    // Never overwrite something already typed — a pasted id beats a guess.
    if ($("auditId").value.trim()) return;
    $("auditId").value = m[1];
    chrome.storage.local.set({ auditId: m[1] });
    const hint = document.getElementById("idhint");
    if (hint) hint.textContent = "filled in from the audit page in this tab";
  } catch (e) { /* a tab we cannot read is not an error worth showing */ }
})();
F.forEach(k => $(k).addEventListener("change", () => {
  const v = ["maxPages", "dwellMs"].includes(k)
    ? parseInt($(k).value, 10) : $(k).value.trim();
  chrome.storage.local.set({ [k]: v });
}));

function render(st) {
  if (!st) return;
  $("bar").style.width = st.total ? `${100 * st.done / st.total}%` : "0";
  $("status").textContent = st.running
    ? `capturing ${st.done}/${st.total}…`
    : (st.pages?.length ? `finished — ${st.pages.length} pages captured` : "idle");
  $("go").textContent = st.running ? "Stop" : "Start capture";
  $("go").className = st.running ? "stop" : "";
  $("log").textContent = (st.log || []).join("\n");
  renderDraft(st);
}

$("go").addEventListener("click", async () => {
  const { state } = await chrome.runtime.sendMessage({ type: "VICI_GET_STATE" });
  if (state?.running) { chrome.runtime.sendMessage({ type: "VICI_STOP" }); return; }
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url?.startsWith("http")) { $("status").textContent = "open the client site first"; return; }
  if (!$("auditId").value.trim()) {
    $("status").textContent = "paste an audit id, or start from the audit page";
    return;
  }
  await chrome.storage.local.set({
    auditId: $("auditId").value.trim(),
    maxPages: parseInt($("maxPages").value, 10) || 30,
    dwellMs: parseInt($("dwellMs").value, 10) || 2500 });
  chrome.runtime.sendMessage({ type: "VICI_START", url: tab.url });
});

// Consent capture is a DIFFERENT job from the crawl capture: one page, watched
// closely, rather than many pages read once. Same settings, same upload target,
// separate button — because doing both from one button would mean guessing
// which one the operator meant.
$("consent").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url || !/^https?:/.test(tab.url)) {
    alert("Open the site you want to check in this tab first.");
    return;
  }
  chrome.runtime.sendMessage({ type: "VICI_CONSENT", url: tab.url });
});

chrome.runtime.onMessage.addListener(m => { if (m?.type === "VICI_STATE") render(m.state); });
chrome.runtime.sendMessage({ type: "VICI_GET_STATE" }).then(r => render(r?.state));
setInterval(() => chrome.runtime.sendMessage({ type: "VICI_GET_STATE" })
  .then(r => render(r?.state)).catch(() => {}), 1000);

// ---- Search Console capture ------------------------------------------------
$("console").addEventListener("click", async () => {
  const id = $("auditId").value.trim();
  if (!id) { $("status").textContent = "paste an audit id first"; return; }
  const prop = prompt(
    "Search Console property to read.\n\n" +
    "Copy it exactly as Search Console shows it — usually the site URL with " +
    "the trailing slash, or sc-domain:example.com for a domain property.",
    "https://");
  if (!prop) return;
  $("status").textContent = "opening Search Console…";
  chrome.runtime.sendMessage({ type: "VICI_CONSOLE", auditId: id, property: prop });
});

// The draft is rendered as EDITABLE fields, not a read-only summary. If the
// scrape put a number in the wrong row the fix is right there, which is the
// difference between a tool someone trusts and one they stop using the first
// time it is wrong.
const DRAFT_LABELS = {
  indexed: "Indexed pages",
  not_indexed: "Not indexed",
  cwv_poor: "CWV — Poor",
  cwv_ni: "CWV — Needs improvement"
};

function renderDraft(st) {
  const box = $("draft");
  const d = st?.consoleDraft;
  if (!d) { box.style.display = "none"; return; }
  box.style.display = "block";
  const rows = [];
  const add = (key, label, val) =>
    rows.push(`<label>${label}</label>` +
      `<input data-k="${key}" value="${(val ?? "").toString()
        .replace(/"/g, "&quot;")}">`);
  add("indexed", DRAFT_LABELS.indexed, d.draft.indexed);
  add("not_indexed", DRAFT_LABELS.not_indexed, d.draft.not_indexed);
  Object.keys(d.draft.reasons || {}).forEach(k =>
    add(`reasons.${k}`, k, d.draft.reasons[k]));
  if (d.draft.cwv) {
    add("cwv.poor", DRAFT_LABELS.cwv_poor, d.draft.cwv.poor);
    add("cwv.needs_improvement", DRAFT_LABELS.cwv_ni,
        d.draft.cwv.needs_improvement);
  }
  $("draftrows").innerHTML = rows.join("");
}

function collectDraft(st) {
  const d = JSON.parse(JSON.stringify(st.consoleDraft.draft));
  document.querySelectorAll("#draftrows input").forEach(el => {
    const k = el.dataset.k, v = el.value.trim();
    if (k.startsWith("reasons.")) {
      if (v) d.reasons[k.slice(8)] = v; else delete d.reasons[k.slice(8)];
    } else if (k.startsWith("cwv.")) {
      d.cwv = d.cwv || {}; d.cwv[k.slice(4)] = v || null;
    } else if (v) { d[k] = v; } else { delete d[k]; }
  });
  return d;
}

$("send").addEventListener("click", async () => {
  const { state } = await chrome.runtime.sendMessage({ type: "VICI_GET_STATE" });
  if (!state?.consoleDraft) return;
  await chrome.runtime.sendMessage({
    type: "VICI_CONSOLE_EDIT", draft: collectDraft(state) });
  chrome.runtime.sendMessage({ type: "VICI_CONSOLE_SEND" });
  $("draft").style.display = "none";
});

$("discard").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ type: "VICI_CONSOLE_EDIT", draft: {} });
  $("draft").style.display = "none";
});
