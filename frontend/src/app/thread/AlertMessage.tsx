import type { ReactNode } from 'react';

type AlertVariant = 'scanned';

const VARIANT_STYLE: Record<AlertVariant, string> = {
  scanned: 'border-med-200 bg-med-50 text-med-700',
};

// ui-spec §3.2 `alert` — 掃描頁警示。plimsoll-subtraction-matrix.html 小win
// #04：未覆核 High 警示原本在這裡、KPI、匯出區、Guard 各講一次，判定只留 KPI
// 那一次（見 OverviewMessage.tsx 的 showSentence／待簽核 High tag）；缺件警
// 示（missing-info）從未真正被任何畫面使用過，一併清掉。
export function AlertMessage({ variant, children }: { variant: AlertVariant; children: ReactNode }) {
  return <div className={`rounded-xl border p-3 text-[13px] ${VARIANT_STYLE[variant]}`}>{children}</div>;
}
