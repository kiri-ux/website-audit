# Changed files — build 2026.08.20-30

Cumulative delta since **2026.08.18-16**. Unzip over the repo root, commit, push.

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
unzip -o vici-audit-2026.08.20-30.zip
git add -A && git commit -m "no analyst section; gradient PDF; adtini chrome matched" && git push
```

Both services redeploy. Confirm `build 2026.08.20-30` in the header before
trusting a run.

The extension is not deployed by Render — reload it in `chrome://extensions`
after the pull. You should see **Site Scanner 1.2.0** with the new icon.
