"""Bedrock (Claude + Amazon Nova) and Gemini support across the semantic
layer, OCR and the review agent. Every client here is a fake — Anthropic
SDK stand-ins, an httpx MockTransport for the Converse API, and real
google-genai response types fed through a fake `generate_content` — so the
request shapes are checked without a network call."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from google.genai import types as genai_types

from backend.config import REPO_ROOT
from backend.main import app
from backend.services import session_store
from backend.services.agent import runs
from backend.services.agent.anthropic_backend import BedrockClaudeBackend
from backend.services.agent.client import resolve_agent_backend
from backend.services.agent.converse_backend import ConverseBackend
from backend.services.agent.gemini_backend import GeminiBackend
from backend.services.agent.runner import SUBMIT_TOOL, AgentError, RunLimits, run_loop
from backend.services.agent.schemas import AgentAnswer
from backend.services.agent.tools import SessionContext
from backend.services.llm import bedrock_provider
from backend.services.llm.bedrock import ConverseClient, model_family, resolve_bedrock_target
from backend.services.llm.credentials import LlmCredentials
from backend.services.llm.json_schema import inline_schema, nova_schema
from backend.services.llm.provider import LlmUnavailable, resolve_llm_provider
from backend.services.llm.schemas import ResidualSuggestion
from backend.services.ocr.provider import resolve_ocr_provider

DEMO_OLD = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.0.pdf"
DEMO_NEW = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.1.pdf"
SERVER_KEYS = (
    "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
    "AWS_BEARER_TOKEN_BEDROCK", "AWS_REGION", "AWS_DEFAULT_REGION", "PLIMSOLL_BEDROCK_MODEL", "PLIMSOLL_GEMINI_AGENT_MODEL",
    "PLIMSOLL_AI_PROVIDER",
)
NOVA = "global.amazon.nova-2-lite-v1:0"
RESIDUAL = {"semantic_change_type": "clarification", "suggest_escalate": False, "suggested_risk": None, "rationale": "用詞更精確。"}
ANSWER = {"answer_type": "out_of_scope", "text": "", "citations": [], "pending": [], "glossary_terms": []}


@pytest.fixture(autouse=True)
def no_server_keys(monkeypatch):
    for var in SERVER_KEYS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def session_id():
    result = session_store.process_upload(DEMO_OLD.read_bytes(), DEMO_OLD.name, DEMO_NEW.read_bytes(), DEMO_NEW.name)
    sid = result["session"]["session_id"]
    yield sid
    session_store.delete_session(sid)


@pytest.fixture
def ctx(session_id) -> SessionContext:
    return SessionContext.load(session_id)


def bedrock(model: str = "anthropic.claude-sonnet-5", region: str | None = "ap-northeast-1") -> LlmCredentials:
    return LlmCredentials("bedrock", "bedrock-token", region, model)


# ---- Bedrock target ----------------------------------------------------------


def test_bedrock_target_validates_region_and_model():
    target, reason = resolve_bedrock_target(bedrock(NOVA))
    assert reason is None and target.family == "nova" and target.region == "ap-northeast-1"
    assert "bedrock-token" not in repr(target)
    assert resolve_bedrock_target(bedrock(region=None))[1] == "尚未選擇 Bedrock 的區域（region）。"
    # The region becomes a hostname and the model a URL path — neither may smuggle anything in.
    assert resolve_bedrock_target(bedrock(region="evil.example.com/x"))[0] is None
    assert resolve_bedrock_target(bedrock(model="anthropic.claude/../../x"))[0] is None
    assert resolve_bedrock_target(bedrock(model="meta.llama4-maverick"))[1].startswith("不支援的 Bedrock 模型")


def test_bedrock_target_falls_back_to_server_env(monkeypatch):
    assert resolve_bedrock_target(None)[1] == "尚未設定 Bedrock 的 API 金鑰。"
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "server-token")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    target, _ = resolve_bedrock_target(None)
    assert (target.token, target.region, target.model) == ("server-token", "us-east-1", "anthropic.claude-sonnet-5")


def test_model_family_reads_through_inference_profile_prefixes():
    assert model_family(NOVA) == "nova"
    assert model_family("us.anthropic.claude-haiku-4-5") == "claude"
    assert model_family("amazon.titan-text") is None


def test_schemas_are_flattened_for_gemini_and_nova():
    for schema in (inline_schema(ResidualSuggestion.model_json_schema()), nova_schema(AgentAnswer.model_json_schema())):
        text = json.dumps(schema)
        assert "$ref" not in text and "$defs" not in text and "anyOf" not in text and '"title"' not in text
    folded = inline_schema(ResidualSuggestion.model_json_schema())["properties"]["suggested_risk"]
    assert folded["type"] == ["string", "null"] and None in folded["enum"]
    assert "additionalProperties" not in json.dumps(nova_schema({"type": "object", "properties": {}, "additionalProperties": False}))


# ---- semantic layer + OCR on Bedrock -----------------------------------------


class FakeAnthropic:
    """Stands in for anthropic.Anthropic: `messages.create` (Bedrock) and
    `beta.messages.create` (Claude API) both draw from one script."""

    def __init__(self, script: list):
        self.calls: list[dict] = []
        self._script = list(script)
        create = SimpleNamespace(create=self._create)
        self.messages = create
        self.beta = SimpleNamespace(messages=create)

    def _create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._script.pop(0)


def _usage():
    return SimpleNamespace(input_tokens=100, output_tokens=40, cache_creation_input_tokens=0, cache_read_input_tokens=60)


def claude_response(content: list, stop: str):
    return SimpleNamespace(content=content, stop_reason=stop, usage=_usage(), model="anthropic.claude-sonnet-5")


def tool_use(block_id: str, name: str, arguments: dict):
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=arguments)


def text_block(value: str):
    return SimpleNamespace(type="text", text=value)


def test_bedrock_claude_provider_forces_the_submit_tool(monkeypatch):
    fake = FakeAnthropic([claude_response([tool_use("t1", "submit_result", RESIDUAL)], "tool_use")])
    monkeypatch.setattr(bedrock_provider, "claude_client", lambda _target: fake)
    provider = resolve_llm_provider(bedrock())
    assert provider.provider_name == "bedrock" and provider.model_id == "anthropic.claude-sonnet-5"
    assert provider.classify_residual("舊", "新").semantic_change_type == "clarification"
    call = fake.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "submit_result"}
    # A forced tool can't be combined with thinking, and Sonnet 5 thinks by default.
    assert call["thinking"] == {"type": "disabled"}
    assert "output_config" not in call and "fallbacks" not in call


def test_bedrock_claude_provider_never_guesses(monkeypatch):
    bad = {**RESIDUAL, "semantic_change_type": "made_up"}
    fake = FakeAnthropic([claude_response([text_block("我覺得是潤飾")], "end_turn"), claude_response([tool_use("t1", "submit_result", bad)], "tool_use")])
    monkeypatch.setattr(bedrock_provider, "claude_client", lambda _target: fake)
    provider = resolve_llm_provider(bedrock())
    with pytest.raises(LlmUnavailable):
        provider.classify_residual("舊", "新")
    with pytest.raises(LlmUnavailable):
        provider.classify_residual("舊", "新")


def test_models_that_refuse_a_forced_tool_get_auto(monkeypatch):
    fake = FakeAnthropic([claude_response([tool_use("t1", "submit_result", RESIDUAL)], "tool_use")])
    monkeypatch.setattr(bedrock_provider, "claude_client", lambda _target: fake)
    resolve_llm_provider(bedrock("anthropic.claude-opus-5-5")).classify_residual("舊", "新")
    assert fake.calls[0]["tool_choice"] == {"type": "auto"} and "thinking" not in fake.calls[0]


def test_bedrock_has_no_batch(monkeypatch):
    monkeypatch.setattr(bedrock_provider, "claude_client", lambda _target: FakeAnthropic([]))
    provider = resolve_llm_provider(bedrock())
    assert provider.supports_batch is False
    with pytest.raises(LlmUnavailable, match="批次"):
        provider.classify_residual_batch([("a", "舊", "新")])


def converse_transport(replies: list[dict], seen: list[httpx.Request], *, status: int = 200, headers: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=replies.pop(0), headers=headers or {})

    return httpx.MockTransport(handler)


def nova_reply(content: list, stop: str = "tool_use") -> dict:
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": stop,
        "usage": {"inputTokens": 50, "outputTokens": 20, "cacheReadInputTokens": 30, "cacheWriteInputTokens": 0},
    }


def test_nova_provider_calls_converse_with_bearer_token_and_forced_tool(monkeypatch):
    seen: list[httpx.Request] = []
    reply = nova_reply([{"toolUse": {"toolUseId": "u1", "name": "submit_result", "input": RESIDUAL}}])
    monkeypatch.setattr(bedrock_provider, "ConverseClient", lambda t: ConverseClient(t, http=httpx.Client(transport=converse_transport([reply], seen))))
    provider = resolve_llm_provider(bedrock(NOVA))
    assert provider.classify_residual("舊", "新").rationale == "用詞更精確。"
    request = seen[0]
    assert str(request.url) == "https://bedrock-runtime.ap-northeast-1.amazonaws.com/model/global.amazon.nova-2-lite-v1%3A0/converse"
    assert request.headers["authorization"] == "Bearer bedrock-token"
    body = json.loads(request.content)
    assert body["toolConfig"]["toolChoice"] == {"tool": {"name": "submit_result"}}
    assert "$defs" not in json.dumps(body["toolConfig"]["tools"])


def test_nova_ocr_sends_the_image_as_base64(monkeypatch):
    seen: list[httpx.Request] = []
    reply = nova_reply([{"toolUse": {"toolUseId": "u1", "name": "submit_result", "input": {"text": "冷卻水", "confidence": 0.9, "illegible": False}}}])
    monkeypatch.setattr(bedrock_provider, "ConverseClient", lambda t: ConverseClient(t, http=httpx.Client(transport=converse_transport([reply], seen))))
    ocr = resolve_ocr_provider(bedrock(NOVA))
    assert ocr.provider_name == "bedrock-vision"
    assert ocr.recognize(b"\x89PNG-bytes", media_type="image/png").text == "冷卻水"
    image = json.loads(seen[0].content)["messages"][0]["content"][0]["image"]
    assert image["format"] == "png" and isinstance(image["source"]["bytes"], str)


def test_bedrock_env_key_is_a_server_side_provider(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "server-token")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setattr(bedrock_provider, "claude_client", lambda _target: FakeAnthropic([]))
    assert resolve_llm_provider(None).provider_name == "bedrock"
    assert resolve_ocr_provider(None).provider_name == "bedrock-vision"


def test_chain_batch_with_bedrock_is_409_with_a_reason(monkeypatch):
    monkeypatch.setattr(bedrock_provider, "claude_client", lambda _target: FakeAnthropic([]))
    headers = {"X-Llm-Provider": "bedrock", "X-Llm-Api-Key": "t", "X-Llm-Region": "ap-northeast-1", "X-Llm-Model": "anthropic.claude-sonnet-5"}
    res = TestClient(app).post("/api/chains/c-any/semantic-preview/batch", headers=headers)
    assert res.status_code == 409 and "批次" in res.json()["detail"]


# ---- which backend the agent runs on -----------------------------------------


def test_agent_backend_follows_the_selected_provider(monkeypatch):
    monkeypatch.setattr("backend.services.llm.bedrock.claude_client", lambda _target: FakeAnthropic([]))
    assert resolve_agent_backend(LlmCredentials("anthropic", "k"))[0].provider == "anthropic"
    gemini = resolve_agent_backend(LlmCredentials("gemini", "k"))[0]
    assert (gemini.provider, gemini.model) == ("gemini", "gemini-3.1-pro-preview")
    claude_on_bedrock = resolve_agent_backend(bedrock())[0]
    assert isinstance(claude_on_bedrock, BedrockClaudeBackend) and claude_on_bedrock.model == "anthropic.claude-sonnet-5"
    assert isinstance(resolve_agent_backend(bedrock(NOVA))[0], ConverseBackend)
    backend, reason = resolve_agent_backend(LlmCredentials("openai", "k"))
    assert backend is None and "Gemini" in reason
    assert resolve_agent_backend(bedrock(region=None)) == (None, "尚未選擇 Bedrock 的區域（region）。")


def test_agent_backend_from_server_env(monkeypatch):
    assert resolve_agent_backend(None)[0] is None
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert "Gemini" in resolve_agent_backend(None)[1]  # only ChatGPT configured: say the agent doesn't do it
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("PLIMSOLL_GEMINI_AGENT_MODEL", "gemini-3.8-flash")
    assert resolve_agent_backend(None)[0].model == "gemini-3.8-flash"


# ---- agent loop on Claude-on-Bedrock --------------------------------------------


def _answer_loop(backend, ctx):
    return run_loop(backend, system="s", user_content="u", ctx=ctx, output_model=AgentAnswer, limits=RunLimits(5, 60))


def test_bedrock_claude_agent_request_and_submit_tool(ctx):
    fake = FakeAnthropic(
        [
            claude_response([tool_use("t1", "get_session_overview", {})], "tool_use"),
            claude_response([tool_use("t2", SUBMIT_TOOL, ANSWER)], "tool_use"),
        ]
    )
    raw, loop = _answer_loop(BedrockClaudeBackend(fake, "anthropic.claude-sonnet-5"), ctx)
    assert raw.answer_type == "out_of_scope" and [s.tool for s in loop.steps] == ["get_session_overview"]
    first = fake.calls[0]
    assert first["model"] == "anthropic.claude-sonnet-5"
    assert {"fallbacks", "betas", "cache_control"}.isdisjoint(first)  # none of these exist on Bedrock
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["thinking"] == {"type": "adaptive"} and first["output_config"] == {"effort": "medium"}
    assert first["tools"][-1]["name"] == SUBMIT_TOOL
    haiku = FakeAnthropic([claude_response([tool_use("t1", SUBMIT_TOOL, ANSWER)], "tool_use")])
    _answer_loop(BedrockClaudeBackend(haiku, "anthropic.claude-haiku-4-5"), ctx)
    assert "thinking" not in haiku.calls[0] and "output_config" not in haiku.calls[0]


def test_bad_submit_gets_one_correction_and_prose_gets_a_nudge(ctx):
    fake = FakeAnthropic(
        [
            claude_response([text_block("我查完了。")], "end_turn"),
            claude_response([tool_use("t1", SUBMIT_TOOL, {**ANSWER, "answer_type": "maybe"})], "tool_use"),
            claude_response([tool_use("t2", SUBMIT_TOOL, ANSWER)], "tool_use"),
        ]
    )
    raw, _ = _answer_loop(BedrockClaudeBackend(fake, "anthropic.claude-sonnet-5"), ctx)
    assert raw.answer_type == "out_of_scope"
    assert fake.calls[1]["messages"][-1]["content"] == f"請呼叫 {SUBMIT_TOOL} 工具交出結果。"
    correction = fake.calls[2]["messages"][-1]["content"][0]
    assert correction["is_error"] is True and "answer_type" in correction["content"]


# ---- agent loop on Nova (Converse) ---------------------------------------------


def test_nova_agent_loop(ctx):
    seen: list[httpx.Request] = []
    replies = [
        nova_reply([{"reasoningContent": {"reasoningText": {"text": "[REDACTED]"}}}, {"toolUse": {"toolUseId": "u1", "name": "get_difference", "input": {"difference_id": "D99"}}}]),
        nova_reply([{"toolUse": {"toolUseId": "u2", "name": SUBMIT_TOOL, "input": ANSWER}}]),
    ]
    target, _ = resolve_bedrock_target(bedrock(NOVA))
    backend = ConverseBackend(ConverseClient(target, http=httpx.Client(transport=converse_transport(replies, seen))))
    raw, loop = _answer_loop(backend, ctx)
    assert raw.answer_type == "out_of_scope"
    assert loop.usage["cache_read_input_tokens"] == 60 and loop.model == NOVA
    first, second = (json.loads(r.content) for r in seen)
    assert first["system"][1] == {"cachePoint": {"type": "default"}}
    assert first["additionalModelRequestFields"]["reasoningConfig"]["maxReasoningEffort"] == "medium"
    assert second["messages"][1]["content"][0] == {"reasoningContent": {"reasoningText": {"text": "[REDACTED]"}}}  # echoed verbatim
    result = second["messages"][2]["content"][0]["toolResult"]
    assert result["toolUseId"] == "u1" and result["status"] == "error" and "D99" in result["content"][0]["text"]


def test_nova_errors_and_refusals_reach_the_reviewer_worded(ctx):
    target, _ = resolve_bedrock_target(bedrock(NOVA))
    denied = ConverseClient(target, http=httpx.Client(transport=converse_transport(
        [{"message": "Model access denied"}], [], status=403, headers={"x-amzn-ErrorType": "AccessDeniedException:http://internal"},
    )))
    with pytest.raises(AgentError, match="開通模型"):
        _answer_loop(ConverseBackend(denied), ctx)
    filtered = ConverseClient(target, http=httpx.Client(transport=converse_transport([nova_reply([], "content_filtered")], [])))
    with pytest.raises(AgentError, match="拒絕"):
        _answer_loop(ConverseBackend(filtered), ctx)


# ---- agent loop on Gemini ------------------------------------------------------


class FakeGenai:
    def __init__(self, script: list):
        self.calls: list[dict] = []
        self._script = list(script)
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": list(contents), "config": config})
        return self._script.pop(0)


def gemini_response(parts: list, finish: str = "STOP"):
    return genai_types.GenerateContentResponse(
        candidates=[genai_types.Candidate(content=genai_types.Content(role="model", parts=parts), finish_reason=finish)],
        usage_metadata=genai_types.GenerateContentResponseUsageMetadata(
            prompt_token_count=100, cached_content_token_count=60, candidates_token_count=10, thoughts_token_count=5,
        ),
        model_version="gemini-3.1-pro-preview",
    )


def call_part(call_id: str, name: str, args: dict):
    return genai_types.Part(function_call=genai_types.FunctionCall(id=call_id, name=name, args=args))


def test_gemini_agent_loop(ctx):
    fake = FakeGenai(
        [
            gemini_response([genai_types.Part(text="先看概況。", thought=True), call_part("c1", "get_session_overview", {})]),
            gemini_response([call_part("c2", SUBMIT_TOOL, ANSWER)]),
        ]
    )
    raw, loop = _answer_loop(GeminiBackend(api_key="k", client=fake), ctx)
    assert raw.answer_type == "out_of_scope"
    assert loop.usage["input_tokens"] == 80 and loop.usage["cache_read_input_tokens"] == 120 and loop.usage["output_tokens"] == 30
    config = fake.calls[0]["config"]
    assert config.automatic_function_calling.disable is True
    assert config.thinking_config.thinking_level == "MEDIUM" or str(config.thinking_config.thinking_level).upper().endswith("MEDIUM")
    names = [d.name for d in config.tools[0].function_declarations]
    assert names[-1] == SUBMIT_TOOL and "get_difference" in names
    history = fake.calls[1]["contents"]
    assert history[1].parts[1].function_call.id == "c1"  # the model's own Content, unchanged (thought signatures live here)
    response = history[2].parts[0].function_response
    assert response.id == "c1" and response.name == "get_session_overview" and "result" in response.response


def test_gemini_semantic_layer_thinks_at_the_calls_effort():
    from backend.services.llm.gemini_provider import GeminiProvider

    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(parsed=ResidualSuggestion(**RESIDUAL))

    provider = GeminiProvider(api_key="k")
    provider._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    provider.classify_residual("舊", "新", effort="low")
    assert calls[0]["model"] == "gemini-3.8-flash"
    thinking = calls[0]["config"].thinking_config
    assert str(getattr(thinking.thinking_level, "value", thinking.thinking_level)).lower() == "low" and thinking.thinking_budget is None


def test_gemini_safety_stop_is_a_refusal(ctx):
    fake = FakeGenai([gemini_response([], finish="SAFETY")])
    with pytest.raises(AgentError, match="拒絕"):
        _answer_loop(GeminiBackend(api_key="k", client=fake), ctx)


# ---- end to end: the run record names the provider -------------------------------


def test_agent_run_records_bedrock_as_provider(session_id, monkeypatch):
    fake = FakeAnthropic([claude_response([tool_use("t1", SUBMIT_TOOL, ANSWER)], "tool_use")])
    monkeypatch.setattr("backend.api.agent.resolve_agent_backend", lambda *_: (BedrockClaudeBackend(fake, "anthropic.claude-sonnet-5"), None))
    api = TestClient(app)
    run_id = api.post(f"/api/sessions/{session_id}/agent/questions", json={"question": "這份文件的頁數？"}).json()["run_id"]
    for _ in range(100):
        body = api.get(f"/api/sessions/{session_id}/agent/runs/{run_id}").json()
        if body["status"] != "running":
            break
        time.sleep(0.02)
    assert body["status"] == "done"
    record = json.loads((session_store.SESSIONS_ROOT / session_id / runs.RUNS_FILE).read_text(encoding="utf-8").splitlines()[-1])
    assert record["provider"] == "bedrock" and record["model"] == "anthropic.claude-sonnet-5"


# ---- the server's own keys: placeholders and PLIMSOLL_AI_PROVIDER --------------
# 2026-10-02: a .env copied from .env.example kept 「your_..._here」 values for
# Anthropic/Gemini/OpenAI next to a real Bedrock token; the server picked the
# fake Anthropic key (first in order) and every agent run got a 401.


def test_example_placeholders_dont_count_as_server_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your_anthropic_key_here")
    monkeypatch.setenv("GEMINI_API_KEY", "your_gemini_api_key_here")
    monkeypatch.setenv("OPENAI_API_KEY", "換成你的金鑰")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "ABSKreal-looking-token")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    monkeypatch.setattr("backend.services.llm.bedrock.claude_client", lambda _target: FakeAnthropic([]))
    monkeypatch.setattr(bedrock_provider, "claude_client", lambda _target: FakeAnthropic([]))
    assert resolve_llm_provider(None).provider_name == "bedrock"
    assert resolve_ocr_provider(None).provider_name == "bedrock-vision"
    assert resolve_agent_backend(None)[0].provider == "bedrock"


def test_plimsoll_ai_provider_pins_the_server_side_choice(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-a-real-looking-key")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "ABSKreal-looking-token")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    monkeypatch.setattr("backend.services.llm.bedrock.claude_client", lambda _target: FakeAnthropic([]))
    monkeypatch.setattr(bedrock_provider, "claude_client", lambda _target: FakeAnthropic([]))
    assert resolve_llm_provider(None).provider_name == "anthropic"  # default order
    monkeypatch.setenv("PLIMSOLL_AI_PROVIDER", "bedrock")
    assert resolve_llm_provider(None).provider_name == "bedrock"
    assert resolve_agent_backend(None)[0].provider == "bedrock"
    monkeypatch.setenv("PLIMSOLL_AI_PROVIDER", "openai")  # pinned, but no key and no agent
    assert resolve_llm_provider(None) is None
    backend, reason = resolve_agent_backend(None)
    assert backend is None and "Gemini" in reason
    monkeypatch.setenv("PLIMSOLL_AI_PROVIDER", "groq")  # unknown: ignored
    assert resolve_llm_provider(None).provider_name == "anthropic"


def test_a_pasted_key_still_beats_the_server(monkeypatch):
    monkeypatch.setenv("PLIMSOLL_AI_PROVIDER", "bedrock")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "ABSKreal-looking-token")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    assert resolve_agent_backend(LlmCredentials("anthropic", "k"))[0].provider == "anthropic"
