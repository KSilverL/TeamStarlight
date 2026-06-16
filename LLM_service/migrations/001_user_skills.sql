-- TeamStarlight LLM service — PostgreSQL schema (run by hand in the Supabase SQL editor).
--
-- The app also auto-creates these on first connection (PostgresStore._pool /
-- PostgresCheckpointStorage._pool use CREATE TABLE IF NOT EXISTS), so this file is for
-- provisioning the database up front or reviewing the shape. Each table stores a whole
-- document in a JSONB `doc` column (the document's own `id` is the row key).
--
-- Connecting to Supabase: the direct host (db.<ref>.supabase.co:5432) may resolve to
-- IPv6 only; if you can't connect, use the connection pooler instead, e.g.
--   postgresql://postgres.<project-ref>:[YOUR-PASSWORD]@aws-<region>.pooler.supabase.com:6543/postgres
-- Put the real password ONLY in your local .env (gitignored) — never commit it.

-- Brand_Voice_Profile, keyed by business_id (the brand-voice learning channel).
CREATE TABLE IF NOT EXISTS brand_profiles (
    id         TEXT PRIMARY KEY,
    doc        JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-user learned skills, keyed by user_id (the per-user learning channel). `doc` holds
-- a UserSkillDoc: {user_id, rules:[{text, platform, kind}], version, updated_at}.
CREATE TABLE IF NOT EXISTS user_skills (
    id         TEXT PRIMARY KEY,
    doc        JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- MAF workflow checkpoints (so a RequestPort human-gate pause survives a restart).
CREATE TABLE IF NOT EXISTS workflow_checkpoints (
    seq           BIGSERIAL,
    id            TEXT PRIMARY KEY,
    workflow_name TEXT,
    doc           JSONB NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
