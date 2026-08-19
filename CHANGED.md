# Changed files — build 2026.08.19-03

**Cumulative since 2026.08.18-16**, which is the last build I know reached your
repo. Apply this and you are current no matter which earlier deltas you did or
didn't upload. See `NEXT.md` for what to check after deploying and what's still
pending.

## New files

| File | What it is |
|---|---|
| `NEXT.md` | Post-deploy checklist and the pending list |
| `tests/test_manage.py` | Delete and client-grouping tests |

## Modified

| File | Why |
|---|---|
| `app/ui.py` | Dashboard grouped by client; delete + prune buttons; intake fields on the form |
| `app/db.py` | `delete_audit()`, `client_key()`, `group_by_client()` |
| `app/artifacts.py` | `delete_artifacts()` — clears blobs for a deleted audit |
| `app/api.py` | DELETE endpoint, form-post delete, client prune; intake fields; context rebuilt at render time |
| `app/worker.py` | Passes `channels` into the check context |
| `app/version.py` | Build id → 2026.08.19-03 |
| `engine/charts.py` | `DefBadge` — the ⓘ marker, drawn as vector |
| `engine/pdf_report.py` | Pills, visual roadmap, scope-not-instructions, US dates, no build in footer, AI Search naming |
| `engine/summarise.py` | `SERVICE_ACTION` scope lines; plain-language summary |
| `engine/report.py` | PDF opens in a new tab; AI Search naming |
| `engine/glossary.py` | Term renamed to "AI Search (GEO)" |
| `engine/context.py` | *(unchanged since -16; not included)* |
| `engine/crawler.py` | `artifact_from_json()` — report improvements without re-crawling |
| `engine/judgment.py` | US spelling in the prompts |
| `engine/checks/tagdetect.py` | Channel-aware pixel checks; one-line N/A notes |
| `Dockerfile` | Installs `fonts-dejavu-core` |
| `tests/test_voice.py`, `tests/test_glossary.py` | Kept in step |

## Verified before sending

- Unpacked over a clean tree; `import app.api, app.worker` succeeds — the same
  check your Docker build runs.
- Import-closure check: nothing in here imports a symbol from a changed file
  that was left out of the zip (the mistake that broke the last deploy).
- 14 suites green.
