import { Mark } from '../helpBlocks';
import { Callout, Figure } from './shared';

// 圖 f — 文字比對的標示色：新增／刪除／修改。這幾個 class 字串必須跟
// app/CenterStage.tsx 的 MARK_CLASS 完全一致——改那邊時這裡要一起改。
const MARK_CLASS = {
  add: 'rounded border border-low-200 bg-low-50 text-low-700 underline decoration-low-500 decoration-2 underline-offset-2',
  del: 'rounded border border-high-200 bg-high-50 text-high-700 line-through decoration-high-500 decoration-2',
  mod: 'rounded border border-med-200 bg-med-50 text-med-700 underline decoration-med-500 decoration-2 underline-offset-2',
};

export function HighlightLegend() {
  return (
    <Figure
      caption={[
        <>新增文字：綠色加底線。</>,
        <>刪除文字：紅色加刪除線。</>,
        <>修改文字：橙色加底線。</>,
      ]}
    >
      <div className="flex flex-wrap gap-3">
        <span className="inline-flex items-center gap-1.5">
          <Callout n={1} />
          <Mark className={MARK_CLASS.add}>新增文字</Mark>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Callout n={2} />
          <Mark className={MARK_CLASS.del}>刪除文字</Mark>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Callout n={3} />
          <Mark className={MARK_CLASS.mod}>修改文字</Mark>
        </span>
      </div>
    </Figure>
  );
}
