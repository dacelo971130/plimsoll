"""HTTP-layer tests for P5's term_aliases 核准 endpoints. The pending queue
and versioned config live under the REAL data/store/config/term_aliases/
directory (config_loader's functions default `config_root` to the real
CONFIG_ROOT, bound at import time — unlike SESSIONS_ROOT there's no per-test
subdirectory to isolate into), so every test that writes here MUST restore
the directory to its original state, the same discipline
scripts/generate_demo_pdfs.py-adjacent fixtures already follow for
SESSIONS_ROOT elsewhere in this suite."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.config import CONFIG_ROOT, REPO_ROOT, SESSIONS_ROOT
from backend.main import app
from backend.storage.config_loader import get_term_aliases

client = TestClient(app)

DEMO_OLD = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.0.pdf"
DEMO_NEW = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.1.pdf"

_ALIASES_DIR = CONFIG_ROOT / "term_aliases"
_PENDING_PATH = _ALIASES_DIR / "pending.json"


@pytest.fixture
def clean_term_aliases_dir():
    """Snapshots which term_aliases files exist before the test, deletes
    anything new afterward (pending.json, any vN.json created by an
    approval), and clears the lru_cache so later tests see the real seed
    again."""
    before = set(_ALIASES_DIR.iterdir())
    yield
    for p in set(_ALIASES_DIR.iterdir()) - before:
        p.unlink()
    get_term_aliases.cache_clear()


def test_pending_aliases_endpoint_returns_a_list():
    res = client.get("/api/term-aliases/pending")
    assert res.status_code == 200
    assert isinstance(res.json()["candidates"], list)


def test_approve_unknown_pending_alias_is_404():
    res = client.post("/api/term-aliases/pending/pa-doesnotexist/approve", json={"approved_by": "tester"})
    assert res.status_code == 404


def test_reject_unknown_pending_alias_is_404():
    res = client.post("/api/term-aliases/pending/pa-doesnotexist/reject", json={})
    assert res.status_code == 404


def test_approve_without_approved_by_is_400(clean_term_aliases_dir):
    # No pending entry needs to exist yet — the missing-approver check runs first.
    res = client.post("/api/term-aliases/pending/pa-anything/approve", json={})
    assert res.status_code == 400


@pytest.mark.skipif(not (DEMO_OLD.exists() and DEMO_NEW.exists()), reason="run scripts/generate_demo_pdfs.py first")
def test_suggest_aliases_end_to_end_through_http(clean_term_aliases_dir, monkeypatch):
    from backend.services.llm.schemas import AliasCandidateSuggestion, ResidualSuggestion

    class _FakeProvider:
        model_id = "fake-model"
        provider_name = "fake"

        def classify_residual(self, old_text, new_text, *, effort="medium"):
            return ResidualSuggestion(
                semantic_change_type="clarification", suggest_escalate=False, rationale="用詞更精確，語意未變"
            )

        def suggest_term_alias(self, old_text, new_text, *, effort="low"):
            return AliasCandidateSuggestion(
                is_synonym_pair=True, canonical="測試標準詞", variant="測試舊說法", rationale="同一件事"
            )

    monkeypatch.setattr("backend.services.llm.provider.get_llm_provider", lambda: _FakeProvider())

    res = client.post("/api/sessions/demo")
    assert res.status_code == 200
    session_id = res.json()["session"]["session_id"]
    try:
        res = client.post(f"/api/sessions/{session_id}/suggest-aliases")
        assert res.status_code == 200
        body = res.json()
        assert body["semantic_layer_available"] is True

        res = client.get("/api/term-aliases/pending")
        pending = res.json()["candidates"]
        assert any(c["source_session_id"] == session_id for c in pending)
        target = next(c for c in pending if c["source_session_id"] == session_id)

        res = client.post(
            f"/api/term-aliases/pending/{target['id']}/approve", json={"approved_by": "tester@example.com"}
        )
        assert res.status_code == 200
        assert res.json()["candidate"]["status"] == "approved"

        # a new version was written and is now the latest.
        versions = sorted(p.stem for p in _ALIASES_DIR.glob("v*.json"))
        new_table = json.loads((_ALIASES_DIR / f"{versions[-1]}.json").read_text(encoding="utf-8"))
        assert any(a["canonical"] == "測試標準詞" for a in new_table["aliases"])
    finally:
        import shutil

        shutil.rmtree(SESSIONS_ROOT / session_id, ignore_errors=True)
