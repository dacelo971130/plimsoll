"""`LlmProvider` Strategy (architecture-decisions-A-B.md §25) — restricted,
for W7, to the two single structured-output call sites the improvement plan
scopes it to (§03).

Why not an agent: differences are classified with a FIXED input (one old/new
sentence pair, or one parameter series) and a FIXED output shape (change
type + escalation suggestion, or a trend verdict) — that is exactly the
bottom rung of Claude's own surface-selection guidance (single-call
classification/extraction), not a multi-step, plan-as-you-go task. Making it
an agent would cost this project its three load-bearing properties: **same
document, same result every run** (a tool-loop's path can vary), **one
`analysis_mode` field a稽核 event can capture the judgement's provenance
in** (a multi-turn tool trace doesn't collapse into one auditable field),
and **predictable cost/latency** (a structured call is one round trip; an
agent loop isn't).

`get_llm_provider()` is the ONLY place that decides whether the semantic
layer runs at all — no API key (or the `anthropic` package missing
entirely) returns None, and every caller must treat None as "skip, don't
degrade": the rules-first pipeline is complete and correct with zero LLM
involvement (§03 "LLM 是加值層不是相依"). Nothing in this module is wired
into the default session/chain creation path — see
backend/services/llm/residual.py's module docstring for why that's a
deliberate, separate opt-in rather than automatic.
"""

from __future__ import annotations

from typing import Protocol

from backend.models.chain import ParameterPoint
from backend.services.llm.credentials import NO_CREDENTIALS, PROVIDER_IDS, LlmCredentials, server_key, server_providers
from backend.services.llm.schemas import (
    AliasCandidateSuggestion,
    DrawingRegionSuggestion,
    ResidualSuggestion,
    TrailAnalysis,
)


class LlmUnavailable(Exception):
    """Raised by a provider when a call fails for any reason (auth, rate
    limit, network, malformed response after the SDK's own retries) — always
    caught at the call site and treated as "no suggestion this time", never
    allowed to fail the surrounding comparison/session flow."""


class LlmProvider(Protocol):
    model_id: str
    provider_name: str

    def classify_residual(
        self, old_text: str | None, new_text: str | None, *, effort: str = "medium"
    ) -> ResidualSuggestion:
        """W7a. Raises LlmUnavailable on failure — never returns a guessed
        default silently."""
        ...

    def analyze_trail(self, series: list[ParameterPoint], *, effort: str = "high") -> TrailAnalysis:
        """W7b. Raises LlmUnavailable on failure."""
        ...

    def describe_drawing_region(
        self, old_crop_png: bytes | None, new_crop_png: bytes | None, *, effort: str = "medium"
    ) -> DrawingRegionSuggestion:
        """P5 §26. Exactly one of `old_crop_png`/`new_crop_png` is None for a
        pure insert/delete region; both are given for a changed region.
        Raises LlmUnavailable on failure."""
        ...

    def suggest_term_alias(self, old_text: str, new_text: str, *, effort: str = "low") -> AliasCandidateSuggestion:
        """P5 term_aliases 核准流程. Raises LlmUnavailable on failure."""
        ...

    def classify_residual_batch(self, items: list[tuple[str, str | None, str | None]]) -> str:
        """P5 Message Batches (backend.services.llm.batch_jobs). `items` is
        `(custom_id, old_text, new_text)` triples; returns the batch id.
        Raises LlmUnavailable if the submit call itself fails — never
        partially submits."""
        ...

    def get_batch_status(self, batch_id: str) -> str:
        """Returns the Anthropic Batch API's `processing_status`
        ('in_progress' | 'canceling' | 'ended'). Raises LlmUnavailable on
        failure."""
        ...

    def fetch_batch_results(self, batch_id: str) -> dict[str, ResidualSuggestion | None]:
        """Only valid once get_batch_status() returns 'ended'. Returns
        {custom_id: ResidualSuggestion} for succeeded requests; a custom_id
        maps to None for errored/canceled/expired ones — the caller treats
        that exactly like a single-call LlmUnavailable (skip, never guess).
        Raises LlmUnavailable if fetching the results themselves fails."""
        ...


def get_llm_provider() -> LlmProvider | None:
    """Server-env-var path — returns None (never raises) when the semantic
    layer can't run: no provider's SDK is installed, or no real key is set.
    All are legitimate, expected states in a rules-first deployment — this
    is a config/env check, not an error path. PLIMSOLL_AI_PROVIDER pins one
    provider; otherwise the first with a real key in this order (Anthropic
    first, since it's the original/default integration). Example
    placeholders copied from .env.example don't count as keys — see
    credentials.server_key()."""
    for provider_id in server_providers():
        provider = _server_side(provider_id)
        if provider is not None:
            return provider
    return None


def _server_side(provider_id: str) -> LlmProvider | None:
    if provider_id == "bedrock":
        return _bedrock_provider(NO_CREDENTIALS)
    try:
        if provider_id == "anthropic":
            from backend.services.llm.anthropic_provider import AnthropicProvider

            return AnthropicProvider(api_key=server_key("anthropic"))
        if provider_id == "gemini":
            from backend.services.llm.gemini_provider import GeminiProvider

            return GeminiProvider(api_key=server_key("gemini"))
        from backend.services.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=server_key("openai"))
    except ImportError:  # that provider's SDK isn't installed
        return None


def _bedrock_provider(creds: LlmCredentials) -> LlmProvider | None:
    from backend.services.llm.bedrock import resolve_bedrock_target
    from backend.services.llm.bedrock_provider import BedrockProvider

    target, _reason = resolve_bedrock_target(creds)
    return BedrockProvider(target) if target is not None else None


# P5 multi-provider support: Settings → AI 模型 lets a user pick a provider
# and paste their OWN key, kept client-side in sessionStorage
# (frontend/src/app/settings/AiModelTab.tsx) and sent per-request as
# `X-Llm-*` headers — never persisted server-side, never logged (see
# backend/api/llm_headers.py). An unknown provider id degrades to None
# (unavailable) exactly like an unset key would, never a crash or a silent
# fall-through to a DIFFERENT provider the user didn't ask for.


def resolve_llm_provider(creds: LlmCredentials | None = None) -> LlmProvider | None:
    """The request-scoped counterpart to `get_llm_provider()`. When the
    frontend's BYOK headers name a provider and carry a key, THOSE win and
    construct a provider on the spot for this call only. Falls back to
    `get_llm_provider()`'s server-env-var behavior otherwise, so a
    deployment that sets `ANTHROPIC_API_KEY` (etc.) server-side still works
    with zero frontend involvement."""
    creds = creds or NO_CREDENTIALS
    if not creds.explicit:
        return get_llm_provider()
    provider_id, api_key = creds.provider_id, creds.api_key
    if provider_id not in PROVIDER_IDS:
        return None
    if provider_id == "bedrock":
        return _bedrock_provider(creds)
    if provider_id == "anthropic":
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return None
        from backend.services.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=api_key)
    if provider_id == "gemini":
        try:
            import google.genai  # noqa: F401
        except ImportError:
            return None
        from backend.services.llm.gemini_provider import GeminiProvider

        return GeminiProvider(api_key=api_key)
    try:
        import openai  # noqa: F401
    except ImportError:
        return None
    from backend.services.llm.openai_provider import OpenAIProvider

    return OpenAIProvider(api_key=api_key)
