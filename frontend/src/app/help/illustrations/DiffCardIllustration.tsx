import { Callout, Figure, MockButton, MockChip, MockPrimaryButton, MockRiskPill } from './shared';

// 圖 c — 差異卡＋覆核列：風險與類型（含左側色條）、查看＝跳頁＋展開合一、
// 三選一判定、風險改判、送出並前往下一筆。對照 thread/DiffListMessage.tsx /
// thread/ReviewBar.tsx。
// 2026-09-28 使用者回饋「點擊卡片或查看，同時跳轉並展開」— 原本分開的
// 「舊 p.3」「新 p.3」「展開 →」三顆按鈕，合併成一顆「查看 舊 3 → 新 3」；
// 展開後同一顆鈕變成「收合」。卡片左側色條顏色跟 thread/riskStyle.ts 的
// RISK_STRIPE 一致（這裡固定示範 High／紅），兩邊改動時要一起改。
const RISK_STRIPE_HIGH = 'border-l-high-fill';

export function DiffCardIllustration() {
  return (
    <Figure
      caption={[
        <>風險等級與變更類型，一眼看出這筆多重要；卡片左側色條同一套顏色。</>,
        <>點卡片任何地方，或按 查看 舊 3 → 新 3，同時跳到原文並展開（展開後這顆鈕變成 收合）。</>,
        <>選 已確認／需追蹤／不採納 三選一。</>,
        <>覺得風險判斷不對，用 風險改判 改成 High／Medium／Low。</>,
        <>按 確認並前往下一筆，同時送出並換下一筆（Enter 也可以）。</>,
      ]}
    >
      <div className={`space-y-2 rounded-lg border border-l-4 ${RISK_STRIPE_HIGH} border-line bg-surface p-2`}>
        <div className="flex flex-wrap items-center gap-1.5">
          <Callout n={1} />
          <MockRiskPill risk="High" />
          <MockChip>修改</MockChip>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <Callout n={2} />
          <span className="ml-auto">
            <MockButton>
              查看 <span className="font-normal text-ink-500">舊 3 → 新 3</span>
            </MockButton>
          </span>
        </div>

        <div className="space-y-1.5 border-t border-line pt-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <Callout n={3} />
            <MockPrimaryButton>✓ 已確認</MockPrimaryButton>
            <MockButton>◷ 需追蹤</MockButton>
            <MockButton>✕ 不採納</MockButton>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Callout n={4} />
            <span className="text-ink-500">風險改判</span>
            <MockChip>維持 AI 初判（High）</MockChip>
          </div>
          <div className="flex items-center gap-1.5">
            <Callout n={5} />
            <MockPrimaryButton>確認並前往下一筆 → (Enter)</MockPrimaryButton>
          </div>
        </div>
      </div>
    </Figure>
  );
}
