"""
The credentialed Azure code paths (core/services/azure.py) — the layer BELOW the
`_complete` / `_analyze` / `_transcribe` seams that test_contract_parity.py stubs out.

Everything here is what only ever runs with real endpoints and keys: how each SDK
client is constructed, the exact request kwargs sent to Azure OpenAI (and the
gpt-5.x-specific parameter rules), the Content Safety severity mapping, the Voice
Live WebSocket wire protocol, and the Azure Speech TTS request. The SDKs are
lazy-imported inside the methods, so a fake module in `sys.modules` (conftest's
`install_fake_module`) drives the real code with no network and no credentials.
"""

from __future__ import annotations

import json

import pytest

from LLM_service.core.config import Settings
from LLM_service.core.services import azure
from LLM_service.tests.conftest import FakeResponse, install_fake_module


# ── Fake `openai` SDK ─────────────────────────────────────────────────────────

class FakeCompletions:
    def __init__(self, client: "FakeAsyncOpenAI") -> None:
        self._client = client

    async def create(self, **kwargs):
        self._client.calls.append(kwargs)
        return self._client.reply


class FakeAsyncOpenAI:
    """Records construction kwargs + every chat.completions.create() call."""

    instances: list["FakeAsyncOpenAI"] = []

    def __init__(self, **kwargs) -> None:
        self.init_kwargs = kwargs
        self.calls: list[dict] = []
        self.reply = _chat_reply("ok")
        FakeAsyncOpenAI.instances.append(self)
        self.chat = type("_Chat", (), {"completions": FakeCompletions(self)})()


def _chat_reply(content, tool_calls=None):
    """The slice of an OpenAI ChatCompletion the impls actually read."""
    message = type("_Msg", (), {"content": content, "tool_calls": tool_calls})()
    return type("_Resp", (), {"choices": [type("_Choice", (), {"message": message})()]})()


def _tool_call(name: str, arguments: str):
    function = type("_Fn", (), {"name": name, "arguments": arguments})()
    return type("_TC", (), {"function": function})()


@pytest.fixture
def fake_openai(monkeypatch):
    FakeAsyncOpenAI.instances = []
    install_fake_module(monkeypatch, "openai", AsyncOpenAI=FakeAsyncOpenAI)
    return FakeAsyncOpenAI


def _settings(**over) -> Settings:
    base = dict(
        azure_openai_endpoint="https://starlight.openai.azure.com/openai/v1/",
        azure_openai_api_key="sk-test", azure_chat_deployment="gpt-5.4",
    )
    base.update(over)
    return Settings(**base)


# ── AzureLLM: client construction + the `_complete` request contract ──────────

async def test_llm_client_is_built_once_against_the_v1_surface(fake_openai):
    """The CLAUDE.md endpoint gotcha: a plain AsyncOpenAI(base_url=…) — NOT
    AsyncAzureOpenAI, which would append a second /openai path and 404."""
    llm = azure.AzureLLM(_settings())
    await llm.chat([{"role": "user", "content": "hi"}])
    await llm.chat([{"role": "user", "content": "again"}])

    assert len(fake_openai.instances) == 1  # lazily built, then cached
    init = fake_openai.instances[0].init_kwargs
    assert init["base_url"] == "https://starlight.openai.azure.com/openai/v1"  # trailing / stripped
    assert init["api_key"] == "sk-test"
    assert init["max_retries"] == 3 and init["timeout"] == 300.0


async def test_complete_sends_only_the_deployment_and_messages_by_default(fake_openai):
    llm = azure.AzureLLM(_settings())
    assert await llm.chat([{"role": "user", "content": "hi"}]) == "ok"

    call = fake_openai.instances[0].calls[0]
    assert call == {"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}


async def test_complete_maps_max_tokens_to_max_completion_tokens(fake_openai):
    """The legacy `max_tokens` name is rejected by gpt-5.x / o-series deployments."""
    llm = azure.AzureLLM(_settings())
    await llm._complete([{"role": "user", "content": "x"}], max_tokens=512, temperature=0.3)

    call = fake_openai.instances[0].calls[0]
    assert call["max_completion_tokens"] == 512 and "max_tokens" not in call
    assert call["temperature"] == 0.3


async def test_complete_drops_temperature_when_reasoning_effort_is_set(fake_openai):
    """A reasoning-tier deployment rejects a custom temperature — opting into
    reasoning_effort asserts this is such a call, so temperature is dropped."""
    llm = azure.AzureLLM(_settings())
    await llm._complete([{"role": "user", "content": "x"}], model="gpt-5.4-mini",
                        temperature=0.9, reasoning_effort="minimal", verbosity="low")

    call = fake_openai.instances[0].calls[0]
    assert call["model"] == "gpt-5.4-mini"  # per-call deployment override
    assert call["reasoning_effort"] == "minimal" and call["verbosity"] == "low"
    assert "temperature" not in call


async def test_complete_returns_empty_string_when_the_model_returns_no_content(fake_openai):
    llm = azure.AzureLLM(_settings())
    llm._ensure_client().reply = _chat_reply(None)  # gpt-5.x finish_reason=length
    assert await llm.chat([{"role": "user", "content": "x"}]) == ""


async def test_name_session_uses_the_cheap_summary_tier(fake_openai):
    """Off-path decoration must not compete with the manager/persona deployments."""
    llm = azure.AzureLLM(_settings(preference_summary_model="gpt-5.4-mini"))
    llm._ensure_client().reply = _chat_reply("  Summer Oat Milk Launch  ")

    assert await llm.name_session(topic="oat latte", user_intent="trials") == "Summer Oat Milk Launch"
    assert fake_openai.instances[0].calls[0]["model"] == "gpt-5.4-mini"


# ── AzureLLM: function calling (intake) ──────────────────────────────────────

async def test_complete_with_tools_parses_tool_calls(fake_openai):
    llm = azure.AzureLLM(_settings())
    client = llm._ensure_client()
    client.reply = _chat_reply("thinking", tool_calls=[
        _tool_call("update_brief", json.dumps({"topic": "cold brew", "user_intent": ""})),
        _tool_call("suggest_topic", ""),  # no arguments at all → {}
    ])

    out = await llm.fill_brief(
        system_prompt="gather a brief", tools=[{"type": "function"}], history=[],
        user_text="post about cold brew", brief_partial={}, pending_field="topic",
    )

    call = client.calls[0]
    assert call["tools"] == [{"type": "function"}] and call["tool_choice"] == "auto"
    assert "You just asked the user for: topic." in call["messages"][0]["content"]
    # Empty values are dropped from the update; suggest_topic flips the copilot flag.
    assert out == {"brief_updates": {"topic": "cold brew"}, "wants_topic_idea": True}


async def test_complete_with_tools_handles_a_plain_text_turn(fake_openai):
    llm = azure.AzureLLM(_settings())
    llm._ensure_client().reply = _chat_reply("What's the goal?", tool_calls=None)
    out = await llm.fill_brief(
        system_prompt="gather", tools=[], history=[{"role": "assistant", "content": "hi"}],
        user_text="not sure", brief_partial={"topic": "x"}, pending_field=None,
    )
    assert out == {"brief_updates": {}, "wants_topic_idea": False}


# ── AzureChatClient (roundtable seats) ───────────────────────────────────────

async def test_chat_client_can_point_at_a_separate_persona_resource(fake_openai):
    client = azure.AzureChatClient(
        _settings(), agent_name="platform_editor", model="gpt-5.4-mini",
        endpoint="https://personas.openai.azure.com/openai/v1/", api_key="persona-key",
        max_tokens=1024, reasoning_effort="minimal", verbosity="low",
    )
    assert await client._complete([{"role": "user", "content": "your angle?"}]) == "ok"

    init = fake_openai.instances[0].init_kwargs
    assert init == {"base_url": "https://personas.openai.azure.com/openai/v1",
                    "api_key": "persona-key"}
    call = fake_openai.instances[0].calls[0]
    assert call["model"] == "gpt-5.4-mini"
    assert call["max_completion_tokens"] == 1024  # not the legacy max_tokens
    assert call["reasoning_effort"] == "minimal" and call["verbosity"] == "low"


async def test_chat_client_falls_back_to_the_main_resource_and_omits_unset_levers(fake_openai):
    client = azure.AzureChatClient(_settings(), agent_name="manager")
    await client._complete([{"role": "user", "content": "ledger?"}])

    assert fake_openai.instances[0].init_kwargs["api_key"] == "sk-test"
    call = fake_openai.instances[0].calls[0]
    assert call["model"] == "gpt-5.4"  # no persona model set → the main deployment
    assert not {"max_completion_tokens", "reasoning_effort", "verbosity"} & set(call)


async def test_chat_client_prepends_agent_instructions_from_options(fake_openai):
    """MAF carries an Agent's `instructions` on the per-call options dict, NOT in the
    message list — dropping them makes the seat speak with no role context."""
    from agent_framework import Message

    client = azure.AzureChatClient(_settings(), agent_name="brand_voice")
    # `contents` is a Sequence — a BARE str is iterated one content per character,
    # so the text must be wrapped in a list (the same gotcha `_finalize` documents).
    resp = await client._inner_get_response(
        messages=[Message("user", ["your angle?"])], stream=False,
        options={"instructions": "You are the brand voice."},
    )

    assert resp.text == "ok"
    sent = fake_openai.instances[0].calls[0]["messages"]
    assert sent[0] == {"role": "system", "content": "You are the brand voice."}
    assert sent[1]["content"] == "your angle?"


# ── AzureSafety (Azure AI Content Safety) ────────────────────────────────────

class FakeContentSafetyClient:
    """Records construction + analyze_text, and whether it was closed. The next
    instance's answer is scripted on the CLASS (`severities` / `raises`), since the
    client is constructed inside `_analyze`."""

    instances: list["FakeContentSafetyClient"] = []
    severities: dict[str, int] = {}
    raises: Exception | None = None

    def __init__(self, endpoint, credential) -> None:
        self.endpoint = endpoint
        self.credential = credential
        self.closed = False
        self.analyzed: list[str] = []
        self._severities = dict(FakeContentSafetyClient.severities)
        self._raises = FakeContentSafetyClient.raises
        FakeContentSafetyClient.instances.append(self)

    async def analyze_text(self, options):
        self.analyzed.append(options.text)
        if self._raises:
            raise self._raises
        analysis = [type("_Cat", (), {"category": cat, "severity": sev})()
                    for cat, sev in self._severities.items()]
        return type("_Result", (), {"categories_analysis": analysis})()

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_content_safety(monkeypatch):
    FakeContentSafetyClient.instances = []
    FakeContentSafetyClient.severities = {}
    FakeContentSafetyClient.raises = None
    install_fake_module(monkeypatch, "azure.ai.contentsafety.aio",
                        ContentSafetyClient=FakeContentSafetyClient)
    install_fake_module(monkeypatch, "azure.ai.contentsafety.models",
                        AnalyzeTextOptions=lambda text: type("_Opts", (), {"text": text})())
    install_fake_module(monkeypatch, "azure.core.credentials",
                        AzureKeyCredential=lambda key: ("key", key))
    return FakeContentSafetyClient


def _safety_settings() -> Settings:
    return Settings(azure_content_safety_endpoint="https://cs.cognitiveservices.azure.com",
                    azure_content_safety_key="cs-key")


@pytest.mark.parametrize("severities, blocked, reason", [
    ({"Hate": 4, "Sexual": 0}, True, "flagged: Hate"),        # 4 IS the threshold
    ({"Hate": 2, "Violence": 0}, False, "ok"),                # below it → safe
    ({"Hate": 6, "Violence": 4}, True, "flagged: Hate, Violence"),
    ({"Hate": None}, False, "ok"),                            # missing severity → 0
])
async def test_safety_maps_category_severities_to_the_contract(
        fake_content_safety, severities, blocked, reason):
    fake_content_safety.severities = severities
    result = await azure.AzureSafety(_safety_settings()).check(text="some copy")
    assert result.blocked is blocked and result.reason == reason


async def test_safety_client_is_built_with_endpoint_and_key_and_always_closed(fake_content_safety):
    await azure.AzureSafety(_safety_settings()).check(text="fine")

    client = fake_content_safety.instances[-1]
    assert client.endpoint == "https://cs.cognitiveservices.azure.com"
    assert client.credential == ("key", "cs-key")
    assert client.analyzed == ["fine"]
    assert client.closed is True


async def test_safety_closes_the_client_even_when_analysis_raises(fake_content_safety):
    fake_content_safety.raises = RuntimeError("content safety is down")
    with pytest.raises(RuntimeError, match="content safety is down"):
        await azure.AzureSafety(_safety_settings()).check(text="anything")
    assert fake_content_safety.instances[-1].closed is True


# ── Voice Live (STT) + the realtime speech-to-speech bridge ──────────────────

class FakeWebSocket:
    def __init__(self, inbound: list[dict] | None = None) -> None:
        self.sent: list[dict] = []
        self.closed = False
        self._inbound = inbound or []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        async def gen():
            for event in self._inbound:
                yield json.dumps(event)

        return gen()


class FakeConnect:
    """`websockets.connect(...)` is both awaitable and an async context manager —
    AzureVoice uses the `async with` form, AzureRealtimeVoice awaits it."""

    def __init__(self, recorder, ws: FakeWebSocket) -> None:
        self._recorder = recorder
        self._ws = ws

    def __await__(self):
        async def go():
            return self._ws

        return go().__await__()

    async def __aenter__(self):
        return self._ws

    async def __aexit__(self, *exc):
        return False


class FakeWebsockets:
    def __init__(self, ws: FakeWebSocket) -> None:
        self.ws = ws
        self.connections: list[tuple[str, dict]] = []

    def connect(self, url, **kwargs):
        self.connections.append((url, kwargs))
        return FakeConnect(self, self.ws)


@pytest.fixture
def fake_websockets(monkeypatch):
    def install(inbound: list[dict] | None = None) -> FakeWebsockets:
        fake = FakeWebsockets(FakeWebSocket(inbound))
        install_fake_module(monkeypatch, "websockets", connect=fake.connect)
        return fake

    return install


def _voice_settings(**over) -> Settings:
    base = dict(azure_voicelive_endpoint="https://starlight.services.ai.azure.com",
                azure_voicelive_api_key="voice-key", azure_voicelive_model="gpt-realtime")
    base.update(over)
    return Settings(**base)


def test_voice_live_url_normalizes_scheme_and_path():
    url = azure.AzureVoice(_voice_settings())._ws_url()
    assert url.startswith("wss://starlight.services.ai.azure.com/voice-live/realtime?")
    assert "model=gpt-realtime" in url and "api-version=" in url

    # http → ws, an already-complete path is not doubled, trailing / is trimmed.
    plain = azure.AzureVoice(_voice_settings(
        azure_voicelive_endpoint="http://localhost:8000/voice-live/realtime/"))._ws_url()
    assert plain.startswith("ws://localhost:8000/voice-live/realtime?")
    assert plain.count("/voice-live/realtime") == 1


async def test_voice_transcribe_drives_the_voice_live_handshake(fake_websockets):
    fake = fake_websockets([
        {"type": "session.created"},  # ignored
        {"type": "conversation.item.input_audio_transcription.completed",
         "transcript": "  post about cold brew  "},
    ])

    out = await azure.AzureVoice(_voice_settings()).transcribe_turn(
        session_id="s1", user_audio="AAA=")

    assert out == {"session_id": "s1", "transcript": "post about cold brew"}
    url, kwargs = fake.connections[0]
    assert url.startswith("wss://") and kwargs["additional_headers"] == {"api-key": "voice-key"}
    assert [frame["type"] for frame in fake.ws.sent] == [
        "session.update", "input_audio_buffer.append", "input_audio_buffer.commit"]
    assert fake.ws.sent[0]["session"]["input_audio_transcription"] == {"model": "whisper-1"}
    assert fake.ws.sent[1]["audio"] == "AAA="


async def test_voice_transcribe_returns_empty_when_the_stream_ends_silent(fake_websockets):
    fake_websockets([{"type": "response.done"}])
    out = await azure.AzureVoice(_voice_settings()).transcribe_turn(session_id="s1", user_audio="A=")
    assert out["transcript"] == ""


async def test_voice_key_falls_back_to_the_openai_key(fake_websockets):
    """Both point at one resource; AZURE_VOICELIVE_API_KEY is optional."""
    fake = fake_websockets([])
    settings = _voice_settings(azure_voicelive_api_key=None, azure_openai_api_key="sk-test")
    await azure.AzureVoice(settings).transcribe_turn(session_id="s1", user_audio="A=")
    assert fake.connections[0][1]["additional_headers"] == {"api-key": "sk-test"}


async def test_realtime_open_session_connects_and_configures(fake_websockets):
    from LLM_service.intake.base import BRIEF_TOOL_DEFS

    fake = fake_websockets([])
    session = await azure.AzureRealtimeVoice(_voice_settings()).open_session(
        session_id="s1", instructions="be brief", tools=BRIEF_TOOL_DEFS)

    assert isinstance(session, azure._AzureRealtimeSession)
    url, kwargs = fake.connections[0]
    assert url.startswith("wss://") and kwargs["additional_headers"] == {"api-key": "voice-key"}

    config = fake.ws.sent[0]["session"]
    assert config["instructions"] == "be brief" and config["voice"] == "verse"
    assert config["turn_detection"] == {"type": "server_vad"}
    # The shared tool defs are reshaped to the Realtime API's flat shape.
    assert [t["name"] for t in config["tools"]] == [t["function"]["name"] for t in BRIEF_TOOL_DEFS]
    assert all("function" not in t for t in config["tools"])

    await session.close()
    assert fake.ws.closed is True


def test_realtime_tool_adapter_defaults_missing_parameters():
    flat = azure._to_realtime_tools([{"function": {"name": "bare"}}])
    assert flat == [{"type": "function", "name": "bare", "description": "",
                     "parameters": {"type": "object", "properties": {}}}]


# ── Azure Speech TTS (the render pipeline's optional narration) ──────────────

def _speech_settings() -> Settings:
    # ONE Azure Speech credential serves both TTS consumers — the roundtable persona
    # readback and this render-pipeline narration — hence the roundtable-prefixed names.
    return Settings(roundtable_tts_key="speech-key", roundtable_tts_region="westeurope")


def test_speech_synthesis_url_is_region_scoped():
    assert azure.AzureSpeechVoiceover(_speech_settings())._synthesis_url() == (
        "https://westeurope.tts.speech.microsoft.com/cognitiveservices/v1")


def test_speech_ssml_escapes_the_narration_text():
    ssml = azure.AzureSpeechVoiceover._ssml('5 < 10 & "quoted"', "en-US-JennyNeural")
    assert '<voice name="en-US-JennyNeural">' in ssml
    assert "5 &lt; 10 &amp; &quot;quoted&quot;" in ssml
    assert 'version="1.0"' in ssml


async def test_speech_synthesize_posts_ssml_with_the_subscription_key(fake_httpx):
    fake_httpx.handler = lambda *_: FakeResponse(content=b"mp3-narration")

    out = await azure.AzureSpeechVoiceover(_speech_settings()).synthesize(
        text="Our new single-origin is here.", voice="en-US-JennyNeural")

    method, url, kwargs = fake_httpx.call()
    assert (method, url) == ("POST", "https://westeurope.tts.speech.microsoft.com/cognitiveservices/v1")
    assert kwargs["headers"]["Ocp-Apim-Subscription-Key"] == "speech-key"
    assert kwargs["headers"]["Content-Type"] == "application/ssml+xml"
    assert kwargs["headers"]["X-Microsoft-OutputFormat"] == "audio-24khz-48kbitrate-mono-mp3"
    assert b"Our new single-origin is here." in kwargs["content"]
    # A SynthesizedSpeech, not raw bytes: the per-slide voiceover pipeline stretches each
    # slide to fit its narration, and only this impl knows the output format well enough
    # to say how long the clip is (CBR 48 kbit/s → bytes × 8 / 48000).
    assert out.audio == b"mp3-narration"
    assert out.duration_seconds == pytest.approx(len(b"mp3-narration") * 8 / 48000)
