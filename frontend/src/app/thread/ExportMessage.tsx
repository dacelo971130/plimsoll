import { useState } from 'react';
import { X } from 'lucide-react';
import { exportSession } from '../../lib/api';
import { hasReviewerIdentity } from '../../state/useReviewerIdentity';
import type { ExportFormat, ExportGuardInfo } from '../../types';
import { IdentityHint } from '../IdentityHint';
import { UnreviewedExportGuard } from './UnreviewedExportGuard';

interface ExportMessageProps {
  sessionId: string;
  reviewerName: string;
  approvalRoleCode: string;
  // 2026-09-15 redesign — now always opened from a modal (the 總差異 card's
  // 「匯出審查報告」button), so it always needs its own way to close.
  onClose: () => void;
  onGoToIdentity: () => void;
  // 2026-09-28 使用者回饋 — lets RightPanel know a REAL (non-guarded) export
  // completed, so its 開始新的比對 confirm-guard can skip itself next time.
  // Optional: nothing outside RightPanel needs this today.
  onExported?: () => void;
}

const FORMAT_LABEL: Record<ExportFormat, string> = { pdf: 'PDF', html: 'HTML', docx: 'Word (.docx)' };
const OTHER_FORMATS: ExportFormat[] = ['html', 'docx'];

// ui-spec §3.2 `export` — "簽核資訊表單 + 匯出格式"；B1/B6 回歸（HTML 下載、
// DOCX 帶簽核資訊）。未覆核 High 的二次確認交給 UnreviewedExportGuard。
// plimsoll-subtraction-matrix.html 小win #11 — 三個並列格式按鈕讓一個簽核動
// 作看起來像檔案轉換工具；改成一顆「匯出 PDF」主按鈕＋「其他格式」小選單，
// 報告編號／部門收進「更多」，預設不顯示。
export function ExportMessage({
  sessionId,
  reviewerName,
  approvalRoleCode,
  onClose,
  onGoToIdentity,
  onExported,
}: ExportMessageProps) {
  const [format, setFormat] = useState<ExportFormat>('pdf');
  const [showOtherFormats, setShowOtherFormats] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const [reportNo, setReportNo] = useState('');
  const [dept, setDept] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [guardInfo, setGuardInfo] = useState<ExportGuardInfo | null>(null);
  const [downloaded, setDownloaded] = useState<string | null>(null);

  async function runExport(acknowledgeDraft: boolean) {
    setBusy(true);
    setError(null);
    try {
      const result = await exportSession(sessionId, {
        format,
        reviewer_name: reviewerName,
        approval_role_code: approvalRoleCode,
        report_no: reportNo,
        dept,
        acknowledge_draft: acknowledgeDraft,
      });
      if (result.status === 'guard') {
        setGuardInfo(result.info);
      } else {
        setGuardInfo(null);
        setDownloaded(result.filename);
        onExported?.();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const canExport = hasReviewerIdentity(reviewerName, approvalRoleCode) && !busy;

  return (
    <div className="rounded-xl border border-line bg-surface p-4 shadow-[var(--sh-3)]">
      <div className="flex items-center justify-between">
        <h3 className="text-[13.5px] font-semibold text-ink-900">匯出審查報告</h3>
        <button type="button" onClick={onClose} className="rounded-md p-1 text-ink-500 hover:bg-accent-soft">
          <X size={16} />
        </button>
      </div>

      {showMore ? (
        <div className="mt-2 grid grid-cols-2 gap-2">
          <input
            value={reportNo}
            onChange={(e) => setReportNo(e.target.value)}
            placeholder="報告編號（選填）"
            className="rounded-md border border-line bg-surface-2 px-2 py-1 text-[12px] text-ink-800"
          />
          <input
            value={dept}
            onChange={(e) => setDept(e.target.value)}
            placeholder="部門（選填）"
            className="rounded-md border border-line bg-surface-2 px-2 py-1 text-[12px] text-ink-800"
          />
        </div>
      ) : (
        <button type="button" onClick={() => setShowMore(true)} className="mt-1.5 text-[11.5px] text-ink-500 hover:text-ink-700">
          ＋ 更多（報告編號／部門）
        </button>
      )}

      {!canExport && !busy && (
        <IdentityHint onGo={onGoToIdentity} className="mt-2 text-[11.5px]" />
      )}
      {error && (
        <p className="mt-2 rounded-md border border-high-200 bg-high-50 px-2.5 py-1.5 text-[12px] text-high-700">{error}</p>
      )}
      {downloaded && (
        <p className="mt-2 rounded-md border border-low-200 bg-low-50 px-2.5 py-1.5 text-[12px] text-low-700">
          已下載 {downloaded}
        </p>
      )}

      <button
        type="button"
        disabled={!canExport}
        onClick={() => runExport(false)}
        className="mt-2.5 w-full rounded-md bg-ink-800 py-1.5 text-[12.5px] font-medium text-on-accent disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? '匯出中…' : `匯出 ${FORMAT_LABEL[format]}`}
      </button>

      {showOtherFormats ? (
        <div className="mt-1.5 flex items-center gap-1.5 text-[11.5px] text-ink-500">
          <span>改用：</span>
          {(['pdf', ...OTHER_FORMATS] as ExportFormat[]).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => {
                setFormat(f);
                setShowOtherFormats(false);
              }}
              className={`rounded px-1.5 py-0.5 ${format === f ? 'bg-accent-soft text-ink-800' : 'hover:text-ink-700'}`}
            >
              {FORMAT_LABEL[f]}
            </button>
          ))}
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setShowOtherFormats(true)}
          className="mt-1.5 text-[11.5px] text-ink-500 hover:text-ink-700"
        >
          其他格式（{OTHER_FORMATS.map((f) => FORMAT_LABEL[f]).join('／')}）
        </button>
      )}

      {guardInfo && (
        <UnreviewedExportGuard
          info={guardInfo}
          busy={busy}
          onCancel={() => setGuardInfo(null)}
          onConfirm={() => runExport(true)}
        />
      )}
    </div>
  );
}
