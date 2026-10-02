"""Claude as the agent's model — on the Claude API, or on Amazon Bedrock's
Claude endpoint (bedrock-mantle, the same Messages API shape).

Claude API: the request in runner.request_params — structured output via
`output_config.format`, automatic caching, and server-side `fallbacks`.

Bedrock: none of those three are offered there, so the request drops them,
keeps the explicit cache breakpoint on the system prompt, and takes the
answer through the `submit_result` tool instead (see runner.py). Thinking
and effort follow the model: Haiku 4.5 accepts neither."""

from __future__ import annotations

from typing import Any, Callable

import anthropic
from pydantic import BaseModel

from backend.services.agent.runner import (
    MAX_TOKENS,
    MODEL_ID,
    SUBMIT_DESCRIPTION,
    SUBMIT_TOOL,
    AgentApiError,
    Effort,
    ToolAnswer,
    ToolCall,
    Turn,
    request_params,
    submit_tool_schema,
)
from backend.services.agent.schemas import strict_json_schema
from backend.services.agent.tools import TOOLS, ToolSpec


def api_error_message(exc: anthropic.APIError, service: str) -> str:
    if isinstance(exc, anthropic.AuthenticationError):
        return f"{service} 的 API 金鑰無效，請到 設定 → 進階 → AI 模型 確認。"
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "這把 API 金鑰沒有使用這個模型的權限。"
    if isinstance(exc, anthropic.RateLimitError):
        return "AI 服務目前忙碌，請稍後再試。"
    if isinstance(exc, anthropic.APIConnectionError):
        return "無法連線到 AI 服務，請確認網路。"
    if isinstance(exc, anthropic.APIStatusError):
        return f"AI 服務回應錯誤（{exc.status_code}），請稍後再試。"
    return "AI 服務發生錯誤，請稍後再試。"


def _error_detail(exc: anthropic.APIError) -> str:
    return f"status={getattr(exc, 'status_code', None)} request_id={getattr(exc, 'request_id', None)}: {exc.message}"


def _final_text(content: list[Any]) -> str | None:
    texts = [b.text for b in content if getattr(b, "type", None) == "text" and getattr(b, "text", "").strip()]
    return texts[-1] if texts else None


def _usage(usage: Any) -> dict[str, int]:
    keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    return {k: getattr(usage, k, None) or 0 for k in keys}


def claude_reasoning_params(model: str, effort: Effort = "medium") -> dict:
    """Adaptive thinking at the run's effort, except on Haiku 4.5, which
    takes neither (a 400 for `effort`, and it only knows budget-style thinking)."""
    if "haiku" in model:
        return {}
    return {"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}}


class AnthropicConversation:
    def __init__(self, create: Callable[..., Any], params: Callable[[list[dict]], dict], *, user_content: str, service: str):
        self._create = create
        self._params = params
        self._service = service
        self._messages: list[dict] = [{"role": "user", "content": user_content}]

    def send(self) -> Turn:
        try:
            response = self._create(**self._params(self._messages))
        except anthropic.APIError as exc:
            raise AgentApiError(api_error_message(exc, self._service), detail=_error_detail(exc)) from exc
        calls = [
            ToolCall(id=b.id, name=b.name, arguments=dict(b.input or {}))
            for b in response.content
            if getattr(b, "type", None) == "tool_use"
        ]
        return Turn(
            stop=response.stop_reason,
            calls=calls,
            text=_final_text(response.content),
            usage=_usage(response.usage),
            model=getattr(response, "model", None),
            raw=response.content,
        )

    def answer_tools(self, turn: Turn, answers: list[ToolAnswer]) -> None:
        results = []
        for call, content, ok in answers:
            entry = {"type": "tool_result", "tool_use_id": call.id, "content": content}
            if not ok:
                entry["is_error"] = True
            results.append(entry)
        self._messages.append({"role": "assistant", "content": turn.raw})
        self._messages.append({"role": "user", "content": results})

    def nudge(self, turn: Turn, text: str) -> None:
        self._messages.append({"role": "assistant", "content": turn.raw})
        self._messages.append({"role": "user", "content": text})


class AnthropicBackend:
    """Claude on the Claude API."""

    provider = "anthropic"
    submits_by_tool = False

    def __init__(self, client: Any):
        self._client = client
        self.model = MODEL_ID

    def start(
        self, *, system: str, user_content: str, output_model: type[BaseModel], tools: list[ToolSpec] = TOOLS, effort: Effort = "medium"
    ) -> AnthropicConversation:
        schema = strict_json_schema(output_model)
        return AnthropicConversation(
            self._client.beta.messages.create,
            lambda messages: request_params(system, messages, schema, tools, effort),
            user_content=user_content,
            service="Claude",
        )


class BedrockClaudeBackend:
    """Claude on Amazon Bedrock (bedrock-mantle)."""

    provider = "bedrock"
    submits_by_tool = True

    def __init__(self, client: Any, model: str):
        self._client = client
        self.model = model

    def start(
        self, *, system: str, user_content: str, output_model: type[BaseModel], tools: list[ToolSpec] = TOOLS, effort: Effort = "medium"
    ) -> AnthropicConversation:
        definitions = [t.definition for t in tools]
        definitions.append({"name": SUBMIT_TOOL, "description": SUBMIT_DESCRIPTION, "input_schema": submit_tool_schema(output_model)})
        base = dict(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=definitions,
            **claude_reasoning_params(self.model, effort),
        )
        return AnthropicConversation(
            self._client.messages.create,
            lambda messages: {**base, "messages": messages},
            user_content=user_content,
            service="Bedrock",
        )
