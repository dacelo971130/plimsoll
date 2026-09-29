"""Agent runs: background execution, progress for polling, and the
append-only record (spec §4.8).

Each 簡報 or 問答 is one run on a background thread (§27(c): plain threads,
no queue infrastructure) — Cloudflare Quick Tunnel can't carry SSE, so the
UI polls `get_run()` for steps instead of streaming. A finished run is
appended to sessions/<id>/agent_runs.jsonl. That file is deliberately NOT
review_events.jsonl: the agent's output is advice, not an audit event, so
it never touches fold_review_state() or the integrity anchor. When a
reviewer adopts a suggestion, the review event's own note carries the
run_id, which is how the two records meet."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import anthropic

from backend.config import SESSIONS_ROOT
from backend.services.agent.prompts import ANSWER_SYSTEM_PROMPT, BRIEFING_SYSTEM_PROMPT
from backend.services.agent.runner import AgentError, RunLimits, Step, run_loop
from backend.services.agent.schemas import AgentAnswer, ReviewBriefing
from backend.services.agent.tools import SessionContext
from backend.services.agent.verify import Verifier
from backend.storage.config_loader import get_glossary, latest_glossary_version

log = logging.getLogger(__name__)

RUNS_FILE = "agent_runs.jsonl"
BRIEFING_LIMITS = RunLimits(max_tool_calls=25, max_seconds=120)
ANSWER_LIMITS = RunLimits(max_tool_calls=10, max_seconds=60)
HISTORY_TURNS = 10
BRIEFING_REQUEST = "請準備這次比對的覆核簡報。"

RunKind = Literal["briefing", "question"]
RunStatus = Literal["running", "done", "failed"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class AgentRun:
    run_id: str
    session_id: str
    kind: RunKind
    question: str | None = None
    status: RunStatus = "running"
    steps: list[dict] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None
    model: str | None = None
    usage: dict = field(default_factory=dict)
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None

    def public(self) -> dict:
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "question": self.question,
            "status": self.status,
            "steps": self.steps,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    def record(self) -> dict:
        return {**self.public(), "session_id": self.session_id, "model": self.model, "provider": "anthropic", "usage": self.usage}


class RunConflict(Exception):
    """Another run of the same kind is still going for this session."""

    def __init__(self, run: AgentRun):
        super().__init__(run.run_id)
        self.run = run


_lock = threading.Lock()
_runs: dict[str, AgentRun] = {}


def _runs_path(session_id: str) -> Path:
    return SESSIONS_ROOT / session_id / RUNS_FILE


def _read_records(session_id: str) -> list[dict]:
    path = _runs_path(session_id)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _persist(run: AgentRun) -> None:
    path = _runs_path(run.session_id)
    if not path.parent.exists():  # session deleted mid-run — nothing to attach to
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(run.record(), ensure_ascii=False) + "\n")


def _running(session_id: str, kind: RunKind) -> AgentRun | None:
    return next((r for r in _runs.values() if r.session_id == session_id and r.kind == kind and r.status == "running"), None)


def _history(session_id: str) -> list[dict]:
    done = [r for r in _read_records(session_id) if r["kind"] == "question" and r["status"] == "done"]
    return done[-HISTORY_TURNS:]


def _question_request(question: str, history: list[dict]) -> str:
    if not history:
        return f"本次問題：{question}"
    lines = ["以下是先前的問答，只用來理解上下文，不能當成依據；依據一律以工具查到的原文為準。"]
    for h in history:
        lines.append(f"問：{h['question']}")
        lines.append(f"答：{h['result']['text']}")
    lines.append("")
    lines.append(f"本次問題：{question}")
    return "\n".join(lines)


def _load_glossary():
    version = latest_glossary_version()
    return get_glossary(version) if version else None


def _api_error_message(exc: anthropic.APIError) -> str:
    if isinstance(exc, anthropic.AuthenticationError):
        return "Claude 的 API 金鑰無效，請到 設定 → 進階 → AI 模型 確認。"
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "這把 API 金鑰沒有使用這個模型的權限。"
    if isinstance(exc, anthropic.RateLimitError):
        return "AI 服務目前忙碌，請稍後再試。"
    if isinstance(exc, anthropic.APIConnectionError):
        return "無法連線到 AI 服務，請確認網路。"
    if isinstance(exc, anthropic.APIStatusError):
        return f"AI 服務回應錯誤（{exc.status_code}），請稍後再試。"
    return "AI 服務發生錯誤，請稍後再試。"


def _execute(run: AgentRun, client: Any) -> None:
    def record_step(step: Step) -> None:
        with _lock:
            run.steps.append(step.as_dict())

    try:
        ctx = SessionContext.load(run.session_id)
        if ctx is None:
            raise AgentError("找不到這次比對的資料。")
        verifier = Verifier(ctx, _load_glossary())
        if run.kind == "briefing":
            raw, loop = run_loop(
                client, system=BRIEFING_SYSTEM_PROMPT, user_content=BRIEFING_REQUEST, ctx=ctx,
                output_model=ReviewBriefing, limits=BRIEFING_LIMITS, on_step=record_step,
            )
            result = verifier.briefing(raw)
        else:
            raw, loop = run_loop(
                client, system=ANSWER_SYSTEM_PROMPT, user_content=_question_request(run.question or "", _history(run.session_id)),
                ctx=ctx, output_model=AgentAnswer, limits=ANSWER_LIMITS, on_step=record_step,
            )
            result = verifier.answer(raw, run.question or "")
        with _lock:
            run.result, run.model, run.usage, run.status = result, loop.model, dict(loop.usage), "done"
    except AgentError as exc:
        with _lock:
            run.error, run.status = str(exc), "failed"
    except anthropic.APIError as exc:
        with _lock:
            run.error, run.status = _api_error_message(exc), "failed"
    except Exception:  # noqa: BLE001 — a background thread must never die silently
        log.exception("agent run %s failed", run.run_id)
        with _lock:
            run.error, run.status = "Agent 執行時發生未預期的錯誤。", "failed"
    finally:
        with _lock:
            run.finished_at = _now()
        try:
            _persist(run)
        except OSError:
            log.exception("could not persist agent run %s; keeping it in memory", run.run_id)
        else:
            # Persisted before dropping it, so a poll landing in between still
            # finds the finished record in agent_runs.jsonl.
            with _lock:
                _runs.pop(run.run_id, None)


def start_run(session_id: str, kind: RunKind, client: Any, question: str | None = None, *, background: bool = True) -> AgentRun:
    with _lock:
        existing = _running(session_id, kind)
        if existing is not None:
            raise RunConflict(existing)
        run = AgentRun(run_id=f"r-{uuid.uuid4().hex[:8]}", session_id=session_id, kind=kind, question=question)
        _runs[run.run_id] = run
    if background:
        threading.Thread(target=_execute, args=(run, client), name=f"agent-{run.run_id}", daemon=True).start()
    else:
        _execute(run, client)
    return run


def get_run(session_id: str, run_id: str) -> dict | None:
    with _lock:
        run = _runs.get(run_id)
        if run is not None and run.session_id == session_id:
            return run.public()
    for record in reversed(_read_records(session_id)):
        if record["run_id"] == run_id:
            return {k: record.get(k) for k in AgentRun(run_id="", session_id="", kind="briefing").public()}
    return None


def latest(session_id: str) -> dict:
    """What the UI needs after a reload: the newest finished briefing, the
    recent Q&A, and anything still running."""
    records = _read_records(session_id)
    public_keys = AgentRun(run_id="", session_id="", kind="briefing").public().keys()

    def public(record: dict) -> dict:
        return {k: record.get(k) for k in public_keys}

    briefing = next((public(r) for r in reversed(records) if r["kind"] == "briefing" and r["status"] == "done"), None)
    answers = [public(r) for r in records if r["kind"] == "question"][-HISTORY_TURNS:]
    with _lock:
        running = [r.public() for r in _runs.values() if r.session_id == session_id and r.status == "running"]
    return {"briefing": briefing, "answers": answers, "running": running}
