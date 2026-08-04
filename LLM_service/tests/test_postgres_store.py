"""
The credentialed PostgreSQL persistence (core/services/postgres.py): PostgresStore
and PostgresCheckpointStorage against a fake `asyncpg`.

test_contract_parity.py overrides `_read`/`_write`, so the SQL layer beneath them —
the lazy pool build, the DDL bootstrap, every statement that does NOT go through
those seams (video jobs, posting plans, the whole checkpoint table), and the
sslmode→ssl translation Cosmos DB needs — only ran with a real database. Here a
fake asyncpg driver (an in-memory table map that understands the handful of
statement shapes this module emits) exercises exactly those paths offline.
"""

from __future__ import annotations

import json
import re
import ssl as _ssl
from datetime import datetime, timezone

import pytest
from agent_framework import WorkflowCheckpoint

from LLM_service.core.config import Settings
from LLM_service.core.services import postgres
from LLM_service.core.skill_schema import SkillRule
from LLM_service.core.trend_schema import TRENDS_DOC_KEY, Trend
from LLM_service.tests.conftest import install_fake_module


# ── A fake asyncpg driver (in-memory rows, real SQL text) ─────────────────────

class FakeConnection:
    """Understands only the statement shapes postgres.py emits. Rows are dicts of
    the promoted columns plus `doc`, keyed by id, per table."""

    def __init__(self, db: "FakeDatabase") -> None:
        self._db = db

    async def execute(self, sql: str, *args) -> str:
        self._db.statements.append(sql)
        create = re.match(r"CREATE TABLE IF NOT EXISTS (\w+)", sql)
        if create:
            self._db.tables.setdefault(create.group(1), {})
            return "CREATE TABLE"

        insert = re.match(r"INSERT INTO (\w+) \(([^)]*)\)", sql)
        if insert:
            table, columns = insert.group(1), [c.strip() for c in insert.group(2).split(",")]
            row = dict(zip(columns, args))
            rows = self._db.tables.setdefault(table, {})
            if "ON CONFLICT" not in sql and row["id"] in rows:
                raise RuntimeError(f"duplicate key: {row['id']}")
            rows[row["id"]] = row
            return "INSERT 0 1"

        update = re.match(r"UPDATE (\w+) SET doc = \$2::jsonb, status = \$3", sql)
        if update:
            rows = self._db.tables.setdefault(update.group(1), {})
            rows[args[0]].update({"doc": args[1], "status": args[2]})
            return "UPDATE 1"

        delete = re.match(r"DELETE FROM (\w+) WHERE id = \$1", sql)
        if delete:
            removed = self._db.tables.setdefault(delete.group(1), {}).pop(args[0], None)
            return "DELETE 1" if removed is not None else "DELETE 0"

        raise AssertionError(f"fake asyncpg cannot handle: {sql}")

    async def fetchrow(self, sql: str, *args):
        rows = await self.fetch(sql, *args)
        return rows[0] if rows else None

    async def fetch(self, sql: str, *args) -> list:
        self._db.statements.append(sql)
        table = re.search(r"FROM (\w+)", sql).group(1)
        rows = list(self._db.tables.get(table, {}).values())
        where = re.search(r"WHERE (.+?)(?: ORDER BY|$)", sql)
        if where:
            for i, clause in enumerate(where.group(1).split(" AND ")):
                column = clause.split(" = ")[0].strip()
                rows = [r for r in rows if r.get(column) == args[i]]
        return rows


class FakePool:
    def __init__(self, db: "FakeDatabase") -> None:
        self._db = db

    def acquire(self):
        db = self._db

        class _Ctx:
            async def __aenter__(self):
                return FakeConnection(db)

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


class FakeDatabase:
    def __init__(self) -> None:
        self.tables: dict[str, dict] = {}
        self.statements: list[str] = []
        self.pool_kwargs: list[dict] = []

    async def create_pool(self, **kwargs) -> FakePool:
        self.pool_kwargs.append(kwargs)
        return FakePool(self)


@pytest.fixture
def fake_db(monkeypatch) -> FakeDatabase:
    """Install a fake `asyncpg`; postgres.py lazy-imports it inside `_pool()`."""
    db = FakeDatabase()
    install_fake_module(monkeypatch, "asyncpg", create_pool=db.create_pool)
    return db


def _settings(**over) -> Settings:
    base = dict(postgres_dsn="postgresql://user:pw@host:5432/newsroom")
    base.update(over)
    return Settings(**base)


# ── sslmode → asyncpg `ssl` (the Supabase ⟷ Cosmos DB difference) ─────────────

def test_connect_kwargs_unset_or_negotiated_passes_nothing():
    for mode in (None, "", "allow", "prefer", "  PREFER  "):
        assert postgres._connect_kwargs(_settings(postgres_sslmode=mode)) == {}


def test_connect_kwargs_disable_turns_ssl_off():
    assert postgres._connect_kwargs(_settings(postgres_sslmode="disable")) == {"ssl": False}


def test_connect_kwargs_require_encrypts_without_verifying_chain():
    """Cosmos DB for PostgreSQL mandates TLS; `require` matches libpq — encrypt,
    don't validate the cert chain."""
    ctx = postgres._connect_kwargs(_settings(postgres_sslmode="require"))["ssl"]
    assert isinstance(ctx, _ssl.SSLContext)
    assert ctx.check_hostname is False and ctx.verify_mode == _ssl.CERT_NONE


def test_connect_kwargs_verify_ca_and_verify_full():
    ca = postgres._connect_kwargs(_settings(postgres_sslmode="verify-ca"))["ssl"]
    assert ca.check_hostname is False and ca.verify_mode == _ssl.CERT_REQUIRED
    full = postgres._connect_kwargs(_settings(postgres_sslmode="verify-full"))["ssl"]
    assert full.check_hostname is True and full.verify_mode == _ssl.CERT_REQUIRED


# ── Pool bootstrap ────────────────────────────────────────────────────────────

async def test_pool_is_built_once_and_creates_every_table(fake_db):
    store = postgres.PostgresStore(_settings(postgres_sslmode="require"))
    await store.get_profile(business_id="biz")
    await store.get_profile(business_id="biz")  # second call reuses the pool

    assert len(fake_db.pool_kwargs) == 1
    assert fake_db.pool_kwargs[0]["dsn"] == "postgresql://user:pw@host:5432/newsroom"
    assert isinstance(fake_db.pool_kwargs[0]["ssl"], _ssl.SSLContext)
    assert set(fake_db.tables) == {
        "brand_profiles", "user_skills", "workflow_checkpoints",
        "video_jobs", "trends", "posting_plans",
    }


async def test_table_name_overrides_are_honoured(fake_db):
    store = postgres.PostgresStore(_settings(postgres_profiles_table="bp_custom"))
    await store.upsert_profile(business_id="biz", profile={"must_do": ["hook"]})
    assert "bp_custom" in fake_db.tables
    assert json.loads(fake_db.tables["bp_custom"]["biz"]["doc"])["must_do"] == ["hook"]


# ── The document tables, through real SQL ─────────────────────────────────────

async def test_profile_roundtrip_through_sql(fake_db):
    store = postgres.PostgresStore(_settings())
    assert await store.get_profile(business_id="unknown") == {
        "id": "unknown", "must_do": [], "must_avoid": [], "examples": [], "updated_at": None,
    }
    assert (await store.get_profile(business_id=None))["id"] is None  # no store read at all

    await store.upsert_profile(business_id="biz", profile={"must_do": ["data hook"]})
    got = await store.get_profile(business_id="biz")
    assert got["id"] == "biz" and got["must_do"] == ["data hook"] and got["must_avoid"] == []


async def test_user_skills_roundtrip_and_version_bump(fake_db):
    store = postgres.PostgresStore(_settings())
    assert await store.get_user_skills(user_id="u1") is None

    rules = [SkillRule(text="Open with a stat", platform="linkedin", kind="positive")]
    first = await store.upsert_user_skills(user_id="u1", rules=rules)
    assert first.version == 1
    # Stored JSON-shaped so the JSONB doc round-trips (datetime → ISO string).
    stored = json.loads(fake_db.tables["user_skills"]["u1"]["doc"])
    assert isinstance(stored["updated_at"], str)

    second = await store.upsert_user_skills(user_id="u1", rules=rules)
    assert second.version == 2
    assert (await store.get_user_skills(user_id="u1")).version == 2


async def test_trends_snapshot_roundtrip_and_empty_scan_is_a_noop(fake_db):
    store = postgres.PostgresStore(_settings())
    assert await store.get_trends(limit=6) == []  # cold start, no row yet

    trend = Trend(text="a meme moment", category="meme",
                  captured_at=datetime.now(timezone.utc).isoformat())
    await store.upsert_trends(trends=[trend])
    assert [t.text for t in await store.get_trends(limit=6)] == ["a meme moment"]

    await store.upsert_trends(trends=[])  # never clobbers the last good snapshot
    assert json.loads(fake_db.tables["trends"][TRENDS_DOC_KEY]["doc"])["trends"]
    assert [t.text for t in await store.get_trends(limit=6)] == ["a meme moment"]


async def test_store_checkpoint_kv_roundtrip(fake_db):
    store = postgres.PostgresStore(_settings())
    assert await store.load_checkpoint(task_id="t1") is None
    await store.save_checkpoint(task_id="t1", data={"state": "paused"})
    assert (await store.load_checkpoint(task_id="t1")) == {"id": "t1", "state": "paused"}


# ── video_jobs (its own statements, not the _read/_write seams) ───────────────

async def test_video_job_lifecycle_promotes_columns(fake_db):
    store = postgres.PostgresStore(_settings())
    created = await store.create_video_job(
        job_id="job-1", task_id="task-1", platform="instagram_reels",
        storyboard={"brandName": "COFFEE"},
    )
    assert created["status"] == "pending" and created["output_path"] is None
    row = fake_db.tables["video_jobs"]["job-1"]
    # Promoted columns are written alongside the JSONB doc (so a future list query
    # needs no JSONB index).
    assert (row["task_id"], row["platform"], row["status"]) == ("task-1", "instagram_reels", "pending")

    updated = await store.update_video_job(job_id="job-1", status="done", output_path="/x/out.mp4")
    assert updated["status"] == "done" and updated["output_path"] == "/x/out.mp4"
    assert updated["updated_at"] >= created["created_at"]
    assert fake_db.tables["video_jobs"]["job-1"]["status"] == "done"  # column kept in sync

    assert (await store.get_video_job(job_id="job-1"))["output_path"] == "/x/out.mp4"
    assert await store.get_video_job(job_id="nope") is None


async def test_update_unknown_video_job_raises_keyerror(fake_db):
    store = postgres.PostgresStore(_settings())
    with pytest.raises(KeyError, match="unknown video job"):
        await store.update_video_job(job_id="ghost", status="done")


# ── posting_plans (filtered list query) ──────────────────────────────────────

def _plan(plan_id: str, **over) -> dict:
    base = {"plan_id": plan_id, "business_id": "biz", "user_id": "u1", "status": "draft",
            "items": []}
    base.update(over)
    return base


async def test_posting_plan_upsert_get_and_filtered_list(fake_db):
    store = postgres.PostgresStore(_settings())
    await store.upsert_posting_plan(plan=_plan("p1"))
    await store.upsert_posting_plan(plan=_plan("p2", status="active"))
    await store.upsert_posting_plan(plan=_plan("p3", business_id="other", user_id="u2"))

    assert (await store.get_posting_plan(plan_id="p1"))["status"] == "draft"
    assert await store.get_posting_plan(plan_id="ghost") is None

    assert {p["plan_id"] for p in await store.list_posting_plans()} == {"p1", "p2", "p3"}
    assert {p["plan_id"] for p in await store.list_posting_plans(business_id="biz")} == {"p1", "p2"}
    assert [p["plan_id"] for p in await store.list_posting_plans(status="active")] == ["p2"]
    assert [p["plan_id"] for p in await store.list_posting_plans(
        business_id="other", user_id="u2")] == ["p3"]


async def test_posting_plan_upsert_overwrites_in_place(fake_db):
    store = postgres.PostgresStore(_settings())
    await store.upsert_posting_plan(plan=_plan("p1"))
    await store.upsert_posting_plan(plan=_plan("p1", status="active"))
    assert len(await store.list_posting_plans()) == 1
    assert fake_db.tables["posting_plans"]["p1"]["status"] == "active"


# ── PostgresCheckpointStorage (the MAF CheckpointStorage) ────────────────────

def _checkpoint(workflow_name: str = "newsroom", **over) -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        workflow_name=workflow_name, graph_signature_hash="sig-1",
        state={"phase": "human_gate"}, iteration_count=2, **over,
    )


async def test_checkpoint_save_load_roundtrip(fake_db):
    storage = postgres.PostgresCheckpointStorage(_settings())
    cp = _checkpoint()
    returned = await storage.save(cp)
    assert returned == cp.checkpoint_id

    loaded = await storage.load(cp.checkpoint_id)
    assert isinstance(loaded, WorkflowCheckpoint)
    assert loaded.checkpoint_id == cp.checkpoint_id
    assert loaded.workflow_name == "newsroom"
    assert loaded.state == {"phase": "human_gate"}
    assert loaded.iteration_count == 2


async def test_checkpoint_save_is_idempotent_on_the_same_id(fake_db):
    """A superstep re-save must UPDATE (ON CONFLICT), not violate the primary key."""
    storage = postgres.PostgresCheckpointStorage(_settings())
    cp = _checkpoint()
    await storage.save(cp)
    cp.iteration_count = 5
    await storage.save(cp)
    assert (await storage.load(cp.checkpoint_id)).iteration_count == 5


async def test_checkpoint_listing_is_scoped_by_workflow_and_ordered(fake_db):
    storage = postgres.PostgresCheckpointStorage(_settings())
    first, second = _checkpoint(), _checkpoint()
    other = _checkpoint(workflow_name="other-graph")
    for cp in (first, second, other):
        await storage.save(cp)

    listed = await storage.list_checkpoints(workflow_name="newsroom")
    assert [c.checkpoint_id for c in listed] == [first.checkpoint_id, second.checkpoint_id]
    assert await storage.list_checkpoint_ids(workflow_name="newsroom") == [
        first.checkpoint_id, second.checkpoint_id]
    # seq ASC → the last row is the newest.
    assert (await storage.get_latest(workflow_name="newsroom")).checkpoint_id == second.checkpoint_id
    assert await storage.get_latest(workflow_name="nothing-here") is None


async def test_checkpoint_delete_reports_whether_a_row_went(fake_db):
    storage = postgres.PostgresCheckpointStorage(_settings())
    cp = _checkpoint()
    await storage.save(cp)
    assert await storage.delete(cp.checkpoint_id) is True
    assert await storage.delete(cp.checkpoint_id) is False


async def test_checkpoint_storage_honours_sslmode(fake_db):
    storage = postgres.PostgresCheckpointStorage(_settings(postgres_sslmode="require"))
    await storage.save(_checkpoint())
    assert isinstance(fake_db.pool_kwargs[0]["ssl"], _ssl.SSLContext)
