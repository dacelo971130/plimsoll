"""P1 session-store tests: needs_info vs created, and that every persisted
difference gets exactly one AI_INITIAL audit event (§21 backbone wired to
real session creation)."""

from __future__ import annotations

import json
import shutil

import fitz
import pytest

from backend.config import REPO_ROOT, SESSIONS_ROOT
from backend.services import session_store
from backend.storage import events as event_store

DEMO_OLD = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.0.pdf"
DEMO_NEW = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.1.pdf"

pytestmark = pytest.mark.skipif(
    not (DEMO_OLD.exists() and DEMO_NEW.exists()), reason="run scripts/generate_demo_pdfs.py first"
)


def _make_plain_text_pdf(text: str) -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((50, 72), text)
    return doc.tobytes()


def _make_two_page_pdf_with_diagram(n_extra_lines: int) -> bytes:
    """Page 1 has real metadata text (so version/date are found); page 2 is a
    vector-heavy, text-free engineering-drawing page (P5 §26 `diagram` kind)."""
    doc = fitz.open()
    meta_page = doc.new_page()
    # ASCII-only metadata line (English regex path) — insert_text's default
    # base-14 font has no CJK glyphs, and registering one isn't needed here.
    meta_page.insert_text((50, 72), "Version: v1.0 | Issue date: 2026-01-01")
    diagram_page = doc.new_page()
    shape = diagram_page.new_shape()
    for i in range(60):
        shape.draw_line((10, 10 + i * 5), (400, 10 + i * 5))
    for i in range(n_extra_lines):
        shape.draw_line((450, 10 + i * 5), (500, 10 + i * 5))
    shape.finish(color=(0, 0, 0), width=0.5)
    shape.commit()
    return doc.tobytes()


@pytest.fixture
def cleanup_sessions():
    created: list[str] = []
    yield created
    for session_id in created:
        shutil.rmtree(SESSIONS_ROOT / session_id, ignore_errors=True)


def test_demo_upload_creates_a_session_with_events_matching_differences(cleanup_sessions):
    result = session_store.process_upload(
        DEMO_OLD.read_bytes(), "old.pdf", DEMO_NEW.read_bytes(), "new.pdf"
    )
    assert result["status"] == "created"
    session = result["session"]
    cleanup_sessions.append(session["session_id"])

    assert len(session["differences"]) >= 5
    assert session["storage_tag"] == "本機"

    events = event_store.read_events(session["session_id"])
    assert len(events) == len(session["differences"])
    assert all(e["event_type"] == "AI_INITIAL" for e in events)
    assert {e["difference_id"] for e in events} == {d["id"] for d in session["differences"]}

    # differences.json / session.json / pages.json are all on disk as specified.
    session_dir = SESSIONS_ROOT / session["session_id"]
    assert (session_dir / "session.json").exists()
    assert (session_dir / "differences.json").exists()
    assert (session_dir / "pages.json").exists()
    pages = json.loads((session_dir / "pages.json").read_text(encoding="utf-8"))
    # W2: v1.1 has one more page than v1.0 (a whole new closing section).
    assert len(pages["old"]) == 6 and len(pages["new"]) == 7


def test_missing_version_returns_needs_info_without_creating_a_session():
    before = set(p.name for p in SESSIONS_ROOT.iterdir()) if SESSIONS_ROOT.exists() else set()

    result = session_store.process_upload(
        _make_plain_text_pdf("No version marker here."),
        "mystery-old.pdf",
        DEMO_NEW.read_bytes(),
        "new.pdf",
    )
    assert result["status"] == "needs_info"
    assert "version" in result["old_meta"]["missing_fields"]
    assert result["new_meta"]["is_complete"] is True

    after = set(p.name for p in SESSIONS_ROOT.iterdir()) if SESSIONS_ROOT.exists() else set()
    assert after == before  # nothing persisted — R1: never guess, never half-create


def test_supplying_the_missing_version_unblocks_creation(cleanup_sessions):
    result = session_store.process_upload(
        _make_plain_text_pdf("No version marker here."),
        "mystery-old.pdf",
        DEMO_NEW.read_bytes(),
        "new.pdf",
        old_version_override="v0.9-draft",
        old_date_override="2026-01-01",
    )
    assert result["status"] == "created"
    cleanup_sessions.append(result["session"]["session_id"])
    assert result["session"]["old_meta"]["version"] == "v0.9-draft"
    # title was never supplied — creation isn't blocked by it (only a missing
    # VERSION gates the compare button, per ui-spec §3.3), but it's still
    # honestly reported rather than silently dropped.
    assert result["session"]["old_meta"]["missing_fields"] == ["title"]


def test_get_session_and_list_sessions_round_trip(cleanup_sessions):
    result = session_store.process_upload(DEMO_OLD.read_bytes(), "old.pdf", DEMO_NEW.read_bytes(), "new.pdf")
    session_id = result["session"]["session_id"]
    cleanup_sessions.append(session_id)

    fetched = session_store.get_session(session_id)
    assert fetched is not None
    assert fetched["session_id"] == session_id

    listed = session_store.list_sessions()
    assert any(s["session_id"] == session_id for s in listed)

    assert session_store.get_session("s-doesnotexist") is None


def test_source_pdfs_are_stashed_and_fetchable(cleanup_sessions):
    result = session_store.process_upload(DEMO_OLD.read_bytes(), "old.pdf", DEMO_NEW.read_bytes(), "new.pdf")
    session_id = result["session"]["session_id"]
    cleanup_sessions.append(session_id)

    assert session_store.get_pdf(session_id, "old") == DEMO_OLD.read_bytes()
    assert session_store.get_pdf(session_id, "new") == DEMO_NEW.read_bytes()
    assert session_store.get_pdf(session_id, "sideways") is None
    assert session_store.get_pdf("s-doesnotexist", "old") is None


def test_preview_semantic_suggestions_is_unavailable_without_a_provider(cleanup_sessions, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = session_store.process_upload(DEMO_OLD.read_bytes(), "old.pdf", DEMO_NEW.read_bytes(), "new.pdf")
    session_id = result["session"]["session_id"]
    cleanup_sessions.append(session_id)

    preview = session_store.preview_semantic_suggestions(session_id)
    assert preview["semantic_layer_available"] is False
    assert preview["differences"] == result["session"]["differences"]  # unchanged, byte-for-byte


def test_preview_semantic_suggestions_is_none_for_unknown_session():
    assert session_store.preview_semantic_suggestions("s-doesnotexist") is None


def test_analysis_mode_defaults_to_rules_first_and_is_persisted(cleanup_sessions):
    result = session_store.process_upload(DEMO_OLD.read_bytes(), "old.pdf", DEMO_NEW.read_bytes(), "new.pdf")
    session_id = result["session"]["session_id"]
    cleanup_sessions.append(session_id)
    assert result["session"]["analysis_mode"] == "rules_first"


def test_unknown_analysis_mode_is_rejected():
    with pytest.raises(ValueError):
        session_store.process_upload(
            DEMO_OLD.read_bytes(), "old.pdf", DEMO_NEW.read_bytes(), "new.pdf", analysis_mode="not_a_real_mode"
        )


def test_model_only_analysis_mode_widens_semantic_review_on_preview(cleanup_sessions, monkeypatch):
    from backend.services.llm.schemas import ResidualSuggestion

    class _FakeProvider:
        model_id = "fake-model"
        provider_name = "fake"

        def classify_residual(self, old_text, new_text, *, effort="medium"):
            return ResidualSuggestion(
                semantic_change_type="clarification", suggest_escalate=False, rationale="用詞更精確，語意未變"
            )

    monkeypatch.setattr("backend.services.llm.provider.get_llm_provider", lambda: _FakeProvider())

    result = session_store.process_upload(
        DEMO_OLD.read_bytes(), "old.pdf", DEMO_NEW.read_bytes(), "new.pdf", analysis_mode="model_only"
    )
    session_id = result["session"]["session_id"]
    cleanup_sessions.append(session_id)
    assert result["session"]["analysis_mode"] == "model_only"

    preview = session_store.preview_semantic_suggestions(session_id)
    assert preview["semantic_layer_available"] is True
    modifications = [d for d in preview["differences"] if d["change_type"] == "修改" and d.get("kind") != "drawing"]
    # model_only: every text 修改 gets a suggestion, regardless of rule_id.
    assert modifications  # sanity: the demo pair actually has some
    assert all(d["ai_semantic_suggestion"] is not None for d in modifications)

    events = event_store.read_events(session_id)
    ai_events = [e for e in events if e["event_type"] == "AI_INITIAL" and e.get("provider") == "fake"]
    assert ai_events and all(e["analysis_mode"] == "model_only" for e in ai_events)


def test_diagram_page_produces_a_drawing_difference_end_to_end(cleanup_sessions, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # no vision description — pure pixel diff
    old_bytes = _make_two_page_pdf_with_diagram(n_extra_lines=0)
    new_bytes = _make_two_page_pdf_with_diagram(n_extra_lines=20)

    result = session_store.process_upload(old_bytes, "old.pdf", new_bytes, "new.pdf")
    assert result["status"] == "created"
    session = result["session"]
    cleanup_sessions.append(session["session_id"])

    drawing_diffs = [d for d in session["differences"] for _ in [None] if d.get("kind") == "drawing"]
    assert len(drawing_diffs) == 1
    drawing = drawing_diffs[0]
    assert drawing["page_alignment"] == "matched"
    assert len(drawing["regions"]) >= 1
    assert drawing["regions"][0]["old_crop_png_b64"]

    # every difference — text or drawing — still gets exactly one AI_INITIAL event
    events = event_store.read_events(session["session_id"])
    assert {e["difference_id"] for e in events} == {d["id"] for d in session["differences"]}

    # non-drawing differences keep the "text" discriminator (back-compat)
    assert all(d["kind"] == "text" for d in session["differences"] if d["id"] != drawing["id"])


def test_preview_semantic_suggestions_enriches_and_appends_a_provenance_event(cleanup_sessions, monkeypatch):
    from backend.services.llm.schemas import ResidualSuggestion

    class _FakeProvider:
        model_id = "fake-model"
        provider_name = "fake"

        def classify_residual(self, old_text, new_text, *, effort="medium"):
            return ResidualSuggestion(
                semantic_change_type="clarification", suggest_escalate=False, rationale="用詞更精確，語意未變"
            )

    monkeypatch.setattr("backend.services.llm.provider.get_llm_provider", lambda: _FakeProvider())

    result = session_store.process_upload(DEMO_OLD.read_bytes(), "old.pdf", DEMO_NEW.read_bytes(), "new.pdf")
    session_id = result["session"]["session_id"]
    cleanup_sessions.append(session_id)
    before_event_count = len(event_store.read_events(session_id))

    preview = session_store.preview_semantic_suggestions(session_id)
    assert preview["semantic_layer_available"] is True
    enriched = [d for d in preview["differences"] if d.get("ai_semantic_suggestion")]
    assert len(enriched) >= 1
    for d in enriched:
        assert d["ai_semantic_suggestion"]["semantic_change_type"] == "clarification"
        assert d["data_origin"] == "ai_inferred"

    after_events = event_store.read_events(session_id)
    assert len(after_events) == before_event_count + len(enriched)
    new_events = after_events[before_event_count:]
    assert all(e["event_type"] == "AI_INITIAL" and e["provider"] == "fake" for e in new_events)

    # differences.json itself must stay untouched (write-once invariant).
    stored = session_store.get_session(session_id)["differences"]
    assert all(d.get("ai_semantic_suggestion") is None for d in stored)


class TestSubmitReviewEvent:
    @pytest.fixture
    def session(self, cleanup_sessions):
        result = session_store.process_upload(DEMO_OLD.read_bytes(), "old.pdf", DEMO_NEW.read_bytes(), "new.pdf")
        cleanup_sessions.append(result["session"]["session_id"])
        return result["session"]

    def test_authorized_role_writes_a_human_review_event(self, session):
        high_diff = next(d for d in session["differences"] if d["ai_risk"] == "High")

        result = session_store.submit_review_event(
            session["session_id"],
            difference_id=high_diff["id"],
            human_verdict="CONFIRMED",
            reviewer_name="陳○○",
            approval_role_code="TECH_SUPT",  # policy ceiling High -> allowed
            reviewer_note="已核對新版頁碼",
        )
        assert result["event"]["event_type"] == "HUMAN_REVIEW"
        assert result["event"]["approval_role_label_snapshot"] == "船舶技術監督（Technical Superintendent）"

        review_state = result["session"]["review_state"][high_diff["id"]]
        assert review_state["human_verdict"] == "CONFIRMED"
        assert review_state["reviewer_name"] == "陳○○"

    def test_role_over_its_policy_ceiling_is_denied_and_never_written(self, session):
        high_diff = next(d for d in session["differences"] if d["ai_risk"] == "High")
        events_before = event_store.read_events(session["session_id"])

        with pytest.raises(session_store.ReviewNotAuthorized):
            session_store.submit_review_event(
                session["session_id"],
                difference_id=high_diff["id"],
                human_verdict="CONFIRMED",
                reviewer_name="王○○",
                approval_role_code="OTHER",  # policy ceiling Low -> denied for High
            )

        events_after = event_store.read_events(session["session_id"])
        assert events_after == events_before  # denied review never touches the log

    def test_risk_override_is_checked_against_the_overridden_risk_not_the_original(self, session):
        low_diff = next(d for d in session["differences"] if d["ai_risk"] == "Low")

        # FLEET_MGR's ceiling is Medium — fine for the original Low risk, but
        # escalating the override to High must be re-checked against High,
        # not silently approved because the original was Low.
        with pytest.raises(session_store.ReviewNotAuthorized):
            session_store.submit_review_event(
                session["session_id"],
                difference_id=low_diff["id"],
                human_verdict="CONFIRMED",
                reviewer_name="李○○",
                approval_role_code="FLEET_MGR",
                risk_override="High",
            )

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_reviewer_name_is_rejected_and_never_written(self, session, blank):
        # The UI's Enter shortcut once skipped the identity check ReviewBar's
        # button had; the server must refuse regardless of which path sent it.
        diff = session["differences"][0]
        events_before = event_store.read_events(session["session_id"])

        with pytest.raises(session_store.MissingReviewerName):
            session_store.submit_review_event(
                session["session_id"],
                difference_id=diff["id"],
                human_verdict="CONFIRMED",
                reviewer_name=blank,
                approval_role_code="DPA",
            )

        assert event_store.read_events(session["session_id"]) == events_before

    def test_unknown_role_is_rejected(self, session):
        diff = session["differences"][0]
        with pytest.raises(session_store.UnknownApprovalRole):
            session_store.submit_review_event(
                session["session_id"],
                difference_id=diff["id"],
                human_verdict="CONFIRMED",
                reviewer_name="X",
                approval_role_code="NOT_A_REAL_ROLE",
            )

    def test_unknown_difference_is_rejected(self, session):
        with pytest.raises(session_store.DifferenceNotFound):
            session_store.submit_review_event(
                session["session_id"],
                difference_id="D99",
                human_verdict="CONFIRMED",
                reviewer_name="X",
                approval_role_code="DPA",
            )

    def test_unknown_session_is_rejected(self):
        with pytest.raises(session_store.SessionNotFound):
            session_store.submit_review_event(
                "s-doesnotexist",
                difference_id="D01",
                human_verdict="CONFIRMED",
                reviewer_name="X",
                approval_role_code="DPA",
            )

    def test_a_rejudgement_appends_rather_than_overwrites(self, session):
        diff = session["differences"][0]
        session_store.submit_review_event(
            session["session_id"], difference_id=diff["id"], human_verdict="TRACK",
            reviewer_name="陳○○", approval_role_code="DPA",
        )
        result = session_store.submit_review_event(
            session["session_id"], difference_id=diff["id"], human_verdict="CONFIRMED",
            reviewer_name="陳○○", approval_role_code="DPA",
        )
        events = [e for e in event_store.read_events(session["session_id"]) if e["difference_id"] == diff["id"]]
        # AI_INITIAL + two HUMAN_REVIEW rows — the first TRACK verdict is
        # still in the log, just superseded by fold projection, never erased.
        assert len(events) == 3
        assert result["session"]["review_state"][diff["id"]]["human_verdict"] == "CONFIRMED"
