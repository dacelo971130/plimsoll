"""Amazon Bedrock plumbing shared by the semantic layer, OCR and the review
agent. Authentication is a Bedrock API key (bearer token) only — the same
"paste one key" shape as the other providers, and no AWS SDK dependency.

Two model families sit behind one key, each on its own endpoint:
  - Claude (`anthropic.*`): the Messages API at
    https://bedrock-mantle.{region}.api.aws/anthropic — the plain Anthropic
    client with `base_url` + the token as `api_key` (bearer-token auth is
    the only kind that client path supports, which is all we use).
  - Amazon Nova (`amazon.nova*`): the Converse API at
    https://bedrock-runtime.{region}.amazonaws.com, called over httpx with
    `Authorization: Bearer <token>`.

The region ends up in a hostname and the model id in a URL path, so both are
validated against strict patterns before any request is built — a header
value must never be able to point a request somewhere else."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import quote

import httpx

from backend.services.llm.credentials import NO_CREDENTIALS, LlmCredentials, server_key

DEFAULT_MODEL = "anthropic.claude-sonnet-5"
REQUEST_TIMEOUT_S = 90.0
_REGION = re.compile(r"[a-z]{2}(?:-[a-z]+)+-\d{1,2}")
_MODEL = re.compile(r"[a-z0-9][a-z0-9.:\-]{2,99}")
# Cross-region inference profile prefixes in front of a base model id.
_GEO_PREFIXES = ("global.", "us.", "eu.", "apac.", "jp.", "au.", "ca.", "us-gov.")

Family = Literal["claude", "nova"]


def model_family(model: str) -> Family | None:
    base = model
    for prefix in _GEO_PREFIXES:
        if base.startswith(prefix):
            base = base[len(prefix):]
            break
    if base.startswith("anthropic.claude"):
        return "claude"
    if base.startswith("amazon.nova"):
        return "nova"
    return None


@dataclass(frozen=True)
class BedrockTarget:
    token: str = field(repr=False)
    region: str
    model: str

    @property
    def family(self) -> Family:
        family = model_family(self.model)
        assert family is not None  # resolve_bedrock_target only builds supported ones
        return family


def resolve_bedrock_target(creds: LlmCredentials | None = None) -> tuple[BedrockTarget | None, str | None]:
    """(target, None), or (None, reason) worded for the reviewer. The pasted
    key, region and model win; otherwise the server's
    AWS_BEARER_TOKEN_BEDROCK / AWS_REGION / PLIMSOLL_BEDROCK_MODEL."""
    creds = creds or NO_CREDENTIALS
    token = creds.api_key if creds.explicit else server_key("bedrock")
    region = creds.region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    model = creds.model or os.environ.get("PLIMSOLL_BEDROCK_MODEL") or DEFAULT_MODEL
    if not token:
        return None, "尚未設定 Bedrock 的 API 金鑰。"
    if not region:
        return None, "尚未選擇 Bedrock 的區域（region）。"
    if not _REGION.fullmatch(region):
        return None, f"Bedrock 區域格式不正確：{region[:40]}"
    if not _MODEL.fullmatch(model) or model_family(model) is None:
        return None, f"不支援的 Bedrock 模型：{model[:60]}"
    return BedrockTarget(token=token, region=region, model=model), None


def claude_client(target: BedrockTarget):
    import anthropic

    return anthropic.Anthropic(
        api_key=target.token,
        base_url=f"https://bedrock-mantle.{target.region}.api.aws/anthropic",
        timeout=REQUEST_TIMEOUT_S,
        max_retries=2,
    )


class ConverseError(Exception):
    """A non-2xx answer from the Converse API. `status` is the HTTP status
    (0 for a connection failure); `str()` is AWS's own message."""

    def __init__(self, status: int, message: str, error_type: str | None = None):
        super().__init__(message)
        self.status = status
        self.error_type = error_type


class ConverseClient:
    """Minimal Converse API client: one POST per turn, bearer-token auth."""

    def __init__(self, target: BedrockTarget, *, http: httpx.Client | None = None):
        self.model = target.model
        self._url = f"https://bedrock-runtime.{target.region}.amazonaws.com/model/{quote(target.model, safe='')}/converse"
        self._headers = {"Authorization": f"Bearer {target.token}", "Content-Type": "application/json", "Accept": "application/json"}
        self._http = http or httpx.Client(timeout=REQUEST_TIMEOUT_S)

    def converse(self, body: dict) -> dict:
        try:
            response = self._http.post(self._url, headers=self._headers, json=body)
        except httpx.HTTPError as exc:
            raise ConverseError(0, f"無法連線到 Bedrock：{type(exc).__name__}") from exc
        if response.status_code >= 400:
            try:
                message = response.json().get("message") or response.text
            except ValueError:
                message = response.text
            # restJson1: "Namespace#ThrottlingException:http://…" → "ThrottlingException"
            error_type = (response.headers.get("x-amzn-ErrorType") or "").split(":")[0].split("#")[-1] or None
            raise ConverseError(response.status_code, message[:500], error_type)
        return response.json()


def converse_error_message(exc: ConverseError) -> str:
    if exc.status == 0:
        return "無法連線到 Bedrock，請確認網路。"
    if exc.status in (401, 403):
        return "Bedrock 的 API 金鑰無效，或沒有使用這個模型的權限（請確認已在 AWS 主控台開通模型）。"
    if exc.status == 429:
        return "Bedrock 目前忙碌，請稍後再試。"
    return f"Bedrock 回應錯誤（{exc.status}），請稍後再試。"
