# Changed files — build 2026.08.20-19

## "Why is Reviewed by hand here?" — the panel contradicted itself

The panel headline read **"Action needed before this goes out"**, and directly
under it a group said **"Nothing to configure, and nothing blocking this
report."** It demanded action and then listed things needing none. No wonder it
did not parse.

The headline is now neutral — *"Before this goes out"* — and says which list is
which. The second group is retitled **Analyst work list**, and its text says what
it is rather than what it isn't:

> **Not a gap and not a bug** — these are the checkpoints no tool can answer, so
> a person does them as part of the engagement. They are already excluded from
> the score, so leaving them until the work starts costs nothing.

## "Why wouldn't we be reviewing something?"

Same question one layer down, on the **Reviewed 4/12** column. Last build I fixed
the arithmetic; I never explained the gap. The caption now says where the
difference goes, and points at the coverage panel that breaks it down: checks we
complete by hand during the engagement, or checks that need access to their
accounts. Never "we skipped it".

---

## The lamp

**It was in the PDF all along** — sitting in a nested cell fixed at 1.55 inches,
so on a short checkpoint name it floated an inch and a half from the text, in
white space between two columns, belonging to neither. Against the **ID** it
lands in a tidy vertical column, unmistakably attached to its row. That is what
makes it scannable, and it is why you could not find it.

**The legend is gone from the client PDF.** You were right. The lamp is a signal
for whoever reviews the draft; the client was never asked to act on it, so a
paragraph explaining a symbol is furniture. The mark stays in both documents, the
explanation stays only on the operator page — which is where the review actually
happens.

---

## Smaller things

| | |
|---|---|
| At a glance tiles | Separate rounded cards, matching the dashboard. The first version was one long box with hairlines, on the theory that five borders spend more ink on chrome than on numbers — next to the dashboard it just looked like a table that had lost its header |
| Footer | `Client - Website Audit`, single hyphen |
| "Nothing here is a mark against you" | Now "Unmeasured checks are left out of the score, never counted as zero" — the same fact, stated rather than reassured |
| Completed audit page | **All audits** button at the top. It was a dead end otherwise: back-button only, and after a rerun that lands on a stale status page |

---

## OFF-18 Image backlinks

An image backlink is a link where the clickable thing is a picture rather than
words — a badge, a logo, an infographic embed. They pass authority like any other
link, but where a text link hands Google a phrase describing the destination, an
image link hands it the alt attribute, and an image link with **no** alt text
hands it nothing at all. That is the part worth reporting, and it is why this row
is not simply a count.

**It turned out not to need a new endpoint after all.** The row read exactly one
key — `referring_links_types["image"]` — and when that key was not in the
response it fell through to the catch-all, which said the collector "requires an
additional DataForSEO backlinks endpoint". That sent us looking for a call to add
when the real problem was a key we were not finding. Same class of bug as the
missing `dofollow` field, one row over.

Two routes now:

- **The summary breakdown**, tried first under four possible key names. Costs
  nothing — the response is already in hand.
- **`/backlinks/backlinks/live`** if the summary genuinely does not carry it. One
  metered call, made only when needed, reading the 1,000 most recent links and
  counting `item_type == "image"` — plus how many of those have empty alt text.

The endpoint route reads a **sample**, so it says so: *"20 of the 1,000 most
recent backlinks come through an image rather than text."* Same rule as the URL
Inspection rows — a bounded read never gets written up as a profile-wide total.

And when the summary key is missing, the log now prints the top-level field names
it did return, so the next fix is a rename rather than another round of guessing.

---

## "No address" when it's in the footer

Third time this has reached a client, and the previous two fixes were both aimed
at the wrong place. Adding JSON-LD helped where the address was in the schema. It
did nothing where the address is simply printed in the footer.

**The footer is the last thing in the DOM.** Body text is capped at 20,000
characters and then sliced head-and-tail before it reaches the judgment layer —
so on a long page, the footer is *precisely* what falls out of the middle. The
address was never in the material the model saw. No amount of prompt tuning fixes
a string that does not contain the thing.

The crawler now captures the footer into its own field — `<footer>`,
`role="contentinfo"`, or an id/class containing "footer" — and every judgment
prompt carries it **in full, never sliced**, with a rule saying anything in it is
present site-wide and must be treated as visible to visitors.

A second rule went in alongside it, because the same row exposed it: evidence
must be written as a finding about the site, addressed to its owner. *"…no
physical address is visible in the provided material from any contact page URL"*
describes how the sausage was made, appears nowhere else in the document, and so
stands out as machine output on an otherwise human page.

**This needs a fresh crawl to take effect.** The footer field does not exist in
artifacts captured by earlier builds, so reusing a stored crawl keeps the old
behaviour for that run.

---

## Nine checkpoints that were never manual

Every one of these was printing "Manual" or "Waiting on our data provider" while
the answer sat unread in a Lighthouse response we already fetch for
PERF-10/11/19. No new API calls, no new credentials.

| | Answered from |
|---|---|
| **MOB-03** Mobile Friendly Test | viewport, content-width, font-size, tap-targets |
| **MOB-04** Responsive design | viewport + content-width |
| **MOB-05** Touch elements | tap-targets |
| **MOB-06** Font readability | font-size |
| **HTML-09** Accessibility basics | the Lighthouse accessibility category, naming the failing basics |
| **ONP-43** Proper compression | uses-text-compression |
| **PERF-05 / 07 / 09** | compression, minification, resource-summary |

Plus **HTML-04** (Flash, Java applets, Silverlight) from the crawl — it is a
substring search over HTML we already hold, which is a strange thing to ask a
person to do by hand.

One honest note on MOB-03: Google retired the standalone Mobile-Friendly Test
API. What replaced it is exactly these Lighthouse audits, so that is what the row
now says it is.

---

## At a glance, in the PDF

The tile strip from the operator dashboard, under the score ring: **Passing ·
Failing · Worth a look · Need your access · Pages reviewed**. Five whole numbers
with no ratios to decode — it answers "how did we do" before the reader has to
interpret a bar.

Hairlines between tiles rather than five separate cards; at 6.5 inches, five
bordered boxes spend more ink on chrome than on numbers.

---

## Copy

**"44 checks are ours to finish… reviewed by hand rather than by crawler"** had
two faults: it said *crawler*, and it left you unsure whether any of it was
yours. Nothing on that line is. It now reads "checks we finish ourselves, with
nothing needed from you", and says plainly that they never count against the
result.

**Nofollow** added to the glossary — "0 of 875 outbound external links use
rel=nofollow" is unreadable without it. "Pages crawled" on the dashboard tiles is
now "Pages reviewed".

---

## The OFF-13/16/17/19/20 "Need Access" rows

Already fixed in ‑14; they need a rerun to clear. The anchors endpoint has no
`dofollow` field — it reports a total and a *nofollow* count, and followed is the
difference. Reading a key that does not exist summed to zero, and an implausible
zero is reported as unreadable rather than printed as a measurement, which is why
you saw Need Access rather than a confident "0.0% followed".

**OFF-18 Image backlinks** is the one genuinely missing endpoint. Say the word
and it is a small addition.

---

## "It looks like we didn't finish the audit"

You were reading it correctly, and the numbers were wrong.

**Reviewed 4/12** was two different numbers printed as one ratio. The numerator
excluded `Info` rows — measurements we *did* take and report, like a backlink
count, that simply have no pass/fail threshold. The denominator counted every
row the template has, including checks that do not apply to this client at all.

So International SEO showed **2/8 · Excellent** for a US-only law firm whose
other six international checkpoints are not gaps in our work, they are questions
about markets it does not sell in. And Off-Page showed **10/29** for a section we
had largely measured — thirteen answered rows were invisible.

Two corrections pulling in opposite directions:

- **N/A leaves the denominator.** A check that does not apply is not a shortfall.
- **Info joins the numerator.** We measured it and printed it; that is reviewed.

What is left is the honest remainder: checks that apply to this site and that we
could not answer. Off-Page goes from 10/29 to roughly 23/29, and the caption now
says what the pair means.

---

## Blank cells under "What we found"

Every **Manual** row had an empty cell. The old reasoning was that the pill
already says Manual and repeating one sentence down twelve rows is wallpaper.
That was wrong: an empty cell in a column headed *What we found* does not read as
"handled by hand", it reads as **nobody did this** — which is the opposite of
true and the worst thing a paid deliverable can imply about itself.

Each Manual row now carries a short, per-section note — four to eight words,
specific enough to be information, brief enough that a column of them scans as a
status rather than as prose. "Confirmed with an external TLS scanner."
"Confirmed firing in GA4 DebugView on a real session."

The dedupe skips them deliberately. Three Manual rows in a row *should* read the
same; collapsing them to "Same finding as PERF-05" would say something false —
they are three separate checks that happen to be handled the same way.

### And three of them should never have been manual

**PERF-05** (uncompressed JS/CSS), **PERF-07** (unminified), **PERF-09** (script
and stylesheet weight) were telling an analyst to go and read a DevTools
waterfall. The Lighthouse run we **already make** for PERF-10/11/19 answers all
three outright — `uses-text-compression`, `unminified-javascript`,
`unminified-css`, `resource-summary`. No new call; those audits were already in
the response and we were ignoring them.

---

## One finding, printed twice

Two separate bugs, same symptom.

**In Top Findings** — ONP-23 "Unique title on every page" and ONP-01 "Issues with
duplicate title tags" both printed *"83 pages share 25 duplicated title tags"* in
consecutive rows. The dedupe that fixes exactly this was written months ago and
wired only to the appendix, so it never ran on the page-3 table a client actually
reads.

**In the five headline findings** — items 2 and 3 were *"On-page fundamentals are
inconsistent"* and *"Page titles don't say what each page is about"*, with the
same evidence, the same rationale and the same remedy under both. There was
already a merge pass for groups that would print the same *title*; there was none
for two different titles resting on the same *observation*. Two of the client's
five headline slots spent on one measurement.

---

## Copy and definitions

| Was | Now |
|---|---|
| "…and its absence is not a fault." | "Google collects real-visitor speed data only for sites above a traffic threshold, and this site is below it." |
| `srcset` used with no explanation | **Responsive images (srcset)** added to the glossary |

Lazy loading turned out to be defined already — worth knowing that the definition
only appears when the term is *first* used, so it can be several pages from where
you noticed the gap.

---

## GSC-20/21/22 — the plan, and why the last one was wrong

I told you last message to keep these as an analyst read. That was the weaker
answer, and "someone will open Search Console and read it off" is a plan that
means it never happens on a single audit.

All three are now measured, from data this tool **already pays for and already
fetches** for the Off-Page section. No new subscription, one extra API call.

| | Answered from |
|---|---|
| **GSC-20** External links | Total backlinks, already in the summary call |
| **GSC-21** Top linking sites | `referring_domains`, ordered by link volume |
| **GSC-22** Top linked pages | `domain_pages`, already fetched for OFF-19/20 |

**The one extra call, and why it is not optional.** The toxicity check already
queries `referring_domains`, but ordered by *spam score* — its 200 rows are the
worst neighbours, not the biggest linkers. Sorting that sample by backlinks
would confidently name a "top linking site" that is merely the most-linked of
the 200 diciest ones. So GSC-21 makes its own call ordered by volume.

**Every one of these rows says where its number came from**, because ours will
not match Search Console. Google's Links report shows a sample; a backlink index
does not, so our figures are generally larger. A client who opens Search Console,
sees a different number and was not warned stops trusting the whole document.

### And a bug this turned up

**GSC-22 "Top linked pages" was being filled with the pages that got the most
organic *traffic*.** A page can be the most linked on a site and receive no
traffic at all. That is the same error as OFF-10 printing a nofollow percentage
under "Lost backlinks" — a real number, confidently mislabelled, which is worse
than an admitted gap. The traffic figure was genuinely useful, so it moved to
GSC-01 where it describes what it actually is.

---

---

## The 502

Your run reached the judgment layer and the report page returned 502. The API's
own code was fine. What was not fine is that three things had no ceiling on how
long they could wait:

- `psycopg2.connect()` with no `connect_timeout` waits **forever** when Postgres
  cannot accept another connection.
- A query with no `statement_timeout` waits forever behind a lock.
- `redis.from_url()` with no socket timeout waits forever on a host that accepts
  the connection and then goes quiet.

Uvicorn serves these routes from a bounded thread pool. A handful of permanently
stuck requests takes every thread — and once that happens `/healthz` cannot be
answered either, so Render concludes the service is dead and starts serving 502s
to the browser. **A database having a bad minute became a total outage.**

The judgment layer is where it surfaced because that is the window of heaviest
database write pressure, and it just grew 50%. The status page was also
refreshing every 4 seconds, each refresh opening a brand-new connection.

Four fixes:

| | |
|---|---|
| `/healthz` no longer touches Redis or Postgres | Queue depth is best-effort and degrades to `null`. A liveness check that fails when a dependency is slow is not a liveness check; it is a way of converting someone else's bad minute into your own outage |
| Postgres gets `connect_timeout` and `statement_timeout` | A request that cannot get a connection now fails fast with a real error instead of hanging a thread forever |
| Redis gets socket timeouts | Sized to outlast the 2-second blocking pop the worker legitimately sits on |
| The status page refreshes every 6s, not 4s | Every refresh is a full render and a fresh connection |

None of this makes the database faster. It puts a ceiling on the damage.

### And the run that died is no longer a spinner

The worker now stamps a heartbeat on every step. If that stops moving for ten
minutes the status page says **"This run has stopped responding"**, tells you
how long ago and at which phase, and offers a rerun **from the stored pages** so
it does not go back out to the client's server. Runs from before this build have
no heartbeat, and unknown is treated as alive — calling a live run dead is the
worse error of the two.

---

## Lightbulbs on the judged rows

Every row the judgment layer produced now carries a small gold lightbulb, in
both the HTML report and the PDF, with a legend at the head of the full record.

**On the wording.** You asked for the mark without calling the rows AI-generated,
which left the question of what the legend should say. It reads:

> **Judged by review rather than measured.** These checkpoints are qualitative —
> whether a page answers the question it ranks for, whether its call to action is
> clear — so they carry a judgment where the rest of this report carries a
> measurement.

That is true, it does not name the mechanism, and it is useful to both readers.
Your team sees exactly which rows to check hardest. A client sees something worth
knowing: this row is an assessment, not a hard number. An unexplained symbol in a
client deliverable would have been worse than no symbol.

Two details. A **Need Access** or **N/A** row gets no lamp — it was never judged,
so there is nothing to reread. And the lamp is drawn as vectors, not the emoji:
U+1F4A1 is missing from Roboto *and* from DejaVu, and reportlab renders a missing
glyph as a solid black box.

---

## Report copy

| Was | Now |
|---|---|
| "Schema entities — WebSite, Organization, WebPage, BreadcrumbList, ImageObject" | "Structured data found — site identity, business details, page markup, breadcrumb trail, images" |
| "worth handling this month" | "should be resolved within 30 days" |
| "The same gap shows up across 8 different **signals**" | "…across 8 separate **checks**" |
| "This is table stakes rather than optimization." | Cut |
| — | **Ranking signal** added to the glossary |

Schema.org type names are developer vocabulary. Brendan's template never printed
raw type names — it asked whether the right markup was present, in words. A
business owner cannot act on "ImageObject" and will not ask; they will decide the
page is not for them.

"Signals" was a third word for a thing the report already calls a **check** on
the cover and a **checkpoint** in the appendix. One word now.

### Definitions land at first mention

Two faults, one cause. Glossary terms came back in glossary order rather than in
the order they appear, so **canonical tag** was explained underneath the E-E-A-T
paragraph — two paragraphs after the word it was needed for. And the definitions
for both summary blocks were pooled with the overview text, which is why
**structured data** appeared with a definition for a term that is in none of the
paragraphs above it.

Terms now come back in order of first appearance, and each block defines only
what it introduced, directly underneath itself.

---

## Prepared by, per audit

A **Prepared by** field on the audit form, saved with the audit and prefilled
from a previous run for the same client. It overrides `FIRM_NAME` on the cover;
blank falls back to the configured firm, so nothing changes for audits where
nobody fills it in. White-labelled work goes out under the partner's name and
that varies between two audits run in the same hour — an environment variable
was the wrong home for it.

---

## From the Ooten run

**Search Console filled.** GSC-05 through 19 all carried measurements — 24 of 24
sampled pages indexed, 111 of 111 served over HTTPS, breadcrumbs appearing in
search, 121.9 average internal links per page. Only GSC-20/21 remain, which is
correct: no API exists for them.

**Two GA4 rows fell through, both my bugs.**

- **GA4-03 Enhanced Measurement** swallowed its exception with no logging, so a
  failed call was indistinguishable from "not built yet" — on a run where the
  Admin API demonstrably worked, because GA4-06 read key events from the same API
  with the same token two rows below. It now logs, and reports which of the two
  it is.
- **GA4-16 Revenue** — GA4 returns **no rows** rather than a row of zeros when a
  property has never recorded revenue. That is an answer, not a failure to read.
  It also now falls back to requesting `totalRevenue` alone, because one unknown
  metric name fails the whole request.

**The DataForSEO shapes.** `_num()` now tries every plausible key name instead of
one guess. The specific bug: the anchors endpoint has **no `dofollow` field** —
it reports a total and a *nofollow* count, and the followed figure is the
difference. Reading a key that does not exist summed to zero, which is what
produced "0.0% of backlinks are followed" on a live profile. If a shape still
misses, the row stays Need Access and the field names appear in the row's
recommendation on the internal report.

---

## Files

| File | Change |
|---|---|
| `app/db.py` | Connect and statement timeouts; `heartbeat_at` migration |
| `app/queue.py` | Redis socket timeouts |
| `app/api.py` | `/healthz` independent of dependencies; `partner` field; rerun accepts `reuse_crawl` |
| `app/ui.py` | Stalled-run panel; 6s refresh; Prepared by field |
| `app/worker.py` | Heartbeat on every step |
| `engine/report.py` | Lamp, legend, `is_judged` |
| `engine/pdf_report.py` | Lamp in the table, legend, per-block definitions, plain-English structured data |
| `engine/charts.py` | `Lamp` flowable |
| `engine/glossary.py` | Appearance-order terms; **Ranking signal** |
| `engine/summarise.py` | "separate checks"; 30 days; the HTTPS line |
| `engine/context.py` | `describe_entities()` |
| `engine/collectors/analytics.py` | GA4-03 logging, GA4-16 empty-result handling |
| `engine/collectors/dataforseo.py` | `_num()` / `_str()` tolerant field reads |
| `tests/test_resilience.py` | **New.** 40 checks |

All 17 suites green.

---

# Changed files — build 2026.08.20-13

## Two builds you asked for, both about the same thing: stop deferring

### 1. On-page quality is judged, not left for an analyst

*"Read the priority pages and judge intent, keyword use and CTA quality"* was
printed in the report as **your** homework. It is now the scan's.

Fifteen On-Page checkpoints moved into the judgment layer — ONP-13, 24, 25, 28,
29, 34, 35, 36, 37, 38, 39, 40, 41, 49, 50. They cover search intent match,
keyword placement and density, heading structure against the topic, CTA presence
and clarity, readability, content depth against what the query needs, and
internal linking relevance.

These need a different sample from the E-E-A-T rows, so they got their own
retriever. It picks up to six content-bearing pages (120+ words), weights money
pages first (`/service`, `/product`, `/practice`, `/solution`, `/pricing`,
`/contact`, `/quote`, `/book`), and **deduplicates by URL shape** so that twelve
near-identical location pages do not consume the whole sample and leave the
services page unread. It also passes a wider window — 2,200 characters rather
than 900 — because you cannot judge whether a page answers a search intent from
its first paragraph.

**ONP-43 (compression) was deliberately left alone.** It is a response header,
not a judgment, and asking a language model to guess at one would be a worse
answer than admitting we have not automated it.

Cost note, since it is real: the judgment layer went from 29 calls per audit to
44. Runtime is roughly flat — it is still six-way parallel — but the API spend
per audit rises about 50%.

### 2. The 27 Search Console and Analytics rows that said "read this from the interface"

A granted, working Google connection filled 11 of 38 rows. The other 27 said
some version of *we have not built this yet*, which is a strange thing to print
in a document you are charging for. All 27 now carry measurements, from three
places the collector was not previously looking.

**URL Inspection API — index coverage (GSC-05..11).** Indexed and excluded
counts, crawled-not-indexed, discovered-not-indexed, soft 404s, server errors,
redirect errors.

This one comes with a caveat built into every sentence it writes. The API
answers **one URL per call** and is quota-capped, so it reads a bounded sample —
the shallowest, best-linked pages first, 25 by default (`GSC_INSPECT_SAMPLE`).
Every row therefore carries its denominator: *"8 of the 12 pages sampled are
indexed; all 12 pages found on the site were inspected."* The version of that
sentence without the denominator would be a lie about a 400-page site, and the
temptation to write it is exactly why the test suite now asserts the
denominator is present.

**The `searchAppearance` dimension — rich results (GSC-14..18).** Rich results
overall, breadcrumbs, product results, FAQ results, video pages, each with
impressions and clicks.

Absence is handled with some care here. No breadcrumbs is a Warning, because
breadcrumb markup applies to essentially any site. No **product** results is
`Info` — a law firm has nothing to sell, and scoring that as a defect is the
kind of noise that teaches a reader to skim the section. `Info` is already
excluded from scoring, so it reports the fact without moving the number.

**The GA4 Admin API — configuration (GA4-03, GA4-06).** Enhanced Measurement,
naming which events are switched off; and key events, read from `keyEvents` with
a fallback to `conversionEvents` for properties Google has not migrated.

Traffic tells you what happened. Configuration tells you whether what happened
was measured correctly — and when a number looks wrong, it is almost always the
second one that explains it.

**Plus GA4-04 events** (with the automatic-event set filtered out, so "3 events
recorded" cannot pass for a real install), **GA4-07 cross-domain** and **GA4-08
internal traffic** from one hostname report, and **GA4-13 landing pages**.

GA4-08 measures the *effect* rather than reading the filter config, because the
Admin API does not expose data filters — if `staging.example.com` is reporting
into the live property, the filter is not working whatever it says it does.

### Four rows answered from data the audit already had

No new API call for any of these; we were sitting on the answers.

| | |
|---|---|
| **GSC-12** Core Web Vitals | The CrUX field data PageSpeed Insights already returned for PERF-11 — the same dataset Search Console's report is built from |
| **GSC-13** HTTPS | Our own fetches, plus the HTTP→HTTPS upgrade check |
| **GSC-19** Internal links | The crawl's link graph, which can also name the orphaned pages |
| **GA4-15** Conversion rate | Organic conversions ÷ organic sessions, two numbers GA4 returns and will not divide |

### Three rows that will never be answered, said plainly

**GSC-20** (external links) and **GSC-21** (top linking sites) have no API in any
form. **GA4-14** (exit pages) has no equivalent in an event-based model — it was
a Universal Analytics concept and did not survive the move.

None of the three is a missing client grant, and none is a build being deferred.
GSC-20/21 now bucket as **"Reviewed by hand"** with a pointer to the backlink
data in Off-Page and Authority, which covers the same ground properly. GA4-14 is
marked **N/A** with the reason stated.

This needed a third rule in `engine/access.py`. We already had one for *"the
prefix says client, the reason says it is ours"*; there is now one for *"the
prefix says client, the reason says nobody can get it"*.

### No re-consent needed

Both new APIs are covered by the scopes your tokens already hold —
`webmasters.readonly` for URL Inspection, `analytics.readonly` for the Admin
API. Nothing to do in Google Cloud.

---

## Files

| File | Change |
|---|---|
| `engine/judgment.py` | 15 ONP specs; `_priority()` retriever; a British spelling caught by the voice test |
| `engine/collectors/analytics.py` | URL Inspection, searchAppearance, GA4 Admin API, four rows from our own data |
| `engine/access.py` | `MANUAL_DESPITE_PREFIX` — reports with no API are an analyst's read |
| `app/worker.py` | Passes the crawl and the findings-so-far into the Search Console collector |
| `engine/report.py` | The On-Page "reviewed by hand" note is now about compression, not intent; a Search Console note added |
| `tests/test_analytics_build.py` | **New.** 45 checks over the new rows |
| `tests/test_charts.py` | ONP-34 is no longer manual — it belongs to the judgment layer now |
| `tests/test_collectors.py` | Coverage grew 96 → 111 |

All 16 suites green.

---

# Changed files — build 2026.08.20-07

## Restyled to adtini

The operator UI now uses adtini's design language, so it does not arrive
looking like a separate product bolted on when it moves into that site.

Read off the workflow and forecast screens:

| | |
|---|---|
| Navy rail, fixed left, gold active item | `#12356b` / `#f0b429` |
| White top bar with the page title, sticky | 44px, matching the Forecast header |
| Breadcrumb under it | `Audits › The Ooten Law Firm` |
| Pale blue-grey page, white cards, 6px radius | `#f4f6f9` on `#ffffff` |
| Navy table header, white type | matches the Workflow list |
| Pastel status pills, dark text | green ready, blue running, purple needs-capture, pink failed |
| Fully-rounded action buttons | blue primary, ghost, plus navy / gold / orange to hand |
| Roboto | loaded from Google Fonts, same as the PDF |

**Two things deliberately did not change.** Severity keeps its ordinal blue
ramp rather than adtini's categorical pastels, because on a ranked scale the
ordering *is* the information and four unrelated hues would destroy it. And the
score ring stays one hue with length carrying magnitude, for the same reason it
always has.

This is the operator UI only — `app/ui.py`. The client-facing HTML report has
its own stylesheet and is untouched, since it is a deliverable that goes out
under the client's nose rather than a screen inside adtini. Say the word if you
want that moved over too.

---

# Build 2026.08.20-06

## "No stored crawl when there is" — the same split, the other way

Ooten's earlier run came from a **browser capture**, and the capture endpoint
runs on the **API**, which wrote the artifact to the API's disk. The worker
then looked for it on the worker's disk and found nothing. Last build I moved
resolution to the worker to fix the crawl direction; this is the same bug
mirrored, and it was sitting right behind it.

There is no arrangement of a local path that fixes this, because the two
services do not share a filesystem at all. So **artifacts now live in the
database** — `ARTIFACT_STORE` defaults to `db://`. The database is the one
store both services demonstrably share, and a crawl artifact is a few megabytes
of very repetitive JSON that gzips to a fraction of that. `s3://` is still
there and still right at volume; `local://` is now honestly documented as
single-process only.

This also fixes artifact download, which had been quietly 404ing for the same
reason since the first two-service deploy.

The failure message now names what it looked at: *"3 earlier run(s) of this URL
exist, but none has a stored crawl"* rather than a flat "none available" while
the dashboard shows three.

## Settings used — the expand arrow

Every client card gets **Settings used**: vertical, max pages, primary markets,
primary conversion, the hand-picked Search Console and GA4 properties, and the
render/user-agent flags. Under it, **Start a new audit with these settings**
fills the form at the top — including re-selecting the properties you chose by
hand, which is the part that was being lost on every re-audit.

That last bit matters more than it looks: a property picked by hand was picked
because the matcher was wrong about that client, and re-deriving it from the
domain would quietly undo the correction.

## Installing the extension

The blocked-audit page now carries the steps, because an unpacked extension
disappears whenever its folder moves and "ask someone for the folder" is not a
step that survives a Tuesday. **`GET /extension.zip`** builds the extension
from the running image, so the download always matches the deployment.

`chrome://extensions` gets a copy button rather than a link — Chrome refuses to
let a page link there.

## Smaller

- Access-check results are pills: green found, amber "could not tell quickly",
  red no. The amber state exists because GA4's quick check genuinely cannot
  answer, and that must not look like a no.
- One back link on the audit page, not two.

---

# Build 2026.08.20-05

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
