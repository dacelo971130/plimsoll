"""HTTP-level tests for the W5/W6/W8 chain endpoints."""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from backend.config import REPO_ROOT, SESSIONS_ROOT
from backend.main import app

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


def test_demo_chain_end_to_end_through_http(cleanup_chain):
    res = client.post("/api/chains/demo")
    assert res.status_code == 200
    body = res.json()
    chain_id = body["chain_id"]
    cleanup_chain.append(chain_id)
    cleanup_chain.extend(body["manifest"]["adjacent_session_ids"])
    cleanup_chain.extend(body["manifest"]["anchor_session_ids"])

    assert body["manifest"]["ordered_versions"] == ["v1.0", "v1.1", "v1.2", "v1.3", "v1.4"]
    drift = next(f for f in body["drift_report"] if f["canonical_param"].endswith("::%"))
    assert drift["is_drift"] is True
    assert drift["risk"] == "High"

    res = client.get(f"/api/chains/{chain_id}")
    assert res.status_code == 200
    assert res.json()["chain_id"] == chain_id
    assert res.json()["review_state"] == {}

    res = client.post(
        f"/api/chains/{chain_id}/review-events",
        json={
            "human_verdict": "CONFIRMED",
            "reviewer_name": "陳○○",
            "approval_role_code": "TECH_SUPT",
            "reviewer_note": "累積調整已確認為刻意調整",
        },
    )
    assert res.status_code == 200
    assert res.json()["event"]["event_type"] == "CHAIN_REVIEW"
    assert res.json()["chain"]["review_events"][0]["reviewer_note"] == "累積調整已確認為刻意調整"


def test_get_unknown_chain_is_404():
    res = client.get("/api/chains/c-does-not-exist")
    assert res.status_code == 404


def test_chain_review_on_unknown_chain_is_404():
    res = client.post(
        "/api/chains/c-does-not-exist/review-events",
        json={"human_verdict": "CONFIRMED", "reviewer_name": "X", "approval_role_code": "DPA"},
    )
    assert res.status_code == 404


def test_create_chain_requires_at_least_two_files():
    with open(DEMO_CHAIN_FILES[0], "rb") as f:
        res = client.post("/api/chains", files=[("files", ("v1.0.pdf", f.read(), "application/pdf"))])
    assert res.status_code == 400
