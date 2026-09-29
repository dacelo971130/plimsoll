import { Callout, Figure, MockButton, MockChip, MockPrimaryButton } from './shared';

// 圖 d — 匯出流程：按下匯出後，還有 High 沒確認時跳出的二次確認。對照
// thread/ExportMessage.tsx / thread/UnreviewedExportGuard.tsx。
export function ExportGuardIllustration() {
  return (
    <Figure
      caption={[
        <>按 匯出審查報告 →。</>,
        <>還有 High 沒標「已確認」時，跳出警示並逐筆列出。</>,
        <>勾選「已知悉」才能繼續。</>,
        <>按 仍要匯出為修訂草稿 才會送出。</>,
        <>報告封面會標記為「修訂草稿」。</>,
      ]}
    >
      <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-center">
        <span className="inline-flex items-center gap-1">
          <Callout n={1} />
          <MockPrimaryButton>匯出審查報告 →</MockPrimaryButton>
        </span>
        <span aria-hidden="true" className="text-ink-400 sm:mx-1">
          →
        </span>
        <div className="w-full space-y-1.5 rounded-lg border border-high-200 bg-high-50 p-2 text-high-700 sm:w-auto">
          <div className="flex items-center gap-1.5 font-medium">
            <Callout n={2} />
            <span>仍有重大安全變更未完成人工覆核</span>
          </div>
          <div className="flex items-center gap-1.5 text-ink-700">
            <Callout n={3} />
            <span aria-hidden="true" className="h-3 w-3 rounded-sm border border-line bg-surface" />
            <span>我已知悉此報告將標為「修訂草稿」</span>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Callout n={4} />
            <MockButton>取消</MockButton>
            <span className="inline-flex items-center rounded-md border border-high-200 px-2 py-1 font-medium text-high-700">
              仍要匯出為修訂草稿
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <Callout n={5} />
            <MockChip>修訂草稿</MockChip>
          </div>
        </div>
      </div>
    </Figure>
  );
}
