import type { DocMetadata } from '../../types';

interface DocInfoMessageProps {
  oldMeta: DocMetadata;
  newMeta: DocMetadata;
  oldFilename: string;
  newFilename: string;
}

function DocColumn({ label, filename, meta }: { label: string; filename: string; meta: DocMetadata }) {
  return (
    <div className="min-w-0 flex-1">
      <div className="text-[11px] font-medium uppercase tracking-wide text-ink-500">{label}</div>
      <div className="truncate text-[12.5px] font-medium text-ink-900">{meta.title ?? filename}</div>
      <div className="mt-1 text-[12px] text-ink-600">
        {meta.version ?? '版本未知'} · {meta.date ?? '日期未知'} · {meta.page_count} 頁
      </div>
    </div>
  );
}

// ui-spec §3.2 `doc-info` — "文件資訊卡（兩份文件的標題、版本、日期、頁數、文字層
// 品質）"。與右欄 FileCard 同一份資料的對話式重述，AC1 的一部分證據。
export function DocInfoMessage({ oldMeta, newMeta, oldFilename, newFilename }: DocInfoMessageProps) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4 shadow-[var(--sh-1)]">
      <div className="flex gap-4">
        <DocColumn label="舊版" filename={oldFilename} meta={oldMeta} />
        <DocColumn label="新版" filename={newFilename} meta={newMeta} />
      </div>
    </div>
  );
}
