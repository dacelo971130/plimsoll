import type { ReactNode } from 'react';

// 使用說明頁用的小型排版元件。和文字內容（helpContent.tsx）分開放，
// 讓那個檔案只匯出資料，fast refresh 才能正常運作。

// A small non-interactive "label chip" — rounded + bordered like the real
// control it names, so a reader scanning the page recognises the button/tab
// on screen instead of parsing a bold「quoted」label. Never a real control:
// no onClick, no focus ring, no cursor change (see HelpPage 說明文字 rule).
export function Ui({ children }: { children: ReactNode }) {
  return (
    <span className="mx-0.5 inline-flex items-center whitespace-nowrap rounded-md border border-line bg-surface px-1.5 py-0.5 align-middle text-[12.5px] font-medium text-ink-800">
      {children}
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-line bg-surface-2 px-1.5 py-0.5 font-mono text-[12px] text-ink-800">{children}</kbd>
  );
}

export function Note({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-[13px] text-ink-600">{children}</p>;
}

export function Steps({ items }: { items: ReactNode[] }) {
  return (
    <ol className="space-y-2">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2.5">
          <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-ink-800 text-[11px] font-medium text-on-accent">
            {i + 1}
          </span>
          <span>{item}</span>
        </li>
      ))}
    </ol>
  );
}

export function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full border-collapse bg-surface text-[13px]">
        <thead>
          <tr className="bg-surface-2 text-left text-[12px] text-ink-500">
            {head.map((h) => (
              <th key={h} className="px-3 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line-soft">
          {rows.map((row, i) => (
            <tr key={i} className="align-top">
              {row.map((cell, j) => (
                <td key={j} className="px-3 py-2 text-ink-700">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Mark({ className, children }: { className: string; children: ReactNode }) {
  return <span className={`px-0.5 ${className}`}>{children}</span>;
}

// 「三步上手」的一步：編號＋短標題＋最多兩行的極短說明＋一張示意圖。文字刻
// 意壓到最少（細節留給圖下方的編號說明清單），三步並排時才擠得進 1280×800
// 第一屏，不需要捲動。
export function QuickstartStep({
  n,
  title,
  figure,
  children,
}: {
  n: number;
  title: string;
  figure: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col rounded-xl border border-line bg-surface p-3">
      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink-800 text-[12px] font-medium text-on-accent">
          {n}
        </span>
        <h4 className="text-[13.5px] font-semibold text-ink-900">{title}</h4>
      </div>
      <div className="mt-1 space-y-0.5 pl-8 text-[12px] leading-snug text-ink-700">{children}</div>
      <div className="mt-2">{figure}</div>
    </div>
  );
}
