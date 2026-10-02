"""System-level endpoints: health check, global DB-sync status (§24), and
config lookups. No endpoint here ever touches a database at import/startup
time — the connection probe is deliberately absent in P0 (NullSyncTarget is
always disconnected), so the frontend's grey status dot reflects reality
without any request ever blocking on it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.config import SESSIONS_ROOT
from backend.storage import events as event_store
from backend.storage.config_loader import get_glossary, latest_glossary_version, list_approval_roles
from backend.storage.sync_target import get_sync_target

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health_check() -> dict:
    return {"status": "ok", "service": "Plimsoll API", "data_origin": "computed"}


@router.get("/system/data-source")
def data_source_status() -> dict:
    """Backs the TopBar gear status dot + Settings → 資料來源 → 資料庫同步.

    P0 ships no real adapter, so this is always the grey "未連線" state — but
    the *shape* (pending count, quarantined sessions) is real and already
    wired to `sync_state.json`, ready for a later phase to swap in a
    connected SyncTarget without changing this endpoint's contract.
    """
    target = get_sync_target()
    connected = target.is_connected()

    pending = 0
    quarantined: list[dict] = []
    if SESSIONS_ROOT.exists():
        for session_dir in SESSIONS_ROOT.iterdir():
            if not session_dir.is_dir():
                continue
            session_id = session_dir.name
            state = event_store.read_sync_state(session_id)
            tag = event_store.derive_storage_tag(session_id, sync_target=target)
            if tag == "未同步":
                pending += 1
            if state.get("quarantined"):
                quarantined.append({"session_id": session_id, "reason": state.get("quarantine_reason")})

    return {
        "data_origin": "computed",
        "status": "connected" if connected else "disconnected",
        "target": None,
        "pending_count": pending,
        "quarantined_sessions": quarantined,
    }


def _quarantined_session_dir(session_id: str):
    """Both quarantine actions only ever act on a session that exists AND is
    currently flagged — never a way to reach an arbitrary path or clear a
    flag that was never raised. `iterdir()` membership (not path joining)
    keeps a crafted id like `..` from resolving outside SESSIONS_ROOT."""
    if not SESSIONS_ROOT.exists() or session_id not in {d.name for d in SESSIONS_ROOT.iterdir() if d.is_dir()}:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    if not event_store.read_sync_state(session_id).get("quarantined"):
        raise HTTPException(status_code=409, detail=f"Session {session_id} 目前沒有完整性告警")
    return SESSIONS_ROOT / session_id


@router.get("/system/quarantine/{session_id}/events")
def download_quarantined_events(session_id: str):
    """Settings → 資料來源 → 完整性告警 「下載原始稽核日誌（.jsonl）」 — the
    file byte-for-byte as it sits on disk (it IS the evidence), never
    re-serialised through read_events()."""
    path = _quarantined_session_dir(session_id) / "review_events.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail="此 session 沒有稽核日誌檔")
    return FileResponse(path, media_type="application/x-ndjson", filename=f"{session_id}-review_events.jsonl")


@router.post("/system/quarantine/{session_id}/acknowledge")
def acknowledge_quarantine(session_id: str) -> dict:
    """「標記為已知悉並結案」 — clears the alert only; the JSONL stays
    untouched and nothing is re-ingested (events.acknowledge_quarantine)."""
    _quarantined_session_dir(session_id)
    event_store.acknowledge_quarantine(session_id)
    return data_source_status()


@router.get("/config/approval-roles")
def approval_roles() -> dict:
    roles = [r.model_dump() for r in list_approval_roles() if r.is_active]
    return {"data_origin": "computed", "roles": roles}


@router.get("/config/glossary")
def glossary() -> dict:
    """Backs 使用說明 → 名詞解釋. `sources` (repo paths) stay server-side —
    they're review evidence, not user copy. `status` travels with the data
    so the page can say the glossary is still a draft instead of passing it
    off as settled; a missing file returns an empty list, never a 500."""
    version = latest_glossary_version()
    if version is None:
        return {"data_origin": "computed", "version": None, "status": None, "reviewed_at": None, "simulated": False, "terms": []}
    table = get_glossary(version)
    return {
        "data_origin": "computed",
        "version": table.version,
        "status": table.status,
        "reviewed_at": table.reviewed_at,
        "simulated": table.simulated,
        "terms": [t.model_dump(exclude={"sources"}) for t in table.terms],
    }
