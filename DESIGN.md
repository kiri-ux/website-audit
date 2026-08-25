# Vici SEO/GEO Audit Engine — Design Document

**Status:** working POC, verified end to end
**Audience:** dev team
**Deployment:** internal first, partner-facing later (designed for both from day one)

---

## 1. What this is

An automated implementation of the 313-checkpoint white-label SEO/GEO audit that
is currently produced by hand and sold at $2,950 per report.

The insight the whole design rests on: **the audit template is not a document,
it is a 313-row database with a Word front-end.** Every finding has the identical
shape — `ID | Checkpoint | Tool | Priority | Status/Evidence` — and everything
else in the deliverable (executive summary, area snapshot, scoring, roadmap) is
a projection of those rows.

So the product is the **findings store**. The Word document, the HTML report and
the partner API are all just renderers over it. Build the store first; never let
a renderer become the source of truth.

**Current coverage: 159 of 313 checkpoints (50%) from the crawl alone, plus 8
AI-visibility rows from the monitor — 167 of 313 (53%), no paid SEO APIs.**

---

## 2. How it actually works

### Request lifecycle

```
 1  POST /api/audits            client submits target URL
 2  ├─ auth        →  tenancy.resolve()  →  Principal(partner_id)
 3  ├─ persist     →  audits row, status=queued
 4  ├─ enqueue     →  jobs table (or Redis list)
 5  └─ 202 Accepted { audit_id }          ◀── returns in ~5ms. NO crawl yet.

 6  worker leases the job
 7  ├─ crawl       →  status=crawling   one pass, builds the artifact
 8  ├─ checks      →  status=checking   159 checkers query the artifact
 9  ├─ score       →  status=scoring    severity → section → overall
10  ├─ persist     →  findings + section_scores rows
11  ├─ artifact    →  object storage (crawl_artifact.json)
12  └─ status=ready

13  GET /audits/{id}            renders the report from the DB
```

**Step 5 is the load-bearing design decision.** A 150-page crawl takes 2–5
minutes; a large site takes far longer. No HTTP request can be held open for
that, on Render or anywhere else. The API enqueues and returns; the worker owns
all long-running work. Everything else in the architecture follows from this.

### Component map

| Module | Responsibility | Notes |
|---|---|---|
| `app/api.py` | HTTP surface | Thin. Never crawls. Every handler returns in ms |
| `app/worker.py` | Job consumer | Where crawls actually run. Separate process |
| `app/queue.py` | Queue abstraction | `DbQueue` (no deps) / `RedisQueue` (production) |
| `app/db.py` | Storage | Raw SQL, no ORM. SQLite + Postgres |
| `app/tenancy.py` | The internal→partner seam | See §5 |
| `app/artifacts.py` | Blob storage | `local://` or `s3://` |
| `app/config.py` | Env-driven config | Every backend has a local and a production impl |
| `app/ui.py` | Operator dashboard | Server-rendered, no build step |
| `engine/crawler.py` | The keystone collector | Runs once, serves ~190 checkpoints |
| `engine/checks/` | 159 checkpoint implementations | Pure functions over the artifact |
| `engine/scoring.py` | Severity → score → rating | Implements the template's own rubric |
| `engine/report.py` | HTML report renderer | One renderer among several |

### The crawl artifact is the keystone

One crawl produces one artifact. Every check is then a **query against stored
data**, never a new fetch. This is why an audit takes minutes instead of hours
and why we don't get rate-limited by our own clients.

`crawl_pages` captures everything any checkpoint might need, on the first pass:
full HTML, response headers, redirect chain, title/meta/canonical/viewport/lang,
heading tree, word count, images (src/alt/loading/srcset), internal and external
links with anchors and rel, **script sources and inline JS** (this alone powers
all 12 analytics checkpoints), JSON-LD schema, and inbound internal link counts.

Adding a checkpoint that needs a field the artifact doesn't capture means
extending the crawler — do that rather than adding a second fetch.

### Adding a checkpoint

```python
@check("ONP-99")
def my_check(art, ctx):
    bad = [p.url for p in art.pages.values() if problem(p)]
    return finding("Fail" if bad else "Pass",
                   {"count": len(bad)},                    # structured, never prose
                   f"{len(bad)} pages have the problem.",  # goes into the report
                   bad, "Medium", "How to fix it.")
```

Registry is import-time; no wiring. **No I/O in a check.** That rule is what
keeps checks unit-testable and the crawl count at one.

---

## 3. Data model

Five tables carry the system. Full DDL in `app/db.py`.

```
partners ──< audits ──< findings
                    └─< section_scores
checkpoints (static catalog, 313 rows, seeded from seed/checkpoints.csv)
jobs (queue, used when Redis is absent)
```

Two columns deserve explanation:

**`findings.value` is structured JSON, not prose.** `{"count": 579}`, not
`"579 images missing alt text"`. The sentence is a rendering of the number.
Keeping the number structured is what makes severity escalation, trend tracking
over time, and client dashboards possible later. Bake it into a string now and
you lose all three.

**`findings.source` + `confidence` are not optional.** At $2,950 a report,
partners will dispute findings. You need to show which collector produced a row
and when. It is also what lets you re-run one failed collector without redoing
the audit.

### Status enum

`Pass | Fail | Warning | Not Implemented | Need Access | N/A`

`Need Access` is **not** an error state — it is the normal resting state for the
38 Search Console and GA4 rows until a client grants OAuth. The reference audit
we worked from has all 22 GSC rows sitting at Need Access. The report must
render that gracefully.

---

## 4. Scoring

Implements the template's own rubric — severity penalties, capped per section,
banded into ratings (Excellent / Strong / Needs Improvement / Weak / Critical).

Two guardrails matter more than the formula, and both are load-bearing:

**Never score a section 0 because data was missing.** `Need Access` and `N/A`
are excluded from the denominator. A section with nothing assessable renders
"Not Assessed". Conflating *we couldn't check* with *it's broken* is the fastest
way to lose a partner's trust. The same rule applies inside checkers — `URL-01`
returns `Need Access` when neither host variant resolves rather than inventing a
defect from a failed probe. (This was a real bug caught in testing.)

**Cascade dependent failures.** An HTTP-only origin produces one finding
(`SEC-01`), not six "could not retrieve certificate" failures. Root causes
appear once. See `_cascade()` in `engine/checks/security.py`.

**Vertical weighting** changes severity weights by business model — Product and
Review schema weigh heavily for e-commerce; author credentials weigh heavily for
YMYL finance. This is cheap to build and is the main driver of "this audit
understands my business", which is what justifies the price against a $99 scan.
Visible in the demo: the same site scores 62 / 63 / 61 under ecommerce /
local_service / finance_ymyl.

---

## 5. Internal → partner-facing

`app/tenancy.py` is the **entire** difference between the two modes. Every
request resolves to a `Principal`; every query is scoped by `partner_id`.

- `APP_MODE=internal` — one implicit tenant, no auth, operator sees everything
- `APP_MODE=partner` — API-key auth, every read scoped, partners isolated

**`partner_id` is written in both modes.** Internal audits are owned by
`vici-internal`. That is the whole migration:

1. `APP_MODE=partner`
2. Insert partner rows with real API keys
3. There is no step 3.

The usual failure here is shipping the internal tool with no tenant concept,
then discovering that "add multi-tenancy" means touching every query, every
route and every template. Carrying the column from day one costs nothing now and
removes that rewrite entirely.

Still to build for partner mode (none of it structural): key issuance/rotation,
per-partner branding in the renderer (`partners.branding` already exists),
usage metering, and a partner-visible status page.

---

## 6. Running it

**Fastest look — no Docker, no Postgres, no Redis:**

```bash
pip install -r requirements.txt
python3 -m app.dev          # API + worker in one process
open http://localhost:8000
```

**Production topology locally:**

```bash
docker compose up --build   # separate API + worker, Postgres, Redis
```

**Verify:**

```bash
python3 tests/test_e2e.py   # boots everything, asserts the full pipeline
python3 verify.py           # 37 ground-truth assertions against the fixture
```

`python3 -m app.dev` runs the worker in a thread purely for convenience.
**Production always runs them as separate processes** — see `render.yaml`.

---

## 7. Deployment (Render)

`render.yaml` is a working blueprint. Topology:

| Service | Plan | Why |
|---|---|---|
| `vici-audit-api` (web) | starter | Thin; does no real work |
| `vici-audit-worker` (worker) | standard | Chromium needs ~1GB per concurrent browser |
| `vici-audit-queue` (keyvalue) | starter | Redis-compatible job queue |
| `vici-audit-db` (Postgres) | basic-256mb | Findings store |
| S3 / Cloudflare R2 | — | Artifacts. **Not** a Render disk — disks pin a service to one instance and block zero-downtime deploys |

Scale by raising worker `numInstances`. The Redis queue makes workers
independent and job handling is idempotent, so this is safe.

### The operational risk nobody budgets for

**You are crawling client sites from a datacenter IP.** Cloudflare and Akamai
will challenge or block you, and it will look like the tool is broken when it is
actually being denied. Mitigations, in order of effectiveness:

1. Static outbound IP + ask partners to allowlist it during onboarding
2. Honest user-agent with a contact URL (already the default)
3. Conservative per-host rate limiting (already implemented: `CRAWL_DELAY`)
4. Surface "blocked by WAF" as a distinct, visible audit failure rather than a
   silent 403 — so operators diagnose it in seconds

Plan for this before the first partner demo, not during it.

---

## 8. What's built vs. what's next

**Built and verified (159 checkpoints):** the full pipeline above, plus Analytics
(12/12), Structured Data (10/10), URL (17/18), Technical (26/38), On-Page
(34/50), Performance (16/19), Security (11/15), E-E-A-T page-existence (9/24),
GEO deterministic subset (8/30).

**Phase 2 — deterministic gap (+74 rows → 233).** Semrush adapter, Search
Console and GA4 (needs client OAuth — the fiddliest part, and it gates two whole
sections). Note the spike result below before sizing the Semrush work.

**Phase 3 — judgment layer (+37 rows → 270).** One narrow LLM call per
checkpoint, each fed a targeted slice of the crawl artifact and returning a
strict structured object. **Do not write one broad "assess E-E-A-T" prompt** —
it produces confident mush that a competent SEO spots instantly and it discredits
the other 276 rows. 37 narrow calls beat 5 broad ones on accuracy, cost and
debuggability. Budget ~$2–4 per audit; don't optimize it, optimize accuracy.

**Phase 4 — AI visibility monitor (+8 rows → 278). ✅ BUILT.** See §11.

**Remaining 35:** 29 backlink rows (one adapter once you pick Ahrefs or Semrush)
and 6 blocked on a client-supplied keyword map.

### The Semrush finding

The template assigns 94 rows to Semrush. **Our own crawler already answers 70 of
them (74%).** Of the 24 remaining, exactly one — `ONP-13 Pages require content
optimization` — is genuinely locked behind Semrush's proprietary index. The rest
is unbuilt engineering: asset-level checks, subdomain enumeration, hreflang edge
cases, AMP.

Semrush's irreplaceable value here is the **keyword rankings table and backlink
data**, not the 94 site-audit rows. Since the top-tier plan plus metered units is
likely the single largest fixed cost, this materially changes the build-vs-buy
call. The collector interface is designed so re-pointing a row from `semrush` to
`crawler` is a config change, not a refactor.

---

## 11. AI Visibility Monitor (Phase 4 — built)

Fills GEO-23 … GEO-30, which the template marks "Manual Review" — meaning
someone currently types prompts into chat windows and screenshots the answers.

### The measurement

Four numbers, in increasing order of commercial value:

| Metric | What it means |
|---|---|
| **mention rate** | the brand name appears in the answer |
| **citation rate** | the client's DOMAIN appears in the answer's sources — **the real metric** |
| **unprompted citation rate** | cited on queries that never named the brand — *earned* visibility |
| **share of voice** | which domains got cited instead |

"Mentioned" is the vanity metric. A model can name a brand from training data
while citing five competitors as its sources. The citation is what drives
referral traffic and what a content/PR retainer can actually move. The dashboard
leads with citation rate and states the distinction explicitly, because clients
will otherwise anchor on the bigger, softer number.

### Three design decisions that matter

**1. Repeats, not single shots.** These platforms are non-deterministic — the
same question can be cited once in three asks. Every query runs `repeats` times
and every number is a RATE over attempts. A single-shot boolean would swing 30
points between runs for no real-world reason, and a client watching that would
rightly stop believing it. Three is the floor; five is better.

**2. The panel is frozen at profile creation.** The product is a time series, so
the questions must be stable. Regenerating them between runs would make
consecutive points incomparable while still looking like a trend. Changing the
panel creates a new `panel_version` rather than mutating the old one.

**3. Unmeasured ≠ zero.** A platform with no API key is reported as `Need
Access` with `confidence: 0.0`, never as 0% visibility. Copilot has no public
consumer API and is left explicitly unavailable rather than faked. GEO-24/25
(Featured Snippets, Passage Ranking) are Google SERP features, not chatbots —
they cap at `Warning` with a stated proxy, and **a proxy can never return
`Pass`**. (That last rule was added after testing caught the code doing exactly
that: certifying a row it had never measured.)

### Panel construction

~40 queries across five intents, weighted toward the ones where the brand is
NOT named in the prompt:

```
brand       "Is <brand> reputable?"                  prompted   — proves little
category    "Best <category> in <location>?"         unprompted — the real test
product     "Where can I buy <product> near me?"     unprompted
comparison  "<brand> vs <competitor>"                prompted
question    "How long does <category> delivery take?" unprompted
```

Default mix: 25 unprompted / 14 prompted.

### Platforms

| Adapter | Grounded | Notes |
|---|---|---|
| `perplexity` | yes | Sonar returns sources natively |
| `claude` | yes | server-side `web_search` tool |
| `chatgpt` | yes | Responses API + hosted `web_search` |
| `gemini` | yes | Google Search grounding |
| `ai_overview` | yes | **no official API** — via a SERP provider; least stable adapter |
| `copilot` | — | no public consumer API; Azure OpenAI + Bing grounding, or leave off |

Citation extraction is deliberately defensive — each adapter tries several known
response shapes and falls back to scraping URLs from the answer text. Every
result records `citation_shape` (where the URLs were actually found), because a
renamed API field would otherwise silently zero the headline metric.

### Accuracy

The analyser is validated against a recorded corpus with planted traps —
false positives matter more than misses here, since over-reporting tells a client
they're visible when they aren't:

```
"a grand total of"        must NOT match "Grand Home Furnishings"
"Grand Rapids, Michigan"  place name sharing the first token
"Grandiose Furniture"     prefix collision, different brand
notgrandhf.com            domain ENDING with the client domain
grandhf.com.evil.example  client domain as a subdomain of another host
blog.grandhf.com          real subdomain — MUST count
www.grandhf.com           www normalisation
```

`python3 verify_ai.py` → **100% precision and recall on both mention and
citation across 195 answers; all six traps rejected.**

### Running it

```bash
# deterministic, no API keys, no spend — demos and CI
AI_REPLAY_CORPUS=fixture/ai_corpus.json python3 -m app.dev
python3 make_ai_fixture.py     # rebuild the corpus
python3 verify_ai.py           # accuracy vs ground truth
python3 tests/test_aivis_e2e.py

# live: set any of OPENAI_API_KEY / ANTHROPIC_API_KEY / PERPLEXITY_API_KEY /
# GEMINI_API_KEY / SERP_API_KEY. Unset platforms are skipped, not zeroed.
```

Record a real corpus once with `aivis.record_corpus()`, commit it, and CI gets a
realistic regression suite that costs nothing and never flakes.

### Scheduling — why this justifies hosting

`app/schedule.py` enqueues runs for every profile past `MONITOR_INTERVAL_DAYS`.
It **only enqueues** — the worker executes. That split is deliberate: Render
hard-stops a cron at 12 hours, and a fleet of monitor runs across many clients
would blow past it. The cron finishes in seconds. It also skips profiles with a
run already in flight, so a double-fired cron cannot double-bill your API spend.

`render.yaml` includes a `vici-monitor-scheduler` cron running monthly.

**This is the piece that makes hosting necessary.** A one-shot audit runs fine
from a CLI. Scheduled recurring measurement across a client book does not.

---

## 9. Known issues

- **`MOB-03..07` reference a retired tool.** Google shut down the Mobile-Friendly
  Test and its API and points users to Lighthouse. The Word template needs
  updating regardless of automation.
- **PSI needs outbound access to `googleapis.com`**; `SKIP_PSI=true` degrades
  those rows to `Need Access` rather than failing the audit.
- **External link checking is sampled** (60 URLs) to bound crawl time. Raise it
  when off-page work lands.
- **`DbQueue` is single-worker.** Correct for internal use; set `REDIS_URL`
  before scaling out.
- **No auth in internal mode by design.** Put it behind your VPN or add a
  reverse-proxy auth layer before exposing it.
- **`ai_overview` has no official API** and depends on a SERP provider. Expect
  it to need more maintenance than the other adapters; it is also the one
  clients ask about most.
- **Copilot is not measurable** without Azure OpenAI + Bing grounding. It
  reports `Need Access` rather than a fake zero.
- **AI platform responses vary by region and personalisation.** Fix what you can
  (region, no history) and report rates across repeats, never single answers.

---

## 10. Suggested first tasks for the dev team

1. Run `python3 -m app.dev`, submit an audit against a real client site, read
   the report. Form your own view on output quality before building anything.
2. Run it against 10–20 real sites and triage the findings. Which rows produce
   garbage? That list is the real backlog, and it is worth more than any
   roadmap written in advance.
3. Do the Semrush spike properly: pick 20 Semrush-assigned rows, diff our
   crawler's output against Semrush on the same site. The result decides your
   cost structure.
4. Wire the Search Console OAuth flow — it unblocks 38 rows and it is the
   longest-lead item because it needs client action.
5. Only then decide on hosting. Nothing above requires a deployed app.
