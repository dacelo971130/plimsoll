"""Google Gemini as the agent's model (google-genai, generate_content with a
manual function-calling loop).

Per Google's docs as of 2026-10: the Pro tier is `gemini-3.1-pro-preview`
(a Preview model — PLIMSOLL_GEMINI_AGENT_MODEL overrides it when Google
renames or retires it); thinking can't be turned off on it, so it runs at
`thinking_level="medium"`, like Claude's effort; automatic function calling
is disabled so every call goes through runner.py's limits; the model's
`Content` goes back into history unchanged, which is what keeps Gemini's
thought signatures valid between turns; each FunctionResponse carries the
id of the call it answers. The answer comes in through the `submit_result`
function — structured output combined with function calling is still a
Preview feature there."""

from __future__ import annotations

import os

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
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
from backend.services.llm.json_schema import inline_schema

DEFAULT_MODEL = "gemini-3.1-pro-preview"
_REFUSALS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY", "IMAGE_PROHIBITED_CONTENT"}


def gemini_error_message(exc: genai_errors.APIError) -> str:
    code = getattr(exc, "code", None)
    if code in (401, 403):
        return "Gemini 的 API 金鑰無效，或沒有使用這個模型的權限，請到 設定 → 進階 → AI 模型 確認。"
    if code == 429:
        return "AI 服務目前忙碌，請稍後再試。"
    return f"AI 服務回應錯誤（{code}），請稍後再試。"


def _declaration(name: str, description: str, schema: dict) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(name=name, description=description, parameters_json_schema=inline_schema(schema))


class GeminiConversation:
    def __init__(self, client: genai.Client, model: str, config: types.GenerateContentConfig, *, user_content: str):
        self._client = client
        self._model = model
        self._config = config
        self._contents: list[types.Content] = [types.Content(role="user", parts=[types.Part(text=user_content)])]

    def send(self) -> Turn:
        try:
            response = self._client.models.generate_content(model=self._model, contents=self._contents, config=self._config)
        except genai_errors.APIError as exc:
            raise AgentApiError(gemini_error_message(exc), detail=f"code={exc.code} status={exc.status}: {exc.message}") from exc
        meta = response.usage_metadata
        prompt = getattr(meta, "prompt_token_count", None) or 0
        cached = getattr(meta, "cached_content_token_count", None) or 0
        usage = {
            "input_tokens": prompt - cached,
            "cache_read_input_tokens": cached,
            "output_tokens": (getattr(meta, "candidates_token_count", None) or 0) + (getattr(meta, "thoughts_token_count", None) or 0),
            "cache_creation_input_tokens": 0,
        }
        model = getattr(response, "model_version", None) or self._model
        candidate = (response.candidates or [None])[0]
        if candidate is None or candidate.content is None:
            blocked = getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
            return Turn(stop="refusal" if blocked else "empty", calls=[], text=None, usage=usage, model=model)
        parts = candidate.content.parts or []
        calls = [
            ToolCall(id=p.function_call.id or "", name=p.function_call.name, arguments=dict(p.function_call.args or {}))
            for p in parts
            if p.function_call is not None
        ]
        texts = [p.text for p in parts if p.text and not p.thought and p.text.strip()]
        finish = str(getattr(candidate.finish_reason, "value", candidate.finish_reason) or "STOP")
        stop = {"STOP": "end_turn", "MAX_TOKENS": "max_tokens"}.get(finish, "refusal" if finish in _REFUSALS else finish)
        return Turn(stop=stop, calls=calls, text=texts[-1] if texts else None, usage=usage, model=model, raw=candidate.content)

    def answer_tools(self, turn: Turn, answers: list[ToolAnswer]) -> None:
        parts = [
            types.Part(
                function_response=types.FunctionResponse(
                    id=call.id or None, name=call.name, response={"result": content} if ok else {"error": content}
                )
            )
            for call, content, ok in answers
        ]
        self._contents.append(turn.raw)
        self._contents.append(types.Content(role="user", parts=parts))

    def nudge(self, turn: Turn, text: str) -> None:
        self._contents.append(turn.raw)
        self._contents.append(types.Content(role="user", parts=[types.Part(text=text)]))


class GeminiBackend:
    provider = "gemini"
    submits_by_tool = True

    def __init__(self, *, api_key: str, client: genai.Client | None = None):
        self._client = client or genai.Client(api_key=api_key)
        self.model = os.environ.get("PLIMSOLL_GEMINI_AGENT_MODEL") or DEFAULT_MODEL

    def start(
        self, *, system: str, user_content: str, output_model: type[BaseModel], tools: list[ToolSpec] = TOOLS, effort: Effort = "medium"
    ) -> GeminiConversation:
        declarations = [_declaration(t.name, t.description, t.input_schema) for t in tools]
        declarations.append(_declaration(SUBMIT_TOOL, SUBMIT_DESCRIPTION, submit_tool_schema(output_model)))
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            thinking_config=types.ThinkingConfig(thinking_level=effort),
            max_output_tokens=MAX_TOKENS,
        )
        return GeminiConversation(self._client, self.model, config, user_content=user_content)
