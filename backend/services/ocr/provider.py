"""`OcrProvider` Strategy — same shape and same "opt-in, never a hard
dependency" contract as backend.services.llm.provider.LlmProvider.

Why vision-LLM OCR and not Tesseract/PaddleOCR (§26's original "OSS 優先"
plan): this deployment target has no `tesseract` system binary and
`paddlepaddle` is a multi-GB native dependency most hosting environments
(including this one) don't have — pulling either in would make OCR silently
unavailable in exactly the environments most likely to run this project.
Vision-LLM OCR reuses the SAME provider/key gate the semantic layer already
uses (P5: any of Claude/Gemini/GPT-4o, whichever the user has configured),
so "no key configured" degrades to today's "flag it, don't recognize it"
behavior instead of a broken install.
"""

from __future__ import annotations

import os
from typing import Protocol

from backend.services.ocr.schemas import OcrPageResult


class OcrUnavailable(Exception):
    """Raised by a provider when recognition fails for any reason — always
    caught at the call site and treated as "leave this page's text alone",
    never allowed to fail the surrounding extraction/session flow."""


class OcrProvider(Protocol):
    provider_name: str

    def recognize(self, image_bytes: bytes, *, media_type: str = "image/png", lang_hint: str = "zh-Hant") -> OcrPageResult:
        """Raises OcrUnavailable on failure — never returns a guessed result."""
        ...


def get_ocr_provider() -> OcrProvider | None:
    """Server-env-var path — returns None (never raises) when OCR can't
    run: no provider SDK installed, or none of `ANTHROPIC_API_KEY`/
    `GEMINI_API_KEY`/`OPENAI_API_KEY` is set. A rules-first deployment with
    no AI configured still works, it just keeps flagging scanned pages
    instead of reading them."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic  # noqa: F401
        except ImportError:
            pass
        else:
            from backend.services.ocr.claude_vision_provider import ClaudeVisionOcrProvider

            return ClaudeVisionOcrProvider()
    if os.environ.get("GEMINI_API_KEY"):
        try:
            import google.genai  # noqa: F401
        except ImportError:
            pass
        else:
            from backend.services.llm.gemini_provider import GeminiOcrProvider

            return GeminiOcrProvider(api_key=os.environ["GEMINI_API_KEY"])
    if os.environ.get("OPENAI_API_KEY"):
        try:
            import openai  # noqa: F401
        except ImportError:
            pass
        else:
            from backend.services.llm.openai_provider import OpenAIOcrProvider

            return OpenAIOcrProvider(api_key=os.environ["OPENAI_API_KEY"])
    return None


_REQUEST_SCOPED_PROVIDERS = ("anthropic", "gemini", "openai")


def resolve_ocr_provider(provider_id: str | None = None, api_key: str | None = None) -> OcrProvider | None:
    """Request-scoped counterpart to `get_ocr_provider()` — mirrors
    backend.services.llm.provider.resolve_llm_provider() exactly, using the
    SAME provider_id/api_key pair a request carries (one BYOK selection
    covers both the semantic layer and OCR, since both are "the AI backend
    this user configured", not two independent choices)."""
    if not provider_id or not api_key:
        return get_ocr_provider()
    if provider_id not in _REQUEST_SCOPED_PROVIDERS:
        return None
    if provider_id == "anthropic":
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return None
        from backend.services.ocr.claude_vision_provider import ClaudeVisionOcrProvider

        return ClaudeVisionOcrProvider(api_key=api_key)
    if provider_id == "gemini":
        try:
            import google.genai  # noqa: F401
        except ImportError:
            return None
        from backend.services.llm.gemini_provider import GeminiOcrProvider

        return GeminiOcrProvider(api_key=api_key)
    try:
        import openai  # noqa: F401
    except ImportError:
        return None
    from backend.services.llm.openai_provider import OpenAIOcrProvider

    return OpenAIOcrProvider(api_key=api_key)
