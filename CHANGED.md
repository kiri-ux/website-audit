# Changed files — build 2026.08.19-14

**Cumulative since 2026.08.18-16.** Apply and you are current whatever you last
uploaded.

## Search Console + GA4: what was already there, and what wasn't

Both collectors were fully built — 38 checkpoints, real API calls, a multi-login
token index, and GA4 property discovery that matches on the data stream's URI
rather than trusting a property's display name. What was missing was the one
step that turns a Google login into the token they spend: `consent_url()` and
`exchange_code()` existed in `engine/collectors/analytics.py` and **nothing
called them**. No route, no way to mint a token without leaving the app.

Added, gated behind `OAUTH_SETUP_TOKEN`:

```
GET /oauth/google/start?t=<token>&label=seo-main   → Google consent
GET /oauth/google/callback                          → prints the merged GOOGLE_TOKENS
```

With `OAUTH_SETUP_TOKEN` unset both routes return **404** — not 401, not a login
page. The surface does not exist. A token minted there inherits every client
property that login can see across Search Console and Analytics, which makes it
the most valuable credential this service touches, so the resting state is
"absent" rather than "present and checking".

Full walkthrough in **DEPLOY.md → "Minting a `GOOGLE_TOKENS` entry"**.

## The thing to know before you ask a client for access

Access alone will **not** make these sections score:

| Section | Filled by the API today | Gate | Result |
|---|---|---|---|
| Search Console | 5/22 (23%) | 50% | still Not Assessed |
| Google Analytics 4 | 6/16 (38%) | 50% | still Not Assessed |

Same shape as the E-E-A-T problem: the rows come back, the section stays
suppressed. The remainder is reachable and just unwritten — GSC's
`searchAppearance` dimension covers GSC-14..18, its links endpoint covers
GSC-19..21, and the GA4 Admin API covers GA4-03/04/06/07/08. That is +8 for GSC
(→59%) and +5 for GA4 (→69%), clearing both.

I would rather write those **after** your first successful grant than before,
so the response shapes get checked against a real payload instead of guessed
at. Guessing at a vendor's JSON shape is what the DataForSEO rankings table is
still waiting on.

## Files

| File | Why |
|---|---|
| `app/api.py` | The two OAuth routes, the setup-token gate, and https-forcing on the redirect URI — Render terminates TLS in front of us, so the app sees `http://` and Google rejects a mismatched URI |
| `render.yaml` | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `OAUTH_SETUP_TOKEN` on the **API** service. `GOOGLE_TOKENS` stays on the worker |
| `DEPLOY.md` | Step-by-step, including the Internal-vs-External consent screen trap: External expires refresh tokens after 7 days until the app is verified, which breaks collection a week later with no error |
| `tests/test_routes.py` | The routes must not exist without the variable, must 404 (not 401) on a wrong token, and must force https |

## Carried from earlier in this batch

- **Need Access split three ways** (`engine/access.py`): the client's ask drops
  from 161 to 38. The other ~123 were our unset vendor keys and 58 checkpoints
  with no automation, all printed as the client's homework.
- **58 unautomated checkpoints** now named with a **Manual** pill instead of
  being counted in the coverage chart and omitted from "the full record".
- **Worker says what ran** — judgment layer and DataForSEO both log success or
  the reason for silence.
- **Favicon** — the SVG was invalid XML (`aria-label="… SEO & AI Search …"`),
  so all three delivery routes served a file no browser would parse.
- **Gauge rating** fitted to the arc's opening; "Needs Improvement" was drawn
  struck through.

## Verified before sending

- Routes exercised over HTTP in all four states: variable unset, wrong token,
  missing label, no client ID. 404 / 404 / 400 / 400.
- `render.yaml` parses; 13 env vars on the API, 26 on the worker.
- 14 suites green; `import app.api, app.worker` on a clean merged tree.

## What to check on this build

- Header chip reads **2026.08.19-14**.
- `/oauth/google/start` returns 404 before you set `OAUTH_SETUP_TOKEN`.
- Worker still needs `ANTHROPIC_API_KEY`, `DFS_LOGIN`, `DFS_PASSWORD` — the
  E-E-A-T, AI Search and Off-Page sections are still empty without them.
