"""W7 LLM semantic layer tests. Everything here runs against a FAKE
LlmProvider — no test in this repo makes a real network call, matching
residual.py's module docstring: the semantic layer is opt-in and its trigger
heuristic / enrichment contract must be verifiable without spending API
credits or depending on network availability."""

from __future__ import annotations

import pytest

from backend.services.comparison import DifferenceRecord, PageRef, SourceSpan
from backend.services.llm.provider import LlmUnavailable, get_llm_provider, resolve_llm_provider
from backend.services.llm.credentials import LlmCredentials
from backend.services.llm.residual import (
    edit_distance_ratio,
    enrich_differences_with_semantic_suggestions,
    enrich_session_differences,
    needs_semantic_review,
)
from backend.services.llm.schemas import (
    AliasCandidateSuggestion,
    DrawingRegionSuggestion,
    ResidualSuggestion,
    TrailAnalysis,
)
from backend.services.llm.trail_analysis import analyze_trail


class FakeProvider:
    """Implements the LlmProvider protocol without touching the network."""

    model_id = "fake-model"
    provider_name = "fake"

    def __init__(
        self,
        *,
        fail: bool = False,
        residual: ResidualSuggestion | None = None,
        trail: TrailAnalysis | None = None,
        drawing_region: DrawingRegionSuggestion | None = None,
        alias_candidate: AliasCandidateSuggestion | None = None,
    ):
        self.fail = fail
        self._residual = residual or ResidualSuggestion(
            semantic_change_type="scope_widening", suggest_escalate=True, suggested_risk="Medium", rationale="範圍擴大"
        )
        self._trail = trail or TrailAnalysis(is_eroding_safety_margin=True, onset_version="v1.1", rationale="持續下降")
        self._drawing_region = drawing_region or DrawingRegionSuggestion(
            component_label="CP-120", change_summary="閥門位置略有偏移", confidence=0.7
        )
        self._alias_candidate = alias_candidate or AliasCandidateSuggestion(
            is_synonym_pair=True, canonical="溫度上限", variant="最高溫度限值", rationale="同一件事的兩種說法"
        )
        self.calls: list[tuple] = []

    def classify_residual(self, old_text, new_text, *, effort="medium"):
        self.calls.append(("classify_residual", old_text, new_text))
        if self.fail:
            raise LlmUnavailable("boom")
        return self._residual

    def analyze_trail(self, series, *, effort="high"):
        self.calls.append(("analyze_trail", series))
        if self.fail:
            raise LlmUnavailable("boom")
        return self._trail

    def describe_drawing_region(self, old_crop_png, new_crop_png, *, effort="medium"):
        self.calls.append(("describe_drawing_region", old_crop_png, new_crop_png))
        if self.fail:
            raise LlmUnavailable("boom")
        return self._drawing_region

    def suggest_term_alias(self, old_text, new_text, *, effort="low"):
        self.calls.append(("suggest_term_alias", old_text, new_text))
        if self.fail:
            raise LlmUnavailable("boom")
        return self._alias_candidate


def _page(pdf_page=1):
    return PageRef(pdf_page=pdf_page, print_label=None, label_source="unknown")


def _diff(rule_id="default", change_type="修改", old_text="舊的說明文字。", new_text="新的說明文字完全重寫過了。") -> DifferenceRecord:
    return DifferenceRecord(
        id="D01",
        change_type=change_type,
        ai_risk="Low",
        ai_confidence="高",
        explanation="一般文字或說明變更",
        affected="1. 段落",
        recommended_action="更新技術手冊檔案存檔",
        old=SourceSpan(page=_page(), text=old_text) if old_text is not None else None,
        new=SourceSpan(page=_page(), text=new_text) if new_text is not None else None,
        ruleset_version="v2",
        rule_id=rule_id,
    )


# --------------------------------------------------------------------------
# provider factory — no real network call, but real object construction
# --------------------------------------------------------------------------

def _clear_all_provider_env(monkeypatch):
    for var in (
        "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
        "AWS_BEARER_TOKEN_BEDROCK", "AWS_REGION", "AWS_DEFAULT_REGION", "PLIMSOLL_BEDROCK_MODEL", "PLIMSOLL_AI_PROVIDER",
    ):
        monkeypatch.delenv(var, raising=False)


def test_get_llm_provider_returns_none_without_an_api_key(monkeypatch):
    _clear_all_provider_env(monkeypatch)
    assert get_llm_provider() is None


def test_get_llm_provider_returns_a_provider_with_a_key_present(monkeypatch):
    # A fabricated key — client construction never calls the network.
    _clear_all_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    provider = get_llm_provider()
    assert provider is not None
    assert provider.provider_name == "anthropic"
    assert provider.model_id == "claude-opus-5"


def test_get_llm_provider_picks_gemini_when_only_gemini_key_set(monkeypatch):
    _clear_all_provider_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    provider = get_llm_provider()
    assert provider is not None
    assert provider.provider_name == "gemini"


def test_get_llm_provider_picks_openai_when_only_openai_key_set(monkeypatch):
    _clear_all_provider_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    provider = get_llm_provider()
    assert provider is not None
    assert provider.provider_name == "openai"


def test_get_llm_provider_prefers_anthropic_when_multiple_keys_set(monkeypatch):
    _clear_all_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    provider = get_llm_provider()
    assert provider.provider_name == "anthropic"


# --------------------------------------------------------------------------
# P5 multi-provider BYOK — resolve_llm_provider()
# --------------------------------------------------------------------------


def test_resolve_llm_provider_with_explicit_anthropic_credentials(monkeypatch):
    _clear_all_provider_env(monkeypatch)
    provider = resolve_llm_provider(LlmCredentials("anthropic", "sk-ant-not-real"))
    assert provider is not None
    assert provider.provider_name == "anthropic"


def test_resolve_llm_provider_with_explicit_gemini_credentials(monkeypatch):
    _clear_all_provider_env(monkeypatch)
    provider = resolve_llm_provider(LlmCredentials("gemini", "not-a-real-key"))
    assert provider is not None
    assert provider.provider_name == "gemini"
    assert provider.model_id == "gemini-3.8-flash"


def test_resolve_llm_provider_with_explicit_openai_credentials(monkeypatch):
    _clear_all_provider_env(monkeypatch)
    provider = resolve_llm_provider(LlmCredentials("openai", "not-a-real-key"))
    assert provider is not None
    assert provider.provider_name == "openai"
    assert provider.model_id == "gpt-4o"


def test_resolve_llm_provider_unknown_provider_id_degrades_to_none(monkeypatch):
    _clear_all_provider_env(monkeypatch)
    assert resolve_llm_provider(LlmCredentials("groq", "some-key")) is None
    # Bedrock without a region can't route anywhere — unavailable, not a guess.
    assert resolve_llm_provider(LlmCredentials("bedrock", "some-key")) is None


def test_resolve_llm_provider_falls_back_to_env_when_headers_missing(monkeypatch):
    _clear_all_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-real")
    provider = resolve_llm_provider(LlmCredentials())
    assert provider is not None
    assert provider.provider_name == "anthropic"


def test_resolve_llm_provider_requires_both_id_and_key(monkeypatch):
    _clear_all_provider_env(monkeypatch)
    assert resolve_llm_provider(LlmCredentials("gemini", None)) is None
    assert resolve_llm_provider(LlmCredentials(None, "some-key")) is None


# --------------------------------------------------------------------------
# W7a trigger heuristic
# --------------------------------------------------------------------------

def test_edit_distance_ratio_is_zero_for_identical_text():
    assert edit_distance_ratio("一樣的文字", "一樣的文字") == 0.0


def test_edit_distance_ratio_is_one_for_completely_different_text():
    assert edit_distance_ratio("abc", "xyz") == 1.0


def test_needs_semantic_review_requires_default_rule_and_large_edit():
    assert needs_semantic_review(_diff(rule_id="default", old_text="A", new_text="完全不同的一段話內容")) is True
    assert needs_semantic_review(_diff(rule_id="numeric_safety")) is False  # named rule already explains itself
    assert needs_semantic_review(_diff(change_type="新增", old_text=None)) is False  # unambiguous already


# --------------------------------------------------------------------------
# P5 analysis_mode — widens/narrows the trigger, never touches ai_risk
# --------------------------------------------------------------------------

_SMALL_EDIT_OLD = "溫度需維持在攝氏85度以下才可以進行下一步操作程序"
_SMALL_EDIT_NEW = "溫度需維持在攝氏85度以內才可以進行下一步操作流程"  # edit_distance_ratio ≈ 0.12: above model_heavy's 0.10 bar, below rules_first's 0.30


def test_rules_first_is_the_default_and_matches_pre_p5_behavior():
    small_edit = _diff(rule_id="default", old_text=_SMALL_EDIT_OLD, new_text=_SMALL_EDIT_NEW)
    assert needs_semantic_review(small_edit) is False
    assert needs_semantic_review(small_edit, analysis_mode="rules_first") is False


def test_model_heavy_lowers_the_edit_ratio_bar_for_default_rule_changes():
    small_edit = _diff(rule_id="default", old_text=_SMALL_EDIT_OLD, new_text=_SMALL_EDIT_NEW)
    assert needs_semantic_review(small_edit, analysis_mode="model_heavy") is True
    # still gated to default-rule 修改 — a named rule's differences are untouched.
    assert needs_semantic_review(_diff(rule_id="numeric_safety"), analysis_mode="model_heavy") is False


def test_model_only_sends_every_modification_regardless_of_rule_or_edit_size():
    tiny_edit = _diff(rule_id="numeric_safety", old_text="A", new_text="A.")
    assert needs_semantic_review(tiny_edit, analysis_mode="model_only") is True
    # non-修改 change types are still never sent — 新增/刪除 already unambiguous.
    assert needs_semantic_review(_diff(change_type="新增", old_text=None), analysis_mode="model_only") is False


def test_analysis_mode_never_changes_ai_risk_or_rule_id():
    d = _diff(rule_id="numeric_safety", old_text="A", new_text="B")
    provider = FakeProvider()
    enriched = enrich_differences_with_semantic_suggestions([d], provider, analysis_mode="model_only")
    assert enriched[0].ai_risk == d.ai_risk
    assert enriched[0].rule_id == d.rule_id
    assert enriched[0].ai_semantic_suggestion is not None  # did get sent, thanks to model_only


def test_enrich_session_differences_skips_drawing_kind_even_in_model_only_mode():
    drawing = {
        "id": "D01",
        "kind": "drawing",
        "change_type": "修改",
        "rule_id": None,
        "old": {"text": "第 2 頁工程圖"},
        "new": {"text": "第 2 頁工程圖"},
    }
    provider = FakeProvider()
    out = enrich_session_differences([drawing], provider, analysis_mode="model_only")
    assert out == [drawing]
    assert provider.calls == []
    assert needs_semantic_review(_diff(rule_id="default", old_text="小改一字", new_text="小改一子")) is False  # tiny edit


# --------------------------------------------------------------------------
# W7a enrichment — dataclass and dict variants
# --------------------------------------------------------------------------

def test_enrichment_only_touches_selected_differences_and_never_ai_risk():
    reviewed = _diff(rule_id="default")
    named_rule = _diff(rule_id="numeric_safety")
    provider = FakeProvider()

    out = enrich_differences_with_semantic_suggestions([reviewed, named_rule], provider)

    enriched, untouched = out
    assert enriched.ai_semantic_suggestion == provider._residual.model_dump()
    assert enriched.data_origin == "ai_inferred"
    assert enriched.ai_risk == "Low"  # untouched — LLM never sets this
    assert enriched.rule_id == "default"  # untouched

    assert untouched.ai_semantic_suggestion is None
    assert untouched.data_origin == "computed"
    assert [c[0] for c in provider.calls] == ["classify_residual"]  # only the qualifying one was sent


def test_enrichment_leaves_a_difference_unsuggested_when_the_provider_fails():
    reviewed = _diff(rule_id="default")
    out = enrich_differences_with_semantic_suggestions([reviewed], FakeProvider(fail=True))
    assert out[0].ai_semantic_suggestion is None
    assert out[0].data_origin == "computed"


def test_enrich_session_differences_dict_shape_matches_dataclass_behavior():
    reviewed = {
        "id": "D01", "rule_id": "default", "change_type": "修改", "ai_risk": "Low",
        "old": {"text": "舊的說明文字。"}, "new": {"text": "新的說明文字完全重寫過了。"},
    }
    named_rule = {
        "id": "D02", "rule_id": "numeric_safety", "change_type": "修改", "ai_risk": "High",
        "old": {"text": "85°C"}, "new": {"text": "80°C"},
    }
    provider = FakeProvider()

    out = enrich_session_differences([reviewed, named_rule], provider)

    assert out[0]["ai_semantic_suggestion"] == provider._residual.model_dump()
    assert out[0]["data_origin"] == "ai_inferred"
    assert out[0]["ai_risk"] == "Low"  # untouched
    assert "ai_semantic_suggestion" not in out[1]
    assert reviewed.get("ai_semantic_suggestion") is None  # original dict untouched (new dict returned)


# --------------------------------------------------------------------------
# W7b trail analysis
# --------------------------------------------------------------------------

def test_analyze_trail_returns_none_for_a_too_short_series():
    from backend.models.chain import ParameterPoint

    series = [ParameterPoint(version="v1.0", value=20.0, unit="%", pdf_page=1, source_text="x")]
    assert analyze_trail(series, FakeProvider()) is None


def test_analyze_trail_delegates_to_the_provider():
    from backend.models.chain import ParameterPoint

    series = [
        ParameterPoint(version="v1.0", value=20.0, unit="%", pdf_page=1, source_text="x"),
        ParameterPoint(version="v1.1", value=19.8, unit="%", pdf_page=1, source_text="y"),
    ]
    provider = FakeProvider()
    result = analyze_trail(series, provider)
    assert result == provider._trail
    assert provider.calls[0][0] == "analyze_trail"


def test_analyze_trail_returns_none_when_provider_fails():
    from backend.models.chain import ParameterPoint

    series = [
        ParameterPoint(version="v1.0", value=20.0, unit="%", pdf_page=1, source_text="x"),
        ParameterPoint(version="v1.1", value=19.8, unit="%", pdf_page=1, source_text="y"),
    ]
    assert analyze_trail(series, FakeProvider(fail=True)) is None
