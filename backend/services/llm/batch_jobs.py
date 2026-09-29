"""P5 Message Batches (docs/redesign/plimsoll-improvement-plan.html: "殘差
分類走 Message Batches，非即時任務，五折"). Deliberately scoped to CHAIN-level
bulk re-analysis, not the single-session "AI 語意建議" button
(backend.services.session_store.preview_semantic_suggestions): the Batch API
has no fast-turnaround guarantee (Anthropic doesn't promise a completion
window), so it's only a good fit for a bulk, walk-away-and-come-back job — a
chain's adjacent+anchor sessions can easily have dozens of qualifying
residuals, exactly the "非即時任務" case the original plan describes.

Batch submissions are tracked in a per-chain ledger
(data/store/sessions/<chain_id>/batch_jobs.json) — appended to, never
rewritten, so a chain's batch history stays visible across multiple
submissions. The actual suggestion CONTENT lives only in that ledger once a
batch completes (differences.json is write-once and review_events.jsonl's
ReviewEvent schema has no field for it — extra="forbid" — see
backend/models/review_event.py); one AI_INITIAL audit event per applied
difference still gets appended for provenance, matching the exact shape
preview_semantic_suggestions() already writes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from backend.config import SESSIONS_ROOT
from backend.services import session_store
from backend.services.llm.provider import LlmProvider, LlmUnavailable
from backend.services.llm.residual import needs_semantic_review_dict
from backend.storage import events as event_store


class BatchNotFound(Exception):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ledger_path(chain_id: str) -> Path:
    return SESSIONS_ROOT / chain_id / "batch_jobs.json"


def _read_ledger(chain_id: str) -> list[dict]:
    path = _ledger_path(chain_id)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _write_ledger(chain_id: str, entries: list[dict]) -> None:
    path = _ledger_path(chain_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def get_batch_ledger(chain_id: str) -> list[dict]:
    """Every batch ever submitted for this chain, newest first."""
    return list(reversed(_read_ledger(chain_id)))


def _chain_session_ids(chain: dict) -> list[str]:
    """Every distinct session in the chain — adjacent + anchor, deduplicated
    (anchor_session_ids[0] always equals adjacent_session_ids[0], per
    chain.py's build_chain: v1→v2 is shared, never duplicated)."""
    return list(dict.fromkeys(chain["adjacent_session_ids"] + chain["anchor_session_ids"]))


def submit_batch(chain_id: str, provider: LlmProvider) -> dict:
    """Gathers every qualifying residual difference across the chain's
    sessions (each session's own `analysis_mode`, same trigger as the
    single-session path) and submits ONE Anthropic Batch job. Returns
    `{batch_id, session_count, difference_count}` — `batch_id` is None and
    nothing is submitted if no difference qualifies (never an empty/wasted
    API call). Raises session_store.SessionNotFound if the chain doesn't
    exist, LlmUnavailable if the submit call itself fails."""
    from backend.services import chain as chain_service

    chain = chain_service.get_chain(chain_id)
    if chain is None:
        raise session_store.SessionNotFound(chain_id)

    session_ids = _chain_session_ids(chain)
    items: list[tuple[str, str | None, str | None]] = []
    for session_id in session_ids:
        session = session_store.get_session(session_id)
        if session is None:
            continue
        analysis_mode = session.get("analysis_mode", "rules_first")
        for d in session["differences"]:
            if d.get("kind") == "drawing" or not needs_semantic_review_dict(d, analysis_mode=analysis_mode):
                continue
            old_text = (d.get("old") or {}).get("text")
            new_text = (d.get("new") or {}).get("text")
            items.append((f"{session_id}:{d['id']}", old_text, new_text))

    if not items:
        return {"batch_id": None, "session_count": len(session_ids), "difference_count": 0}

    batch_id = provider.classify_residual_batch(items)
    entries = _read_ledger(chain_id)
    entries.append(
        {
            "batch_id": batch_id,
            "status": "in_progress",
            "submitted_at": _now_iso(),
            "difference_count": len(items),
            "custom_ids": [item[0] for item in items],
            "results": None,
            "completed_at": None,
        }
    )
    _write_ledger(chain_id, entries)
    return {"batch_id": batch_id, "session_count": len(session_ids), "difference_count": len(items)}


def poll_batch(chain_id: str, batch_id: str, provider: LlmProvider) -> dict:
    """Checks the batch's status; if it has ended, fetches + applies results
    (one AI_INITIAL audit event per successfully-applied difference,
    idempotent to call again — the ledger entry's `status` flips to
    "completed" exactly once) and returns the full results map for the
    caller to merge into whatever session view it's showing, the same
    overlay technique the single-session semantic bar already uses. Returns
    `{status: "in_progress"}` while still running, or an already-completed
    entry's stored results on a repeat call (never re-applies audit events).
    """
    entries = _read_ledger(chain_id)
    entry = next((e for e in entries if e["batch_id"] == batch_id), None)
    if entry is None:
        raise BatchNotFound(batch_id)

    if entry["status"] == "completed":
        return {"status": "completed", "results": entry["results"]}

    status = provider.get_batch_status(batch_id)
    if status != "ended":
        return {"status": "in_progress"}

    try:
        raw_results = provider.fetch_batch_results(batch_id)
    except LlmUnavailable:
        return {"status": "in_progress"}  # transient fetch failure — try again later, don't mark completed

    results: dict[str, dict | None] = {}
    applied = 0
    for custom_id, suggestion in raw_results.items():
        if suggestion is None:
            results[custom_id] = None
            continue
        results[custom_id] = suggestion.model_dump()
        session_id, difference_id = custom_id.split(":", 1)
        session = session_store.get_session(session_id)
        if session is None:
            continue
        difference = next((d for d in session["differences"] if d["id"] == difference_id), None)
        if difference is None:
            continue
        event_store.append_event(
            session_id,
            {
                "difference_id": difference_id,
                "event_type": "AI_INITIAL",
                "ai_risk_at_time": difference["ai_risk"],
                "ai_confidence_at_time": difference["ai_confidence"],
                "ruleset_version": difference.get("ruleset_version"),
                "model_id": provider.model_id,
                "provider": provider.provider_name,
                "analysis_mode": session.get("analysis_mode", "rules_first"),
                "data_origin": "ai_inferred",
            },
        )
        applied += 1

    entry["status"] = "completed"
    entry["results"] = results
    entry["completed_at"] = _now_iso()
    entry["applied_count"] = applied
    _write_ledger(chain_id, entries)
    return {"status": "completed", "results": results}
