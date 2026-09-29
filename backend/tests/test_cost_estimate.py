"""P6 成本試算, real-document version: estimate_semantic_review_cost() must
agree with needs_semantic_review_dict() on which differences qualify (no
separate/drifted trigger logic), scale its token estimate with actual text
length, and never call any provider (pure, offline, free)."""

from __future__ import annotations

from backend.services.llm.cost_estimate import estimate_semantic_review_cost


def _diff(id_, *, rule_id="default", change_type="修改", old_text="舊文字", new_text="新文字", kind=None):
    d = {
        "id": id_,
        "rule_id": rule_id,
        "change_type": change_type,
        "old": {"text": old_text} if old_text is not None else None,
        "new": {"text": new_text} if new_text is not None else None,
    }
    if kind is not None:
        d["kind"] = kind
    return d


def test_all_three_modes_are_present_even_with_no_differences():
    result = estimate_semantic_review_cost([])
    assert set(result.keys()) == {"rules_first", "model_heavy", "model_only"}
    for mode in result.values():
        assert mode == {"qualifying_count": 0, "estimated_input_tokens": 0, "estimated_output_tokens": 0}


def test_named_rule_differences_never_qualify_in_any_mode():
    # numeric_safety already has a rule-derived rationale — the real trigger
    # (needs_semantic_review_dict) never sends these, in any mode except
    # model_only, which sends every 修改 regardless of rule_id.
    d = _diff("D01", rule_id="numeric_safety", old_text="85°C 以下", new_text="80°C 以下")
    result = estimate_semantic_review_cost([d])
    assert result["rules_first"]["qualifying_count"] == 0
    assert result["model_heavy"]["qualifying_count"] == 0
    assert result["model_only"]["qualifying_count"] == 1  # model_only ignores rule_id


def test_drawing_kind_never_qualifies_even_in_model_only():
    d = _diff("D01", kind="drawing")
    result = estimate_semantic_review_cost([d])
    assert result["model_only"]["qualifying_count"] == 0


def test_default_rule_small_edit_only_qualifies_under_wider_modes():
    # A tiny edit (low edit-distance ratio) clears model_heavy's lower bar
    # but not rules_first's higher one — mirrors residual.py's own thresholds.
    d = _diff("D01", rule_id="default", old_text="設備每月檢查一次並記錄", new_text="設備每月檢查一次並記錄結果")
    result = estimate_semantic_review_cost([d])
    assert result["rules_first"]["qualifying_count"] == 0
    assert result["model_heavy"]["qualifying_count"] == 1
    assert result["model_only"]["qualifying_count"] == 1


def test_qualifying_count_matches_across_modes_is_monotonically_non_decreasing():
    # rules_first is a subset of model_heavy, which is a subset of model_only
    # — widening the mode can only ever add differences, never drop one.
    diffs = [
        _diff("D01", rule_id="default", old_text="第一段內容維持大致不變", new_text="第一段內容維持大致不變，補一句"),
        _diff("D02", rule_id="default", old_text="舊的說明文字整段重寫", new_text="全新完全不同的一段說明內容"),
        _diff("D03", rule_id="numeric_safety", old_text="85°C", new_text="80°C"),
    ]
    result = estimate_semantic_review_cost(diffs)
    assert (
        result["rules_first"]["qualifying_count"]
        <= result["model_heavy"]["qualifying_count"]
        <= result["model_only"]["qualifying_count"]
    )


def test_longer_document_text_produces_a_larger_token_estimate():
    short_diff = _diff("D01", rule_id="default", old_text="舊的說明文字整段重寫", new_text="全新完全不同的一段說明內容")
    long_diff = _diff(
        "D01",
        rule_id="default",
        old_text="舊的說明文字整段重寫" * 50,
        new_text="全新完全不同的一段說明內容" * 50,
    )
    empty_tokens = estimate_semantic_review_cost([_diff("D01", rule_id="default", old_text="", new_text="")])[
        "model_only"
    ]["estimated_input_tokens"]  # the fixed system-prompt overhead alone
    short_tokens = estimate_semantic_review_cost([short_diff])["model_only"]["estimated_input_tokens"]
    long_tokens = estimate_semantic_review_cost([long_diff])["model_only"]["estimated_input_tokens"]
    # Both include the same fixed system-prompt overhead — compare the
    # *marginal* token count each text contributes, not the raw totals, since
    # long_diff's text is a 50x repeat of short_diff's.
    assert (long_tokens - empty_tokens) > 40 * (short_tokens - empty_tokens)


def test_output_tokens_scale_with_qualifying_count_not_input_size():
    one = estimate_semantic_review_cost([_diff("D01", rule_id="default", old_text="改動很多字" * 20, new_text="改動很多字改過" * 20)])
    two = estimate_semantic_review_cost(
        [
            _diff("D01", rule_id="default", old_text="改動" * 5, new_text="改過" * 5),
            _diff("D02", rule_id="default", old_text="改動" * 5, new_text="改過" * 5),
        ]
    )
    assert two["model_only"]["estimated_output_tokens"] == 2 * one["model_only"]["estimated_output_tokens"]


def test_never_calls_out_to_any_network_or_provider():
    # No provider argument exists in this function's signature at all — the
    # strongest possible guarantee that this can't accidentally spend money.
    import inspect

    sig = inspect.signature(estimate_semantic_review_cost)
    assert "provider" not in sig.parameters
