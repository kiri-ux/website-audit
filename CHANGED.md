# Changed files — build 2026.08.19-10

**Cumulative since 2026.08.18-16.** Apply and you are current whatever you last
uploaded.

## This build

| File | Why |
|---|---|
| `app/api.py`, `app/ui.py` | **Re-run** — form + JSON endpoints, buttons on the card and on every earlier run. Creates a NEW audit rather than re-queuing the row, so the "before" survives |
| `engine/summarise.py` | Plan items are verb-led work: "Rewrite duplicate page titles", not "Duplicate title tags". Several checkpoints map to one action so near-duplicates collapse |
| `engine/charts.py` | Score + rating auto-fits its column. "70 Needs Improvement" is twice the width of "100 Strong" and was running back over the bar |
| `engine/checks/tagdetect.py` | Undetected ad pixels read "Not detected." — no scope commentary |
| `engine/collectors/dataforseo.py` | Prospecting rows read "Not measured." |
| `engine/pdf_report.py` | Priority Issues column header no longer promises a recommendation the client PDF does not carry |
| `tests/test_manage.py` | Re-run coverage |

## Verified before sending

- Measured every value label against the bar's right edge: the tightest case
  ("70 Needs Improvement") now clears it by 28pt.
- Unpacked over a clean tree; `import app.api, app.worker` succeeds.
- 14 suites green.
