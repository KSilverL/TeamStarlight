"""
PostgreSQL-backed persistence.

`PostgresStore` is the StoreService — brand profiles (`brand_profiles`) plus the
StoreService checkpoint KV. `PostgresCheckpointStorage` is the MAF CheckpointStorage
that persists every workflow superstep to `workflow_checkpoints`, so a RequestPort
pause survives a process restart. Both store whole documents in a JSONB `doc` column.

`asyncpg` is **lazy-imported inside `_pool()`** so this module imports cleanly in
mock mode / tests where the driver (and a database) are absent. The `_read` / `_write`
seams on `PostgresStore` are overridable, so contract-parity tests exercise the
shaping logic without a database.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import ssl as _ssl
from datetime import datetime, timezone
from typing import AsyncIterator, List, Optional

from agent_framework import CheckpointStorage, WorkflowCheckpoint

from ..config import Settings
from ..skill_schema import SkillRule, UserSkillDoc
from ..trend_schema import TRENDS_DOC_KEY, Trend, select_current_trends
from .base import StoreService, empty_profile


def _connect_kwargs(settings: Settings) -> dict:
    """Extra `asyncpg.create_pool` kwargs derived from `settings.postgres_sslmode`.

    Translates a libpq-style sslmode into asyncpg's `ssl` argument so the same DSN
    works against Supabase (SSL optional) and Azure Cosmos DB for PostgreSQL (SSL
    mandatory). Unset → `{}` (the DSN's own `?sslmode=` governs, if any)."""
    mode = (settings.postgres_sslmode or "").strip().lower()
    if not mode or mode in ("allow", "prefer"):
        return {}  # let the driver / DSN negotiate
    if mode == "disable":
        return {"ssl": False}
    ctx = _ssl.create_default_context()
    if mode == "require":
        # Encrypt without validating the cert chain (matches libpq sslmode=require).
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
    elif mode == "verify-ca":
        ctx.check_hostname = False
    # verify-full → keep the default (hostname + chain verification).
    return {"ssl": ctx}


def _profiles_ddl(table: str) -> str:
    return (
        f"CREATE TABLE IF NOT EXISTS {table} ("
        f"id TEXT PRIMARY KEY, doc JSONB NOT NULL, "
        f"updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )


def _user_skills_ddl(table: str) -> str:
    # Same whole-document-in-JSONB shape as brand_profiles; the user_id is the primary key.
    return (
        f"CREATE TABLE IF NOT EXISTS {table} ("
        f"id TEXT PRIMARY KEY, doc JSONB NOT NULL, "
        f"updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )


def _checkpoints_ddl(table: str) -> str:
    return (
        f"CREATE TABLE IF NOT EXISTS {table} ("
        f"seq BIGSERIAL, id TEXT PRIMARY KEY, workflow_name TEXT, doc JSONB NOT NULL, "
        f"updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )


def _video_jobs_ddl(table: str) -> str:
    # Same whole-document-in-JSONB shape as brand_profiles/user_skills; the job_id
    # is the primary key. task_id/platform/status are pulled out as plain columns
    # too (not just inside `doc`) so a future "list jobs for a task" query doesn't
    # need a JSONB index — nothing runs that query yet, but the columns are free.
    return (
        f"CREATE TABLE IF NOT EXISTS {table} ("
        f"id TEXT PRIMARY KEY, task_id TEXT, platform TEXT, status TEXT, "
        f"doc JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )


def _trends_ddl(table: str) -> str:
    # The daily trends snapshot: one rolling row keyed `current`, whole doc in JSONB —
    # written daily by the external Foundry routine, read by StoreService.get_trends.
    return (
        f"CREATE TABLE IF NOT EXISTS {table} ("
        f"id TEXT PRIMARY KEY, doc JSONB NOT NULL, "
        f"updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )


def _channel(task_id: str) -> str:
    """The LISTEN/NOTIFY channel for one task.

    Hashed rather than interpolated: a channel name is a PostgreSQL identifier, capped at
    63 bytes and case-folded unless quoted, while a task_id is a caller-supplied string
    (the backend's session id) with none of those guarantees. A hash makes the mapping
    total and injection-proof.
    """
    return "llm_task_" + hashlib.sha1(task_id.encode("utf-8")).hexdigest()[:24]


def _leases_ddl(table: str) -> str:
    # Expiring cross-replica locks. `expires_at` rather than a held-open lock because the
    # holder is a process that can be killed mid-run: a session-scoped
    # pg_try_advisory_lock would also be wrong here, since asyncpg hands out a DIFFERENT
    # pooled connection per call, so the lock would not survive to the release.
    return (
        f"CREATE TABLE IF NOT EXISTS {table} ("
        f"name TEXT PRIMARY KEY, owner TEXT NOT NULL, "
        f"expires_at TIMESTAMPTZ NOT NULL)"
    )


def _posting_plans_ddl(table: str) -> str:
    # One row per posting plan (core.plan_schema.PostingPlan), whole doc in JSONB.
    # business_id/user_id/status are pulled out as plain columns (kept in sync on
    # every upsert) so the daily "list active plans for this brand" query filters
    # without a JSONB index — same rationale as video_jobs' promoted columns.
    return (
        f"CREATE TABLE IF NOT EXISTS {table} ("
        f"id TEXT PRIMARY KEY, business_id TEXT, user_id TEXT, status TEXT, "
        f"doc JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )


class PostgresStore(StoreService):
    """brand_profiles + the StoreService checkpoint KV, on PostgreSQL."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool_obj = None

    async def _pool(self):
        """Lazily build the connection pool + ensure the two tables exist."""
        if self._pool_obj is None:
            import asyncpg  # lazy import

            s = self._settings
            self._pool_obj = await asyncpg.create_pool(dsn=s.postgres_dsn, **_connect_kwargs(s))
            async with self._pool_obj.acquire() as conn:
                await conn.execute(_profiles_ddl(s.postgres_profiles_table))
                await conn.execute(_user_skills_ddl(s.postgres_user_skills_table))
                await conn.execute(_checkpoints_ddl(s.postgres_checkpoints_table))
                await conn.execute(_video_jobs_ddl(s.postgres_video_jobs_table))
                await conn.execute(_trends_ddl(s.postgres_trends_table))
                await conn.execute(_posting_plans_ddl(s.postgres_posting_plans_table))
                await conn.execute(_leases_ddl(s.postgres_leases_table))
        return self._pool_obj

    async def _read(self, table: str, key: str) -> Optional[dict]:
        """Return the stored doc for `key` in `table`, or None. Overridable seam."""
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT doc FROM {table} WHERE id = $1", key)
        return json.loads(row["doc"]) if row else None

    async def _write(self, table: str, key: str, doc: dict) -> None:
        """Upsert `doc` under `key` in `table`. Overridable seam."""
        pool = await self._pool()
        payload = json.dumps(doc)
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {table} (id, doc) VALUES ($1, $2::jsonb) "
                f"ON CONFLICT (id) DO UPDATE SET doc = EXCLUDED.doc, updated_at = now()",
                key,
                payload,
            )

    async def get_profile(self, *, business_id: Optional[str]) -> dict:
        if not business_id:
            return empty_profile(business_id)
        doc = await self._read(self._settings.postgres_profiles_table, business_id)
        if doc is None:
            return empty_profile(business_id)
        return {**empty_profile(business_id), **doc}

    async def upsert_profile(self, *, business_id: str, profile: dict) -> None:
        doc = {**empty_profile(business_id), **profile, "id": business_id}
        await self._write(self._settings.postgres_profiles_table, business_id, doc)

    async def get_user_skills(self, *, user_id: str) -> Optional[UserSkillDoc]:
        doc = await self._read(self._settings.postgres_user_skills_table, user_id)
        return UserSkillDoc(**doc) if doc is not None else None

    async def upsert_user_skills(
        self, *, user_id: str, rules: List[SkillRule]
    ) -> UserSkillDoc:
        prior = await self._read(self._settings.postgres_user_skills_table, user_id)
        doc = UserSkillDoc(
            user_id=user_id,
            rules=list(rules),
            version=(prior["version"] + 1) if prior else 1,
            updated_at=datetime.now(timezone.utc),
        )
        # Store JSON-shaped (datetime → ISO string) so the JSONB doc round-trips cleanly.
        await self._write(self._settings.postgres_user_skills_table, user_id,
                          doc.model_dump(mode="json"))
        return doc

    async def get_trends(self, *, limit: int = 6) -> List[Trend]:
        doc = await self._read(self._settings.postgres_trends_table, TRENDS_DOC_KEY)
        trends = [Trend(**t) for t in (doc or {}).get("trends", [])]
        return select_current_trends(
            trends, limit=limit, ttl_days=self._settings.trend_scout_ttl_days
        )

    async def upsert_trends(self, *, trends: List[Trend]) -> None:
        if not trends:
            return  # an empty scan never clobbers the last good snapshot
        doc = {
            "id": TRENDS_DOC_KEY,
            "date": datetime.now(timezone.utc).date().isoformat(),
            "trends": [t.model_dump(mode="json") for t in trends],
        }
        await self._write(self._settings.postgres_trends_table, TRENDS_DOC_KEY, doc)

    async def save_checkpoint(self, *, task_id: str, data: dict) -> None:
        await self._write(self._settings.postgres_checkpoints_table, task_id, {"id": task_id, **data})

    async def load_checkpoint(self, *, task_id: str) -> Optional[dict]:
        return await self._read(self._settings.postgres_checkpoints_table, task_id)

    # ── Cross-replica coordination ────────────────────────────────────────────

    async def try_acquire_lease(self, *, name: str, owner: str, ttl_seconds: float) -> bool:
        """One statement, so the winner is decided by the database rather than by a
        read-then-write that two replicas can both pass.

        The conflict clause updates ONLY when the row has expired or we already own it.
        `RETURNING` reports rows actually written, so a live lease held by someone else
        filters the UPDATE out and comes back EMPTY — that absence is the "you lost" signal.
        One statement, so there is no window between deciding and taking it.
        """
        pool = await self._pool()
        table = self._settings.postgres_leases_table
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"INSERT INTO {table} (name, owner, expires_at) "
                f"VALUES ($1, $2, now() + make_interval(secs => $3)) "
                f"ON CONFLICT (name) DO UPDATE "
                f"  SET owner = EXCLUDED.owner, expires_at = EXCLUDED.expires_at "
                f"  WHERE {table}.expires_at < now() OR {table}.owner = EXCLUDED.owner "
                f"RETURNING owner",
                name, owner, float(ttl_seconds),
            )
        # No row at all means the ON CONFLICT matched but the WHERE filtered the update
        # out — i.e. a live lease held by someone else.
        return bool(row) and row["owner"] == owner

    async def release_lease(self, *, name: str, owner: str) -> None:
        """`AND owner = $2` is the whole point: if our lease expired and another replica
        took over, this deletes nothing rather than yanking the lock out from under it."""
        pool = await self._pool()
        table = self._settings.postgres_leases_table
        async with pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {table} WHERE name = $1 AND owner = $2", name, owner)

    async def notify_task(self, *, task_id: str, seq: int) -> None:
        """NOTIFY carrying only the high-water `seq`.

        Deliberately not the event: NOTIFY payloads are capped (8000 bytes) and a `final`
        event with an embedded HTML brand card sails past that. The durable log is the
        source of truth; this only says "there is something new to read"."""
        pool = await self._pool()
        async with pool.acquire() as conn:
            # The channel name is an identifier, so it cannot be parameterised — hence
            # quote_ident, and `pg_notify` rather than raw NOTIFY (which takes no params).
            await conn.execute("SELECT pg_notify($1, $2)", _channel(task_id), str(int(seq)))

    async def watch_task(self, *, task_id: str) -> AsyncIterator[int]:
        """LISTEN on a dedicated connection, yielding each announced `seq`.

        Dedicated (not pooled) because LISTEN is connection-scoped: handing the connection
        back to the pool between notifications would silently stop the subscription. The
        connection is closed in the `finally`, which is what unsubscribes."""
        import asyncpg  # lazy import, like _pool()

        s = self._settings
        queue: asyncio.Queue = asyncio.Queue()
        conn = await asyncpg.connect(dsn=s.postgres_dsn, **_connect_kwargs(s))
        try:
            def _on_notify(_conn, _pid, _channel, payload) -> None:
                try:
                    queue.put_nowait(int(payload))
                except (TypeError, ValueError):
                    pass  # a malformed hint costs latency, never correctness
            await conn.add_listener(_channel(task_id), _on_notify)
            while True:
                yield await queue.get()
        finally:
            await conn.close()

    async def create_video_job(self, *, job_id: str, task_id: str, platform: str, storyboard: dict) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        doc = {
            "id": job_id, "task_id": task_id, "platform": platform, "status": "pending",
            "storyboard": storyboard, "output_path": None, "error": None,
            "created_at": now, "updated_at": now,
        }
        pool = await self._pool()
        table = self._settings.postgres_video_jobs_table
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {table} (id, task_id, platform, status, doc) "
                f"VALUES ($1, $2, $3, $4, $5::jsonb)",
                job_id, task_id, platform, "pending", json.dumps(doc),
            )
        return doc

    async def update_video_job(self, *, job_id: str, **fields) -> dict:
        pool = await self._pool()
        table = self._settings.postgres_video_jobs_table
        async with pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT doc FROM {table} WHERE id = $1", job_id)
            if row is None:
                raise KeyError(f"unknown video job: {job_id}")
            doc = json.loads(row["doc"])
            doc.update(fields)
            doc["updated_at"] = datetime.now(timezone.utc).isoformat()
            await conn.execute(
                f"UPDATE {table} SET doc = $2::jsonb, status = $3, updated_at = now() WHERE id = $1",
                job_id, json.dumps(doc), doc.get("status", "pending"),
            )
        return doc

    async def get_video_job(self, *, job_id: str) -> Optional[dict]:
        pool = await self._pool()
        table = self._settings.postgres_video_jobs_table
        async with pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT doc FROM {table} WHERE id = $1", job_id)
        return json.loads(row["doc"]) if row else None

    async def upsert_posting_plan(self, *, plan: dict) -> None:
        pool = await self._pool()
        table = self._settings.postgres_posting_plans_table
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {table} (id, business_id, user_id, status, doc) "
                f"VALUES ($1, $2, $3, $4, $5::jsonb) "
                f"ON CONFLICT (id) DO UPDATE SET business_id = EXCLUDED.business_id, "
                f"user_id = EXCLUDED.user_id, status = EXCLUDED.status, "
                f"doc = EXCLUDED.doc, updated_at = now()",
                plan["plan_id"], plan.get("business_id"), plan.get("user_id"),
                plan.get("status", "draft"), json.dumps(plan),
            )

    async def get_posting_plan(self, *, plan_id: str) -> Optional[dict]:
        return await self._read(self._settings.postgres_posting_plans_table, plan_id)

    async def list_posting_plans(
        self,
        *,
        business_id: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[dict]:
        clauses, args = [], []
        for column, value in (("business_id", business_id), ("user_id", user_id),
                              ("status", status)):
            if value is not None:
                args.append(value)
                clauses.append(f"{column} = ${len(args)}")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        pool = await self._pool()
        table = self._settings.postgres_posting_plans_table
        async with pool.acquire() as conn:
            rows = await conn.fetch(f"SELECT doc FROM {table}{where} ORDER BY updated_at", *args)
        return [json.loads(row["doc"]) for row in rows]


class PostgresCheckpointStorage(CheckpointStorage):
    """MAF CheckpointStorage backed by the Postgres `workflow_checkpoints` table.
    Each WorkflowCheckpoint is stored as its `to_dict()` in a
    JSONB column; `seq` (insertion order) drives list/get_latest, so we make no
    assumption about the checkpoint timestamp type."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool_obj = None

    @property
    def _table(self) -> str:
        return self._settings.postgres_checkpoints_table

    async def _pool(self):
        if self._pool_obj is None:
            import asyncpg  # lazy import

            self._pool_obj = await asyncpg.create_pool(
                dsn=self._settings.postgres_dsn, **_connect_kwargs(self._settings)
            )
            async with self._pool_obj.acquire() as conn:
                await conn.execute(_checkpoints_ddl(self._table))
        return self._pool_obj

    async def save(self, checkpoint: "WorkflowCheckpoint") -> str:
        # `to_dict()` is a SHALLOW conversion: nested values stay live framework objects
        # (e.g. WorkflowMessage, our pydantic messages), which `json.dumps` cannot encode.
        # Mirror MAF's own FileCheckpointStorage: run the checkpoint encoder first — it
        # pickles non-JSON-native values to base64 strings — then JSON-serialize the result.
        from agent_framework._workflows._checkpoint_encoding import encode_checkpoint_value

        pool = await self._pool()
        doc = json.dumps(encode_checkpoint_value(checkpoint.to_dict()))
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {self._table} (id, workflow_name, doc) VALUES ($1, $2, $3::jsonb) "
                f"ON CONFLICT (id) DO UPDATE SET doc = EXCLUDED.doc, "
                f"workflow_name = EXCLUDED.workflow_name, updated_at = now()",
                checkpoint.checkpoint_id,
                checkpoint.workflow_name,
                doc,
            )
        return checkpoint.checkpoint_id

    @staticmethod
    def _from_doc(doc: str) -> "WorkflowCheckpoint":
        """Reverse `save`'s encoding: JSON-decode, then run the checkpoint decoder
        (un-pickles the base64-encoded framework/pydantic values) before rebuilding."""
        from agent_framework._workflows._checkpoint_encoding import decode_checkpoint_value

        return WorkflowCheckpoint.from_dict(decode_checkpoint_value(json.loads(doc)))

    async def load(self, checkpoint_id: str) -> "WorkflowCheckpoint":
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT doc FROM {self._table} WHERE id = $1", checkpoint_id)
        return self._from_doc(row["doc"])

    async def list_checkpoints(self, *, workflow_name: str) -> List["WorkflowCheckpoint"]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT doc FROM {self._table} WHERE workflow_name = $1 ORDER BY seq ASC",
                workflow_name,
            )
        return [self._from_doc(r["doc"]) for r in rows]

    async def list_checkpoint_ids(self, *, workflow_name: str) -> List[str]:
        return [c.checkpoint_id for c in await self.list_checkpoints(workflow_name=workflow_name)]

    async def get_latest(self, *, workflow_name: str):
        checkpoints = await self.list_checkpoints(workflow_name=workflow_name)
        return checkpoints[-1] if checkpoints else None  # seq ASC → last is newest

    async def delete(self, checkpoint_id: str) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            status = await conn.execute(f"DELETE FROM {self._table} WHERE id = $1", checkpoint_id)
        return status != "DELETE 0"
