"""P5 term_aliases 候選 suggestion tests — FakeProvider, no network call."""

from __future__ import annotations

from backend.services.llm.alias_suggest import suggest_term_aliases
from backend.services.llm.schemas import AliasCandidateSuggestion
from backend.tests.test_llm import FakeProvider


def _diff(change_type_llm="clarification", old_text="舊說法", new_text="新說法"):
    return {
        "id": "D01",
        "old": {"text": old_text} if old_text else None,
        "new": {"text": new_text} if new_text else None,
        "ai_semantic_suggestion": {"semantic_change_type": change_type_llm} if change_type_llm else None,
    }


def test_only_clarification_differences_are_sent_to_the_provider():
    provider = FakeProvider()
    diffs = [_diff(change_type_llm="clarification"), _diff(change_type_llm="scope_widening"), _diff(change_type_llm=None)]

    suggest_term_aliases(diffs, provider)

    assert len(provider.calls) == 1


def test_returns_only_candidates_the_model_judged_as_synonym_pairs():
    provider = FakeProvider(
        alias_candidate=AliasCandidateSuggestion(is_synonym_pair=True, canonical="A", variant="B", rationale="x")
    )
    candidates = suggest_term_aliases([_diff()], provider)
    assert len(candidates) == 1
    assert candidates[0].canonical == "A"


def test_non_synonym_verdict_is_not_returned_as_a_candidate():
    provider = FakeProvider(
        alias_candidate=AliasCandidateSuggestion(is_synonym_pair=False, rationale="語意其實不同")
    )
    candidates = suggest_term_aliases([_diff()], provider)
    assert candidates == []


def test_provider_failure_is_skipped_not_raised():
    provider = FakeProvider(fail=True)
    candidates = suggest_term_aliases([_diff()], provider)
    assert candidates == []


def test_missing_old_or_new_text_is_skipped():
    provider = FakeProvider()
    diffs = [_diff(old_text=None), _diff(new_text=None)]
    suggest_term_aliases(diffs, provider)
    assert provider.calls == []
