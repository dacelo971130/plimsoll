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

from typing import Protocol

from backend.services.llm.credentials import NO_CREDENTIALS, PROVIDER_IDS, LlmCredentials, server_key, server_providers
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
    `GEMINI_API_KEY`/`OPENAI_API_KEY`/`AWS_BEARER_TOKEN_BEDROCK` is set. A
    rules-first deployment with no AI configured still works, it just keeps
    flagging scanned pages instead of reading them."""
    for provider_id in server_providers():
        provider = _server_side(provider_id)
        if provider is not None:
            return provider
    return None


def _server_side(provider_id: str) -> OcrProvider | None:
    if provider_id == "bedrock":
        return _bedrock_ocr(NO_CREDENTIALS)
    try:
        if provider_id == "anthropic":
            from backend.services.ocr.claude_vision_provider import ClaudeVisionOcrProvider

            return ClaudeVisionOcrProvider(api_key=server_key("anthropic"))
        if provider_id == "gemini":
            from backend.services.llm.gemini_provider import GeminiOcrProvider

            return GeminiOcrProvider(api_key=server_key("gemini"))
        from backend.services.llm.openai_provider import OpenAIOcrProvider

        return OpenAIOcrProvider(api_key=server_key("openai"))
    except ImportError:
        return None


def _bedrock_ocr(creds: LlmCredentials) -> OcrProvider | None:
    from backend.services.llm.bedrock import resolve_bedrock_target
    from backend.services.llm.bedrock_provider import BedrockOcrProvider

    target, _reason = resolve_bedrock_target(creds)
    return BedrockOcrProvider(target) if target is not None else None


def resolve_ocr_provider(creds: LlmCredentials | None = None) -> OcrProvider | None:
    """Request-scoped counterpart to `get_ocr_provider()` — mirrors
    backend.services.llm.provider.resolve_llm_provider() exactly, using the
    SAME credentials a request carries (one BYOK selection covers both the
    semantic layer and OCR, since both are "the AI backend this user
    configured", not two independent choices)."""
    creds = creds or NO_CREDENTIALS
    if not creds.explicit:
        return get_ocr_provider()
    provider_id, api_key = creds.provider_id, creds.api_key
    if provider_id not in PROVIDER_IDS:
        return None
    if provider_id == "bedrock":
        return _bedrock_ocr(creds)
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
