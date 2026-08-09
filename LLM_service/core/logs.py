"""
Structured logging for the LLM service.

One JSON object per line on stdout, so a log shipper (Container Apps / CloudWatch /
Loki) can index fields instead of regex-ing prose. Built on stdlib `logging` — no new
dependency, and every existing `logging.getLogger(__name__)` call site in the package
is picked up for free with no edit.

    {"ts":"2026-08-09T12:00:00.123Z","level":"INFO","logger":"LLM_service.api",
     "msg":"run_completed","request_id":"b1f0…","task_id":"sess-42","duration_ms":8123}

**The point is correlation, not prettiness.** A run crosses an HTTP request, a detached
background task, a roundtable fan-out and a render job, and until now nothing tied those
together — a failure in an executor produced no log line at all, just a task status. So
this module carries a `contextvars` bag: bind `request_id`/`task_id` once and every log
record emitted underneath it — including from `asyncio.create_task`, which copies the
context at creation — carries them without a single call site passing them down. The bag is
merged onto records by a log-record factory installed at import, so the fields are on the
RECORD (visible to every handler), not just in this module's formatted output.

`X-Request-ID` is honoured on the way in and echoed on the way out, so a trace started by
the Java backend keeps ONE id across both services (see api.py's middleware).

Configuration (env, read once at `configure_logging()`):
  LOG_LEVEL   INFO (default) | DEBUG | WARNING | …
  LOG_FORMAT  json (default) | text — `text` is the human-readable dev form, same fields.
"""

from __future__ import annotations

import contextlib
import contextvars
import datetime as _dt
import json
import logging
import os
import sys
from typing import Any, Iterator, Optional

# The bag of fields every record under this context inherits. A plain dict rather than
# one ContextVar per field: binding is a single set(), and the formatter needs one read.
_context: contextvars.ContextVar[dict] = contextvars.ContextVar("llm_log_context", default={})

# LogRecord's own attributes. Anything else a caller passed via `extra=` is ours to emit,
# which is what lets `logger.info("run_started", extra={"platforms": [...]})` work with no
# per-field plumbing. `taskName` is 3.12+; harmless to list on 3.11.
_RESERVED = frozenset((
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info", "taskName",
    "thread", "threadName",
    "_ctx",   # our own context snapshot — merged separately, never emitted as a field
))


def bind(**fields: Any) -> None:
    """Add fields to the current context, for the rest of THIS context's life.

    Use inside a coroutine that owns its context — a detached background run, a render
    job — where there is no scope to exit. `asyncio.create_task` copies the context at
    creation, so a bind inside the task cannot leak back to whoever spawned it.
    """
    _context.set({**_context.get(), **fields})


@contextlib.contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Bind fields for the duration of a block, then restore. The request-scoped form."""
    token = _context.set({**_context.get(), **fields})
    try:
        yield
    finally:
        _context.reset(token)


def current_context() -> dict:
    """The fields currently bound — for a caller that needs to echo one (the request id
    into a response header, say) rather than log it."""
    return dict(_context.get())


# ── Context injection ─────────────────────────────────────────────────────────
# Bound fields reach the record AT CREATION, via the log-record factory, rather than being
# merged by the formatter. It matters: a formatter only sees records routed to its own
# handler, so merging there would make the context invisible to every other handler — a
# host's, a test's caplog, anything a future deployment adds — and those are exactly where
# someone looks when the primary log isn't enough. Here it is simply part of the record.
#
# The context is held in a snapshot attribute and exposed through `__getattr__` rather than
# written into `record.__dict__`, because `Logger.makeRecord` REJECTS an `extra=` key that
# already exists on the record ("Attempt to overwrite %r in LogRecord"). Writing context
# into `__dict__` would therefore turn `logger.info(..., extra={"task_id": …})` into a
# KeyError at any call site that happens to sit under a bound `task_id` — i.e. exactly the
# ones that matter. With `__getattr__`, normal attribute lookup still finds an explicit
# `extra` first (it's in `__dict__`), an inherited field resolves as a fallback, and the two
# can never collide.

class _ContextRecord(logging.LogRecord):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Snapshot, not a live read: the record may be formatted on another thread (the
        # logging queue, a shipper) long after the context that produced it has been reset.
        self._ctx = _context.get()

    def __getattr__(self, name: str) -> Any:  # only consulted when normal lookup fails
        try:
            return self.__dict__["_ctx"][name]
        except KeyError:
            raise AttributeError(name) from None


def _record_fields(record: logging.LogRecord) -> dict:
    """The non-standard fields on one record: the bound context, then whatever the call site
    passed as `extra=` — that order, so an explicit field wins over an inherited one."""
    fields = dict(getattr(record, "_ctx", None) or {})
    fields.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED})
    return fields


# Installed at import, not in configure_logging(): correlation should not depend on a setup
# call having run first. Costs one dict read per record when nothing is bound.
if logging.getLogRecordFactory() is not _ContextRecord:
    logging.setLogRecordFactory(_ContextRecord)


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Non-serializable values degrade to `repr` rather than
    raising — a logging call must never be the thing that breaks a request."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": _dt.datetime.fromtimestamp(record.created, _dt.timezone.utc)
                     .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(_record_fields(record))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=repr, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """The same fields, laid out for a human reading a terminal. Dev-only (LOG_FORMAT=text)."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        fields = _record_fields(record)
        if fields:
            base += "  " + " ".join(f"{k}={v!r}" for k, v in sorted(fields.items()))
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def build_formatter(fmt: Optional[str] = None) -> logging.Formatter:
    fmt = (fmt or os.getenv("LOG_FORMAT") or "json").strip().lower()
    if fmt == "text":
        return TextFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                             datefmt="%H:%M:%S")
    return JsonFormatter()


_configured = False


def configure_logging(*, level: Optional[str] = None, fmt: Optional[str] = None,
                      force: bool = False) -> None:
    """Install the structured handler on the ROOT logger, once per process.

    Root rather than a package logger so third-party output (uvicorn, MAF, the Azure SDKs)
    lands in the same stream and the same shape — a deployment that has to grep two log
    formats is one where the JSON was pointless.

    Idempotent: `create_app()` calls it, and so may a CLI entry point or a test, and the
    second call is a no-op. Anything that already attached a handler to root (pytest's
    caplog, a host that configures logging itself) is left alone unless `force`.
    """
    global _configured
    if _configured and not force:
        return

    root = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(build_formatter(fmt))
    handler.set_name("llm-service-structured")

    for existing in list(root.handlers):
        if existing.get_name() == "llm-service-structured":
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel((level or os.getenv("LOG_LEVEL") or "INFO").strip().upper())

    # Third-party loggers that are chatty at INFO and say nothing this service's own lines
    # don't. Measured on one partial mock run: MAF's workflow runner alone ("Starting superstep
    # N", "Created checkpoint …", once per superstep) was 13 of 23 lines, and httpx adds one per
    # outbound call — which on a roundtable run is every persona turn. Capped at WARNING rather
    # than filtered out, so their genuine failures still surface.
    for noisy in ("httpx", "httpcore", "agent_framework._workflows",
                  "azure.core.pipeline.policies.http_logging_policy"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def reset_logging() -> None:
    """Drop the installed handler and allow reconfiguration — for tests only."""
    global _configured
    root = logging.getLogger()
    for existing in list(root.handlers):
        if existing.get_name() == "llm-service-structured":
            root.removeHandler(existing)
    _configured = False
