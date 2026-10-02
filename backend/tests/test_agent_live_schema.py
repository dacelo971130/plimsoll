"""Real-API checks that every AI provider accepts the requests this app
sends. The other tests use fakes, which can't see a provider's own limits —
that gap let the briefing ship with a schema the Claude API always rejected
(400 "The compiled grammar is too large"). Run it after touching schemas.py,
prompts.py, the tool definitions or a provider/backend module.

Spends a few US cents per provider, so it only runs when asked — inside the
container, which already has the server's keys. A provider whose key isn't
set is skipped:
    docker compose exec -T -e PLIMSOLL_LIVE_API=1 plimsoll python -m pytest -q backend/tests/test_agent_live_schema.py

Keys read: ANTHROPIC_API_KEY; GEMINI_API_KEY; AWS_BEARER_TOKEN_BEDROCK with
AWS_REGION (and PLIMSOLL_BEDROCK_MODEL to pick Claude or Nova on Bedrock).
"""

from __future__ import annotations

import os

import anthropic
import pytest

from backend.services.agent.client import resolve_agent_backend
from backend.services.agent.prompts import ANSWER_SYSTEM_PROMPT, BRIEFING_SYSTEM_PROMPT, EXTRAS_SYSTEM_PROMPT
from backend.services.agent.runner import AgentApiError, request_params
from backend.services.agent.schemas import AgentAnswer, BriefingBody, BriefingExtras, strict_json_schema
from backend.services.agent.tools import QUESTION_TOOLS, TOOLS
from backend.services.llm.credentials import LlmCredentials
from backend.services.llm.provider import LlmUnavailable

pytestmark = pytest.mark.skipif(os.environ.get("PLIMSOLL_LIVE_API") != "1", reason="live API check: set PLIMSOLL_LIVE_API=1")

# Compilation happens before generation, so a rejected schema costs nothing;
# one that compiles only has to emit a near-empty result.
FORMAT_ONLY = "這是格式測試。不要呼叫工具，直接輸出符合格式的最小結果：字串留空、陣列留空。"
# Each request with the tools it really carries — Q&A has get_briefing too.
AGENT_REQUESTS = pytest.mark.parametrize(
    ("system", "model", "tools"),
    [(BRIEFING_SYSTEM_PROMPT, BriefingBody, TOOLS), (EXTRAS_SYSTEM_PROMPT, BriefingExtras, TOOLS), (ANSWER_SYSTEM_PROMPT, AgentAnswer, QUESTION_TOOLS)],
    ids=["briefing-body", "briefing-extras", "answer"],
)


def _require(*env_vars: str) -> None:
    missing = [v for v in env_vars if not os.environ.get(v)]
    if missing:
        pytest.skip(f"{', '.join(missing)} not set")


@AGENT_REQUESTS
def test_claude_api_compiles_the_schema(system, model, tools):
    _require("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(timeout=200.0, max_retries=0)
    messages = [{"role": "user", "content": FORMAT_ONLY}]
    try:
        client.beta.messages.create(**request_params(system, messages, strict_json_schema(model), tools))
    except anthropic.BadRequestError as exc:
        pytest.fail(f"{model.__name__} rejected by the API: {exc.message}")


@pytest.mark.parametrize(("provider", "env_vars"), [("gemini", ("GEMINI_API_KEY",)), ("bedrock", ("AWS_BEARER_TOKEN_BEDROCK", "AWS_REGION"))])
@AGENT_REQUESTS
def test_agent_request_accepted(provider, env_vars, system, model, tools):
    _require(*env_vars)
    backend, reason = resolve_agent_backend(LlmCredentials(provider))  # no key in the credentials → the server's
    assert backend is not None, reason
    conversation = backend.start(system=system, user_content=FORMAT_ONLY, output_model=model, tools=tools)
    try:
        conversation.send()
    except AgentApiError as exc:
        pytest.fail(f"{provider} ({backend.model}) rejected the {model.__name__} request: {exc.detail}")


def test_gemini_semantic_layer():
    _require("GEMINI_API_KEY")
    from backend.services.llm.gemini_provider import GeminiProvider

    provider = GeminiProvider(api_key=os.environ["GEMINI_API_KEY"])
    try:
        provider.classify_residual("冷卻水出口溫度不得超過 85°C。", "冷卻水出口溫度不得超過 80°C。")
    except LlmUnavailable as exc:
        pytest.fail(f"Gemini semantic layer ({provider.model_id}) failed: {exc}")


def test_bedrock_semantic_layer():
    _require("AWS_BEARER_TOKEN_BEDROCK", "AWS_REGION")
    from backend.services.llm.bedrock import resolve_bedrock_target
    from backend.services.llm.bedrock_provider import BedrockProvider

    target, reason = resolve_bedrock_target(None)
    assert target is not None, reason
    try:
        BedrockProvider(target).classify_residual("冷卻水出口溫度不得超過 85°C。", "冷卻水出口溫度不得超過 80°C。")
    except LlmUnavailable as exc:
        pytest.fail(f"Bedrock semantic layer ({target.model}) failed: {exc}")
