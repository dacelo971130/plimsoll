"""Ties extraction + comparison + the storage backbone together.

Persistence follows the exact file layout from architecture-decisions-A-B.md
("本機檔案配置 (P0 落地)"):

    data/store/sessions/<id>/session.json        # one-time write
    data/store/sessions/<id>/differences.json    # one-time write, immutable
    data/store/sessions/<id>/pages.json          # one-time write (B2: page text for the source viewer)
    data/store/sessions/<id>/review_events.jsonl # append-only (backend/storage/events.py)

`session.json`/`differences.json`/`pages.json` are written exactly once, at
session-creation time — the "系統不自行猜測版本號" rule means a session is
only created once both documents' metadata is complete (auto-detected or
user-supplied), so there is never a reason to patch them afterwards.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from backend.config import SESSIONS_ROOT
from backend.models.config_models import Ruleset
from backend.services import export as export_service
from backend.services.comparison import DifferenceRecord, align_pages, compare_documents
from backend.services.drawing_diff import DrawingDifferenceRecord, build_drawing_differences
from backend.services.extraction import (
    ExtractedDocument,
    ExtractedMetadata,
    extract_document,
    extract_metadata,
    scanned_page_numbers,
)
from backend.services.llm.credentials import LlmCredentials
from backend.services.normalize import apply_term_aliases
from backend.services.ocr.pipeline import ocr_scanned_pages
from backend.storage import events as event_store
from backend.storage.config_loader import (
    get_approval_policy,
    get_role_label_snapshot,
    get_ruleset,
    get_term_aliases,
    latest_ruleset_version,
    latest_term_aliases_version,
)


class SessionNotFound(Exception):
    pass


class DifferenceNotFound(Exception):
    pass


class UnknownApprovalRole(Exception):
    pass


class MissingReviewerName(Exception):
    """Every event a human signs (HUMAN_REVIEW, CHAIN_REVIEW, EXPORT_SIGNOFF)
    carries reviewer_name into the audit trail — a blank one would be an
    unattributable signature. Checked here, not just in the UI (v4 決定 #3):
    ReviewBar's button already refused, but its Enter shortcut did not."""

    def __init__(self):
        super().__init__("未填寫覆核人姓名，無法送出")


def require_reviewer_name(reviewer_name: str) -> None:
    if not reviewer_name.strip():
        raise MissingReviewerName()


class ExportRequiresAcknowledgement(Exception):
    """情境四 Human Control: exporting with unreviewed High-risk items is
    never silently blocked — it's watermarked "修訂草稿" and requires an
    explicit acknowledgement flag from the client (the UnreviewedExportGuard
    modal). Raised, not returned, so the API layer can map it to a distinct
    HTTP status the frontend recognizes as "show the guard, don't just
    error out."""

    def __init__(self, unreviewed_high: list[dict]):
        self.unreviewed_high = unreviewed_high
        super().__init__(f"{len(unreviewed_high)} 筆 High 風險變更尚未完成人工覆核")


class ReviewNotAuthorized(Exception):
    """Raised when `approval_policies` denies this role from approving this
    risk level — server-side enforcement (v4 決定 #3), not just a UI hint."""

    def __init__(self, role_label: str, risk: str):
        self.role_label = role_label
        self.risk = risk
        super().__init__(f"{role_label} 無權核准 {risk} 風險等級的變更")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_session_id() -> str:
    return f"s-{uuid.uuid4().hex[:8]}"


def _apply_overrides(meta: ExtractedMetadata, *, version: str | None, date: str | None) -> ExtractedMetadata:
    resolved_version = version or meta.version
    resolved_date = date or meta.date
    missing = [
        name
        for name, value in (("title", meta.title), ("version", resolved_version), ("date", resolved_date))
        if value is None
    ]
    return ExtractedMetadata(
        title=meta.title,
        version=resolved_version,
        date=resolved_date,
        applicable_equipment=meta.applicable_equipment,
        missing_fields=missing,
    )


def _doc_meta_dict(meta: ExtractedMetadata, extracted: ExtractedDocument) -> dict:
    return {
        "title": meta.title,
        "version": meta.version,
        "date": meta.date,
        "applicable_equipment": meta.applicable_equipment,
        "page_count": extracted.page_count,
        "size_bytes": extracted.size_bytes,
        "is_complete": meta.is_complete,
        "missing_fields": meta.missing_fields,
    }


def _difference_dict(d: DifferenceRecord) -> dict:
    return {
        "id": d.id,
        "kind": "text",
        "change_type": d.change_type,
        "ai_risk": d.ai_risk,
        "ai_confidence": d.ai_confidence,
        "explanation": d.explanation,
        "affected": d.affected,
        "recommended_action": d.recommended_action,
        "old": asdict(d.old) if d.old else None,
        "new": asdict(d.new) if d.new else None,
        "ruleset_version": d.ruleset_version,
        "rule_id": d.rule_id,
        "component_ref": None,  # §28 — reserved, not populated in P0–P4
        "data_origin": d.data_origin,
        "ai_semantic_suggestion": d.ai_semantic_suggestion,  # W7a — None unless explicitly enriched
    }


def _best_component_label(regions: list) -> str | None:
    """Picks the highest-confidence AI-read component label across a drawing
    difference's regions, or None if no region got a confident-enough read
    (or no LLM provider ran at all). Never a taxonomy lookup — see §28 note
    at the call site."""
    labeled = [r for r in regions if r.component_label and r.confidence is not None]
    if not labeled:
        return None
    return max(labeled, key=lambda r: r.confidence).component_label


def _drawing_difference_dict(d: DrawingDifferenceRecord) -> dict:
    """P5 §26 counterpart to `_difference_dict()` — same envelope shape
    where it makes sense (id/change_type/ai_risk/.../old/new) so the
    frontend can render both kinds through mostly the same code path, plus
    `regions` (pixel-diff crops + optional AI reading) which text
    differences never have. `kind: "drawing"` is the discriminator."""
    return {
        "id": d.id,
        "kind": "drawing",
        "change_type": d.change_type,
        "ai_risk": d.ai_risk,
        "ai_confidence": d.ai_confidence,
        "explanation": d.explanation,
        "affected": d.affected,
        "recommended_action": d.recommended_action,
        "old": asdict(d.old) if d.old else None,
        "new": asdict(d.new) if d.new else None,
        "ruleset_version": None,
        "rule_id": None,
        # §28 is still not a real taxonomy lookup (no component_taxonomy.json,
        # no SFI coding, no 2D view) — but when the drawing layer's opt-in
        # vision step confidently read a label off a changed region, surface
        # it here rather than leaving a hardcoded None a human has to derive
        # from the crop images themselves.
        "component_ref": _best_component_label(d.regions),
        "data_origin": d.data_origin,
        "ai_semantic_suggestion": None,
        "page_alignment": d.page_alignment,
        "regions": [
            {
                "bbox": list(r.bbox),
                "old_crop_png_b64": r.old_crop_png_b64,
                "new_crop_png_b64": r.new_crop_png_b64,
                "component_label": r.component_label,
                "change_summary": r.change_summary,
                "confidence": r.confidence,
            }
            for r in d.regions
        ],
    }


def process_upload(
    old_bytes: bytes,
    old_filename: str,
    new_bytes: bytes,
    new_filename: str,
    *,
    old_version_override: str | None = None,
    new_version_override: str | None = None,
    old_date_override: str | None = None,
    new_date_override: str | None = None,
    ruleset_version: str | None = None,
    analysis_mode: str = "rules_first",
    llm: LlmCredentials | None = None,
) -> dict:
    """Single entry point for both the "just dropped two files" inspection
    step and the "user filled in the missing version, go" creation step —
    same request shape either way (see backend/api/sessions.py).

    `analysis_mode` (P5 config knob, docs §25) is frozen onto the session at
    creation time — see backend.services.llm.residual.needs_semantic_review
    for what each of the three values actually changes. It never affects the
    deterministic rule-engine result in `differences`, only how widely
    `preview_semantic_suggestions()` later casts its net.

    `llm` (P5 multi-provider BYOK) selects which AI backend does OCR +
    drawing-region description for THIS upload — see
    resolve_ocr_provider()/resolve_llm_provider(). None falls back to
    whatever server-side env var is configured, same as before this existed."""
    if analysis_mode not in ("rules_first", "model_heavy", "model_only"):
        raise ValueError(f"unknown analysis_mode: {analysis_mode!r}")

    old_doc = extract_document(old_bytes)
    new_doc = extract_document(new_bytes)

    # Stage -1 OCR (§26, P5): opt-in, only runs when an OCR provider is
    # configured — otherwise every `scanned_text` page passes through
    # unchanged, exactly as before this existed. Local import (matches
    # every other LLM-resolution call site in this module) so tests can
    # monkeypatch backend.services.ocr.provider.resolve_ocr_provider.
    from backend.services.ocr.provider import resolve_ocr_provider

    ocr_provider = resolve_ocr_provider(llm)
    if ocr_provider is not None:
        old_doc = ocr_scanned_pages(old_bytes, old_doc, ocr_provider)
        new_doc = ocr_scanned_pages(new_bytes, new_doc, ocr_provider)

    # W4: canonicalize before anything downstream sees the pages — page
    # mapping (W3) and rule classification both need the normalized view,
    # and metadata/scanned-page detection only ever read raw_text/char_count,
    # which apply_term_aliases() never touches, so this is safe up-front.
    term_aliases_version = latest_term_aliases_version()
    term_aliases = get_term_aliases(term_aliases_version)
    old_doc = apply_term_aliases(old_doc, term_aliases)
    new_doc = apply_term_aliases(new_doc, term_aliases)

    old_meta = _apply_overrides(extract_metadata(old_doc), version=old_version_override, date=old_date_override)
    new_meta = _apply_overrides(extract_metadata(new_doc), version=new_version_override, date=new_date_override)

    scanned_old = scanned_page_numbers(old_doc)
    scanned_new = scanned_page_numbers(new_doc)

    base_response = {
        "old_meta": _doc_meta_dict(old_meta, old_doc),
        "new_meta": _doc_meta_dict(new_meta, new_doc),
        "old_filename": old_filename,
        "new_filename": new_filename,
        "scanned_old": scanned_old,
        "scanned_new": scanned_new,
        "data_origin": "computed",
    }

    # R1 / AC1 / AC4: never guess. `missing_fields` (title/version/date) is
    # reported for ANY gap so the UI can warn — but only a missing VERSION
    # actually blocks the compare button (ui-spec §3.3 MissingVersionField is
    # specifically about version; title/date missing is a warning, not a gate).
    if old_meta.version is None or new_meta.version is None:
        return {"status": "needs_info", **base_response}

    version = ruleset_version or latest_ruleset_version()
    ruleset = get_ruleset(version)

    # §26 Stage -1 routing: `diagram` pages carry almost no diffable text —
    # text-diff them and every alignment/classify call downstream would just
    # see empty lines. Pull them out before compare_documents() and run them
    # through the pixel-diff pipeline instead (backend.services.drawing_diff).
    old_text_pages = [p for p in old_doc.pages if p.page_kind != "diagram"]
    new_text_pages = [p for p in new_doc.pages if p.page_kind != "diagram"]
    old_diagram_pages = [p for p in old_doc.pages if p.page_kind == "diagram"]
    new_diagram_pages = [p for p in new_doc.pages if p.page_kind == "diagram"]

    old_text_doc = ExtractedDocument(
        pages=old_text_pages, page_count=len(old_text_pages), size_bytes=old_doc.size_bytes
    )
    new_text_doc = ExtractedDocument(
        pages=new_text_pages, page_count=len(new_text_pages), size_bytes=new_doc.size_bytes
    )
    text_page_pairs = align_pages(old_text_doc, new_text_doc)
    differences = compare_documents(old_text_doc, new_text_doc, ruleset, page_pairs=text_page_pairs)

    # LLM description of drawing regions is opt-in (resolve_llm_provider(),
    # same gate as the rest of W7) — the pixel-diff regions themselves are
    # always computed regardless, since that half needs no AI at all.
    drawing_differences: list[DrawingDifferenceRecord] = []
    if old_diagram_pages or new_diagram_pages:
        from backend.services.llm.provider import resolve_llm_provider

        drawing_differences = build_drawing_differences(
            old_bytes,
            new_bytes,
            old_diagram_pages,
            new_diagram_pages,
            start_id=len(differences),
            provider=resolve_llm_provider(llm),
        )

    session_id = _new_session_id()
    title = old_meta.title or new_meta.title or "未命名比對"
    created_at = _now_iso()

    session_dir = SESSIONS_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    session_json = {
        "session_id": session_id,
        "title": title,
        "old_meta": base_response["old_meta"],
        "new_meta": base_response["new_meta"],
        "old_filename": old_filename,
        "new_filename": new_filename,
        "scanned_old": scanned_old,
        "scanned_new": scanned_new,
        "ruleset_version": version,
        "term_aliases_version": term_aliases_version,
        "analysis_mode": analysis_mode,
        "created_at": created_at,
        "status": "compared",
        "data_origin": "computed",
    }
    (session_dir / "session.json").write_text(json.dumps(session_json, ensure_ascii=False, indent=2), encoding="utf-8")

    difference_dicts = [_difference_dict(d) for d in differences] + [
        _drawing_difference_dict(d) for d in drawing_differences
    ]
    (session_dir / "differences.json").write_text(
        json.dumps(difference_dicts, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # W3 page alignment, exposed for the source viewer's page-by-page
    # navigation (CenterStage.tsx) — NOT just for compare_documents(). Without
    # this, the viewer independently indexed `pages.old`/`pages.new` by raw
    # `pdf_page` number (舊版第 N 頁 next to 新版第 N 頁), silently assuming the
    # two documents keep step page-for-page. That assumption is exactly what
    # W3 alignment exists to drop for the diff LIST — real documents with any
    # front-matter/page-count drift (SOLAS 2004→2020 inserts ~22 pages before
    # the same content starts) make "page N of old" and "page N of new"
    # unrelated pages that only coincidentally share a page number, so the
    # viewer was showing two unrelated pages side by side and the leftover
    # highlighting from whichever page's OWN difference records happened to
    # reference that raw page number made it look like content was
    # incorrectly flagged as changed.
    #
    # text_page_pairs indexes into old_text_pages/new_text_pages (the
    # `page_kind != "diagram"` subset compare_documents() itself uses — see
    # above); diagram pages are excluded from that alignment, so they're
    # merged back in here using the SAME positional pairing
    # build_drawing_differences() already assumes (engineering drawings
    # overwhelmingly keep their position across versions), then the whole
    # list is sorted into document order by whichever side has a page number
    # (an entry always has at least one side set).
    page_alignment = [
        {
            "old_pdf_page": old_text_pages[oi].pdf_page if oi is not None else None,
            "new_pdf_page": new_text_pages[ni].pdf_page if ni is not None else None,
        }
        for oi, ni in text_page_pairs
    ]
    for i in range(max(len(old_diagram_pages), len(new_diagram_pages))):
        page_alignment.append(
            {
                "old_pdf_page": old_diagram_pages[i].pdf_page if i < len(old_diagram_pages) else None,
                "new_pdf_page": new_diagram_pages[i].pdf_page if i < len(new_diagram_pages) else None,
            }
        )
    page_alignment.sort(key=lambda e: e["old_pdf_page"] if e["old_pdf_page"] is not None else e["new_pdf_page"])

    pages_json = {
        "old": [
            {"pdf_page": p.pdf_page, "print_label": p.print_label, "label_source": p.label_source, "text": p.raw_text}
            for p in old_doc.pages
        ],
        "new": [
            {"pdf_page": p.pdf_page, "print_label": p.print_label, "label_source": p.label_source, "text": p.raw_text}
            for p in new_doc.pages
        ],
        "page_alignment": page_alignment,
    }
    (session_dir / "pages.json").write_text(json.dumps(pages_json, ensure_ascii=False, indent=2), encoding="utf-8")

    # C2 (架構決策，nice-to-have): 原檔暫存供 P3「原始 PDF」原文模式用；v1 不做
    # 自動清理，留在本機由使用者自理。
    source_dir = session_dir / "source"
    source_dir.mkdir(exist_ok=True)
    (source_dir / "old.pdf").write_bytes(old_bytes)
    (source_dir / "new.pdf").write_bytes(new_bytes)

    for d in differences:
        event_store.append_event(
            session_id,
            {
                "difference_id": d.id,
                "event_type": "AI_INITIAL",
                "ai_risk_at_time": d.ai_risk,
                "ai_confidence_at_time": d.ai_confidence,
                "ruleset_version": d.ruleset_version,
                "data_origin": d.data_origin,
            },
        )
    for d in drawing_differences:
        event_store.append_event(
            session_id,
            {
                "difference_id": d.id,
                "event_type": "AI_INITIAL",
                "ai_risk_at_time": d.ai_risk,
                "ai_confidence_at_time": d.ai_confidence,
                "ruleset_version": version,
                "data_origin": d.data_origin,
            },
        )

    return {"status": "created", "session": get_session(session_id)}


def preview_semantic_suggestions(
    session_id: str, *, llm: LlmCredentials | None = None
) -> dict | None:
    """W7a, on-demand: never called by process_upload(). `differences.json`
    is written-once (see module docstring), so this returns an ENRICHED COPY
    of the session's differences without touching the stored file — the
    permanent record of what the model said is the AI_INITIAL event this
    appends per enriched difference (ai_risk_at_time unchanged; only the
    provenance fields the schema has reserved since P0 get filled in), not a
    rewrite of the original difference record.

    Returns None if the session doesn't exist. `semantic_layer_available` is
    False (differences unchanged) whenever `resolve_llm_provider()` returns
    None — no API key configured (server-side or via the P5 BYOK `llm`
    credentials) is a normal, complete state, not a degraded one."""
    from backend.services.llm.provider import resolve_llm_provider
    from backend.services.llm.residual import enrich_session_differences

    session = get_session(session_id)
    if session is None:
        return None

    provider = resolve_llm_provider(llm)
    if provider is None:
        return {"semantic_layer_available": False, "differences": session["differences"]}

    analysis_mode = session.get("analysis_mode", "rules_first")  # sessions created before P5 default to rules_first
    enriched = enrich_session_differences(session["differences"], provider, analysis_mode=analysis_mode)
    for original, updated in zip(session["differences"], enriched):
        if updated is original or updated.get("ai_semantic_suggestion") is None:
            continue
        event_store.append_event(
            session_id,
            {
                "difference_id": updated["id"],
                "event_type": "AI_INITIAL",
                "ai_risk_at_time": original["ai_risk"],  # unchanged — LLM never sets this
                "ai_confidence_at_time": original["ai_confidence"],
                "ruleset_version": original["ruleset_version"],
                "model_id": provider.model_id,
                "provider": provider.provider_name,
                "analysis_mode": analysis_mode,
                "data_origin": "ai_inferred",
            },
        )
    return {"semantic_layer_available": True, "differences": enriched}


def suggest_aliases_for_session(
    session_id: str, *, llm: LlmCredentials | None = None
) -> dict | None:
    """P5 term_aliases 核准流程, step 1: runs the same semantic-preview
    enrichment as `preview_semantic_suggestions()`, then scans the enriched
    differences for `clarification` residuals and proposes term_alias
    candidates from them (backend.services.llm.alias_suggest) — appended to
    the shared pending queue (backend.storage.config_loader) for a human to
    approve or reject later, from any session. Returns None if the session
    doesn't exist; `semantic_layer_available=False` (no candidates produced)
    when no LLM provider is configured, same convention as
    preview_semantic_suggestions()."""
    from backend.services.llm.alias_suggest import suggest_term_aliases
    from backend.services.llm.provider import resolve_llm_provider
    from backend.storage.config_loader import append_pending_alias

    preview = preview_semantic_suggestions(session_id, llm=llm)
    if preview is None:
        return None
    if not preview["semantic_layer_available"]:
        return {"semantic_layer_available": False, "candidates": []}

    provider = resolve_llm_provider(llm)
    candidates = suggest_term_aliases(preview["differences"], provider)
    stored = [
        append_pending_alias(
            canonical=c.canonical, variant=c.variant, rationale=c.rationale, source_session_id=session_id
        )
        for c in candidates
    ]
    return {"semantic_layer_available": True, "candidates": [s.model_dump() for s in stored]}


def get_session(session_id: str) -> dict | None:
    session_dir = SESSIONS_ROOT / session_id
    session_path = session_dir / "session.json"
    if not session_path.exists():
        return None

    session = json.loads(session_path.read_text(encoding="utf-8"))
    differences = json.loads((session_dir / "differences.json").read_text(encoding="utf-8"))
    events = event_store.read_events(session_id)
    review_state = event_store.fold_review_state(events)
    storage_tag = event_store.derive_storage_tag(session_id)

    return {
        **session,
        "differences": differences,
        "review_state": review_state,
        "storage_tag": storage_tag,
    }


def get_pages(session_id: str) -> dict | None:
    pages_path = SESSIONS_ROOT / session_id / "pages.json"
    if not pages_path.exists():
        return None
    return json.loads(pages_path.read_text(encoding="utf-8"))


def estimate_cost(session_id: str) -> dict | None:
    """P6 成本試算, real-document version — see cost_estimate.py's module
    docstring. Read-only and free: `needs_semantic_review_dict()` is the same
    zero-cost heuristic the real semantic layer runs before ever touching a
    provider, so this never calls out to any LLM."""
    from backend.services.llm.cost_estimate import estimate_semantic_review_cost

    session = get_session(session_id)
    if session is None:
        return None
    return {"modes": estimate_semantic_review_cost(session["differences"])}


def get_pdf(session_id: str, side: str) -> bytes | None:
    """Backs the 「原始 PDF」原文模式 (ui-spec §3.3). Returns None — never a
    guess — when the file wasn't stashed (e.g. a session created before this
    existed), so the API layer can 404 and the frontend can show "原檔未保存"."""
    if side not in ("old", "new"):
        return None
    pdf_path = SESSIONS_ROOT / session_id / "source" / f"{side}.pdf"
    if not pdf_path.exists():
        return None
    return pdf_path.read_bytes()


def submit_review_event(
    session_id: str,
    *,
    difference_id: str,
    human_verdict: str,
    reviewer_name: str,
    approval_role_code: str,
    reviewer_note: str = "",
    risk_override: str | None = None,
) -> dict:
    """The P3 ReviewBar's "確認並前往下一筆" action. Enforces
    `approval_policies` server-side (v4 決定 #3) before ever touching the
    append-only log — a denied review never gets written, not even as a
    rejected/undone entry."""
    session = get_session(session_id)
    if session is None:
        raise SessionNotFound(session_id)

    difference = next((d for d in session["differences"] if d["id"] == difference_id), None)
    if difference is None:
        raise DifferenceNotFound(difference_id)

    require_reviewer_name(reviewer_name)
    role_label = get_role_label_snapshot(approval_role_code)
    if role_label is None:
        raise UnknownApprovalRole(approval_role_code)

    effective_risk = risk_override or difference["ai_risk"]
    policy = get_approval_policy(session["ruleset_version"])
    if not policy.can_approve(approval_role_code, effective_risk):
        raise ReviewNotAuthorized(role_label, effective_risk)

    event = event_store.append_event(
        session_id,
        {
            "difference_id": difference_id,
            "event_type": "HUMAN_REVIEW",
            "human_verdict": human_verdict,
            "risk_override": risk_override,
            "reviewer_name": reviewer_name,
            "approval_role_code": approval_role_code,
            "approval_role_label_snapshot": role_label,
            "reviewer_note": reviewer_note,
            "ruleset_version": session["ruleset_version"],
        },
    )
    return {"event": event, "session": get_session(session_id)}


def list_sessions() -> list[dict]:
    if not SESSIONS_ROOT.exists():
        return []
    summaries = []
    for d in sorted(SESSIONS_ROOT.iterdir()):
        if not d.is_dir():
            continue
        summary = get_session(d.name)
        if summary is not None:
            summaries.append(summary)
    summaries.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return summaries


# --------------------------------------------------------------------------
# P5 — HistoryRail 一鍵清除／單筆刪除 (user feedback: 左側比對紀錄清單需要
# 清除功能). A session's on-disk footprint is exactly its directory
# (session.json/differences.json/pages.json/source/review_events.jsonl —
# see the module docstring), so deletion is just removing that directory;
# there is no separate index file to keep in sync.
# --------------------------------------------------------------------------


def delete_session(session_id: str) -> bool:
    """Returns False (no-op, not an error) if the session never existed —
    matches get_session()'s own "missing means None, never guess" stance."""
    target = SESSIONS_ROOT / session_id
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True


def delete_all_sessions() -> int:
    """Wipes every session under SESSIONS_ROOT and returns how many were
    removed. Used by HistoryRail's "清除全部" — an explicit, user-confirmed
    action (confirmed client-side before this is ever called), not something
    triggered as a side effect of anything else."""
    if not SESSIONS_ROOT.exists():
        return 0
    dirs = [d for d in SESSIONS_ROOT.iterdir() if d.is_dir()]
    for d in dirs:
        shutil.rmtree(d)
    return len(dirs)


# --------------------------------------------------------------------------
# P4: export (ui-spec §7 AC4 / 情境四)
# --------------------------------------------------------------------------

EXPORT_SIGNOFF_DIFFERENCE_ID = "*"  # session-level event, not tied to one difference

_EXPORT_BUILDERS = {
    "html": (export_service.build_html_report, "text/html", "html"),
    "docx": (
        export_service.build_docx_report,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    ),
    "pdf": (export_service.build_pdf_report, "application/pdf", "pdf"),
}


def unreviewed_high_differences(session: dict) -> list[dict]:
    """High-risk items without an explicit 已確認/CONFIRMED verdict — 需追蹤
    /不採納/未覆核 all still count, matching the same "待簽核 High" definition
    used by the P2 overview KPI and P3's alert, so the numbers a reviewer
    sees never disagree with each other."""
    review_state = session["review_state"]
    return [
        d
        for d in session["differences"]
        if d["ai_risk"] == "High" and review_state.get(d["id"], {}).get("human_verdict") != "CONFIRMED"
    ]


def export_session(
    session_id: str,
    *,
    fmt: str,
    reviewer_name: str,
    approval_role_code: str,
    report_no: str = "",
    dept: str = "",
    acknowledge_draft: bool = False,
) -> tuple[bytes, str, str]:
    """Returns (content, media_type, filename). Raises ExportRequiresAcknowledgement
    if High-risk items are unreviewed and the caller hasn't set
    acknowledge_draft=True — the frontend's UnreviewedExportGuard is what
    sets that, after the human explicitly ticks the box."""
    if fmt not in _EXPORT_BUILDERS:
        raise ValueError(f"unknown export format: {fmt}")

    session = get_session(session_id)
    if session is None:
        raise SessionNotFound(session_id)

    require_reviewer_name(reviewer_name)
    role_label = get_role_label_snapshot(approval_role_code)
    if role_label is None:
        raise UnknownApprovalRole(approval_role_code)

    unreviewed_high = unreviewed_high_differences(session)
    is_draft = len(unreviewed_high) > 0
    if is_draft and not acknowledge_draft:
        raise ExportRequiresAcknowledgement(unreviewed_high)

    meta = export_service.ExportMeta(
        reviewer_name=reviewer_name,
        approval_role_code=approval_role_code,
        role_label=role_label,
        report_no=report_no,
        dept=dept,
        is_draft=is_draft,
        exported_at=_now_iso(),
    )

    builder, media_type, ext = _EXPORT_BUILDERS[fmt]
    content = builder(session, meta)

    status_note = "修訂草稿" if is_draft else "正式"
    event_store.append_event(
        session_id,
        {
            "difference_id": EXPORT_SIGNOFF_DIFFERENCE_ID,
            "event_type": "EXPORT_SIGNOFF",
            "reviewer_name": reviewer_name,
            "approval_role_code": approval_role_code,
            "approval_role_label_snapshot": role_label,
            "reviewer_note": f"匯出格式={fmt}；報告編號={report_no or '—'}；部門={dept or '—'}；狀態={status_note}",
            "ruleset_version": session["ruleset_version"],
        },
    )

    filename = f"{session_id}-{'draft' if is_draft else 'final'}.{ext}"
    return content, media_type, filename
