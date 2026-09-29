"""The append-only audit trail — and its own sync protocol.

architecture-decisions-A-B.md §21:

    覆核狀態為 `review_events.jsonl` 唯增長事件流之投影（讀檔 fold），非可變欄位；
    改判＝追加凌駕行。每筆帶唯一 event_id 使上游 upsert idempotent、forward-only、免衝突。

Tamper-evidence uses a "frozen-prefix hash anchor": once a prefix `[0, offset)`
of the file has been checkpointed (`save_anchor`), that prefix must never
change. `check_integrity` re-hashes the current prefix and compares; a
mismatch means the historical region was hand-edited, and the session is
quarantined — never auto-repaired, never silently dropped.

Single-writer, single-machine (v1 premise) — a per-session ``threading.Lock``
is sufficient; no queue/Celery/Redis needed.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from backend.config import INTEGRITY_ROOT, SESSIONS_ROOT
from backend.models.review_event import ReviewEvent
from backend.storage.sync_target import SyncTarget, get_sync_target

StorageTag = Literal["本機", "未同步", "已同步"]

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(session_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(session_id, threading.Lock())


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------

def events_path(session_id: str, store_root: Path = SESSIONS_ROOT) -> Path:
    d = store_root / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "review_events.jsonl"


def sync_state_path(session_id: str, store_root: Path = SESSIONS_ROOT) -> Path:
    return (store_root / session_id) / "sync_state.json"


def integrity_path(session_id: str, integrity_root: Path = INTEGRITY_ROOT) -> Path:
    integrity_root.mkdir(parents=True, exist_ok=True)
    return integrity_root / f"{session_id}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# append + read + fold
# --------------------------------------------------------------------------

def _next_event_id(existing: list[dict]) -> str:
    return f"e-{len(existing) + 1:04d}"


def _canonical(event_no_hash: dict) -> str:
    return json.dumps(event_no_hash, sort_keys=True, ensure_ascii=False)


def append_event(
    session_id: str,
    event: dict,
    *,
    store_root: Path = SESSIONS_ROOT,
    sync_target: SyncTarget | None = None,
) -> dict:
    """Validate, hash-chain, and durably append one event. Returns the event
    exactly as written (with event_id/created_at/prev_*/hash filled in).

    ① Local append is ALWAYS the commit point.
    ② Sync-target write-through is best-effort and never blocks/undoes ①.
    """
    lock = _lock_for(session_id)
    with lock:
        existing = _read_events_unlocked(session_id, store_root)
        prev = existing[-1] if existing else None

        record = {**event}
        record.setdefault("session_id", session_id)
        record.setdefault("event_id", _next_event_id(existing))
        record.setdefault("created_at", _now_iso())
        record.setdefault("prev_event_id", prev["event_id"] if prev else None)
        record.setdefault("prev_hash", prev["hash"] if prev else None)
        record.setdefault("data_origin", "computed")

        prehash_fields = {k: v for k, v in record.items() if k != "hash"}
        record["hash"] = hashlib.sha256(
            ((record.get("prev_hash") or "") + _canonical(prehash_fields)).encode("utf-8")
        ).hexdigest()

        # Schema validation — bad shape is rejected before it ever touches disk.
        validated = ReviewEvent(**record)
        line = validated.model_dump_json()

        path = events_path(session_id, store_root)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    target = sync_target or get_sync_target()
    if target.is_connected():
        try:
            target.ingest_events([record])
            _mark_synced(session_id, record["event_id"], store_root)
        except Exception:
            pass  # stays on local disk, tagged 未同步; flush_pending retries later

    return record


def _read_events_unlocked(session_id: str, store_root: Path = SESSIONS_ROOT) -> list[dict]:
    path = events_path(session_id, store_root)
    if not path.exists():
        return []
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def read_events(session_id: str, store_root: Path = SESSIONS_ROOT) -> list[dict]:
    lock = _lock_for(session_id)
    with lock:
        return _read_events_unlocked(session_id, store_root)


def fold_review_state(events: list[dict]) -> dict[str, dict]:
    """Projection: latest AI_INITIAL for baseline + latest human decision per
    difference_id. Review status is derived here — it is never a column
    anyone can overwrite directly."""
    state: dict[str, dict] = {}
    for e in events:
        if e["event_type"] in ("EXPORT_SIGNOFF", "CHAIN_REVIEW"):
            continue  # session-/chain-level (difference_id="*"), not a per-difference review state
        diff_id = e["difference_id"]
        row = state.setdefault(
            diff_id,
            {
                "difference_id": diff_id,
                "ai_risk_at_time": None,
                "ruleset_version": None,
                "human_verdict": None,
                "risk_override": None,
                "reviewer_name": None,
                "approval_role_code": None,
                "approval_role_label_snapshot": None,
                "reviewer_note": None,
                "last_event_id": None,
                "last_event_type": None,
            },
        )
        if e["event_type"] == "AI_INITIAL":
            row["ai_risk_at_time"] = e.get("ai_risk_at_time")
            row["ruleset_version"] = e.get("ruleset_version")
        elif e["event_type"] in ("HUMAN_REVIEW", "RISK_OVERRIDE"):
            for key in (
                "human_verdict",
                "risk_override",
                "reviewer_name",
                "approval_role_code",
                "approval_role_label_snapshot",
                "reviewer_note",
            ):
                if e.get(key) is not None:
                    row[key] = e.get(key)
        row["last_event_id"] = e["event_id"]
        row["last_event_type"] = e["event_type"]
    return state


# --------------------------------------------------------------------------
# tamper-evidence: frozen-prefix SHA-256 anchor
# --------------------------------------------------------------------------

@dataclass
class IntegrityResult:
    ok: bool
    reason: str | None = None
    checked_offset: int = 0


def _sha256_prefix(raw: bytes, offset: int) -> str:
    return hashlib.sha256(raw[:offset]).hexdigest()


def save_anchor(
    session_id: str,
    *,
    store_root: Path = SESSIONS_ROOT,
    integrity_root: Path = INTEGRITY_ROOT,
) -> dict:
    """Checkpoint the current end-of-file as the new frozen prefix. In v1
    this is DB-preferred/local-fallback (§21); P0 has no DB yet, so it always
    writes to `.integrity/<session_id>.json`."""
    path = events_path(session_id, store_root)
    raw = path.read_bytes() if path.exists() else b""
    anchor = {"offset": len(raw), "prefix_sha256": hashlib.sha256(raw).hexdigest(), "saved_at": _now_iso()}
    integrity_path(session_id, integrity_root).write_text(json.dumps(anchor, ensure_ascii=False), encoding="utf-8")
    return anchor


def load_anchor(session_id: str, *, integrity_root: Path = INTEGRITY_ROOT) -> dict | None:
    p = integrity_path(session_id, integrity_root)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def check_integrity(
    session_id: str,
    *,
    store_root: Path = SESSIONS_ROOT,
    integrity_root: Path = INTEGRITY_ROOT,
) -> IntegrityResult:
    """Re-hash the checkpointed prefix and compare. No anchor yet ⇒ nothing
    to verify (ok=True) — legitimate for a session that has never been
    checkpointed."""
    anchor = load_anchor(session_id, integrity_root=integrity_root)
    if anchor is None:
        return IntegrityResult(ok=True, reason=None, checked_offset=0)

    path = events_path(session_id, store_root)
    raw = path.read_bytes() if path.exists() else b""
    offset = anchor["offset"]
    if len(raw) < offset:
        return IntegrityResult(ok=False, reason="稽核日誌短於錨點記錄的長度，疑遭截斷", checked_offset=offset)

    current = _sha256_prefix(raw, offset)
    if current != anchor["prefix_sha256"]:
        return IntegrityResult(ok=False, reason="完整性驗證失敗：歷史稽核區前綴雜湊不符，疑遭手動修改", checked_offset=offset)
    return IntegrityResult(ok=True, reason=None, checked_offset=offset)


# --------------------------------------------------------------------------
# sync_state.json sidecar (mutable, NOT part of the audit trail)
# --------------------------------------------------------------------------

def read_sync_state(session_id: str, store_root: Path = SESSIONS_ROOT) -> dict:
    p = sync_state_path(session_id, store_root)
    if not p.exists():
        return {
            "target": None,
            "last_synced_event_id": None,
            "synced_at": None,
            "pending": 0,
            "quarantined": False,
            "quarantine_reason": None,
        }
    return json.loads(p.read_text(encoding="utf-8"))


def _write_sync_state(session_id: str, store_root: Path, state: dict) -> None:
    sync_state_path(session_id, store_root).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def _mark_synced(session_id: str, event_id: str, store_root: Path = SESSIONS_ROOT) -> None:
    state = read_sync_state(session_id, store_root)
    state["last_synced_event_id"] = event_id
    state["synced_at"] = _now_iso()
    state["pending"] = 0
    _write_sync_state(session_id, store_root, state)


def mark_quarantined(session_id: str, reason: str, store_root: Path = SESSIONS_ROOT) -> None:
    """Integrity check failed: isolate for human review. The raw JSONL is
    left exactly as-is (it IS the evidence) — this only flags it."""
    state = read_sync_state(session_id, store_root)
    state["quarantined"] = True
    state["quarantine_reason"] = reason
    _write_sync_state(session_id, store_root, state)


def acknowledge_quarantine(session_id: str, store_root: Path = SESSIONS_ROOT) -> None:
    """UI "標記為已知悉並結案" — only clears the alert's visibility, never
    touches the underlying JSONL or re-attempts ingest automatically."""
    state = read_sync_state(session_id, store_root)
    state["quarantined"] = False
    _write_sync_state(session_id, store_root, state)


def derive_storage_tag(
    session_id: str,
    *,
    store_root: Path = SESSIONS_ROOT,
    sync_target: SyncTarget | None = None,
) -> StorageTag:
    """三態 tag — 本機／未同步／已同步 (architecture-decisions-A-B.md §19)."""
    target = sync_target or get_sync_target()
    state = read_sync_state(session_id, store_root)
    if state.get("target") is None or state.get("last_synced_event_id") is None:
        if not target.is_connected():
            return "本機"
    events = read_events(session_id, store_root)
    last_id = events[-1]["event_id"] if events else None
    if state.get("last_synced_event_id") == last_id and last_id is not None:
        return "已同步"
    if state.get("target") is not None:
        return "未同步"
    return "本機"
