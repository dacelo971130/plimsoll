"""Claude-Vision-backed `OcrProvider` implementation. Same `messages.parse()`
+ Pydantic `output_format` pattern as backend.services.llm.anthropic_provider
— the only difference is an image content block instead of a plain JSON
string user message."""

from __future__ import annotations

import base64
import os

import anthropic

from backend.services.llm.prompts import OCR_SYSTEM_PROMPT as _OCR_SYSTEM_PROMPT
from backend.services.ocr.provider import OcrUnavailable
from backend.services.ocr.schemas import OcrPageResult

MODEL_ID = "claude-opus-5"


class ClaudeVisionOcrProvider:
    provider_name = "anthropic-vision"

    def __init__(self, *, api_key: str | None = None) -> None:
        self._client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])

    def recognize(
        self, image_bytes: bytes, *, media_type: str = "image/png", lang_hint: str = "zh-Hant"
    ) -> OcrPageResult:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        try:
            result = self._client.messages.parse(
                model=MODEL_ID,
                max_tokens=4096,
                system=[{"type": "text", "text": _OCR_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {"type": "base64", "media_type": media_type, "data": b64},
                            },
                            {
                                "type": "text",
                                "text": f"請轉錄這張圖片上的文字（語言提示：{lang_hint}）。",
                            },
                        ],
                    }
                ],
                output_config={"effort": "medium"},
                output_format=OcrPageResult,
            )
        except anthropic.AnthropicError as err:
            raise OcrUnavailable(f"recognize failed: {err}") from err
        if result.parsed_output is None:
            raise OcrUnavailable("recognize: response did not match OcrPageResult schema")
        return result.parsed_output
