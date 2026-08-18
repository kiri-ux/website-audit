# Voice

Every word the report puts in front of a client is written to this. It is
derived from Kiri's Confluence pages (AdLib Setup Guide, Campaign Reviews,
Campaign Check Process) — not invented, and not a generic "professional tone"
guide. Where a rule below has a source, the source is a real line from those
pages.

The tests in `tests/test_voice.py` enforce the parts of this that can be
checked mechanically. The rest is on whoever edits the strings.

---

## 1. Talk to the reader, not about them

Second person, present tense, active. Her docs almost never use a passive
construction or an abstract subject.

> "Make sure your pixels are installed within the client's container tag"
> "Check your overall product pacing"
> "Feel free to tweak the impression numbers"

**Do:** "Your homepage doesn't redirect to HTTPS. Add a sitewide 301."
**Don't:** "It is recommended that a sitewide redirect be implemented."

## 2. Short lines. Fragments are fine.

Her bullets run four to fifteen words. Long explanations get broken into a
parent line plus an indented consequence, not a subordinate clause.

**Do:** "8 pages are served over plain HTTP. Browsers flag those pages."
**Don't:** "Analysis identified 8 pages which are being served over plain HTTP,
which may result in browsers displaying security warnings to end users."

## 3. American spelling

Vici is a US agency with US clients. `optimization`, `canonicalization`,
`behavior`, `organization`, `analyze`, `prioritize`. Never the British forms.
This is enforced by a test — a single "optimisation" fails the suite.

## 4. Say the consequence, then the fix

Her pattern throughout: what to do → what happens if you don't.

> "Remove daily budget to avoid limitations on serving ads."
> "Even extra spaces will prevent your lines/creatives from merging in reporting."

The report's **What we found → Why it matters → What to do** structure is this
pattern, spelled out.

## 5. Callouts carry the important bits

She leans on Confluence panels constantly: ℹ️ for context, ⚠️ for a trap, ✅
for a rule of thumb. They are visually distinct, short, and they interrupt.
Our definition bubbles and warning banners are the same idea, and they are the
reason a definition sits NEXT TO the finding that used the word rather than in
a glossary at the back.

## 6. Bold the thing the reader is looking for

She bolds UI elements and the operative word: **Save**, **POOL** level,
**CURRENT** line item ID. In the report, bold the label of a finding and the
number that matters. Do not bold whole sentences.

## 7. Warmth is allowed. Hype is not.

> "you'll end up with some extra impressions which is okay!"
> "When searching for your categories check here first!"
> "keep an eye out!"

One exclamation mark where something is genuinely good news or a genuine
gotcha. Zero marketing verbs. The banned list lives in `tests/test_voice.py`:
leverage, unlock, delve, seamless, harness, elevate, robust solution, and the
rest of that family.

Her emphasis style is ALL CAPS for a single word ("EXACTLYYYY", "ONE
Advertiser"). That works internally between colleagues; in a client
deliverable it reads as shouting, so we use bold instead. This is the one
place we deliberately soften her register.

## 8. "We" is Vici. "You" is the client.

> "we are putting in the maximum budget", "our naming conventions"

Never "the auditor" or "this report". The report has people behind it and says
so.

## 9. Name the limit out loud

She flags what is broken, pending, or uncertain rather than glossing it:

> "AdLib is currently working on these updates for us"
> "this is currently being worked on as an enhancement"

This is the same instinct behind **Need Access** and the honesty rules in the
scoring engine. When we could not measure something, we say so plainly and
say what would unblock it.

## 10. Explain the jargon at the point of use

Her guides define a term the first time it appears — "On AdLib, **audiences**
are created first and then added to a campaign" — rather than assuming or
deferring to a glossary. Same rule here: the definition bubble goes beside the
finding.

---

## Words we don't use

| Instead of | Write |
|---|---|
| utilize, leverage | use |
| in order to | to |
| it is recommended that | you should / add / fix |
| significant improvement opportunity | this is worth fixing |
| comprehensive analysis | we checked |
| best practices dictate | we'd do it this way because |
| ensure | make sure |
| additionally, furthermore, moreover | (start a new sentence) |
| In plain English | (nothing — just define the word where it appears) |
