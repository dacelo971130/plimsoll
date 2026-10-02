"""Amazon Nova on Bedrock as the agent's model, over the Converse API.

Shape notes, per AWS's Nova 2 docs: tools are `toolSpec`s whose schemas are
flattened (json_schema.nova_schema — Nova documents no `$ref`/`anyOf`); the
answer comes in through the `submit_result` tool (Nova 2 Lite lists
structured outputs as unsupported); reasoning is on at medium effort and the
assistant message — reasoning blocks included — goes back verbatim, as AWS's
own agent loop does; a `cachePoint` after the system prompt lets Bedrock
cache that repeated prefix (Nova caches system and messages, not tools)."""

from __future__ import annotations

from pydantic import BaseModel

from backend.services.agent.runner import (
    MAX_TOKENS,
    SUBMIT_DESCRIPTION,
    SUBMIT_TOOL,
    AgentApiError,
    Effort,
    ToolAnswer,
    ToolCall,
    Turn,
    submit_tool_schema,
)
from backend.services.agent.tools import TOOLS, ToolSpec
from backend.services.llm.bedrock import ConverseClient, ConverseError, converse_error_message
from backend.services.llm.json_schema import nova_schema

_REFUSALS = ("guardrail_intervened", "content_filtered")


def _tool_spec(name: str, description: str, schema: dict) -> dict:
    return {"toolSpec": {"name": name, "description": description, "inputSchema": {"json": nova_schema(schema)}}}


class ConverseConversation:
    def __init__(self, client: ConverseClient, base: dict, *, user_content: str):
        self._client = client
        self._base = base
        self._messages: list[dict] = [{"role": "user", "content": [{"text": user_content}]}]

    def send(self) -> Turn:
        try:
            response = self._client.converse({**self._base, "messages": self._messages})
        except ConverseError as exc:
            raise AgentApiError(converse_error_message(exc), detail=f"status={exc.status} type={exc.error_type}: {exc}") from exc
        message = (response.get("output") or {}).get("message") or {"role": "assistant", "content": []}
        blocks = message.get("content") or []
        calls = [
            ToolCall(id=b["toolUse"]["toolUseId"], name=b["toolUse"]["name"], arguments=dict(b["toolUse"].get("input") or {}))
            for b in blocks
            if "toolUse" in b
        ]
        texts = [b["text"] for b in blocks if isinstance(b.get("text"), str) and b["text"].strip()]
        stop = response.get("stopReason") or ""
        usage = response.get("usage") or {}
        return Turn(
            stop="refusal" if stop in _REFUSALS else stop,
            calls=calls,
            text=texts[-1] if texts else None,
            usage={
                "input_tokens": usage.get("inputTokens", 0),
                "output_tokens": usage.get("outputTokens", 0),
                "cache_read_input_tokens": usage.get("cacheReadInputTokens", 0),
                "cache_creation_input_tokens": usage.get("cacheWriteInputTokens", 0),
            },
            model=self._client.model,
            raw=message,
        )

    def answer_tools(self, turn: Turn, answers: list[ToolAnswer]) -> None:
        results = [
            {"toolResult": {"toolUseId": call.id, "content": [{"text": content}], "status": "success" if ok else "error"}}
            for call, content, ok in answers
        ]
        self._messages.append(turn.raw)
        self._messages.append({"role": "user", "content": results})

    def nudge(self, turn: Turn, text: str) -> None:
        self._messages.append(turn.raw)
        self._messages.append({"role": "user", "content": [{"text": text}]})


class ConverseBackend:
    provider = "bedrock"
    submits_by_tool = True

    def __init__(self, client: ConverseClient):
        self._client = client
        self.model = client.model

    def start(
        self, *, system: str, user_content: str, output_model: type[BaseModel], tools: list[ToolSpec] = TOOLS, effort: Effort = "medium"
    ) -> ConverseConversation:
        specs = [_tool_spec(t.name, t.description, t.input_schema) for t in tools]
        specs.append(_tool_spec(SUBMIT_TOOL, SUBMIT_DESCRIPTION, submit_tool_schema(output_model)))
        base = {
            "system": [{"text": system}, {"cachePoint": {"type": "default"}}],
            "toolConfig": {"tools": specs, "toolChoice": {"auto": {}}},
            "inferenceConfig": {"maxTokens": MAX_TOKENS},
            "additionalModelRequestFields": {"reasoningConfig": {"type": "enabled", "maxReasoningEffort": effort}},
        }
        return ConverseConversation(self._client, base, user_content=user_content)
