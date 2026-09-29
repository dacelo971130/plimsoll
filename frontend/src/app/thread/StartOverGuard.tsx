import { useState } from 'react';

interface StartOverGuardProps {
  // False for a chain-only screen (no pairwise session) — there is no
  // 匯出審查報告 modal to offer in that case (ChainMessage has its own
  // separate 鏈級簽核, untouched by this guard).
  canExport: boolean;
  onCancel: () => void;
  onExportInstead: () => void;
  onConfirm: (skipNextTime: boolean) => void;
}

// 2026-09-28 使用者回饋 —「開始新的比對要有確認防呆，避免洗掉紀錄」。Visual
// pattern copied from UnreviewedExportGuard.tsx (same backdrop/card/footer
// shape). Only shown when RightPanel decides it's needed — see its own
// hasExportedThisSession/skip logic; this component itself has no opinion on
// when to appear, only on what to do once it has.
export function StartOverGuard({ canExport, onCancel, onExportInstead, onConfirm }: StartOverGuardProps) {
  const [skipNextTime, setSkipNextTime] = useState(false);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onCancel}>
      <div
        role="dialog"
        aria-label="開始新的比對"
        onClick={(e) => e.stopPropagation()}
        className="w-[420px] rounded-xl border border-line bg-surface p-4 shadow-[var(--sh-3)]"
      >
        <h3 className="text-[14px] font-semibold text-ink-900">開始新的比對？</h3>
        <p className="mt-1.5 text-[12.5px] text-ink-600">
          目前這份比對的畫面會被清空——尚未送出的判定草稿、AI 建議結果都會遺失。已送出的覆核紀錄仍保存在伺服器上，不會被刪除{canExport && '；建議先匯出審查報告留存'}。
        </p>

        {canExport && (
          <label className="mt-3 flex items-start gap-2 text-[12.5px] text-ink-700">
            <input
              type="checkbox"
              checked={skipNextTime}
              onChange={(e) => setSkipNextTime(e.target.checked)}
              className="mt-0.5"
            />
            <span>已匯出過的比對不再詢問</span>
          </label>
        )}

        <div className="mt-3 flex flex-col gap-1.5">
          {canExport && (
            <button
              type="button"
              onClick={onExportInstead}
              className="w-full rounded-md bg-ink-800 py-1.5 text-[12.5px] font-medium text-on-accent hover:opacity-90"
            >
              先匯出審查報告
            </button>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onCancel}
              className="flex-1 rounded-md border border-line py-1.5 text-[12.5px] text-ink-600 hover:bg-accent-soft"
            >
              取消
            </button>
            <button
              type="button"
              onClick={() => onConfirm(skipNextTime)}
              className="flex-1 rounded-md border border-high-200 py-1.5 text-[12.5px] font-medium text-high-700 hover:bg-high-50"
            >
              仍要開始新的比對
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
