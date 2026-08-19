# Changed files — build 2026.08.19-08

**Cumulative since 2026.08.18-16.** Apply and you are current whatever you last
uploaded.

## This build

| File | Why |
|---|---|
| `engine/scoring.py` | **N/A rows no longer count against section coverage.** "Need Access" still does — the check applies and we couldn't see it. "N/A" doesn't — it doesn't apply. Without this, Off-Page could never score even with DataForSEO working |
| `engine/collectors/dataforseo.py` | OFF-21..29 (link prospecting) marked N/A — campaign work, not audit measurement. Plus 5 more rows mapped from the summary payload we already pay for |
| `app/brand.py` | **New.** Favicon owned in code; `<link>` uses an inline data URI so it cannot go missing |
| `app/api.py`, `app/ui.py`, `engine/report.py` | Use the inlined brand tags |
| `app/version.py` | 2026.08.19-08 |

## Verified before sending

- Renamed `static/` away entirely and confirmed the icon still renders from the
  embedded fallback — the exact failure mode you hit.
- Simulated a post-credentials audit: E-E-A-T 24/24, AI Search 22/30, Off-Page
  13/20 assessable, Analytics 6/6 — all four now score instead of reading
  "Not Assessed".
- Unpacked over a clean tree; `import app.api, app.worker` succeeds.
- 14 suites green.
