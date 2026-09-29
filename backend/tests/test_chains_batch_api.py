"""HTTP-layer tests for the P5 Message Batches chain endpoints."""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from backend.config import REPO_ROOT, SESSIONS_ROOT
from backend.main import app
from backend.tests.test_batch import FakeBatchProvider

client = TestClient(app)

DEMO_CHAIN_FILES = [REPO_ROOT / "data" / "demo" / f"Main_Engine_Cooling_v1.{i}.pdf" for i in range(5)]

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in DEMO_CHAIN_FILES), reason="run scripts/generate_demo_pdfs.py first"
)


@pytest.fixture
def cleanup_chain():
    created: list[str] = []
    yield created
    for entity_id in created:
        shutil.rmtree(SESSIONS_ROOT / entity_id, ignore_errors=True)


def _create_demo_chain(cleanup_chain):
    res = client.post("/api/chains/demo")
    assert res.status_code == 200
    body = res.json()
    cleanup_chain.append(body["chain_id"])
    cleanup_chain.extend(body["manifest"]["adjacent_session_ids"])
    cleanup_chain.extend(body["manifest"]["anchor_session_ids"])
    return body["chain_id"]


def test_submit_batch_is_unavailable_without_a_provider(cleanup_chain, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    chain_id = _create_demo_chain(cleanup_chain)

    res = client.post(f"/api/chains/{chain_id}/semantic-preview/batch")
    assert res.status_code == 200
    assert res.json()["semantic_layer_available"] is False


def test_submit_and_poll_batch_end_to_end(cleanup_chain, monkeypatch):
    provider = FakeBatchProvider()
    monkeypatch.setattr("backend.services.llm.provider.get_llm_provider", lambda: provider)
    chain_id = _create_demo_chain(cleanup_chain)

    res = client.post(f"/api/chains/{chain_id}/semantic-preview/batch")
    assert res.status_code == 200
    body = res.json()
    assert body["semantic_layer_available"] is True
    batch_id = body["batch_id"]
    assert batch_id is not None
    assert body["difference_count"] > 0

    res = client.get(f"/api/chains/{chain_id}/semantic-preview/batch/{batch_id}")
    assert res.status_code == 200
    assert res.json()["status"] == "in_progress"

    provider.end_batch(batch_id)
    res = client.get(f"/api/chains/{chain_id}/semantic-preview/batch/{batch_id}")
    assert res.status_code == 200
    completed = res.json()
    assert completed["status"] == "completed"
    assert len(completed["results"]) == body["difference_count"]

    res = client.get(f"/api/chains/{chain_id}/semantic-preview/batch")
    assert res.status_code == 200
    ledger = res.json()["batches"]
    assert len(ledger) == 1
    assert ledger[0]["batch_id"] == batch_id
    assert ledger[0]["status"] == "completed"


def test_poll_unknown_batch_is_404(cleanup_chain, monkeypatch):
    provider = FakeBatchProvider()
    monkeypatch.setattr("backend.services.llm.provider.get_llm_provider", lambda: provider)
    chain_id = _create_demo_chain(cleanup_chain)

    res = client.get(f"/api/chains/{chain_id}/semantic-preview/batch/batch-doesnotexist")
    assert res.status_code == 404


def test_submit_batch_on_unknown_chain_is_404(monkeypatch):
    provider = FakeBatchProvider()
    monkeypatch.setattr("backend.services.llm.provider.get_llm_provider", lambda: provider)

    res = client.post("/api/chains/c-doesnotexist/semantic-preview/batch")
    assert res.status_code == 404
