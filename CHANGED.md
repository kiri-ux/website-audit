# Changed files — build 2026.08.18-16

Delta against **build 2026.08.18-14** (the one that was live when the PDF link
returned `{"detail":"audit not found"}`). Everything from build -15 is included
too, so it applies cleanly whether or not you uploaded that one.

Drop these over the repo, keeping the folder structure. Nothing else changed.

## New files

| File | What it is |
|---|---|
| `engine/glossary.py` | The 14 plain-English definitions, with an emoji for HTML and a PDF-safe glyph for print |
| `VOICE.md` | The writing rules, derived from your AdLib Confluence pages |
| `tests/test_routes.py` | Fetches the URLs a browser actually requests — this is what would have caught the PDF bug |
| `tests/test_glossary.py` | Every icon is checked against the embedded font so none render as black boxes |
| `tests/test_voice.py` | Spelling, direct address, no duplicate findings, no marketing filler |

## Modified

| File | Why |
|---|---|
| `app/api.py` | **The PDF fix.** `/audits/{id}.pdf` is now registered before `/audits/{id}`, which was swallowing the `.pdf` suffix |
| `app/version.py` | Build id → `2026.08.18-16` |
| `engine/pdf_report.py` | Definition bubbles beside each finding, "Top Findings", US spelling, copy rewritten to the voice guide |
| `engine/report.py` | Same bubbles and headings in the HTML report |
| `engine/summarise.py` | Plain-language summary, US spelling, "the checks we could run" instead of "assessed checkpoints" |
| `engine/context.py` | Quotes the site's own words instead of inferring a business from URL slugs |
| `engine/charts.py` | US spelling in labels and comments |
| `engine/judgment.py` | US spelling in the prompts |
| `render.yaml`, `DEPLOY.md` | Analyst/authorship env vars (unchanged since -14 — included only so you don't have to check) |

## Not included

Regenerated artifacts, safe to leave stale: `sample_audit_report.pdf`,
`docs/pdf_p1.png`, `docs/pdf_p2.png`.

## After deploying

Confirm the header reads **build 2026.08.18-16** before trusting a run, then
open a finished report and click through to the PDF — that link was dead on -14.
