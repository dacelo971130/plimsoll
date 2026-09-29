"""Direct-Claude-API `LlmProvider` implementation (W7). Bedrock is §25's
eventual second adapter — swapping in `AnthropicBedrock` only changes client
construction, since `messages.parse()` is the same call either way; not done
here because nothing in this codebase needs it yet (YAGNI over
speculative plumbing).

Tech choices, per docs/redesign/plimsoll-improvement-plan.html §03's table —
each one is a documented gotcha, not a style preference:
  - `client.messages.parse(output_format=<Pydantic model>)`, not manual
    `json.loads()` — the SDK validates/retries on schema mismatch for us.
  - `thinking={"type": "adaptive"}` — NOT `budget_tokens`, which 400s on
    Opus 5.
  - `effort` lives inside `output_config`, not as a top-level kwarg.
  - `cache_control` on the system prompt — every residual call repeats the
    same instructions, so this is the ~10x cost lever, not a nice-to-have.
"""

from __future__ import annotations

import base64
import json
import os

import anthropic

from backend.models.chain import ParameterPoint
from backend.services.llm.prompts import (
    ALIAS_SUGGEST_SYSTEM_PROMPT as _ALIAS_SUGGEST_SYSTEM_PROMPT,
    DRAWING_REGION_SYSTEM_PROMPT as _DRAWING_REGION_SYSTEM_PROMPT,
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

MODEL_ID = "claude-opus-5"


def _system_with_cache(prompt: str) -> list[dict]:
    return [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]


class AnthropicProvider:
    model_id = MODEL_ID
    provider_name = "anthropic"

    def __init__(self, *, api_key: str | None = None) -> None:
        self._client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])

    def classify_residual(
        self, old_text: str | None, new_text: str | None, *, effort: str = "medium"
    ) -> ResidualSuggestion:
        user_content = json.dumps({"old_text": old_text, "new_text": new_text}, ensure_ascii=False)
        try:
            result = self._client.messages.parse(
                model=self.model_id,
                max_tokens=1024,
                system=_system_with_cache(_RESIDUAL_SYSTEM_PROMPT),
                messages=[{"role": "user", "content": user_content}],
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                output_format=ResidualSuggestion,
            )
        except anthropic.AnthropicError as err:
            raise LlmUnavailable(f"classify_residual failed: {err}") from err
        if result.parsed_output is None:
            raise LlmUnavailable("classify_residual: response did not match ResidualSuggestion schema")
        return result.parsed_output

    def analyze_trail(self, series: list[ParameterPoint], *, effort: str = "high") -> TrailAnalysis:
        payload = [
            {"version": p.version, "value": p.value, "unit": p.unit, "source_text": p.source_text} for p in series
        ]
        user_content = json.dumps(payload, ensure_ascii=False)
        try:
            result = self._client.messages.parse(
                model=self.model_id,
                max_tokens=1536,
                system=_system_with_cache(_TRAIL_SYSTEM_PROMPT),
                messages=[{"role": "user", "content": user_content}],
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                output_format=TrailAnalysis,
            )
        except anthropic.AnthropicError as err:
            raise LlmUnavailable(f"analyze_trail failed: {err}") from err
        if result.parsed_output is None:
            raise LlmUnavailable("analyze_trail: response did not match TrailAnalysis schema")
        return result.parsed_output

    def describe_drawing_region(
        self, old_crop_png: bytes | None, new_crop_png: bytes | None, *, effort: str = "medium"
    ) -> DrawingRegionSuggestion:
        content: list[dict] = []
        if old_crop_png is not None:
            content.append({"type": "text", "text": "舊版本："})
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(old_crop_png).decode("ascii")},
                }
            )
        if new_crop_png is not None:
            content.append({"type": "text", "text": "新版本："})
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(new_crop_png).decode("ascii")},
                }
            )
        content.append({"type": "text", "text": "請描述這個區塊看起來是什麼元件，以及新舊版本之間的差異。"})

        try:
            result = self._client.messages.parse(
                model=self.model_id,
                max_tokens=1024,
                system=_system_with_cache(_DRAWING_REGION_SYSTEM_PROMPT),
                messages=[{"role": "user", "content": content}],
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                output_format=DrawingRegionSuggestion,
            )
        except anthropic.AnthropicError as err:
            raise LlmUnavailable(f"describe_drawing_region failed: {err}") from err
        if result.parsed_output is None:
            raise LlmUnavailable("describe_drawing_region: response did not match DrawingRegionSuggestion schema")
        return result.parsed_output

    def suggest_term_alias(self, old_text: str, new_text: str, *, effort: str = "low") -> AliasCandidateSuggestion:
        user_content = json.dumps({"old_text": old_text, "new_text": new_text}, ensure_ascii=False)
        try:
            result = self._client.messages.parse(
                model=self.model_id,
                max_tokens=512,
                system=_system_with_cache(_ALIAS_SUGGEST_SYSTEM_PROMPT),
                messages=[{"role": "user", "content": user_content}],
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                output_format=AliasCandidateSuggestion,
            )
        except anthropic.AnthropicError as err:
            raise LlmUnavailable(f"suggest_term_alias failed: {err}") from err
        if result.parsed_output is None:
            raise LlmUnavailable("suggest_term_alias: response did not match AliasCandidateSuggestion schema")
        return result.parsed_output

    def classify_residual_batch(self, items: list[tuple[str, str | None, str | None]]) -> str:
        """P5 Message Batches. The raw Batch API request shape
        (`messages.batches.create`) mirrors `messages.create()`'s params,
        NOT `messages.parse()`'s convenience wrapper — there's no
        `output_format` here, so structured output is requested the way
        `messages.parse()` itself does it under the hood: a JSON-schema
        `output_config.format` derived straight from the Pydantic model via
        `model_json_schema()`, parsed back with `model_validate_json()` in
        `fetch_batch_results()` below."""
        requests = [
            {
                "custom_id": custom_id,
                "params": {
                    "model": self.model_id,
                    "max_tokens": 1024,
                    "system": _system_with_cache(_RESIDUAL_SYSTEM_PROMPT),
                    "messages": [
                        {
                            "role": "user",
                            "content": json.dumps({"old_text": old_text, "new_text": new_text}, ensure_ascii=False),
                        }
                    ],
                    "output_config": {
                        "effort": "medium",
                        "format": {"type": "json_schema", "schema": ResidualSuggestion.model_json_schema()},
                    },
                },
            }
            for custom_id, old_text, new_text in items
        ]
        try:
            batch = self._client.messages.batches.create(requests=requests)
        except anthropic.AnthropicError as err:
            raise LlmUnavailable(f"classify_residual_batch failed: {err}") from err
        return batch.id

    def get_batch_status(self, batch_id: str) -> str:
        try:
            batch = self._client.messages.batches.retrieve(batch_id)
        except anthropic.AnthropicError as err:
            raise LlmUnavailable(f"get_batch_status failed: {err}") from err
        return batch.processing_status

    def fetch_batch_results(self, batch_id: str) -> dict[str, ResidualSuggestion | None]:
        try:
            results = self._client.messages.batches.results(batch_id)
        except anthropic.AnthropicError as err:
            raise LlmUnavailable(f"fetch_batch_results failed: {err}") from err

        out: dict[str, ResidualSuggestion | None] = {}
        for item in results:
            if item.result.type != "succeeded":
                out[item.custom_id] = None  # errored/canceled/expired — treated like a single-call LlmUnavailable
                continue
            text_block = next((c for c in item.result.message.content if c.type == "text"), None)
            if text_block is None:
                out[item.custom_id] = None
                continue
            try:
                out[item.custom_id] = ResidualSuggestion.model_validate_json(text_block.text)
            except ValueError:
                out[item.custom_id] = None  # malformed response — never guess, same rule as the sync path
        return out
