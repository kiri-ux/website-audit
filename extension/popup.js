// apiBase and token are gone from the UI. The API is one fixed deployment, and
// partner mode is not in use — two fields that were never changed and always
// had to be filled in.
const F = ["auditId", "maxPages", "dwellMs"];
const $ = id => document.getElementById(id);

chrome.storage.local.get(null).then(s => F.forEach(k => { if (s[k] != null) $(k).value = s[k]; }));
F.forEach(k => $(k).addEventListener("change", () => {
  const v = ["maxPages", "dwellMs"].includes(k) ? parseInt($(k).value, 10) : $(k).value.trim();
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

chrome.runtime.onMessage.addListener(m => { if (m?.type === "VICI_STATE") render(m.state); });
chrome.runtime.sendMessage({ type: "VICI_GET_STATE" }).then(r => render(r?.state));
setInterval(() => chrome.runtime.sendMessage({ type: "VICI_GET_STATE" })
  .then(r => render(r?.state)).catch(() => {}), 1000);
