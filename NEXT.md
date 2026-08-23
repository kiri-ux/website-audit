# 2026.08.20-56

**Do**

- Upload the zip, wait for Render.
- Run a scan. Tick "Reuse the last crawl", "Ask the AI assistants", "Consent & privacy".
- Run the capture on that new audit. (Scan first — each scan makes a new audit.)
- Reload the extension at chrome://extensions.

**Check**

- New "Full consent scan" link at the top of the report, next to the PDF buttons.
- That page shows: CMP evidence, GTM container, Consent Mode, every tracker
  with the page it fired on, products bought vs firing, TN state checks.
- Empty sections say why they're empty, not just blank.
- Ours to fix: 0 or 1 items.
- GSC-09, 10, 11 have numbers.

**Pending**

- Pick a word to replace "Pass" (Met? OK?).
- Parity: gtm_api.py (large) → product pixel checkpoints → remediation layer
  → client share link → run history → batch + CSV + alerts.
