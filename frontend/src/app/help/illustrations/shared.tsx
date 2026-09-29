import type { ReactNode } from 'react';

// 使用說明「圖文示範」共用零件。規則：
//  - 只用既有 design tokens（bg-surface / bg-surface-2 / bg-canvas /
//    border-line / text-ink-* / risk 色階…），不加新顏色、不寫死 hex。
//  - 示意圖本身永遠是非互動的（沒有 button/a/input，pointer-events-none），
//    並且對輔助科技隱藏（aria-hidden） —— 真正的說明文字在 <figcaption> 裡的
//    編號清單，兩邊的編號用同一套圓圈數字對齊。
//  - 這個檔案只匯出元件，符合 react/only-export-components。

const CIRCLED_DIGITS = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩'];

// 圖上的編號標記。永遠 aria-hidden：出現在示意圖裡時，整張圖已經被隱藏；
// 出現在下方清單裡時，<ol> 本身已經提供編號語意，這裡純粹是視覺對齊。
export function Callout({ n }: { n: number }) {
  return (
    <span aria-hidden="true" className="shrink-0 font-semibold leading-none text-ink-800">
      {CIRCLED_DIGITS[n - 1] ?? `(${n})`}
    </span>
  );
}

// 圖旁／下方的編號說明清單，用跟 Callout 一樣的圈數字，讀者能一一對應。
export function CaptionList({ items }: { items: ReactNode[] }) {
  return (
    <ol className="space-y-1.5">
      {items.map((item, i) => (
        <li key={i} className="flex gap-1.5 text-[12px] leading-relaxed text-ink-700">
          <Callout n={i + 1} />
          <span>{item}</span>
        </li>
      ))}
    </ol>
  );
}

// 示意圖外框：<figure> + 隱藏的 mockup + 「示意圖」標籤 + 真正承載語意的
// <figcaption>（編號清單）。mockup 本身用 aria-hidden 隱藏，避免螢幕報讀器
// 唸出一堆假按鈕的文字——它們不能被按、也不代表真的畫面狀態。
export function Figure({ children, caption }: { children: ReactNode; caption: ReactNode[] }) {
  return (
    <figure className="my-2">
      <div className="relative">
        <div
          aria-hidden="true"
          className="pointer-events-none select-none overflow-hidden rounded-lg border border-line bg-canvas p-2.5 sm:p-3"
        >
          <div className="text-[10.5px] leading-tight text-ink-700 sm:text-[11px]">{children}</div>
        </div>
        <span
          aria-hidden="true"
          className="absolute right-2 top-2 rounded-full border border-line bg-surface px-1.5 py-0.5 text-[10px] text-ink-500"
        >
          示意圖
        </span>
      </div>
      <figcaption className="mt-2">
        <CaptionList items={caption} />
      </figcaption>
    </figure>
  );
}

// mockup 內部零件——全部是 span/div，不是真的 button/input，避免看起來像可
// 以互動的介面（減法矩陣「不做假的」）。
export function MockPrimaryButton({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-md bg-ink-800 px-2 py-1 font-medium text-on-accent">
      {children}
    </span>
  );
}

export function MockButton({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-line bg-surface px-2 py-1 text-ink-700">
      {children}
    </span>
  );
}

export function MockTab({ children, active = false }: { children: ReactNode; active?: boolean }) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-md px-2 py-1 ${
        active ? 'bg-ink-800 font-medium text-on-accent' : 'border border-line text-ink-600'
      }`}
    >
      {children}
    </span>
  );
}

export function MockChip({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center whitespace-nowrap rounded-full border border-line bg-surface-2 px-2 py-0.5 text-ink-600">
      {children}
    </span>
  );
}

const RISK_IDLE: Record<'All' | 'High' | 'Medium' | 'Low', string> = {
  All: 'border-line bg-surface-2 text-ink-700',
  High: 'border-high-fill/60 bg-high-fill/10 text-high-700',
  Medium: 'border-med-fill/70 bg-med-fill/15 text-med-700',
  Low: 'border-low-fill/60 bg-low-fill/10 text-low-700',
};

// 風險篩選 tile（未按下狀態）——顏色沿用 OverviewMessage 的 TILE_STYLE.idle，
// 兩邊改動時要一起改。
export function MockRiskTile({ label, value, risk }: { label: string; value: number; risk: 'All' | 'High' | 'Medium' | 'Low' }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg border px-2 py-1 ${RISK_IDLE[risk]}`}>
      <span className="font-medium">{label}</span>
      <span className="font-semibold tabular-nums">{value}</span>
    </span>
  );
}

const RISK_FILL: Record<'High' | 'Medium' | 'Low', string> = {
  High: 'bg-high-fill text-high-on-fill',
  Medium: 'bg-med-fill text-med-on-fill',
  Low: 'bg-low-fill text-low-on-fill',
};

// 差異卡上的風險等級實心圓標——顏色沿用 thread/riskStyle.ts 的 RISK_FILL，
// 兩邊改動時要一起改。
export function MockRiskPill({ risk }: { risk: 'High' | 'Medium' | 'Low' }) {
  return <span className={`rounded-full px-1.5 py-0.5 text-[11px] font-semibold ${RISK_FILL[risk]}`}>{risk}</span>;
}
