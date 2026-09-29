import { X } from 'lucide-react';
import type { DocMetadata } from '../../types';

interface FileCardProps {
  label: string;
  fileName: string;
  clientSizeBytes: number | null;
  meta: DocMetadata | null;
  scannedPages: number[];
  onRemove?: () => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

// ui-spec §3.3 — "已載入：FileCard — 檔名、來源 tag、頁數（實際值）、大小、
// 文字層品質、版本、日期、移除鈕"。來源 tag 固定「本機」：P1 上傳走瀏覽器直傳，
// 無 Drive/資料夾串接（已依決議整條移除）。
export function FileCard({ label, fileName, clientSizeBytes, meta, scannedPages, onRemove }: FileCardProps) {
  const sizeBytes = meta?.size_bytes ?? clientSizeBytes ?? 0;
  const pageCount = meta?.page_count;
  const textQuality = meta ? (scannedPages.length > 0 ? `${scannedPages.length} 頁疑似掃描` : '文字層良好') : '解析中…';

  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[11.5px] font-medium uppercase tracking-wide text-ink-500">{label}</div>
          <div className="truncate text-[13px] font-medium text-ink-900">{fileName}</div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <span className="rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[11px] text-ink-600">本機</span>
          {onRemove && (
            <button type="button" onClick={onRemove} title="移除" className="rounded-md p-1 text-ink-400 hover:bg-accent-soft">
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      {meta && (
        <div className="mt-2 text-[12px] text-ink-600">
          <div>
            <span className="text-ink-400">名稱：</span>
            {meta.title ?? <span className="text-med-700">未偵測到</span>}
          </div>
          <div>
            <span className="text-ink-400">適用設備：</span>
            {meta.applicable_equipment ?? '—'}
          </div>
        </div>
      )}

      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[12px] text-ink-600">
        <div>
          <dt className="inline text-ink-400">頁數：</dt>
          <dd className="inline">{pageCount ?? '—'}</dd>
        </div>
        <div>
          <dt className="inline text-ink-400">大小：</dt>
          <dd className="inline">{formatSize(sizeBytes)}</dd>
        </div>
        <div>
          <dt className="inline text-ink-400">版本：</dt>
          <dd className={`inline ${meta && !meta.version ? 'text-med-700' : ''}`}>
            {meta ? (meta.version ?? '未偵測到') : '—'}
          </dd>
        </div>
        <div>
          <dt className="inline text-ink-400">日期：</dt>
          <dd className={`inline ${meta && !meta.date ? 'text-med-700' : ''}`}>{meta ? (meta.date ?? '未偵測到') : '—'}</dd>
        </div>
        <div className="col-span-2">
          <dt className="inline text-ink-400">文字層：</dt>
          <dd className={`inline ${scannedPages.length > 0 ? 'text-med-700' : ''}`}>{textQuality}</dd>
        </div>
      </dl>

      {scannedPages.length > 0 && (
        <p className="mt-2 rounded-md border border-med-200 bg-med-50 px-2 py-1.5 text-[11.5px] text-med-700">
          第 {scannedPages.join('、')} 頁偵測到掃描頁或文字層不足，建議人工雙重校對以防漏看重大變更。
        </p>
      )}
    </div>
  );
}
