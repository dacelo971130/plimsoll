"""Which Claude client the agent may use for this request (spec §4.8).

The agent is Claude-only. A reviewer who picked Claude in 設定 → AI 模型 and
pasted a key uses that key; otherwise the server's ANTHROPIC_API_KEY. A
reviewer who picked a *different* provider gets no agent at all — the same
rule provider.py follows for the semantic layer: never silently switch to a
provider the user didn't choose."""

from __future__ import annotations

import os

import anthropic

REQUEST_TIMEOUT_S = 90.0


def resolve_agent_client(provider_id: str | None, api_key: str | None) -> tuple[anthropic.Anthropic | None, str | None]:
    """Returns (client, None) or (None, reason) — the reason is shown to the
    reviewer as-is."""
    if provider_id and provider_id != "anthropic":
        return None, "目前選擇的 AI 服務不是 Claude；覆核 Agent 只支援 Claude。"
    key = api_key if provider_id == "anthropic" and api_key else os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None, "尚未設定 Claude 的 API 金鑰。"
    return anthropic.Anthropic(api_key=key, timeout=REQUEST_TIMEOUT_S, max_retries=2), None
