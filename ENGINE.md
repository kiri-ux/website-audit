# Vici SEO/GEO Audit Tool — Phase 1 Prototype

Working implementation of Phase 1 from the build spec. Crawls a site once and
auto-fills **159 of the 313** audit checkpoints with zero paid API dependencies.

## Quick start

```bash
pip install requests beautifulsoup4 lxml playwright --break-system-packages
python3 run_audit.py https://www.grandhf.com/ \
        --vertical ecommerce \
        --client "Grand Furniture" \
        --max-pages 150
```

Outputs to `out/`:

| File | Contents |
|---|---|
| `audit_report.html` | Client-facing report — scores, priority issues, all findings |
| `findings.json` | The findings store. **This is the actual product** — the report is one renderer over it |
| `crawl_artifact.json` | Raw crawl data, so checks can be re-run without re-crawling |

### Useful flags

```
--max-pages N      crawl budget (default 150)
--max-depth N      click depth (default 4)
--delay S          per-request politeness delay (default 0.25s)
--vertical V       ecommerce | finance_ymyl | local_service — changes severity weights
--skip-psi         skip PageSpeed Insights (offline / rate-limited)
--psi-key KEY      PSI API key for higher quota
--render-js        render pages in Chromium before parsing (slower, needed for SPA sites)
```

## What it covers

| Section | Implemented | Notes |
|---|---:|---|
| Analytics & Tracking | 12/12 | Full section. Template calls these "Manual Review" — all are tag detection |
| Structured Data | 10/10 | Full section |
| URL Structure | 17/18 | |
| Technical SEO | 26/38 | |
| On-Page SEO | 34/50 | Remainder are keyword-map (Tier C) and judgment (Tier B) rows |
| Performance & CWV | 16/19 | CWV rows via PageSpeed Insights |
| HTTPS & Security | 11/15 | TLS probe + header inspection |
| Canonicalization | 4/6 | |
| International SEO | 4/8 | |
| HTML & Code Quality | 5/9 | |
| Mobile SEO | 3/7 | Remainder need the Lighthouse reroute (Google retired the Mobile-Friendly Test) |
| E-E-A-T | 9/24 | Page-existence subset; the other 15 are Tier B judgment |
| AI SEO / GEO | 8/30 | llms.txt, AI-crawler access, schema; 14 are Tier B, 8 are the AI-visibility monitor |
| Search Console / GA4 | 0/38 | Phase 2 — needs client OAuth |
| Off-Page & Authority | 0/29 | Phase 2 — needs Ahrefs or Semrush |

## Verification

The tool is validated against a fixture site carrying **deliberately planted
defects** with recorded ground truth — stronger than a live-site run, where the
true defect count is unknown.

```bash
python3 make_fixture.py
(cd fixture/site && python3 -m http.server 8099 &)
python3 run_audit.py http://localhost:8099/ --skip-psi --delay 0.02
python3 verify.py
```

Current result: **37/37 ground-truth assertions detected correctly (100%)**.

Re-run `verify.py` after any change to a checker — it is the regression suite.

## Architecture

```
crawler.py          one crawl → artifact feeding ~190 checkpoints
checks/
  __init__.py       registry + finding contract + count normalisation
  crawler_checks.py TECH, URL, CANON, ONP, MOB, HTML, INTL
  tagdetect.py      ANA (all 12)
  security.py       SEC + TLS, with dependency cascading
  geo_schema.py     SCHEMA, GEO, E-E-A-T page-existence
  perf.py           PERF + PageSpeed Insights adapter
scoring.py          severity → section score → overall rating
report.py           HTML renderer
```

**Adding a checkpoint** is one function:

```python
@check("ONP-99")
def my_check(art, ctx):
    bad = [p.url for p in art.pages.values() if some_condition(p)]
    return finding("Fail" if bad else "Pass",
                   {"count": len(bad)},
                   f"{len(bad)} pages have the problem.",
                   bad, "Medium", "How to fix it.")
```

No I/O in checks — everything comes from the artifact. That is what keeps a
single crawl able to answer 190 rows, and what makes checks unit-testable.

## Two design decisions worth preserving

**Never score a section 0 because data was missing.** `Need Access` and `N/A`
are excluded from scoring; a section with nothing assessable renders as "Not
Assessed". Conflating "we couldn't check" with "it's broken" is the fastest way
to lose a partner's trust. The same rule applies inside checkers: `URL-01`
returns `Need Access` when neither host variant resolves, rather than inventing
a defect from a failed probe.

**Cascade dependent failures.** An HTTP-only origin produces one finding
(`SEC-01`), not six "could not retrieve certificate" failures. Root causes
should appear once. See `_cascade()` in `security.py`.

## Known limits

- `MOB-03..07` reference Google's Mobile-Friendly Test, which Google retired
  along with its API. Reroute to Lighthouse/PSI.
- PSI requires outbound access to `googleapis.com`; use `--skip-psi` offline.
- External-link checking is sampled (60 URLs) to bound crawl time.
- Tier B (37 judgment rows) and the AI-visibility monitor are Phases 3 and 4.
