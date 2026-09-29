// Mirrors data/store/config/rulesets/v1.json's rule ids — "讓風險分級可解釋"
// (ui-spec §3.2 讀出區「觸發規則」). If a future ruleset version adds a rule
// id not listed here, fall back to showing the raw id rather than guessing.
export const RULE_LABEL: Record<string, string> = {
  cumulative_drift: '累積漂移（跨版本）',
  numeric_safety: '數值變更 + 安全關鍵詞',
  parts_change: '零件料號／型號變更',
  applicability_change: '適用範圍／條件變更',
  step_order_change: '操作步驟順序變更',
  obligation_plus: '義務詞彙變更 + 安全關鍵詞／數值',
  obligation_only: '義務詞彙變更',
  safety_only: '安全關鍵詞',
  default: '一般文字變更（無規則命中）',
};

export function ruleLabel(ruleId: string): string {
  return RULE_LABEL[ruleId] ?? ruleId;
}
