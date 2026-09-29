import { Callout, Figure, MockButton } from './shared';

// 圖 e — 兩種操作模式對照：清單總覽模式（全部差異都在清單裡）vs 逐步引導
// 模式（一次一筆＋上一筆／下一筆）。對照 DiffListMessage.tsx 的
// SHELL_CONFIG.reviewMode 分支（'list' vs 'stepper'）。
export function ShellModesIllustration() {
  return (
    <Figure
      caption={[
        <>清單總覽模式：所有差異一次列出，適合鍵盤快速判定。</>,
        <>逐步引導模式：一次只看一筆，顯示「第 N／M 筆」。</>,
        <>逐步引導模式用 ← 上一筆／下一筆 → 換筆，沒判定也能換。</>,
      ]}
    >
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="flex-1 space-y-1">
          <div className="flex items-center gap-1.5 font-medium text-ink-800">
            <Callout n={1} />
            <span>清單總覽模式</span>
          </div>
          <div className="space-y-1">
            <div className="rounded border border-line bg-surface p-1.5 text-ink-600">差異 1</div>
            <div className="rounded border border-ink-800 bg-surface p-1.5 text-ink-600">差異 2（展開）</div>
            <div className="rounded border border-line bg-surface p-1.5 text-ink-600">差異 3</div>
          </div>
        </div>

        <div className="flex-1 space-y-1">
          <div className="flex items-center gap-1.5 font-medium text-ink-800">
            <Callout n={2} />
            <span>逐步引導模式</span>
          </div>
          <div className="space-y-1">
            <div className="text-ink-500">第 2／5 筆</div>
            <div className="rounded border border-ink-800 bg-surface p-1.5 text-ink-600">差異 2</div>
            <div className="flex items-center gap-1.5">
              <Callout n={3} />
              <MockButton>← 上一筆</MockButton>
              <MockButton>下一筆 →</MockButton>
            </div>
          </div>
        </div>
      </div>
    </Figure>
  );
}
