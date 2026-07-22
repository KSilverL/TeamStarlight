"""
Remotion Lambda render backend:
workflow/video/render.py's local-vs-lambda dispatch, and
workflow/video/lambda_render.py's orchestration (stable vs. ephemeral site
selection, strict-JSON stdout parsing, error handling).

The actual `node scripts/lambda-*.mjs` calls are faked via a monkeypatched
`_run_node_script` seam (mirrors codegen.py's `_run_typecheck`/`_run_preview_render`
convention) — fully offline, no AWS credentials or real Node/AWS calls needed. This
mirrors SoundrawMusic's "unverified against a live account" caveat: the Node
scripts' call shapes are confirmed against the installed @remotion/lambda[-client]
package's own TypeScript declarations, but a live AWS render hasn't been exercised.
"""

from __future__ import annotations

import pytest

from LLM_service.core.config import Settings
from LLM_service.core.video_schema import RenderableStoryboard, RenderGeneratedSlide, RenderHookSlide
from LLM_service.workflow.video import lambda_render, render
from LLM_service.workflow.video.render import RenderError


def _lambda_settings(**overrides) -> Settings:
    defaults = dict(
        video_render_backend="lambda",
        aws_region="us-east-1",
        remotion_lambda_function_name="remotion-render-fn",
        remotion_lambda_serve_url="https://example.cloudfront.net/sites/stable/index.html",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _no_generated_storyboard() -> RenderableStoryboard:
    return RenderableStoryboard(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        width=1080, height=1920,
        slides=[RenderHookSlide(headline="Hi", durationFrames=90)],
    )


def _generated_storyboard() -> RenderableStoryboard:
    return RenderableStoryboard(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        width=1080, height=1920,
        slides=[RenderGeneratedSlide(componentName="Generated_job1_0", data={}, durationFrames=100)],
    )


# ── render.py: local vs lambda dispatch ───────────────────────────────────────

async def test_render_storyboard_dispatches_to_local_by_default(tmp_path, monkeypatch):
    called = {}

    async def fake_render_local(renderable, *, job_dir, settings, entry_point, composition_id, timeout_s):
        called["args"] = (entry_point, composition_id)
        return job_dir / "output.mp4"

    monkeypatch.setattr(render, "_render_local", fake_render_local)
    settings = Settings()  # default: video_render_backend == "local"
    result = await render.render_storyboard(_no_generated_storyboard(), job_dir=tmp_path, settings=settings)
    assert result == tmp_path / "output.mp4"
    assert called["args"] == ("src/index.tsx", "StoryboardVideo")


async def test_render_storyboard_dispatches_to_lambda_when_configured(tmp_path, monkeypatch):
    called = {}

    async def fake_render_on_lambda(renderable, *, job_id, entry_point, composition_id, props_path, settings, timeout_s):
        called["job_id"] = job_id
        return "https://bucket.s3.amazonaws.com/output.mp4"

    monkeypatch.setattr(lambda_render, "render_on_lambda", fake_render_on_lambda)
    settings = _lambda_settings()
    result = await render.render_storyboard(_no_generated_storyboard(), job_dir=tmp_path, settings=settings)
    assert result == "https://bucket.s3.amazonaws.com/output.mp4"
    assert called["job_id"] == tmp_path.name
    assert (tmp_path / "props.json").is_file()  # props.json is written either way


# ── lambda_render._run_node_script: strict-JSON parsing / error handling ─────

async def _fake_subprocess(returncode: int, stdout: bytes, stderr: bytes = b""):
    class _Proc:
        async def communicate(self):
            return stdout, stderr
        def kill(self):
            pass
        async def wait(self):
            pass
    _Proc.returncode = returncode
    return _Proc()


async def test_run_node_script_parses_last_json_line(monkeypatch):
    async def fake_exec(*args, **kwargs):
        return await _fake_subprocess(0, b'some log line\n{"status": "done", "url": "https://x"}\n')

    monkeypatch.setattr(lambda_render.asyncio, "create_subprocess_exec", fake_exec)
    result = await lambda_render._run_node_script(
        Settings(), "scripts/fake.mjs", [], timeout_s=5.0,
    )
    assert result == {"status": "done", "url": "https://x"}


async def test_run_node_script_raises_on_error_status(monkeypatch):
    async def fake_exec(*args, **kwargs):
        return await _fake_subprocess(1, b'{"status": "error", "message": "no credentials"}\n')

    monkeypatch.setattr(lambda_render.asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(RenderError, match="no credentials"):
        await lambda_render._run_node_script(Settings(), "scripts/fake.mjs", [], timeout_s=5.0)


async def test_run_node_script_raises_on_unparsable_output(monkeypatch):
    async def fake_exec(*args, **kwargs):
        return await _fake_subprocess(0, b"not json at all\n")

    monkeypatch.setattr(lambda_render.asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(RenderError, match="did not print valid JSON"):
        await lambda_render._run_node_script(Settings(), "scripts/fake.mjs", [], timeout_s=5.0)


async def test_run_node_script_raises_on_no_output(monkeypatch):
    async def fake_exec(*args, **kwargs):
        return await _fake_subprocess(1, b"", b"stack trace here")

    monkeypatch.setattr(lambda_render.asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(RenderError, match="stack trace here"):
        await lambda_render._run_node_script(Settings(), "scripts/fake.mjs", [], timeout_s=5.0)


# ── lambda_render._serve_url_for: stable vs. ephemeral site selection ────────

async def test_serve_url_for_uses_stable_url_without_generated_slides():
    settings = _lambda_settings()
    url = await lambda_render._serve_url_for(
        _no_generated_storyboard(), job_id="job1", entry_point="src/index.tsx", settings=settings,
    )
    assert url == settings.remotion_lambda_serve_url


async def test_serve_url_for_raises_when_stable_url_unconfigured():
    settings = _lambda_settings(remotion_lambda_serve_url=None)
    with pytest.raises(RenderError, match="REMOTION_LAMBDA_SERVE_URL"):
        await lambda_render._serve_url_for(
            _no_generated_storyboard(), job_id="job1", entry_point="src/index.tsx", settings=settings,
        )


async def test_serve_url_for_deploys_ephemeral_site_with_generated_slides(monkeypatch):
    captured = {}

    async def fake_run_node_script(settings, script, args, *, timeout_s):
        captured["script"] = script
        captured["args"] = args
        return {"status": "done", "serveUrl": "https://ephemeral.cloudfront.net/index.html"}

    monkeypatch.setattr(lambda_render, "_run_node_script", fake_run_node_script)
    settings = _lambda_settings()
    url = await lambda_render._serve_url_for(
        _generated_storyboard(), job_id="job1", entry_point="src/generated/job1/entry.tsx", settings=settings,
    )
    assert url == "https://ephemeral.cloudfront.net/index.html"
    assert captured["script"] == lambda_render._DEPLOY_SCRIPT
    assert "src/generated/job1/entry.tsx" in captured["args"]
    assert "storyboard-job-job1" in captured["args"]


# ── lambda_render.render_on_lambda: end-to-end orchestration ──────────────────

async def test_render_on_lambda_returns_output_url(tmp_path, monkeypatch):
    async def fake_run_node_script(settings, script, args, *, timeout_s):
        assert script == lambda_render._RENDER_SCRIPT
        return {"status": "done", "url": "https://bucket.s3.amazonaws.com/renders/out.mp4"}

    monkeypatch.setattr(lambda_render, "_run_node_script", fake_run_node_script)
    settings = _lambda_settings()
    props_path = tmp_path / "props.json"
    props_path.write_text("{}")

    url = await lambda_render.render_on_lambda(
        _no_generated_storyboard(), job_id="job1", entry_point="src/index.tsx",
        composition_id="StoryboardVideo", props_path=props_path, settings=settings, timeout_s=30.0,
    )
    assert url == "https://bucket.s3.amazonaws.com/renders/out.mp4"


async def test_render_on_lambda_requires_function_name(tmp_path):
    settings = _lambda_settings(remotion_lambda_function_name=None)
    with pytest.raises(RenderError, match="REMOTION_LAMBDA_FUNCTION_NAME"):
        await lambda_render.render_on_lambda(
            _no_generated_storyboard(), job_id="job1", entry_point="src/index.tsx",
            composition_id="StoryboardVideo", props_path=tmp_path / "props.json",
            settings=settings, timeout_s=30.0,
        )


async def test_render_on_lambda_requires_region(tmp_path):
    settings = _lambda_settings(aws_region=None)
    with pytest.raises(RenderError, match="AWS_REGION"):
        await lambda_render.render_on_lambda(
            _no_generated_storyboard(), job_id="job1", entry_point="src/index.tsx",
            composition_id="StoryboardVideo", props_path=tmp_path / "props.json",
            settings=settings, timeout_s=30.0,
        )
