# Build 2026.08.19-08

## Answering the two questions

**Yes — the judgment layer and DataForSEO run automatically.** No flags, no
config beyond the keys you have already set. A fresh audit will call them.

But **before this build, Off-Page would still have read "Not Assessed"** even
with DataForSEO working, and that was a bug worth fixing before you ran it —
see below.

## Check after deploying

- [ ] Header reads **build 2026.08.19-08**.
- [ ] Favicon appears. It is now inlined as a data URI in the page itself, so it
      no longer depends on the `static/` directory reaching the container. If it
      is still missing, the deploy did not take.
- [ ] Run a fresh audit. Expect it to take **3–6 minutes longer**: 29 judgment
      calls (6 at a time) plus the DataForSEO round trips.
- [ ] Worker log shows the judgment step and, if credentials are right, no
      `DataForSEO ... failed` lines.
- [ ] Scores by Area: **E-E-A-T, AI Search and Off-Page should all carry a
      score** rather than "Not Assessed".
- [ ] Off-Page rows OFF-21..29 read *"Prospecting work, delivered during the
      campaign rather than measured in the audit."*
- [ ] Send me the keyword rankings table — that is the DataForSEO payload most
      likely to differ from what I coded against.

## Up next

- **Feed the paid data into the judgment layer.** Now unblocked: once you
  confirm the DataForSEO response looks right, the E-E-A-T and AI Search prompts
  can read the backlink profile and rankings instead of judging authority from
  the site's own copy. Same-day change.
