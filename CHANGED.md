# Changed files — build 2026.08.19-05

**Cumulative since 2026.08.18-16.** Apply this and you are current regardless of
which earlier deltas you did or didn't upload. `NEXT.md` has the post-deploy
checklist.

## New

| File | What it is |
|---|---|
| `static/favicon.svg` | Vici-styled favicon — Atlas Blue field, gold gauge |
| `static/apple-touch-icon.png` | 180px version for iOS home screen / bookmarks |
| `engine/screenshots.py` | Annotated evidence screenshots (Playwright, already in the image) |
| `NEXT.md` | Post-deploy checklist and pending list |
| `tests/test_manage.py` | Delete and client-grouping tests |

## Modified

| File | Why |
|---|---|
| `app/api.py` | Icon routes; AI visibility at render time; screenshot blobs for the PDF; delete + prune; intake fields |
| `app/ui.py`, `engine/report.py` | Icon `<link>` tags; dashboard grouped by client; delete/prune; PDF opens in a new tab |
| `app/worker.py` | Captures up to 3 evidence shots after the audit completes |
| `app/db.py` | `delete_audit()`, `group_by_client()`, `latest_ai_run_for_audit()` |
| `app/artifacts.py` | `delete_artifacts()` |
| `engine/pdf_report.py` | AI Search Visibility page, evidence section, pills, visual roadmap, scope-not-instructions, US dates |
| `engine/summarise.py` | `SERVICE_ACTION` scope lines |
| `engine/crawler.py` | `artifact_from_json()` |
| `engine/charts.py` | `DefBadge` |
| `engine/checks/tagdetect.py` | Channel-aware pixel checks |
| `engine/glossary.py`, `engine/judgment.py` | AI Search naming; US spelling |
| `Dockerfile` | `fonts-dejavu-core` |
| `render.yaml`, `DEPLOY.md` | `SKIP_SCREENSHOTS` documented |
| `tests/test_routes.py` etc. | Icons, delete, voice rules |

`.dockerignore` does not exclude `static/`, so the icons ship with `COPY . .` —
no Dockerfile change needed.

## Verified before sending

- Unpacked over a clean tree; `import app.api, app.worker` succeeds.
- Icons fetched over HTTP: 200, correct content types, linked from both the
  dashboard and the report page.
- 10 suites green.
