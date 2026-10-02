"""Which AI backend one request asked for (P5 multi-provider BYOK).

Built from the frontend's `X-Llm-*` headers (backend/api/llm_headers.py) and
handed, unchanged, to every resolver — the semantic layer
(llm/provider.py), OCR (ocr/provider.py) and the review agent
(agent/client.py) — so one selection in Settings → AI 模型 covers them all.
`region` and `model` only mean something for Bedrock: a Bedrock API key
works in many regions and fronts both Claude and Amazon Nova, so the key
alone doesn't say where to send the request or to which model. The key is
never persisted or logged; `__repr__` leaves it out so a stray log line or
traceback can't either."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

PROVIDER_IDS = ("anthropic", "gemini", "openai", "bedrock")


@dataclass(frozen=True)
class LlmCredentials:
    provider_id: str | None = None
    api_key: str | None = field(default=None, repr=False)
    region: str | None = None
    model: str | None = None

    @property
    def explicit(self) -> bool:
        """The user picked a provider and pasted a key — those win over any
        server-side key. Anything less falls back to the server's env vars."""
        return bool(self.provider_id and self.api_key)


NO_CREDENTIALS = LlmCredentials()


# --------------------------------------------------------------------------
# The server's own keys (env vars), for requests that carry no pasted key.
# --------------------------------------------------------------------------

SERVER_KEY_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "bedrock": "AWS_BEARER_TOKEN_BEDROCK",
}
# Values copied straight from .env.example or a README — 「your_..._here」,
# 「換成你的金鑰」, 「<新的key>」. No real key looks like these, and treating
# them as set made the server pick a fake Anthropic key ahead of a real
# Bedrock token (2026-10-02).
_PLACEHOLDER = re.compile(r"^your[_-]|_here$|換成|金鑰|^<.*>$|^changeme$", re.IGNORECASE)
_warned: set[str] = set()  # agent status is polled — say it once per variable


def server_key(provider_id: str) -> str | None:
    """That provider's key from the server env, or None if unset, blank or
    still an example placeholder."""
    value = (os.environ.get(SERVER_KEY_VARS[provider_id]) or "").strip().strip("'\"")
    if not value:
        return None
    if _PLACEHOLDER.search(value):
        var = SERVER_KEY_VARS[provider_id]
        if var not in _warned:
            _warned.add(var)
            log.warning("%s looks like an example placeholder, not a key — ignored", var)
        return None
    return value


def server_providers(order: tuple[str, ...] = PROVIDER_IDS) -> list[str]:
    """Providers the server's own env can run, best first. PLIMSOLL_AI_PROVIDER
    pins one (so a stray key for another provider can't win); otherwise the
    first in `order` with a real key."""
    pinned = (os.environ.get("PLIMSOLL_AI_PROVIDER") or "").strip().lower()
    if pinned and pinned not in PROVIDER_IDS:
        log.warning("PLIMSOLL_AI_PROVIDER=%r is not one of %s — ignored", pinned, ", ".join(PROVIDER_IDS))
        pinned = ""
    candidates = [pinned] if pinned else list(order)
    return [p for p in candidates if server_key(p)]


def pinned_provider() -> str | None:
    pinned = (os.environ.get("PLIMSOLL_AI_PROVIDER") or "").strip().lower()
    return pinned if pinned in PROVIDER_IDS else None
