"""Config-file-backed models — never hardcoded enums / thresholds.

approval_roles.json, rulesets/v{N}.json and approval_policies/v{N}.json are
the sources of truth (architecture-decisions-A-B.md §20). Adding a role or
adjusting a threshold is a new/edited config file, never a code change.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

RiskLevel = Literal["High", "Medium", "Low"]

RISK_ORDER: dict[str, int] = {"Low": 0, "Medium": 1, "High": 2}


class ApprovalRole(BaseModel):
    code: str
    label_zh: str
    label_en: str
    is_active: bool = True
    sort_order: int = 99
    is_system_seed: bool = False
    custom_role_label: str | None = None


class RulesetRule(BaseModel):
    id: str
    priority: int
    when: dict
    then: dict


class Ruleset(BaseModel):
    version: str
    safety_terms: list[str] = []
    obligation_terms: list[str] = []
    applicability_terms: list[str] = []  # v2+: 適用範圍詞（"適用"/"限用"/"僅適用"）
    rules: list[RulesetRule] = []


class TermAlias(BaseModel):
    """One canonicalization entry (W4). `approved_by`/`approved_at` make the
    table itself auditable — an LLM (W7) may PROPOSE a candidate offline, but
    only a human-approved entry ever reaches the live comparison path; the
    engine never infers synonymy on its own."""

    canonical: str
    variants: list[str] = []
    approved_by: str | None = None
    approved_at: str | None = None


class TermAliasTable(BaseModel):
    version: str
    aliases: list[TermAlias] = []


class GlossaryTerm(BaseModel):
    term: str
    aliases: list[str] = []
    category: str
    definition: str
    # Where the definition came from — repo paths, or for domain terms the
    # law article / standard-term entry URL. Review evidence only; never
    # sent to the UI (subtraction matrix: 實作名詞不給使用者看).
    sources: list[str]
    status: Literal["draft", "pending", "approved"]


class Glossary(BaseModel):
    """data/store/config/glossary/v{N}.json — the controlled vocabulary the
    help page, the sign-off report appendix and the review agent share
    (plimsoll-review-agent-spec.md §4.5). Until a human flips `status` to
    "approved", the agent and the report must not cite it; the help page
    may show it with a draft notice."""

    version: str
    status: Literal["draft", "approved"]
    drafted_by: str | None = None
    drafted_at: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    note: str | None = None
    # A stand-in table the user chose to switch on before an expert review
    # (2026-10-02): approved so the agent can cite it, but every place that
    # shows a definition says it's simulated, and the formal sign-off
    # report leaves it out (backend/services/export.py).
    simulated: bool = False
    terms: list[GlossaryTerm]


class PendingAlias(BaseModel):
    """One LLM-proposed candidate awaiting human approval (P5 "term_aliases
    核准流程"). Lives in data/store/config/term_aliases/pending.json — a
    queue, not an audit trail; the audit trail is the new immutable
    term_aliases/v{N}.json version an approval creates (backend.storage.
    config_loader.resolve_pending_alias)."""

    id: str
    canonical: str
    variant: str
    rationale: str
    source_session_id: str | None = None
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: str
    approved_by: str | None = None
    approved_at: str | None = None


class ApprovalPolicy(BaseModel):
    ruleset_version: str
    policies: dict[str, RiskLevel]

    def max_risk_for(self, approval_role_code: str) -> RiskLevel | None:
        return self.policies.get(approval_role_code)

    def can_approve(self, approval_role_code: str, risk: RiskLevel) -> bool:
        """Server-side enforcement — not just a UI hint (v4 決定 #3)."""
        ceiling = self.max_risk_for(approval_role_code)
        if ceiling is None:
            return False
        return RISK_ORDER[risk] <= RISK_ORDER[ceiling]
