"""LLM-proposed term_alias candidates (P5 "term_aliases 核准流程"). Pure
suggestion generator — never writes to data/store/config/term_aliases/*.json
itself. See backend.storage.config_loader's pending-alias functions for the
human-approval gate every candidate this module produces must pass through
before it can affect a live comparison (TermAlias.approved_by/approved_at
already modeled that gate; this module is what finally puts candidates in
front of it, rather than requiring someone to hand-author the JSON).
"""

from __future__ import annotations

from backend.services.llm.provider import LlmProvider, LlmUnavailable
from backend.services.llm.schemas import AliasCandidateSuggestion


def suggest_term_aliases(differences: list[dict], provider: LlmProvider) -> list[AliasCandidateSuggestion]:
    """Scans a session's (already W7a-enriched) differences for ones whose
    `ai_semantic_suggestion` classified them as a pure `clarification` —
    wording changed, meaning didn't — since that's exactly the shape of a
    plausible synonym pair. Returns only the candidates the model itself
    judged `is_synonym_pair=true`; a provider failure on one difference is
    skipped, never aborts the rest."""
    candidates: list[AliasCandidateSuggestion] = []
    for d in differences:
        suggestion = d.get("ai_semantic_suggestion")
        if not suggestion or suggestion.get("semantic_change_type") != "clarification":
            continue
        old_text = (d.get("old") or {}).get("text")
        new_text = (d.get("new") or {}).get("text")
        if not old_text or not new_text:
            continue
        try:
            candidate = provider.suggest_term_alias(old_text, new_text)
        except LlmUnavailable:
            continue
        if candidate.is_synonym_pair and candidate.canonical and candidate.variant:
            candidates.append(candidate)
    return candidates
