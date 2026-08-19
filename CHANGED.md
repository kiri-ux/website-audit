# Changed files — build 2026.08.19-13

**Cumulative since 2026.08.18-16.** Apply and you are current whatever you last
uploaded.

## Why E-E-A-T and AI Search were blank

Not a rendering problem. The worker never got the key:

```
EEAT-01  Need Access  Not assessed — no LLM credentials configured for the judgment layer.
OFF-01   Need Access  No backlink data provider is configured.
```

`ANTHROPIC_API_KEY`, `DFS_LOGIN` and `DFS_PASSWORD` have to be on
**vici-audit-worker**. The API never runs a collector. With the judgment layer
running, E-E-A-T goes 9/24 → 24/24 and AI Search 8/22 → 22/22, which is what
clears the 50% coverage gate those two sections are failing.

Both now say so in the log rather than degrading silently:

```
[worker] <id> judgment layer answered 29/29 E-E-A-T and AI Search rows
[worker] <id> judgment layer produced NOTHING — ANTHROPIC_API_KEY is not set ON THE WORKER
[worker] <id> DataForSEO rankings OK — 412 keywords, 37 in the top 10
[worker] <id> DataForSEO SKIPPED — DFS_LOGIN / DFS_PASSWORD are not set ON THE WORKER
```

## "Only Search Console and GA4 need client access, right?"

Right — and the report was saying otherwise on every run:

> 161 checks need access to accounts only you control — mostly Search Console
> and Analytics.

38 of those were the client's. The rest were our unset vendor keys and 58
checkpoints with no automation at all, all filed as the client's homework.

`engine/access.py` splits every unmeasured checkpoint three ways:

| Bucket | Junk Bee Gone | Meaning |
|---|---|---|
| `client` | **38** | Search Console + GA4. The only real ask |
| `vendor` | 68 | Our keys — backlinks, judgment layer, Lighthouse |
| `manual` | ~55 | No automation exists; reviewed by hand |

The coverage strip is now **Measured / Need your access / We complete these /
Not applicable**, and the methodology page splits "What we need from you" from
"What we complete during the engagement".

## The 58 checkpoints nobody could see

The appendix is headed "the full record, by area" and was omitting every
checkpoint that returned no finding — 58 of them — while still counting them in
the coverage chart. Charged for, then not named. They now appear with a
**Manual** pill, and section totals read against the template (`Technical SEO
26/38`, not `26/26`). The scoring gate is deliberately unchanged, so no section
newly drops to Not Assessed.

## Files

| File | Why |
|---|---|
| `engine/access.py` | **New.** One rule for who a missing checkpoint is blocked on |
| `engine/pdf_report.py` | Four-way coverage; split methodology copy; Manual pill; appendix names unautomated rows |
| `engine/summarise.py` | Exec summary quotes the client bucket, on the same denominator as the chart above it. It previously printed a different number for the same fact |
| `engine/scoring.py` | Section totals count the template's rows, not ours |
| `engine/charts.py` | Coverage gets a fourth segment. Gauge rating is fitted to the arc's opening — "Needs Improvement" was drawn struck through by the arc; "Strong" fit, which is how it passed review |
| `app/worker.py` | Judgment layer and DataForSEO both report what happened |
| `static/favicon.svg`, `app/brand.py`, `app/ui.py` | Favicon — see below |
| `tests/test_charts.py` | Bucketing, four-way coverage, every rating band fits the arc |
| `tests/test_routes.py` | The served favicon must parse as XML |

## Favicon (carried from -11)

`static/favicon.svg` was not well-formed XML — `aria-label="Vici SEO & AI
Search Audit"`. A bare `&` in an attribute is a parse error, SVG is parsed
strictly, so all three delivery routes served a file no browser would render.
Every test asserted the response contained `<svg`, which it did.

## Verified before sending

- Re-rendered the cover at 150dpi and looked at it: the four-segment legend
  wraps cleanly, the rating clears the arc.
- Reconciled against the real Junk Bee Gone run: 145 measured, 38 client, 68
  vendor, 55 manual, 7 N/A = 313.
- 14 suites green; `import app.api, app.worker` on a clean merged tree.

## What to check on this build

- Header chip reads **2026.08.19-13**.
- Worker env tab: `ANTHROPIC_API_KEY`, `DFS_LOGIN`, `DFS_PASSWORD`.
- Re-run Junk Bee Gone, then read the worker log for the four lines above.
- Cover page: "Need your access **38**", not 161.
