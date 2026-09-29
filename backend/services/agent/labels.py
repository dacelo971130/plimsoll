"""Rule-id → 中文名, mirrored from frontend/src/lib/ruleLabels.ts so the agent
never shows a rule id to a user (subtraction matrix: 實作名詞不給使用者看).
test_agent_labels.py fails if the two copies drift apart."""

from __future__ import annotations

RULE_LABEL: dict[str, str] = {
    "cumulative_drift": "累積漂移（跨版本）",
    "numeric_safety": "數值變更 + 安全關鍵詞",
    "parts_change": "零件料號／型號變更",
    "applicability_change": "適用範圍／條件變更",
    "step_order_change": "操作步驟順序變更",
    "obligation_plus": "義務詞彙變更 + 安全關鍵詞／數值",
    "obligation_only": "義務詞彙變更",
    "safety_only": "安全關鍵詞",
    "default": "一般文字變更（無規則命中）",
}

# Ruleset `when` keys → plain wording for explain_rule, so the model reads
# (and repeats) the condition in words, not config keys.
CONDITION_LABEL: dict[str, str] = {
    "numeric_change": "數值有變更",
    "safety_terms": "含安全關鍵詞",
    "part_number_change": "零件料號或型號變更",
    "applicability_change": "適用範圍或條件變更",
    "step_order_change": "步驟相同但順序改變",
    "obligation_change": "義務詞彙改變",
    "any_of": "且符合其中之一",
    "series_length": "連續版本數",
    "direction_consistent": "調整方向一致",
    "total_delta_ratio": "累積變化比例",
}


def rule_label(rule_id: str | None) -> str:
    if not rule_id:
        return "未知規則"
    return RULE_LABEL.get(rule_id, rule_id)
