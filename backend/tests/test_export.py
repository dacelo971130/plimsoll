"""P4 export tests: draft watermarking / UnreviewedExportGuard enforcement,
the three report formats, and the EXPORT_SIGNOFF audit event."""

from __future__ import annotations

import shutil

import pytest

from backend.config import REPO_ROOT, SESSIONS_ROOT
from backend.services import session_store
from backend.storage import events as event_store

DEMO_OLD = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.0.pdf"
DEMO_NEW = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.1.pdf"

pytestmark = pytest.mark.skipif(
    not (DEMO_OLD.exists() and DEMO_NEW.exists()), reason="run scripts/generate_demo_pdfs.py first"
)


@pytest.fixture
def cleanup_sessions():
    created: list[str] = []
    yield created
    for session_id in created:
        shutil.rmtree(SESSIONS_ROOT / session_id, ignore_errors=True)


@pytest.fixture
def session(cleanup_sessions):
    result = session_store.process_upload(DEMO_OLD.read_bytes(), "old.pdf", DEMO_NEW.read_bytes(), "new.pdf")
    cleanup_sessions.append(result["session"]["session_id"])
    return result["session"]


def test_export_of_a_fully_high_unreviewed_session_requires_acknowledgement(session):
    with pytest.raises(session_store.ExportRequiresAcknowledgement) as excinfo:
        session_store.export_session(
            session["session_id"], fmt="html", reviewer_name="陳○○", approval_role_code="TECH_SUPT"
        )
    # every High-risk difference is unreviewed right after creation (only AI_INITIAL exists)
    high_ids = {d["id"] for d in session["differences"] if d["ai_risk"] == "High"}
    assert {d["id"] for d in excinfo.value.unreviewed_high} == high_ids

    # a rejected export attempt must never write anything to the audit log.
    events_before = event_store.read_events(session["session_id"])
    with pytest.raises(session_store.ExportRequiresAcknowledgement):
        session_store.export_session(
            session["session_id"], fmt="html", reviewer_name="陳○○", approval_role_code="TECH_SUPT"
        )
    assert event_store.read_events(session["session_id"]) == events_before


def test_acknowledging_the_draft_produces_a_watermarked_report_and_signoff_event(session):
    content, media_type, filename = session_store.export_session(
        session["session_id"],
        fmt="html",
        reviewer_name="陳○○",
        approval_role_code="TECH_SUPT",
        report_no="RPT-001",
        dept="工程部",
        acknowledge_draft=True,
    )
    assert media_type == "text/html"
    assert "draft" in filename
    html = content.decode("utf-8")
    assert "修訂草稿" in html
    assert "RPT-001" in html
    assert "船舶技術監督" in html  # role_label_snapshot rendered, not the raw code

    events = event_store.read_events(session["session_id"])
    signoff = [e for e in events if e["event_type"] == "EXPORT_SIGNOFF"]
    assert len(signoff) == 1
    assert signoff[0]["difference_id"] == "*"
    assert "修訂草稿" in signoff[0]["reviewer_note"]

    # EXPORT_SIGNOFF must never leak into per-difference review_state.
    refreshed = session_store.get_session(session["session_id"])
    assert "*" not in refreshed["review_state"]


def test_export_is_not_watermarked_once_every_high_item_is_confirmed(session):
    for d in session["differences"]:
        if d["ai_risk"] == "High":
            session_store.submit_review_event(
                session["session_id"],
                difference_id=d["id"],
                human_verdict="CONFIRMED",
                reviewer_name="陳○○",
                approval_role_code="TECH_SUPT",
            )

    # no acknowledge_draft needed now — nothing left to acknowledge.
    content, _, filename = session_store.export_session(
        session["session_id"], fmt="html", reviewer_name="陳○○", approval_role_code="TECH_SUPT"
    )
    assert "final" in filename
    assert "修訂草稿" not in content.decode("utf-8")


def test_docx_and_pdf_formats_produce_nonempty_binary_output(session):
    docx_bytes, docx_media, docx_name = session_store.export_session(
        session["session_id"],
        fmt="docx",
        reviewer_name="陳○○",
        approval_role_code="TECH_SUPT",
        acknowledge_draft=True,
    )
    assert docx_name.endswith(".docx")
    assert docx_media == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert docx_bytes[:2] == b"PK"  # docx is a zip container

    pdf_bytes, pdf_media, pdf_name = session_store.export_session(
        session["session_id"],
        fmt="pdf",
        reviewer_name="陳○○",
        approval_role_code="TECH_SUPT",
        acknowledge_draft=True,
    )
    assert pdf_name.endswith(".pdf")
    assert pdf_media == "application/pdf"
    assert pdf_bytes[:5] == b"%PDF-"


def test_unknown_format_and_unknown_role_are_rejected(session):
    with pytest.raises(ValueError):
        session_store.export_session(
            session["session_id"], fmt="csv", reviewer_name="X", approval_role_code="DPA", acknowledge_draft=True
        )
    with pytest.raises(session_store.UnknownApprovalRole):
        session_store.export_session(
            session["session_id"],
            fmt="html",
            reviewer_name="X",
            approval_role_code="NOT_A_ROLE",
            acknowledge_draft=True,
        )


def test_export_on_unknown_session_is_rejected():
    with pytest.raises(session_store.SessionNotFound):
        session_store.export_session(
            "s-doesnotexist", fmt="html", reviewer_name="X", approval_role_code="DPA", acknowledge_draft=True
        )


# ---- appendix: 待確認事項 + 名詞解釋 (plimsoll-review-agent-spec.md §4.5) ----

from backend.models.config_models import Glossary  # noqa: E402
from backend.services import export as export_service  # noqa: E402


def _glossary(status: str, *terms: tuple[str, list[str], str]) -> Glossary:
    return Glossary(
        version="v1",
        status=status,
        terms=[
            {"term": t, "aliases": aliases, "category": "c", "definition": f"{t} 的受控定義", "sources": ["x"], "status": term_status}
            for t, aliases, term_status in terms
        ],
    )


def test_appendix_lists_unreviewed_highs_and_tracked_items(session):
    fresh = session_store.get_session(session["session_id"])
    fresh["review_state"]["D04"]["human_verdict"] = "TRACK"
    appendix = export_service.build_appendix(fresh, is_draft=True, glossary=None)
    items = dict(appendix.pending)
    assert items["D01（High）"] == "尚未覆核"
    assert items["D04（Low）"] == "覆核人標為「需追蹤」"
    assert sum(1 for item, _ in appendix.pending if item.endswith("（High）")) == 8


def test_appendix_reports_missing_metadata_and_scanned_pages(session):
    fresh = session_store.get_session(session["session_id"])
    fresh["new_meta"]["missing_fields"] = ["version", "date"]
    fresh["scanned_old"] = [2]
    items = dict(export_service.build_appendix(fresh, is_draft=False, glossary=None).pending)
    assert items["新版文件資訊"] == "缺少版本號、發布日期"
    assert items["舊版 p.2"].startswith("疑似掃描頁")


def test_draft_glossary_is_never_cited(session):
    fresh = session_store.get_session(session["session_id"])
    appendix = export_service.build_appendix(fresh, is_draft=True, glossary=_glossary("draft", ("風險等級", ["High"], "approved")))
    assert appendix.glossary == []
    assert appendix.glossary_note == "詞彙表尚未經人工核准，本報告暫不附名詞解釋。"


def test_approved_glossary_defines_only_terms_the_report_uses(session):
    fresh = session_store.get_session(session["session_id"])
    table = _glossary(
        "approved",
        ("風險等級", ["High", "Medium", "Low"], "approved"),
        ("受影響設備／流程", [], "approved"),  # report header uses a half-width slash
        ("鏈式比對", [], "approved"),  # nowhere in a two-document report
        ("需追蹤", [], "pending"),
    )
    fresh["review_state"]["D04"]["human_verdict"] = "TRACK"
    appendix = export_service.build_appendix(fresh, is_draft=False, glossary=table)
    assert [term for term, _ in appendix.glossary] == ["風險等級", "受影響設備／流程"]
    assert ("名詞「需追蹤」", "定義尚未定案") in appendix.pending


def test_all_three_formats_carry_the_appendix(session, monkeypatch):
    monkeypatch.setattr(export_service, "_load_glossary", lambda: _glossary("approved", ("風險等級", ["High"], "approved")))
    fresh = session_store.get_session(session["session_id"])
    meta = export_service.ExportMeta(
        reviewer_name="測試", approval_role_code="TECH_SUPT", role_label="船舶技術監督",
        report_no="R-1", dept="工務", is_draft=True, exported_at="2026-09-28T00:00:00Z",
    )
    html_doc = export_service.build_html_report(fresh, meta).decode("utf-8")
    assert "待確認事項" in html_doc and "名詞解釋" in html_doc and "風險等級 的受控定義" in html_doc

    import io
    from docx import Document

    docx_text = "\n".join(p.text for p in Document(io.BytesIO(export_service.build_docx_report(fresh, meta))).paragraphs)
    assert "待確認事項" in docx_text and "風險等級 的受控定義" in docx_text

    assert export_service.build_pdf_report(fresh, meta)[:5] == b"%PDF-"


# ---- PDF layout / markup safety (real-document smoke test, s-4b1fdf8c) ----


def _meta(is_draft: bool = True) -> export_service.ExportMeta:
    return export_service.ExportMeta(
        reviewer_name="測試", approval_role_code="TECH_SUPT", role_label="船舶技術監督",
        report_no="R-1", dept="工務", is_draft=is_draft, exported_at="2026-09-28T00:00:00Z",
    )


def _pdf_text(pdf_bytes: bytes) -> str:
    import pymupdf

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return " ".join(page.get_text() for page in doc)


def test_pdf_splits_a_source_cell_taller_than_a_page(session):
    # A whole-section delete in a real document put 2846 characters into one
    # 38 mm cell — a ~1080 pt row on a 526 pt frame, which used to be a
    # LayoutError (export 500). The row must break across pages, uncut.
    fresh = session_store.get_session(session["session_id"])
    target = next(d for d in fresh["differences"] if d["old"])
    target["old"]["text"] = "Liferaft capacity approval text. " * 90 + "END-OF-LONG-CELL"
    pdf = export_service.build_pdf_report(fresh, _meta())
    assert pdf[:5] == b"%PDF-"
    assert "END-OF-LONG-CELL" in _pdf_text(pdf)


def test_pdf_renders_markup_characters_in_source_text_verbatim(session):
    fresh = session_store.get_session(session["session_id"])
    target = next(d for d in fresh["differences"] if d["old"])
    target["old"]["text"] = "if x<y then stop; valve A&B open"
    target["explanation"] = "pressure<br>limit"
    fresh["title"] = "Manual <b>v2</b>"
    text = _pdf_text(export_service.build_pdf_report(fresh, _meta()))
    assert "x<y" in text and "A&B" in text and "pressure<br>limit" in text and "<b>v2</b>" in text


def test_html_escapes_the_pdf_page_label(session):
    # print_label is the uploaded PDF's own PageLabels string — document
    # content, not something Plimsoll wrote.
    fresh = session_store.get_session(session["session_id"])
    target = next(d for d in fresh["differences"] if d["old"])
    target["old"]["page"]["print_label"] = "<img src=x onerror=alert(1)>"
    html_doc = export_service.build_html_report(fresh, _meta()).decode("utf-8")
    assert "<img src=x" not in html_doc
    assert "&lt;img src=x onerror=alert(1)&gt;" in html_doc
