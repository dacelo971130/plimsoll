"""P5 multi-provider BYOK — shared FastAPI dependency every AI-touching
endpoint uses to read the frontend's chosen provider/key. Headers, not a
query string or JSON body field: uvicorn's default access log includes the
request line (method + path + query string) but NOT headers, so a header is
the one transport that never ends up in a log file. The key is used to
construct a provider instance for exactly this one request
(resolve_llm_provider/resolve_ocr_provider) and is never written to disk or
echoed back in any response."""

from __future__ import annotations

from fastapi import Header


def llm_credentials(
    x_llm_provider: str | None = Header(default=None, alias="X-Llm-Provider"),
    x_llm_api_key: str | None = Header(default=None, alias="X-Llm-Api-Key"),
) -> tuple[str | None, str | None]:
    return x_llm_provider, x_llm_api_key
