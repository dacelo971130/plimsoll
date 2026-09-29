"""Chain coordinator (W5): docs/redesign/plimsoll-improvement-plan.html
§02/§03. Only calls existing session_store/comparison/extraction/normalize
functions — no comparison logic is duplicated or reimplemented here.

A chain over N ordered versions is:

  1. N-1 *adjacent* pairwise sessions: v1→v2, v2→v3, ..., v(N-1)→vN.
  2. N-2 *anchor* pairwise sessions: v1→v3, v1→v4, ..., v1→vN — v1→v2 is
     shared with the first adjacent session (§02), so total distinct
     sessions created is 2N-3, not 2(N-1).
  3. A parameter series per canonical_param, built by scanning every
     participating document's OWN extracted+canonicalized text for
     numeric-with-unit mentions — not the diff output. A value that never
     changes between two adjacent versions produces no diff record at all,
     but must still contribute a data point to the series.
  4. A drift_report.json — one DriftFinding per canonical_param, computed by
     re-running comparison.classify() with `chain_history` set (W6), so
     cumulative_drift competes on equal footing with every other rule
     instead of being a bespoke threshold check bolted on the side.

Canonical-param identification here is a `{section heading}::{unit}`
heuristic, not real semantic naming (§28 taxonomy is Someday; giving a
parameter a human name like "cooling.outlet_temp.max" is W7 territory,
where an LLM proposes a label a human then approves — never on the live
comparison path). Each document is extracted+normalized twice (once inside
session_store.process_upload() for the pairwise diff, once here for the
per-version parameter scan) — a deliberate simplicity-over-cost tradeoff for
this first cut; the PDFs involved are small.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.config import SESSIONS_ROOT
from backend.models.chain import ChainManifest, DriftFinding, ParameterPoint
from backend.models.config_models import Ruleset
from backend.services import session_store
from backend.services.comparison import classify, numbers_with_unit
from backend.services.extraction import ExtractedDocument, extract_document, extract_metadata
from backend.services.normalize import apply_term_aliases
from backend.storage.config_loader import get_ruleset, get_term_aliases, latest_ruleset_version, latest_term_aliases_version

CHAIN_REVIEW_DIFFERENCE_ID = "*"  # chain-level event, not tied to one difference (mirrors EXPORT_SIGNOFF)


class ChainVersionMissing(Exception):
    """A version's metadata couldn't be auto-detected — a chain never
    guesses, same rule as a pairwise session (R1/AC1/AC4)."""

    def __init__(self, filename: str):
        self.filename = filename
        super().__init__(f"{filename}: 版本號無法自動偵測，鏈式比對不猜測版本")


class ChainStepFailed(Exception):
    """One of the chain's pairwise comparisons didn't reach `created` status
    (e.g. that pair also has a missing-version doc) — surfaced with which
    step failed rather than a bare KeyError deep in session_store."""

    def __init__(self, label: str, status: str):
        self.label = label
        self.status = status
        super().__init__(f"{label}: session_store 回傳 status={status!r}，未能建立比對 session")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_chain_id() -> str:
    return f"c-{uuid.uuid4().hex[:8]}"


def _slug(heading: str | None) -> str:
    return re.sub(r"\s+", "_", (heading or "unknown").strip()) or "unknown"


def extract_parameter_points(doc: ExtractedDocument, version: str) -> dict[str, list[ParameterPoint]]:
    """One list per `{heading}::{unit}` key seen anywhere in this document
    version. Multiple numeric-with-unit mentions under the same heading+unit
    are kept in first-appearance order; when merging across versions
    (`_merge_parameter_series`) they're paired positionally — a heuristic
    proxy for "same parameter", not real identification (see module
    docstring). Scans `lines_canonical` (W4, so alias variants never split
    one parameter into two keys) but keeps `lines` (raw) as `source_text`."""
    points: dict[str, list[ParameterPoint]] = {}
    for page in doc.pages:
        for idx, canonical_line in enumerate(page.lines_canonical):
            raw_line = page.lines[idx] if idx < len(page.lines) else canonical_line
            for value, unit in numbers_with_unit(canonical_line):
                key = f"{_slug(page.heading)}::{unit.lower()}"
                points.setdefault(key, []).append(
                    ParameterPoint(version=version, value=value, unit=unit, pdf_page=page.pdf_page, source_text=raw_line)
                )
    return points


def _merge_parameter_series(
    per_version_points: list[dict[str, list[ParameterPoint]]],
) -> dict[str, list[ParameterPoint]]:
    """One dict-per-version -> one series-per-canonical_param, keeping only
    the versions where that key was actually found (a version that drops a
    section simply has a shorter series for that key — never an invented
    data point)."""
    all_keys = {key for points in per_version_points for key in points}
    merged: dict[str, list[ParameterPoint]] = {}
    for key in all_keys:
        series = [points[key][0] for points in per_version_points if points.get(key)]
        merged[key] = series
    return merged


def compute_drift_report(series_by_param: dict[str, list[ParameterPoint]], ruleset: Ruleset) -> list[DriftFinding]:
    """One DriftFinding per canonical_param — `is_drift` is decided by
    whether classify()'s cumulative_drift rule actually wins (W6), not by
    re-checking the same thresholds by hand."""
    findings: list[DriftFinding] = []
    for canonical_param, series in sorted(series_by_param.items()):
        values = [p.value for p in series]
        result = classify(None, None, ruleset, chain_history=values)

        deltas = [b - a for a, b in zip(values, values[1:])] if len(values) >= 2 else []
        direction_consistent = bool(deltas) and (all(d > 0 for d in deltas) or all(d < 0 for d in deltas))
        total_delta = (values[-1] - values[0]) if values else 0.0
        total_delta_ratio = abs(total_delta) / abs(values[0]) if values and values[0] else 0.0

        findings.append(
            DriftFinding(
                canonical_param=canonical_param,
                series=series,
                series_length=len(series),
                direction_consistent=direction_consistent,
                total_delta=total_delta,
                total_delta_ratio=total_delta_ratio,
                is_drift=result["rule_id"] == "cumulative_drift",
                risk=result["risk"],
                confidence=result["confidence"],
                rationale=result["rationale"],
                recommended_action=result["recommended_action"],
                rule_id=result["rule_id"],
                first_version=series[0].version if series else "",
                last_version=series[-1].version if series else "",
            )
        )
    return findings


def build_chain(pdf_versions: list[tuple[bytes, str]], *, ruleset_version: str | None = None) -> dict:
    """`pdf_versions` is `[(pdf_bytes, filename), ...]` in version order
    (v1 first). Creates one session per adjacent/anchor pair via the exact
    same `session_store.process_upload()` every single pairwise comparison
    already uses, then derives the parameter series / drift report from the
    resulting documents. Persists chain.json / parameter_series.json /
    drift_report.json under `data/store/sessions/<chain_id>/` — a chain
    lives alongside sessions, not inside one, since it references several."""
    if len(pdf_versions) < 2:
        raise ValueError("a chain needs at least 2 versions")

    version_labels: list[str] = []
    for pdf_bytes, filename in pdf_versions:
        meta = extract_metadata(extract_document(pdf_bytes))
        if meta.version is None:
            raise ChainVersionMissing(filename)
        version_labels.append(meta.version)

    ruleset_version = ruleset_version or latest_ruleset_version()
    ruleset = get_ruleset(ruleset_version)
    term_aliases_version = latest_term_aliases_version()
    term_aliases = get_term_aliases(term_aliases_version)

    n = len(pdf_versions)

    adjacent_session_ids: list[str] = []
    for i in range(n - 1):
        old_bytes, old_name = pdf_versions[i]
        new_bytes, new_name = pdf_versions[i + 1]
        result = session_store.process_upload(old_bytes, old_name, new_bytes, new_name, ruleset_version=ruleset_version)
        if result["status"] != "created":
            raise ChainStepFailed(f"adjacent {version_labels[i]}→{version_labels[i + 1]}", result["status"])
        adjacent_session_ids.append(result["session"]["session_id"])

    anchor_session_ids: list[str] = [adjacent_session_ids[0]]  # v1→v2 shared (§02)
    for i in range(2, n):
        old_bytes, old_name = pdf_versions[0]
        new_bytes, new_name = pdf_versions[i]
        result = session_store.process_upload(old_bytes, old_name, new_bytes, new_name, ruleset_version=ruleset_version)
        if result["status"] != "created":
            raise ChainStepFailed(f"anchor {version_labels[0]}→{version_labels[i]}", result["status"])
        anchor_session_ids.append(result["session"]["session_id"])

    per_version_points = [
        extract_parameter_points(apply_term_aliases(extract_document(pdf_bytes), term_aliases), version)
        for (pdf_bytes, _), version in zip(pdf_versions, version_labels)
    ]
    series_by_param = _merge_parameter_series(per_version_points)
    drift_report = compute_drift_report(series_by_param, ruleset)

    chain_id = _new_chain_id()
    chain_dir = SESSIONS_ROOT / chain_id
    chain_dir.mkdir(parents=True, exist_ok=True)

    manifest = ChainManifest(
        chain_id=chain_id,
        ordered_versions=version_labels,
        adjacent_session_ids=adjacent_session_ids,
        anchor_session_ids=anchor_session_ids,
        ruleset_version=ruleset_version,
        term_aliases_version=term_aliases_version,
        created_at=_now_iso(),
    )
    (chain_dir / "chain.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (chain_dir / "parameter_series.json").write_text(
        json.dumps({k: [p.model_dump() for p in v] for k, v in series_by_param.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (chain_dir / "drift_report.json").write_text(
        json.dumps([f.model_dump() for f in drift_report], ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "chain_id": chain_id,
        "manifest": manifest,
        "parameter_series": series_by_param,
        "drift_report": drift_report,
    }


def get_chain(chain_id: str) -> dict | None:
    """Read-back counterpart to build_chain — chain.json / parameter_series/
    drift_report plus any CHAIN_REVIEW events (folded the same way a
    session's review state is), so the frontend has one call to get
    everything about a chain."""
    from backend.storage import events as event_store  # local import: avoid a hard cycle at module load time

    chain_dir = SESSIONS_ROOT / chain_id
    manifest_path = chain_dir / "chain.json"
    if not manifest_path.exists():
        return None

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parameter_series = json.loads((chain_dir / "parameter_series.json").read_text(encoding="utf-8"))
    drift_report = json.loads((chain_dir / "drift_report.json").read_text(encoding="utf-8"))
    events = event_store.read_events(chain_id)
    review_state = event_store.fold_review_state(events)

    return {
        **manifest,
        "parameter_series": parameter_series,
        "drift_report": drift_report,
        "review_events": events,
        "review_state": review_state,
    }


def submit_chain_review(
    chain_id: str,
    *,
    human_verdict: str,
    reviewer_name: str,
    approval_role_code: str,
    reviewer_note: str = "",
) -> dict:
    """The W8 "鏈級簽核" action — one judgement over the whole chain instead
    of N-1 pairwise sessions each needing their own sign-off for what is
    really one cross-version pattern. Mirrors session_store.submit_review_event's
    shape but writes a CHAIN_REVIEW event, which fold_review_state() (and
    session-level review-state projections) always skip, same as
    EXPORT_SIGNOFF."""
    from backend.storage import events as event_store
    from backend.storage.config_loader import get_role_label_snapshot

    chain = get_chain(chain_id)
    if chain is None:
        raise session_store.SessionNotFound(chain_id)

    session_store.require_reviewer_name(reviewer_name)
    role_label = get_role_label_snapshot(approval_role_code)
    if role_label is None:
        raise session_store.UnknownApprovalRole(approval_role_code)

    event = event_store.append_event(
        chain_id,
        {
            "difference_id": CHAIN_REVIEW_DIFFERENCE_ID,
            "event_type": "CHAIN_REVIEW",
            "chain_id": chain_id,
            "human_verdict": human_verdict,
            "reviewer_name": reviewer_name,
            "approval_role_code": approval_role_code,
            "approval_role_label_snapshot": role_label,
            "reviewer_note": reviewer_note,
            "ruleset_version": chain["ruleset_version"],
        },
    )
    return {"event": event, "chain": get_chain(chain_id)}
