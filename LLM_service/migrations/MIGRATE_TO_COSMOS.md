# Migrating the store: Supabase Postgres ➜ Azure Cosmos DB for PostgreSQL

Azure Cosmos DB for PostgreSQL is a **Citus-based, wire-compatible Postgres**. The
LLM service's store layer (`core/services/postgres.py` — `PostgresStore` +
`PostgresCheckpointStorage`) runs against it **unchanged**; only the connection
string and SSL differ. There is no NoSQL/Cosmos-SQL involved.

## What changes

| Concern | Supabase | Cosmos DB for PostgreSQL |
|---|---|---|
| Driver | `asyncpg` | `asyncpg` (same) |
| Schema | 3 JSONB doc tables, auto-created | identical, auto-created on first connect |
| SSL | optional | **mandatory** → `POSTGRES_SSLMODE=require` |
| Distribution | n/a | tables stay **coordinator-local** (not `create_distributed_table`d) |

The three tables (`brand_profiles`, `user_skills`, `workflow_checkpoints`) are small
JSONB KV/metadata tables. They are deliberately left as local coordinator tables:
distributing them would force `id` to be the Citus distribution column for the
`ON CONFLICT (id)` upserts. Local tables are correct and need no extra DDL.

## Steps

1. **Provision** an Azure Cosmos DB for PostgreSQL cluster. Note the coordinator host
   `c-<cluster>.<id>.postgres.cosmos.azure.com`, default db/user `citus`, and password.

2. **Copy the data** (schema is ensured automatically by the script):

   ```bash
   # dry-run first — reads source, writes nothing, reports row counts
   /opt/anaconda3/envs/TeamProject/bin/python3 LLM_service/migrations/migrate_to_cosmos.py \
     --source "postgresql://postgres.<ref>:<pw>@aws-0-eu-west-1.pooler.supabase.com:5432/postgres" \
     --target "postgresql://citus:<pw>@c-<cluster>.<id>.postgres.cosmos.azure.com:5432/citus" \
     --dry-run

   # then the real copy (idempotent — upserts on id, safe to re-run)
   /opt/anaconda3/envs/TeamProject/bin/python3 LLM_service/migrations/migrate_to_cosmos.py \
     --source "<supabase-dsn>" --target "<cosmos-dsn>"
   ```

   DSNs may instead come from `SOURCE_DATABASE_URL` / `TARGET_DATABASE_URL`. `--source`
   falls back to `DATABASE_URL`. The target defaults to `sslmode=require`; override
   with `--target-sslmode`. Other flags: `--truncate`, `--tables profiles,user_skills`.

3. **Repoint the service** — in `LLM_service/.env`:

   ```dotenv
   DATABASE_URL=postgresql://citus:<pw>@c-<cluster>.<id>.postgres.cosmos.azure.com:5432/citus
   POSTGRES_SSLMODE=require
   USE_MOCK_STORE=false
   ```

4. **Verify**: start the API (`python -m LLM_service.api`) and run a workflow that
   reads/writes a brand profile, or `python LLM_service/db_test.py` if present.
