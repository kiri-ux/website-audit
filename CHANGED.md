# Changed files — build 2026.08.19-07

**Cumulative since 2026.08.18-16.** Apply and you are current whatever you last
uploaded. `NEXT.md` has the checklist.

## This build

| File | Why |
|---|---|
| `engine/checks/tagdetect.py` | Paid-media pixels (Meta, LinkedIn, Google Ads) are detected and reported but **never** scored as defects — different team, often a different agency |
| `app/ui.py` | Paid-channels checkbox removed from the form |
| `app/api.py`, `app/worker.py` | `channels` intake removed |
| `engine/summarise.py` | `roadmap_item()` normalizes every plan bullet to one shape; duplicates collapsed; phase captions reworded; "Top issue"; no date; "workstream" → "optimization" |
| `engine/context.py` | Self-description no longer repeats the brand name |
| `engine/glossary.py` | Lazy loading defined |
| `engine/pdf_report.py` | Phase captions centered; no ghost meter on unassessed rows |
| `tests/test_voice.py` | Asserts ad pixels are never defects |

## Verified before sending

- Unpacked over a clean tree; `import app.api, app.worker` succeeds.
- Roadmap rendered and read: all bullets are noun-phrase defects, no duplicates.
- Every glossary glyph verified present in the embedded font.
- 10 suites green.
