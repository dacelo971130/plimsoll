"""Upload / inspect / compare / fetch sessions.

`POST /api/sessions` handles BOTH steps of the P1 flow with the same request
shape: drop two files with no version overrides → get `needs_info` back
(FileCard data + missing-field list, nothing persisted yet); resubmit with
the user-filled `old_version`/`new_version` (etc.) → get `created` with a
full session. This mirrors ui-spec §3.3's rule that the compare button stays
disabled until both sides are complete — the frontend just calls the same
endpoint again once the fields are filled in.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel

from backend.api.llm_headers import llm_credentials
from backend.services.llm.credentials import LlmCredentials
from backend.config import REPO_ROOT
from backend.services import session_store

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

DEMO_OLD = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.0.pdf"
DEMO_NEW = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.1.pdf"

# Real third-party documents pulled in for the 2026-09-28 real-document
# smoke test (docs/redesign/plimsoll-real-document-smoketest-2026-09.html) —
# local-only (.gitignored, see that report §8 for the copyright reasoning),
# so `available` below is what lets a fresh clone fall back to just the one
# fixture that actually ships in the repo instead of erroring.
_EXTERNAL_SAMPLES = REPO_ROOT / "data" / "external-samples"
_SPECS = REPO_ROOT / "data" / "specs"


@dataclass(frozen=True)
class DemoFixture:
    id: str
    label: str
    old_path: Path
    new_path: Path
    old_version: str | None = None
    new_version: str | None = None
    old_date: str | None = None
    new_date: str | None = None


DEMO_FIXTURES: list[DemoFixture] = [
    DemoFixture(
        id="main_engine_cooling",
        label="主機冷卻系統維護程序（6 頁合成文件）",
        old_path=DEMO_OLD,
        new_path=DEMO_NEW,
    ),
    DemoFixture(
        id="aircraft_easa",
        label="EASA 波音 737 型別檢定資料表（Issue 24 → 29）",
        old_path=_EXTERNAL_SAMPLES / "aircraft" / "easa_tcds_b737_im120_issue24_2021.pdf",
        new_path=_EXTERNAL_SAMPLES / "aircraft" / "easa_tcds_b737_im120_issue29_2025.pdf",
        old_version="Issue 24 (2021)",
        new_version="Issue 29 (2025)",
    ),
    DemoFixture(
        id="car_unece",
        label="UNECE 車輛構造決議文 R.E.3（Rev.6 → Rev.7）",
        old_path=_EXTERNAL_SAMPLES / "car" / "unece_re3_rev6_2017.pdf",
        new_path=_EXTERNAL_SAMPLES / "car" / "unece_re3_rev7_2023.pdf",
        old_version="Rev.6 (2017)",
        new_version="Rev.7 (2023)",
    ),
    DemoFixture(
        id="bicycle_cfr1512",
        label="美國自行車安全法規 16 CFR 1512（2017 → 2024）",
        old_path=_EXTERNAL_SAMPLES / "bicycle" / "cfr1512_bicycles_2017-01-01.pdf",
        new_path=_EXTERNAL_SAMPLES / "bicycle" / "cfr1512_bicycles_2024-01-01.pdf",
        old_version="2017-01-01",
        new_version="2024-01-01",
    ),
    DemoFixture(
        id="scanned_page_test",
        label="掃描頁測試（合成：一頁文字 vs 一頁掃描影像）",
        old_path=_EXTERNAL_SAMPLES / "scanned-page-test" / "solas_excerpt_text_only.pdf",
        new_path=_EXTERNAL_SAMPLES / "scanned-page-test" / "solas_excerpt_one_page_scanned.pdf",
        old_version="excerpt-text",
        new_version="excerpt-with-scan",
    ),
    DemoFixture(
        id="ship_solas",
        label="IMO SOLAS 海上人命安全公約（2004 → 2020）⚠️ 840 頁，比對約需 4 分鐘",
        old_path=_EXTERNAL_SAMPLES / "ship" / "solas_consolidated_2004.pdf",
        new_path=_EXTERNAL_SAMPLES / "ship" / "solas_consolidated_2020.pdf",
        old_version="SOLAS Consolidated 2004",
        new_version="SOLAS Consolidated 2020",
    ),
    DemoFixture(
        id="ccs_steel_ships",
        label="CCS 鋼船規範（2026 → 2027，目標文件）⚠️ 近 4000 頁，比對約需 4 分鐘",
        old_path=_SPECS / "Rules-for-Steel-Ships_CH_2026_completeset_202512.pdf",
        new_path=_SPECS / "Rules_for_Steel_Ships_2027_CH_completeset.pdf",
        old_version="CCS 鋼船規範 2026",
        new_version="CCS 鋼船規範 2027",
    ),
]

_FIXTURES_BY_ID = {f.id: f for f in DEMO_FIXTURES}


@router.post("")
async def upload_or_create_session(
    old_file: UploadFile = File(...),
    new_file: UploadFile = File(...),
    old_version: str | None = Form(None),
    new_version: str | None = Form(None),
    old_date: str | None = Form(None),
    new_date: str | None = Form(None),
    analysis_mode: Literal["rules_first", "model_heavy", "model_only"] = Form("rules_first"),
    llm: LlmCredentials = Depends(llm_credentials),
):
    old_bytes = await old_file.read()
    new_bytes = await new_file.read()
    return session_store.process_upload(
        old_bytes,
        old_file.filename or "old.pdf",
        new_bytes,
        new_file.filename or "new.pdf",
        old_version_override=old_version,
        new_version_override=new_version,
        old_date_override=old_date,
        new_date_override=new_date,
        analysis_mode=analysis_mode,
        llm=llm,
    )


@router.get("/demo-fixtures")
def list_demo_fixtures():
    """Which demo pairs the picker can offer — `available` is false for a
    fixture whose files aren't on this machine (external-samples is
    .gitignored, so a fresh clone only ever has `main_engine_cooling`)."""
    return {
        "data_origin": "computed",
        "fixtures": [
            {"id": f.id, "label": f.label, "available": f.old_path.exists() and f.new_path.exists()}
            for f in DEMO_FIXTURES
        ],
    }


@router.post("/demo")
def create_demo_session(
    demo_id: str = Form("main_engine_cooling"),
    analysis_mode: Literal["rules_first", "model_heavy", "model_only"] = Form("rules_first"),
    llm: LlmCredentials = Depends(llm_credentials),
):
    fixture = _FIXTURES_BY_ID.get(demo_id)
    if fixture is None:
        raise HTTPException(status_code=404, detail=f"Unknown demo fixture: {demo_id!r}")
    if not (fixture.old_path.exists() and fixture.new_path.exists()):
        raise HTTPException(status_code=404, detail=f"Demo fixture files missing on disk: {fixture.id}")
    return session_store.process_upload(
        fixture.old_path.read_bytes(),
        fixture.old_path.name,
        fixture.new_path.read_bytes(),
        fixture.new_path.name,
        old_version_override=fixture.old_version,
        new_version_override=fixture.new_version,
        old_date_override=fixture.old_date,
        new_date_override=fixture.new_date,
        analysis_mode=analysis_mode,
        llm=llm,
    )


@router.get("")
def list_sessions():
    return {"data_origin": "computed", "sessions": session_store.list_sessions()}


@router.get("/{session_id}")
def get_session(session_id: str):
    session = session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return session


@router.delete("")
def delete_all_sessions():
    """HistoryRail's "清除全部" — user-confirmed client-side before this is
    ever called (see the frontend's ClearHistoryDialog)."""
    count = session_store.delete_all_sessions()
    return {"data_origin": "computed", "deleted_count": count}


@router.delete("/{session_id}")
def delete_session(session_id: str):
    deleted = session_store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return {"data_origin": "computed", "deleted": True}


@router.post("/{session_id}/semantic-preview")
def semantic_preview(session_id: str, llm: LlmCredentials = Depends(llm_credentials)):
    """W7a, explicitly opt-in — never triggered by session creation itself.
    Returns the session's differences with `ai_semantic_suggestion` filled
    in wherever the deterministic trigger (default rule + large edit)
    selected them and a provider is configured; `semantic_layer_available`
    tells the frontend whether to show the feature at all."""
    result = session_store.preview_semantic_suggestions(session_id, llm=llm)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return {"data_origin": "computed", **result}


@router.post("/{session_id}/suggest-aliases")
def suggest_aliases(session_id: str, llm: LlmCredentials = Depends(llm_credentials)):
    """P5 term_aliases 核准流程 step 1 — proposes candidates from this
    session's clarification-type residuals and queues them for approval via
    /api/term-aliases/pending. Opt-in like semantic-preview; never called
    automatically."""
    result = session_store.suggest_aliases_for_session(session_id, llm=llm)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return {"data_origin": "computed", **result}


@router.get("/{session_id}/pages")
def get_session_pages(session_id: str):
    pages = session_store.get_pages(session_id)
    if pages is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return {"data_origin": "computed", **pages}


@router.get("/{session_id}/cost-estimate")
def get_session_cost_estimate(session_id: str):
    """P6 成本試算, real-document version (CostEstimatorModal.tsx) — read-
    only, no LLM call, safe to call as often as the modal opens."""
    result = session_store.estimate_cost(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return {"data_origin": "computed", **result}


@router.get("/{session_id}/pdf/{side}")
def get_session_pdf(session_id: str, side: Literal["old", "new"]):
    """Backs the 「原始 PDF」原文模式 (ui-spec §3.3) — `<embed>`-able raw PDF."""
    pdf_bytes = session_store.get_pdf(session_id, side)
    if pdf_bytes is None:
        raise HTTPException(status_code=404, detail="原檔未保存，請重新上傳或同步到伺服器")
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": "inline"})


class ReviewEventRequest(BaseModel):
    difference_id: str
    human_verdict: Literal["CONFIRMED", "TRACK", "REJECTED"]
    reviewer_name: str
    approval_role_code: str
    reviewer_note: str = ""
    risk_override: Literal["High", "Medium", "Low"] | None = None


@router.post("/{session_id}/review-events")
def submit_review_event(session_id: str, payload: ReviewEventRequest):
    """ReviewBar's "確認並前往下一筆" — writes one append-only HUMAN_REVIEW
    event. `approval_policies` is enforced here, server-side, before the
    event is ever written (v4 決定 #3 — not just a UI hint)."""
    try:
        result = session_store.submit_review_event(
            session_id,
            difference_id=payload.difference_id,
            human_verdict=payload.human_verdict,
            reviewer_name=payload.reviewer_name,
            approval_role_code=payload.approval_role_code,
            reviewer_note=payload.reviewer_note,
            risk_override=payload.risk_override,
        )
    except session_store.SessionNotFound:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except session_store.DifferenceNotFound:
        raise HTTPException(status_code=404, detail=f"Difference {payload.difference_id} not found")
    except session_store.MissingReviewerName as err:
        raise HTTPException(status_code=400, detail=str(err))
    except session_store.UnknownApprovalRole:
        raise HTTPException(status_code=400, detail=f"Unknown approval_role_code: {payload.approval_role_code}")
    except session_store.ReviewNotAuthorized as err:
        raise HTTPException(status_code=403, detail=str(err))

    return {"data_origin": "computed", **result}


class ExportRequest(BaseModel):
    format: Literal["html", "docx", "pdf"]
    reviewer_name: str
    approval_role_code: str
    report_no: str = ""
    dept: str = ""
    acknowledge_draft: bool = False


@router.post("/{session_id}/export")
def export_session(session_id: str, payload: ExportRequest):
    """情境四 Human Control: unreviewed High-risk items never block export
    outright — they require `acknowledge_draft=true` first (HTTP 428 until
    then, with the exact list so the frontend's UnreviewedExportGuard can
    render it), and the resulting file is watermarked "修訂草稿"."""
    try:
        content, media_type, filename = session_store.export_session(
            session_id,
            fmt=payload.format,
            reviewer_name=payload.reviewer_name,
            approval_role_code=payload.approval_role_code,
            report_no=payload.report_no,
            dept=payload.dept,
            acknowledge_draft=payload.acknowledge_draft,
        )
    except session_store.SessionNotFound:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except session_store.MissingReviewerName as err:
        raise HTTPException(status_code=400, detail=str(err))
    except session_store.UnknownApprovalRole:
        raise HTTPException(status_code=400, detail=f"Unknown approval_role_code: {payload.approval_role_code}")
    except session_store.ExportRequiresAcknowledgement as err:
        raise HTTPException(
            status_code=428,
            detail={
                "message": str(err),
                "unreviewed_high": [{"id": d["id"], "explanation": d["explanation"]} for d in err.unreviewed_high],
            },
        )

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
