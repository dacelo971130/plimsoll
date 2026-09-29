"""Chain endpoints (W5/W6/W8): build a chain from N ordered PDF versions,
read one back, and record a chain-level review. Thin wrappers over
backend.services.chain — no comparison/session logic lives here."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.api.llm_headers import llm_credentials
from backend.config import REPO_ROOT
from backend.services import chain as chain_service
from backend.services import session_store
from backend.services.llm.batch_jobs import BatchNotFound, get_batch_ledger, poll_batch, submit_batch
from backend.services.llm.provider import LlmUnavailable

router = APIRouter(prefix="/api/chains", tags=["chains"])

DEMO_CHAIN_FILES = [REPO_ROOT / "data" / "demo" / f"Main_Engine_Cooling_v1.{i}.pdf" for i in range(5)]


@router.post("")
async def create_chain(files: list[UploadFile] = File(...)):
    """`files` must be uploaded in version order (v1 first) — a chain never
    guesses version order any more than a pairwise session guesses a
    version string."""
    if len(files) < 2:
        raise HTTPException(status_code=400, detail="A chain needs at least 2 versions")
    pdf_versions = [(await f.read(), f.filename or f"version-{i}.pdf") for i, f in enumerate(files)]
    try:
        result = chain_service.build_chain(pdf_versions)
    except chain_service.ChainVersionMissing as err:
        raise HTTPException(status_code=422, detail=str(err))
    except chain_service.ChainStepFailed as err:
        raise HTTPException(status_code=422, detail=str(err))
    return {
        "chain_id": result["chain_id"],
        "manifest": result["manifest"],
        "parameter_series": result["parameter_series"],
        "drift_report": result["drift_report"],
    }


@router.post("/demo")
def create_demo_chain():
    if not all(p.exists() for p in DEMO_CHAIN_FILES):
        raise HTTPException(status_code=404, detail="Demo chain PDFs missing. Run scripts/generate_demo_pdfs.py first.")
    pdf_versions = [(p.read_bytes(), p.name) for p in DEMO_CHAIN_FILES]
    result = chain_service.build_chain(pdf_versions)
    return {
        "chain_id": result["chain_id"],
        "manifest": result["manifest"],
        "parameter_series": result["parameter_series"],
        "drift_report": result["drift_report"],
    }


@router.get("/{chain_id}")
def get_chain(chain_id: str):
    chain = chain_service.get_chain(chain_id)
    if chain is None:
        raise HTTPException(status_code=404, detail=f"Chain {chain_id} not found")
    return chain


class ChainReviewRequest(BaseModel):
    human_verdict: Literal["CONFIRMED", "TRACK", "REJECTED"]
    reviewer_name: str
    approval_role_code: str
    reviewer_note: str = ""


@router.post("/{chain_id}/review-events")
def submit_chain_review(chain_id: str, payload: ChainReviewRequest):
    """One judgement over the whole chain (e.g. "v1→v5 累積變化已確認為刻意調
    整") instead of forcing a sign-off per pairwise session (§02)."""
    try:
        result = chain_service.submit_chain_review(
            chain_id,
            human_verdict=payload.human_verdict,
            reviewer_name=payload.reviewer_name,
            approval_role_code=payload.approval_role_code,
            reviewer_note=payload.reviewer_note,
        )
    except session_store.SessionNotFound:
        raise HTTPException(status_code=404, detail=f"Chain {chain_id} not found")
    except session_store.MissingReviewerName as err:
        raise HTTPException(status_code=400, detail=str(err))
    except session_store.UnknownApprovalRole:
        raise HTTPException(status_code=400, detail=f"Unknown approval_role_code: {payload.approval_role_code}")

    return {"data_origin": "computed", **result}


@router.post("/{chain_id}/semantic-preview/batch")
def submit_semantic_batch(chain_id: str, creds: tuple[str | None, str | None] = Depends(llm_credentials)):
    """P5 Message Batches — bulk residual re-analysis across every session
    in the chain, submitted as ONE Batch job (non-interactive; no
    fast-turnaround guarantee, poll GET .../batch/{batch_id} for status).
    Opt-in like every other LLM entry point; `semantic_layer_available:
    false` (no batch submitted) means no provider is configured."""
    from backend.services.llm.provider import resolve_llm_provider

    provider_id, api_key = creds
    provider = resolve_llm_provider(provider_id, api_key)
    if provider is None:
        return {"data_origin": "computed", "semantic_layer_available": False}
    try:
        result = submit_batch(chain_id, provider)
    except session_store.SessionNotFound:
        raise HTTPException(status_code=404, detail=f"Chain {chain_id} not found")
    except LlmUnavailable as err:
        raise HTTPException(status_code=502, detail=f"批次提交失敗：{err}")
    return {"data_origin": "computed", "semantic_layer_available": True, **result}


@router.get("/{chain_id}/semantic-preview/batch/{batch_id}")
def get_semantic_batch(chain_id: str, batch_id: str, creds: tuple[str | None, str | None] = Depends(llm_credentials)):
    from backend.services.llm.provider import resolve_llm_provider

    provider_id, api_key = creds
    provider = resolve_llm_provider(provider_id, api_key)
    if provider is None:
        raise HTTPException(status_code=409, detail="未設定 AI 金鑰，無法查詢批次狀態")
    try:
        result = poll_batch(chain_id, batch_id, provider)
    except BatchNotFound:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found for chain {chain_id}")
    return {"data_origin": "computed", **result}


@router.get("/{chain_id}/semantic-preview/batch")
def list_semantic_batches(chain_id: str):
    return {"data_origin": "computed", "batches": get_batch_ledger(chain_id)}
