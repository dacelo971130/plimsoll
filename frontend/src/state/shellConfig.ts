import type { Settings } from './useSettings';

// plimsoll-two-shell-spec.md §1.2 — the ONLY place shell A/B diverge. Every
// item in ui-spec's §04 「留」list that isn't driven by one of these fields
// is shared, full stop — no third divergence point. Both shells carry the
// exact same capability set; this only ever changes density/pacing.
export type ShellVariant = 'A' | 'B';

export interface ShellConfig {
  fontScale: Settings['fontSize'];
  overviewPresentation: 'sentence' | 'tiles';
  magnifierInput: 'hover' | 'click';
  reviewMode: 'inline' | 'stepper';
  showPdfNewTabLink: boolean;
}

// 匯出 no longer has a shell-specific accordion/sticky split — it moved into
// a modal opened from the overview card's button, same for both shells (see
// the 2026-09-15 follow-up redesign session that superseded that part of
// plimsoll-two-shell-spec.md §3 #30). historyDefaultCollapsed (§3 #35) is
// gone too — HistoryRail itself was deleted (2026-09-27, 使用者回饋: 左欄整
// 個砍掉), so there's no longer a rail whose default collapse state a shell
// could pick.
export const SHELL_CONFIG: Record<ShellVariant, ShellConfig> = {
  A: {
    fontScale: 'md',
    overviewPresentation: 'sentence',
    magnifierInput: 'hover',
    reviewMode: 'inline',
    showPdfNewTabLink: false,
  },
  B: {
    fontScale: 'lg',
    overviewPresentation: 'tiles',
    magnifierInput: 'click',
    reviewMode: 'stepper',
    showPdfNewTabLink: true,
  },
};
