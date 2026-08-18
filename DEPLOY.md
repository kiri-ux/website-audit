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
