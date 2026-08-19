# Build 2026.08.19-07

## Check after deploying

- [ ] Header reads **build 2026.08.19-07**.
- [ ] Re-run Junk Bee Gone (findings are stored, so this needs a fresh run).
- [ ] **No Google Ads / Meta / LinkedIn rows anywhere in Top Findings or the
      plan.** They now read N/A — *"Not detected. Paid media tracking — outside
      the scope of this audit."*
- [ ] The paid-channels checkbox is gone from the new-audit form.
- [ ] Executive summary: no date, no "not counted against you", and the
      description no longer repeats the brand name twice in one sentence.
- [ ] Pull quote reads **"Top issue: …"**.
- [ ] Recommended Plan bullets are all the same shape — "Duplicate title tags",
      "Missing image alt attributes", "Broken internal links". Phase captions are
      centered.
- [ ] A lazy-loading definition bubble appears where that finding is discussed.

## Coverage still showing "Not Assessed"

Four sections need credentials, not code:

| Section | What's needed |
|---|---|
| E-E-A-T (9/24) | `ANTHROPIC_API_KEY` on the worker — the judgment layer answers the other 15 |
| AI Search (8/22) | `ANTHROPIC_API_KEY`, plus per-platform keys (`OPENAI_API_KEY`, `PERPLEXITY_API_KEY`, `GEMINI_API_KEY`) for the visibility monitor |
| Off-Page (0/29) | `DFS_LOGIN` + `DFS_PASSWORD` |
| Search Console / GA4 | A Vici login added to the client's property, plus `GOOGLE_TOKENS` |

A section stays "Not Assessed" below 50% coverage on purpose — a score built
from a third of its checks is worse than no score.

## Up next

- **Real DataForSEO run.** Two env vars, then send me the rankings table.
- **Feed the paid data into the judgment layer.** Blocked on the above by choice.
