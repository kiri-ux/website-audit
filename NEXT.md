# Build 2026.08.19-05

## Check after deploying

- [ ] Header reads **build 2026.08.19-05**.
- [ ] Browser tab shows the gold gauge on Atlas Blue — same family as site-scan
      and the SEO quote tool. Hard refresh if you still see the default globe;
      browsers cache favicons aggressively.
- [ ] `/favicon.svg` and `/apple-touch-icon.png` both return 200, not 404. A 404
      means `static/` didn't make it into the image.
- [ ] Run one fresh audit — ~30s longer than before, that's the screenshots.
      Worker log should say `captured N evidence shots`.
- [ ] PDF has **What This Looks Like** after Top Findings, with real screenshots
      of the client's pages and red outlines on the flagged elements.
- [ ] Link an AI visibility run to an audit → PDF gains an **AI Search
      Visibility** page. No monitor run = section omitted, not empty.
- [ ] Dashboard still groups by client; delete and prune still work.

## Up next

- **Real DataForSEO run.** Set `DFS_LOGIN` (account email) and `DFS_PASSWORD`
  (API password from Dashboard → API Access, not the portal login) on the
  worker — the same two values the SEO quote tool uses. Turns on backlinks, the
  rankings table, Lighthouse via their infrastructure, and SERP screenshots.
  Run one audit and send me the rankings table.
- **Feed the paid data into the judgment layer.** Blocked on the above by
  choice: wiring backlink and ranking data into 29 LLM prompts before we have
  seen one real response would mean debugging two unknowns at once. Once the
  credentials are confirmed, this is same-day work and it is the thing
  Brendan's template structurally cannot do — his E-E-A-T rows are 100% manual
  review and quote none of his own backlink numbers.

## Not doing (your call)

- Partner-facing mode. The seam exists; nobody has authenticated as a
  non-default partner. Revisit before the first partner, not during.
