"""Structured-output contract for OCR recognition — mirrors
backend.services.llm.schemas's shape (a plain Pydantic model the SDK
validates the model's output against), not a hand-parsed dict."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OcrPageResult(BaseModel):
    text: str = Field(description="頁面上辨識出的完整文字，保留原始換行與段落結構")
    confidence: float = Field(ge=0.0, le=1.0, description="0-1，對辨識結果整體正確性的信心")
    illegible: bool = Field(
        default=False, description="頁面模糊、解析度不足或內容非文字（例如純圖片）導致無法可靠辨識時設為 true"
    )
