"""
Structured logging (core/logs.py) + the api.py request-context middleware.

What actually matters here is CORRELATION, so that is what these pin: that a field bound
once is carried by every record underneath it — including from a detached
`asyncio.create_task`, which is where a run's real work happens and where the old logging
told you nothing — and that an inbound `X-Request-ID` survives the whole trip so a trace
started in the Java backend stays one id across both services.

Everything runs against the real formatter, not a mock: a JSON line that doesn't parse is
the failure mode a log shipper actually hits.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

from LLM_service.api import create_app
from LLM_service.core.logs import (
    JsonFormatter,
    TextFormatter,
    bind,
    build_formatter,
    configure_logging,
    current_context,
    log_context,
    reset_logging,
)
from LLM_service.tests.conftest import run_app


def _emit(logger: logging.Logger, level: int, msg: str, **extra) -> logging.LogRecord:
    """Build a real LogRecord the way logging would, without installing a handler."""
    return logger.makeRecord(
        logger.name, level, "test.py", 1, msg, (), None, extra=extra or None)


@pytest.fixture(autouse=True)
def _clean_logging():
    reset_logging()
    yield
    reset_logging()


# ── The JSON envelope ─────────────────────────────────────────────────────────

def test_a_record_renders_as_one_parseable_json_line():
    line = JsonFormatter().format(_emit(logging.getLogger("t"), logging.INFO, "run_started"))

    assert "\n" not in line                       # one line per record, or the shipper splits it
    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "t"
    assert payload["msg"] == "run_started"
    assert payload["ts"].endswith("Z")            # UTC, not the container's local zone


def test_extra_fields_become_top_level_keys():
    """`logger.info("x", extra={...})` is the whole ergonomic story — the fields have to be
    indexable, not embedded in a formatted string."""
    line = JsonFormatter().format(
        _emit(logging.getLogger("t"), logging.INFO, "run_completed",
              task_id="sess-1", outputs=2, duration_ms=812.5))

    payload = json.loads(line)
    assert payload["task_id"] == "sess-1"
    assert payload["outputs"] == 2
    assert payload["duration_ms"] == 812.5


def test_a_non_serializable_value_degrades_instead_of_raising():
    """A logging call must never be the thing that breaks a request."""
    payload = json.loads(JsonFormatter().format(
        _emit(logging.getLogger("t"), logging.INFO, "odd", blob=object())))
    assert isinstance(payload["blob"], str)


def test_an_exception_is_captured_as_a_field():
    logger = logging.getLogger("t")
    try:
        raise ValueError("executor blew up")
    except ValueError:
        import sys
        record = logger.makeRecord(logger.name, logging.ERROR, "t.py", 1, "run_failed",
                                   (), sys.exc_info())
    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError: executor blew up" in payload["exc"]


def test_the_text_formatter_shows_the_same_fields(monkeypatch):
    """LOG_FORMAT=text is the local-dev form. It must not quietly DROP the context — a
    developer debugging a run is the reader who most needs the task id."""
    with log_context(request_id="req-1"):
        line = TextFormatter("%(levelname)s %(name)s: %(message)s").format(
            _emit(logging.getLogger("t"), logging.INFO, "run_started", task_id="sess-1"))

    assert "run_started" in line
    assert "request_id='req-1'" in line
    assert "task_id='sess-1'" in line
    assert "\n" not in line


def test_the_text_formatter_appends_a_traceback():
    import sys
    logger = logging.getLogger("t")
    try:
        raise ValueError("boom")
    except ValueError:
        record = logger.makeRecord(logger.name, logging.ERROR, "t.py", 1, "run_failed",
                                   (), sys.exc_info())
    line = TextFormatter("%(message)s").format(record)
    assert line.startswith("run_failed")
    assert "ValueError: boom" in line


def test_log_format_selects_the_formatter(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "text")
    assert isinstance(build_formatter(), TextFormatter)
    monkeypatch.setenv("LOG_FORMAT", "json")
    assert isinstance(build_formatter(), JsonFormatter)
    monkeypatch.delenv("LOG_FORMAT")
    assert isinstance(build_formatter(), JsonFormatter)   # json is the default


# ── Context propagation (the point of the exercise) ──────────────────────────

def test_bound_context_lands_on_records_no_call_site_touched():
    with log_context(request_id="req-1", task_id="sess-1"):
        payload = json.loads(JsonFormatter().format(
            _emit(logging.getLogger("deep.module"), logging.INFO, "something happened")))

    assert payload["request_id"] == "req-1"
    assert payload["task_id"] == "sess-1"


def test_context_is_restored_on_exit():
    assert current_context() == {}
    with log_context(request_id="req-1"):
        assert current_context() == {"request_id": "req-1"}
        with log_context(task_id="sess-1"):                 # nests
            assert current_context() == {"request_id": "req-1", "task_id": "sess-1"}
        assert current_context() == {"request_id": "req-1"}
    assert current_context() == {}


def test_an_explicit_extra_wins_over_an_inherited_field():
    with log_context(task_id="from-context"):
        payload = json.loads(JsonFormatter().format(
            _emit(logging.getLogger("t"), logging.INFO, "m", task_id="explicit")))
    assert payload["task_id"] == "explicit"


def test_passing_an_already_bound_field_as_extra_does_not_raise():
    """`Logger.makeRecord` refuses an `extra=` key that already exists on the record, so
    injecting context into `record.__dict__` would turn the most ordinary call —
    `logger.info(..., extra={"task_id": …})` under a bound task_id — into a KeyError. This
    is why the context lives behind `__getattr__` instead. Real call sites do exactly this
    (api.py's `_run_guarded` binds task_id and then logs it), so it must be a non-event."""
    logger = logging.getLogger("t")
    with log_context(task_id="bound", request_id="req-1"):
        logger.info("run_failed", extra={"task_id": "bound"})   # no KeyError


def test_context_fields_are_readable_as_record_attributes():
    """Not just in this module's formatted output: any handler — a host's, caplog — reads
    them off the record like a normal field."""
    with log_context(request_id="req-1"):
        record = _emit(logging.getLogger("t"), logging.INFO, "m")
    assert record.request_id == "req-1"
    with pytest.raises(AttributeError):
        record.not_a_bound_field


async def test_a_detached_task_inherits_the_context_and_cannot_leak_back():
    """`asyncio.create_task` copies the context, which is exactly why a background run keeps
    its request_id — and why a `bind` inside it can't contaminate the caller."""
    seen: dict = {}

    async def _background():
        bind(task_id="sess-bg")             # only this task's copy
        seen.update(current_context())

    with log_context(request_id="req-1"):
        await asyncio.create_task(_background())
        assert current_context() == {"request_id": "req-1"}   # unchanged out here

    assert seen == {"request_id": "req-1", "task_id": "sess-bg"}


# ── configure_logging ────────────────────────────────────────────────────────

def test_configure_logging_is_idempotent():
    configure_logging()
    configure_logging()
    root = logging.getLogger()
    installed = [h for h in root.handlers if h.get_name() == "llm-service-structured"]
    assert len(installed) == 1


def test_configure_logging_quiets_the_known_chatty_loggers():
    """MAF's per-superstep runner lines and httpx's per-call lines swamp the service's own."""
    configure_logging()
    for noisy in ("httpx", "agent_framework._workflows"):
        assert logging.getLogger(noisy).level == logging.WARNING


def test_log_level_is_honoured(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "warning")
    configure_logging()
    assert logging.getLogger().level == logging.WARNING


# ── The HTTP middleware, over real HTTP ──────────────────────────────────────

@pytest.fixture
def http_server():
    with run_app(create_app()) as base_url:
        yield base_url


def test_an_inbound_request_id_is_reused_not_replaced(http_server):
    """One id across both services. If this regresses, a Java-side trace and the LLM-side
    trace can only be joined by timestamp — which is not a join."""
    with httpx.Client(timeout=20) as client:
        resp = client.get(f"{http_server}/health", headers={"X-Request-ID": "java-trace-1"})
    assert resp.headers["X-Request-ID"] == "java-trace-1"


def test_a_request_without_one_still_gets_an_id(http_server):
    with httpx.Client(timeout=20) as client:
        first = client.get(f"{http_server}/health").headers["X-Request-ID"]
        second = client.get(f"{http_server}/health").headers["X-Request-ID"]
    assert first and second and first != second


def test_the_id_is_echoed_on_errors_too(http_server):
    """The failing request is the one whose id someone will quote back to you."""
    with httpx.Client(timeout=20) as client:
        resp = client.get(f"{http_server}/tasks/does-not-exist",
                          headers={"X-Request-ID": "java-trace-404"})
    assert resp.status_code == 404
    assert resp.headers["X-Request-ID"] == "java-trace-404"


def test_a_run_logs_its_shape_and_carries_the_request_id(http_server, caplog):
    """The end-to-end claim: one POST, and the run's own log line is attributable to the
    caller's trace id AND to the task, without the route passing either down."""
    with caplog.at_level(logging.INFO, logger="LLM_service.api"):
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{http_server}/tasks",
                headers={"X-Request-ID": "java-trace-run"},
                json={"topic": "ethiopia harvest", "target_platforms": ["linkedin"],
                      "business_id": "biz-log", "content_types": ["text"]},
            )
    task_id = resp.json()["task_id"]

    started = [r for r in caplog.records if r.getMessage() == "run_started"]
    assert len(started) == 1
    assert started[0].request_id == "java-trace-run"
    assert started[0].task_id == task_id
    assert started[0].platforms == ["linkedin"]
    assert started[0].content_types == ["text"]


def test_health_checks_do_not_flood_the_log_at_info(http_server, caplog):
    """A probe every few seconds forever would otherwise BE the log."""
    with caplog.at_level(logging.INFO, logger="LLM_service.api"):
        with httpx.Client(timeout=20) as client:
            client.get(f"{http_server}/health")
    assert not [r for r in caplog.records
                if r.getMessage() == "http_request" and getattr(r, "path", "") == "/health"]
