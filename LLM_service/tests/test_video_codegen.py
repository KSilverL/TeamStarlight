"""
Bespoke Remotion scene codegen (Phase 1 of the autonomous video-agent plan):
workflow/video/codegen.py's self-repair loop (generate -> typecheck -> preview-render
-> retry-on-error -> fallback), MockLLM.generate_scene_component's deterministic
BROKEN_CODEGEN_MARKER lever, and assets.py's integration (a `generated` slide
resolves to a RenderGeneratedSlide, or falls back to a static template slide on
exhaustion).

The typecheck/preview-render subprocess calls are faked via monkeypatched
module-level seams (mirrors the `_complete`/`_run_agent` convention elsewhere) —
fully offline, no real Node/tsc/Remotion invocation needed.
"""

from __future__ import annotations

import json
import logging
import os
import time

import pytest

from LLM_service.core.config import Settings
from LLM_service.core.services.mock import (
    BROKEN_CODEGEN_MARKER,
    SUBJECT_MISMATCH_MARKER,
    VISUAL_QA_REJECT_MARKER,
    MockLLM,
)
from LLM_service.core.video_schema import (
    GeneratedSlideSpec,
    RenderableStoryboard,
    RenderGeneratedSlide,
    RenderHookSlide,
    RenderOutroSlide,
    StoryboardSpec,
)
from LLM_service.workflow.video import codegen
from LLM_service.workflow.video.assets import resolve_storyboard_assets


async def _ok_typecheck(settings, **kw):
    return True, ""


async def _ok_preview(settings, **kw):
    # generate_scene() reads output_path's bytes for the visual-QA pass on success,
    # so a fake standing in for a real `remotion still` call must actually produce
    # a (dummy) file there — MockLLM.review_scene_preview doesn't inspect the bytes.
    kw["output_path"].write_bytes(b"fake-png-bytes")
    return True, ""


@pytest.fixture
def scratch_settings(tmp_path):
    """A Settings whose video_renderer_dir points at an empty tmp_path, so
    codegen.py's file-writing has somewhere real to write without touching the
    actual video_renderer/ project. Built directly (not via get_settings()/env),
    so no global state leaks between tests."""
    (tmp_path / "src").mkdir()
    return Settings(video_renderer_dir=str(tmp_path))


# ── MockLLM.generate_scene_component ──────────────────────────────────────────

async def test_mock_generate_scene_component_is_valid_by_default():
    source = await MockLLM().generate_scene_component(
        description="A calm intro card", data={"headline": "Hello"},
        width=1080, height=1920, fps=30, duration_frames=90,
    )
    assert "export default GeneratedScene" in source
    assert "undefinedIdentifierBoom" not in source
    assert "accentColor" in source and "primaryColor" in source  # matches the shared slide prop shape


async def test_mock_generate_scene_component_is_broken_on_first_attempt_with_marker():
    kw = dict(description=f"intro card ({BROKEN_CODEGEN_MARKER})", data={}, width=1080,
              height=1920, fps=30, duration_frames=90)
    first = await MockLLM().generate_scene_component(**kw, attempt=1)
    assert "undefinedIdentifierBoom" in first

    fixed = await MockLLM().generate_scene_component(
        **kw, attempt=2, prior_error="ReferenceError: undefinedIdentifierBoom is not defined",
        prior_source=first,
    )
    assert "undefinedIdentifierBoom" not in fixed


async def test_mock_generate_scene_component_ignores_marker_without_the_substring():
    source = await MockLLM().generate_scene_component(
        description="a totally normal scene", data={}, width=1080, height=1920,
        fps=30, duration_frames=90, attempt=1,
    )
    assert "undefinedIdentifierBoom" not in source


# ── MockLLM.review_scene_preview ───────────────────────────────────────────────

async def test_mock_review_scene_preview_approves_by_default():
    review = await MockLLM().review_scene_preview(description="a calm intro card", image_bytes=b"png")
    assert review == {"approved": True, "feedback": "", "fixes": []}


async def test_mock_review_scene_preview_rejects_on_first_attempt_with_marker():
    kw = dict(description=f"intro card ({VISUAL_QA_REJECT_MARKER})", image_bytes=b"png")
    first = await MockLLM().review_scene_preview(**kw, attempt=1)
    assert first["approved"] is False
    assert first["feedback"]

    second = await MockLLM().review_scene_preview(**kw, attempt=2)
    assert second["approved"] is True


async def test_mock_review_scene_preview_rejects_subject_mismatch_on_first_attempt():
    """The strengthened QA rubric's offline lever: a frame that doesn't DEPICT the
    brief's subject (e.g. a text card standing in for a requested map) is rejected
    with subject-specific feedback, then approved on the retry like the other marker."""
    kw = dict(description=f"a map of Ireland ({SUBJECT_MISMATCH_MARKER})", image_bytes=b"png")
    first = await MockLLM().review_scene_preview(**kw, attempt=1)
    assert first["approved"] is False
    assert "does not depict" in first["feedback"]

    second = await MockLLM().review_scene_preview(**kw, attempt=2)
    assert second["approved"] is True


# ── codegen.generate_scene: the self-repair loop ──────────────────────────────

async def test_generate_scene_succeeds_on_first_attempt(scratch_settings, monkeypatch):
    monkeypatch.setattr(codegen, "_run_typecheck", _ok_typecheck)
    monkeypatch.setattr(codegen, "_run_preview_render", _ok_preview)

    spec = GeneratedSlideSpec(description="A calm intro card", data={"headline": "Hi"})
    result = await codegen.generate_scene(
        job_id="job1", slide_index=0, spec=spec, width=1080, height=1920, fps=30,
        settings=scratch_settings,
    )
    assert isinstance(result, RenderGeneratedSlide)
    assert result.componentName == "Generated_job1_0"
    assert result.data == {"headline": "Hi"}
    written = scratch_settings.resolved_video_renderer_dir / "src" / "generated" / "job1" / "Generated_job1_0.tsx"
    assert written.is_file()


async def test_generate_scene_recovers_after_typecheck_failure(scratch_settings, monkeypatch):
    """A first-attempt typecheck failure feeds the exact error back; the SECOND
    attempt (armed by BROKEN_CODEGEN_MARKER + a real prior_error) succeeds."""
    attempts = {"n": 0}

    async def flaky_typecheck(settings, **kw):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return False, "TS2304: Cannot find name 'undefinedIdentifierBoom'."
        return True, ""

    monkeypatch.setattr(codegen, "_run_typecheck", flaky_typecheck)
    monkeypatch.setattr(codegen, "_run_preview_render", _ok_preview)

    spec = GeneratedSlideSpec(description=f"intro card ({BROKEN_CODEGEN_MARKER})", data={})
    result = await codegen.generate_scene(
        job_id="job2", slide_index=0, spec=spec, width=1080, height=1920, fps=30,
        settings=scratch_settings, max_attempts=3,
    )
    assert isinstance(result, RenderGeneratedSlide)
    assert attempts["n"] == 2


async def test_generate_scene_recovers_after_preview_render_failure(scratch_settings, monkeypatch):
    attempts = {"n": 0}

    async def flaky_preview(settings, **kw):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return False, "Error: Component threw during render"
        kw["output_path"].write_bytes(b"fake-png-bytes")
        return True, ""

    monkeypatch.setattr(codegen, "_run_typecheck", _ok_typecheck)
    monkeypatch.setattr(codegen, "_run_preview_render", flaky_preview)

    spec = GeneratedSlideSpec(description="whatever", data={})
    result = await codegen.generate_scene(
        job_id="job2b", slide_index=0, spec=spec, width=1080, height=1920, fps=30,
        settings=scratch_settings, max_attempts=3,
    )
    assert isinstance(result, RenderGeneratedSlide)
    assert attempts["n"] == 2


async def test_generate_scene_returns_none_once_attempts_exhausted(scratch_settings, monkeypatch):
    async def always_fails(settings, **kw):
        return False, "boom"

    monkeypatch.setattr(codegen, "_run_typecheck", always_fails)
    monkeypatch.setattr(codegen, "_run_preview_render", _ok_preview)

    spec = GeneratedSlideSpec(description="whatever", data={})
    result = await codegen.generate_scene(
        job_id="job3", slide_index=0, spec=spec, width=1080, height=1920, fps=30,
        settings=scratch_settings, max_attempts=2,
    )
    assert result is None


async def test_generate_scene_recovers_after_visual_qa_rejection(scratch_settings, monkeypatch):
    """A candidate that compiles and renders fine can still be rejected by the
    visual-QA pass; the loop retries with that feedback as the next attempt's
    prior_error, same as a compile/render failure."""
    monkeypatch.setattr(codegen, "_run_typecheck", _ok_typecheck)
    monkeypatch.setattr(codegen, "_run_preview_render", _ok_preview)

    spec = GeneratedSlideSpec(description=f"intro card ({VISUAL_QA_REJECT_MARKER})", data={})
    result = await codegen.generate_scene(
        job_id="job4", slide_index=0, spec=spec, width=1080, height=1920, fps=30,
        settings=scratch_settings, max_attempts=3,
    )
    assert isinstance(result, RenderGeneratedSlide)


async def test_generate_scene_recovers_after_subject_mismatch_rejection(scratch_settings, monkeypatch):
    """Same retry path as the legibility rejection above, but through the
    strengthened doesn't-depict-the-subject criterion."""
    monkeypatch.setattr(codegen, "_run_typecheck", _ok_typecheck)
    monkeypatch.setattr(codegen, "_run_preview_render", _ok_preview)

    spec = GeneratedSlideSpec(description=f"a map of Ireland ({SUBJECT_MISMATCH_MARKER})", data={})
    result = await codegen.generate_scene(
        job_id="job4b", slide_index=0, spec=spec, width=1080, height=1920, fps=30,
        settings=scratch_settings, max_attempts=3,
    )
    assert isinstance(result, RenderGeneratedSlide)


async def test_generate_scene_returns_none_when_visual_qa_never_approves(scratch_settings, monkeypatch):
    monkeypatch.setattr(codegen, "_run_typecheck", _ok_typecheck)
    monkeypatch.setattr(codegen, "_run_preview_render", _ok_preview)

    class _AlwaysRejectLLM:
        async def plan_scene_design(self, **kw):
            return "- a plan"

        async def generate_scene_component(self, **kw):
            return "export default function X() { return null; }"

        async def review_scene_preview(self, **kw):
            return {"approved": False, "feedback": "still wrong", "fixes": ["do better"]}

    monkeypatch.setattr(codegen.factory, "get_llm", lambda: _AlwaysRejectLLM())
    spec = GeneratedSlideSpec(description="whatever", data={})
    result = await codegen.generate_scene(
        job_id="job5", slide_index=0, spec=spec, width=1080, height=1920, fps=30,
        settings=scratch_settings, max_attempts=2,
    )
    assert result is None


async def test_generate_scene_runs_two_stage_and_threads_plan_and_fixes(scratch_settings, monkeypatch):
    """Phase 5: plan_scene_design runs once up front; its plan is passed as
    design_plan to every generate call; and a QA rejection's `fixes` are folded
    into the next attempt's prior_error."""
    monkeypatch.setattr(codegen, "_run_typecheck", _ok_typecheck)
    monkeypatch.setattr(codegen, "_run_preview_render", _ok_preview)
    calls = {"plan": 0, "design_plans": [], "prior_errors": []}

    class _TwoStageLLM:
        async def plan_scene_design(self, *, description, data):
            calls["plan"] += 1
            return "- centre the hero\n- stagger the rest"

        async def generate_scene_component(self, *, design_plan=None, prior_error=None, **kw):
            calls["design_plans"].append(design_plan)
            calls["prior_errors"].append(prior_error)
            return "export default function X() { return null; }"

        async def review_scene_preview(self, *, attempt=1, **kw):
            if attempt == 1:
                return {"approved": False, "feedback": "too plain", "fixes": ["add a chart", "increase contrast"]}
            return {"approved": True, "feedback": "", "fixes": []}

    monkeypatch.setattr(codegen.factory, "get_llm", lambda: _TwoStageLLM())
    spec = GeneratedSlideSpec(description="something bespoke", data={})
    result = await codegen.generate_scene(
        job_id="job7", slide_index=0, spec=spec, width=1080, height=1920, fps=30,
        settings=scratch_settings, max_attempts=3,
    )
    assert isinstance(result, RenderGeneratedSlide)
    assert calls["plan"] == 1  # planned exactly once, not per attempt
    assert all(dp == "- centre the hero\n- stagger the rest" for dp in calls["design_plans"])
    # Attempt 2's prior_error carries the QA feedback AND the concrete fixes.
    assert "too plain" in calls["prior_errors"][1]
    assert "add a chart" in calls["prior_errors"][1] and "increase contrast" in calls["prior_errors"][1]


async def test_generate_scene_logs_each_attempt(scratch_settings, monkeypatch, caplog):
    monkeypatch.setattr(codegen, "_run_typecheck", _ok_typecheck)
    monkeypatch.setattr(codegen, "_run_preview_render", _ok_preview)

    spec = GeneratedSlideSpec(description="a calm intro card", data={})
    with caplog.at_level(logging.INFO, logger="LLM_service.workflow.video.codegen"):
        await codegen.generate_scene(
            job_id="job6", slide_index=0, spec=spec, width=1080, height=1920, fps=30,
            settings=scratch_settings,
        )
    assert any("codegen attempt succeeded" in r.message for r in caplog.records)
    success_record = next(r for r in caplog.records if "succeeded" in r.message)
    assert success_record.job_id == "job6" and success_record.slide_index == 0


# ── CodegenBudget: cross-slide attempt budget ─────────────────────────────────

def test_codegen_budget_take_exhausts_after_total():
    budget = codegen.CodegenBudget(total_attempts=2)
    assert budget.take() is True
    assert budget.take() is True
    assert budget.take() is False
    assert budget.take() is False  # stays exhausted


async def test_generate_scene_respects_a_shared_budget_across_calls(scratch_settings, monkeypatch):
    """A budget shared across two generate_scene() calls (simulating two slides in
    one storyboard) is consumed cumulatively — the second slide can be starved by
    the first's attempts, exactly like a per-slide budget starves a single slide."""
    monkeypatch.setattr(codegen, "_run_typecheck", _ok_typecheck)
    monkeypatch.setattr(codegen, "_run_preview_render", _ok_preview)
    budget = codegen.CodegenBudget(total_attempts=1)

    spec = GeneratedSlideSpec(description="fine", data={})
    first = await codegen.generate_scene(
        job_id="jobB", slide_index=0, spec=spec, width=1080, height=1920, fps=30,
        settings=scratch_settings, max_attempts=3, budget=budget,
    )
    assert isinstance(first, RenderGeneratedSlide)  # consumed the only unit, succeeded immediately
    assert budget.remaining == 0

    second = await codegen.generate_scene(
        job_id="jobB", slide_index=1, spec=spec, width=1080, height=1920, fps=30,
        settings=scratch_settings, max_attempts=3, budget=budget,
    )
    assert second is None  # no budget left, falls back without even trying


async def test_generate_scene_names_components_uniquely_per_slide(scratch_settings, monkeypatch):
    monkeypatch.setattr(codegen, "_run_typecheck", _ok_typecheck)
    monkeypatch.setattr(codegen, "_run_preview_render", _ok_preview)
    spec = GeneratedSlideSpec(description="x", data={})

    a = await codegen.generate_scene(job_id="jobA", slide_index=0, spec=spec,
                                      width=1080, height=1920, fps=30, settings=scratch_settings)
    b = await codegen.generate_scene(job_id="jobA", slide_index=3, spec=spec,
                                      width=1080, height=1920, fps=30, settings=scratch_settings)
    assert a.componentName != b.componentName


# ── codegen.ensure_job_entry_point (Phase 2 fix: the FULL render, not just the
# preview, needs a per-job entry point when `generated` slides are present) ──────

def test_ensure_job_entry_point_returns_none_without_generated_slides(scratch_settings):
    renderable = RenderableStoryboard(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        width=1080, height=1920,
        slides=[RenderHookSlide(headline="Hi", durationFrames=90),
                RenderOutroSlide(brandName="X", ctaLabel="Go", durationFrames=90)],
    )
    assert codegen.ensure_job_entry_point(scratch_settings, "job9", renderable) is None


def test_ensure_job_entry_point_writes_imports_and_registrations(scratch_settings):
    renderable = RenderableStoryboard(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        width=1080, height=1920,
        slides=[
            RenderHookSlide(headline="Hi", durationFrames=90),
            RenderGeneratedSlide(componentName="Generated_job9_1", data={}, durationFrames=100),
            RenderGeneratedSlide(componentName="Generated_job9_2", data={}, durationFrames=100),
        ],
    )
    result = codegen.ensure_job_entry_point(scratch_settings, "job9", renderable)
    assert result is not None
    entry_relpath, composition_id = result
    assert composition_id == "StoryboardVideo"
    assert entry_relpath == "src/generated/job9/entry.tsx"

    source = (scratch_settings.resolved_video_renderer_dir / entry_relpath).read_text()
    assert 'import Generated_job9_1 from "./Generated_job9_1";' in source
    assert 'import Generated_job9_2 from "./Generated_job9_2";' in source
    assert 'registerGeneratedSlide("Generated_job9_1", Generated_job9_1);' in source
    assert 'registerGeneratedSlide("Generated_job9_2", Generated_job9_2);' in source
    assert "registerRoot(Root)" in source


async def test_ensure_job_entry_point_typechecks_for_real_against_real_project():
    """Unlike the other codegen tests (which point video_renderer_dir at an empty
    tmp_path), this one targets the REAL video_renderer/ project so a real `tsc
    --noEmit` can confirm the generated entry point + a real generated component
    actually type-check together — the same validation approach used to manually
    verify Phase 1 end-to-end. Skipped if the real project's node_modules isn't
    installed (CI/dev boxes that haven't run `npm install` in video_renderer/)."""
    real_settings = Settings()  # default: repo-root sibling video_renderer/
    renderer_dir = real_settings.resolved_video_renderer_dir
    if not (renderer_dir / "node_modules" / "@remotion" / "cli").is_dir():
        pytest.skip("video_renderer/node_modules is not installed")

    job_id = "test_entry_point_typecheck"
    scene = await MockLLM().generate_scene_component(
        description="a calm intro card", data={"headline": "Hi"},
        width=1080, height=1920, fps=30, duration_frames=90,
    )
    codegen._write_component(real_settings, job_id, "Generated_test_0", scene)
    renderable = RenderableStoryboard(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        width=1080, height=1920,
        slides=[RenderGeneratedSlide(componentName="Generated_test_0", data={"headline": "Hi"}, durationFrames=90)],
    )
    # A deliberately broken sibling job left behind (crash, kill -9) must NOT fail
    # this job's typecheck — the job-scoped tsconfig excludes it structurally. This
    # is the root-cause regression test: the old whole-project `tsc --noEmit` made
    # one stale broken file poison every subsequent job's codegen into fallback.
    broken_sibling_job = "test_entry_point_broken_sibling"
    codegen._write_component(
        real_settings, broken_sibling_job, "Generated_broken_0",
        "export default not even TypeScript {{{",
    )
    try:
        result = codegen.ensure_job_entry_point(real_settings, job_id, renderable)
        assert result is not None
        ok, err = await codegen._run_typecheck(real_settings, job_id=job_id)
        assert ok, err
    finally:
        codegen.cleanup_job_generated(real_settings, job_id)
        codegen.cleanup_job_generated(real_settings, broken_sibling_job)


# ── assets.py integration ──────────────────────────────────────────────────────

async def test_resolve_storyboard_assets_handles_generated_slide_success(tmp_path, monkeypatch):
    async def fake_generate_scene(**kw):
        spec = kw["spec"]
        return RenderGeneratedSlide(componentName="Generated_x_1", data=spec.data, durationFrames=100)

    monkeypatch.setattr(codegen, "generate_scene", fake_generate_scene)

    storyboard = StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="linkedin",
        slides=[
            {"type": "hook", "headline": "Intro"},
            {"type": "generated", "description": "bespoke thing", "data": {"headline": "Wow"}},
        ],
    )
    renderable = await resolve_storyboard_assets(storyboard, job_dir=tmp_path)
    generated = renderable.slides[1]
    assert generated.type == "generated"
    assert generated.componentName == "Generated_x_1"
    assert generated.durationFrames == 100
    assert generated.data == {"headline": "Wow"}


async def test_resolve_storyboard_assets_falls_back_when_codegen_exhausted(tmp_path, monkeypatch):
    async def fake_generate_scene(**kw):
        return None  # simulates attempt-budget exhaustion

    monkeypatch.setattr(codegen, "generate_scene", fake_generate_scene)

    storyboard = StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="linkedin",
        slides=[
            {"type": "generated", "description": "A neon skyline sweep", "data": {}},
            {"type": "outro", "brandName": "X", "ctaLabel": "Go"},
        ],
    )
    renderable = await resolve_storyboard_assets(storyboard, job_dir=tmp_path)
    fallback = renderable.slides[0]
    assert fallback.type == "hook"  # degraded to the always-available static template
    assert fallback.headline == "A neon skyline sweep"


async def test_resolve_storyboard_assets_scales_budget_with_generated_slide_count(tmp_path, monkeypatch):
    """The env-configured total is a FLOOR: 3 generated slides get max(9, 4*3)=12
    shared attempts, so a multi-bespoke storyboard can't starve its later slides."""
    seen = {}

    async def fake_generate_scene(**kw):
        seen.setdefault("budget", kw["budget"])
        spec = kw["spec"]
        return RenderGeneratedSlide(componentName="G", data=spec.data, durationFrames=100)

    monkeypatch.setattr(codegen, "generate_scene", fake_generate_scene)

    storyboard = StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="linkedin",
        slides=[
            {"type": "generated", "description": "one", "data": {}},
            {"type": "generated", "description": "two", "data": {}},
            {"type": "generated", "description": "three", "data": {}},
            {"type": "outro", "brandName": "X", "ctaLabel": "Go"},
        ],
    )
    settings = Settings(video_renderer_dir=str(tmp_path), codegen_max_total_attempts=9)
    await resolve_storyboard_assets(storyboard, job_dir=tmp_path, settings=settings)
    assert seen["budget"].remaining == 12  # the fake never take()s, so this is the initial total


async def test_resolve_storyboard_assets_never_calls_codegen_for_fixed_slides(tmp_path, monkeypatch):
    def boom(**kw):
        raise AssertionError("codegen.generate_scene must not be called for fixed slide types")

    monkeypatch.setattr(codegen, "generate_scene", boom)

    storyboard = StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="linkedin",
        slides=[{"type": "hook", "headline": "Intro"}, {"type": "outro", "brandName": "X", "ctaLabel": "Go"}],
    )
    renderable = await resolve_storyboard_assets(storyboard, job_dir=tmp_path)
    assert [s.type for s in renderable.slides] == ["hook", "outro"]


# ── typecheck isolation + cleanup (the fallback-cascade root-cause fixes) ───────

def test_write_job_tsconfig_scopes_to_this_job_only(scratch_settings):
    """The per-job tsconfig includes the job's own files + enumerated shared src/
    dirs — never a `src/generated/**` (or any other) pattern a sibling job's files
    could match."""
    path = codegen._write_job_tsconfig(scratch_settings, "jobT")
    assert path == scratch_settings.resolved_video_renderer_dir / "src" / "generated" / "jobT" / "tsconfig.json"
    config = json.loads(path.read_text())
    assert config["extends"] == "../../../tsconfig.json"
    assert "./**/*.tsx" in config["include"]
    assert "../../*.ts" in config["include"] and "../../*.tsx" in config["include"]
    assert "../../slides/**/*" in config["include"]
    # no include pattern can reach back into src/generated/ (where siblings live)
    assert not any("generated" in pattern for pattern in config["include"])


def test_cleanup_job_generated_removes_the_job_dir(scratch_settings):
    codegen._write_component(scratch_settings, "jobC", "Generated_jobC_0", "export default 1;")
    job_dir = codegen._generated_dir(scratch_settings, "jobC")
    assert job_dir.is_dir()
    codegen.cleanup_job_generated(scratch_settings, "jobC")
    assert not job_dir.exists()
    codegen.cleanup_job_generated(scratch_settings, "jobC")  # idempotent on a missing dir


def test_sweep_stale_generated_reaps_only_old_dirs(scratch_settings):
    codegen._write_component(scratch_settings, "job_old", "Generated_old_0", "x")
    codegen._write_component(scratch_settings, "job_new", "Generated_new_0", "x")
    old_dir = codegen._generated_dir(scratch_settings, "job_old")
    two_days_ago = time.time() - 48 * 3600
    os.utime(old_dir, (two_days_ago, two_days_ago))

    removed = codegen.sweep_stale_generated(scratch_settings, max_age_hours=24)
    assert removed == 1
    assert not old_dir.exists()
    assert codegen._generated_dir(scratch_settings, "job_new").is_dir()


def test_sweep_stale_generated_tolerates_missing_root(tmp_path):
    # No src/generated/ at all (fresh checkout / scratch project): a no-op, not an error.
    (tmp_path / "src").mkdir()
    assert codegen.sweep_stale_generated(Settings(video_renderer_dir=str(tmp_path))) == 0


async def test_generate_scene_removes_its_files_after_exhaustion(scratch_settings, monkeypatch):
    """A permanently failed slide must not leave its broken .tsx behind, or a LATER
    `generated` slide in the SAME job would inherit it into its job-scoped typecheck."""
    async def always_fails(settings, **kw):
        return False, "TS2304: Cannot find name 'boom'."

    monkeypatch.setattr(codegen, "_run_typecheck", always_fails)
    monkeypatch.setattr(codegen, "_run_preview_render", _ok_preview)

    spec = GeneratedSlideSpec(description="whatever", data={})
    result = await codegen.generate_scene(
        job_id="jobX", slide_index=0, spec=spec, width=1080, height=1920, fps=30,
        settings=scratch_settings, max_attempts=2,
    )
    assert result is None
    assert not codegen._component_path(scratch_settings, "jobX", "Generated_jobX_0").exists()


# ── _repair_hint: error-category-specific retry guidance ────────────────────────

def test_repair_hint_matches_error_categories():
    assert "type error" in codegen._repair_hint("src/generated/j/G.tsx(4,5): error TS2304: Cannot find name 'x'.")
    assert "monotonically increasing" in codegen._repair_hint("inputRange must be strictly monotonically increasing")
    assert "unconditionally" in codegen._repair_hint("Error: Rendered more hooks than during the previous render.")
    assert "useCurrentFrame" in codegen._repair_hint("preview render timed out after 60s")
    assert codegen._repair_hint("some totally novel failure") is None


def test_with_repair_hint_appends_only_when_matched():
    hinted = codegen._with_repair_hint("error TS2749: 'Foo' refers to a value")
    assert hinted.startswith("error TS2749") and "Repair hint:" in hinted
    assert codegen._with_repair_hint("novel failure") == "novel failure"
