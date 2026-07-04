-- TeamStarlight LLM service — daily current-trends snapshot (docs/TREND_SCOUT_IMPLEMENTATION.md).
--
-- The app also auto-creates this on first connection (PostgresStore._pool uses
-- CREATE TABLE IF NOT EXISTS), so this file is for provisioning up front or reviewing
-- the shape. Same whole-document-in-JSONB pattern as brand_profiles / user_skills.
--
-- One rolling row keyed 'current' holds {"date": ..., "trends": [{text, category, source,
-- captured_at, expires_at}, ...]}. The WRITE side is an external Foundry agent + daily
-- routine (Grounding with Bing Search) that upserts the row — only on a non-empty result,
-- so a failed/empty scan never clobbers the last good snapshot. The READ side is
-- StoreService.get_trends (TTL-dropped, category-diverse pick), feeding the roundtable's
-- trend_scout persona. The Foundry routine should connect with its own least-privilege
-- role (INSERT/UPDATE on this table only) and, on Azure Cosmos DB for PostgreSQL,
-- sslmode=require.

CREATE TABLE IF NOT EXISTS trends (
    id         TEXT PRIMARY KEY,
    doc        JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
