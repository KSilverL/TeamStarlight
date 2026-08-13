"""
Central runtime configuration and the Mock ↔ Production feature toggle.

A single `Settings` object is the source of truth for which implementation each
service uses. Resolution order for every service is:

    per-service env var (USE_MOCK_LLM / ...)  >  global USE_MOCK  >  default (True)

Default is mock so the system never accidentally hits paid/real APIs without an
explicit opt-in. One-click production: set `USE_MOCK=false`. Gradual rollout:
keep `USE_MOCK=true` and flip individual services with `USE_MOCK_LLM=false`, etc.

The toggle set tracks the service contracts in core/services/base.py
(LLM / Safety / Store / Voice, plus the render-pipeline asset services).

`get_settings()` is cached; tests call `reset_settings()` after monkeypatching env.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional, Union

_TRUE = {"1", "true", "yes", "on", "y", "t"}
_FALSE = {"0", "false", "no", "off", "n", "f"}

# Default .env location: next to .env.example, at the LLM_service/ package root
# (this file is core/config.py, so parent.parent is LLM_service/).
_DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# Set this to suppress the automatic .env read in get_settings(). The test suite
# sets it (at conftest import time, before anything can resolve settings) so a
# developer's local .env can never leak into an offline, deterministic run.
IGNORE_DOTENV_VAR = "LLM_SERVICE_IGNORE_DOTENV"


def _parse_env_value(raw: str) -> str:
    """Parse one .env value. Quoted values ('...' / "...") are taken verbatim;
    for unquoted values a trailing ` # inline comment` is stripped — but only a
    '#' introduced by whitespace, so a '#' inside a value (URL fragment, password)
    is preserved. A value that is nothing but whitespace + a comment becomes ""."""
    s = raw.strip()
    if not s:
        return ""
    if s[0] in ("'", '"'):
        end = s.find(s[0], 1)
        return s[1:end] if end != -1 else s[1:]
    out: list[str] = []
    prev_ws = True  # treat start as whitespace so a leading '#' is a pure comment
    for ch in s:
        if ch == "#" and prev_ws:
            break
        out.append(ch)
        prev_ws = ch.isspace()
    return "".join(out).strip()


def load_dotenv(path: Union[str, Path, None] = None, *, override: bool = False) -> bool:
    """Load KEY=VALUE pairs from a .env file into ``os.environ``.

    Dependency-free (no python-dotenv needed). Real environment variables win by
    default (``override=False``), so a value exported in the shell — or set by a
    caller — is never clobbered by the file. ``get_settings()`` calls this itself,
    so consumers do not have to; entry points may still call it explicitly (to
    report whether a file was found, say). It is not an import side-effect, so
    importing this module stays inert. Returns True if a file was found and read."""
    env_path = Path(path) if path is not None else _DEFAULT_ENV_FILE
    if not env_path.is_file():
        return False
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key:
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = _parse_env_value(value)
    return True


def _env_int(name: str, default: int) -> int:
    """Parse an int env var, falling back to `default` when unset or malformed."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    """Parse a float env var, falling back to `default` when unset or malformed."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_bool(name: str) -> Optional[bool]:
    """
    Parse a boolean env var. Returns None when the var is unset, blank, or
    unrecognised, so callers can fall back to a lower-priority default.
    """
    raw = os.getenv(name)
    if raw is None:
        return None
    val = raw.strip().lower()
    if val in _TRUE:
        return True
    if val in _FALSE:
        return False
    return None


@dataclass(frozen=True)
class Settings:
    # ── Feature toggle ─────────────────────────────────────────────────────────
    use_mock: bool = True                     # master switch (default: mock)
    use_mock_llm: Optional[bool] = None       # None → inherit `use_mock`
    use_mock_safety: Optional[bool] = None
    use_mock_store: Optional[bool] = None
    use_mock_voice: Optional[bool] = None
    use_mock_image_search: Optional[bool] = None
    # Stock-FOOTAGE search (Pexels Videos) for media_statement slides. Not the
    # same thing as use_mock_video_generation, which fakes AI clip SYNTHESIS.
    use_mock_video_search: Optional[bool] = None
    use_mock_background_removal: Optional[bool] = None
    use_mock_music_generation: Optional[bool] = None
    use_mock_web_search: Optional[bool] = None
    use_mock_voiceover: Optional[bool] = None
    use_mock_video_generation: Optional[bool] = None

    # ── Azure OpenAI / Foundry (chat + structured output + copywriting) ────────
    azure_openai_endpoint: Optional[str] = None
    azure_openai_api_key: Optional[str] = None
    azure_openai_api_version: str = "2024-02-01"
    azure_chat_deployment: str = "gpt-4o"

    # ── Azure AI Content Safety (reviewer) ─────────────────────────────────────
    azure_content_safety_endpoint: Optional[str] = None
    azure_content_safety_key: Optional[str] = None

    # ── PostgreSQL (brand profiles + user skills + workflow checkpoints) ───────
    # One database; brand_profiles + user_skills + workflow_checkpoints (and the
    # video_jobs/trends/posting_plans tables) each store whole documents in a
    # JSONB `doc` column.
    # DSN comes from DATABASE_URL (preferred, e.g. a Supabase connection string),
    # falling back to POSTGRES_DSN — see _load().
    postgres_dsn: Optional[str] = None     # postgresql://user:pass@host:5432/newsroom
    postgres_profiles_table: str = "brand_profiles"
    postgres_user_skills_table: str = "user_skills"
    postgres_checkpoints_table: str = "workflow_checkpoints"
    # libpq-style sslmode. Unset → let the DSN decide (Supabase works without it).
    # Azure Cosmos DB for PostgreSQL *requires* SSL, so set POSTGRES_SSLMODE=require
    # there. Honoured by PostgresStore._pool / PostgresCheckpointStorage._pool.
    postgres_sslmode: Optional[str] = None
    postgres_video_jobs_table: str = "video_jobs"
    postgres_trends_table: str = "trends"
    postgres_posting_plans_table: str = "posting_plans"

    # ── Voice Live API (voice intake) ──────────────────────────────────────────
    azure_voicelive_endpoint: Optional[str] = None
    azure_voicelive_model: str = "gpt-realtime"
    azure_voicelive_api_version: str = "2026-04-10"
    azure_voicelive_api_key: Optional[str] = None   # falls back to the OpenAI key (same resource)
    azure_voicelive_voice: str = "verse"            # Preset voice for the realtime speech-to-speech bridge,
                                                      # (must be one the deployment supports).

    # ── Roundtable (multi-persona discussion stage) ────────────────────────────
    # ROUNDTABLE_ENABLED gates the drop-in replacement of `strategist`; off → the
    # pipeline runs the plain linear graph. max_rounds is the per-table hard cap
    # that stops an infinite debate. The two model tiers (cheap personas / stronger
    # manager) are read in the production path; the mock path ignores them.
    roundtable_enabled: bool = False
    # Each persona turn is now a short, single-point contribution (see roundtable/personas.py),
    # so the table can afford MANY more short exchanges — the cap is raised accordingly. It is
    # still the per-table hard stop on the debate.
    roundtable_max_rounds: int = 12
    # Hard backstop on how long a single persona turn may be (None → no cap, rely on the prompt).
    # Keeps turns short like a real discussion; passed to the persona chat clients as
    # `max_completion_tokens`. The LLM manager is NOT capped (it needs room for the final strategy).
    roundtable_persona_max_tokens: Optional[int] = None
    # Reasoning effort for the persona seats (gpt-5.x are reasoning models). A persona turn is
    # one short spoken point, so it needs NO hidden reasoning — and at a small max_tokens cap the
    # reasoning pass would eat the whole budget, returning EMPTY content (finish_reason=length).
    # "minimal" → reasoning_tokens=0, so the cap is spent on the visible answer and turns are ~2x
    # faster. Blank/None → omit the param (use for a non-reasoning persona model). Manager unaffected.
    roundtable_persona_reasoning_effort: Optional[str] = "minimal"
    # Output verbosity for the persona seats (gpt-5.x). "low" keeps a turn to one short spoken
    # point (a sentence or two) instead of an essay — faster turns + the intended discussion feel.
    # Blank/None → omit (use for a non-gpt-5 persona model). Manager unaffected.
    roundtable_persona_verbosity: Optional[str] = "low"
    # Reasoning effort for the LLM manager's own calls (the facts/plan phase before the first
    # turn, every round's progress ledger, the final consensus). The project default is "low" —
    # the roundtable latency lever: it shrinks the silent plan phase before the first turn AND
    # every between-turn round boundary, at some risk to ledger/selection quality. Set an explicit
    # value (minimal/medium/high) to override; the _load() fallback also resolves blank → "low".
    roundtable_manager_reasoning_effort: Optional[str] = "low"
    # The personas run on a cheaper, rate-limit-friendlier model; only the LLM manager keeps
    # the main (gpt-5.4) deployment. The personas may live on a SEPARATE Azure resource
    # (its own endpoint + key); when those are unset they fall back to the main resource and
    # only the deployment name (roundtable_persona_model) differs.
    roundtable_persona_model: Optional[str] = None
    roundtable_manager_model: Optional[str] = None
    roundtable_persona_endpoint: Optional[str] = None
    roundtable_persona_api_key: Optional[str] = None
    # How long the table waits for a user who raised a hand to actually send their message
    # before proceeding without them (seconds) — bounds the "stop and wait for the user" pause.
    roundtable_user_turn_timeout: float = 300.0
    # Step mode (roundtable_mode: "manual" on POST /tasks|/roundtable[s]): how long each round's
    # 4-way prompt (next / speak / enough / auto) waits for POST /tasks/{id}/round-control before
    # the table goes hands-off (sticky auto) — an absent user degrades to the normal flow, never
    # a hung table. The default mode is "auto" (no prompts), so this only bites when the caller
    # explicitly asked to be prompted.
    roundtable_control_timeout: float = 300.0
    # Per-user learning write-back from the roundtable (transcript + interjections + verdict).
    # LEARNING_ENABLED=false still READS stored skills but writes none (regression/isolation).
    learning_enabled: bool = True
    # ── Trend scout (the roundtable's fifth seat; docs/TREND_SCOUT_IMPLEMENTATION.md) ──
    # TREND_SCOUT_ENABLED adds the `trend_scout` persona to every table, fed from the daily
    # trends snapshot an EXTERNAL Foundry routine writes to the store. Off (default) → the
    # roster stays the current four seats and no trends read happens. The read degrades to
    # [] on any store failure — trends are an enhancement, never a dependency.
    trend_scout_enabled: bool = False
    # How many trends are injected per run, chosen category-diverse at read time.
    trend_scout_limit: int = 6
    # Staleness safety net: a trend with no explicit expires_at is dropped this many days
    # after captured_at (covers ~2-3 missed daily routine runs before degrading to "no trends").
    trend_scout_ttl_days: int = 3
    # Cheap tier for the prod per-user preference summary call. Defaults to the same
    # rate-limit-friendly deployment as the roundtable personas (ROUNDTABLE_PERSONA_MODEL);
    # PREFERENCE_SUMMARY_MODEL overrides it. None → fall back to the main chat deployment.
    preference_summary_model: Optional[str] = None
    # ── Pexels (stock photo search) + Remove.bg (cut-out backgrounds) ──────────
    pexels_api_key: Optional[str] = None
    removebg_api_key: Optional[str] = None

    # ── Geoapify (static maps + geocoding for `map` slides) ─────────────────────
    # No key → map slides render the bundled vector outline instead; never blocking.
    geoapify_api_key: Optional[str] = None
    # Explicit basemap-style override. None (default) → the style is picked from the
    # storyboard's theme (media_assets.MAP_STYLE_BY_THEME: light→osm-bright, dark→dark-matter).
    # Kept in sync with _load()'s `GEOAPIFY_MAP_STYLE or None`, so a directly-constructed
    # Settings follows the theme exactly like a loaded one. See
    # https://apidocs.geoapify.com/docs/maps/map-tiles/ for the preset names.
    geoapify_map_style: Optional[str] = None

    # ── Background music ────────────────────────────────────────────────────────
    # Provider order (see services/factory.get_music_generation): Jamendo first — a free
    # API key from devportal.jamendo.com over ~500k Creative-Commons tracks, and the only
    # provider where the agent's mood/genre/energy actually changes what you hear. Behind
    # it, a local curated library (media_assets.BundledMusicLibrary) keeps offline and
    # no-key machines working; `music_library_dir` overrides where its tracks +
    # manifest.json live (default: LLM_service/assets/music/), and it is used when the
    # library has ≥1 tagged track. Soundraw is a generative option but enterprise-gated,
    # so it is only reached when neither of the above is available.
    jamendo_client_id: Optional[str] = None
    music_library_dir: Optional[str] = None
    soundraw_api_key: Optional[str] = None

    # ── Azure Speech (text-to-speech — roundtable persona readback + video narration) ──
    roundtable_tts_key: Optional[str] = None
    roundtable_tts_region: Optional[str] = None
    # Default Neural voice when a caller doesn't specify one (POST /tasks/{id}/render-video).
    # ── Azure Speech (voiceover text-to-speech) ─────────────────────────────────
    azure_speech_key: Optional[str] = None
    azure_speech_region: Optional[str] = None
    # Default voice when a persona/caller doesn't specify one. An Azure Dragon HD voice
    # (LM-based, far more natural than the older Neural voices) — same Speech endpoint;
    # note HD voices may require the S0 tier and specific regions (see .env.example).
    voiceover_default_voice: str = "en-US-Ava:DragonHDLatestNeural"

    # ── Higgsfield (premium generative AI video render backend) ─────────────────
    # Used only when video_render_backend == "higgsfield" (see below). Auth + upload +
    # polling go through the official `higgsfield-client` SDK (base URL
    # platform.higgsfield.ai). The model ids are catalog paths passed to the SDK's
    # subscribe(): the image id (DoP image-to-video) is confirmed against the docs;
    # the text-to-video id is NOT — set HIGGSFIELD_TEXT_MODEL to the catalog path from
    # your cloud.higgsfield.ai dashboard before using the no-reference-image path.
    # Duration is clamped to the model's per-generation max (~15s for v1's single clip).
    higgsfield_api_key: Optional[str] = None
    higgsfield_api_secret: Optional[str] = None
    higgsfield_text_model: str = ""  # unverified — set from the dashboard for text-to-video
    higgsfield_image_model: str = "higgsfield-ai/dop/standard"
    higgsfield_max_duration_s: float = 15.0

    # ── Web research (Bing grounding via Azure AI Foundry agents) ──────────────
    # Reuses the same "Grounding with Bing Search" mechanism as
    # trend_scout_routine/run_scan.py (a portal-defined Foundry agent, called
    # through the OpenAI-compatible responses API) rather than a new search vendor.
    # Two separate agents because their portal instructions differ (general web
    # research vs. review-quote mining); both live on the same project endpoint.
    foundry_project_endpoint: Optional[str] = None
    web_search_agent_name: Optional[str] = None
    web_search_agent_version: Optional[str] = None
    review_search_agent_name: Optional[str] = None
    review_search_agent_version: Optional[str] = None

    # ── Video render pipeline (local Remotion CLI, or Remotion Lambda) ──────────
    # Path to the video_renderer/ Node project (repo-root sibling of LLM_service/).
    video_renderer_dir: Optional[str] = None
    # Per-job working directory: resolved images + the final MP4 (local backend
    # only — the lambda backend never writes an MP4 to local disk). Not git-tracked.
    video_jobs_dir: str = ".video_jobs"
    # "local" (default): the original `npx remotion render` subprocess, output on
    # local disk. "lambda": workflow/video/lambda_render.py — compiles + renders on
    # AWS Lambda, output in S3; render_storyboard() returns an https:// URL instead
    # of a Path either way, so jobs.py/api.py don't need to know which ran.
    # "higgsfield": the premium generative-AI-video path (workflow/video/higgsfield_render.py)
    # — no Remotion; a single cinematic clip generated from a crafted prompt (+ optional
    # user reference images for image-to-video), written to job_dir/output.mp4. This is
    # the intended fee-paying-tier product; the free tier stays on "local"/"lambda".
    video_render_backend: str = "local"
    # Headless-Chromium workers for a LOCAL render. None -> Remotion's own default
    # (~half the logical cores), except that render.py caps storyboards containing
    # stock footage, whose decoded video frames are what exhaust a small host.
    # Set this to override on a machine with more (or less) memory headroom.
    video_render_concurrency: Optional[int] = None
    # ── Remotion Lambda (workflow/video/lambda_render.py) ───────────────────────
    # Required when video_render_backend == "lambda". These name resources YOU
    # deploy yourself first via the Remotion Lambda CLI (`npx remotion lambda
    # functions deploy`, `npx remotion lambda sites create`) — this service only
    # ever TRIGGERS renders against them, it never provisions them. AWS credentials
    # are resolved the standard way (env vars / shared config / IAM role) by the
    # AWS SDK the Node trigger scripts use — nothing AWS-specific is read from this
    # Settings object beyond the region.
    aws_region: Optional[str] = None
    remotion_lambda_function_name: Optional[str] = None
    # A STABLE, pre-deployed site's serve URL, used for any storyboard with no
    # `generated` slides (the common, fast case — no per-job site deploy needed).
    remotion_lambda_serve_url: Optional[str] = None
    # A storyboard WITH `generated` slide(s) needs its own bespoke component(s)
    # bundled in, so lambda_render.py deploys a fresh, job-scoped "site" instead of
    # reusing remotion_lambda_serve_url — named "<prefix>-<job_id>".
    remotion_lambda_site_name_prefix: str = "storyboard-job"
    # S3 output location. None (default) → Remotion Lambda picks its own
    # auto-created bucket in `aws_region` (its documented default behaviour).
    remotion_lambda_output_bucket: Optional[str] = None
    # Cross-slide attempt budget for one render job's WHOLE `generated`-slide
    # codegen pass (workflow/video/codegen.CodegenBudget) — bounds total LLM calls
    # + compiles + preview-renders across every bespoke slide in one storyboard,
    # not just per-slide (codegen.DEFAULT_MAX_ATTEMPTS already bounds that). A
    # storyboard with several struggling slides could otherwise spend
    # max_attempts-per-slide x N-slides worth of real cost.
    codegen_max_total_attempts: int = 9
    # The wall-clock half of the same budget (codegen.CodegenBudget). An attempt
    # count bounds COST but says nothing about DURATION: on a reasoning-tier
    # deployment one attempt can run minutes, so a budget that looks cheap in
    # attempts can still hold a render job open far past what anyone will wait for
    # — and nothing else in the pipeline caps it (jobs.py runs the render detached,
    # the client just polls). Like the attempt budget this is a FLOOR, scaled up per
    # `generated` slide in assets.py. Checked between attempts only, so the real
    # bound is this plus one in-flight attempt. 0/blank disables the deadline.
    codegen_max_total_seconds: float = 900.0
    # Deployment for the scene-codegen LLM calls (generate_scene_component,
    # plan_scene_design, review_scene_preview, convert_generated_to_template).
    # None -> falls back to azure_chat_deployment, same pattern as
    # roundtable_persona_model/preference_summary_model. Lets a separate/stronger
    # (e.g. coding-tuned) deployment be swapped in later with no code change.
    codegen_model: Optional[str] = None
    # Reasoning effort for generate_scene_component/review_scene_preview/
    # convert_generated_to_template on a gpt-5.x/o-series deployment. None -> model
    # default. Unlike the roundtable personas (which use "minimal" for short, fast
    # turns), codegen is correctness-critical and not latency-sensitive, so a
    # higher effort is worth trying once it's actually wired (previously it silently
    # was NOT being sent at all here, unlike the roundtable path).
    codegen_reasoning_effort: Optional[str] = None
    # generate_scene_component's max_completion_tokens. MUST have enough headroom
    # for hidden reasoning tokens (gpt-5.x/o-series) PLUS a full compiling TSX
    # component — the previous 4096 hardcoded cap left razor-thin margin once any
    # reasoning is spent, the same failure mode documented for
    # ROUNDTABLE_PERSONA_MAX_TOKENS ("keep >=512, else hidden reasoning eats the
    # whole budget and turns come back EMPTY, finish_reason=length").
    codegen_max_tokens: int = 12000
    # plan_scene_design's max_completion_tokens. The old hardcoded 512 sat exactly
    # at the documented danger threshold with no reasoning_effort steer — a prime
    # suspect for the design plan silently coming back empty (swallowed by
    # plan_scene_design's `except Exception: return ""`), degrading every
    # subsequent generate_scene_component call for that slide.
    codegen_plan_max_tokens: int = 1536
    # plan_scene_design is a short creative brainstorm ("Do NOT write code"), not a
    # deep-reasoning task — mirrors the roundtable personas' "minimal" so the
    # budget goes to the visible bullets, not hidden reasoning tokens.
    codegen_plan_reasoning_effort: Optional[str] = "minimal"
    # SDK-level retries for the codegen calls ONLY (every other call site keeps the
    # client's max_retries=3). 0 by default because the openai SDK retries
    # APITimeoutError: at the client's 300s timeout, a reasoning-tier codegen call
    # that runs long costs 4 x 300s = 20 MINUTES before it finally raises. codegen.py
    # already owns retrying at a much better altitude — its own loop re-prompts with
    # the error and re-validates, and CodegenBudget bounds the total — so a
    # transport-level retry here only multiplies wall clock. Raise it only if you see
    # genuinely transient 429/5xx (which this also stops retrying).
    codegen_max_retries: int = 0
    # review_scene_preview's max_completion_tokens. The visible answer is a tiny JSON
    # object, but this call sent NO cap at all, so on a reasoning deployment it was
    # unbounded. Deliberately generous (not the ~512 the output needs): no
    # reasoning_effort is steered here, so the cap must clear the hidden-reasoning
    # floor by a wide margin or the response comes back EMPTY (see
    # ROUNDTABLE_PERSONA_MAX_TOKENS). This is a runaway ceiling, not a tight budget.
    codegen_review_max_tokens: int = 4096
    # convert_generated_to_template's max_completion_tokens. Also previously
    # uncapped — and it's the most expensive prompt in the pipeline, since it dumps
    # the whole ~23KB TemplateSlideSpec JSON schema into the system message.
    codegen_convert_max_tokens: int = 4096
    # ...and it is schema-filling, not reasoning: the slide type is nearly determined
    # by the brief, so "minimal" keeps the budget on the visible JSON. Setting this
    # also DROPS the temperature=0.2 that call used to send (see AzureLLM._complete —
    # a reasoning deployment should not get a custom temperature). Blank -> send no
    # reasoning_effort, restoring the temperature.
    codegen_convert_reasoning_effort: Optional[str] = "minimal"
    # Visual QA pass for `map` slides (workflow/video/map_qa.py): preview-still +
    # vision review per map slide, with a bounded zoom-out repair on rejection.
    # Cost per attempt ≈ one `remotion still` (5-20s) + one vision call, so
    # MAP_QA_ENABLED=false is the latency/cost kill switch.
    map_qa_enabled: bool = True
    map_qa_max_attempts: int = 2

    # ── Per-service resolution: override > global > default ─────────────────────
    def mock_llm(self) -> bool:
        return self.use_mock if self.use_mock_llm is None else self.use_mock_llm

    def mock_safety(self) -> bool:
        return self.use_mock if self.use_mock_safety is None else self.use_mock_safety

    def mock_store(self) -> bool:
        return self.use_mock if self.use_mock_store is None else self.use_mock_store

    def mock_voice(self) -> bool:
        return self.use_mock if self.use_mock_voice is None else self.use_mock_voice

    def mock_image_search(self) -> bool:
        return self.use_mock if self.use_mock_image_search is None else self.use_mock_image_search

    def mock_video_search(self) -> bool:
        return self.use_mock if self.use_mock_video_search is None else self.use_mock_video_search

    def mock_background_removal(self) -> bool:
        return self.use_mock if self.use_mock_background_removal is None else self.use_mock_background_removal

    def mock_music_generation(self) -> bool:
        return self.use_mock if self.use_mock_music_generation is None else self.use_mock_music_generation

    def mock_web_search(self) -> bool:
        return self.use_mock if self.use_mock_web_search is None else self.use_mock_web_search

    def mock_voiceover(self) -> bool:
        return self.use_mock if self.use_mock_voiceover is None else self.use_mock_voiceover

    def mock_video_generation(self) -> bool:
        return self.use_mock if self.use_mock_video_generation is None else self.use_mock_video_generation

    # ── Credential presence checks (used by production impls / factory) ─────────
    @property
    def has_azure_openai(self) -> bool:
        return bool(self.azure_openai_endpoint and self.azure_openai_api_key)

    @property
    def has_content_safety(self) -> bool:
        return bool(self.azure_content_safety_endpoint and self.azure_content_safety_key)

    @property
    def has_postgres(self) -> bool:
        return bool(self.postgres_dsn)

    @property
    def has_voice(self) -> bool:
        return bool(self.azure_voicelive_endpoint)

    @property
    def has_pexels(self) -> bool:
        return bool(self.pexels_api_key)

    @property
    def has_removebg(self) -> bool:
        return bool(self.removebg_api_key)

    @property
    def has_geoapify(self) -> bool:
        return bool(self.geoapify_api_key)

    @property
    def has_jamendo(self) -> bool:
        return bool(self.jamendo_client_id)

    @property
    def has_soundraw(self) -> bool:
        return bool(self.soundraw_api_key)

    @property
    def resolved_music_library_dir(self) -> Path:
        """Absolute path to the bundled royalty-free music library. MUSIC_LIBRARY_DIR
        overrides; otherwise defaults to LLM_service/assets/music/ (this file is
        core/config.py, so parent.parent is LLM_service/)."""
        if self.music_library_dir:
            return Path(self.music_library_dir).resolve()
        return Path(__file__).resolve().parent.parent / "assets" / "music"

    @property
    def has_music_library(self) -> bool:
        """Whether a usable bundled music library is present: a manifest.json with at
        least one tagged track. Parses defensively — a missing/malformed manifest reads
        as 'no library' (the factory then falls back to Soundraw/mock), never an error."""
        manifest = self.resolved_music_library_dir / "manifest.json"
        if not manifest.is_file():
            return False
        try:
            return bool(json.loads(manifest.read_text(encoding="utf-8")).get("tracks"))
        except Exception:
            return False

    @property
    def has_web_search(self) -> bool:
        return bool(self.foundry_project_endpoint and self.web_search_agent_name)

    @property
    def has_roundtable_tts(self) -> bool:
        return bool(self.roundtable_tts_key and self.roundtable_tts_region)

    @property
    def has_higgsfield(self) -> bool:
        return bool(self.higgsfield_api_key and self.higgsfield_api_secret)

    @property
    def resolved_video_renderer_dir(self) -> Path:
        """Absolute path to the video_renderer/ Node project. VIDEO_RENDERER_DIR
        overrides; otherwise defaults to the repo-root sibling of LLM_service/ (this
        file is core/config.py, so parent.parent.parent is the repo root).
        `.resolve()` on the override matters: render.py/codegen.py pass paths
        derived from this property as subprocess args while also setting the
        subprocess's `cwd` to this same directory — a RELATIVE VIDEO_RENDERER_DIR
        left unresolved would have the subprocess reinterpret that relative path
        against its own cwd (this directory), silently writing/reading a
        double-nested path instead of the intended one."""
        if self.video_renderer_dir:
            return Path(self.video_renderer_dir).resolve()
        return Path(__file__).resolve().parent.parent.parent / "video_renderer"

    @property
    def resolved_video_jobs_dir(self) -> Path:
        """Absolute path to the per-job working directory (resolved images + the
        final MP4). Relative `video_jobs_dir` values resolve under LLM_service/."""
        path = Path(self.video_jobs_dir)
        if path.is_absolute():
            return path
        return Path(__file__).resolve().parent.parent / path

    def mode_banner(self) -> str:
        """Human-readable one-liner describing the resolved mode of each service."""
        def tag(is_mock: bool) -> str:
            return "MOCK" if is_mock else "PROD"
        overall = "MOCK" if self.use_mock else "PRODUCTION"
        return (
            f"MODE: {overall}  "
            f"[llm={tag(self.mock_llm())} safety={tag(self.mock_safety())} "
            f"store={tag(self.mock_store())} voice={tag(self.mock_voice())} "
            f"image_search={tag(self.mock_image_search())} "
            f"video_search={tag(self.mock_video_search())} "
            f"background_removal={tag(self.mock_background_removal())} "
            f"music_generation={tag(self.mock_music_generation())} "
            f"web_search={tag(self.mock_web_search())} "
            f"voiceover={tag(self.mock_voiceover())} "
            f"video_generation={tag(self.mock_video_generation())}]"
        )


def _load() -> Settings:
    use_mock = _env_bool("USE_MOCK")
    learning = _env_bool("LEARNING_ENABLED")
    map_qa = _env_bool("MAP_QA_ENABLED")
    return Settings(
        use_mock=True if use_mock is None else use_mock,
        use_mock_llm=_env_bool("USE_MOCK_LLM"),
        use_mock_safety=_env_bool("USE_MOCK_SAFETY"),
        use_mock_store=_env_bool("USE_MOCK_STORE"),
        use_mock_voice=_env_bool("USE_MOCK_VOICE"),
        use_mock_image_search=_env_bool("USE_MOCK_IMAGE_SEARCH"),
        use_mock_video_search=_env_bool("USE_MOCK_VIDEO_SEARCH"),
        use_mock_background_removal=_env_bool("USE_MOCK_BACKGROUND_REMOVAL"),
        use_mock_music_generation=_env_bool("USE_MOCK_MUSIC_GENERATION"),
        use_mock_web_search=_env_bool("USE_MOCK_WEB_SEARCH"),
        use_mock_voiceover=_env_bool("USE_MOCK_VOICEOVER"),
        use_mock_video_generation=_env_bool("USE_MOCK_VIDEO_GENERATION"),
        azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        azure_chat_deployment=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o"),
        foundry_project_endpoint=os.getenv("FOUNDRY_PROJECT_ENDPOINT"),
        azure_content_safety_endpoint=os.getenv("AZURE_CONTENTSAFETY_ENDPOINT")
        or os.getenv("AZURE_CONTENT_SAFETY_ENDPOINT"),
        azure_content_safety_key=os.getenv("AZURE_CONTENTSAFETY_KEY")
        or os.getenv("AZURE_CONTENT_SAFETY_KEY"),
        postgres_dsn=os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN"),
        postgres_profiles_table=os.getenv("POSTGRES_PROFILES_TABLE", "brand_profiles"),
        postgres_user_skills_table=os.getenv("POSTGRES_USER_SKILLS_TABLE", "user_skills"),
        postgres_checkpoints_table=os.getenv("POSTGRES_CHECKPOINTS_TABLE", "workflow_checkpoints"),
        postgres_sslmode=os.getenv("POSTGRES_SSLMODE"),
        postgres_video_jobs_table=os.getenv("POSTGRES_VIDEO_JOBS_TABLE", "video_jobs"),
        postgres_trends_table=os.getenv("POSTGRES_TRENDS_TABLE", "trends"),
        postgres_posting_plans_table=os.getenv("POSTGRES_POSTING_PLANS_TABLE", "posting_plans"),
        azure_voicelive_endpoint=os.getenv("AZURE_VOICELIVE_ENDPOINT"),
        azure_voicelive_model=os.getenv("AZURE_VOICELIVE_MODEL", "gpt-realtime"),
        azure_voicelive_api_version=os.getenv("AZURE_VOICELIVE_API_VERSION", "2026-04-10"),
        azure_voicelive_api_key=os.getenv("AZURE_VOICELIVE_API_KEY"),
        azure_voicelive_voice=os.getenv("AZURE_VOICELIVE_VOICE", "verse"),
        roundtable_enabled=bool(_env_bool("ROUNDTABLE_ENABLED")),
        roundtable_max_rounds=_env_int("ROUNDTABLE_MAX_ROUNDS", 12),
        roundtable_persona_max_tokens=(
            _env_int("ROUNDTABLE_PERSONA_MAX_TOKENS", 0) or None
        ),
        roundtable_persona_reasoning_effort=(
            os.getenv("ROUNDTABLE_PERSONA_REASONING_EFFORT", "minimal").strip() or None
        ),
        roundtable_persona_verbosity=(
            os.getenv("ROUNDTABLE_PERSONA_VERBOSITY", "low").strip() or None
        ),
        roundtable_persona_model=os.getenv("ROUNDTABLE_PERSONA_MODEL"),
        roundtable_manager_model=os.getenv("ROUNDTABLE_MANAGER_MODEL"),
        roundtable_manager_reasoning_effort=(
            os.getenv("ROUNDTABLE_MANAGER_REASONING_EFFORT", "").strip() or "low"
        ),
        roundtable_persona_endpoint=os.getenv("AZURE_PERSONA_ENDPOINT"),
        roundtable_persona_api_key=os.getenv("AZURE_PERSONA_API_KEY"),
        roundtable_user_turn_timeout=_env_float("ROUNDTABLE_USER_TURN_TIMEOUT", 300.0),
        roundtable_control_timeout=_env_float("ROUNDTABLE_CONTROL_TIMEOUT", 300.0),
        learning_enabled=True if learning is None else learning,
        trend_scout_enabled=bool(_env_bool("TREND_SCOUT_ENABLED")),
        trend_scout_limit=_env_int("TREND_SCOUT_LIMIT", 6),
        trend_scout_ttl_days=_env_int("TREND_SCOUT_TTL_DAYS", 3),
        # The per-user summary call reuses the cheap persona deployment by default
        # (ROUNDTABLE_PERSONA_MODEL); PREFERENCE_SUMMARY_MODEL overrides if set.
        preference_summary_model=(
            os.getenv("PREFERENCE_SUMMARY_MODEL") or os.getenv("ROUNDTABLE_PERSONA_MODEL")
        ),
        pexels_api_key=os.getenv("PEXELS_API_KEY"),
        removebg_api_key=os.getenv("REMOVEBG_API_KEY"),
        geoapify_api_key=os.getenv("GEOAPIFY_API_KEY"),
        geoapify_map_style=os.getenv("GEOAPIFY_MAP_STYLE") or None,
        jamendo_client_id=os.getenv("JAMENDO_CLIENT_ID"),
        music_library_dir=os.getenv("MUSIC_LIBRARY_DIR"),
        soundraw_api_key=os.getenv("SOUNDRAW_API_KEY"),
        # Shared Azure Speech credential — used by BOTH the roundtable persona TTS
        # readback and workflow/video/voiceover.py's video narration.
        roundtable_tts_key=os.getenv("ROUNDTABLE_TTS_KEY"),
        roundtable_tts_region=os.getenv("ROUNDTABLE_TTS_REGION"),
        azure_speech_key=os.getenv("AZURE_SPEECH_KEY"),
        azure_speech_region=os.getenv("AZURE_SPEECH_REGION"),
        voiceover_default_voice=os.getenv("VOICEOVER_DEFAULT_VOICE", "en-US-Ava:DragonHDLatestNeural"),

        higgsfield_api_key=os.getenv("HIGGSFIELD_API_KEY"),
        higgsfield_api_secret=os.getenv("HIGGSFIELD_API_SECRET"),
        higgsfield_text_model=os.getenv("HIGGSFIELD_TEXT_MODEL", ""),
        higgsfield_image_model=os.getenv("HIGGSFIELD_IMAGE_MODEL", "higgsfield-ai/dop/standard"),
        higgsfield_max_duration_s=_env_float("HIGGSFIELD_MAX_DURATION_S", 15.0),
        web_search_agent_name=os.getenv("WEB_SEARCH_AGENT_NAME"),
        web_search_agent_version=os.getenv("WEB_SEARCH_AGENT_VERSION"),
        review_search_agent_name=os.getenv("REVIEW_SEARCH_AGENT_NAME"),
        review_search_agent_version=os.getenv("REVIEW_SEARCH_AGENT_VERSION"),
        video_renderer_dir=os.getenv("VIDEO_RENDERER_DIR"),
        video_jobs_dir=os.getenv("VIDEO_JOBS_DIR", ".video_jobs"),
        video_render_backend=os.getenv("VIDEO_RENDER_BACKEND", "local").strip().lower(),
        video_render_concurrency=_env_int("VIDEO_RENDER_CONCURRENCY", 0) or None,
        aws_region=os.getenv("AWS_REGION"),
        remotion_lambda_function_name=os.getenv("REMOTION_LAMBDA_FUNCTION_NAME"),
        remotion_lambda_serve_url=os.getenv("REMOTION_LAMBDA_SERVE_URL"),
        remotion_lambda_site_name_prefix=os.getenv("REMOTION_LAMBDA_SITE_NAME_PREFIX", "storyboard-job"),
        remotion_lambda_output_bucket=os.getenv("REMOTION_LAMBDA_OUTPUT_BUCKET"),
        codegen_max_total_attempts=_env_int("CODEGEN_MAX_TOTAL_ATTEMPTS", 9),
        codegen_max_total_seconds=_env_float("CODEGEN_MAX_TOTAL_SECONDS", 900.0),
        codegen_model=os.getenv("CODEGEN_MODEL"),
        codegen_reasoning_effort=(os.getenv("CODEGEN_REASONING_EFFORT") or "").strip() or None,
        codegen_max_tokens=_env_int("CODEGEN_MAX_TOKENS", 12000),
        codegen_plan_max_tokens=_env_int("CODEGEN_PLAN_MAX_TOKENS", 1536),
        codegen_plan_reasoning_effort=(
            os.getenv("CODEGEN_PLAN_REASONING_EFFORT", "minimal").strip() or None
        ),
        codegen_max_retries=_env_int("CODEGEN_MAX_RETRIES", 0),
        codegen_review_max_tokens=_env_int("CODEGEN_REVIEW_MAX_TOKENS", 4096),
        codegen_convert_max_tokens=_env_int("CODEGEN_CONVERT_MAX_TOKENS", 4096),
        codegen_convert_reasoning_effort=(
            os.getenv("CODEGEN_CONVERT_REASONING_EFFORT", "minimal").strip() or None
        ),
        map_qa_enabled=True if map_qa is None else map_qa,
        map_qa_max_attempts=_env_int("MAP_QA_MAX_ATTEMPTS", 2),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings, loading from the environment on first call.

    The `.env` file is read here, so **every** consumer sees the configured
    settings — not just `api.py:serve()` and `main.py`, which used to be the only
    callers of `load_dotenv()`. Anything else (a script, a notebook, the
    evaluation harness) silently saw an empty configuration and every toggle fell
    back to its default, which is a very quiet way to be wrong: "inherit the
    project's configuration" ended up meaning "always mock".

    Real environment variables still win (`override=False`), so an exported var
    or a value set by a caller is never clobbered by the file. Setting
    `LLM_SERVICE_IGNORE_DOTENV` suppresses the read entirely — the test suite does
    this (see `tests/conftest.py`) so the offline/deterministic guarantee never
    depends on whatever a developer happens to have in their local `.env`.

    That flag must be set **before the first resolution**, not merely before a
    `reset_settings()`: `load_dotenv` copies the file into `os.environ`, so once a
    read has happened the values are in the process environment for good and
    setting the flag later suppresses nothing. Hence conftest sets it at import.
    """
    if not _env_bool(IGNORE_DOTENV_VAR):
        load_dotenv()
    return _load()


def reset_settings() -> None:
    """Clear the cache so the next get_settings() re-reads the environment (tests)."""
    get_settings.cache_clear()
