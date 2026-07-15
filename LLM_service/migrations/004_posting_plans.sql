-- TeamStarlight LLM service — posting plans (multi-date campaign schedules).
--
-- The app also auto-creates this on first connection (PostgresStore._pool uses
-- CREATE TABLE IF NOT EXISTS), so this file is for provisioning up front or reviewing
-- the shape.
--
-- One row per plan; the whole core.plan_schema.PostingPlan document lives in `doc`
-- ({plan_id, business_id, user_id, goal, target_platforms, start_date, end_date,
-- status, strategy_summary, items: [{item_id, planned_date, time_of_day, platforms,
-- topic, angle, rationale, status, content_types, task_id}], created_at, updated_at}).
-- business_id / user_id / status are promoted to plain columns (kept in sync on every
-- upsert) so the backend's daily "list active plans for this brand" query filters
-- without a JSONB index — same rationale as video_jobs' promoted columns. Due-ness is
-- computed by the CALLER (core.plan_schema.select_due_items, date supplied by the
-- backend's clock) — never in SQL, so the service stays timezone-agnostic.

CREATE TABLE IF NOT EXISTS posting_plans (
    id          TEXT PRIMARY KEY,
    business_id TEXT,
    user_id     TEXT,
    status      TEXT,
    doc         JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
