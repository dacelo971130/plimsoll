import type { AgentSuggestion, AgentWarning } from '../../types';

// Same words the ReviewBar uses (ReviewBar.tsx VERDICT_OPTIONS) — an agent
// suggestion and the button it prefills must read identically.
export const VERDICT_LABEL: Record<AgentSuggestion['verdict'], string> = {
  CONFIRMED: '✓ 已確認',
  TRACK: '◷ 需追蹤',
  REJECTED: '✕ 不採納',
};

export const WARNING_LABEL: Record<AgentWarning['kind'], string> = {
  missing_metadata: '文件資訊缺漏',
  low_confidence: '需人工校對',
  unsupported: '找不到依據',
  suspicious_instruction: '文件內有可疑指令',
};

export const CONFIDENCE_LABEL = { high: '信心 高', medium: '信心 中', low: '信心 低' } as const;

export const IMPACT_LABEL = {
  equipment: '設備',
  parts: '零件',
  procedures: '程序',
  inspections: '檢查項目',
} as const;

/** The review note that ties a human-confirmed verdict back to the agent run
 * that suggested it (spec §4.4). Only added when the reviewer kept the
 * suggested verdict — changing it means they didn't adopt the suggestion. */
export function adoptedNote(runId: string, note = ''): string {
  const marker = `採納 Agent 建議（${runId}）`;
  if (note.includes(marker)) return note;
  return note.trim() ? `${note.trim()}\n${marker}` : marker;
}
