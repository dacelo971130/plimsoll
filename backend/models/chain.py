"""Chain models (W5): docs/redesign/plimsoll-improvement-plan.html §02/§03.

A chain ties together the adjacent (vN→vN+1) and anchor (v1→vN) pairwise
comparisons across an ordered run of document versions. Nothing here
re-implements comparison logic — a chain is a manifest over pairwise
sessions the existing session_store already created, plus a parameter
series / drift report derived from them (see backend.services.chain).
"""

from __future__ import annotations

from pydantic import BaseModel


class ChainManifest(BaseModel):
    chain_id: str
    ordered_versions: list[str]
    adjacent_session_ids: list[str]
    anchor_session_ids: list[str]  # v1→v2 shared with adjacent_session_ids[0] (§02)
    ruleset_version: str
    term_aliases_version: str
    created_at: str


class ParameterPoint(BaseModel):
    """One (canonical_param, value, unit) observation at one version — the
    unit of a parameter_series.json entry."""

    version: str
    value: float
    unit: str
    pdf_page: int | None
    source_text: str  # original wording (W4: never the canonicalized view)


class DriftFinding(BaseModel):
    """One drift_report.json entry — classify()'s cumulative_drift verdict
    for a single canonical_param's series (W6), computed via the exact same
    rule engine every pairwise diff uses, not a bespoke threshold check."""

    canonical_param: str
    series: list[ParameterPoint]
    series_length: int
    direction_consistent: bool
    total_delta: float
    total_delta_ratio: float
    is_drift: bool
    risk: str
    confidence: str
    rationale: str
    recommended_action: str
    rule_id: str
    first_version: str
    last_version: str
