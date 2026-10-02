"""P5 multi-provider BYOK — shared FastAPI dependency every AI-touching
endpoint uses to read the frontend's chosen provider/key. Headers, not a
query string or JSON body field: uvicorn's default access log includes the
request line (method + path + query string) but NOT headers, so a header is
the one transport that never ends up in a log file. The key is used to
construct a provider instance for exactly this one request
(resolve_llm_provider/resolve_ocr_provider/resolve_agent_backend) and is
never written to disk or echoed back in any response. `X-Llm-Region` and
`X-Llm-Model` are only sent for Bedrock (see LlmCredentials)."""

from __future__ import annotations

from fastapi import Header

from backend.services.llm.credentials import LlmCredentials


def llm_credentials(
    x_llm_provider: str | None = Header(default=None, alias="X-Llm-Provider"),
    x_llm_api_key: str | None = Header(default=None, alias="X-Llm-Api-Key"),
    x_llm_region: str | None = Header(default=None, alias="X-Llm-Region"),
    x_llm_model: str | None = Header(default=None, alias="X-Llm-Model"),
) -> LlmCredentials:
    return LlmCredentials(provider_id=x_llm_provider, api_key=x_llm_api_key, region=x_llm_region, model=x_llm_model)
