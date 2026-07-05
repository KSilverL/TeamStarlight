# Trend Scout routine — the daily write side

Phase 2 of [docs/TREND_SCOUT_IMPLEMENTATION.md](../docs/TREND_SCOUT_IMPLEMENTATION.md): a
Foundry agent with **Grounding with Bing Search** + a **daily** scheduled run that upserts one
rolling `current` trends document into the `trends` table. The LLM service (read side, Phase 1)
only ever reads that table — **the contract is the table, nothing else**. This folder is a
standalone sibling runtime (like `dev_backend.py`): it is never imported by `LLM_service/` and
imports nothing from it, which is exactly what makes the
`agent_framework_azure_ai`/`agent-framework-core` version skew irrelevant.

```
run_scan.py        the routine body: agent scan → validate → stamp → upsert (non-empty only)
prompt.md          the agent's Instructions (Appendix A; {MARKET}/{LANGUAGE} filled from env)
sample_scan.json   a canned scan for offline dry-runs / seeding dev data
role.sql           least-privilege DB role (INSERT/UPDATE/SELECT on trends only)
.env.example       all env vars; real env > ./.env > ../LLM_service/.env (dev fallback)
requirements.txt   standalone deps (the conda env `TeamProject` already has them all)
```

## One-time provisioning

1. **Foundry project** — `FOUNDRY_PROJECT_ENDPOINT`
   (`https://<resource>.services.ai.azure.com/api/projects/<project>`).
2. **The agent (portal-defined)** — in the Foundry portal create an agent whose
   *Instructions* are the output of `run_scan.py --print-instructions` (prompt.md with
   MARKET/LANGUAGE filled), attach the **web grounding tool** (Grounding with Bing Search — a
   paid add-on billed per grounded query, ~30/month at daily cadence), and **publish a
   version**. Set `TREND_AGENT_NAME` (+ optional `TREND_AGENT_VERSION`); the script calls it
   through the project's OpenAI **responses API** with an `agent_reference` body
   (azure-ai-projects ≥ 2.1.0 — the current official calling convention).
3. **Table** — provision `trends` with
   [LLM_service/migrations/003_trends.sql](../LLM_service/migrations/003_trends.sql) (or let the
   LLM service auto-create it on its first production store connect, or one dev
   `run_scan.py --ensure-table`).
4. **DB role** — run [role.sql](role.sql) as admin; put the role's DSN in `TRENDS_DATABASE_URL`
   (in the scheduler's secret store, NOT in git). Cosmos DB for PostgreSQL requires TLS:
   `POSTGRES_SSLMODE=require`.
5. **Auth for the agent call** — `DefaultAzureCredential`: locally `az login`; in a scheduler a
   managed identity (or `AZURE_CLIENT_ID`/`AZURE_TENANT_ID`/`AZURE_CLIENT_SECRET`) with access
   to the Foundry project.

## Running

```bash
# print the resolved agent Instructions (to paste into the portal agent)
python3 trend_scout_routine/run_scan.py --print-instructions

# offline: parse+stamp a canned scan, print the doc, write nothing
python3 trend_scout_routine/run_scan.py --from-file trend_scout_routine/sample_scan.json --dry-run

# seed dev data through the same pipe (creates the table if missing — dev only)
python3 trend_scout_routine/run_scan.py --from-file trend_scout_routine/sample_scan.json --ensure-table

# the real daily scan: Bing-grounded agent → validate → stamp → upsert
python3 trend_scout_routine/run_scan.py

# read the stored `current` doc back (date, count, category spread, lines)
python3 trend_scout_routine/run_scan.py --verify
```

A scan that yields **no usable trends exits 1 without touching the table** (decision #1: a
failed/empty run never clobbers the last good snapshot); the read side's TTL then degrades the
seat gracefully after `TREND_SCOUT_TTL_DAYS`.

## Scheduling (daily, off-peak)

Any scheduler that can run a Python one-liner works; the routine is stateless, and a missed
day is harmless (TTL 3 days + the non-empty guard). Dev interim: cron on a box that has the
env + `az login`/identity:

```cron
# 05:30 UTC daily — off-peak for a global/English market
30 5 * * * cd /path/to/TeamStarlight && /opt/anaconda3/envs/TeamProject/bin/python3 trend_scout_routine/run_scan.py >> /var/log/trend_scout.log 2>&1
```

### Azure-hosted: Container Apps Job (cron trigger) — the recommended production shape

A **scheduled Job** is managed cron: at the cron time it starts one replica of the
[Dockerfile](Dockerfile) image, `run_scan.py` runs once and exits, the replica is torn down.
No always-on server; billed per execution second. One-time setup (set the vars, then
copy-paste; requires `az extension add -n containerapp`):

```bash
RG=TeamStartlight LOC=eastus ACR=trendscout ENV=starlight-env JOB=trend-scout-daily
AGENTS_RESOURCE_ID=$(az cognitiveservices account show -n starlight-agents-resource \
    -g <agents-resource-rg> --query id -o tsv)

# 1) Build & push the image (no local docker needed — ACR builds it).
az acr create -n $ACR -g $RG --sku Basic
az acr build -r $ACR -t trendscout:v1 trend_scout_routine/

# 2) Environment (reuse an existing one if the team already has one).
az containerapp env create -n $ENV -g $RG -l $LOC

# 3) The scheduled job. Cron is UTC: "30 5 * * *" = 05:30 UTC = 13:30 北京时间.
az containerapp job create -n $JOB -g $RG --environment $ENV \
  --trigger-type Schedule --cron-expression "30 5 * * *" \
  --parallelism 1 --replica-completion-count 1 --replica-retry-limit 1 --replica-timeout 900 \
  --image $ACR.azurecr.io/trendscout:v1 \
  --registry-server $ACR.azurecr.io --registry-identity system \
  --mi-system-assigned \
  --secrets "trends-db-url=postgresql://citus:twinkletwinklelittlestar1234!@c-starlight.x2pbktk6pzh5or.postgres.cosmos.azure.com:5432/starlight" \
  --env-vars "TRENDS_DATABASE_URL=secretref:trends-db-url" "POSTGRES_SSLMODE=require" \
    "FOUNDRY_PROJECT_ENDPOINT=https://starlight-agents-resource.services.ai.azure.com/api/projects/starlight-agents" \
    "TREND_AGENT_NAME=test-eastUS-01" "TREND_AGENT_VERSION=8"

# 4) Let the job's managed identity call the Foundry agent (DefaultAzureCredential picks
#    the system-assigned identity up automatically inside the container).
PRINCIPAL_ID=$(az containerapp job show -n $JOB -g $RG --query identity.principalId -o tsv)
az role assignment create --assignee $PRINCIPAL_ID --role "Azure AI User" \
  --scope $AGENTS_RESOURCE_ID

# 5) Cosmos firewall: on the cluster's Networking blade tick "Allow Azure services and
#    resources to access this cluster" (a Consumption environment has no static egress IP).
#    Locked-down alternative: a workload-profiles environment + NAT gateway → one static IP
#    to allowlist.

# 6) Fire it once manually, then check the run + the data.
az containerapp job start -n $JOB -g $RG
az containerapp job execution list -n $JOB -g $RG -o table
python3 trend_scout_routine/run_scan.py --verify   # from your machine
```

Updating later: `az acr build -r $ACR -t trend-scout:v2 trend_scout_routine/` then
`az containerapp job update -n $JOB -g $RG --image $ACR.azurecr.io/trend-scout:v2`.

## Verify (Phase 2 definition of done)

1. Run the scan once manually → `upserted `current` trends doc: N trends for YYYY-MM-DD`.
2. `--verify` shows the doc with a category spread (≥3 categories) and fresh timestamps.
3. Run it again → same row updated (`updated_at` advances), never a second row.
4. Read side end-to-end: `TREND_SCOUT_ENABLED=true USE_MOCK_STORE=false` and the roundtable's
   `trend_scout` seat opens with today's lines (that flip is Phase 3).
