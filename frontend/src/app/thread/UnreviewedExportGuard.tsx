import { useState } from 'react';
import type { ExportGuardInfo } from '../../types';

interface UnreviewedExportGuardProps {
  info: ExportGuardInfo;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

// ui-spec §7 情境四 Human Control — "未覆核的 High 在點匯出時必跳二次確認並
// 逐項列出"。清單直接來自伺服器 428 回應（見 backend/api/sessions.py），不是
// 前端自己算的，避免前後端對「還有哪幾筆未覆核」各執一詞。
export function UnreviewedExportGuard({ info, busy, onCancel, onConfirm }: UnreviewedExportGuardProps) {
  const [acknowledged, setAcknowledged] = useState(false);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onCancel}>
      <div
        role="dialog"
        aria-label="未覆核 High 風險變更"
        onClick={(e) => e.stopPropagation()}
        className="w-[420px] rounded-xl border border-line bg-surface p-4 shadow-[var(--sh-3)]"
      >
        <h3 className="text-[14px] font-semibold text-high-700">仍有重大安全變更未完成人工覆核</h3>
        <p className="mt-1.5 text-[12.5px] text-ink-600">
          下列 {info.unreviewed_high.length} 項 High 風險變更尚未判定為「已確認」。若繼續匯出，報告會標註為
          「修訂草稿」並在封面加註警示。
        </p>

        <ul className="mt-2.5 max-h-[160px] space-y-1.5 overflow-y-auto rounded-md border border-line bg-surface-2 p-2">
          {info.unreviewed_high.map((d) => (
            <li key={d.id} className="text-[12px] text-ink-700">
              <span className="font-mono font-medium">{d.id}</span> · {d.explanation}
            </li>
          ))}
        </ul>

        <label className="mt-3 flex items-start gap-2 text-[12.5px] text-ink-700">
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(e) => setAcknowledged(e.target.checked)}
            className="mt-0.5"
          />
          <span>我已知悉此報告將標為「修訂草稿」，並由本人承擔簽核責任。</span>
        </label>

        <div className="mt-3 flex gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="flex-1 rounded-md border border-line py-1.5 text-[12.5px] text-ink-600 hover:bg-accent-soft"
          >
            取消
          </button>
          <button
            type="button"
            disabled={!acknowledged || busy}
            onClick={onConfirm}
            title={!acknowledged ? '需先勾選上方確認項才可匯出' : undefined}
            className="flex-1 rounded-md border border-high-200 py-1.5 text-[12.5px] font-medium text-high-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? '匯出中…' : '仍要匯出為修訂草稿'}
          </button>
        </div>
      </div>
    </div>
  );
}
