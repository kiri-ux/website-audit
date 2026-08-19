# Build 2026.08.19-03

## Check after deploying

- [ ] Header reads **build 2026.08.19-03**. If it doesn't, the deploy didn't take.
- [ ] Dashboard groups by client — your six Grand Furniture runs collapse to one
      card with "5 earlier runs" underneath.
- [ ] Case and spacing variants merge: "Grand Furniture" and "grand furniture "
      land in the same card. Genuinely different clients must NOT merge.
- [ ] **Delete** on a card removes the row and doesn't come back on refresh.
- [ ] **Keep newest, delete the other N** leaves exactly one run for that client.
- [ ] Open a finished report → **PDF** opens in a new tab, report stays put.
- [ ] PDF cover: no build id in the footer, date reads MM/DD/YYYY, Prepared by
      Vici, no "Collection method" row.
- [ ] Top Findings say **"How we handle it"** — scope, not step-by-step fixes.
- [ ] Definition bubbles carry the blue ⓘ badge AND a symbol (⚑ ◆ ⚡). The symbol
      needs the new Dockerfile — if it's missing, the font install didn't run.
- [ ] Severity and status pills are readable — no white-on-mid-blue.
- [ ] Run one fresh audit and check the Analytics rows: unused ad pixels should
      read **N/A — "Not in use. Only needed if you run Google Ads."**, not a
      Medium defect. Existing audits keep the old wording until re-run.

## Up next

- **Annotated screenshots.** The one thing Brendan's audit has that we don't.
  Playwright and Chromium are already in the worker image, and each finding
  already knows which element failed — so it's re-open the page, box the
  element, capture the viewport, attach to the finding. Needs a decision on
  where the images live (S3 alongside the crawl artifact) and roughly a day.
- **Judgment layer can't see the paid data.** The 29 E-E-A-T and AI Search calls
  read the crawl only, so they assess trust signals without knowing the backlink
  profile or what you rank for. Wiring the DataForSEO results into that prompt
  is a small change and a materially better assessment.
- **AI visibility never reaches the client PDF.** GEO-23..30 merge onto the
  audit as checkpoints, but share-of-voice and the mention-vs-citation story —
  the most differentiated thing in the product — live only on /visibility.
  Needs a page in the PDF fed from the monitor run linked to that audit.
- **Real-site verification of DataForSEO.** The collector is tested for how it
  degrades, never against a live response. `ranked_keywords` is the payload most
  likely to surprise us. Set `DFS_LOGIN`/`DFS_PASSWORD`, run one real audit,
  read the rankings table.
- **Partner mode has never been exercised.** `partner_id` is written everywhere
  and the API-key path exists, but nobody has ever authenticated as a non-default
  partner. Needs a deliberate test pass before the first partner, not during.
