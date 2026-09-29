"""P5 term_aliases 核准流程 — list/approve/reject pending LLM-proposed
candidates. Candidates themselves are generated per-session via
`POST /api/sessions/{id}/suggest-aliases` (backend/api/sessions.py); this
router is the shared, session-independent approval queue."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.storage import config_loader

router = APIRouter(prefix="/api/term-aliases", tags=["term-aliases"])


@router.get("/pending")
def list_pending_aliases(status: Literal["pending", "approved", "rejected", "all"] = "pending"):
    entries = config_loader.get_pending_aliases(status=None if status == "all" else status)
    return {"data_origin": "computed", "candidates": [e.model_dump() for e in entries]}


class ResolveAliasRequest(BaseModel):
    approved_by: str | None = None


@router.post("/pending/{pending_id}/approve")
def approve_pending_alias(pending_id: str, payload: ResolveAliasRequest):
    if not payload.approved_by:
        raise HTTPException(status_code=400, detail="approved_by is required to approve a pending alias")
    try:
        entry = config_loader.resolve_pending_alias(pending_id, decision="approve", approved_by=payload.approved_by)
    except config_loader.UnknownPendingAlias as err:
        raise HTTPException(status_code=404, detail=str(err))
    return {"data_origin": "computed", "candidate": entry.model_dump()}


@router.post("/pending/{pending_id}/reject")
def reject_pending_alias(pending_id: str):
    try:
        entry = config_loader.resolve_pending_alias(pending_id, decision="reject")
    except config_loader.UnknownPendingAlias as err:
        raise HTTPException(status_code=404, detail=str(err))
    return {"data_origin": "computed", "candidate": entry.model_dump()}
