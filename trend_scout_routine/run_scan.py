"""
Trend Scout — the daily WRITE side (docs/TREND_SCOUT_IMPLEMENTATION.md §5, Phase 2).

Runs OUTSIDE the LLM service process — this script never imports `LLM_service` and the
service never imports this. The only contact surface between the two sides is the
`trends` table: one rolling JSONB document keyed `current`, shaped exactly like
`PostgresStore.upsert_trends` writes it:

    {"id": "current", "date": "<YYYY-MM-DD>", "trends": [
        {"text": ..., "category": ..., "source": ..., "captured_at": ..., "expires_at": ...},
    ]}

Flow (one run = one daily scan):
  1. Drive the Foundry agent (defined in the portal: prompt.md instructions + the web
     grounding tool, referenced by name+version via the OpenAI responses API) with the
     trigger message; it returns a strict JSON array of {text, category, source}.
  2. Validate + coerce the items (category whitelist, length cap, dedupe, max 15).
  3. Stamp `captured_at` / `expires_at` HERE (an LLM's idea of "today" is not trustworthy).
  4. Upsert the rolling `current` doc — ONLY on a non-empty result (decision #1): a
     failed/empty scan exits non-zero without touching the last good snapshot.

Offline / dev paths: `--from-file scan.json` bypasses the agent (feed a saved scan),
`--dry-run` prints the doc instead of writing, `--verify` reads the stored doc back,
`--print-instructions` emits the resolved prompt to paste into the portal agent.
`--ensure-table` creates the table (dev convenience — the production least-privilege
role deliberately cannot; provision with LLM_service/migrations/003_trends.sql instead).

Env (see .env.example): FOUNDRY_PROJECT_ENDPOINT, TREND_AGENT_NAME, TREND_AGENT_VERSION,
TREND_MARKET, TREND_LANGUAGE, TREND_TTL_DAYS,
TRENDS_DATABASE_URL (falls back to DATABASE_URL), POSTGRES_SSLMODE, POSTGRES_TRENDS_TABLE.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import ssl as _ssl
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRENDS_DOC_KEY = "current"
ALLOWED_CATEGORIES = {"news", "meme", "format", "cultural", "general"}
MAX_TRENDS = 15
MAX_TEXT_CHARS = 300  # Appendix A asks ≤ ~200; hard-truncate runaways rather than drop them
TRIGGER_MESSAGE = "Run today's trend scan and return the JSON array per your instructions."


# ── Env (dependency-free .env loader; own copy — no imports across the boundary) ──

def load_env() -> None:
    """Load KEY=VALUE pairs; real environment always wins. Reads this folder's .env
    first, then falls back to LLM_service/.env (dev convenience — the two sides may
    share a database DSN locally, never a process)."""
    for env_path in (HERE / ".env", HERE.parent / "LLM_service" / ".env"):
        if not env_path.is_file():
            continue
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            key, sep, value = line.partition("=")
            key = key.strip()
            if not sep or not key or key in os.environ:
                continue
            value = value.strip()
            if value[:1] in ("'", '"'):
                end = value.find(value[0], 1)
                value = value[1:end] if end != -1 else value[1:]
            else:
                value = value.split(" #")[0].strip()
            os.environ[key] = value


# ── Parse + validate the agent's output ─────────────────────────────────────────

def parse_scan(raw: str) -> list[dict]:
    """Parse the agent's STRICT-JSON-ONLY output into clean {text, category, source}
    items. Defensive against the classic LLM slips (code fences, prose around the
    array) but strict about content: bad items are dropped, never invented."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("["):
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            return []
        text = text[start:end + 1]
    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []

    cleaned: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        line = str(item.get("text") or "").strip()
        if not line:
            continue
        norm = re.sub(r"\W+", " ", line.lower()).strip()
        if norm in seen:
            continue  # no duplicates / near-duplicate phrasings
        seen.add(norm)
        category = str(item.get("category") or "general").strip().lower()
        if category not in ALLOWED_CATEGORIES:
            category = "general"
        source = item.get("source")
        source = str(source).strip() if source else None
        cleaned.append({"text": line[:MAX_TEXT_CHARS], "category": category, "source": source})
        if len(cleaned) >= MAX_TRENDS:
            break
    return cleaned


def stamp_and_wrap(items: list[dict], *, ttl_days: int) -> dict:
    """Stamp captured_at/expires_at at write time and wrap into the rolling doc."""
    now = datetime.now(timezone.utc)
    captured = now.isoformat()
    expires = (now + timedelta(days=ttl_days)).isoformat()
    return {
        "id": TRENDS_DOC_KEY,
        "date": now.date().isoformat(),
        "trends": [
            {**item, "captured_at": captured, "expires_at": expires} for item in items
        ],
    }


# ── Foundry agent (portal-defined, called by agent_reference) ───────────────────

def build_instructions() -> str:
    """The Appendix A system prompt with MARKET/LANGUAGE resolved from env — this is
    what gets pasted into the portal agent's Instructions (`--print-instructions`)."""
    prompt = (HERE / "prompt.md").read_text(encoding="utf-8")
    market = os.environ.get("TREND_MARKET", "global, English-language")
    language = os.environ.get("TREND_LANGUAGE", "English")
    return prompt.replace("{MARKET}", market).replace("{LANGUAGE}", language)


def run_agent() -> str:
    """One grounded scan: call the portal-defined Foundry agent (instructions + web
    grounding tool live on the agent version) through the project's OpenAI responses
    API, referenced by TREND_AGENT_NAME/TREND_AGENT_VERSION. Azure SDK imports live
    here so the offline paths need no azure deps. Requires azure-ai-projects>=2.1.0."""
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        raise SystemExit("FOUNDRY_PROJECT_ENDPOINT is not set")
    agent_name = os.environ.get("TREND_AGENT_NAME")
    if not agent_name:
        raise SystemExit(
            "TREND_AGENT_NAME is not set — create the agent in the Foundry portal first "
            "(paste `run_scan.py --print-instructions` output, attach the web grounding "
            "tool, publish a version; see README.md)"
        )

    project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    openai_client = project.get_openai_client()

    reference: dict = {"name": agent_name, "type": "agent_reference"}
    version = os.environ.get("TREND_AGENT_VERSION")
    if version:
        reference["version"] = version

    response = openai_client.responses.create(
        input=[{"role": "user", "content": TRIGGER_MESSAGE}],
        extra_body={"agent_reference": reference},
    )
    reply = (getattr(response, "output_text", "") or "").strip()
    if not reply:
        raise SystemExit("agent returned an empty reply")
    return reply


# ── Database (asyncpg; same sslmode translation the service uses) ───────────────

def _ssl_kwargs() -> dict:
    mode = (os.environ.get("POSTGRES_SSLMODE") or "").strip().lower()
    if not mode or mode in ("allow", "prefer"):
        return {}
    if mode == "disable":
        return {"ssl": False}
    ctx = _ssl.create_default_context()
    if mode == "require":
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
    elif mode == "verify-ca":
        ctx.check_hostname = False
    return {"ssl": ctx}


def _dsn_and_table() -> tuple[str, str]:
    dsn = os.environ.get("TRENDS_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("TRENDS_DATABASE_URL / DATABASE_URL is not set")
    return dsn, os.environ.get("POSTGRES_TRENDS_TABLE", "trends")


async def upsert_doc(doc: dict, *, ensure_table: bool) -> None:
    import asyncpg

    dsn, table = _dsn_and_table()
    conn = await asyncpg.connect(dsn=dsn, **_ssl_kwargs())
    try:
        if ensure_table:
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table} ("
                f"id TEXT PRIMARY KEY, doc JSONB NOT NULL, "
                f"updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
        await conn.execute(
            f"INSERT INTO {table} (id, doc) VALUES ($1, $2::jsonb) "
            f"ON CONFLICT (id) DO UPDATE SET doc = EXCLUDED.doc, updated_at = now()",
            TRENDS_DOC_KEY, json.dumps(doc),
        )
    finally:
        await conn.close()


async def verify_doc() -> int:
    import asyncpg

    dsn, table = _dsn_and_table()
    conn = await asyncpg.connect(dsn=dsn, **_ssl_kwargs())
    try:
        row = await conn.fetchrow(
            f"SELECT doc, updated_at FROM {table} WHERE id = $1", TRENDS_DOC_KEY
        )
    finally:
        await conn.close()
    if row is None:
        print("no `current` trends doc found — the routine has not run yet")
        return 1
    doc = json.loads(row["doc"])
    trends = doc.get("trends", [])
    categories: dict[str, int] = {}
    for t in trends:
        categories[t.get("category", "?")] = categories.get(t.get("category", "?"), 0) + 1
    print(f"current doc: date={doc.get('date')} updated_at={row['updated_at']} "
          f"trends={len(trends)} categories={categories}")
    for t in trends:
        print(f"  - [{t.get('category')}] {t.get('text')}")
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Daily trend scan → trends table")
    parser.add_argument("--from-file", metavar="PATH",
                        help="parse a saved scan (raw agent output / JSON array) instead of calling the agent")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the stamped doc instead of writing the database")
    parser.add_argument("--verify", action="store_true",
                        help="read the stored `current` doc back and print it")
    parser.add_argument("--print-instructions", action="store_true",
                        help="print the resolved agent Instructions (prompt.md with "
                             "MARKET/LANGUAGE filled) to paste into the Foundry portal")
    parser.add_argument("--ensure-table", action="store_true",
                        help="CREATE TABLE IF NOT EXISTS before writing (dev only — "
                             "the production role can't and shouldn't)")
    args = parser.parse_args()
    load_env()

    if args.print_instructions:
        print(build_instructions())
        return 0
    if args.verify:
        return asyncio.run(verify_doc())

    raw = (Path(args.from_file).read_text(encoding="utf-8") if args.from_file
           else run_agent())
    items = parse_scan(raw)
    if not items:
        # Decision #1: an empty/unparseable scan NEVER clobbers the last good snapshot.
        print("scan produced no usable trends — leaving the stored snapshot untouched",
              file=sys.stderr)
        print(f"raw reply (first 400 chars): {raw[:400]!r}", file=sys.stderr)
        return 1

    ttl_days = int(os.environ.get("TREND_TTL_DAYS", "3"))
    doc = stamp_and_wrap(items, ttl_days=ttl_days)
    if args.dry_run:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0

    asyncio.run(upsert_doc(doc, ensure_table=args.ensure_table))
    print(f"upserted `current` trends doc: {len(doc['trends'])} trends for {doc['date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
