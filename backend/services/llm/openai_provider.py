"""OpenAI `LlmProvider` implementation (P5 multi-provider support). Same
Strategy shape as `AnthropicProvider`/`GeminiProvider`.

Tech choices:
  - `client.chat.completions.parse(response_format=<Pydantic model>)` is
    OpenAI's structured-output convenience — `.choices[0].message.parsed`
    gives back a validated instance, same idea as the other two providers.
  - `reasoning_effort` is OpenAI's equivalent of Anthropic's `effort` /
    Gemini's thinking budget — passed straight through.
  - Batch mode needs a real file upload (`client.files.create(purpose=
    "batch")` with an in-memory JSONL blob), unlike Anthropic/Gemini's
    inline-request batch APIs — `custom_id` here is a genuine per-request
    field (matches Anthropic's shape), so no metadata-dict workaround like
    Gemini needs.
"""

from __future__ import annotations

import base64
import json
from io import BytesIO

import openai

from backend.models.chain import ParameterPoint
from backend.services.llm.prompts import (
    ALIAS_SUGGEST_SYSTEM_PROMPT as _ALIAS_SUGGEST_SYSTEM_PROMPT,
    DRAWING_REGION_SYSTEM_PROMPT as _DRAWING_REGION_SYSTEM_PROMPT,
    OCR_SYSTEM_PROMPT as _OCR_SYSTEM_PROMPT,
    RESIDUAL_SYSTEM_PROMPT as _RESIDUAL_SYSTEM_PROMPT,
    TRAIL_SYSTEM_PROMPT as _TRAIL_SYSTEM_PROMPT,
)
from backend.services.llm.provider import LlmUnavailable
from backend.services.llm.schemas import (
    AliasCandidateSuggestion,
    DrawingRegionSuggestion,
    ResidualSuggestion,
    TrailAnalysis,
)

MODEL_ID = "gpt-4o"


class OpenAIProvider:
    model_id = MODEL_ID
    provider_name = "openai"

    def __init__(self, *, api_key: str) -> None:
        self._client = openai.OpenAI(api_key=api_key)

    def _parse(self, *, system_prompt: str, user_content, schema: type, effort: str):
        try:
            result = self._client.chat.completions.parse(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                reasoning_effort=effort if effort in ("low", "medium", "high") else "medium",
                response_format=schema,
            )
        except openai.APIError as err:
            raise LlmUnavailable(f"OpenAI call failed: {err}") from err
        parsed = result.choices[0].message.parsed
        if parsed is None:
            raise LlmUnavailable(f"OpenAI response did not match {schema.__name__} schema")
        return parsed

    def classify_residual(
        self, old_text: str | None, new_text: str | None, *, effort: str = "medium"
    ) -> ResidualSuggestion:
        user_content = json.dumps({"old_text": old_text, "new_text": new_text}, ensure_ascii=False)
        return self._parse(
            system_prompt=_RESIDUAL_SYSTEM_PROMPT, user_content=user_content, schema=ResidualSuggestion, effort=effort
        )

    def analyze_trail(self, series: list[ParameterPoint], *, effort: str = "high") -> TrailAnalysis:
        payload = [
            {"version": p.version, "value": p.value, "unit": p.unit, "source_text": p.source_text} for p in series
        ]
        user_content = json.dumps(payload, ensure_ascii=False)
        return self._parse(
            system_prompt=_TRAIL_SYSTEM_PROMPT, user_content=user_content, schema=TrailAnalysis, effort=effort
        )

    def describe_drawing_region(
        self, old_crop_png: bytes | None, new_crop_png: bytes | None, *, effort: str = "medium"
    ) -> DrawingRegionSuggestion:
        content: list[dict] = []
        if old_crop_png is not None:
            content.append({"type": "text", "text": "舊版本："})
            content.append(_image_content_part(old_crop_png))
        if new_crop_png is not None:
            content.append({"type": "text", "text": "新版本："})
            content.append(_image_content_part(new_crop_png))
        content.append({"type": "text", "text": "請描述這個區塊看起來是什麼元件，以及新舊版本之間的差異。"})
        return self._parse(
            system_prompt=_DRAWING_REGION_SYSTEM_PROMPT, user_content=content, schema=DrawingRegionSuggestion, effort=effort
        )

    def suggest_term_alias(self, old_text: str, new_text: str, *, effort: str = "low") -> AliasCandidateSuggestion:
        user_content = json.dumps({"old_text": old_text, "new_text": new_text}, ensure_ascii=False)
        return self._parse(
            system_prompt=_ALIAS_SUGGEST_SYSTEM_PROMPT, user_content=user_content, schema=AliasCandidateSuggestion, effort=effort
        )

    def classify_residual_batch(self, items: list[tuple[str, str | None, str | None]]) -> str:
        """OpenAI's Batch API needs a real file upload — no inline-request
        shortcut like Anthropic/Gemini — so this builds an in-memory JSONL
        blob (never touches local disk) and uploads it before creating the
        batch job."""
        lines = []
        for custom_id, old_text, new_text in items:
            body = {
                "model": self.model_id,
                "messages": [
                    {"role": "system", "content": _RESIDUAL_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps({"old_text": old_text, "new_text": new_text}, ensure_ascii=False),
                    },
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "ResidualSuggestion",
                        "schema": ResidualSuggestion.model_json_schema(),
                        "strict": True,
                    },
                },
            }
            lines.append(json.dumps({"custom_id": custom_id, "method": "POST", "url": "/v1/chat/completions", "body": body}, ensure_ascii=False))
        jsonl_blob = ("\n".join(lines) + "\n").encode("utf-8")

        try:
            uploaded = self._client.files.create(file=("batch.jsonl", BytesIO(jsonl_blob)), purpose="batch")
            batch = self._client.batches.create(
                input_file_id=uploaded.id, endpoint="/v1/chat/completions", completion_window="24h"
            )
        except openai.APIError as err:
            raise LlmUnavailable(f"classify_residual_batch failed: {err}") from err
        return batch.id

    def get_batch_status(self, batch_id: str) -> str:
        try:
            batch = self._client.batches.retrieve(batch_id)
        except openai.APIError as err:
            raise LlmUnavailable(f"get_batch_status failed: {err}") from err
        if batch.status in ("completed", "failed", "expired", "cancelled"):
            return "ended"
        return "in_progress"

    def fetch_batch_results(self, batch_id: str) -> dict[str, ResidualSuggestion | None]:
        try:
            batch = self._client.batches.retrieve(batch_id)
            if batch.output_file_id is None:
                return {}
            content = self._client.files.content(batch.output_file_id)
        except openai.APIError as err:
            raise LlmUnavailable(f"fetch_batch_results failed: {err}") from err

        out: dict[str, ResidualSuggestion | None] = {}
        for line in content.text.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            custom_id = row["custom_id"]
            body = (row.get("response") or {}).get("body")
            if row.get("error") or not body:
                out[custom_id] = None
                continue
            try:
                text = body["choices"][0]["message"]["content"]
                out[custom_id] = ResidualSuggestion.model_validate_json(text)
            except (KeyError, IndexError, ValueError):
                out[custom_id] = None
        return out


def _image_content_part(png_bytes: bytes) -> dict:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}


class OpenAIOcrProvider:
    """Mirrors backend.services.ocr.claude_vision_provider.ClaudeVisionOcrProvider."""

    provider_name = "openai-vision"

    def __init__(self, *, api_key: str) -> None:
        self._client = openai.OpenAI(api_key=api_key)

    def recognize(self, image_bytes: bytes, *, media_type: str = "image/png", lang_hint: str = "zh-Hant"):
        from backend.services.ocr.provider import OcrUnavailable
        from backend.services.ocr.schemas import OcrPageResult

        b64 = base64.b64encode(image_bytes).decode("ascii")
        try:
            result = self._client.chat.completions.parse(
                model=MODEL_ID,
                messages=[
                    {"role": "system", "content": _OCR_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}},
                            {"type": "text", "text": f"請轉錄這張圖片上的文字（語言提示：{lang_hint}）。"},
                        ],
                    },
                ],
                response_format=OcrPageResult,
            )
        except openai.APIError as err:
            raise OcrUnavailable(f"recognize failed: {err}") from err
        parsed = result.choices[0].message.parsed
        if parsed is None:
            raise OcrUnavailable("recognize: response did not match OcrPageResult schema")
        return parsed
