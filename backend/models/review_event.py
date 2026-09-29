"""`review_events.jsonl` row schema — one append-only event per line.

Field set matches architecture-decisions-A-B.md's worked example verbatim
(§"review_events.jsonl 一行一事件") plus the §25 provenance fields
(model_id/model_version/provider/analysis_mode), which are optional because
P0 has no analysis pipeline wired yet.

Review status is NEVER a mutable column — it is always the fold/projection
of this event stream (see backend/storage/events.py::fold_review_state).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

EventType = Literal["AI_INITIAL", "HUMAN_REVIEW", "RISK_OVERRIDE", "EXPORT_SIGNOFF", "CHAIN_REVIEW"]
RiskLevel = Literal["High", "Medium", "Low"]
HumanVerdict = Literal["CONFIRMED", "TRACK", "REJECTED", "FALSE_POSITIVE"]
DataOrigin = Literal["computed", "ai_inferred", "demo_seed"]


class ReviewEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    session_id: str
    difference_id: str
    event_type: EventType

    ai_risk_at_time: Optional[RiskLevel] = None
    ai_confidence_at_time: Optional[str] = None
    ruleset_version: Optional[str] = None

    # W5/W6: set only on CHAIN_REVIEW events — a single judgement over an
    # entire chain (§02), so a reviewer isn't forced to sign off N-1
    # pairwise sessions individually for one cross-version pattern.
    chain_id: Optional[str] = None

    human_verdict: Optional[HumanVerdict] = None
    risk_override: Optional[RiskLevel] = None
    reviewer_name: Optional[str] = None
    approval_role_code: Optional[str] = None
    approval_role_label_snapshot: Optional[str] = None
    reviewer_note: Optional[str] = None

    # §25: frozen at judgement time so a later model/provider upgrade never
    # rewrites history.
    model_id: Optional[str] = None
    model_version: Optional[str] = None
    provider: Optional[str] = None
    analysis_mode: Optional[Literal["rules_first", "model_heavy", "model_only"]] = None

    data_origin: DataOrigin = "computed"

    created_at: str
    prev_event_id: Optional[str] = None
    prev_hash: Optional[str] = None
    hash: str
