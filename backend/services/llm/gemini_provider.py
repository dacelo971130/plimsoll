"""Google Gemini `LlmProvider` implementation (P5 multi-provider support).
Same Strategy shape as `AnthropicProvider` — this file exists so a user who
picks "Gemini" in Settings → AI 模型 gets a REAL, fully-working provider,
not a dropdown option that silently does nothing (see `resolve_llm_provider`
in provider.py for how a request's `X-Llm-Provider`/`X-Llm-Api-Key` headers
route here).

Tech choices, mirroring anthropic_provider.py's tech-choices docstring:
  - `client.models.generate_content(config=GenerateContentConfig(response_schema=<Pydantic model>))`
    is Gemini's structured-output convenience — `response.parsed` gives back
    a validated instance, same idea as Anthropic's `messages.parse()`.
  - Batch mode (`client.batches.create(src=[InlinedRequest, ...])`) has no
    `custom_id` field like Anthropic/OpenAI's batch APIs — correlation is
    via the free-form `metadata: dict[str,str]` field instead, echoed back
    on each `InlinedResponse`.
  - Batch results are parsed by hand (`ResidualSuggestion.model_validate_json`
    on `response.text`), not via `.parsed` — unconfirmed whether the SDK
    populates `.parsed` on batch-deserialized responses the same way it does
    for a live `generate_content()` call, so this never depends on it.
"""

from __future__ import annotations

import json

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

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

MODEL_ID = "gemini-2.5-flash"


class GeminiProvider:
    model_id = MODEL_ID
    provider_name = "gemini"

    def __init__(self, *, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    def _generate(self, *, system_prompt: str, contents, schema: type, effort: str):
        try:
            response = self._client.models.generate_content(
                model=self.model_id,
                contents=contents,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=schema,
                    thinking_config=genai_types.ThinkingConfig(thinking_budget=-1),  # -1 = dynamic/adaptive
                ),
            )
        except genai_errors.APIError as err:
            raise LlmUnavailable(f"Gemini call failed: {err}") from err
        if response.parsed is None:
            raise LlmUnavailable(f"Gemini response did not match {schema.__name__} schema")
        return response.parsed

    def classify_residual(
        self, old_text: str | None, new_text: str | None, *, effort: str = "medium"
    ) -> ResidualSuggestion:
        contents = json.dumps({"old_text": old_text, "new_text": new_text}, ensure_ascii=False)
        return self._generate(
            system_prompt=_RESIDUAL_SYSTEM_PROMPT, contents=contents, schema=ResidualSuggestion, effort=effort
        )

    def analyze_trail(self, series: list[ParameterPoint], *, effort: str = "high") -> TrailAnalysis:
        payload = [
            {"version": p.version, "value": p.value, "unit": p.unit, "source_text": p.source_text} for p in series
        ]
        contents = json.dumps(payload, ensure_ascii=False)
        return self._generate(system_prompt=_TRAIL_SYSTEM_PROMPT, contents=contents, schema=TrailAnalysis, effort=effort)

    def describe_drawing_region(
        self, old_crop_png: bytes | None, new_crop_png: bytes | None, *, effort: str = "medium"
    ) -> DrawingRegionSuggestion:
        parts: list = []
        if old_crop_png is not None:
            parts.append("舊版本：")
            parts.append(genai_types.Part.from_bytes(data=old_crop_png, mime_type="image/png"))
        if new_crop_png is not None:
            parts.append("新版本：")
            parts.append(genai_types.Part.from_bytes(data=new_crop_png, mime_type="image/png"))
        parts.append("請描述這個區塊看起來是什麼元件，以及新舊版本之間的差異。")
        return self._generate(
            system_prompt=_DRAWING_REGION_SYSTEM_PROMPT, contents=parts, schema=DrawingRegionSuggestion, effort=effort
        )

    def suggest_term_alias(self, old_text: str, new_text: str, *, effort: str = "low") -> AliasCandidateSuggestion:
        contents = json.dumps({"old_text": old_text, "new_text": new_text}, ensure_ascii=False)
        return self._generate(
            system_prompt=_ALIAS_SUGGEST_SYSTEM_PROMPT, contents=contents, schema=AliasCandidateSuggestion, effort=effort
        )

    def classify_residual_batch(self, items: list[tuple[str, str | None, str | None]]) -> str:
        """Gemini's Batch API has no `custom_id` field (unlike Anthropic/
        OpenAI) — correlation rides in the free-form `metadata` dict
        instead, echoed back on each `InlinedResponse` in `fetch_batch_results`."""
        requests = [
            genai_types.InlinedRequest(
                model=self.model_id,
                contents=json.dumps({"old_text": old_text, "new_text": new_text}, ensure_ascii=False),
                metadata={"custom_id": custom_id},
                config=genai_types.GenerateContentConfig(
                    system_instruction=_RESIDUAL_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=ResidualSuggestion,
                ),
            )
            for custom_id, old_text, new_text in items
        ]
        try:
            job = self._client.batches.create(model=self.model_id, src=requests)
        except genai_errors.APIError as err:
            raise LlmUnavailable(f"classify_residual_batch failed: {err}") from err
        return job.name

    def get_batch_status(self, batch_id: str) -> str:
        try:
            job = self._client.batches.get(name=batch_id)
        except genai_errors.APIError as err:
            raise LlmUnavailable(f"get_batch_status failed: {err}") from err
        state = job.state.value if job.state is not None else "JOB_STATE_UNSPECIFIED"
        # Normalize to the same three-way vocabulary batch_jobs.py expects
        # from every provider ("ended" once nothing more will change).
        if state in ("JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED", "JOB_STATE_PARTIALLY_SUCCEEDED"):
            return "ended"
        return "in_progress"

    def fetch_batch_results(self, batch_id: str) -> dict[str, ResidualSuggestion | None]:
        try:
            job = self._client.batches.get(name=batch_id)
        except genai_errors.APIError as err:
            raise LlmUnavailable(f"fetch_batch_results failed: {err}") from err

        out: dict[str, ResidualSuggestion | None] = {}
        inlined = job.dest.inlined_responses if job.dest is not None else None
        for item in inlined or []:
            custom_id = (item.metadata or {}).get("custom_id")
            if custom_id is None:
                continue
            if item.error is not None or item.response is None:
                out[custom_id] = None
                continue
            try:
                out[custom_id] = ResidualSuggestion.model_validate_json(item.response.text)
            except ValueError:
                out[custom_id] = None
        return out


def _ocr_prompt_contents(image_bytes: bytes, media_type: str, lang_hint: str) -> list:
    return [
        genai_types.Part.from_bytes(data=image_bytes, mime_type=media_type),
        f"請轉錄這張圖片上的文字（語言提示：{lang_hint}）。",
    ]


class GeminiOcrProvider:
    """Mirrors backend.services.ocr.claude_vision_provider.ClaudeVisionOcrProvider."""

    provider_name = "gemini-vision"

    def __init__(self, *, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    def recognize(self, image_bytes: bytes, *, media_type: str = "image/png", lang_hint: str = "zh-Hant"):
        from backend.services.ocr.provider import OcrUnavailable
        from backend.services.ocr.schemas import OcrPageResult

        try:
            response = self._client.models.generate_content(
                model=MODEL_ID,
                contents=_ocr_prompt_contents(image_bytes, media_type, lang_hint),
                config=genai_types.GenerateContentConfig(
                    system_instruction=_OCR_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=OcrPageResult,
                ),
            )
        except genai_errors.APIError as err:
            raise OcrUnavailable(f"recognize failed: {err}") from err
        if response.parsed is None:
            raise OcrUnavailable("recognize: response did not match OcrPageResult schema")
        return response.parsed
