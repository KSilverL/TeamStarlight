"""
Connectivity smoke test for the LLM_service store — Azure Cosmos DB for PostgreSQL.

Reads DATABASE_URL + POSTGRES_SSLMODE from LLM_service/.env (the same values the
service uses), then exercises: SSL-required connect → confirm it's a Citus/Cosmos
cluster on an encrypted link → check the three app tables → write/read/cleanup a
temp doc. Exits non-zero if any step fails.

    /opt/anaconda3/envs/TeamProject/bin/python3 LLM_service/db_test.py
"""
import asyncio
import json
import os
import ssl as _ssl
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

DSN = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
SSLMODE = os.getenv("POSTGRES_SSLMODE", "require")


def _ssl_ctx(mode: str | None):
    """libpq sslmode → asyncpg `ssl` arg (None = let the DSN decide)."""
    mode = (mode or "").strip().lower()
    if not mode or mode in ("allow", "prefer"):
        return None
    if mode == "disable":
        return False
    ctx = _ssl.create_default_context()
    if mode in ("require", "verify-ca"):
        ctx.check_hostname = False
        if mode == "require":
            ctx.verify_mode = _ssl.CERT_NONE
    return ctx


async def main():
    results = {}
    if not DSN:
        print("❌ No DATABASE_URL / POSTGRES_DSN in LLM_service/.env")
        sys.exit(2)

    host = DSN.split("@")[-1].split("/")[0]
    print("=" * 60)
    print(f"Target: {host}  (sslmode={SSLMODE or 'unset'})")

    ssl_arg = _ssl_ctx(SSLMODE)
    conn = None

    # 1. SSL-required connection
    print("\n1. TESTING CONNECTION (SSL)...")
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(dsn=DSN, **({} if ssl_arg is None else {"ssl": ssl_arg})),
            timeout=20,
        )
        ver = await conn.fetchval("SELECT version()")
        print(f"   ✅ Connected! Server: {ver[:70]}...")
        results["connection"] = "PASS"
    except Exception as e:
        print(f"   ❌ Connection FAILED: {e}")
        sys.exit(1)

    # 2. Confirm it's a Citus/Cosmos cluster on an encrypted link
    print("\n2. CONFIRMING COSMOS / CITUS + ENCRYPTION...")
    try:
        db = await conn.fetchval("SELECT current_database()")
        citus = await conn.fetchval("SELECT extversion FROM pg_extension WHERE extname = 'citus'")
        is_ssl = await conn.fetchval("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
        if citus:
            print(f"   ✅ Citus extension v{citus} present (db '{db}') — this is Cosmos for PostgreSQL")
            results["citus"] = f"PASS (v{citus})"
        else:
            print(f"   ⚠️  No Citus extension found (db '{db}') — plain Postgres, not a Cosmos cluster")
            results["citus"] = "WARN: no citus extension"
        print(f"   {'✅' if is_ssl else '❌'} Connection encrypted: ssl={is_ssl}")
        results["ssl"] = "PASS" if is_ssl else "FAIL: not encrypted"
    except Exception as e:
        print(f"   ⚠️  Probe warning: {e}")
        results["citus"] = f"WARN: {e}"

    # 3. Existing application tables
    print("\n3. CHECKING APPLICATION TABLES...")
    for table in (
        os.getenv("POSTGRES_PROFILES_TABLE", "brand_profiles"),
        os.getenv("POSTGRES_USER_SKILLS_TABLE", "user_skills"),
        os.getenv("POSTGRES_CHECKPOINTS_TABLE", "workflow_checkpoints"),
    ):
        try:
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
            print(f"   ✅ Table '{table}' exists — {count} rows")
            results[f"table_{table}"] = f"PASS ({count} rows)"
        except Exception as e:
            print(f"   ⚠️  Table '{table}' not found (auto-created on first service write): {e}")
            results[f"table_{table}"] = "NOT FOUND (expected pre-migration)"

    # 4. Write
    test_table = "_db_connectivity_test"
    print(f"\n4. TESTING WRITE (temp table '{test_table}')...")
    try:
        await conn.execute(
            f"CREATE TABLE IF NOT EXISTS {test_table} ("
            f"id TEXT PRIMARY KEY, doc JSONB NOT NULL, "
            f"updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        test_doc = json.dumps({"msg": "hello from LLM_service", "test": True})
        await conn.execute(
            f"INSERT INTO {test_table} (id, doc) VALUES ($1, $2::jsonb) "
            f"ON CONFLICT (id) DO UPDATE SET doc = EXCLUDED.doc, updated_at = now()",
            "test-key-1", test_doc,
        )
        print("   ✅ Write succeeded")
        results["write"] = "PASS"
    except Exception as e:
        print(f"   ❌ Write FAILED: {e}")
        results["write"] = f"FAIL: {e}"

    # 5. Read
    print("\n5. TESTING READ...")
    try:
        row = await conn.fetchrow(f"SELECT doc FROM {test_table} WHERE id = $1", "test-key-1")
        if row:
            print(f"   ✅ Read succeeded: {json.loads(row['doc'])}")
            results["read"] = "PASS"
        else:
            print("   ❌ Read returned no rows")
            results["read"] = "FAIL: no rows"
    except Exception as e:
        print(f"   ❌ Read FAILED: {e}")
        results["read"] = f"FAIL: {e}"

    # 6. Cleanup
    print("\n6. CLEANUP...")
    try:
        await conn.execute(f"DROP TABLE IF EXISTS {test_table}")
        print("   ✅ Test table dropped")
    except Exception as e:
        print(f"   ⚠️  Cleanup warning: {e}")

    await conn.close()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY:")
    failed = False
    for k, v in results.items():
        status = "✅" if v.startswith("PASS") else ("⚠️" if v.startswith(("WARN", "NOT FOUND")) else "❌")
        if status == "❌":
            failed = True
        print(f"  {status} {k}: {v}")
    print("=" * 60)
    sys.exit(1 if failed else 0)


asyncio.run(main())
