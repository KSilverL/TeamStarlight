-- TeamStarlight LLM service — video_jobs table (run by hand in the Supabase SQL editor).
--
-- The app also auto-creates this on first connection (PostgresStore._pool uses
-- CREATE TABLE IF NOT EXISTS), so this file is for provisioning the database up front
-- or reviewing the shape. See migrations/001_user_skills.sql for the other three tables.
--
-- Tracks one Remotion render job per (task_id, platform) trigger. `task_id`/`platform`/
-- `status` are pulled out as plain columns (not just inside `doc`) so a future "list
-- jobs for a task" query doesn't need a JSONB index — not used by Phase 1, but free to
-- have. `doc` holds the whole job document: {id, task_id, platform, status, storyboard,
-- output_path, error, created_at, updated_at}.
CREATE TABLE IF NOT EXISTS video_jobs (
    id         TEXT PRIMARY KEY,
    task_id    TEXT,
    platform   TEXT,
    status     TEXT,
    doc        JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
