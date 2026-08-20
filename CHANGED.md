# Changed files — build 2026.08.20-05

## "I ticked reuse and it crawled anyway"

It did, and that is on me. `reuse_crawl` was resolved on the **API**, which
looked up the previous audit's artifact and passed its id to the worker. But
the API and the worker are separate containers, and with a local
`ARTIFACT_STORE` the API cannot read a single artifact the worker wrote — the
gotcha already written down in this very file. So the lookup found nothing,
quietly dropped the option, and crawled a site that blocks crawlers.

Resolution moved to the worker, which is the process that can actually see the
artifacts. And if reuse is requested and no stored crawl exists, the audit now
**fails with that sentence** instead of crawling. Doing the slow, rude thing
after being told not to is worse than stopping.

## The extension

**It stopped when you switched tabs.** Not tab throttling — the MV3 service
worker was being evicted. A capture spends most of its time waiting for page
loads and dwelling, which is exactly what Chrome reads as idle, so the worker
died mid-run about 30 seconds in. Now a cheap API call every 20s holds it open
for the length of a run, with a `chrome.alarms` backstop that survives eviction
and wakes it back up. Switching tabs is fine; the capture drives its own
background tab.

**"150 pages" captured 2.** `ootenlawfirm.com/sitemap.xml` is a sitemap
*index* — `<sitemapindex>` pointing at child sitemaps, not a list of pages. The
regex matched its `<loc>` elements, found one, and sampled two URLs. Now
follows one level of index (up to 25 children), and when a sitemap is still
thin it reads the homepage's own internal links rather than giving up. The
existing "will follow links from the homepage" message was aspirational — that
code did not exist.

**Fewer fields.** API URL is gone: it is one fixed deployment, and it was a box
nobody ever changed and everybody had to fill. Partner API key is gone too.
What is left is the audit id, pages and dwell.

**One-click start.** The blocked-audit page now carries a **Start capture with
the Chrome extension** button. The extension's content script finds it, reads
the audit id and target off the element, and starts the run — nothing is copied
between tabs. When the extension is not installed the button stays hidden and
you get the audit id with a copy button instead, which is also new.

## How does it know a capture finished?

The extension tells it. When the walk ends it POSTs every captured page to
`/api/audits/{id}/capture`; the API runs the checkpoints against that payload
and marks the audit ready. Your log line — `DONE — 255 checkpoints evaluated` —
is the server's reply. There is no polling and no timeout to wait out.

## Layout

The access-check button and the property dropdowns were living inside the
Target URL grid cell, so they became part of the five-column row: labels
stopped lining up with their inputs, and the result text wrapped one word per
line in a 200px column. Both now sit on their own full-width rows below the
form.

---

# Build 2026.08.20-04

## Pick the property yourself when the matcher misses

Two dropdowns appear under the URL field after you click **Check access**, one
for Search Console and one for GA4, each listing every property our logins can
see. A matched property is preselected. When nothing matched, the first option
reads *"No match — pick one, or leave blank"* and the list is right there.

Each has a filter box above it, because `reporting-zone` holds hundreds of
properties and a native select with 400 rows is not a control.

This is the answer to a question the automatic match cannot answer: **is the
client actually in there?** A miss currently means "email them for access", and
that is the wrong move if the property exists under a name the matcher could
not connect to the domain — a brand that is not the domain, a client on a
subdomain, a Search Console entry that is a domain property. Now you look.

Mechanics worth knowing:

- A chosen property **wins over the automatic match**. It is stored on the
  audit, so a re-run keeps the choice rather than making you find it twice.
- Leaving the blank option selected is exactly the old behaviour — the audit
  matches on its own.
- `GET /api/properties` backs the lists. It uses `sites` and
  `accountSummaries` only; neither opens a data stream, so it does not get
  slower as the number of properties grows. Cached for two minutes.
- A login whose token will not exchange is reported in `errors` and skipped,
  rather than taking the whole list down with it.

---

# Build 2026.08.20-03

## Check access before you spend a crawl

**Check GA4 / Search Console access** sits next to the URL field on the
homepage. It asks the same questions the collectors ask and answers in a
second or two:

```
✓ Search Console: https://ootenlawfirm.com/ (via reporting-zone)
✓ GA4: Ooten Law Firm (522482558, via reporting-zone)
```

Search Console is exact — one `sites` call per login lists everything, so a
"no" there is a real no. **GA4 is not**, and the button says so rather than
pretending. Matching a GA4 property to a domain means opening its data
streams, one API call each, and `reporting-zone` holds hundreds. The quick
check only opens streams for properties whose *name* already looks right; when
that finds nothing it reports "no quick match — the audit looks wider" instead
of claiming there is no property. An overconfident "no" is worse than a slow
"maybe", because it would have us emailing clients for access they already
gave.

`GOOGLE_TOKENS` has to be on the **API** as well as the worker for this, since
the API is what answers while you are still looking at the form. If it is only
on the worker the button says "not set on this service" — accurate about the
API, and it says nothing about whether the audit will find the data.

## Run only the part you need

Under the form: **E-E-A-T and AI Search**, **Search Console / Analytics /
off-page**, **Evidence screenshots**, and **Reuse the last crawl of this URL**.

The last one is the point. The crawl is the slow, rude phase — 150 requests to
someone's server — and re-running because our LLM key was missing shouldn't
cost the client's site another 150. Ticking it finds the newest audit of that
exact URL whose artifact we still hold and re-scores those pages.

The honest caveat is on the form: sitewide counts then describe the site as of
that crawl, so a fresh crawl is the right choice for "has the fix landed".

One subtlety worth knowing: an unticked checkbox sends nothing, which is
indistinguishable from a script that predates the feature. A hidden `phases`
field tells them apart — with it, an absent box really means off; without it,
everything runs as before. Getting that backwards silently skips the judgment
layer, which is the failure we have already had once.

---

# Build 2026.08.20-02

## Why Ooten's Search Console and GA4 came back empty

Not a permissions problem. Two matching bugs, and both produced the same false
sentence — "no Vici login has access to this property" — about properties
`digital@reporting.zone` can read perfectly well.

**Search Console: scheme.** The audit was submitted as
`http://ootenlawfirm.com/`. The property is `https://ootenlawfirm.com/`. Those
are genuinely different properties to Google, and we compared the two strings
literally, so it did not match. Anyone typing a URL types `http://`, and the
site then redirects — so this would have missed on most audits, not just this
one. Now matches any of `http`/`https` x `www`/bare, plus the `sc-domain:`
form, and **queries with the property string Google returned** rather than the
URL the audit was submitted with. Matching on one and querying with the other
is its own bug, waiting.

**GA4: display names have spaces.** The scan ordered properties by name
similarity — `"ootenlawfirm" in "ooten law firm"` — which can essentially never
be true. So nothing was ever "likely", the scan ran in arbitrary order, and on
a login holding hundreds of properties the right one sat past the 60-property
cap. Both sides are now squashed to letters and digits, so "Ooten Law Firm"
matches `ootenlawfirm` and sorts first.

Neither is a scoring change. Both are the difference between the section
filling and the section reading Not Assessed.

---

# Build 2026.08.20-01

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
MOB-03..06 both reading "waiting on our data provider".

*(Written before -02: this section also claimed the Search Console and GA4
message was a real missing client grant. It was not — see the top of this file.
Leaving the correction visible rather than quietly editing it, because "the
tool said access was missing" is exactly the kind of claim that gets repeated
to a client before anyone checks it.)*

## Verified before sending

- Rendered and looked at: cover, gauge, severity legend, methodology.
- Roboto registers; `_agree`, `_dedupe_evidence` unit-checked including the
  cases they must NOT touch (real plurals, "1 address", short rows).
- 14 suites green; `import app.api, app.worker` on a clean merged tree.

## What to check

- Header chip reads **2026.08.20-01**.
- Put `DFS_LOGIN` / `DFS_PASSWORD` on the worker, then re-run.
- Open the internal report page — Action needed is the first thing on it.
