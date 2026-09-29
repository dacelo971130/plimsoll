"""The optional shared-password gate (backend/api/demo_auth.py): off by
default, and once PLIMSOLL_DEMO_PASSWORD is set every route — API, SPA and
the destructive DELETE — needs the password, except the health probe."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from backend.api.demo_auth import PASSWORD_ENV
from backend.main import app

client = TestClient(app)


def _basic(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def demo_password(monkeypatch):
    monkeypatch.setenv(PASSWORD_ENV, "錨點-2026")
    return "錨點-2026"


def test_gate_is_off_when_env_unset(monkeypatch):
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    assert client.get("/api/sessions").status_code == 200


def test_gate_is_off_when_env_is_empty(monkeypatch):
    # docker-compose passes `PLIMSOLL_DEMO_PASSWORD=${PLIMSOLL_DEMO_PASSWORD:-}`,
    # so "unset on the host" arrives as an empty string, not a missing var.
    monkeypatch.setenv(PASSWORD_ENV, "")
    assert client.get("/api/sessions").status_code == 200


def test_missing_credentials_get_a_basic_auth_challenge(demo_password):
    res = client.get("/api/sessions")
    assert res.status_code == 401
    assert res.headers["www-authenticate"].startswith("Basic ")


def test_wrong_password_is_rejected(demo_password):
    assert client.get("/api/sessions", headers=_basic("demo", "wrong")).status_code == 401


def test_right_password_passes_with_any_username(demo_password):
    assert client.get("/api/sessions", headers=_basic("", demo_password)).status_code == 200
    assert client.get("/api/sessions", headers=_basic("評審", demo_password)).status_code == 200


def test_destructive_delete_is_gated(demo_password):
    assert client.delete("/api/sessions").status_code == 401


def test_spa_root_is_gated(demo_password):
    assert client.get("/").status_code == 401


def test_health_probe_stays_open(demo_password):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


@pytest.mark.parametrize(
    "header",
    ["Bearer abc", "Basic !!!not-base64!!!", "Basic " + base64.b64encode(b"no-colon").decode("ascii")],
)
def test_malformed_headers_are_401_not_500(demo_password, header):
    assert client.get("/api/sessions", headers={"Authorization": header}).status_code == 401
