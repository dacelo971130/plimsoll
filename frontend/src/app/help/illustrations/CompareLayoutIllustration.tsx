import { Callout, Figure, MockButton, MockChip, MockRiskTile, MockTab } from './shared';

// 圖 b — 比對結果版面：頂端列、中間比對區（切換＋翻頁）、右欄（新的比對／
// 匯出、覆核人身分、風險篩選、待核准清單）。對照 TopBar.tsx / CenterStage.tsx
// / RightPanel.tsx。刻意壓縮高度——這張圖用在「三步上手」的三欄並排版位，
// 欄寬有限，且不需要重現每個細節，只需要讓讀者對上畫面的四個區塊。
export function CompareLayoutIllustration() {
  return (
    <Figure
      caption={[
        <>頂端：目前版本、形象網站、使用說明、設定齒輪。</>,
        <>中間：文字比對／原始 PDF 切換，用 ‹ › 翻頁。</>,
        <>右欄上方：開始新的比對、匯出審查報告；填一次覆核人身分。</>,
        <>右欄下方：風險篩選與待核准清單。</>,
      ]}
    >
      <div className="space-y-1.5">
        {/* pr-12 reserves room so the top bar's right-aligned text never
            sits under the Figure's absolutely-positioned 「示意圖」tag. */}
        <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-line bg-surface py-1 pl-1.5 pr-12">
          <Callout n={1} />
          <MockChip>v1.0 → v1.1</MockChip>
          <span className="ml-auto text-ink-500">形象網站　使用說明 ⚙</span>
        </div>

        <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-line bg-surface px-1.5 py-1">
          <Callout n={2} />
          <MockTab active>文字比對</MockTab>
          <MockTab>原始 PDF</MockTab>
          <span className="ml-auto text-ink-400">‹ p.3 ›</span>
        </div>

        <div className="space-y-1 rounded-md border border-line bg-surface-2 p-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <Callout n={3} />
            <MockButton>＋ 開始新的比對</MockButton>
            {/* The real button (RightPanel.tsx) stays unlit — outlined, with a
                red count badge — until every High is 已確認, and the example
                state here has 2 unsigned High (the tiles below). */}
            <MockButton>
              匯出審查報告 →
              <span className="rounded-full bg-high-fill px-1.5 text-[10px] font-semibold leading-[16px] text-high-on-fill">2</span>
            </MockButton>
          </div>
          <div className="flex items-center gap-1.5">
            <MockChip>覆核人身分</MockChip>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Callout n={4} />
            <MockRiskTile label="全部" value={12} risk="All" />
            <MockRiskTile label="High" value={2} risk="High" />
            <span className="ml-auto font-medium text-ink-800">待核准清單</span>
          </div>
        </div>
      </div>
    </Figure>
  );
}
