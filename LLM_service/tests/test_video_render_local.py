"""
The local Remotion render subprocess (workflow/video/render.py `_render_local`).

test_video_lambda.py fakes `_render_local` wholesale to test the backend dispatch,
so the actual `npx remotion render` invocation — the argv, the working directory,
the --public-dir mechanism that makes job-relative asset paths resolve, and every
failure mode (missing project, non-zero exit, silent success, timeout) — was only
ever exercised by really rendering an MP4. Here `asyncio.create_subprocess_exec` is
faked, so those paths run in milliseconds with no Node, no Chromium, no render.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from LLM_service.core.config import Settings
from LLM_service.core.video_schema import RenderableStoryboard, RenderHookSlide
from LLM_service.workflow.video import render
from LLM_service.workflow.video.render import RenderError


def _storyboard() -> RenderableStoryboard:
    return RenderableStoryboard(
        brandName="COFFEE", primaryColor="#0d0d1a", secondaryColor="#5b8def",
        accentColor="#f0a500", width=1080, height=1920,
        slides=[RenderHookSlide(headline="Ready to sip?", durationFrames=90)],
    )


class FakeProcess:
    """An asyncio subprocess stand-in: scripted exit code / stderr, optionally
    writing the output file the real renderer would produce (or hanging forever)."""

    def __init__(self, *, returncode: int = 0, stderr: bytes = b"", output: Path | None = None,
                 hang: bool = False) -> None:
        self.returncode = returncode
        self._stderr = stderr
        self._output = output
        self._hang = hang
        self.killed = False

    async def communicate(self):
        if self._hang:
            await asyncio.Event().wait()  # never resolves → the caller's timeout fires
        if self._output is not None:
            self._output.write_bytes(b"fake-mp4")
        return b"", self._stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode


@pytest.fixture
def spawn(monkeypatch):
    """Capture the argv/kwargs `_render_local` spawns and answer with a scripted process."""
    calls: list[tuple[tuple, dict]] = []
    state: dict = {"process": None}

    async def fake_exec(*argv, **kwargs):
        calls.append((argv, kwargs))
        proc = state["process"]
        if proc is None:  # default: succeed, writing the output path from the argv
            proc = FakeProcess(output=Path(argv[5]))
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return type("_Spawn", (), {"calls": calls, "state": state})()


def _settings(renderer_dir: Path, **over) -> Settings:
    base = dict(video_renderer_dir=str(renderer_dir))
    base.update(over)
    return Settings(**base)


async def test_local_render_invokes_remotion_with_the_job_public_dir(tmp_path, spawn):
    renderer_dir = tmp_path / "video_renderer"
    renderer_dir.mkdir()
    job_dir = tmp_path / "job-1"

    out = await render.render_storyboard(
        _storyboard(), job_dir=job_dir, settings=_settings(renderer_dir))

    assert out == job_dir / "output.mp4" and out.is_file()
    argv, kwargs = spawn.calls[0]
    assert argv[1:5] == ("remotion", "render", "src/index.tsx", "StoryboardVideo")
    assert argv[5] == str(job_dir / "output.mp4")
    assert argv[6] == f"--props={job_dir / 'props.json'}"
    # --public-dir is what makes the job-relative asset paths assets.py wrote (e.g.
    # "images/0.png") resolve through staticFile(); Chromium refuses file:// URLs.
    assert argv[7] == f"--public-dir={job_dir.resolve().as_posix()}"
    assert kwargs["cwd"] == str(renderer_dir)
    # props.json is written before the process starts.
    assert (job_dir / "props.json").is_file()
    assert "Ready to sip?" in (job_dir / "props.json").read_text(encoding="utf-8")


async def test_local_render_fails_loudly_when_the_node_project_is_missing(tmp_path, spawn):
    missing = tmp_path / "not-checked-out"
    with pytest.raises(RenderError, match="video_renderer project not found"):
        await render.render_storyboard(
            _storyboard(), job_dir=tmp_path / "job", settings=_settings(missing))
    assert spawn.calls == []  # nothing was spawned


async def test_local_render_surfaces_the_stderr_tail_on_a_failed_render(tmp_path, spawn):
    renderer_dir = tmp_path / "video_renderer"
    renderer_dir.mkdir()
    spawn.state["process"] = FakeProcess(
        returncode=1, stderr=b"x" * 5000 + b"TypeError: slide.data is undefined")

    with pytest.raises(RenderError) as excinfo:
        await render.render_storyboard(
            _storyboard(), job_dir=tmp_path / "job", settings=_settings(renderer_dir))

    message = str(excinfo.value)
    assert "exit 1" in message
    assert "TypeError: slide.data is undefined" in message
    assert len(message) < 2200  # only the tail, not a 5 KB wall of output


async def test_local_render_rejects_a_silent_success(tmp_path, spawn):
    """Exit 0 with no file on disk is a failure, not a job that quietly 'succeeded'."""
    renderer_dir = tmp_path / "video_renderer"
    renderer_dir.mkdir()
    spawn.state["process"] = FakeProcess(returncode=0, output=None)

    with pytest.raises(RenderError, match="produced no output file"):
        await render.render_storyboard(
            _storyboard(), job_dir=tmp_path / "job", settings=_settings(renderer_dir))


async def test_local_render_kills_the_process_on_timeout(tmp_path, spawn):
    renderer_dir = tmp_path / "video_renderer"
    renderer_dir.mkdir()
    hung = FakeProcess(hang=True)
    spawn.state["process"] = hung

    with pytest.raises(RenderError, match="timed out after 0s"):
        await render.render_storyboard(
            _storyboard(), job_dir=tmp_path / "job", settings=_settings(renderer_dir),
            timeout_s=0.01)

    assert hung.killed is True  # no orphaned Chromium left behind
