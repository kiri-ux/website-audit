# Vici Audit Capture — Chrome Extension

Captures audit data from sites that block server-side crawlers, using the real
browser render.

## Why it works

WAF bot detection does not ask "is this automated." It fingerprints the **TLS
handshake (JA3/JA4), HTTP/2 frame ordering, header order, and the JS execution
environment**. Python `requests` fails all of those regardless of what
user-agent string it sends — which is why the server crawler gets an empty shell
or a refused connection.

This runs inside real Chrome, on a real IP, with a real profile. There is
nothing to fake.

**Second benefit, independent of blocking:** it reads the **post-JavaScript
DOM**. On any site that renders product grids, reviews or navigation
client-side, this is strictly more accurate than the raw HTML the server crawler
parses.

## Install

1. `chrome://extensions` → enable **Developer mode**
2. **Load unpacked** → select this `extension/` folder
3. Pin it to the toolbar

## Use

1. In the dashboard, submit an audit. If the server crawl is blocked, the audit
   parks at **`needs_capture`** and shows its audit ID.
2. Open the client site in a tab.
3. Click the extension. Fill in:
   - **API URL** — your `vici-audit-api-xxxx.onrender.com`
   - **Audit ID** — from the dashboard
   - **Pages** — 30 is the default (see sampling below)
4. **Start capture**, then leave it. It opens each URL in one reused background
   tab, scrolls to trigger lazy loading, extracts, and moves on.
5. On finish it uploads and the audit flips to `ready`. Open the report.

You do **not** click through the site yourself.

## Why 30 pages is usually enough

Of the 131 implemented checkpoints, **110 (83%) are template-level** — they ask
about title tags, schema, headings, viewport, tracking scripts. Those answers do
not change between the 30th and the 300th product page.

Only 21 need full-site coverage, because their answer depends on the corpus:
duplicate-title detection, orphan pages, click depth, broken-link sweeps, and
sitewide totals like "images missing alt text."

So: **30 pages sampled across the sitemap** gives you 83% of the audit in about
two minutes. Raise the page count when you specifically need the sitewide
counts, and note in the report that totals are sampled.

The sampler steps *through* the sitemap rather than taking the first N, because
the first N are usually all one template (every product, or every blog post),
which would leave most page types unaudited.

## Pacing

Default dwell is 2500ms + up to 900ms of jitter.

- **~2.5s** is enough for load, JS execution, and lazy-load scroll
- **~5s** if you also want layout-stability signals to settle
- Jitter matters: 150 tabs at an exact 1s cadence looks scripted even from real
  Chrome. Advanced bot management watches timing, not just fingerprints.

## What it captures vs what the server still does

| Browser (this extension) | Server |
|---|---|
| Rendered DOM, headings, links, images | TLS certificate, protocol, expiry |
| Schema (JSON-LD + microdata) | HTTP→HTTPS redirect behaviour |
| All scripts + inline JS (the 12 analytics rows) | PageSpeed Insights / Core Web Vitals |
| robots.txt, sitemap.xml, llms.txt | Host resolution (www vs non-www) |

The split is deliberate: the server-side items do not go through the site's HTTP
layer, so they were working even when the crawl was fully blocked.

## Equivalence guarantee

The capture is converted server-side into the **same `SiteArtifact`** the Python
crawler produces, then runs the **same 159 checkers**, the same scoring and the
same report. There is no separate "browser findings" code path — that would
drift within a month and leave you with two different audits.

`tests/test_capture.py` asserts this: it crawls the fixture site with the server
crawler, replays the identical pages through the capture endpoint, and requires
**every content checkpoint to return an identical status**.

## Notes

- Only audit sites you have permission to audit. This is a client-onboarding
  tool, not an evasion tool.
- The safety net applies here too: a capture that returns structurally empty
  pages is caught by the same degeneracy rules and reports `Need Access` rather
  than inventing findings.
- Manifest V3. `webRequest` is used in observe-only mode; no request blocking.
