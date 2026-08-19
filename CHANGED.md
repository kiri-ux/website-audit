# Changed files — build 2026.08.19-02

**Cumulative since 2026.08.18-16.** This replaces the two earlier partial deltas
(`-01` and `-02`) — apply this one and you are current regardless of which of
those you did or didn't upload.

The previous `-02` delta was built against `-01` rather than against what was
actually deployed, so it shipped a `pdf_report.py` that imports `DefBadge` from
a `charts.py` that was never uploaded. That is the ImportError you saw.

## Files (14)

| File | Why |
|---|---|
| `engine/charts.py` | `DefBadge` — the ⓘ marker (**this is the missing import**) |
| `engine/pdf_report.py` | Pills, visual roadmap, scope-not-instructions, US dates, no build in footer, AI Search naming |
| `engine/summarise.py` | `SERVICE_ACTION` scope lines; plain-language summary |
| `engine/report.py` | PDF opens in a new tab; AI Search naming |
| `engine/glossary.py` | Term renamed to "AI Search (GEO)" |
| `engine/context.py` | *(unchanged since -16, not included)* |
| `engine/crawler.py` | `artifact_from_json()` — lets the report improve without re-crawling |
| `engine/judgment.py` | US spelling in the prompts |
| `engine/checks/tagdetect.py` | Channel-aware pixel checks; one-line N/A notes |
| `app/api.py` | Intake fields; context rebuilt at render time |
| `app/worker.py` | Passes `channels` into the check context |
| `app/version.py` | Build id → 2026.08.19-02 |
| `Dockerfile` | Installs `fonts-dejavu-core` |
| `tests/test_voice.py`, `tests/test_glossary.py` | Kept in step |

## Verified before sending

- Unpacked over a clean tree; `import app.api, app.worker` succeeds (the same
  check your Docker build runs at line 37).
- Seven suites green against the merged result.
- Import-closure check: no changed file imports a symbol from another changed
  file that was left out of the zip.
