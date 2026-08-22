# Changed files — build 2026.08.20-55

Cumulative delta since **2026.08.18-16**. Packed by `pack.py`.
Extension is **1.4.4** — unchanged since ‑50.

Four items on the list. Three of them should not have been there, and the
fourth was cut off mid-sentence.

---

## The truncation. Again. Third time.

> ...This model models/gemini-2.5-flash is no longer available to new users.
> Please update your code **to use a different model** ~~t.~~

`geo_checks.py` joined provider messages with `m[:160]`. The diagnosis in these
messages is at the END — it always is — so the cut landed on "update your code
t." and removed the instruction.

This is the third cap in this codebase to delete the only part of a sentence
worth reading: `reasons()` truncated evidence at 110, then the fix line at 180,
now provider messages at 160. All three are gone. A provider error is one line;
print the line.

---

## A listed model is not a promise

`GET /models` returned `gemini-2.5-flash`, the picker took it, and every one of
the 24 queries came back with the message above. Google **lists models it will
not serve** to a project that has never called them, so availability cannot be
decided from the listing — it is decided by asking.

Resolving to one name and failing on it turned a recoverable condition into 24
identical failures. The provider now walks candidates in order, remembers the
first that answers, and remembers the dead ones so twenty-four queries do not
each rediscover them:

```
  PASS  a refused model falls through to the next one  (['gemini-2.5-flash', 'gemini-2.0-flash'])
  PASS  and the working one is remembered, not rediscovered per query
```

If every model refuses, the row names them all rather than reporting the last
one's status code.

---

## Three consent rows were CONS-01 said three more times

Your scan found **no consent platform at all** (`verdict: no_cmp`, full browser
mode). That is the finding, and CONS-01 carries it. The other three were
restatements dressed as separate gaps:

| row | said | should have said |
|---|---|---|
| CONS-02 | "The scan could not determine whether a banner appeared. **Load the page and look.**" | there is no CMP to show a banner — see CONS-01 |
| CONS-05 | "The scan could not find a Reject control to test." | a site with no banner has no reject button to fail |
| CONS-06 | "Global Privacy Control was not tested on this scan." | GPC is not law in Tennessee |

Note what CONS-02 was doing: an instruction to **a person**, on a list headed
*"Nothing to ask anyone for."* The panel contradicted itself in two adjacent
lines.

### GPC is the interesting one

Global Privacy Control must be honoured in twelve states. **Tennessee is not
one of them.** Ooten sells in thirteen Tennessee counties, so the scanner
correctly skipped the GPC pass — and the row then reported that correct
decision as a gap on our fix list.

A check that does not apply to this client's markets is an answer, not an
omission. It reads:

> Global Privacy Control does not apply here: none of the states this client
> sells in (TN) require honouring it.

Status `N/A`, off the fix list. **And the case that IS ours is not swept up
with it**: add California to the markets and a GPC pass that did not run goes
straight back to "Ours to fix — this is ours: the GPC load either did not run
or did not complete." Same for a real CMP whose banner has no reject control.

---

## Also confirmed from your live run

`options.conversion_urls: ["https://ootenlawfirm.com/thank-you/"]` — stored on
the audit record. The ‑49 fix works; that field is saving.

---

## What the panel should say next run

One row, or none. Gemini resolves a model by itself now. If it cannot, it names
every model it tried and what each said.

---

## A platform we do not buy is not an action item

ChatGPT, Perplexity and Copilot were listed under *"Ours to fix — a credential
we have not set."* True, and never going to change: there is no intention to
set one, and Microsoft publishes no consumer Copilot API to set it for. Those
three rows would be on that list on every run forever.

That is precisely how the analyst section and the unticked phases each broke
the list before them — a fix list that never empties is a fix list people stop
reading, and the one real failure in it goes down with the rest.

A skipped platform is now tagged `ai_platform_absent` and dropped to Low, and
the panel filters that source out of "Ours to fix" the same way it already
filters the permanent Google-API boundary.

**It is not silent.** The checkpoint still renders in the body of the report:

> ChatGPT visibility not measured: not configured — no API credentials supplied.
> → Nothing to do unless we start paying for ChatGPT. This deployment holds no
> credentials for it, so it was never going to be measured.

A graceful degradation needs something loud somewhere else, or it is just a
silent failure with good manners. The row is the loud part; what changed is
only that it stopped claiming to be work.

**A platform we DO hold a key for keeps the old behaviour.** Gemini's 404 is
still on the fix list with its unwrapped message, because that one genuinely
needs somebody. That is the distinction the source tag exists to draw.

## And the panel was dropping reasons on the floor

Found while checking the above. Look at your last screenshot: the heading says
**Ours to fix · 7** and there are **four bullets**.

`reasons()` ended in `most_common(4)` while the heading counted the full list.
Three reasons were rendered nowhere, with nothing on screen saying so. A reader
counting bullets against the heading either distrusts the number or — worse —
does not notice.

The cap itself was right; a wall of forty distinct one-off reasons is not a
summary. What was wrong is that it was silent. It shows six now and finishes
with:

> and 4 more reasons covering 4 checkpoints — every one is in the findings
> table below.

Guarded by arithmetic rather than by a string match: bullets shown plus the
overflow count must equal the number in the heading.

```
  PASS  more reasons than fit are summarised, never dropped  (6 of 10 shown)
  PASS  and bullets plus overflow add up to the heading      (6 + 4 vs 10)
```

---

## What your panel should look like after the next run

Of the seven, three leave as not-our-problem and one is now correctly
diagnosed:

| was | now |
|---|---|
| ChatGPT — no credentials | off the list |
| Perplexity — no credentials | off the list |
| Copilot — no credentials | off the list |
| Gemini — HTTP Error 404: Not Found | should be measured; the model is discovered rather than hardcoded |

If Gemini still fails, the row names the reason, and the list is short enough
that you will see it.

---

## ‑52 worked. Your capabilities now read:

```json
"build": "2026.08.20-52",
"ai_platforms": ["ai_overview", "claude", "gemini"],
"ai_missing":   ["chatgpt", "copilot", "perplexity"]
```

`ai_overview` moved. The provider that was written in ‑38 and never shipped is
on the worker, it found DataForSEO on its own, and the panel went from 10 rows
to 7 — AI Overviews and both SERP-feature rows are answered and gone from the
list. The three that remain are honest: no keys for ChatGPT or Perplexity, and
Microsoft publishes no consumer Copilot API at all.

---

## And the new diagnostic immediately earned its keep

> **Google Gemini visibility not measured: every query failed — HTTPError: HTTP
> Error 404: Not Found.**

That row could not have said this last build. It is also two bugs at once.

### 1. The error body was being closed unread

`HTTP Error 404: Not Found` is urllib's status line and nothing else. Google
answers that 404 with a JSON body naming the exact problem:

```
models/gemini-2.0-flash is not found for API version v1beta,
or is not supported for generateContent.
```

`_post` opened the connection, hit the error, and let the body go without
reading it. Every provider shares that helper, so **every** AI platform error
has been arriving as a bare status code. Same shape as the DataForSEO envelope
and the save-ordering bug: the cause exists, it is one layer down, and nothing
unwraps it.

It now reads the body, pulls `error.message` out of the JSON, and keeps the
status and host so a 404 from a wrong base URL stays distinguishable from a 404
for a model name:

```
HTTP 404 from generativelanguage.googleapis.com: models/gemini-2.0-flash is
not found for API version v1beta, or is not supported for generateContent.
```

### 2. The model name was hardcoded

`GEMINI_MODEL` defaulted to `gemini-2.0-flash`. Which Gemini models are served
changes on Google's schedule, not ours, so a hardcoded name is a time bomb with
their hand on the timer: the row dies silently the day they retire it and stays
dead until somebody reads a checkpoint. That is exactly what happened.

The provider asks the key what it can actually call — `GET /v1beta/models`,
filtered to those supporting `generateContent` — and picks from that against a
preference order, caching the answer for the run. An explicit `GEMINI_MODEL`
still wins, because an operator who sets one has expressed a preference and a
preference beats a default. A flash-shaped model you have never heard of beats
failing. And a key that lists nothing says what that usually means:

> No Gemini model on this key supports generateContent — and the model list
> could not be read, which usually means `GEMINI_API_KEY` is wrong or the
> Generative Language API is not enabled on that project.

**You may not need to set anything.** Deploy this and Gemini should resolve a
current model by itself. If it still fails, the row will now name the reason
rather than the status code.

---

## What to run

Nothing new since the last reply — this changes what a run *reports*, and the
rows are written at scan time, so:

1. Deploy, let the worker restart.
2. **Scan site** with *Reuse the last crawl* and *Ask the AI assistants* ticked.
3. Then the capture, on the audit that scan produces.

Same order as before: the scan makes a new audit, so a capture run before it is
thrown away.

---

## `engine/aivis/providers.py` has never been in a delta zip

The delta zips were packed from a file list I maintained by hand. That file was
not on it. Not once.

So: the AI Overview provider learned to speak DataForSEO in build ‑38. It was
tested. It was written up in three changelogs, including mine two replies ago
where I told you *"the provider was fixed in ‑38."* The code was fixed. **The
file never went in a zip, never reached your repo, and has never run on your
worker.** Every fix since was made against code your deployed worker does not
have, and the symptom — AI Overviews measuring nothing — read as a credential
problem the entire time.

Your own API gave it away:

```
/api/capabilities   dataforseo: true
                    ai_missing: ["ai_overview", "chatgpt", "copilot", "perplexity"]
```

DataForSEO configured and working — your backlink rows (GSC-20/21/22) come from
it — while the provider that was taught to use it reports itself unavailable.
That combination is impossible in the code I have been editing. It is exactly
what you get when the file on the server is the one from before ‑38.

I said in the last two replies that the SERP fix had shipped. It had not. I was
reading my own source instead of yours.

### The packaging is generated now

`pack.py` builds the list off the filesystem — every tracked source file newer
than the baseline — and prints what it packed:

```
python3 pack.py --list      # see the list, pack nothing
python3 pack.py             # -> vici-audit-<BUILD>.zip
```

A hand-maintained manifest is a silent-failure machine: a file you forget
reports no error at all. Every other quiet truncation in this codebase got a
loud replacement; this one gets a generated list and a test in
`tests/test_deps.py` that walks the tree and fails if any changed source file
falls outside the delta — plus a second one naming `providers.py` specifically,
because a general rule that happens to cover a past failure is worth naming the
failure.

The 26 files that were never shipping:

```
DESIGN.md  ENGINE.md  VOICE.md  google-setup-runbook.html  make_ai_fixture.py
app/capture.py  app/schedule.py  app/ui_aivis.py
engine/aivis/__init__.py  engine/aivis/monitor.py  engine/aivis/providers.py
engine/checks/geo_schema.py  engine/checks/security.py
engine/collectors/__init__.py  engine/collectors/backlinks.py
tests/__init__.py  tests/_fixture.py  verify_ai.py
tests/test_blocked_crawl.py  tests/test_capture.py  tests/test_deps.py
tests/test_e2e.py  tests/test_sampling.py  tests/test_unreachable.py
tests/test_waf_shell.py
```

Nothing was dropped from the old list — the generated one is a strict superset.

---

## A skipped platform was reported as a failed one

Second fault, independent of the first, and visible in the run you just did.

`run_panel` computed the `skipped` list **only when it had to build the provider
list itself**. The audit worker calls `active_providers()` first so it can log
the platform names, then passes the providers in — so `skipped` stayed empty.
The aggregate said nothing was skipped, and four checkpoints for four
unconfigured platforms reported *"no successful responses collected, and no
error was recorded — that is a bug on our side."*

It was not a bug on our side. It was four platforms with no credentials, which
is what your extras said all along:

```
"platforms": "claude, gemini",
"skipped": ["perplexity", "chatgpt", "ai_overview", "copilot"]
```

The worker computed that list, stored it, and never handed it to the thing that
writes the rows. Fixed at both ends, with a test asserting the worker actually
passes it rather than just that the parameter exists.

---

## The SERP rows have now been wrong in both directions

First they said *"Configure SERP_ENDPOINT / SERP_API_KEY"* long after DataForSEO
could answer them — telling you to buy a second SERP subscription to replace one
you already pay for. Then I fixed that by asserting the opposite: *"DataForSEO
is already configured here, so nothing else is needed"* — which printed on a run
where you HAD ticked the box and the provider was skipped as unavailable.

Same mistake, sign flipped. A row that guesses is worse than a row that asks.
Three states, three sentences:

| state | what the row says |
|---|---|
| provider not configured | *the SERP provider that answers it is not configured on this worker* → set `DFS_LOGIN` / `DFS_PASSWORD` |
| query ran and failed | *the SERP query ran and failed* → and the provider's own message |
| phase not run | *no SERP query ran for this audit* → tick the box |

---

## What to expect after deploying this

Once `providers.py` is actually on the worker, `ai_overview` should move from
`ai_missing` into `ai_platforms` on `/api/capabilities`, because DataForSEO is
already configured there. Check that first — it is a one-line confirmation that
this deploy did what the last three could not:

```
curl -s https://vici-audit-api.onrender.com/api/capabilities | grep ai_
```

If it still lists `ai_overview` under `ai_missing` after the worker restarts,
the provider is reaching DataForSEO and refusing it for a reason of its own, and
the row will now print that reason instead of a shrug.

`copilot` stays missing and that is correct — Microsoft publishes no consumer
API for it, and the provider says so rather than returning zeros.

---

## The status is worn by the field it describes

Three pills in a block of their own, sitting directly above three dropdowns
that already named the same three properties. `https://ootenlawfirm.com/ · via
reporting-zone` printed twice on one screen, six inches apart, and the reader
had to work out that the two halves were the same fact.

The mark and one word now sit on the label; the block is gone.

```
Search Console property  ✓ found        GA4 property  ✓ found
[ https://ootenlawfirm.com/ · reporting-zone ▾ ]
```

On a match nothing else is printed — the selected option already reads
`property · login`, so a note under it would be the same duplication one level
down. On a miss the sentence that explains it goes under the select that can
fix it:

```
Search Console property  ! no quick match
[ https://ootenlawfirm.com/ · reporting-zone ▾ ]
No quick match — the audit looks wider than this URL. Pick the right one below.
```

All four states survive the move, including the one that matters most: `ours
to fix` stays amber rather than red, because a red cross next to "Tag Manager"
reads as the client withholding access and sends someone to write an email
about two minutes of our own re-consent.

## A CSS collision that only appeared in the failure state

The first cut named the modifiers `.amark.good` / `.amark.warn` / `.amark.bad`.
**`.warn` is already a callout box in this stylesheet** — 8px of padding and a
3px gold left border — so the amber badge inherited both, rendered 34.6px tall
against the green one's 21px, and pushed its whole column 22px out of line with
the other two.

Nothing errored. The green state looked perfect, which is the state anyone
would screenshot. I only caught it because I rendered the page in a headless
browser and measured the boxes:

```
gsc mark_h 34.6   sel_y 795.8      <- amber
ga4 mark_h 34.6   sel_y 795.8      <- amber
gtm mark_h 21.0   sel_y 774.3      <- red, and 22px higher than its neighbours
```

The classes are namespaced now (`.amark--ok`, `.amark--hold`, `.amark--no`) and
all three measure 21.0 with their selects at the same y. A test extracts the
badge's modifier class names out of the rendered page and fails if any of them
is also a bare selector elsewhere in the stylesheet — the guard catches the
exact bug I shipped, verified by replaying it:

```
mods: ['bad', 'good', 'warn']
clash the guard would have caught: ['warn']
```

## And the dashboard's JavaScript is now checked by a test, not by memory

This script is built inside a Python f-string, so `\n` becomes a real newline
before the browser ever sees it. That has broken twice — once closing a regex
literal mid-expression, once splitting a `//` comment so its second half parsed
as code. Both shipped. Neither was visible from Python: the page rendered fine
and the script was dead.

`node --check` on the rendered output now runs in `tests/test_manage.py`, and
skips loudly rather than silently if node is missing.

---

## Read your live audit before writing any of this

`b1437dd7` at 18:47 UTC, straight off the API:

```
GSC-05  Info          gsc_ui_capture   Search Console reports 56 indexed pages.
GSC-06  Warning       gsc_ui_capture   115 of 171 known pages are not indexed (67%).
GSC-07  Warning       gsc_ui_capture   46 pages in "Crawled - currently not indexed".
GSC-08  Pass          gsc_ui_capture   No pages in "Discovered - currently not indexed".
GSC-09  Need Access   gsc_ui_only      Google publishes this in Search Console…
GSC-10  Need Access   gsc_ui_only      Google publishes this in Search Console…
GSC-11  Need Access   gsc_ui_only      Google publishes this in Search Console…
GSC-19  Need Access   gsc_ui_only      Google publishes this in Search Console…
```

**The capture worked.** Four rows carry `gsc_ui_capture` and real numbers. What
is left is four rows and three separate faults, and the numbers above give all
three away.

---

## 46 of 115. The capture read five reasons out of a table of twelve

`SC_REASONS` held the five labels that map to checkpoints. Google's exclusion
table has about a dozen rows, and the ones we ignored are usually the biggest:
*Alternate page with proper canonical tag*, *Page with redirect*, *Duplicate
without user-selected canonical*.

So the read found two rows totalling **46** on a report that says **115** pages
are not indexed. Sixty-nine excluded pages sat in rows nobody looked at — and
worse, "Soft 404" being absent proved nothing at all. It could have meant zero
soft 404s, or it could have meant a row we never read. Both were indistinguish-
able, so the honest thing was to report neither, which is why GSC-09/10/11 came
back saying *"Google publishes no API for this — read it by hand"* immediately
after a capture that had just run.

Two changes settle it:

**The extension reads Google's whole exclusion vocabulary**, not just the five
mapped ones. Twelve labels, Google's wording, with curly apostrophes normalized
so *Excluded by ‘noindex’ tag* cannot silently never match.

**The arithmetic licenses the zero.** When the captured rows account for every
not-indexed page, the table was read whole, and a reason not on it has zero
pages — that is a measurement, not a guess. When they do not add up, the row
says so with both numbers:

> Not measured: the capture read exclusion rows covering 46 of 115 not-indexed
> pages, and "Soft 404" was not among them — so this is unread rather than zero.
> → Run the capture again, or read this row directly. A partial read here is
> ours to fix, not the client's.

That is the loud thing a silent gap was never going to be. The extension's own
log now says it at the moment of the read, too — `accounting for 46 of 115 not
indexed — INCOMPLETE` rather than the previous `2 reason rows, indexed 56`,
which read like a success.

The unmapped rows stop being thrown away as well: the largest reasons are named
on GSC-06 and the full breakdown is kept as structured evidence, so the 69 pages
have somewhere to be.

---

## "no successful responses collected" was hiding the answer

> Google AI Overviews visibility not measured: no successful responses collected.

`aggregate()` builds `by_platform` from **successful** answers, so a platform
where every call failed does not appear in it at all. The row then described the
silence. The provider had raised something specific — `DataForSEO SERP returned
40401: invalid credentials`, or whatever it actually was — and that message
reached a counter and died there.

This is the same shape as the save-ordering bug and the truncation bug: *an
error carried inside a success needs unwrapping, or it is not an error to anyone
downstream.* The aggregate now carries `platform_errors` — count, successes and
up to three distinct messages per platform — and the checkpoint prints them:

> Google AI Overviews visibility not measured: every query failed — DataForSEO
> SERP returned 40401: invalid credentials.
> → This is our error, not a missing client permission.

Three outcomes, three different sentences: not configured (a credential),
failed with a message (ours, and here it is), returned nothing with no error
recorded (also ours, and stated as a bug rather than dressed up).

**On your next run this row will finally tell us why AI Overviews is empty.**
I still do not know — that is the point. It has never been able to say.

---

## GSC-19 was being sent to the wrong Search Console report

GSC-19 is **Internal links**, which lives under Links. The fallback routed
everything that was not Core Web Vitals or Enhancements to Indexing → Pages, so
a row about internal linking told you to go and read the "Why pages aren't
indexed" table. A row sent to the wrong report is worse than one sent to none:
it wastes the trip and it makes the other instructions look untrustworthy. It
now points at Links → Internal links with its own instructions.

---

## One correction to what I told you last time

I said the SERP-feature rows were GEO-19 and GEO-20. They are **GEO-24**
(Featured Snippets) and **GEO-25** (Passage-based / long-tail ranking). GEO-19
is a schema-coverage row and has nothing to do with it. The fix in ‑49 was on
the right rows; I named them wrong in the write-up.

---

## Why your panel still showed the old SERP text

Findings are **stored**, and the recommendation text is composed at scan time
and saved with the row. The ‑49 fix changes what gets written on the *next*
run; it cannot reach into an audit that already ran. `b1437dd7` was scanned
before ‑49 went live, so it is still carrying the old sentence and will keep
carrying it. Scan the site again and those two rows change.

---

## Tests

Sixteen new assertions across three suites:

```
A COMPLETE TABLE LICENSES A ZERO; AN INCOMPLETE ONE DOES NOT
  PASS  a partial read never turns an unseen reason into a Pass  (Need Access)
  PASS  and it says so with both numbers, not with silence
  PASS  a complete table makes an absent reason a measured zero  (Pass)
  PASS  a captured row still beats the inference

AND THE UNMAPPED ROWS ARE NOT THROWN AWAY
  PASS  the largest reasons are named on the excluded-pages row
  PASS  and the full breakdown is kept as structured evidence

A PLATFORM THAT FAILED EVERY QUERY SAYS WHY
  PASS  the provider's own message reaches the row  (…40401…)
  PASS  and it is named as ours, not a client permission
  PASS  silence with no error recorded is reported as a bug on our side
```

One test also had to be fixed rather than added. It asserted the wait anchor
`"why aren't pages indexed"` — and passed the entire time the anchor was broken,
because the phrase survived in a comment two lines above the code. A test that
greps a file will do that. It now asserts the actual call.

---

## The SERP rows never asked DataForSEO — they only ever talked about it

You asked: *wasn't the serp fixed to use dataforseo?* It was, in ‑38. The
provider falls through to `/serp/google/organic/live/advanced` and unwraps the
envelope properly.

Two rows never went near the provider. `GEO-19` and `GEO-20` — Featured
Snippets and People Also Ask — are answered by `engine/aivis/geo_checks.py`,
which writes its own recommendation text, and that text still said:

> Configure `SERP_ENDPOINT` and `SERP_API_KEY` on the worker.

Nothing connected that sentence to the provider, so fixing the provider could
not possibly have changed it. It survived because it was never code that ran —
it was a string. You read a fix-me for a variable you do not need, on a row
whose data source has been configured for two builds.

The rows now read the capability and say the true thing:

> Featured Snippets is a Google SERP feature, not an AI chat platform, and no
> SERP query ran for this audit.
> → Tick **Ask the AI assistants** — the SERP query goes through DataForSEO,
> which is already configured here, so nothing else is needed.

That is the whole fix. The measurement was always available; the row was
telling you to go buy a key for it.

---

## Conversion URLs did not save, and neither did four other fields

This one was real and worse than reported.

Every one of these was parsed inside `if run_consent:` in `submit_form`:

- conversion URLs
- products they bought
- industry
- implementation
- the states derived from the markets

Tick **Full audit**, leave the consent box alone, and the form posted all five
correctly — and the server read them, and dropped them on the floor. The
settings panel then rendered them back off the stored options, found nothing,
and printed `—`. The field looked like it lost your typing. It did not: it
posted fine and the guard ate it.

None of those five is a consent setting. They describe the **client**. They now
sit on the record whichever job ran, so the settings panel shows them, a re-run
prefills from them, and nobody retypes fourteen landing pages because the
consent box happened to be off.

`run_consent` itself is still the only thing that decides whether the phase
runs. The consent scan reads these when it runs; it just no longer owns them.

Guarded by six new assertions in `tests/test_consent.py` that post a full audit
with the consent box **unticked** and check all five survive:

```
THE CLIENT PROFILE SURVIVES A RUN WITH CONSENT UNTICKED
  PASS  the consent phase is correctly OFF
  PASS  but the conversion URLs are still on the record
  PASS  the products too
  PASS  the industry too
  PASS  the implementation too
  PASS  and the states derived from the markets, not from a guess  (['TN'])
```

---

## The capture waited for my wording, not Google's

The poll anchored on the string `"why aren't pages indexed"`. Google's heading
is **"Why pages aren't indexed"** — same five words, different order. The test
was `innerText.includes(...)`, so it never matched, and the capture spent its
full forty seconds on a page that had finished rendering before the first poll.
Your log said *"Indexing report did not finish loading — are you signed in?"*
on a report that was fully loaded and signed in.

It now waits on `SC_REASONS` — the exclusion labels themselves, the strings we
came to read. If any one of them is on screen the table is there. Anchoring on
the data instead of on the furniture around it also removes the class of bug
where Google re-words a heading and the capture silently stops working.

## And a failed capture no longer strands you in Search Console

Both exits go through one `scReturn(tab, reload)`: close the Search Console
tab, return to the audit page, reload it on success so the new rows are there.
Before, the success path came back and the failure path left you sitting on
Google's screen wondering whether to press the button again.

---

## What the log said, and the three things it exposed

The diagnostic paid for itself on its first run:

```
No exclusion reasons found. Labels seen on the page:
Feedback | | | 154 | Google Search Console | Search property | |
Privacy | Terms | Page indexing | | EXPORT | | Google Sheets |
Download Excel | Download CSV
```

Sixteen strings, every one of them page furniture, on a report with a full
table on screen. Three separate faults, none of which was guessable from here.

### 1. It waited for a byte count, and the shell cleared it

`scOpen` polled until `innerText` passed 400 characters. That list above is
already past 400 with **none of the report in it** — the chrome renders first
and the table lands seconds later. So every read caught a rendered frame around
an empty table and dutifully reported two numbers and no reasons.

It now waits for **the thing it came for**: the string *"Why aren't pages
indexed"*, which is the heading directly above the exclusion table. Present
means the table is there to read. The byte count survives only as a fallback
for reports with no known anchor.

### 2. The scrape only looked at strict leaf nodes

`children.length === 0` skipped every label Search Console wraps in one or two
more elements than you would expect — which is most of them. It now takes any
element holding a short string with at most two descendants.

### 3. `/search-console/enhancements` does not exist

That is the 404 you hit. Search Console has **no single Enhancements page**:
breadcrumbs, FAQ, videos and review snippets each have their own URL, and each
exists only for a site that actually has that markup. The step is gone.
Opening a URL that cannot exist cost thirty seconds and a Google error screen,
which is worse than not trying — it looks like the capture is broken.

Also: a tab closed by hand mid-run now says so, instead of surfacing
`No tab with id: 972028235`, which is a stack trace pretending to be a message.

> **If the reasons still do not come**, the log will now show a much longer
> label list — that is the next clue, and it is one edit away rather than one
> guess. There is also a `Download CSV` in that export menu, which is Google's
> own supported path to the same numbers and the obvious fallback if reading
> the rendered table keeps disappointing.

---

## One press, every report — and the SERP failure names itself

**No, you should not have to press it repeatedly.** One press has always
opened more than one report; it was filling two rows because the exclusion
table never resolved, not because it only does one thing at a time.

Three changes:

**Enhancements is in the run now.** It read Indexing and Core Web Vitals and
stopped. Rich results, breadcrumbs, FAQ and video each get their own row in
Search Console and each answers a checkpoint, so *"capture these"* quietly
meant *"capture some of these"*. The button says **Capture all of these** and
now means it.

**A partial capture reports what it saw.** When the exclusion table does not
resolve, the log prints the labels that WERE on the page:

> No exclusion reasons found. Labels seen on the page: Indexed | Not indexed |
> Page indexing | Why pages aren't indexed | …

Without that, the only way to find out why is to guess at Google's markup from
a thousand miles away. Those labels turn the next fix into one edit instead of
one deploy — the same move that finally cracked the `domain_pages` endpoint.

**And the AI Overviews row stops saying "no successful responses collected."**
DataForSEO reports its own errors **inside a 200** — a bad location code, an
unpaid balance and an unknown keyword all arrive as a `status_code` in the
envelope rather than as an HTTP failure. So nothing raised, nothing logged, and
the row reported an absence with no cause. The provider now reads that envelope
and fails loudly:

> DataForSEO SERP returned 40401: Payment Required.

That is the third silent failure today with the same shape, and the same fix:
**an error carried inside a success needs unwrapping, or it is not an error to
anyone downstream.**

---

## The capture sends itself and puts you back

**Site Scanner 1.4.0.** No popup trip.

You pressed a button on the audit page, so the audit page is where the answer
belongs. A capture that ends by telling you to go and find another window and
press a second button is a capture most people abandon — the confirmation was
the right instinct in the wrong place.

It now reads the reports, posts them, closes the Search Console tab, switches
you back to the audit and reloads it. The captured rows are simply there.

**Nothing is hidden by that.** Every captured row renders in the report with
its value and a `captured_from: Search Console UI` marker, and running the
capture again overwrites it — so a wrong number is one click from being right,
rather than one click from being sent. The popup keeps the figures as a
**correction** path: change one and press *Re-send corrected*.

### And it scrolls now

Your first live run found the summary — 56 indexed, 115 not indexed — and none
of the exclusion reasons. That is the shape of a page read before it finished:
Search Console renders the *"Why pages aren't indexed"* table below the fold
and builds it lazily, so a read without scrolling gets the two numbers at the
top and stops. The capture now walks the page down and back before reading.

---

## "Run again" fills the form

You are right that it was clunky, and it was worse than clunky.

**Run again** used to POST straight to `/rerun`, which copied the previous
audit's stored options verbatim and queued it. So the settings you were about
to change were invisible, and an option added *after* the first run could never
turn on — that is exactly what left twelve consecutive Ooten runs with no
consent phase, inheriting an options blob written before the checkbox existed.

And there was a second button under the settings table already doing what
people actually wanted: *put these back in the form so I can change one thing*.
That is what "run again" means. So that is what the button does, and the other
one is gone.

It now loads every setting into the form, scrolls you to it, and says so:

> *Settings loaded from The Ooten Law Firm — change anything, then Scan site.*

The `/rerun` endpoint stays for the JSON API and the stalled-run panel, where
"same settings, no questions" is the right behaviour. It is no longer what a
button on the dashboard does.

---

## Three settings that never saved

Implementation, Products and Conversion URLs shipped on the form in ‑39 and
were never added to the settings dict — so they were stored on the audit,
missing from "Settings used", and dropped by the prefill. **The same omission
that cost states and industries five builds, repeated on three more fields two
builds later.**

All three are now stored, displayed and restored, and `test_manage` asserts
each one is in the prefill payload rather than trusting that I remembered.

Vertical and Primary conversion have come off that panel too. They left the
form in ‑41, and listing them as settings "used" implied they could be changed
— on a panel whose entire job is to be loaded back into a form that no longer
has them.

---

## Multiple Google accounts, without signing out of any of them

Chrome signs you into several at once and Search Console opens under whichever
is default — so a capture run while signed in as `kiri@vicimediainc.com` hits
*"Oops, you don't have access to this property"* even though
`digital@reporting.zone`, in the same browser, can see it fine.

**Site Scanner 1.3.1** takes a **Google account** in the popup and appends
`authuser` to every Search Console URL. Set it once; it is remembered.

> **Put the email, not an index.** `/u/1/` and `authuser=1` both address an
> account by its *position in the sign-in list*, and that position changes the
> moment an account is added or removed — so a saved index quietly starts
> pointing at a different person, which is a worse failure than the one it
> fixes. An email addresses the account itself.

Blank still means the default account, which is right for anyone signed into
one.

### And the wrong-account screen is recognised

Without this the scrape simply finds nothing and reports *"nothing recognised
— Google may have renamed a label"*, which points at the parser when the truth
is a sign-in. The capture now detects Google's denial page, **reads the account
it actually used off it**, and stops:

> Search Console opened as **kiri@vicimediainc.com**, which cannot see this
> property. Set the Google account in the popup to the one that can — an
> email, not an index — and run it again.

Same rule as the rest of this build: a failure that names itself, rather than
an empty result that sends someone looking in the wrong place.

---

## THE BROWSER: `No module named 'playwright'`

Your screenshot has the answer in it, and it is not the one anyone guessed:

> **The browser did not start on the worker — Playwright is not importable on
> this worker: No module named 'playwright'** — so this fell back to a basic
> scan of the raw HTML.

Not memory. Not the sandbox. Not the deploy. **The module was never importable
in the running container**, so the consent scan has fallen back to parsing raw
HTML on every run since it shipped, and five checkpoints went unanswered for
weeks.

`requirements.txt` said, with a paragraph of reasoning:

> *NOTE: playwright is deliberately NOT listed. The base image already ships
> it, pinned to the browser build baked into the image.*

The reasoning was sound — reinstalling can drag the package past the bundled
Chromium and produce a confusing "executable doesn't exist". It was also, in
production, wrong. What mattered was whether **the interpreter that runs our
code** could import it, and nothing checked.

Two changes:

- **`playwright==1.42.0` is pinned**, to the same version the base image is
  built from, so the package and the browsers at `PLAYWRIGHT_BROWSERS_PATH`
  stay in step and the original concern does not come back.
- **The Dockerfile asserts the import at build time.** The existing check
  (`import app.api, app.worker`) passes with or without it, because the
  scanner imports Playwright lazily and degrades on purpose. That fallback is
  correct at runtime and it is exactly what made a missing module invisible at
  build: the image built clean, the worker started clean, and every consent
  scan quietly answered four of nine questions. One line, and it fails the
  build instead of degrading a client report.

This is the third time today a correct defensive fallback hid the thing it was
defending against. Worth remembering as a pattern: **a graceful degradation
needs something loud somewhere else, or it is just a silent failure with good
manners.**

---

## The form's helper text is on hover now

Every one of those grey lines was true and none was needed twice. Together
they turned a nine-field form into a wall of prose and the fields stopped being
findable. They are on a small `i` beside each label — there when wanted, gone
when not.

"Blank uses the configured firm name" is gone from the page entirely, as asked;
it survives inside the Partner name tooltip.

The bubble is **left-aligned to its marker rather than centered on it** — centering
put half of it off the left edge of the viewport for every field in the first
column, which is readable in the middle of the form and clipped everywhere it
mattered.

---

## The capture button you could not see

It was there. It shipped `display:none`, revealed only by the extension's
content script — tidy, and useless: someone told the button exists, looking at
a page with no button, cannot tell a missing extension from a broken build.

It is always visible now, with the caveat beside it — *"Needs the Site Scanner
extension, version 1.3 or newer — download, then reload it at
chrome://extensions"* — and the extension removes that line when it is present.

---

## Nothing is pasted any more

"Paste the audit id" was asking someone to copy a sixteen-character hex string
out of the URL bar of the tab next door — three chances to get it wrong before
anything has been measured. Two changes, so it is never typed:

**A button on the report itself.** The *"Google publishes no API for this"*
panel now carries **Capture these from Search Console**, sitting directly under
the eight rows it fills. The audit id and the Search Console property are
already on that page, so the extension reads both off it and asks for nothing.
The button stays hidden until the extension's content script marks the element
present — a browser without it sees the honest instruction rather than a
control that does nothing.

**And the popup fills itself in.** Open it on any audit page or PDF URL and the
id is already there, with the field saying where it came from. A pasted id is
never overwritten: a typed value beats a guess.

If an audit never had a Search Console property pinned, the button asks once
rather than guessing — reading the wrong property is worse than reading none.

---

## The extension reads Search Console's UI-only reports

Eight checkpoints are published by Google in the interface and exposed through
no API. Honest about it since ‑40 — and honest and unmeasured is still
unmeasured, with someone retyping numbers off a screen into nothing.

The extension already runs in your own signed-in Chrome, which is exactly what
those reports require. So it reads them there. **Site Scanner 1.3.0**, new
button: **Search Console capture**.

It opens Indexing → Pages and Core Web Vitals for the property, reads them, and
maps the figures onto the checkpoints that ask for them:

| Report row | Checkpoint |
|---|---|
| Indexed | GSC-05 |
| Not indexed | GSC-06 |
| Crawled - currently not indexed | GSC-07 |
| Discovered - currently not indexed | GSC-08 |
| Soft 404 | GSC-09 |
| Server error (5xx) | GSC-10 |
| Redirect error | GSC-11 |
| Core Web Vitals Poor / Needs improvement | GSC-12 |

That mapping is not a coincidence — the exclusion reasons Search Console lists
under *"Why pages aren't indexed"* **are** those checkpoints, one for one.

### It anchors on Google's words, not Google's markup

The scrape matches the visible English labels — `Crawled - currently not
indexed`, `Soft 404` — rather than class names. Search Console is an obfuscated
Angular build whose class names change without notice; the label is the string
on the screen and in Google's own documentation. When Google does rename one,
the capture returns **nothing** for that row rather than the wrong row's number.

### And it never sends without a person looking

The scrape is a first draft. What it found appears in the popup as **editable
fields**, and nothing posts until you press Send. If a number landed in the
wrong row the fix is right there.

That is deliberate, and it is the difference between a tool people trust and
one they abandon the first time it is quietly wrong. A number read off the
wrong table becomes a number in a client report, and there is a person at the
keyboard three feet away.

### Nothing is invented

Every field is optional and a missing one stays unmeasured. A capture that
half-worked leaves the other half alone rather than filling it with zeros — a
zero in the exclusion reports reads as *"no pages excluded"*, which is a
materially wrong statement about a site rather than a smaller version of the
right one. `test_console_capture` holds that: one number in, one row out.

Provenance travels with every row — `captured_from: Search Console UI`, the
timestamp, and a `gsc_ui_capture` source tag that separates it from a failed
API call. A number read off a screen and a number pulled from an API are not
the same kind of fact, and nobody will remember which in six months.

### A count is not a verdict

Every site of any age has a few soft 404s. Calling nine of them a failure is
how a row gets skipped every time thereafter. Zero is a clean pass; anything
else is reported as a measurement with the number attached; only a large share
of the indexed count earns a Warning, and nothing here is ever worse than one.
Core Web Vitals is the exception — a Poor group is a Fail, because it is a
failing template rather than a tally.

**Consent dashboard is next.**

---

## Why you kept seeing the same error: the panel truncated the fix

You were right to push. The diagnosis **was** being generated — and the panel
was cutting it off.

`reasons()` truncated evidence to 110 characters, and the new diagnosis sits at
the **end** of the sentence:

```
This ran as a basic scan — raw HTML with no browser — which cannot see
the banner, Consent Mode, or what fired before consent. The browser did
not start: BrowserType.launch: …
└──────────────── first 110 characters ────────────────┘ ✂
```

So the moment the scanner started reporting *why*, the panel chopped it
mid-clause and printed the identical unhelpful line it had printed for three
builds. Everything was fixed except the last forty characters of the string,
which were the only ones that mattered.

The tell was in your screenshot all along: the sub-line read *"This is a worker
deployment problem, not a client one"* — which is the recommendation emitted
**only when a cause was recorded**. The cause existed. It just never reached
the page.

Two changes: the panel groups on a short key and **displays the whole string**,
and the evidence now **leads with the cause**, so any future truncation loses
the explanation of what a basic scan is — which never changes — before it
loses the exception.

> **The browser did not start on the worker — BrowserType.launch: Executable
> doesn't exist at /ms-playwright/… — so this fell back to a basic scan of the
> raw HTML**, which cannot see the banner, Consent Mode, or what fired before
> consent.

---

## The eight Search Console rows now carry a route, not just a verdict

You asked whether this is forever manual. For those eight, yes — Google
publishes them in the interface and exposes no API. But *"read this from the
Search Console UI"* is not an instruction: it does not say which of eleven
reports, or where, and we already know the property.

Each row now carries the report name, a **deep link straight to that report for
that property**, and what to record when it opens:

| Rows | Report | What to record |
|---|---|---|
| Index coverage | Indexing → Pages | Total indexed, and the top three exclusion reasons by page count |
| Core Web Vitals | Experience → Core Web Vitals | Mobile first: Poor and Needs-improvement URL counts, and the metric named for each |
| Enhancements | Enhancements | Valid / warning / error counts per structured-data type |

The link is built from the property already selected on the form, so it opens
on the right site rather than the property picker.

**On the extension:** it could capture these, and that is a genuinely good idea
— it already runs in a signed-in browser, which is exactly what these reports
need. It is not in this build. Worth doing after the consent dashboard.

---

## The form, rebuilt

- **"Run audit" → "Scan site."**
- **Order**, as asked: client name, client website *(renamed from Target URL)*,
  industry, partner name, primary markets, products, conversion URLs, Google
  access, then the two jobs.
- **"What to run" is two jobs, not seven checkboxes.** Full audit and consent
  check are a separate product and a phase of one, and the old strip made them
  look like peers — untick every audit phase and you still got a 150-page crawl
  doing nothing with the result. Each job now opens its own settings; unticking
  the audit drops to the one-page consent path that already existed. Both on by
  default, either can be off, and the button says which you are about to run.
- **One control for industry**, not a filter box beside a select. A datalist
  *is* the filter: type to narrow, or open and scroll.
- **Vertical and Primary conversion are gone.** Industry says what the business
  is far more precisely than four hardcoded verticals, and the conversion was
  intake nobody filled in and nothing branched on. Both still accepted by the
  JSON API, so scripts keep working and old audits still render what they
  stored.
- **Rounder corners** throughout, and the form lays itself out — a leftover
  five-column grid rule was turning the reordered fields into a collage.

---

## Conversion URLs, the way the scanner does it

**No cap.** Six was arbitrary and silent, which makes it the same failure as
every other quiet truncation here: a list that looks complete and is not. A
client with fourteen landing pages has fourteen pages where a conversion pixel
can fire ungated.

**URLs are harvested out of whatever gets pasted, not split on whitespace.**
Lifted from the standalone scanner, which learned this the hard way — people
paste a line out of an email and splitting turns every word into a pill. A real
TLD is required, so `e.g.` and sentence fragments never qualify, and trailing
punctuation is stripped so a URL at the end of a sentence survives the full
stop. Verified in a browser against a deliberately messy paste:

```
"thank you page is srmel.com/thanks (and the quote form at
 https://www.srmel.com/quote/), plus SRMEL.COM/THANKS/ again and
 srmel.com itself. e.g. see notes."
                        ↓
srmel.com/thanks    https://www.srmel.com/quote/
```

Everything else dropped: the prose, `e.g.`, the duplicate in different case
with a trailing slash, and the homepage itself — **the main site wins**, since
it is already scanned and adding it again would double every pixel found there.

De-duplication normalizes the way the scanner's own `normUrl` does: scheme,
`www.` and trailing slashes are noise, so `/contact` and
`https://www.site.com/contact/` are one URL rather than two pills scanning the
same page twice. Done in the browser *and* again on the server.

---

## "Ours to fix" was carrying something that will never be fixed

Eight of those rows were Index Coverage, Core Web Vitals and the rest that
Google publishes in the Search Console UI and exposes through **no API**. They
sat under *"a credential we have not set, or a call we have not written."*
There is no credential and no call. They will be there on every run forever.

A permanent entry on a to-do list is how the whole list stops being read — the
same failure as the analyst section and the unticked phases, in a third
costume. They now have their own heading:

> **Google publishes no API for this · 8**
> Read from the Search Console interface by hand, or skipped. Nothing to
> configure and nothing that will change — this is a limit of Google's API,
> not a gap in the run.

Which leaves **Ours to fix · 1** on that report: the one genuine miss.

---

## The consent inputs the standalone tool always had

### The state pill said TN twice

"Anderson County, TN" beside a `TN` tag is the state printed twice. The label
is stripped now and the tag carries it — `Anderson County · TN`. The full
string is still what submits and still what the tooltip shows.

### States are a toggle row, not a text field

Free text was the wrong control for a closed set of twenty: it cannot show
what the options *are*, so a state we can check was invisible unless you
already knew to type it. All twenty are on the form now.

Two visual states, because they mean different things:

| | |
|---|---|
| **Filled** | you chose it |
| **Outlined** | your markets imply it, nobody has confirmed it |

Click a suggestion and it becomes a choice. Click it again and it is off and
stays off, even if the markets keep implying it — a decision outranks a
derivation.

### Products, conversion URLs, implementation

Three inputs the standalone scanner has and the audit never carried:

- **Products** — all eleven the scanner knows, as toggles. Without them the
  scan reports what *is* firing. With them it can report what is **not**: a
  product the client pays for whose pixel never fires is invisible otherwise,
  and it is the finding with money attached.
- **Conversion URLs** — the scan looked at the homepage and said so. But a
  thank-you page is where the conversion pixels actually fire, which makes it
  the page most likely to carry an ungated one, and the page nobody was
  looking at. Up to six extra pages; site-level checks still run once on the
  homepage, exactly as the standalone tool does it.
- **Implementation** — Vici-owned GTM, client-owned GTM, client placement, or
  hardcoded. This decides who a finding is *addressed to*. A pixel firing
  pre-consent in a container we own is our work queue; the same pixel in a
  container the client controls is a conversation. Same finding, different
  owner, and the report could not tell them apart because nothing ever asked.

**All five wired end to end the same day they shipped**, and `test_geo` now
asserts it: the form accepts each one, the API stores it, and `_consent`
passes it to the scanner. Adding an input the server drops is the exact
failure this codebase spent a day chasing — `states` and `industries` sat on
the scanner's signature for five builds with nothing setting them, and two
checkpoints quietly answered nothing while the form looked complete.

Two JavaScript notes, same root cause as the last build: `'[,\\s]+'` survives
neither a Python f-string nor a JS string literal intact — it arrived as the
letter `s`, so the strip matched commas and esses and removed nothing. It is a
plain `[, ]` class now, which cannot be mangled. And `.note` was only styled
inside `.ph`, so every label ran its hint straight into its text.

---

## AI Overviews: you are already paying for this

The panel told you to configure `SERP_ENDPOINT` / `SERP_API_KEY`. **Don't.**

That adapter only spoke SerpApi's dialect — GET, `api_key=` in the query
string — so an install with DataForSEO credentials already set reported "not
measured" and sent the operator off to buy a second SERP provider. You have
one. AI Overviews are part of DataForSEO's **standard SERP API**, on the same
login already answering backlinks, rankings and Lighthouse, at **$0.0006 a
request** ($0.0012 with async overview loading).

Recommending a subscription to replace something already bought is a worse
failure than not measuring: it costs money and it makes the tool look like it
does not know what it is holding.

`AIOverviewProvider` now falls through to `serp/google/organic/live/advanced`
when no SerpApi endpoint is set, reading the `ai_overview` item's nested text
and its `references` array for citations. SerpApi still wins when explicitly
configured — setting `SERP_ENDPOINT` is a preference, and a preference beats a
default.

One call carries the AI Overview *and* the featured snippet *and* the rest of
the SERP features, so all three GEO rows that were each waiting on "a SERP
data provider" are answered by the same request.

---

## A basic scan now says what stopped the browser

Your worker is already Standard 2 GB, so the memory theory was wrong — and the
scanner has always launched with `--no-sandbox`, so it is not the usual
container problem either.

The reason full mode failed was printed to stdout and **dropped**. The report
said "this ran as a basic scan" and stopped, leaving the WHY in a worker log
that is gone by the time anyone reads the report — five checkpoints unanswered
and no route to answering them.

`scan_site` now records the launch failure on the result, and the five
browser-dependent rows carry it:

> **CONS-02 · Need access** — This ran as a basic scan — raw HTML with no
> browser — which cannot see the banner, Consent Mode, or what fired before
> consent. **The browser did not start: BrowserType.launch: Executable doesn't
> exist at /ms-playwright/…** *This is a worker deployment problem, not a
> client one.*

Marked in the source as a Vici addition rather than upstream, so the vendored
scanner still diffs cleanly against the standalone tool.

---

## Markets are pills, and they decide which laws get checked

Three things you asked for, and they turn out to be one thing.

### The states were a guess, and it was wrong for this client

The states box was prefilled `CA CO CT TX VA OR` — defensible in the abstract,
and wrong for every client who does not sell in those states. **A Knoxville law
firm was having California's law tested and Tennessee's ignored**, and nothing
in the report said so.

The markets field already knew the answer. `engine/geo.py` reads the state off
each market, and the consent scan now follows:

```
Anderson County, TN × Blount County, TN × Knox County, TN × …
                        ↓
                     states: TN
```

Type into the states box by hand and it detaches — an override is a decision
and is never overwritten.

### A state we cannot test is said out loud

Thirty states have no comprehensive law in the scanner's map. Dropping them
silently would leave a client in Georgia unable to tell *"we looked and there
is nothing to check"* from *"we forgot to look"*. Derived states render as
pills: green for the twenty we check, grey for the rest, with the count and a
sentence naming which is which.

### Markets are validated as you type

A pill per market, each stamped with its state code. A market that resolves to
no state — `Boise`, with no `, ID` — goes **amber**, not red: it is not invalid
input, it is input we cannot attribute to a body of law, which is a smaller and
more accurate claim. The hidden field still submits the same canonical string,
so the server contract is unchanged, and the server re-parses on submit rather
than trusting the browser.

Pasting a whole list still works — it splits on the same separators the server
does, so thirteen counties go in at once.

> **A separator that eats real data is worse than one that misses.** The first
> cut treated a bare `x` as a separator and turned "Knox County, TN" into "Kno"
> and "County, TN". Fairfax, Essex, Lennox and Bronx would all have gone the
> same way. `x` now separates only with whitespace on both sides, and
> `test_geo` holds each of those names as a single market.

### And the two fields that were not saving

`consent_states` and `consent_industries` were never in the settings dict, so
"Settings used" never showed them and the prefill button never restored them.
Every re-run started blank — and a blank states box means no state requirement
is checked at all, so forgetting cost a quietly thinner audit rather than a
visible gap. Both are now stored, displayed and restored.

Two JavaScript bugs worth recording, because they have the same cause: this
script lives inside a Python f-string, so a single `\n` is a real newline by
the time the page is written. One closed a regex literal mid-expression
("Invalid regular expression: missing /"); the other split a `//` comment in
half so its second line parsed as code. Escapes in that block have to be
doubled, and the rendered script is now syntax-checked with `node --check`
before it ships.

---

## THE ACTUAL CAUSE: the findings table was written before the phases ran

Everything I said about this before was wrong. It is not the scanner, not the
worker's keys, not a stale container. It is four lines of ordering in
`_score_and_save`:

```
db.save_findings(audit_id, findings)     ← line 4.  The ONLY write.
...
_consent(...)                            ← line 35. Adds 9 rows to the dict.
_ai_visibility(...)                      ← line 51. Adds 6 more.
db.save_scores(...) / db.update_audit(extras=...)
```

The two optional phases add their findings to the in-memory dict **after the
only write to the findings table**. Scoring then runs on that dict, and
`extras` is saved after that — so every downstream signal said the phases had
worked:

| Symptom | Why it lied |
|---|---|
| `extras.consent` and `extras.ai_visibility` populated | written after the phases, and they *had* run |
| Coverage read **322/322** | scoring reads the in-memory dict, which had all 15 |
| Findings table had none of the 15 | the only write happened 40 lines earlier |
| Panel said *"produced no result for this run"* | that is the message for a checkpoint with **no row at all** |

So the report insisted the phases produced nothing while the audit row proved
they had run. Every reading of that pointed outward — at Chromium, at platform
keys, at the deploy — and the scanner was working correctly the entire time.

**Fix:** save again after both phases. `save_findings` deletes and rewrites the
audit's rows, so the second call is idempotent and costs one statement. The
early save stays, because a crash inside an optional phase should still leave a
readable audit.

`test_e2e` now asserts the ordering structurally — the last write to the
findings table must come after the last phase that adds to it, and an early
save must still exist. That is the shape of the bug, so that is what the test
holds.

### This has been true since the consent phase shipped in ‑28

Every audit run since then dropped its consent rows, and every audit with AI
visibility ticked dropped those too. Nothing needs re-crawling — hit **Run
again** with the crawl reused and the rows will be there.

---

## Why nine consent rows have been empty on every Ooten run

Not the consent scanner. **The "Run again" button.**

It copies the previous audit's options, which is correct — "run it again"
means the same settings. But a key that is **absent** is not a decision to
leave that phase off; it is a run from before the phase existed. Replaying it
forever means a newly-shipped phase can never turn on.

Every Ooten audit — all twelve — carries the identical options blob:

```json
{"max_pages": 150, "skip_psi": false, "render_js": false,
 "primary_conversion": "call, contact us"}
```

No `run_consent`. No `run_aivis`. No `phases`. They all descend from one audit
created before those checkboxes were added, and each re-run faithfully
propagated a stale snapshot forward. The form has had **Consent & privacy
ticked by default the entire time** — nobody had opened the form since the
first run, so the default never applied.

`rerun_audit()` now fills an absent key with today's default and leaves a
present key alone. Absent is a gap; present is a decision, and decisions
survive:

| Stored options | Carried forward |
|---|---|
| no `run_consent` key (legacy audit) | `run_consent: true` — today's default |
| `run_consent: false` | `false` — someone chose that |
| `run_consent: true` | `true` |
| no `run_aivis` key | still absent — that phase is off by default |

### The second cause, which is not code

The panel *also* kept showing "Ours to fix" because the running API container
was serving `engine/report.py` from **before build ‑32** — the `.vbox` and
`vlist` CSS classes added then are absent from the live page, while
`/healthz` (which reads `app/version.py`) reported ‑35.

GitHub is fine: `main` has the current file, and so does the very commit
`/healthz` names. So the repo is right and the **container is stale** — either
an instance that never rebuilt, or an old instance still taking traffic
alongside a new one.

**Fix: Manual Deploy → Clear build cache & deploy, on both services.** Nothing
in this zip changes that; it has to be forced from the Render dashboard.

---

## A phase that bails now says why

Reloading the report did not move those fifteen rows, and the reason is a
second bug underneath the first.

`_consent()` and `_ai_visibility()` both had `return` statements on their
unhappy paths — a failed import, no platform keys — that wrote **nothing**.
Not a failed row, not an unanswered row: no finding at all for those
checkpoints. Which means:

- The retroactive fix in ‑34 could not classify them, because "not requested"
  is decided from the audit's options and these rows had been requested.
- The panel could only fall back to *"the consent and privacy scan produced no
  result for this run"* — true, and naming no cause, because a checkpoint with
  no finding has no evidence to quote.
- The actual cause was printed to the worker log and then dropped.

Every other part of this codebase treats an unmeasured thing as something that
must **say** it is unmeasured. These two made theirs vanish.

Both now write a full set of rows on every exit path, at zero confidence so
scoring still leaves them out, naming the cause and whose problem it is:

> **CONS-01…09 · Need access** — The consent scanner could not be loaded on
> this worker (ImportError: …). *This is a deployment problem, not a client one
> — the scanner needs Playwright and Chromium in the worker image.*

> **GEO-23…30 · Need access** — No AI platform keys are set on this worker, so
> no assistant was asked. *Set one or more of OPENAI_API_KEY,
> ANTHROPIC_API_KEY, PERPLEXITY_API_KEY or GEMINI_API_KEY on
> vici-audit-worker. Missing: chatgpt, perplexity, copilot, ai_overview.*

Silence became a diagnosis. The next run tells you which of the two it is
instead of leaving it to be inferred.

---

## "Ours to fix · 15" — now retroactive

Build ‑32 taught the panel to separate *"we asked for this and got nothing"*
from *"nobody ticked the box"*. It worked, and you still saw the old panel,
because the worker only started stamping `extras.phases_run` in ‑32 — so every
report that already existed fell to the conservative branch and kept printing
fifteen unticked checkpoints as fifteen defects. The exact panel ‑32 set out to
fix, still there on every report anyone would actually open.

**It never needed a stamp.** The audit row has always stored the options it was
submitted with, and `run_consent` / `run_aivis` are in them. `_extras()` now
derives `phases_run` from those whenever the worker did not record it, so the
fix applies to **every audit ever run**, with no re-run and no re-crawl.

A key missing from options means the phase was not requested — true both for a
run where the box was unticked and for one that predates the box existing.

The worker's stamp still wins where present: it records what the run actually
did, options record what was asked of it. Those agree today, and the stamp is
the one to trust if they ever diverge.

---

## Setup, made checkable

Three things that would have sent you down the wrong path while wiring up
Google.

**`/healthz` reported one of the three required values.** It returned
`google_client` — the presence of `GOOGLE_CLIENT_ID` — and nothing about the
secret or the tokens. All three are required and any one missing produces the
identical symptom, so a health check confirming the part that is fine is worse
than none. It now returns:

```json
"google": { "client_id": true, "client_secret": true,
            "tokens": true, "logins": 2, "ready": true }
```

Counts only, never labels and obviously never tokens. Whether those tokens
carry the Tag Manager scope is deliberately **not** answered here — that means
calling Google, and healthz touching a dependency is what made it unanswerable
and got the instance pulled. The access preflight answers it per site instead.

**The OAuth success page said to paste the token on `vici-audit-worker`.**
Following that exactly leaves the preflight broken, because the API runs it in
its own container. It now says both services, and that the client pair has to
be on both too.

**A 403 from Tag Manager had three causes and one message.** `accessNotConfigured`
means the Tag Manager API is not enabled on the Cloud project the client ID
belongs to — one click in the console, not a re-consent. It was folded in with
the missing-scope case, so the advice was "re-authorize each login", which on a
disabled API is half an hour that changes nothing. Three causes, three messages
now: `scope` (re-consent), `api_disabled` (enable it), and a real permission gap
(the only one that is the client's).

---

## THE CONSENT SCANNER: FOUR FINDINGS THAT WERE WRONG

I went through the standalone scanner against what the audit actually surfaces.
The gap is bigger than "some detail is missing" — **four checkpoints were
reporting wrong answers**, and they are fixed here. Full parity is a plan, not
a single build; that's at the bottom.

### 1. A scan that never saw the page was reported as findings

`_apply_verdict()` marks a bot challenge, an HTTP 4xx, or a sub-2KB body as
`inconclusive` — and deliberately leaves `error = None` and `ok = True`,
because from the scanner's point of view the *run* succeeded. Our adapter
guarded only on `error`.

So a Cloudflare "Checking your browser" page produced:

> **CONS-02 · Fail · Critical** — A consent platform is installed but no banner appeared.
> **CONS-04 · Pass** — No advertising or analytics tags contacted their servers before consent.

about a page consisting of the words *"Checking your browser"*. The standalone
tool refuses this explicitly: *"Nothing here should be treated as a finding
about the site."* Now all nine rows come back unanswered, carrying the
diagnosis — HTTP status, body size, page title, whether a challenge was served
— and pointing at the extension, which is the thing that gets past it.

### 2. CONS-04 passed sites with no CMP and live ad pixels

`_dedupe_product_pixels()` strips every ungated pre-consent row whose URL
matches one of the client's product pixels, so the standalone UI can show it
once under **Product pixels** instead of twice. And `ungated` is the severity
the scanner assigns to *every* pre-consent tracker **when there is no CMP at
all**.

The standalone tool gets away with this because it renders the products
section right underneath. **We never read `products`.** So a site with no
consent platform running Meta and GA4 — about as bad as this gets — came back:

> **CONS-04 · Pass** — No advertising or analytics tags contacted their servers before consent.

Now the product pixels are folded back in. And the fix text is source-aware,
because `src` decides *who does the work*:

> In Tag Manager, set an additional consent check requiring `ad_storage` on
> GA4, then publish. **Meta Pixel is hardcoded in the page template**, so no
> container change will stop it — the tag has to come out of the theme and be
> reinstated behind the consent event.

Previously both got the same sentence, which sent someone hunting in GTM for a
tag that was never in the container.

### 3. "State privacy law requirements" was checking no state

The scanner takes `states=` and `industries=`. The worker passed them. **Nothing
ever set them** — no form field, no option, nowhere. Grepping the repo for
`consent_states` found the worker line and nothing else.

Consequences, both live until this build:

- `states` was always empty → the GPC pass never ran → **CONS-06 was permanently
  "Need Access"**, on all twelve states that require GPC to be honored.
- The only row that ever arrived was the universal privacy-policy-link check
  tagged `US`. So CONS-08, titled **"State privacy law requirements"**, reported
  *"All 1 checked requirements are met across US"* — a privacy-policy-link check
  wearing a state-law label, printed as a clean pass on twenty states nobody had
  looked at.

**20 states and 3 sensitive-industry rules were vendored, tested, and
unreachable for want of a form field.** The form now has both: a states box
prefilled `CA CO CT TX VA OR` (prefilled because blank is how this went unnoticed
— an empty list is not "check nothing", it is "silently answer nothing"), and an
industry field backed by the 346-entry vocabulary, which switches on the
Healthcare / Children-directed / Financial rules.

`US` is no longer counted as a state. With no states selected CONS-08 is
unanswered, never a pass.

### 4. A notice bar counted as a consent platform

`NOTICE_ONLY_CMP` is a banner with an OK button, no reject, no preferences — it
informs, collects nothing, and offers no opt-out. Our adapter counted any entry
in `cmps[]` as a **Pass**, so it read *"Notice-only banner is installed on this
site"* — green, on the finding most likely to matter legally. Now a Fail that
says what is missing.

---

## THE EVIDENCE LAYER, WHICH WAS BEING COLLECTED AND THROWN AWAY

Every finding carries a `value` dict. The collectors fill it, `db.py` stores it,
`/api/audits/{id}/findings` returns it — and **nothing rendered it.** Grepping
`report.py`, `pdf_report.py`, `ui.py` and `summarise.py` for `value` returned
nothing at all.

So the reader got one sentence — *"3 trackers fired before any consent
interaction: Meta, GA4, TikTok"* — while the eight request URLs proving it sat
in the database unread. That is the difference between a claim and evidence, and
it is the whole reason someone opens a detail row.

Findings now render their structured evidence: vendors, the actual request URLs,
Consent Mode defaults, container ids, what matched the CMP signature, and the
failing state requirements **with the scanner's own statute explanation** rather
than a bare `CA: GPC signal` label. Deliberately narrow — it renders the shapes
it recognizes and skips the rest, rather than dumping JSON at a client.

Also carried through now: `cmps[].notes` (the per-CMP operator warnings, e.g.
OneTrust firing its event on every page view including reject), `gtm.gtag_only`
(gtag.js with no container is a materially different remediation from no Google
tagging at all, and both read identically before).

---

## What full parity still needs — sequenced

Being straight with you: this build fixes what was **wrong**. It does not yet
replace the standalone tool. What's left, in the order I'd build it:

| # | Gap | Size |
|---|---|---|
| 1 | **`gtm_api.py`** — 551 lines, not vendored at all. Reads the *published* container over OAuth and returns per-tag `consent_status` (NEEDED vs NOT_SET). That is ground truth for "is this tag gated", independent of what fired on one page load. Also `find_by_domain()`, which reads the container for a site that blocked the browser. | large |
| 2 | **`products` / `post_consent` as checkpoints** — "is the client's bought pixel actually installed, firing, and correctly gated". 11 products, 10 fields per pixel, currently no checkpoint at all. | medium |
| 3 | **Remediation layer** — owner badges (VICI / CLIENT), dependency ordering, the 5-step GTM procedure, the Consent Mode verdict stamp. We emit one `recommendation` string per row. | medium |
| 4 | **Multi-page scanning** — conversion URLs alongside the homepage, with site-level checks running once. We scan one page. | medium |
| 5 | **Client share link** — unauthenticated per-run URL with DSP name masking and internal work suppressed. | medium |
| 6 | **Raw scan persistence + run history** | small |
| 7 | **Scheduled batch scanning, CSV export, the alerting rule** (`verdict bad` OR post-reject violation OR failing state check OR a bought product firing zero) | small |

One note on language, from the scanner's own README: *"No 'compliant',
'certified,' or 'passed' anywhere in product copy — 'no issues detected in
checked items' is the ceiling."* Our status vocabulary says **Pass**. Worth a
conversation before this goes in front of a client's counsel.

---

## A. Tag Manager on the access preflight

A third pill and a third picker beside Search Console and GA4, plus
`tagmanager.readonly` on the OAuth scope.

**It matches on the container the page actually loads, not on a name.** The
Tag Manager API says what we can *administer*; the site's HTML says what is
*installed*. One GET of the homepage pulls the `GTM-XXXXXXX` ids out, and the
answer is the overlap — "the site runs GTM-ABC1234 and yes, it sits in an
account we hold" — rather than a similarity guess between a container called
"Client - Main" and a domain called ootenlawfirm.com.

Four outcomes, because they belong to four different people:

| State | Pill | Whose move |
|---|---|---|
| The container on the page is in an account we hold | green | nobody — we can make the change ourselves |
| Our logins have not approved the scope yet | **amber** | ours, two minutes |
| The page runs a container nobody here can see | red | the client, and the ask names the container |
| No GTM on the page at all | amber | nobody — that is a finding, and ANA-01 already reports it |

> ### Every login must re-authorize before this can go green
>
> A refresh token carries the scopes granted at the moment somebody consented,
> frozen. Every login in `GOOGLE_TOKENS` consented before this scope existed,
> so **all of them will report "not approved yet" until they go back through
> `/oauth/google/start`.** Search Console and GA4 keep working throughout —
> nothing breaks, the new grant is simply absent. DEPLOY.md now says this where
> the tokens are minted.

That amber state is the whole reason `_scope_missing()` exists. Google returns
**403 for both** "your token lacks the scope" and "this login was never invited
to that GTM account", and they are opposite problems: the first is ours and
takes two minutes, the second is an email to the client. Printing the first as
the second is exactly the failure the access buckets were built to prevent.

The container list is capped at 40 accounts per login and **says so when it
caps** — a list that quietly stops at 40 looks identical to a complete one, and
the container you were hunting is the one that fell off the end.

Read-only throughout: the scope lists accounts, containers and published
versions. It cannot create a tag or publish anything.

---

## B. An optional phase nobody ticked is not a defect

Your panel showed **Ours to fix · 15**, and every one of those fifteen was a
run doing exactly what it was asked:

```
9 — the consent and privacy scan produced no result for this run
6 — the AI visibility panel produced no result for this run
```

Both phases are opt-in checkboxes. One drives a browser, the other pays several
platforms per question, so most runs leave them off deliberately. With the
boxes unticked, no findings are produced, the checkpoints fall through to the
vendor bucket, and the panel called them defects.

This is the analyst-list mistake wearing a different hat. A fix list that fills
with no-action items is a list people stop reading — and the one genuine
failure hiding among the fifteen goes with it.

The worker now records which optional phases were requested
(`extras.phases_run`), and the panel splits on it:

- **Ours to fix** — things that were asked for and did not work.
- **Not requested on this run** — muted, phrased as a choice, naming the
  checkbox that would have covered them. *"Not a fault, and not scored against
  the client — they are simply unmeasured."*

Three cases, verified:

| Run | Ours to fix | Not requested |
|---|---|---|
| both phases off | **1** (a real DataForSEO miss) | 17 |
| consent ON, returned nothing | **10** — the bug stays on the list | 8 |
| an older audit with no record | **18** — nothing is claimed without evidence | — |

That middle row is the one that must never regress: ticking the box and getting
nothing back **is** our bug, and it stays on the fix list.

---

## 0. Three lines of chrome off the top of the dashboard

Gone: the `Site Scanner` breadcrumb, the `Vici Media (internal) · mode internal`
line, and the build-notes sentence. The build chip stays.

The breadcrumb was a one-item trail reading "Site Scanner" directly under a
heading reading "Site Scanner" — the page name printed twice with a font
change, not navigation. The audit detail page keeps its trail, because there
the first item is a link back.

`BUILD_NOTES` still exists and still shows in `/healthz`; it just stopped being
the third thing above the first number anyone opens the page to read.

---

## 1. The analyst section is gone, and it is not coming back

You asked to be rid of it. It is not hidden — the thing that produced it no
longer classifies anything into it.

`engine/access.py` sorts every unanswered checkpoint into one of three buckets:
**client** (a grant only they can give), **vendor** (ours), **manual** (a person
does this by hand). `MANUAL_DESPITE_PREFIX` is now empty, and the two source
tags that used to land there — `gsc_no_api`, `ga4_no_api` — moved into
`OURS_DESPITE_PREFIX`.

Those three rows are Search Console's Links reports. Google publishes them and
exposes no API for them, so "an analyst opens Search Console and reads it off"
was once an honest label. It stopped being honest when the backlink index
started answering all three. An empty GSC-22 does not mean nobody has done the
reading; it means **our DataForSEO call missed**. Leaving the old mapping in
place put a work item on a person's list that no person could act on.

Verified across the whole catalog:

```
Counter({'vendor': 284, 'client': 38})     # manual: 0
```

The bucket itself stays declared. An unrecognized checkpoint id still falls to
`manual`, which is the conservative fallback that keeps our gaps off the
client's homework list, and the next genuinely-unautomatable checkpoint should
land there rather than on them.

---

## 2. "Ours to fix" — the real cause, and the six silent rows

### The cause: we were reading the wrong endpoint

The panel's own diagnostic finally printed the field names DataForSEO returned
for `/backlinks/domain_pages/live`:

```
content_encoding, domain, encoded_size, fetch_time, first_visited, ip,
location, main_domain
```

No page URL. No backlink count. **That endpoint returns host records, not
pages.** Three rounds of increasingly tolerant key-matching went into parsing a
shape that was never going to be there.

`_page_split()` now computes the split from the backlinks themselves —
`/backlinks/backlinks/live`, grouped by `url_to`, with referring sources
deduplicated so two links from one page count once. Verified against a fixture
of 40 raw links from 9 distinct sites:

- **OFF-19** — 9 referring links point at the homepage
- **OFF-20** — 13 point at interior pages (59.1%)
- **GSC-22** — top linked page identified, ranked by referring pages

### The six rows that just said "Not run."

A checkpoint with no finding has no evidence to quote, so the panel printed the
placeholder — six times, identically, for six different failures. True, and
completely unactionable.

`engine/access.py` gained `owner()`, which names the subsystem that owed each
row. The panel now says *"the backlink provider produced no result for this
run"* or *"the AI visibility panel produced no result for this run"* — three
different fixes that previously looked like one problem.

---

## 3. Gradients in the PDF

All within one hue, and for a specific reason. Section scores are a magnitude,
carried by a sequential single hue plus length. A gradient that crossed hues
would turn a ranked scale into a categorical palette and destroy the ordering
it exists to show. Every gradient here runs light-to-dark inside the same blue:
it reads as depth and finish, never as a second channel of meaning.

| Where | What |
|---|---|
| **Score gauge** | The arc sweeps in segments with an interpolated stroke, so the largest mark in the document carries the ramp |
| **Section bars** | Every bar on the same ramp, over a flat track |
| **Inline meters** | Same ramp, in the Score-by-Area table |
| **Cover** | A full-measure gradient rule under the title |
| **Hero panel** | A flush gradient cap along its top edge |
| **Nine headings** | A short tapered version of the same rule, so it reads as a recurring section mark |

### Three things that were wrong until I looked at the rendered pages

**The tapered rule printed as a dashed line.** Fading the tail with
`setFillAlpha` seemed obvious. Each band overlaps its neighbor by 0.4pt to stop
hairlines opening between them — and two translucent fills stacked in that
overlap are twice as opaque as either one, so the fade came out striped at
exactly the band pitch. The tail now lerps toward the page color at full
opacity.

**The bars had grown a second color channel.** The first cut gave the three
worst areas a full-depth gradient and everything else a pale one. On the page,
tone started reading as the data — dark bars looked like the bad ones — and it
contradicted the gauge on page one, where dark simply means "further along the
arc". Same ink, two opposite meanings, one document. All bars now share one
ramp; the worst three are emphasized by a bold label instead.

**The inline meters looked striped next to identical bars four times as wide.**
Band count was hard-coded, so the same 48 bands that vanish across four inches
were countable across one. `_grad_rect` now derives the count from the width,
one band per 1.5pt.

---

## 4. The chrome, matched to adtini by measurement

Every value below is the modal pixel of the region it names in your screenshot,
not a match by eye. Eyeballing had produced `#12356b` for the rail and
`#f0b429` for the gold — both close enough alone, both visibly wrong with the
two apps in adjacent tabs, which is the only way anyone ever sees them.

| Token | Was | Now |
|---|---|---|
| left menu | `#12356b` | **`#1c5ba6`** |
| dark navy (table heads) | `#12356b` | **`#0c284c`** |
| gold (active tile) | `#f0b429` | **`#e8ac3e`** |
| page background | `#f4f6f9` | **`#f1f2f4`** |

**The top bar is white again.** It was a navy gradient for one build — it did
look good on its own, and it also made this the one page in the suite whose
header did not match the others. The rail and the bar are the two things a
person recognizes before reading a word. The gradient moved rather than
disappeared: it is now a 2px seam under the bar and the rule under every
heading, where it reads as finish rather than as a different product.

### The font was the wrong font

Not a stack problem — the wrong face. Setting your heading beside candidates at
matched cap height settles it. Ink-box aspect ratio of the word "Workflow":

| | ratio |
|---|---|
| **adtini (measured from your screenshot)** | **6.11** |
| Arial / Helvetica | 6.09 |
| Roboto — what we were loading | **5.44** |

Roboto is visibly narrower, and we were pulling it from Google Fonts on every
page load to get it. The webfont link is gone and the CSS uses the system stack,
which resolves to the same face adtini gets on the same machine — a match by
construction rather than by my picking a lookalike.

> If adtini actually names a licensed face somewhere in its own CSS, say which
> and it is a one-line change. The measurement says Arial-metric; it cannot
> distinguish Arial from a metric-compatible clone.

The PDF still sets Roboto. That is a separate artifact with its own typography
and nobody has complained about it — say the word and it moves too.

### A Site Scanner icon

One object, because every icon in adtini's rail is one object — a house, a
person, a briefcase. The first attempt drew a browser window with a lens over
it: a better picture of what the tool does, and illegible at 21px, where three
concentric strokes inside a 40px gold tile came out as a smudged box. The rail
gets the lens alone.

### `Prepared by` → `Partner name`

In the form and on the audit detail page. The PDF cover still reads "Prepared
by", because that is the client reading it and the phrasing is right there.

---

## 5. The extension is now Site Scanner

Same name as the page it feeds, on purpose: it is not a companion tool, it is
the same tool with a different way in.

- **Name** — `Vici Audit Capture` → **`Site Scanner`**, version 1.2.0
- **Description** — now mentions the consent scan, which it has been able to
  run since ‑28: *"Runs the audit and consent scan from your own browser, so
  sites that block server-side crawlers still get measured."*
- **A logo**, at 16/32/48/128, declared for both the toolbar button and the
  extensions page. The popup leads with the mark instead of a bare string.
- Popup blues repointed at the sampled `#1c5ba6` / `#0c284c`.

`extension/icons/make_icons.py` draws them from the two sampled colors, so the
next palette change is an edit there rather than someone opening an image
editor and guessing. **The small sizes are a different drawing, not a scaled
one** — three concentric strokes cannot resolve inside sixteen pixels, and 16px
in the toolbar is where the icon actually lives all day, so 16 and 32 drop the
window and keep the lens.

---

## Tests

All 18 suites pass. Three needed changing, and all three were the test being
wrong rather than the code:

- **`test_charts`** counted filled rects to count bars. Bars are gradients now,
  so it reported 176 bars in a four-row chart. It was always measuring the
  implementation; it now measures how far each row's ink reaches past its
  track, plus two new assertions (every bar sits on a track; a higher score
  draws a longer bar).
- **`test_analytics_build`** faked `/backlinks/domain_pages/live` with the
  shape the name promises rather than the shape it returns. The fixture is now
  per-link records, and asserts that two links from one source to one page
  count as one referring page.
- **`test_analytics_build`** also asserted GSC-20/21 were `manual`. That was
  right while it was true. Leaving it would have pinned the old behavior in
  place; it now asserts `vendor`, plus a check that GSC-22 is never put on a
  person's list.

---

## Deploy

```
unzip -o vici-audit-2026.08.20-48.zip
git add -A && git commit -m "no analyst section; gradient PDF; adtini chrome matched" && git push
```

Both services redeploy. Confirm `build 2026.08.20-48` in the header before
trusting a run.

The extension is not deployed by Render — reload it in `chrome://extensions`
after the pull. You should see **Site Scanner 1.2.0** with the new icon.
