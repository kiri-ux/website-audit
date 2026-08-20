# Render Deployment — Confirmed Steps

Exact sequence to get this running on Render, internal-only.

Your existing `website-audit` web service was created by hand and is **not
sufficient on its own** — an API with no worker will accept audits and never run
them. Jobs sit at `queued` forever and it looks like the app is broken. Use the
blueprint instead; it wires all five services together.

---

## Step 0 — Push the fixed code

Two fixes went in after your first failed deploy. Make sure they're in the repo
you deploy from (`kiri-ux/website-audit`):

- `Dockerfile` — adds `PIP_RETRIES=10` / `PIP_TIMEOUT=60`. Your build died on a
  transient PyPI 502; without retries a single CDN blip kills the whole build.
- `requirements.txt` — **removed `playwright`**. The base image already ships it
  pinned to the Chromium build baked into that image. Reinstalling it can
  upgrade the Python package past the bundled browser and break JS rendering
  later with a confusing "executable doesn't exist" error.

```bash
git add -A && git commit -m "Fix Docker build: pip retries, drop duplicate playwright" && git push
```

---

## Step 1 — Remove the hand-made service

The blueprint creates its own services (`vici-audit-api`, `vici-audit-worker`,
…). Your existing `website-audit` would just sit there costing money.

Render dashboard → `website-audit` → **Settings** → scroll to bottom → **Delete
Service**.

*(If you'd rather keep the URL, skip this and see "Manual path" at the bottom —
but the blueprint is far less error-prone.)*

---

## Step 2 — Deploy the blueprint

1. Render dashboard → **New +** → **Blueprint**
2. Connect the `kiri-ux/website-audit` repo
3. Render reads `render.yaml` and shows five resources:

| Resource | Type | Plan | Purpose |
|---|---|---|---|
| `vici-audit-api` | Web | Starter | HTTP API + dashboard. Never crawls |
| `vici-audit-worker` | Worker | Standard | Runs crawls and monitor jobs |
| `vici-monitor-scheduler` | Cron | Starter | Monthly — enqueues due monitor runs |
| `vici-audit-queue` | Key Value | Starter | Job queue |
| `vici-audit-db` | Postgres | Basic 256MB | Findings store |

4. Click **Apply**

The worker is deliberately on Standard: Chromium needs roughly 1GB per
concurrent browser. Do not drop it to Starter if you plan to enable
`CRAWL_RENDER_JS`.

---

## Step 3 — Set the secrets

Everything marked `sync: false` in `render.yaml` must be set by hand. Render will
prompt during Apply, or set them later per service.

**Set on BOTH `vici-audit-api` and `vici-audit-worker`:**

| Key | Value | Required? |
|---|---|---|
| `ARTIFACT_STORE` | `s3://your-bucket` | See the warning below |
| `PSI_API_KEY` | Google PageSpeed Insights API key | Optional — free tier works without one, just rate-limited |
| `ANALYST_NAME` | e.g. `Kiri Sanders` | Optional, but set it — see below |
| `ANALYST_TITLE` | e.g. `SEO & GEO Analyst` | Optional |
| `ANALYST_EMAIL` | e.g. `kiri@vicimediainc.com` | Optional |
| `FIRM_NAME` | e.g. `Vici Media` | Optional |

**Set authorship on the API too, not just the worker.** The PDF is rendered by
the API service, so setting `ANALYST_NAME` only on the worker produces an
unsigned report with no error explaining why. Left blank, the "Prepared by" row
and the sign-off block are omitted entirely rather than printed as a
placeholder — an empty name field is worse than no name field.

**Set on `vici-audit-worker` only** (nothing else calls these):

| Key | Purpose |
|---|---|
| `OPENAI_API_KEY` | ChatGPT visibility (GEO-27) |
| `ANTHROPIC_API_KEY` | Claude visibility (GEO-30) |
| `PERPLEXITY_API_KEY` | Perplexity visibility (GEO-28) |
| `GEMINI_API_KEY` | Gemini visibility (GEO-29) |
| `SERP_API_KEY` + `SERP_ENDPOINT` | Google AI Overviews (GEO-23) |

Any platform you leave unset is reported as **"not measured"** rather than
counted as zero visibility. You can add them one at a time.

**Also worker-only — the credentials you already pay for:**

| Key | Purpose |
|---|---|
| `SKIP_SCREENSHOTS` | Set `true` to skip evidence screenshots (adds ~30s per audit) |
| `DFS_LOGIN` + `DFS_PASSWORD` | DataForSEO. Fills the 29 Off-Page rows, the keyword rankings table, Lighthouse (PERF-10..14, PERF-19, MOB-03..06) and report screenshots. Same credentials as the SEO quote tool. |
| `AHREFS_API_KEY` *or* `SEMRUSH_API_KEY` | Fallback for backlinks only, used when `DFS_LOGIN` is unset |
| `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` | OAuth app for Search Console and GA4 |
| `GOOGLE_TOKENS` | JSON `{"label": "refresh_token"}` of Vici logins, or a path to that file |

Two notes on these.

**Route Lighthouse through DataForSEO if PageSpeed Insights is returning 429.**
Unauthenticated PSI calls share a per-IP quota with every other anonymous caller
on Render's egress, so the limit is not really yours. DataForSEO fetches the
site itself. The worker still prefers PSI where it succeeds, because PSI carries
CrUX *field* data and DataForSEO's is a lab run — the DataForSEO rows only fill
what PSI could not answer.

**`GOOGLE_TOKENS` removes the per-client OAuth dance, not the access grant.** A
token inherits exactly what its login can already see, including properties
added tomorrow. If nobody has added a Vici login to the client's Search Console
property, no token helps — and the report says so, naming how many logins were
tried, instead of reporting the site as failing.

### Minting a `GOOGLE_TOKENS` entry

You are authorising a **Vici** login once, not a client. Do this per Vici login
that holds client properties; Google caps how many a single login can hold,
which is why the variable is a JSON object rather than one token.

**1. Create the OAuth client** — Google Cloud console, any project.

- Enable three APIs: *Google Search Console API*, *Google Analytics Data API*,
  *Google Analytics Admin API*.
- Audience: **Google Auth Platform → Audience**
  (`console.cloud.google.com/auth/audience`). This is the page that used to be
  called "OAuth consent screen" and moved out from under APIs & Services, so
  older write-ups send you somewhere that no longer exists.

  Pick **Internal**. It only appears if the project sits inside a Google Cloud
  **Organization**. If it is greyed out that is what it is telling you, and the
  fix is to create the project under the org (or have an admin move it) rather
  than to settle for External.

  **Internal restricts who can CONSENT, not who can be audited.** Only accounts
  belonging to the project's organization can complete the flow. The Vici login
  that holds the client's Search Console and Analytics properties has to be in
  that org — if it is a `@gmail.com` account or sits on an unrelated domain,
  Google refuses at the approval screen with:

  > Error 403: org_internal — This client is restricted to users within its
  > organization.

  That failure is loud and immediate, before any token is issued, so trying it
  costs nothing: set the variables, hit `/oauth/google/start` signed in as the
  login you actually want, and you will know in ten seconds. Do that before
  reasoning about which domain owns what.

  **Our case.** The Cloud org is `vicimediainc.com`; clients grant access to the
  white-label address `digital@reporting.zone`. First attempt was refused:

  > Access blocked: Site Scan can only be used within its organization.
  > Error 403: org_internal

  The cause: the *domain* `reporting.zone` is in our Workspace, but
  `digital@reporting.zone` is an **unmanaged consumer Google account** that
  merely uses that address. It is not a directory user, so it is not in the
  org, so Internal rejects it.

  **Fix it at the account, not at the consent screen.** Bring that account into
  the directory with the **transfer tool for unmanaged users** and Internal
  starts working with no other changes.

  ⚠️ **Transfer it — do NOT create a new user with the same address.** Creating
  one produces a conflicting account: Google makes the existing consumer
  account rename itself, and every client's Search Console and Analytics grant
  points at *that* account. You would keep the address and lose all the access
  attached to it, then have to re-request from every client. A transfer keeps
  the same address and the same account, so the grants come with it.

  Admin console → **Directory → Users → More options → Transfer tool for
  unmanaged users**. Searching "transfer tool" and clicking *Open Transfer
  Tool* only gets you as far as the Users page — the tool itself is behind the
  **More options** menu above the user list, which is easy to miss.

  It lists unmanaged accounts on your **verified** domains. If
  `digital@reporting.zone` is not there, the account is not the problem — it
  demonstrably exists, since it got as far as an `org_internal` refusal. Check
  **Account → Domains → Manage domains** and confirm `reporting.zone` is listed
  *and verified*. A domain you own and route mail for is not necessarily
  verified in Workspace. If you verified it recently, Google says the list can
  take up to 24 hours to catch up.

  Send the transfer request; whoever reads that mailbox accepts it; the account
  becomes a managed user on a Workspace seat.

  Two cautions. Google warns that a transferred personal account "may lose data
  and content for some Google services" — have the mailbox owner run a Takeout
  export first. And before trusting it, sign in as that account afterwards and
  confirm Search Console still lists the client properties. Third-party grants
  follow the account rather than the address, so they should survive, but this
  is cheap to verify and expensive to assume.

  Worth doing regardless of OAuth: today a consumer Gmail account outside admin
  control holds read access to every client's analytics. No enforced 2FA, no
  password reset, no offboarding. That is the actual finding here.

  **If the transfer is not on:** External, in a NEW project. Do not flip
  `site-scan-consent` to External — that consent screen is Site Scan's, in
  production, and changing its audience changes Site Scan's posture too. Two
  OAuth clients in one project is fine; two apps sharing one audience setting
  is not.

  **External, in a new project.** New project (`vici-audit-oauth`), enable the
  three APIs there, then Google Auth Platform → Get started → app name and
  support email → Audience **External** → contact email → Create.

  Then, on the Audience page, **Publish app** and confirm. The status must read
  **In production**, not Testing. This is the single step that matters most: an
  external app left in Testing expires refresh tokens after **7 days**, so
  collection works, then silently stops a week later with every Search Console
  and GA4 row back at Need Access and nothing in the logs to explain it.
  Published apps keep their tokens indefinitely.

  Unverified is fine here. Google requires verification only above 100 users;
  below that you get an interstitial reading "Google hasn't verified this app",
  cleared once per login via **Advanced → Go to … (unsafe)**. Both scopes are
  classed sensitive, which is what triggers that screen. No client ever sees
  it — the only people who touch this flow are us, once per login — so it costs
  nothing in white-label terms. It is not a foundation for a client-facing
  consent flow later, but that was never the plan.
- Credentials → Create → **OAuth client ID** → *Web application*.
- Authorised redirect URI, exactly:
  `https://vici-audit-api.onrender.com/oauth/google/callback`
- Scopes are requested by the app: `webmasters.readonly`,
  `analytics.readonly`. Read-only throughout — nothing here can change a
  client's property.

**2. Set three variables on `vici-audit-api`** (the API, not the worker — this
is the only thing the API side needs): `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, and `OAUTH_SETUP_TOKEN` set to any random string.

With `OAUTH_SETUP_TOKEN` unset, `/oauth/google/start` and
`/oauth/google/callback` return 404 — the surface does not exist. That is the
normal resting state.

**3. Visit, signed in as the Vici login you are authorising:**

```
https://vici-audit-api.onrender.com/oauth/google/start?t=<OAUTH_SETUP_TOKEN>&label=seo-main
```

`label` is your name for that login and becomes the key in `GOOGLE_TOKENS`. It
is also what the report quotes when it says which login read the data, so use
something you will recognise a year from now.

**4. Approve.** The callback prints the complete `GOOGLE_TOKENS` value with the
new login merged in. Paste it onto **`vici-audit-worker`** — the collectors run
there.

**5. Put `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_TOKENS` on the
WORKER.** All three. A refresh token is exchanged *against the client that
issued it*, so the worker cannot turn one into an access token without the id
and secret. Setting them only on the API — the natural instinct, since that is
where you mint the token — leaves every Search Console and GA4 row at Need
Access.

**5b. Put `GOOGLE_TOKENS` on the API as well** if you want the *Check GA4 /
Search Console access* button on the homepage to work. That check answers
synchronously while someone is filling in the form, so it runs on the API. With
the variable only on the worker the button reports "not set on this service",
which is true of the API and says nothing about what the audit will find. The
credentials are read-only and both services are already trusted, so this is a
convenience rather than a widening worth agonising over.

**6. Unset `OAUTH_SETUP_TOKEN`** on the API. Both routes vanish. Repeat from
step 3 for each additional login.

### Telling the three empty states apart

Watch the worker log. Only the third is the client's to fix:

```
Search Console EMPTY — Search Console access not configured.
    → GOOGLE_TOKENS is not set on the worker.

Search Console EMPTY — GOOGLE_TOKENS is set but GOOGLE_CLIENT_ID / ...
    → the step-5 mistake. Ours.

Search Console EMPTY — No Vici login has access to this Search Console
property (tried 1 login(s): reporting-zone). Ask the client to add a Vici
login as a user on the property...
    → credentials are fine; that login is not on the property. Theirs.

Search Console answered 5/22 rows
    → working.
```

The middle one used to render as the third, which would have had us asking a
client to re-grant access they had already given.

Google only issues a refresh token on the first consent for a login. The app
sends `prompt=consent` to force one on repeat runs; if it still comes back
without one, remove the app at `myaccount.google.com/permissions` for that
login and retry.

### What access actually unlocks today

Granting access does **not** by itself make these two sections score. The API
answers 5 of the 22 Search Console rows and 6 of the 16 GA4 rows, and a section
needs 50% coverage before a score is published:

| Section | Filled by the API today | Gate | Result |
|---|---|---|---|
| Search Console | GSC-01..04, GSC-22 — 5/22 (23%) | 50% | still Not Assessed |
| Google Analytics 4 | GA4-01, 02, 05, 09, 10, 11 — 6/16 (38%) | 50% | still Not Assessed |

The rest are reachable, just not written yet: the GSC `searchAppearance`
dimension covers GSC-14..18, the links endpoint covers GSC-19..21, and the GA4
Admin API covers GA4-03/04/06/07/08. That is 8 more rows for GSC (→ 59%) and 5
for GA4 (→ 69%), which clears both. Worth doing **after** the first successful
grant, so the response shapes can be checked against a real payload rather than
guessed at.

### ⚠️ The artifact-store gotcha

`ARTIFACT_STORE` defaults to a local path. That works locally, where the API and
worker are the same process. **In production they are separate containers with
separate filesystems**, so a local path means the worker writes crawl artifacts
the API can never read — `GET /api/audits/{id}/artifact` will 404.

Reports still work (they render from Postgres). Only raw artifact download
breaks. Two options:

- **Recommended:** create a Cloudflare R2 or AWS S3 bucket and set
  `ARTIFACT_STORE=s3://your-bucket` plus `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`, and `AWS_ENDPOINT_URL_S3` (R2 only) on both services.
- **Accept it for now:** leave it local, and know that artifact download 404s.
  Nothing else is affected.

---

## Step 4 — Verify it actually works

Health check:

```bash
curl https://<your-api>.onrender.com/healthz
# {"ok":true,"mode":"internal","queue_depth":0}
```

**The real test — confirm the worker is consuming the queue.** This is the thing
that silently doesn't work if the worker failed to deploy:

```bash
curl -X POST https://<your-api>.onrender.com/api/audits \
  -H 'Content-Type: application/json' \
  -d '{"target_url":"https://www.grandhf.com/","client_name":"Grand Furniture","vertical":"ecommerce","max_pages":50}'
# {"audit_id":"abc123...","status":"queued",...}

curl https://<your-api>.onrender.com/api/audits/abc123...
```

Status should move `queued → crawling → checking → scoring → ready` within a few
minutes. **If it sits at `queued`, the worker isn't running** — check the
`vici-audit-worker` logs. That's the single most likely failure mode.

Then open `https://<your-api>.onrender.com/` for the dashboard and
`/visibility` for the AI monitor.

---

## Step 5 — Static outbound IP (before any partner demo)

You'll be crawling client sites from a datacenter IP. Cloudflare and Akamai will
challenge or block you, and it will look like your tool is broken when it's
actually being denied.

Render dashboard → service → **Connect** → **Outbound** → copy the IPs. Give
them to partners to allowlist during onboarding.

Do this before the first demo, not during it.

---

## Step 6 — Lock it down

Internal mode has **no authentication by design** — anyone with the URL sees
every audit. Before putting real client data in:

- Put it behind Cloudflare Access, a VPN, or basic auth at a proxy, **or**
- Set `APP_MODE=partner` on both services and issue API keys (see DESIGN.md §5)

---

## Cost

| Service | Plan | Approx/mo |
|---|---|---|
| API | Starter | ~$7 |
| Worker | Standard | ~$25 |
| Cron | Starter | ~$1 |
| Key Value | Starter | ~$10 |
| Postgres | Basic 256MB | ~$6 |
| **Total** | | **~$50–60** before API costs |

Confirm against current Render pricing — these move. AI platform API calls are
separate: budget roughly $2–8 per monitor run depending on panel size and repeats.

---

## Manual path (if you keep the existing service)

Only if you'd rather not use the blueprint. You must create, at minimum:

1. Keep `website-audit` as the web service, command
   `uvicorn app.api:app --host 0.0.0.0 --port $PORT`
2. **New → Background Worker**, same repo and Dockerfile, command
   `python3 -m app.worker`, plan Standard
3. **New → Key Value** (Redis), Starter
4. **New → Postgres**, Basic 256MB
5. Set `DATABASE_URL` and `REDIS_URL` on **both** the web service and the worker,
   pointing at the two resources above
6. **New → Cron Job**, same image, command `python3 -m app.schedule --due-only`,
   schedule `0 6 1 * *`

Step 5 is the one people miss. If the API and worker point at different
databases, the API will accept audits the worker never sees.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Build fails on `pip install`, 502 from files.pythonhosted.org | Transient PyPI outage. Manual Deploy → retry. The `PIP_RETRIES` fix reduces this |
| Audits stuck at `queued` | Worker not running, or pointing at a different `DATABASE_URL`/`REDIS_URL` |
| `playwright: executable doesn't exist` | `playwright` got re-added to requirements.txt. Remove it — the base image provides it |
| Artifact download 404s | `ARTIFACT_STORE` is a local path; API and worker have separate filesystems. See Step 3 |
| Crawls return mostly 403s | WAF blocking your datacenter IP. See Step 5 |
| All GEO-23..30 say "Need Access" | No AI platform API keys set on the worker. Expected until Step 3 |
