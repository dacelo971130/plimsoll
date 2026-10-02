"""Which model the review agent runs on for this request (spec §4.8).

One selection in 設定 → AI 模型 covers the agent too: Claude, Gemini, or
Bedrock (Claude or Amazon Nova there) — with the reviewer's pasted key, or
else the server's own key for that provider. ChatGPT has no agent. The same
rule provider.py follows for the semantic layer: never silently switch to a
provider the user didn't choose. SDKs are imported only when chosen, so a
missing optional package can't stop the app from starting."""

from __future__ import annotations

from backend.services.agent.runner import AgentBackend
from backend.services.llm.credentials import NO_CREDENTIALS, LlmCredentials, pinned_provider, server_key, server_providers

AGENT_PROVIDERS = ("anthropic", "gemini", "bedrock")
REQUEST_TIMEOUT_S = 90.0
UNSUPPORTED = "覆核 Agent 支援 Claude、Gemini 與 Bedrock；目前選擇的 AI 服務不支援。"


def _env_provider() -> str | None:
    """The server's own pick: PLIMSOLL_AI_PROVIDER if set (even an
    unsupported one, so the reason can say so), else the first agent-capable
    provider with a real key."""
    pinned = pinned_provider()
    if pinned is not None:
        return pinned
    return next(iter(server_providers(AGENT_PROVIDERS)), None)


def resolve_agent_backend(creds: LlmCredentials | None = None) -> tuple[AgentBackend | None, str | None]:
    """Returns (backend, None) or (None, reason) — the reason is shown to the
    reviewer as-is."""
    creds = creds or NO_CREDENTIALS
    provider = creds.provider_id or _env_provider()
    if provider is None:
        return None, UNSUPPORTED if server_key("openai") else "尚未設定 AI 服務的 API 金鑰。"
    if provider not in AGENT_PROVIDERS:
        return None, UNSUPPORTED

    if provider == "bedrock":
        from backend.services.llm.bedrock import ConverseClient, claude_client, resolve_bedrock_target

        target, reason = resolve_bedrock_target(creds)
        if target is None:
            return None, reason
        if target.family == "claude":
            from backend.services.agent.anthropic_backend import BedrockClaudeBackend

            return BedrockClaudeBackend(claude_client(target), target.model), None
        from backend.services.agent.converse_backend import ConverseBackend

        return ConverseBackend(ConverseClient(target)), None

    key = creds.api_key if creds.explicit else server_key(provider)
    if provider == "anthropic":
        if not key:
            return None, "尚未設定 Claude 的 API 金鑰。"
        import anthropic

        from backend.services.agent.anthropic_backend import AnthropicBackend

        return AnthropicBackend(anthropic.Anthropic(api_key=key, timeout=REQUEST_TIMEOUT_S, max_retries=2)), None

    if not key:
        return None, "尚未設定 Gemini 的 API 金鑰。"
    try:
        from backend.services.agent.gemini_backend import GeminiBackend
    except ImportError:
        return None, "伺服器沒有安裝 Gemini 的套件（google-genai）。"
    return GeminiBackend(api_key=key), None
