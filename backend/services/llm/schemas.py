"""Structured-output contracts for the two W7 call sites. Both are strict
Pydantic models passed as `output_format` to `client.messages.parse()` — the
SDK validates the model's response against these before it ever reaches
application code (docs/redesign/plimsoll-improvement-plan.html §03).

Neither schema has a `risk` field — that's the whole point (§03 "LLM 只做
語意解讀"): the model proposes, a human/rule decides."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SemanticChangeType = Literal[
    "clarification",  # 用詞更精確，語意未變
    "scope_narrowing",  # 適用範圍/條件收窄
    "scope_widening",  # 適用範圍/條件擴大
    "procedure_change",  # 操作程序實質變更（非純措辭）
    "responsibility_shift",  # 負責角色/單位變更
    "no_semantic_change",  # 純文字潤飾，語意不變
    "unclear",  # 模型無法判斷 — 誠實回報，不是硬猜一個類型
]


class ResidualSuggestion(BaseModel):
    """W7a output — attached to `differences.json` as `ai_semantic_suggestion`,
    never written into `ai_risk`/`ai_confidence`/`rule_id`."""

    semantic_change_type: SemanticChangeType
    suggest_escalate: bool = Field(description="模型是否建議人工將此筆風險級調高")
    suggested_risk: Literal["High", "Medium", "Low"] | None = Field(
        default=None, description="僅在 suggest_escalate=true 時提供；絕不直接寫入 ai_risk"
    )
    rationale: str = Field(description="一到兩句話，說明語意變化與建議理由，供覆核者參考")


class TrailAnalysis(BaseModel):
    """W7b output — one parameter series' trend judgement. `onset_version`
    forces the model to point at a traceable version, per §03: "不是『這有
    沒有問題』，而是『這個趨勢是否正在侵蝕安全邊界？若是，從第幾版開始？』"."""

    is_eroding_safety_margin: bool
    onset_version: str | None = Field(
        default=None, description="侵蝕趨勢開始的版本號；is_eroding_safety_margin=false 時為 null"
    )
    rationale: str = Field(description="說明趨勢判讀依據，須可追溯到具體版本與數值")


class AliasCandidateSuggestion(BaseModel):
    """P5 term_aliases 核准流程 output — one old/new sentence pair, judged for
    whether it's a pure synonym swap worth proposing as a term_alias entry.
    Like every other schema here: a suggestion, never written to
    data/store/config/term_aliases/*.json directly — only a human-approved
    pending candidate (backend.storage.config_loader) ever reaches there."""

    is_synonym_pair: bool = Field(description="這兩句是否只是同義詞替換，語意完全相同、只是用詞不同")
    canonical: str | None = Field(default=None, description="建議採用的標準詞，通常是新版用詞；is_synonym_pair=false 時為 null")
    variant: str | None = Field(default=None, description="另一種說法，通常是舊版用詞；is_synonym_pair=false 時為 null")
    rationale: str = Field(description="一句話說明為何判斷是/不是同義詞替換")


class DrawingRegionSuggestion(BaseModel):
    """P5 §26 engineering-drawing layer output — describes ONE pixel-diff
    region (backend.services.drawing_diff), never the whole page. Like the
    other two schemas, this is a suggestion overlaid on a deterministic
    result (the region's bbox itself came from pixel diff, not the model) —
    `component_label`/`change_summary` are never treated as ground truth,
    only shown alongside the crop images for a human to confirm."""

    component_label: str | None = Field(
        default=None, description="推測的閥號/料號/管路標籤，例如 'CP-120' 或 '冷卻水入口閥'；看不出來就留空，不要亂猜"
    )
    change_summary: str = Field(description="一到兩句話描述這個區塊新舊版本之間的差異")
    confidence: float = Field(ge=0.0, le=1.0, description="對這個描述整體正確性的信心")
