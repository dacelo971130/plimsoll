import type { DifferenceRecord, HumanVerdict, ReviewState, ReviewVerdict, RiskLevel } from '../../types';

// What the reviewer has picked but not yet sent for the one focused card —
// shared by the list card's ReviewBar and the 專注簽核 deck (same draft, same
// submit, so switching between them mid-review loses nothing).
export interface ReviewDraft {
  verdict: ReviewVerdict | null;
  riskOverride: RiskLevel | null;
  note: string;
}

export const VERDICT_BADGE: Record<HumanVerdict, string> = {
  CONFIRMED: '✓ 已確認',
  TRACK: '◷ 需追蹤',
  REJECTED: '✕ 不採納',
  FALSE_POSITIVE: '✕ 誤報',
};

export function pageLabel(span: DifferenceRecord['old']): string {
  if (!span) return '—';
  return span.page.print_label ?? (span.page.pdf_page != null ? `p.${span.page.pdf_page}` : '—');
}

// 2026-09-27 使用者回饋 — the card's separate 「舊」「新」 jump buttons became one
// 「查看」. CenterStage's ComparisonViewer always shows both columns at ONE
// shared page number and ignores `side`, so the two buttons only ever differed
// in which page number they sent. Prefer the new side's page (where the change
// lives now); a deletion has no new side, so it falls back to the old page.
export function jumpTarget(d: DifferenceRecord): { side: 'old' | 'new'; pdfPage: number | null } {
  const newPage = d.new?.page.pdf_page ?? null;
  if (newPage != null) return { side: 'new', pdfPage: newPage };
  return { side: 'old', pdfPage: d.old?.page.pdf_page ?? null };
}

// 2026-09-28 使用者回饋 —「High 沒處理完，匯出鍵不亮」的唯一判準：曾經在
// OverviewMessage／DiffListMessage 各寫一份一樣的 filter，現在只有這一份。
export function countUnreviewedHigh(differences: DifferenceRecord[], reviewState: Record<string, ReviewState>): number {
  return differences.filter((d) => d.ai_risk === 'High' && reviewState[d.id]?.human_verdict !== 'CONFIRMED').length;
}
