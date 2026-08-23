# 2026.08.20-59

**Do**

- Upload the zip. The worker reaps the stuck audit when it boots.
- Start a fresh scan once Render says live.

**Check**

- "In flight" goes to 0, "stalled" shows 1 briefly, then the old run reads
  failed with a message about the process going away.
- During a run the progress line moves: "Search Console: inspecting URL 7 of 25".
- Ours to fix: empty.
- "Full consent scan" link at the top of the report.

**Pending**

- Pick a word to replace "Pass" (Met? OK?).
- Watch worker memory. If runs keep dying ~70s in with no error, the 2GB
  instance is the suspect, not the code.
- Parity: gtm_api.py (large) → product pixel checkpoints → remediation layer
  → client share link → run history → batch + CSV + alerts.
