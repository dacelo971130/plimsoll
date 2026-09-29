import { useEffect, useState } from 'react';
import { getDemoFixtures, type DemoFixture } from '../../lib/api';
import type { ChainStatus } from '../../state/useChain';
import { useFocusHints } from '../../state/useFocusHints';
import type { UploadStatus, VersionOverrideFields } from '../../state/useSession';
import type { DocMetadata, SessionInspection, SessionSummary } from '../../types';
import { FocusHint } from '../FocusHint';
import { ChainUploadPanel } from './ChainUploadPanel';
import { Dropzone } from './Dropzone';
import { FileCard } from './FileCard';
import { MissingVersionField } from './MissingVersionField';

interface SourceTabProps {
  oldFile: File | null;
  newFile: File | null;
  setOldFile: (f: File) => void;
  setNewFile: (f: File) => void;
  overrides: VersionOverrideFields;
  updateOverride: <K extends keyof VersionOverrideFields>(key: K, value: VersionOverrideFields[K]) => void;
  inspection: SessionInspection | null;
  session: SessionSummary | null;
  uploadStatus: UploadStatus;
  uploadError: string | null;
  submitComparison: () => void;
  loadDemo: (demoId: string) => void;
  resetUpload: () => void;
  chainStatus: ChainStatus;
  chainError: string | null;
  loadDemoChain: () => void;
  chainFiles: File[];
  addChainFiles: (files: File[]) => void;
  removeChainFile: (index: number) => void;
  moveChainFile: (index: number, direction: -1 | 1) => void;
  uploadChain: () => void;
}

type EntryMode = 'pairwise' | 'chain';

function metaFor(side: 'old' | 'new', inspection: SessionInspection | null, session: SessionSummary | null): DocMetadata | null {
  if (session) return side === 'old' ? session.old_meta : session.new_meta;
  if (inspection) return side === 'old' ? inspection.old_meta : inspection.new_meta;
  return null;
}

function scannedFor(side: 'old' | 'new', inspection: SessionInspection | null, session: SessionSummary | null): number[] {
  const source = session ?? inspection;
  if (!source) return [];
  return side === 'old' ? source.scanned_old : source.scanned_new;
}

// ui-spec §3.3 分頁一「來源」— Dropzone → FileCard(+MissingVersionField) →
// 「開始版本差異比對」，或「載入示範資料」直接體驗完整流程。2026-09-15
// 使用者回饋：鏈式分析入口曾經搬到 RightPanel（原 plimsoll-two-shell-
// spec.md §2 問題 5），但使用者要求「進入頁面就要能選擇鏈式或一般比對」，兩
// 者需同等醒目——改回首屏可見，用一個 tab 切換（不是同時塞兩套 UI）維持
// 「一次只做一件事」。2026-09-27 RightPanel 的「再加一版」移除，這裡是鏈式
// 分析唯一的入口。
export function SourceTab({
  oldFile,
  newFile,
  setOldFile,
  setNewFile,
  overrides,
  updateOverride,
  inspection,
  session,
  uploadStatus,
  uploadError,
  submitComparison,
  loadDemo,
  resetUpload,
  chainStatus,
  chainError,
  loadDemoChain,
  chainFiles,
  addChainFiles,
  removeChainFile,
  moveChainFile,
  uploadChain,
}: SourceTabProps) {
  const [entryMode, setEntryMode] = useState<EntryMode>('pairwise');
  const [demoFixtures, setDemoFixtures] = useState<DemoFixture[]>([]);
  const [selectedDemoId, setSelectedDemoId] = useState('main_engine_cooling');
  const oldMeta = metaFor('old', inspection, session);
  const newMeta = metaFor('new', inspection, session);
  const canSubmit = oldFile !== null && newFile !== null && uploadStatus !== 'busy';
  // 專注提示 stage 1 — same condition as the demo button it sits above.
  const { hintFor } = useFocusHints();
  const demoHint = hintFor(!session && !oldFile && !newFile ? 'demo' : null, 'demo');

  // 示範資料選單 — 2026-09-28 使用者回饋:想從「示範資料」按鈕選擇性比對真實
  // 第三方文件(SOLAS/UNECE/EASA/CFR1512)做測試。只列出這台機器上真的有檔案
  // 的選項(external-samples 沒進 git,換一台機器 clone 就只剩合成 demo)。
  useEffect(() => {
    getDemoFixtures()
      .then((res) => setDemoFixtures(res.fixtures.filter((f) => f.available)))
      .catch(() => setDemoFixtures([]));
  }, []);
  // FileCard's ✕ stays until a session exists — it used to vanish as soon as
  // the missing-version prompt appeared, leaving no way back to an empty
  // first screen. resetUpload also clears that prompt and its overrides.

  if (!session && entryMode === 'chain') {
    return (
      <div className="space-y-3">
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => setEntryMode('pairwise')}
            className="rounded-md px-2.5 py-1.5 text-[13px] border border-line text-ink-600 hover:bg-accent-soft"
          >
            雙文件比對
          </button>
          <button type="button" className="rounded-md px-2.5 py-1.5 text-[13px] bg-ink-800 text-on-accent">
            鏈式分析比對
          </button>
        </div>
        <button
          type="button"
          onClick={loadDemoChain}
          disabled={chainStatus === 'busy'}
          className="w-full rounded-md border border-dashed border-line py-2 text-[13px] font-medium text-ink-700 hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-40"
        >
          {chainStatus === 'busy' ? '建立鏈式比對中…' : '載入鏈式漂移示範（v1.0 → v1.4，5 版）'}
        </button>
        <ChainUploadPanel
          files={chainFiles}
          onAddFiles={addChainFiles}
          onRemoveFile={removeChainFile}
          onMoveFile={moveChainFile}
          onUpload={uploadChain}
          status={chainStatus}
          error={chainError}
        />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {!session && (
        <div className="flex gap-1">
          <button type="button" className="rounded-md px-2.5 py-1.5 text-[13px] bg-ink-800 text-on-accent">
            雙文件比對
          </button>
          <button
            type="button"
            onClick={() => setEntryMode('chain')}
            className="rounded-md px-2.5 py-1.5 text-[13px] border border-line text-ink-600 hover:bg-accent-soft"
          >
            鏈式分析比對
          </button>
        </div>
      )}

      {!oldFile && !session ? (
        <Dropzone label="舊版文件" onFile={setOldFile} />
      ) : (
        <FileCard
          label="舊版文件"
          fileName={session?.old_filename ?? oldFile?.name ?? ''}
          clientSizeBytes={oldFile?.size ?? null}
          meta={oldMeta}
          scannedPages={scannedFor('old', inspection, session)}
          onRemove={session ? undefined : () => resetUpload()}
        />
      )}
      {inspection && oldMeta && (
        <MissingVersionField
          label="舊版文件"
          missingFields={oldMeta.missing_fields.filter((f) => f !== 'title')}
          version={overrides.old_version}
          date={overrides.old_date}
          onVersionChange={(v) => updateOverride('old_version', v)}
          onDateChange={(v) => updateOverride('old_date', v)}
        />
      )}

      {!newFile && !session ? (
        <Dropzone label="新版文件" onFile={setNewFile} />
      ) : (
        <FileCard
          label="新版文件"
          fileName={session?.new_filename ?? newFile?.name ?? ''}
          clientSizeBytes={newFile?.size ?? null}
          meta={newMeta}
          scannedPages={scannedFor('new', inspection, session)}
          onRemove={session ? undefined : () => resetUpload()}
        />
      )}
      {inspection && newMeta && (
        <MissingVersionField
          label="新版文件"
          missingFields={newMeta.missing_fields.filter((f) => f !== 'title')}
          version={overrides.new_version}
          date={overrides.new_date}
          onVersionChange={(v) => updateOverride('new_version', v)}
          onDateChange={(v) => updateOverride('new_date', v)}
        />
      )}

      {uploadError && (
        <p className="rounded-md border border-high-200 bg-high-50 px-2.5 py-1.5 text-[12px] text-high-700">
          比對失敗：{uploadError}
        </p>
      )}

      {!session && (
        <button
          type="button"
          disabled={!canSubmit}
          onClick={submitComparison}
          className="w-full rounded-md bg-ink-800 py-2 text-[13px] font-medium text-on-accent disabled:cursor-not-allowed disabled:opacity-40"
        >
          {uploadStatus === 'busy' ? '比對中…' : '開始版本差異比對'}
        </button>
      )}

      {!oldFile && !newFile && !session && (
        <div className="space-y-1.5">
          {demoHint && <FocusHint hint={demoHint} />}
          {demoFixtures.length > 1 && (
            <select
              value={selectedDemoId}
              onChange={(e) => setSelectedDemoId(e.target.value)}
              disabled={uploadStatus === 'busy'}
              className="w-full rounded-md border border-line bg-surface py-1.5 px-2 text-[12.5px] text-ink-700"
            >
              {demoFixtures.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.label}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            onClick={() => loadDemo(selectedDemoId)}
            disabled={uploadStatus === 'busy'}
            className="w-full rounded-md border border-line py-2 text-[13px] font-medium text-ink-700 hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-40"
          >
            {uploadStatus === 'busy' ? '比對中…' : '載入示範資料'}
          </button>
        </div>
      )}
    </div>
  );
}
