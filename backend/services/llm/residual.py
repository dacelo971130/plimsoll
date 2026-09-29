"""W7a residual classification: docs/redesign/plimsoll-improvement-plan.html
§03. Only the differences the rule engine landed on `default` AND that
changed a lot get sent to the model — on the real demo that's 2-3 of 10+
differences, not all of them.

Deliberately NOT wired into session_store.process_upload() or
chain.build_chain(): those stay 100% deterministic and free by default,
matching "LLM 是加值層不是相依" literally — a caller (API endpoint, script,
or a future background job) must explicitly call
`enrich_differences_with_semantic_suggestions()` and pass a provider it got
from `get_llm_provider()`. This also means no test in this repo makes a real
network call: tests exercise the trigger heuristic and the enrichment
contract against a fake `LlmProvider`, never `AnthropicProvider` itself.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from backend.services.comparison import DifferenceRecord
from backend.services.llm.provider import LlmProvider, LlmUnavailable
from backend.services.llm.schemas import ResidualSuggestion

AnalysisMode = Literal["rules_first", "model_heavy", "model_only"]

RESIDUAL_EDIT_RATIO_THRESHOLD = 0.30
# P5 `model_heavy`: the same trigger, just far more permissive — most
# 修改-type default-rule differences qualify, not only heavily-reworded ones.
MODEL_HEAVY_EDIT_RATIO_THRESHOLD = 0.10


def _edit_ratio_threshold(analysis_mode: AnalysisMode) -> float:
    return MODEL_HEAVY_EDIT_RATIO_THRESHOLD if analysis_mode == "model_heavy" else RESIDUAL_EDIT_RATIO_THRESHOLD


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def edit_distance_ratio(old_text: str | None, new_text: str | None) -> float:
    old_text, new_text = old_text or "", new_text or ""
    longest = max(len(old_text), len(new_text), 1)
    return _levenshtein(old_text, new_text) / longest


def needs_semantic_review(difference: DifferenceRecord, *, analysis_mode: AnalysisMode = "rules_first") -> bool:
    """The deterministic trigger (§03) — the model never decides whether it
    gets consulted. `analysis_mode` (P5, session-level config knob) changes
    how WIDE this net is cast; it never changes what the rule engine itself
    decided (`ai_risk`/`rule_id` stay untouched no matter the mode — see
    enrich_*() below):

    - `rules_first` (default): only a `default`-rule 修改 with a large edit
      qualifies — 新增/刪除 already have an unambiguous change_type, and
      anything a named rule already caught has a rule-derived rationale.
    - `model_heavy`: same shape, but a much lower edit-ratio bar — most
      default-rule 修改 differences qualify, not just heavily-reworded ones.
    - `model_only`: every 修改 difference qualifies, regardless of which
      rule matched or how small the edit was — the rule engine's risk
      classification is still authoritative (unaffected), this only widens
      which differences also get an LLM reading alongside it.
    """
    if difference.change_type != "修改":
        return False
    if analysis_mode == "model_only":
        return True
    if difference.rule_id != "default":
        return False
    old_text = difference.old.text if difference.old else None
    new_text = difference.new.text if difference.new else None
    return edit_distance_ratio(old_text, new_text) > _edit_ratio_threshold(analysis_mode)


def enrich_differences_with_semantic_suggestions(
    differences: list[DifferenceRecord], provider: LlmProvider, *, analysis_mode: AnalysisMode = "rules_first"
) -> list[DifferenceRecord]:
    """Returns a new list — `ai_risk`/`ai_confidence`/`rule_id` are never
    touched; only `ai_semantic_suggestion`/`data_origin` change, and only on
    the differences `needs_semantic_review()` selects. A provider failure
    for one difference is caught and skipped (leaves it as `computed`,
    unsuggested) rather than aborting the whole batch."""
    out: list[DifferenceRecord] = []
    for d in differences:
        if not needs_semantic_review(d, analysis_mode=analysis_mode):
            out.append(d)
            continue
        old_text = d.old.text if d.old else None
        new_text = d.new.text if d.new else None
        try:
            suggestion: ResidualSuggestion = provider.classify_residual(old_text, new_text)
        except LlmUnavailable:
            out.append(d)
            continue
        out.append(replace(d, ai_semantic_suggestion=suggestion.model_dump(), data_origin="ai_inferred"))
    return out


def needs_semantic_review_dict(difference: dict, *, analysis_mode: AnalysisMode = "rules_first") -> bool:
    """Dict-shaped counterpart of `needs_semantic_review()` — public (not
    prefixed) because backend.services.llm.batch_jobs also needs to know
    which differences qualify BEFORE calling the provider, to build the
    batch request list up front."""
    if difference.get("change_type") != "修改":
        return False
    if analysis_mode == "model_only":
        return True
    if difference.get("rule_id") != "default":
        return False
    old_text = (difference.get("old") or {}).get("text")
    new_text = (difference.get("new") or {}).get("text")
    return edit_distance_ratio(old_text, new_text) > _edit_ratio_threshold(analysis_mode)


def enrich_session_differences(
    differences: list[dict], provider: LlmProvider, *, analysis_mode: AnalysisMode = "rules_first"
) -> list[dict]:
    """Dict-shaped counterpart of `enrich_differences_with_semantic_suggestions`
    — operates on the exact JSON shape `differences.json`/the API already
    use, since `session.json`/`differences.json` are written-once (see
    session_store.py's module docstring) and this must never mutate that
    file. The caller (an API endpoint) returns this list directly in its
    response instead of persisting over the original; a suggestion's
    permanent record is the AI_INITIAL audit event the caller appends
    alongside it, not a rewrite of differences.json.

    `analysis_mode` widens/narrows `needs_semantic_review` exactly like the
    dataclass version above — drawing differences (`kind: "drawing"`) never
    qualify regardless of mode, since `change_type` on those means something
    different (page-level 新增/刪除/修改, no rule_id) and they already carry
    their own AI reading via the drawing pipeline, not this one."""
    out: list[dict] = []
    for d in differences:
        if d.get("kind") == "drawing" or not needs_semantic_review_dict(d, analysis_mode=analysis_mode):
            out.append(d)
            continue
        old_text = (d.get("old") or {}).get("text")
        new_text = (d.get("new") or {}).get("text")
        try:
            suggestion = provider.classify_residual(old_text, new_text)
        except LlmUnavailable:
            out.append(d)
            continue
        out.append({**d, "ai_semantic_suggestion": suggestion.model_dump(), "data_origin": "ai_inferred"})
    return out
