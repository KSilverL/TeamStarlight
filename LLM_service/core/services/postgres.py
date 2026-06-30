"""
PostgreSQL-backed persistence.

`PostgresStore` is the StoreService — brand profiles (`brand_profiles`) plus the
StoreService checkpoint KV. `PostgresCheckpointStorage` is the MAF CheckpointStorage
that persists every workflow superstep to `workflow_checkpoints`, so a RequestPort
pause survives a process restart (replacing the in-process MemorySaver). Both store
whole documents in a JSONB `doc` column, so the same code shapes apply as the old
Cosmos impl did.

`asyncpg` is **lazy-imported inside `_pool()`** so this module imports cleanly in
mock mode / tests where the driver (and a database) are absent. The `_read` / `_write`
seams on `PostgresStore` are overridable, so contract-parity tests exercise the
shaping logic without a database.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional

from agent_framework import CheckpointStorage, WorkflowCheckpoint

from ..config import Settings
from ..skill_schema import SkillRule, UserSkillDoc
from .base import StoreService, empty_profile


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
    # need a JSONB index — Phase 1 doesn't need that query, but the columns are free.
    return (
        f"CREATE TABLE IF NOT EXISTS {table} ("
        f"id TEXT PRIMARY KEY, task_id TEXT, platform TEXT, status TEXT, "
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
            self._pool_obj = await asyncpg.create_pool(dsn=s.postgres_dsn)
            async with self._pool_obj.acquire() as conn:
                await conn.execute(_profiles_ddl(s.postgres_profiles_table))
                await conn.execute(_user_skills_ddl(s.postgres_user_skills_table))
                await conn.execute(_checkpoints_ddl(s.postgres_checkpoints_table))
                await conn.execute(_video_jobs_ddl(s.postgres_video_jobs_table))
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

    async def save_checkpoint(self, *, task_id: str, data: dict) -> None:
        await self._write(self._settings.postgres_checkpoints_table, task_id, {"id": task_id, **data})

    async def load_checkpoint(self, *, task_id: str) -> Optional[dict]:
        return await self._read(self._settings.postgres_checkpoints_table, task_id)

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


class PostgresCheckpointStorage(CheckpointStorage):
    """MAF CheckpointStorage backed by the Postgres `workflow_checkpoints` table
    (MIGRATION_PLAN §8.2). Each WorkflowCheckpoint is stored as its `to_dict()` in a
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

            self._pool_obj = await asyncpg.create_pool(dsn=self._settings.postgres_dsn)
            async with self._pool_obj.acquire() as conn:
                await conn.execute(_checkpoints_ddl(self._table))
        return self._pool_obj

    async def save(self, checkpoint: "WorkflowCheckpoint") -> str:
        pool = await self._pool()
        doc = json.dumps(checkpoint.to_dict())
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

    async def load(self, checkpoint_id: str) -> "WorkflowCheckpoint":
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT doc FROM {self._table} WHERE id = $1", checkpoint_id)
        return WorkflowCheckpoint.from_dict(json.loads(row["doc"]))

    async def list_checkpoints(self, *, workflow_name: str) -> List["WorkflowCheckpoint"]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT doc FROM {self._table} WHERE workflow_name = $1 ORDER BY seq ASC",
                workflow_name,
            )
        return [WorkflowCheckpoint.from_dict(json.loads(r["doc"])) for r in rows]

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
