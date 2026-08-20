# Changed files — build 2026.08.20-01

**Cumulative since 2026.08.18-16.** Apply and you are current whatever you last
uploaded.

## Two of these were wrong, not ugly

**The footer never reached the judgment layer.** EEAT-20 told a client "no
physical address or business hours are present" about a site whose address is
in the footer of every page. `_slice()` sent the model `text[:1400]` — and a
footer is, by definition, the last thing on the page, so a head-only slice
could never contain it. The checkpoints that most need the footer (address,
hours, legal entity, support channels) were exactly the ones structurally
guaranteed to miss it. Now sends head **and** tail with the cut marked.

**"CrUX field assessment: UNKNOWN" was a failure.** UNKNOWN means Google has no
real-visitor data, which happens when a site is below the traffic threshold —
so a fast site failed PERF-10 for not being popular enough to measure. Now
falls back to the lab score and says which one you are reading, in English.

## Typeface

Roboto, via `fonts-roboto` in the image. `engine/fonts.py` registers all four
faces or none — registering regular and bold without italic gives a document
that changes typeface mid-sentence. Falls back to Helvetica silently at render
time (a missing font must never take a report down) but says so in the log, and
`tests/test_charts.py` fails if the image lost the package.

## Repetition

| Was | Now |
|---|---|
| ONP-01 and ONP-23 both printing "83 pages share 25 duplicated title tags" | second row reads "Same finding as ONP-01." |
| 15 judgment rows all opening "All examined pages (homepage, practice areas, …) contain only generic…" | near-duplicates keep only what differs, prefixed "As EEAT-01." |
| 12 consecutive Manual rows each carrying the same explanatory sentence | blank — the pill says Manual and the intro says what that means |
| 29 Off-Page rows each saying "No backlink data provider is configured" | collapsed the same way |
| Findings 2 and 3 both titled "Trust and expertise signals are weak" | groups that would print the same title are merged, freeing a headline slot |
| "Meta Pixel · N/A · Not detected." and friends | N/A rows dropped from the appendix; the count is stated instead |

## Copy

- "We crawled 118 pages" → "We reviewed 118 pages". "Automated crawl of…" →
  "118 pages reviewed from…". No mention of crawling anywhere client-facing.
- "It shows up in 11 separate checks, including Real examples included, …" →
  "The same gap shows up across 11 different signals." The trailing list was
  raw checkpoint names, several of which end in "included". **Signals, not
  locations** — we counted signals, and "locations" would read as pages.
- Plan items for the 29 judgment checkpoints are verb-led work. "Address
  first-hand experience demonstrated" → "Add first-hand detail — your own
  cases, photos and specifics".
- "Titles and headings are not doing their job" → "Page titles don't say what
  each page is about" — names the job instead of asserting failure.
- "priority templates" → "starting with the pages that bring in the most
  traffic".
- Top Findings and Methodology sublines removed. Scores by Area subline is
  yours, keeping the hollow-bar note because an unassessed area must never
  read as a zero.
- "1 pages exceed 200KB" → "1 page exceeds 200KB", at render time rather than
  in forty check modules.
- Appendix: "a judgment call we make by hand rather than by crawler" → "a
  judgment call, made by hand as part of the work".

## Layout

- Severity is a pill in the Top Findings meta line, matching the appendix.
- Severity legend uses the same pill. It was painting the cell background and
  setting TEXTCOLOR on the cell — which a Paragraph's own style overrides — so
  "Critical" was dark grey on dark navy.
- Phase captions back to left-aligned.
- Coverage columns renamed **Reviewed** / **Issues**, with a line saying they
  are different denominators. "4/12 … 2" read as one ratio.
- Canonicalization was printing a definition of *indexing*, because "canonical"
  had been defined earlier and the next unused term that appeared in any row
  won by default. A section now only offers terms its own subject licenses, and
  prints nothing when they are spent.

## "88 checks are ours to finish" — where does that reach us?

It didn't. That was a promise in a client deliverable with no worklist behind
it. The internal report page now opens with **Action needed**, before anything
else: what is blocked on our configuration (grouped by reason, not one row per
checkpoint), what is waiting on a client grant, and what needs manual review
listed by section. Internal only — it never appears in the client PDF.

## Still empty, and why

`DFS_LOGIN` / `DFS_PASSWORD` are not on the worker. That is Off-Page (0/29) and
MOB-03..06 both reading "waiting on our data provider". Search Console and GA4
correctly report that `reporting-zone` is not on Ooten's property — that one is
a client grant, and the message is trustworthy on -16 or later.

## Verified before sending

- Rendered and looked at: cover, gauge, severity legend, methodology.
- Roboto registers; `_agree`, `_dedupe_evidence` unit-checked including the
  cases they must NOT touch (real plurals, "1 address", short rows).
- 14 suites green; `import app.api, app.worker` on a clean merged tree.

## What to check

- Header chip reads **2026.08.20-01**.
- Put `DFS_LOGIN` / `DFS_PASSWORD` on the worker, then re-run.
- Open the internal report page — Action needed is the first thing on it.
