import { useState } from 'react';
import { acknowledgeQuarantine, quarantinedEventsUrl } from '../../lib/api';
import { StatusDot } from '../StatusDot';
import type { DataSourceStatus } from '../../types';

interface DataSourceTabProps {
  status: DataSourceStatus;
  onStatusChange: (status: DataSourceStatus) => void;
}

const STATUS_LABEL: Record<DataSourceStatus['status'], string> = {
  connected: '已連線',
  disconnected: '未連線 · 資料僅存本機',
  connecting: '連線中…',
  error: '連線失敗',
};

// ui-spec §3.4 ④ + architecture-decisions-A-B.md §24 — 資料庫同步狀態與完整性
// 告警。減法矩陣「不做假的」：後端目前只有 NullSyncTarget（永遠未連線），所以
// 「立即同步到資料庫」與「連線設定／測試連線」兩組永遠按不下去的控制整段拿
// 掉，DB adapter 真的接上時再一起回來；本機／雲端資料夾來源的「本輪不做」說明
// 也一併拿掉。完整性告警的兩顆按鈕則接上後端（/api/system/quarantine/…）。
export function DataSourceTab({ status, onStatusChange }: DataSourceTabProps) {
  const quarantined = status.quarantined_sessions;
  const [acknowledging, setAcknowledging] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleAcknowledge(sessionId: string) {
    setAcknowledging(sessionId);
    setError(null);
    try {
      onStatusChange(await acknowledgeQuarantine(sessionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAcknowledging(null);
    }
  }

  return (
    <div className="space-y-5">
      <section>
        <div className="mb-1.5 text-[12.5px] font-medium text-ink-700">資料庫同步</div>
        <div className="flex items-center gap-2 rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px] text-ink-700">
          <StatusDot status={status.status} />
          <span>{STATUS_LABEL[status.status]}</span>
          {status.pending_count > 0 && <span className="ml-auto text-ink-500">本機 {status.pending_count} 筆待同步</span>}
        </div>
        <p className="mt-1.5 text-[11.5px] text-ink-500">
          比對、覆核與匯出都不需要資料庫：所有資料存在執行 Plimsoll 的這台電腦上，資料庫只是可選的備份鏡像。未連線時一切照常運作。
        </p>
      </section>

      {quarantined.length > 0 && (
        <section className="rounded-md border border-high-200 bg-high-50 p-3">
          <div className="text-[12.5px] font-medium text-high-700">完整性告警</div>
          <ul className="mt-1.5 space-y-2">
            {quarantined.map((q) => (
              <li key={q.session_id} className="text-[12px] text-ink-700">
                <p>
                  <strong className="text-high-700">
                    {q.session_id}
                  </strong>{' '}
                  因完整性驗證失敗已略過同步——{q.reason ?? '稽核日誌前綴雜湊比對不符，可能遭手動修改'}
                  ，系統已隔離、原始日誌照原樣保留於本機作為證據。
                </p>
                <div className="mt-1.5 flex gap-2">
                  <a
                    href={quarantinedEventsUrl(q.session_id)}
                    download
                    className="rounded-md border border-line bg-surface px-2 py-1 text-[11.5px] text-ink-700 hover:bg-accent-soft"
                  >
                    下載原始稽核日誌（.jsonl）
                  </a>
                  <button
                    type="button"
                    onClick={() => handleAcknowledge(q.session_id)}
                    disabled={acknowledging !== null}
                    className="rounded-md border border-line bg-surface px-2 py-1 text-[11.5px] text-ink-600 hover:bg-accent-soft disabled:opacity-50"
                  >
                    {acknowledging === q.session_id ? '處理中…' : '標記為已知悉並結案'}
                  </button>
                </div>
              </li>
            ))}
          </ul>
          {error && <p className="mt-2 text-[11.5px] text-high-700">{error}</p>}
          <p className="mt-2 text-[11px] text-ink-500">
            系統不會自動修復或覆寫此日誌；「已知悉並結案」只影響告警顯示，不影響本機原始檔案。
          </p>
        </section>
      )}
    </div>
  );
}
