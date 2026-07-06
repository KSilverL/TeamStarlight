-- Least-privilege DB role for the Trend Scout routine (decision #5, run as admin once).
--
-- The routine only ever upserts the single rolling `current` row in the trends table,
-- so its role gets INSERT/UPDATE/SELECT on that one table and nothing else (SELECT is
-- required by INSERT ... ON CONFLICT and by --verify). It cannot create tables —
-- provision the table itself with LLM_service/migrations/003_trends.sql (or let the
-- LLM service auto-create it on first production connect).
--
-- Replace the password, then put the resulting DSN into the routine's secret store as
-- TRENDS_DATABASE_URL, e.g.
--   postgresql://trend_scout_writer:<PASSWORD>@<host>:5432/<db>
-- (Azure Cosmos DB for PostgreSQL requires TLS: keep POSTGRES_SSLMODE=require.)

CREATE ROLE trend_scout_writer LOGIN PASSWORD '<CHANGE-ME>';

GRANT SELECT, INSERT, UPDATE ON TABLE trends TO trend_scout_writer;
