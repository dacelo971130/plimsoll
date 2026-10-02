"""覆核 Agent endpoints (spec §4). Runs are started here and polled — no
streaming, because Cloudflare Quick Tunnel can't carry SSE. Every result is
already verified server-side (services/agent/verify.py) by the time it is
returned; nothing here writes a review event."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.api.llm_headers import llm_credentials
from backend.services import session_store
from backend.services.agent import runs
from backend.services.agent.client import resolve_agent_backend
from backend.services.llm.credentials import LlmCredentials

router = APIRouter(prefix="/api", tags=["agent"])


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


def _require_session(session_id: str) -> None:
    if session_store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="找不到這次比對。")


def _backend_or_409(llm: LlmCredentials):
    backend, reason = resolve_agent_backend(llm)
    if backend is None:
        raise HTTPException(status_code=409, detail=reason)
    return backend


@router.get("/agent/status")
def agent_status(llm: LlmCredentials = Depends(llm_credentials)) -> dict:
    """Lets the UI show the Agent entry only when it can actually run
    (不做假的) — no disabled button standing in for a missing key."""
    backend, reason = resolve_agent_backend(llm)
    if backend is None:
        return {"available": False, "reason": reason, "model": "", "provider": None}
    return {"available": True, "reason": None, "model": backend.model, "provider": backend.provider}


def _start(session_id: str, kind: runs.RunKind, llm: LlmCredentials, question: str | None = None) -> dict:
    _require_session(session_id)
    backend = _backend_or_409(llm)
    try:
        run = runs.start_run(session_id, kind, backend, question)
    except runs.RunConflict as conflict:
        if kind == "briefing":
            # Same button pressed twice: hand back the run already going
            # rather than paying for a second one.
            return conflict.run.public()
        raise HTTPException(status_code=409, detail="上一個問題還在處理中，請稍候。") from None
    return run.public()


@router.post("/sessions/{session_id}/agent/briefing", status_code=202)
def start_briefing(session_id: str, llm: LlmCredentials = Depends(llm_credentials)) -> dict:
    return _start(session_id, "briefing", llm)


@router.post("/sessions/{session_id}/agent/questions", status_code=202)
def ask_question(session_id: str, payload: QuestionRequest, llm: LlmCredentials = Depends(llm_credentials)) -> dict:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="問題不可為空白。")
    return _start(session_id, "question", llm, question)


@router.get("/sessions/{session_id}/agent/runs/{run_id}")
def get_run(session_id: str, run_id: str) -> dict:
    _require_session(session_id)
    run = runs.get_run(session_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="找不到這次 Agent 執行紀錄。")
    return run


@router.get("/sessions/{session_id}/agent/latest")
def latest(session_id: str) -> dict:
    _require_session(session_id)
    return runs.latest(session_id)
