import { ChevronDown, ChevronUp, Upload, X } from 'lucide-react';
import type { ChainStatus } from '../../state/useChain';

interface ChainUploadPanelProps {
  files: File[];
  onAddFiles: (files: File[]) => void;
  onRemoveFile: (index: number) => void;
  onMoveFile: (index: number, direction: -1 | 1) => void;
  onUpload: () => void;
  status: ChainStatus;
  error: string | null;
}

// W5/W6/W8's chain coordinator (backend/services/chain.py, POST /api/chains)
// only ever had a demo entry point in the UI before this — this is the real
// upload flow: pick N PDFs (any order via the browser's file picker), then
// reorder/remove with the ▲▼✕ controls before submitting, since a chain
// never guesses version order (same "never guess" rule as a pairwise
// session's version field).
export function ChainUploadPanel({ files, onAddFiles, onRemoveFile, onMoveFile, onUpload, status, error }: ChainUploadPanelProps) {
  return (
    <div className="rounded-lg border border-dashed border-line p-3">
      <div className="mb-2 text-[12.5px] font-medium text-ink-700">上傳多版本做鏈式分析（依版本順序，v1 在前）</div>

      <label className="flex cursor-pointer items-center justify-center gap-2 rounded-md border border-line bg-surface-2 py-2 text-[12.5px] text-ink-600 hover:bg-accent-soft">
        <Upload size={14} />
        選擇 PDF 檔案（可一次選多個，或分次加入）
        <input
          type="file"
          accept="application/pdf"
          multiple
          className="hidden"
          onChange={(e) => {
            // Copy out of the live FileList *before* resetting .value — the
            // FileList is a live view onto the input, so resetting .value
            // to allow re-selecting the same file empties it too, and
            // React's setState batching means the updater below can run
            // after that reset if we pass the FileList itself instead of a
            // plain array snapshot.
            const selected = e.target.files ? Array.from(e.target.files) : [];
            e.target.value = '';
            if (selected.length > 0) onAddFiles(selected);
          }}
        />
      </label>

      {files.length > 0 && (
        <ol className="mt-2 space-y-1">
          {files.map((f, i) => (
            <li
              key={`${f.name}-${i}`}
              className="flex items-center gap-2 rounded-md border border-line bg-surface px-2 py-1 text-[12px] text-ink-700"
            >
              <span className="w-6 shrink-0 text-center font-mono text-ink-400">v{i + 1}</span>
              <span className="min-w-0 flex-1 truncate">{f.name}</span>
              <button
                type="button"
                title="上移"
                onClick={() => onMoveFile(i, -1)}
                disabled={i === 0}
                className="text-ink-400 hover:text-ink-800 disabled:opacity-30"
              >
                <ChevronUp size={13} />
              </button>
              <button
                type="button"
                title="下移"
                onClick={() => onMoveFile(i, 1)}
                disabled={i === files.length - 1}
                className="text-ink-400 hover:text-ink-800 disabled:opacity-30"
              >
                <ChevronDown size={13} />
              </button>
              <button type="button" title="移除" onClick={() => onRemoveFile(i)} className="text-ink-400 hover:text-high-700">
                <X size={13} />
              </button>
            </li>
          ))}
        </ol>
      )}

      {error && (
        <p className="mt-2 rounded-md border border-high-200 bg-high-50 px-2.5 py-1.5 text-[12px] text-high-700">
          鏈式比對失敗：{error}
        </p>
      )}

      <button
        type="button"
        onClick={onUpload}
        disabled={files.length < 2 || status === 'busy'}
        className="mt-2 w-full rounded-md bg-ink-800 py-1.5 text-[12.5px] font-medium text-on-accent disabled:cursor-not-allowed disabled:opacity-40"
      >
        {status === 'busy' ? '建立鏈式比對中…' : `建立鏈式比對（${files.length} 個版本）`}
      </button>
      {files.length === 1 && <p className="mt-1 text-[11px] text-ink-500">至少需要 2 個版本才能建立鏈式比對。</p>}
    </div>
  );
}
