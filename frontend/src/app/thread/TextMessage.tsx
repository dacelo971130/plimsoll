import type { ReactNode } from 'react';

// ui-spec §3.2 `text` — 一般 agent／使用者訊息。P2 只有 agent 側（Composer
// 尚未能送出使用者訊息，見 §30 RAG Someday）。
export function TextMessage({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4 text-[13.5px] text-ink-700 shadow-[var(--sh-1)]">
      {children}
    </div>
  );
}
