import { SHELL_CONFIG, type ShellVariant } from '../../state/shellConfig';
import type { SessionSummary } from '../../types';
import type { RiskFilter } from './DiffListMessage';
import { countUnreviewedHigh } from './diffFormat';
import { RISK_FILL } from './riskStyle';

interface OverviewMessageProps {
  session: SessionSummary;
  shell: ShellVariant;
  filter: RiskFilter;
  onFilterChange: (f: RiskFilter) => void;
}

// Two pairs, not four loose tiles — see the row's comment below.
const RISK_FILTER_PAIRS: RiskFilter[][] = [
  ['All', 'High'],
  ['Medium', 'Low'],
];
// 2026-09-27 使用者回饋「縮小」— the tiles went from a stacked label/number
// block to a single line, which only fits four across without the 「只看」
// prefix; the pressed/filled state already says "this is the filter now on".
const RISK_FILTER_LABEL: Record<RiskFilter, string> = { All: '全部', High: 'High', Medium: 'Medium', Low: 'Low' };

// idle = tinted + coloured border/text, active = the shared solid fill. Text
// stays on its own contrast-checked colour in both states (never a fill
// laid over the label), per 「醒目色但不可擋住字」.
const TILE_STYLE: Record<RiskFilter, { idle: string; active: string }> = {
  All: { idle: 'border-line bg-surface-2 text-ink-700 hover:bg-accent-soft', active: 'border-ink-800 bg-ink-800 text-on-accent' },
  High: { idle: 'border-high-fill/60 bg-high-fill/10 text-high-700 hover:bg-high-fill/20', active: `border-high-fill ${RISK_FILL.High}` },
  Medium: { idle: 'border-med-fill/70 bg-med-fill/15 text-med-700 hover:bg-med-fill/25', active: `border-med-fill ${RISK_FILL.Medium}` },
  Low: { idle: 'border-low-fill/60 bg-low-fill/10 text-low-700 hover:bg-low-fill/20', active: `border-low-fill ${RISK_FILL.Low}` },
};

// 2026-09-15 redesign — the four KPI rectangles (總差異／High／已覆核／待簽核
// High) and the risk-filter chips used to show the SAME two numbers twice
// (總差異=顯示全部, High=只看 High) in two separate widgets. Folding the risk
// filter INTO these four slots as clickable tag-buttons removes that
// duplication and gives the numbers a real job instead of being read-only.
function RiskTagButton({
  filter,
  active,
  value,
  onClick,
}: {
  filter: RiskFilter;
  active: boolean;
  value: number;
  onClick: () => void;
}) {
  const style = TILE_STYLE[filter];
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={filter === 'All' ? '顯示全部' : `只看 ${filter}`}
      className={`flex flex-1 items-center gap-1.5 whitespace-nowrap rounded-lg border px-2 py-1.5 ${
        active ? `${style.active} tile-pop` : style.idle
      }`}
    >
      <span className="text-[12px] font-medium">{RISK_FILTER_LABEL[filter]}</span>
      <span className="ml-auto text-[14px] font-semibold tabular-nums">{value}</span>
    </button>
  );
}

// ui-spec §3.2 `overview` — KPI／風險篩選。
// 2026-09-27 使用者回饋：匯出／新的比對移到右欄最上方（RightPanel 標題列），
// 「開始逐項覆核」拔掉，已覆核／待簽核 High 這兩個不能按的數字移進待核准清單
// 的標題（DiffListMessage），這張卡只剩「篩選」一件事。
// 2026-09-28 使用者回饋：變更類型篩選（全部類型／新增／刪除／修改）整排拔掉，
// 只剩風險篩選；每張卡片上仍標著自己的變更類型。
// 2026-09-28 使用者回饋「受影響設備／流程留在匯出文件裡就好，直接拔掉」— 這個
// 彙總清單只從畫面上移除；匯出（backend/services/export.py）本來就是逐筆讀
// `d.affected`，跟這裡完全無關，不受影響。單筆差異卡片自己的 affected 標籤
// （DiffListMessage／FocusReviewDeck）也還在，只是這裡不再重複列一次去重清單。
// 2026-09-28 使用者回饋「跟下方待核准區塊整合成一個區塊」— 不再自己包一層
// rounded-xl 卡片，改由 RightPanel 把這個元件跟 DiffListMessage 包進同一張卡
// （見 RightPanel.tsx），這裡只回傳卡片內容本身。
// plimsoll-two-shell-spec.md §3 #14 — only the top row's presentation
// diverges (SHELL_CONFIG.overviewPresentation); the four tag-buttons and
// risk bar are shared, both shells filter the same way.
export function OverviewMessage({
  session,
  shell,
  filter,
  onFilterChange,
}: OverviewMessageProps) {
  const total = session.differences.length;
  const high = session.differences.filter((d) => d.ai_risk === 'High').length;
  const medium = session.differences.filter((d) => d.ai_risk === 'Medium').length;
  const low = session.differences.filter((d) => d.ai_risk === 'Low').length;

  const unreviewedHigh = countUnreviewedHigh(session.differences, session.review_state);

  const riskCounts: Record<RiskFilter, number> = { All: total, High: high, Medium: medium, Low: low };

  const showSentence = SHELL_CONFIG[shell].overviewPresentation === 'sentence';

  return (
    <>
      {showSentence && (
        <p className="mb-2.5 text-[14px] text-ink-800">
          {total} 筆差異，{high} 筆 High，還有 {unreviewedHigh} 筆 High 沒人看過
        </p>
      )}

      {/* 1×4 when all four fit on one line, 2×2 when they don't — decided
          by the labels' real width, not a guessed breakpoint (text is fixed
          px, padding scales with the font preset, counts vary per session).
          Each pair wraps as a unit, so it never lands on a 3+1 with an
          orphaned tile; inside a pair the tiles never shrink below their
          nowrap content, so 「Medium 0」 is never clipped. */}
      <div className="flex flex-wrap gap-1.5">
        {RISK_FILTER_PAIRS.map((pair) => (
          <div key={pair[0]} className="flex flex-auto gap-1.5">
            {pair.map((f) => (
              <RiskTagButton key={f} filter={f} active={filter === f} value={riskCounts[f]} onClick={() => onFilterChange(f)} />
            ))}
          </div>
        ))}
      </div>

      {total > 0 && (
        <div className="mt-3 flex h-2 overflow-hidden rounded-full">
          <div className="bg-high-fill" style={{ width: `${(high / total) * 100}%` }} title={`High ${high}`} />
          <div className="bg-med-fill" style={{ width: `${(medium / total) * 100}%` }} title={`Medium ${medium}`} />
          <div className="bg-low-fill" style={{ width: `${(low / total) * 100}%` }} title={`Low ${low}`} />
        </div>
      )}
    </>
  );
}
