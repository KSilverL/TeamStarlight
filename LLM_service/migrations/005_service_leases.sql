-- 005 — service_leases: expiring cross-replica locks.
--
-- Auto-created by PostgresStore._pool() on first connect (see _leases_ddl); this file is
-- the human-readable copy, matching 001–004.
--
-- What it is for: with more than one API replica, a run paused at the human gate can be
-- resumed by whichever replica the /review call happens to land on (it rebuilds the
-- workflow from the MAF checkpoint). This table is what stops TWO of them doing that at
-- once for the same run, which would drive one workflow from two processes.
--
-- Why a table and not pg_try_advisory_lock: an advisory lock is scoped to the SESSION, and
-- asyncpg hands out a different pooled connection per call — the lock would be released
-- the moment the connection went back to the pool, long before the work finished.
--
-- Why expiring: the holder is a process that can be killed mid-run (a rolling deploy, an
-- OOM). A lock held open forever would strand that task permanently, which is a worse
-- failure than the one it prevents. `expires_at` bounds the damage to the TTL — the lease
-- is acquired for slightly longer than a resume segment is expected to take, and released
-- explicitly on the happy path.
--
-- The acquire is a single INSERT … ON CONFLICT DO UPDATE … WHERE (expired OR same owner)
-- … RETURNING owner, so the database picks the winner. Two replicas racing both get a row
-- back; only one of them sees its own id in it.

CREATE TABLE IF NOT EXISTS service_leases (
    name       TEXT PRIMARY KEY,   -- e.g. "task-resume:<task_id>"
    owner      TEXT NOT NULL,      -- the holding replica's node id (per-process uuid)
    expires_at TIMESTAMPTZ NOT NULL
);

-- Optional housekeeping: expired rows are harmless (the acquire overwrites them in place),
-- but a periodic sweep keeps the table from accumulating one row per task forever.
--   DELETE FROM service_leases WHERE expires_at < now() - interval '1 day';
