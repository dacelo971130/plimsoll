"""Optional shared-password gate for a publicly reachable demo (Cloudflare
Quick Tunnel, Tailscale Funnel, a small PaaS — see README 「讓別人連到本機」).
Off unless `PLIMSOLL_DEMO_PASSWORD` is set, so local dev and every other
test run exactly as before. Once a URL is public this is the one gate a
demo cannot skip: without it anyone who finds the URL can `DELETE
/api/sessions` (wipes every session) and every AI-touching endpoint spends
the server's `ANTHROPIC_API_KEY`.

HTTP Basic, password only — the username field is ignored. The browser's
own prompt collects it once and then attaches it to every same-origin
request (the SPA's fetch() calls, the PDF viewer, downloads), so the
frontend needs no change. The env var is read per request rather than at
import so tests can monkeypatch it."""

from __future__ import annotations

import base64
import binascii
import os
import secrets

from fastapi import Request
from fastapi.responses import PlainTextResponse

PASSWORD_ENV = "PLIMSOLL_DEMO_PASSWORD"

# PaaS liveness probes can't answer a Basic-auth prompt; the body is a
# constant that reveals nothing.
_OPEN_PATHS = frozenset({"/api/health"})


def _password_from_header(value: str | None) -> str | None:
    if not value or not value.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(value[len("Basic "):], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    _, sep, password = decoded.partition(":")
    return password if sep else None


async def demo_password_gate(request: Request, call_next):
    expected = os.environ.get(PASSWORD_ENV)
    if not expected or request.url.path in _OPEN_PATHS:
        return await call_next(request)
    supplied = _password_from_header(request.headers.get("authorization"))
    if supplied is not None and secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        return await call_next(request)
    return PlainTextResponse(
        "需要密碼才能使用這個 Demo。",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Plimsoll demo", charset="UTF-8"'},
    )
