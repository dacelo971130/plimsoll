"""P0 storage backbone tests — append-only events, fold projection,
frozen-prefix integrity anchor, and quarantine handling.

architecture-decisions-A-B.md §21 is the spec under test.
"""

from __future__ import annotations

from backend.storage import events as ev


def _ai_initial(session_id: str, difference_id: str, risk: str = "High") -> dict:
    return {
        "difference_id": difference_id,
        "event_type": "AI_INITIAL",
        "ai_risk_at_time": risk,
        "ai_confidence_at_time": "高",
        "ruleset_version": "v1",
        "data_origin": "computed",
    }


def _human_review(difference_id: str, verdict: str = "CONFIRMED", role: str = "TECH_SUPT") -> dict:
    return {
        "difference_id": difference_id,
        "event_type": "HUMAN_REVIEW",
        "human_verdict": verdict,
        "reviewer_name": "陳○○",
        "approval_role_code": role,
        "approval_role_label_snapshot": "船舶技術監督（Technical Superintendent）",
        "reviewer_note": "已核對新版 p.4",
        "data_origin": "computed",
    }


def test_append_assigns_sequential_ids_and_hash_chain(tmp_path):
    session_id = "s-test"
    e1 = ev.append_event(session_id, _ai_initial(session_id, "D01"), store_root=tmp_path)
    e2 = ev.append_event(session_id, _human_review("D01"), store_root=tmp_path)

    assert e1["event_id"] == "e-0001"
    assert e2["event_id"] == "e-0002"
    assert e2["prev_event_id"] == "e-0001"
    assert e2["prev_hash"] == e1["hash"]
    assert e1["hash"] != e2["hash"]


def test_read_events_round_trips(tmp_path):
    session_id = "s-test"
    ev.append_event(session_id, _ai_initial(session_id, "D01"), store_root=tmp_path)
    ev.append_event(session_id, _ai_initial(session_id, "D02", risk="Low"), store_root=tmp_path)

    rows = ev.read_events(session_id, store_root=tmp_path)
    assert [r["difference_id"] for r in rows] == ["D01", "D02"]


def test_fold_review_state_is_a_projection_not_a_mutable_column(tmp_path):
    session_id = "s-test"
    ev.append_event(session_id, _ai_initial(session_id, "D01"), store_root=tmp_path)
    ev.append_event(session_id, _human_review("D01", verdict="TRACK"), store_root=tmp_path)
    # A re-judgement is a NEW appended row, never an edit of the first.
    ev.append_event(session_id, _human_review("D01", verdict="CONFIRMED"), store_root=tmp_path)

    rows = ev.read_events(session_id, store_root=tmp_path)
    assert len(rows) == 3  # nothing was overwritten in place

    state = ev.fold_review_state(rows)
    assert state["D01"]["ai_risk_at_time"] == "High"
    assert state["D01"]["human_verdict"] == "CONFIRMED"  # latest wins
    assert state["D01"]["approval_role_label_snapshot"] == "船舶技術監督（Technical Superintendent）"


def test_integrity_holds_across_legitimate_appends(tmp_path):
    session_id = "s-test"
    integrity_root = tmp_path / ".integrity"
    ev.append_event(session_id, _ai_initial(session_id, "D01"), store_root=tmp_path)
    ev.append_event(session_id, _human_review("D01"), store_root=tmp_path)
    ev.save_anchor(session_id, store_root=tmp_path, integrity_root=integrity_root)

    # Legitimate forward-only growth after the checkpoint.
    ev.append_event(session_id, _ai_initial(session_id, "D02", risk="Low"), store_root=tmp_path)

    result = ev.check_integrity(session_id, store_root=tmp_path, integrity_root=integrity_root)
    assert result.ok is True


def test_integrity_detects_prefix_tamper(tmp_path):
    session_id = "s-test"
    integrity_root = tmp_path / ".integrity"
    ev.append_event(session_id, _ai_initial(session_id, "D01"), store_root=tmp_path)
    ev.append_event(session_id, _human_review("D01"), store_root=tmp_path)
    ev.save_anchor(session_id, store_root=tmp_path, integrity_root=integrity_root)

    # Simulate a hand-edit of the already-checkpointed (frozen) region.
    path = ev.events_path(session_id, tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace("CONFIRMED", "REJECTED") if "CONFIRMED" in lines[0] else lines[0] + " "
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = ev.check_integrity(session_id, store_root=tmp_path, integrity_root=integrity_root)
    assert result.ok is False
    assert "完整性驗證失敗" in result.reason


def test_quarantine_mark_and_acknowledge_never_touch_the_jsonl(tmp_path):
    session_id = "s-test"
    ev.append_event(session_id, _ai_initial(session_id, "D01"), store_root=tmp_path)
    before = ev.events_path(session_id, tmp_path).read_bytes()

    ev.mark_quarantined(session_id, "完整性驗證失敗：歷史稽核區疑遭手改", store_root=tmp_path)
    state = ev.read_sync_state(session_id, store_root=tmp_path)
    assert state["quarantined"] is True

    ev.acknowledge_quarantine(session_id, store_root=tmp_path)
    state = ev.read_sync_state(session_id, store_root=tmp_path)
    assert state["quarantined"] is False

    after = ev.events_path(session_id, tmp_path).read_bytes()
    assert before == after  # quarantine flag never rewrites the audit log itself


def test_export_signoff_is_session_level_and_excluded_from_review_state(tmp_path):
    session_id = "s-test"
    ev.append_event(session_id, _ai_initial(session_id, "D01"), store_root=tmp_path)
    ev.append_event(
        session_id,
        {
            "difference_id": "*",  # session-level sentinel, not a real difference
            "event_type": "EXPORT_SIGNOFF",
            "reviewer_name": "陳○○",
            "approval_role_code": "TECH_SUPT",
            "approval_role_label_snapshot": "船舶技術監督（Technical Superintendent）",
            "reviewer_note": "匯出格式=html；狀態=修訂草稿",
            "data_origin": "computed",
        },
        store_root=tmp_path,
    )
    rows = ev.read_events(session_id, store_root=tmp_path)
    assert len(rows) == 2  # it IS on the log — just not folded into per-difference state

    state = ev.fold_review_state(rows)
    assert "*" not in state
    assert set(state) == {"D01"}


def test_derive_storage_tag_defaults_to_local_without_sync_target(tmp_path):
    session_id = "s-test"
    ev.append_event(session_id, _ai_initial(session_id, "D01"), store_root=tmp_path)
    tag = ev.derive_storage_tag(session_id, store_root=tmp_path)
    assert tag == "本機"
