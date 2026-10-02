"""Amazon Bedrock `LlmProvider` and OCR provider — Claude (`anthropic.*`) or
Amazon Nova (`amazon.nova*`), whichever model the reviewer picked.

Every call is one structured request, as on the other providers, but the
result comes back through a single tool the model is made to call
(`submit_result`, input schema = the Pydantic model's JSON schema) rather
than through a structured-output parameter: Bedrock's Claude endpoint lists
structured outputs as unsupported, and forced tool use is the one mechanism
both Claude and Nova have. The tool input is validated with Pydantic before
anything is returned — a mismatch is LlmUnavailable, never a guess.

No Message Batches on Bedrock: the batch methods raise LlmUnavailable and
`supports_batch` is False, so the chain batch endpoint can say why instead
of failing (backend/api/chains.py)."""

from __future__ import annotations

import base64
import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from backend.models.chain import ParameterPoint
from backend.services.llm.bedrock import BedrockTarget, ConverseClient, ConverseError, claude_client
from backend.services.llm.json_schema import nova_schema
from backend.services.llm.prompts import (
    ALIAS_SUGGEST_SYSTEM_PROMPT,
    DRAWING_REGION_SYSTEM_PROMPT,
    OCR_SYSTEM_PROMPT,
    RESIDUAL_SYSTEM_PROMPT,
    TRAIL_SYSTEM_PROMPT,
)
from backend.services.llm.provider import LlmUnavailable
from backend.services.llm.schemas import (
    AliasCandidateSuggestion,
    DrawingRegionSuggestion,
    ResidualSuggestion,
    TrailAnalysis,
)

SUBMIT_TOOL = "submit_result"
NO_BATCH = "Bedrock 不支援批次語意分析，請改用單次比對的 AI 語意分析。"
# Claude models that reject a forced tool_choice; they get "auto" plus an
# instruction to call the tool instead. Every other model gets the forced
# tool AND an explicit `thinking: disabled` — a forced tool can't be combined
# with thinking, and Sonnet 5 / Opus 5 think by default when it's omitted.
_NO_FORCED_TOOL = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-mythos-5-1")

M = TypeVar("M", bound=BaseModel)
Part = str | tuple[bytes, str]  # text, or (image bytes, media type)


class _BedrockCaller:
    """One forced-tool structured call, on whichever endpoint the model
    lives. Raises `_CallFailed` with a log-safe message."""

    def __init__(self, target: BedrockTarget):
        self.model = target.model
        self.family = target.family
        if self.family == "claude":
            self._claude = claude_client(target)
        else:
            self._converse = ConverseClient(target)

    def call(self, *, system: str, parts: list[Part], schema: type[M], max_tokens: int) -> M:
        raw = self._claude_call(system, parts, schema, max_tokens) if self.family == "claude" else self._nova_call(system, parts, schema, max_tokens)
        try:
            return schema.model_validate(raw)
        except ValidationError as err:
            raise _CallFailed(f"response did not match {schema.__name__}: {err.error_count()} errors") from err

    def _claude_call(self, system: str, parts: list[Part], schema: type[BaseModel], max_tokens: int) -> dict:
        import anthropic

        content: list[dict] = []
        for part in parts:
            if isinstance(part, str):
                content.append({"type": "text", "text": part})
            else:
                data, media_type = part
                content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(data).decode("ascii")}})
        forced = not any(name in self.model for name in _NO_FORCED_TOOL)
        if not forced:
            content.append({"type": "text", "text": f"請呼叫 {SUBMIT_TOOL} 工具交出結果。"})
        try:
            response = self._claude.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": content}],
                tools=[{"name": SUBMIT_TOOL, "description": "交出結果。", "input_schema": schema.model_json_schema()}],
                tool_choice={"type": "tool", "name": SUBMIT_TOOL} if forced else {"type": "auto"},
                **({"thinking": {"type": "disabled"}} if forced else {}),
            )
        except anthropic.APIError as err:
            raise _CallFailed(f"Bedrock Claude call failed: status={getattr(err, 'status_code', None)} {err.message}") from err
        block = next((b for b in response.content if getattr(b, "type", None) == "tool_use" and b.name == SUBMIT_TOOL), None)
        if block is None:
            raise _CallFailed(f"Bedrock Claude did not call {SUBMIT_TOOL} (stop_reason={response.stop_reason})")
        return dict(block.input or {})

    def _nova_call(self, system: str, parts: list[Part], schema: type[BaseModel], max_tokens: int) -> dict:
        content: list[dict] = []
        for part in parts:
            if isinstance(part, str):
                content.append({"text": part})
            else:
                data, media_type = part
                content.append({"image": {"format": media_type.split("/")[-1], "source": {"bytes": base64.b64encode(data).decode("ascii")}}})
        body = {
            "system": [{"text": system}],
            "messages": [{"role": "user", "content": content}],
            "toolConfig": {
                "tools": [{"toolSpec": {"name": SUBMIT_TOOL, "description": "交出結果。", "inputSchema": {"json": nova_schema(schema.model_json_schema())}}}],
                "toolChoice": {"tool": {"name": SUBMIT_TOOL}},
            },
            "inferenceConfig": {"maxTokens": max_tokens},
        }
        try:
            response = self._converse.converse(body)
        except ConverseError as err:
            raise _CallFailed(f"Bedrock Nova call failed: status={err.status} {err}") from err
        blocks = (response.get("output") or {}).get("message", {}).get("content", [])
        tool_use = next((b["toolUse"] for b in blocks if "toolUse" in b and b["toolUse"].get("name") == SUBMIT_TOOL), None)
        if tool_use is None:
            raise _CallFailed(f"Bedrock Nova did not call {SUBMIT_TOOL} (stopReason={response.get('stopReason')})")
        return dict(tool_use.get("input") or {})


class _CallFailed(Exception):
    pass


class BedrockProvider:
    provider_name = "bedrock"
    supports_batch = False

    def __init__(self, target: BedrockTarget):
        self.model_id = target.model
        self._caller = _BedrockCaller(target)

    def _call(self, name: str, *, system: str, parts: list[Part], schema: type[M], max_tokens: int) -> M:
        try:
            return self._caller.call(system=system, parts=parts, schema=schema, max_tokens=max_tokens)
        except _CallFailed as err:
            raise LlmUnavailable(f"{name} failed: {err}") from err

    def classify_residual(self, old_text: str | None, new_text: str | None, *, effort: str = "medium") -> ResidualSuggestion:
        user = json.dumps({"old_text": old_text, "new_text": new_text}, ensure_ascii=False)
        return self._call("classify_residual", system=RESIDUAL_SYSTEM_PROMPT, parts=[user], schema=ResidualSuggestion, max_tokens=1024)

    def analyze_trail(self, series: list[ParameterPoint], *, effort: str = "high") -> TrailAnalysis:
        payload = [{"version": p.version, "value": p.value, "unit": p.unit, "source_text": p.source_text} for p in series]
        user = json.dumps(payload, ensure_ascii=False)
        return self._call("analyze_trail", system=TRAIL_SYSTEM_PROMPT, parts=[user], schema=TrailAnalysis, max_tokens=1536)

    def describe_drawing_region(
        self, old_crop_png: bytes | None, new_crop_png: bytes | None, *, effort: str = "medium"
    ) -> DrawingRegionSuggestion:
        parts: list[Part] = []
        if old_crop_png is not None:
            parts += ["舊版本：", (old_crop_png, "image/png")]
        if new_crop_png is not None:
            parts += ["新版本：", (new_crop_png, "image/png")]
        parts.append("請描述這個區塊看起來是什麼元件，以及新舊版本之間的差異。")
        return self._call("describe_drawing_region", system=DRAWING_REGION_SYSTEM_PROMPT, parts=parts, schema=DrawingRegionSuggestion, max_tokens=1024)

    def suggest_term_alias(self, old_text: str, new_text: str, *, effort: str = "low") -> AliasCandidateSuggestion:
        user = json.dumps({"old_text": old_text, "new_text": new_text}, ensure_ascii=False)
        return self._call("suggest_term_alias", system=ALIAS_SUGGEST_SYSTEM_PROMPT, parts=[user], schema=AliasCandidateSuggestion, max_tokens=512)

    def classify_residual_batch(self, items: list[tuple[str, str | None, str | None]]) -> str:
        raise LlmUnavailable(NO_BATCH)

    def get_batch_status(self, batch_id: str) -> str:
        raise LlmUnavailable(NO_BATCH)

    def fetch_batch_results(self, batch_id: str) -> dict[str, ResidualSuggestion | None]:
        raise LlmUnavailable(NO_BATCH)


class BedrockOcrProvider:
    provider_name = "bedrock-vision"

    def __init__(self, target: BedrockTarget):
        self._caller = _BedrockCaller(target)

    def recognize(self, image_bytes: bytes, *, media_type: str = "image/png", lang_hint: str = "zh-Hant"):
        from backend.services.ocr.provider import OcrUnavailable
        from backend.services.ocr.schemas import OcrPageResult

        parts: list[Part] = [(image_bytes, media_type), f"請轉錄這張圖片上的文字（語言提示：{lang_hint}）。"]
        try:
            return self._caller.call(system=OCR_SYSTEM_PROMPT, parts=parts, schema=OcrPageResult, max_tokens=4096)
        except _CallFailed as err:
            raise OcrUnavailable(f"recognize failed: {err}") from err
