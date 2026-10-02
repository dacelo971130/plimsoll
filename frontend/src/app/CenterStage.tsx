import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, ZoomIn } from 'lucide-react';
import { getSessionPages, sessionPdfUrl, type SessionPages } from '../lib/api';
import { markDifferencesInPageText } from '../lib/highlightDifferences';
import { SHELL_CONFIG, type ShellVariant } from '../state/shellConfig';
import type { ChainStatus } from '../state/useChain';
import type { UploadStatus, VersionOverrideFields } from '../state/useSession';
import type { DifferenceRecord, FocusRequest, SessionInspection, SessionSummary } from '../types';
import { MAGNIFIER_ZOOM_DEFAULT } from './magnifierConfig';
import type { HoverPoint } from './PdfCanvasViewer';
import { SourceTab } from './source/SourceTab';

// pdfjs-dist is ~1MB minified — code-split it into its own chunk, loaded
// only the first time someone actually switches to 「原始 PDF」模式, instead
// of bloating the initial bundle every user pays for on first load.
const PdfCanvasViewer = lazy(() => import('./PdfCanvasViewer').then((m) => ({ default: m.PdfCanvasViewer })));

type SourceMode = 'reconstructed' | 'original';

const MODE_KEY = 'plimsoll.sourceMode.v1';

// User feedback: the pale -50 tint alone (no border, no underline) reads as
// "no highlight at all" against the page background — a chip with a visible
// outline plus an underline/strikethrough in the semantic color is what
// actually reads as "this text changed" at a glance.
const MARK_CLASS: Record<'add' | 'del' | 'mod', string> = {
  add: 'rounded border border-low-200 bg-low-50 px-0.5 text-low-700 underline decoration-low-500 decoration-2 underline-offset-2',
  del: 'rounded border border-high-200 bg-high-50 px-0.5 text-high-700 line-through decoration-high-500 decoration-2',
  mod: 'rounded border border-med-200 bg-med-50 px-0.5 text-med-700 underline decoration-med-500 decoration-2 underline-offset-2',
};

function highlightQuery(text: string, query: string) {
  if (!query.trim()) return text;
  const parts = text.split(new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'));
  return parts.map((part, i) =>
    part.toLowerCase() === query.toLowerCase() ? (
      <mark key={i} className="bg-[var(--diff-hit)] text-ink-900">
        {part}
      </mark>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

function countHits(text: string, query: string): number {
  if (!query.trim()) return 0;
  return text.toLowerCase().split(query.toLowerCase()).length - 1;
}

type PageEntry = SessionPages['old'][number];

interface DocumentColumnProps {
  label: string;
  docSide: 'old' | 'new';
  pageData: PageEntry | null;
  mode: SourceMode;
  differences: DifferenceRecord[];
  // THIS SIDE's own raw pdf_page for the current alignment entry — never the
  // shared navigation index. null means this alignment entry has no
  // counterpart on this side at all (a whole-page insert/delete), not that
  // data hasn't loaded yet.
  page: number | null;
  query: string;
  sessionId: string;
  activeDifferenceId: string | null;
  magnifierOn: boolean;
  magnifierZoom: number;
  magnifierInput: 'hover' | 'click';
  showPdfNewTabLink: boolean;
  hoverPoint: HoverPoint | null;
  onHoverPoint: (point: HoverPoint | null) => void;
}

// Hoisted to module scope — this used to be defined INSIDE ComparisonViewer's
// render body (a `function Column(...)` closing over its state directly).
// That meant a fresh function identity every render, which React treats as a
// different component TYPE at the same JSX position — so every parent
// re-render unmounted and remounted this (and the PdfCanvasViewer/pdf.js
// pipeline inside it: refetch the PDF over HTTP, re-render to canvas, redo
// text-content matching for the diff overlay — none of it cheap). Bug report:
// turning the magnifier on and moving the mouse — which updates hoverPoint on
// every mousemove — fired a storm of HTTP requests, because each state
// update remounted both columns from scratch. Hoisting it out with all state
// passed as explicit props gives it a stable identity across renders, so
// React reconciles in place instead of unmount+remount — this was already
// latent (typing in the search box hit the same remount on every keystroke),
// mousemove just made it impossible to miss.
function DocumentColumn({
  label,
  docSide,
  pageData,
  mode,
  differences,
  page,
  query,
  sessionId,
  activeDifferenceId,
  magnifierOn,
  magnifierZoom,
  magnifierInput,
  showPdfNewTabLink,
  hoverPoint,
  onHoverPoint,
}: DocumentColumnProps) {
  const relevantDifferences = differences.filter((d) => {
    const span = docSide === 'old' ? d.old : d.new;
    return span?.page.pdf_page === page && d.kind !== 'drawing'; // drawing pages have no reconstructable text
  });

  return (
    <div className="min-w-0 flex-1">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] font-medium uppercase text-ink-500">
          {label}
          {/* Old/new no longer share one page number (W3 alignment can shift
              them independently) — show which real page this column is on,
              since "11 / 431" up top is now a position in the aligned pair
              list, not a page number either side's PDF actually uses. */}
          {page !== null && <span className="ml-1 normal-case tabular-nums text-ink-400">· 第 {page} 頁</span>}
        </div>
        {/* 殼 B 專屬新增（plimsoll-two-shell-spec.md §3 #07）— 原生瀏覽器 PDF
            檢視器的縮放/列印/文字搜尋是內嵌 canvas 沒有的真實能力差異，不是裝
            飾；真正的 <a> 元素，不是 window.open()（§2 問題 6）。 */}
        {mode === 'original' && showPdfNewTabLink && page !== null && (
          <a
            href={sessionPdfUrl(sessionId, docSide)}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 text-[11px] text-ink-500 underline hover:text-ink-800"
          >
            在新分頁開啟原始 PDF
          </a>
        )}
      </div>
      {page === null ? (
        // W3 alignment found no counterpart on this side for the page shown
        // opposite — a whole-page insert/delete, not missing data. Showing
        // THIS side's unrelated raw page here (the old positional-zip
        // behavior) was the actual bug: it looked like real content got
        // flagged as changed, when the two columns were just two unrelated
        // pages that happened to share a page number.
        <p className="mt-1 text-[13px] text-ink-400">此版本無對應頁面（該內容為整頁新增／刪除，見右側差異清單）。</p>
      ) : mode === 'reconstructed' ? (
        <div
          className="mt-1 whitespace-pre-wrap text-[14.5px] leading-[1.85] text-ink-800"
          style={{ fontFamily: 'var(--font-source)' }}
        >
          {pageData ? (
            markDifferencesInPageText(pageData.text, relevantDifferences, docSide).map((seg) =>
              seg.kind ? (
                <mark key={seg.key} data-difference-id={seg.differenceId} className={MARK_CLASS[seg.kind]}>
                  {seg.text}
                </mark>
              ) : (
                <span key={seg.key}>{highlightQuery(seg.text, query)}</span>
              ),
            )
          ) : (
            <span className="text-ink-400">此頁無資料</span>
          )}
        </div>
      ) : (
        <div className="mt-1">
          <Suspense fallback={<p className="text-[13px] text-ink-400">載入 PDF 檢視器中…</p>}>
            <PdfCanvasViewer
              sessionId={sessionId}
              side={docSide}
              page={page}
              differences={differences}
              activeDifferenceId={activeDifferenceId}
              magnifierEnabled={magnifierOn}
              magnifierZoom={magnifierZoom}
              magnifierInput={magnifierInput}
              hoverPoint={hoverPoint}
              onHoverPoint={onHoverPoint}
            />
          </Suspense>
        </div>
      )}
    </div>
  );
}

interface ComparisonViewerProps {
  shell: ShellVariant;
  sessionId: string;
  pageCountOld: number;
  pageCountNew: number;
  differences: DifferenceRecord[];
  focusRequest: FocusRequest | null;
  activeDifferenceId: string | null;
}

// The former TextSourceTab, promoted from a corner of the right rail to the
// main stage: bigger type, one scroll region (not two nested ones — see the
// flex min-h-0 fix below), and the differences are now highlighted directly
// in the reconstructed page text (red=刪除/green=新增/orange=修改) instead of
// only being visible inside an expanded DiffCard.
function ComparisonViewer({ shell, sessionId, pageCountOld, pageCountNew, differences, focusRequest, activeDifferenceId }: ComparisonViewerProps) {
  const { magnifierInput, showPdfNewTabLink } = SHELL_CONFIG[shell];
  const [mode, setMode] = useState<SourceMode>(() => (localStorage.getItem(MODE_KEY) as SourceMode) || 'reconstructed');
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState('');
  const [pages, setPages] = useState<SessionPages | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  // 放大鏡 — user feedback: 兩邊 PDF 要能同步鎖定同一個游標點，光是把單邊字級
  // 放大還是看不準到底改了沒。hoverPoint is lifted up here (not local to one
  // PdfCanvasViewer) specifically so BOTH old/new columns' lenses redraw from
  // the same point regardless of which side's canvas the cursor is actually
  // over — see PdfCanvasViewer's HoverPoint doc comment.
  const [magnifierOn, setMagnifierOn] = useState(false);
  // plimsoll-subtraction-matrix.html 小win #08 — 使用者要的是看清楚，不是選倍
  // 率；固定一個好值，不再是可調的 state。
  const magnifierZoom = MAGNIFIER_ZOOM_DEFAULT;
  const [hoverPoint, setHoverPoint] = useState<HoverPoint | null>(null);

  // 殼 B（click）— Esc clears a locked lens point, same as re-clicking it
  // (plimsoll-two-shell-spec.md §3 #11). Lives here (not in PdfCanvasViewer)
  // because this is the single owner of hoverPoint for both old/new sides.
  useEffect(() => {
    if (magnifierInput !== 'click') return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setHoverPoint(null);
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [magnifierInput]);

  useEffect(() => {
    setPages(null);
    setPage(1);
    getSessionPages(sessionId).then(setPages).catch(() => setPages(null));
  }, [sessionId]);

  useEffect(() => {
    localStorage.setItem(MODE_KEY, mode);
  }, [mode]);

  // A stale crosshair pointing at last page's content would be actively
  // misleading on the new page — drop it on any page/mode change.
  useEffect(() => {
    setHoverPoint(null);
  }, [page, mode]);

  // Jumping from a DiffCard's page-ref pill — `page` is now a position in
  // page_alignment, not a raw pdf_page, so find the alignment entry whose
  // requested SIDE has that pdf_page (the other side comes along for free,
  // whatever it actually aligns to — no separate "side" to switch into, the
  // viewer always shows both columns at once). Depends on `pages` too: a
  // focusRequest firing before page_alignment has loaded should still land
  // once it arrives, rather than silently no-op against an empty list.
  useEffect(() => {
    if (!focusRequest || !pages) return;
    const idx = pages.page_alignment.findIndex((e) =>
      focusRequest.side === 'old' ? e.old_pdf_page === focusRequest.pdfPage : e.new_pdf_page === focusRequest.pdfPage,
    );
    if (idx !== -1) setPage(idx + 1);
  }, [focusRequest, pages]);

  // Scroll the flashed difference into view once its page has rendered.
  useEffect(() => {
    if (!activeDifferenceId || !containerRef.current) return;
    const el = containerRef.current.querySelector(`[data-difference-id="${activeDifferenceId}"]`);
    if (!el) return;
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    el.classList.add('diff-mark-flash');
    const timer = setTimeout(() => el.classList.remove('diff-mark-flash'), 1600);
    return () => clearTimeout(timer);
  }, [activeDifferenceId, page, mode]);

  // `page` is a 1-indexed position in page_alignment (W3, the SAME alignment
  // the diff list uses) — not a raw pdf_page number. Falls back to the naive
  // max-of-both-counts only while page_alignment hasn't loaded yet, so the
  // pager doesn't flash "0" during that instant.
  const pageCount = pages?.page_alignment.length ?? Math.max(pageCountOld, pageCountNew);
  const alignmentEntry = pages?.page_alignment[page - 1] ?? null;
  const oldPdfPage = alignmentEntry?.old_pdf_page ?? null;
  const newPdfPage = alignmentEntry?.new_pdf_page ?? null;
  const oldPage = oldPdfPage != null ? pages?.old.find((p) => p.pdf_page === oldPdfPage) ?? null : null;
  const newPage = newPdfPage != null ? pages?.new.find((p) => p.pdf_page === newPdfPage) ?? null : null;

  const hits = useMemo(() => {
    const oldHits = oldPage ? countHits(oldPage.text, query) : 0;
    const newHits = newPage ? countHits(newPage.text, query) : 0;
    return oldHits + newHits;
  }, [oldPage, newPage, query]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line pb-2">
        <div className="flex gap-1">
          {(
            [
              ['reconstructed', '文字比對'],
              ['original', '原始 PDF'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setMode(key)}
              className={`rounded-md px-2.5 py-1.5 text-[13px] ${
                mode === key ? 'bg-ink-800 text-on-accent' : 'border border-line text-ink-600 hover:bg-accent-soft'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {mode === 'reconstructed' && (
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜尋本頁文字…"
            className="min-w-[160px] flex-1 rounded-md border border-line bg-surface px-2.5 py-1.5 text-[13px] text-ink-800"
          />
        )}

        {mode === 'original' && (
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => {
                setMagnifierOn((v) => !v);
                setHoverPoint(null);
              }}
              title="放大鏡 — 兩側 PDF 同步鎖定同一個游標點，逐像素比對"
              className={`flex items-center gap-1 rounded-md px-2.5 py-1.5 text-[13px] ${
                magnifierOn ? 'bg-ink-800 text-on-accent' : 'border border-line text-ink-600 hover:bg-accent-soft'
              }`}
            >
              <ZoomIn size={14} /> 放大鏡
            </button>
          </div>
        )}

        <div className="ml-auto flex items-center gap-2 text-[12.5px] text-ink-500">
          <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className="disabled:opacity-30">
            <ChevronLeft size={16} />
          </button>
          <span className="tabular-nums" title="比對後的頁面順序，非原始頁碼 — 每欄自己的頁碼見欄位標題">
            {page} / {pageCount} {query.trim() && `· 命中 ${hits} 處`}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
            disabled={page >= pageCount}
            className="disabled:opacity-30"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      <div
        ref={containerRef}
        onMouseLeave={() => setHoverPoint(null)}
        className="mt-3 min-h-0 flex-1 overflow-y-auto rounded-md border border-line bg-surface p-4"
      >
        {!pages ? (
          <p className="text-[13px] text-ink-400">載入中…</p>
        ) : (
          <div className="flex flex-col gap-4 sm:flex-row">
            <DocumentColumn
              label="舊版"
              docSide="old"
              pageData={oldPage}
              mode={mode}
              differences={differences}
              page={oldPdfPage}
              query={query}
              sessionId={sessionId}
              activeDifferenceId={activeDifferenceId}
              magnifierOn={magnifierOn}
              magnifierZoom={magnifierZoom}
              magnifierInput={magnifierInput}
              showPdfNewTabLink={showPdfNewTabLink}
              hoverPoint={hoverPoint}
              onHoverPoint={setHoverPoint}
            />
            <DocumentColumn
              label="新版"
              docSide="new"
              pageData={newPage}
              mode={mode}
              differences={differences}
              page={newPdfPage}
              query={query}
              sessionId={sessionId}
              activeDifferenceId={activeDifferenceId}
              magnifierOn={magnifierOn}
              magnifierZoom={magnifierZoom}
              magnifierInput={magnifierInput}
              showPdfNewTabLink={showPdfNewTabLink}
              hoverPoint={hoverPoint}
              onHoverPoint={setHoverPoint}
            />
          </div>
        )}
      </div>
    </div>
  );
}

interface CenterStageProps {
  shell: ShellVariant;
  session: SessionSummary | null;
  inspection: SessionInspection | null;
  focusRequest: FocusRequest | null;
  activeDifferenceId: string | null;
  // upload flow, forwarded to <SourceTab> when there's no session yet
  oldFile: File | null;
  newFile: File | null;
  setOldFile: (f: File) => void;
  setNewFile: (f: File) => void;
  overrides: VersionOverrideFields;
  updateOverride: <K extends keyof VersionOverrideFields>(key: K, value: VersionOverrideFields[K]) => void;
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

// Main stage: before a session exists this is the upload flow (still just
// <SourceTab>, unchanged — only its home moved); once a session exists it's
// the enlarged, highlight-aware comparison viewer.
export function CenterStage({
  shell,
  session,
  inspection,
  focusRequest,
  activeDifferenceId,
  oldFile,
  newFile,
  setOldFile,
  setNewFile,
  overrides,
  updateOverride,
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
}: CenterStageProps) {
  return (
    <section className="flex min-w-0 flex-1 flex-col bg-canvas">
      <div className="flex-1 overflow-y-auto p-6">
        {session ? (
          <ComparisonViewer
            shell={shell}
            sessionId={session.session_id}
            pageCountOld={session.old_meta.page_count}
            pageCountNew={session.new_meta.page_count}
            differences={session.differences}
            focusRequest={focusRequest}
            activeDifferenceId={activeDifferenceId}
          />
        ) : (
          <div className="mx-auto max-w-[640px] space-y-4">
            <div className="rounded-xl border border-line bg-surface p-4 text-[13.5px] text-ink-700 shadow-[var(--sh-1)]">
              <p>上傳舊版與新版 PDF，Plimsoll 找出變了什麼。</p>
            </div>
            <SourceTab
              oldFile={oldFile}
              newFile={newFile}
              setOldFile={setOldFile}
              setNewFile={setNewFile}
              overrides={overrides}
              updateOverride={updateOverride}
              inspection={inspection}
              session={session}
              uploadStatus={uploadStatus}
              uploadError={uploadError}
              submitComparison={submitComparison}
              loadDemo={loadDemo}
              resetUpload={resetUpload}
              chainStatus={chainStatus}
              chainError={chainError}
              loadDemoChain={loadDemoChain}
              chainFiles={chainFiles}
              addChainFiles={addChainFiles}
              removeChainFile={removeChainFile}
              moveChainFile={moveChainFile}
              uploadChain={uploadChain}
            />
          </div>
        )}
      </div>
    </section>
  );
}
