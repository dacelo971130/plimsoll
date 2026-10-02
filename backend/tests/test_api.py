"""Smoke tests for the P0 API skeleton — startup must never call a database
(architecture-decisions-A-B.md §24(a)) — and the P1 sessions endpoints."""

from __future__ import annotations

import shutil

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.config import REPO_ROOT, SESSIONS_ROOT
from backend.api import system as system_api
from backend.main import app
from backend.storage import events as event_store

client = TestClient(app)

DEMO_OLD = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.0.pdf"
DEMO_NEW = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.1.pdf"


def test_health_ok():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_data_source_status_defaults_to_disconnected_and_never_blocks():
    res = client.get("/api/system/data-source")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "disconnected"
    assert body["pending_count"] == 0
    assert body["quarantined_sessions"] == []


def test_quarantine_download_and_acknowledge():
    session_id = "s-test-quarantine"
    raw = b'{"event_id": "E1", "note": "hand-edited"}\n'
    session_dir = SESSIONS_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    try:
        (session_dir / "review_events.jsonl").write_bytes(raw)

        # Not flagged yet — neither action may run against it.
        assert client.get(f"/api/system/quarantine/{session_id}/events").status_code == 409
        assert client.post(f"/api/system/quarantine/{session_id}/acknowledge").status_code == 409

        event_store.mark_quarantined(session_id, "完整性驗證失敗")
        res = client.get(f"/api/system/quarantine/{session_id}/events")
        assert res.status_code == 200
        assert res.content == raw  # byte-for-byte, it is the evidence
        assert "attachment" in res.headers["content-disposition"]

        res = client.post(f"/api/system/quarantine/{session_id}/acknowledge")
        assert res.status_code == 200
        assert all(q["session_id"] != session_id for q in res.json()["quarantined_sessions"])
        assert (session_dir / "review_events.jsonl").read_bytes() == raw  # log untouched
        assert client.post(f"/api/system/quarantine/{session_id}/acknowledge").status_code == 409
    finally:
        shutil.rmtree(session_dir, ignore_errors=True)


def test_quarantine_actions_404_for_unknown_or_escaping_ids():
    assert client.get("/api/system/quarantine/s-does-not-exist/events").status_code == 404
    assert client.post("/api/system/quarantine/s-does-not-exist/acknowledge").status_code == 404
    # URL clients normalise `..` away before routing, so hit the guard
    # directly: an id that isn't a real child of SESSIONS_ROOT never resolves.
    for escaping in ("..", "../store", "."):
        with pytest.raises(HTTPException) as err:
            system_api._quarantined_session_dir(escaping)
        assert err.value.status_code == 404


def test_approval_roles_endpoint_returns_seed_roles():
    res = client.get("/api/config/approval-roles")
    assert res.status_code == 200
    codes = {r["code"] for r in res.json()["roles"]}
    assert codes == {"DPA", "TECH_SUPT", "FLEET_MGR", "OTHER"}


@pytest.mark.skipif(not (DEMO_OLD.exists() and DEMO_NEW.exists()), reason="run scripts/generate_demo_pdfs.py first")
def test_demo_session_end_to_end_through_http():
    res = client.post("/api/sessions/demo")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "created"
    session_id = body["session"]["session_id"]
    try:
        assert len(body["session"]["differences"]) >= 5

        res = client.get(f"/api/sessions/{session_id}")
        assert res.status_code == 200
        assert res.json()["session_id"] == session_id

        res = client.get(f"/api/sessions/{session_id}/pages")
        assert res.status_code == 200
        assert len(res.json()["old"]) == 6

        res = client.get("/api/sessions")
        assert res.status_code == 200
        assert any(s["session_id"] == session_id for s in res.json()["sessions"])

        # P3: original PDF fetch (原始 PDF 原文模式)
        res = client.get(f"/api/sessions/{session_id}/pdf/old")
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/pdf"
        assert res.content == DEMO_OLD.read_bytes()

        res = client.get(f"/api/sessions/{session_id}/pdf/sideways")
        assert res.status_code == 422  # not a valid Literal["old","new"]

        # P3: review event round trip through HTTP, including denial.
        high_diff = next(d for d in body["session"]["differences"] if d["ai_risk"] == "High")
        res = client.post(
            f"/api/sessions/{session_id}/review-events",
            json={
                "difference_id": high_diff["id"],
                "human_verdict": "CONFIRMED",
                "reviewer_name": "陳○○",
                "approval_role_code": "TECH_SUPT",
                "reviewer_note": "已核對",
            },
        )
        assert res.status_code == 200
        assert res.json()["session"]["review_state"][high_diff["id"]]["human_verdict"] == "CONFIRMED"

        # Blank reviewer name — refused server-side, not only by ReviewBar.
        res = client.post(
            f"/api/sessions/{session_id}/review-events",
            json={
                "difference_id": high_diff["id"],
                "human_verdict": "CONFIRMED",
                "reviewer_name": "",
                "approval_role_code": "TECH_SUPT",
            },
        )
        assert res.status_code == 400
        assert res.json()["detail"] == "未填寫覆核人姓名，無法送出"

        res = client.post(
            f"/api/sessions/{session_id}/review-events",
            json={
                "difference_id": high_diff["id"],
                "human_verdict": "CONFIRMED",
                "reviewer_name": "王○○",
                "approval_role_code": "OTHER",
            },
        )
        assert res.status_code == 403

        # P4: export — other High items are still unreviewed, so this must
        # 428 with the exact list before any acknowledgement is given.
        res = client.post(
            f"/api/sessions/{session_id}/export",
            json={"format": "html", "reviewer_name": "陳○○", "approval_role_code": "TECH_SUPT"},
        )
        assert res.status_code == 428
        unreviewed_ids = {d["id"] for d in res.json()["detail"]["unreviewed_high"]}
        assert high_diff["id"] not in unreviewed_ids  # already confirmed above
        assert len(unreviewed_ids) > 0

        res = client.post(
            f"/api/sessions/{session_id}/export",
            json={"format": "html", "reviewer_name": "  ", "approval_role_code": "TECH_SUPT", "acknowledge_draft": True},
        )
        assert res.status_code == 400

        res = client.post(
            f"/api/sessions/{session_id}/export",
            json={
                "format": "html",
                "reviewer_name": "陳○○",
                "approval_role_code": "TECH_SUPT",
                "report_no": "RPT-001",
                "acknowledge_draft": True,
            },
        )
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/html")
        assert "修訂草稿" in res.text

        res = client.post(
            f"/api/sessions/{session_id}/export",
            json={"format": "docx", "reviewer_name": "陳○○", "approval_role_code": "TECH_SUPT", "acknowledge_draft": True},
        )
        assert res.status_code == 200
        assert res.content[:2] == b"PK"
    finally:
        shutil.rmtree(SESSIONS_ROOT / session_id, ignore_errors=True)


def test_demo_fixtures_lists_main_engine_cooling_as_available():
    # 2026-09-28 使用者回饋: 示範資料按鈕要能選擇性比對真實第三方文件（見
    # docs/redesign/plimsoll-real-document-smoketest-2026-09.html）。
    # `main_engine_cooling` ships in data/demo/ (git-tracked), so its
    # availability must match whether the demo PDFs exist — unlike the
    # data/external-samples/ fixtures, which are .gitignored and may not
    # exist in a fresh clone or CI.
    res = client.get("/api/sessions/demo-fixtures")
    assert res.status_code == 200
    fixtures = res.json()["fixtures"]
    ids = [f["id"] for f in fixtures]
    assert "main_engine_cooling" in ids
    assert len(ids) == len(set(ids))  # no duplicate ids in the registry
    main = next(f for f in fixtures if f["id"] == "main_engine_cooling")
    assert main["available"] == (DEMO_OLD.exists() and DEMO_NEW.exists())


def test_demo_session_rejects_unknown_fixture_id():
    res = client.post("/api/sessions/demo", data={"demo_id": "not-a-real-fixture"})
    assert res.status_code == 404


@pytest.mark.skipif(not (DEMO_OLD.exists() and DEMO_NEW.exists()), reason="run scripts/generate_demo_pdfs.py first")
def test_demo_session_with_explicit_fixture_id_matches_bare_default_call():
    res = client.post("/api/sessions/demo", data={"demo_id": "main_engine_cooling"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "created"
    try:
        assert body["session"]["old_filename"] == DEMO_OLD.name
        assert body["session"]["new_filename"] == DEMO_NEW.name
    finally:
        shutil.rmtree(SESSIONS_ROOT / body["session"]["session_id"], ignore_errors=True)


def test_export_on_unknown_session_is_404():
    res = client.post(
        "/api/sessions/s-does-not-exist/export",
        json={"format": "html", "reviewer_name": "X", "approval_role_code": "DPA", "acknowledge_draft": True},
    )
    assert res.status_code == 404


def test_pdf_fetch_404s_when_not_stashed():
    res = client.get("/api/sessions/s-does-not-exist/pdf/old")
    assert res.status_code == 404


def test_review_event_on_unknown_session_is_404():
    res = client.post(
        "/api/sessions/s-does-not-exist/review-events",
        json={"difference_id": "D01", "human_verdict": "CONFIRMED", "reviewer_name": "X", "approval_role_code": "DPA"},
    )
    assert res.status_code == 404


def test_get_unknown_session_is_404():
    res = client.get("/api/sessions/s-does-not-exist")
    assert res.status_code == 404


# --------------------------------------------------------------------------
# P5 multi-provider BYOK — X-Llm-Provider/X-Llm-Api-Key headers must reach
# resolve_llm_provider() with exactly what the client sent, for every
# AI-touching endpoint. Monkeypatches resolve_llm_provider itself (not a
# specific SDK) so this never makes a real network call regardless of which
# provider id is used.
# --------------------------------------------------------------------------


@pytest.mark.skipif(not (DEMO_OLD.exists() and DEMO_NEW.exists()), reason="run scripts/generate_demo_pdfs.py first")
def test_semantic_preview_forwards_llm_headers_to_resolve_llm_provider(monkeypatch):
    res = client.post("/api/sessions/demo")
    session_id = res.json()["session"]["session_id"]
    try:
        captured = {}

        def fake_resolve(creds):
            captured["provider_id"] = creds.provider_id
            captured["api_key"] = creds.api_key
            return None  # unavailable is fine — we only care what args it was called with

        monkeypatch.setattr("backend.services.llm.provider.resolve_llm_provider", fake_resolve)

        res = client.post(
            f"/api/sessions/{session_id}/semantic-preview",
            headers={"X-Llm-Provider": "gemini", "X-Llm-Api-Key": "my-test-key"},
        )
        assert res.status_code == 200
        assert captured == {"provider_id": "gemini", "api_key": "my-test-key"}

        captured.clear()
        client.post(f"/api/sessions/{session_id}/semantic-preview")
        assert captured == {"provider_id": None, "api_key": None}
    finally:
        shutil.rmtree(SESSIONS_ROOT / session_id, ignore_errors=True)


def test_upload_forwards_llm_headers_to_resolve_ocr_provider(monkeypatch):
    captured = {}

    def fake_resolve(creds):
        captured["provider_id"] = creds.provider_id
        captured["api_key"] = creds.api_key
        return None

    monkeypatch.setattr("backend.services.ocr.provider.resolve_ocr_provider", fake_resolve)

    res = client.post(
        "/api/sessions/demo",
        headers={"X-Llm-Provider": "openai", "X-Llm-Api-Key": "my-test-key"},
    )
    assert res.status_code in (200, 404)  # 404 only if demo PDFs are missing — either way headers already parsed
    assert captured == {"provider_id": "openai", "api_key": "my-test-key"}
    if res.status_code == 200:
        shutil.rmtree(SESSIONS_ROOT / res.json()["session"]["session_id"], ignore_errors=True)


# --------------------------------------------------------------------------
# P5 — HistoryRail 一鍵清除／單筆刪除 (user feedback)
# --------------------------------------------------------------------------


def test_delete_session_removes_it_and_404s_after():
    session_id = client.post("/api/sessions/demo").json()["session"]["session_id"]

    res = client.delete(f"/api/sessions/{session_id}")
    assert res.status_code == 200
    assert res.json()["deleted"] is True

    assert client.get(f"/api/sessions/{session_id}").status_code == 404
    assert not (SESSIONS_ROOT / session_id).exists()
    assert not any(s["session_id"] == session_id for s in client.get("/api/sessions").json()["sessions"])


def test_delete_session_404s_for_unknown_id():
    res = client.delete("/api/sessions/s-does-not-exist")
    assert res.status_code == 404


def test_delete_all_sessions_wipes_every_session():
    ids = [client.post("/api/sessions/demo").json()["session"]["session_id"] for _ in range(2)]
    try:
        res = client.delete("/api/sessions")
        assert res.status_code == 200
        assert res.json()["deleted_count"] >= 2
        assert client.get("/api/sessions").json()["sessions"] == []
        for session_id in ids:
            assert not (SESSIONS_ROOT / session_id).exists()
    finally:
        for session_id in ids:
            shutil.rmtree(SESSIONS_ROOT / session_id, ignore_errors=True)
