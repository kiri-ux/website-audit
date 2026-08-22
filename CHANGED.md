# Changed files — build 2026.08.20-33

Cumulative delta since **2026.08.18-16**. Unzip over the repo root, commit, push.

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
unzip -o vici-audit-2026.08.20-33.zip
git add -A && git commit -m "no analyst section; gradient PDF; adtini chrome matched" && git push
```

Both services redeploy. Confirm `build 2026.08.20-33` in the header before
trusting a run.

The extension is not deployed by Render — reload it in `chrome://extensions`
after the pull. You should see **Site Scanner 1.2.0** with the new icon.
