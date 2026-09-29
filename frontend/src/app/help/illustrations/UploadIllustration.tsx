import { Callout, Figure, MockButton, MockPrimaryButton, MockTab } from './shared';

// 圖 a — 首頁上傳畫面：兩個分頁入口、舊版／新版拖放框、開始比對／示範資料。
// 對照 frontend/src/app/source/SourceTab.tsx。
export function UploadIllustration() {
  return (
    <Figure
      caption={[
        <>先選 <b className="font-medium text-ink-900">雙文件比對</b> 或 <b className="font-medium text-ink-900">鏈式分析比對</b>。</>,
        <>把舊版、新版 PDF 分別拖進對應的框。</>,
        <>按下開始比對。</>,
        <>第一次用可以先按示範資料，不用自己找檔案。</>,
      ]}
    >
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <Callout n={1} />
          <MockTab active>雙文件比對</MockTab>
          <MockTab>鏈式分析比對</MockTab>
        </div>

        <div className="flex flex-wrap gap-2">
          <div className="flex min-w-[110px] flex-1 items-start gap-1.5 rounded-lg border border-dashed border-line bg-surface p-2">
            <Callout n={2} />
            <div className="min-w-0">
              <div className="font-medium text-ink-800">舊版文件</div>
              <div className="mt-0.5 text-ink-400">拖曳 PDF 到這裡</div>
            </div>
          </div>
          <div className="min-w-[110px] flex-1 rounded-lg border border-dashed border-line bg-surface p-2">
            <div className="font-medium text-ink-800">新版文件</div>
            <div className="mt-0.5 text-ink-400">拖曳 PDF 到這裡</div>
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5">
          <span className="inline-flex items-center gap-1">
            <Callout n={3} />
            <MockPrimaryButton>開始版本差異比對</MockPrimaryButton>
          </span>
          <span className="inline-flex items-center gap-1">
            <Callout n={4} />
            <MockButton>載入示範資料（6 頁合成文件）</MockButton>
          </span>
        </div>
      </div>
    </Figure>
  );
}
