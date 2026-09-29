import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, ListChecks, X } from 'lucide-react';
import { useAgent } from '../state/useAgent';
import { type FocusHintStage, useFocusHints } from '../state/useFocusHints';
import { useIsMobile } from '../state/useIsMobile';
import { useReviewerIdentity } from '../state/useReviewerIdentity';
import { useSkipStartOverGuard } from '../state/useSkipStartOverGuard';
import type { ShellVariant } from '../state/shellConfig';
import type { AiSemanticSuggestion, ApprovalRole, ChainReviewSubmission, ChainSummary, SessionSummary } from '../types';
import { AgentSection } from './agent/AgentSection';
import { FocusHint } from './FocusHint';
import { ResizeHandle } from './ResizeHandle';
import { AlertMessage } from './thread/AlertMessage';
import { ChainMessage } from './thread/ChainMessage';
import type { RiskFilter } from './thread/DiffListMessage';
import { DiffListMessage } from './thread/DiffListMessage';
import { countUnreviewedHigh } from './thread/diffFormat';
import { ExportMessage } from './thread/ExportMessage';
import { OverviewMessage } from './thread/OverviewMessage';
import { SemanticLayerBar } from './thread/SemanticLayerBar';
import { StartOverGuard } from './thread/StartOverGuard';

interface RightPanelProps {
  shell: ShellVariant;
  collapsed: boolean;
  width: number;
  onResize: (width: number) => void;
  // 2026-09-27 使用者回饋 — 收合／展開右欄的控制從 TopBar 移進右欄自己：收合
  // 時整個 aside 就是這顆按鈕（點哪裡都展開），展開時內部另外放一顆收合鈕。
  // 兩個方向共用同一個 toggle，這裡統一叫 onToggle（沿用 useSession.toggleRight）。
  onToggle: () => void;
  session: SessionSummary | null;
  approvalRoles: ApprovalRole[];
  onSessionUpdate: (session: SessionSummary) => void;
  onJumpToPage: (side: 'old' | 'new', pdfPage: number | null, differenceId?: string) => void;
  onStartOver: () => void;
  chain: ChainSummary | null;
  onChainReview: (submission: ChainReviewSubmission) => void;
}

// 2026-09-28 使用者回饋 — ReviewerIdentityBar moved out to its own file
// (frontend/src/app/thread/ReviewerIdentityBar.tsx) so it can be mounted at
// the top of DiffListMessage's 待核准清單 AND inside FocusReviewDeck's 卡片
// 模式 header; this component still owns the state (useReviewerIdentity) and
// the identityRef that goToIdentity() scrolls/flashes.

function Section({
  title,
  defaultOpen,
  children,
}: {
  title: string;
  defaultOpen: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-line bg-surface shadow-[var(--sh-1)]">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 px-4 py-2.5 text-left text-[13px] font-medium text-ink-800"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {title}
      </button>
      {open && <div className="border-t border-line p-4 pt-3">{children}</div>}
    </div>
  );
}

// The differences list — formerly buried in the center conversation thread —
// now lives here, in the right rail, alongside the KPI/filter/action card
// and export controls; the center column is reserved for the enlarged
// text/PDF comparison viewer (CenterStage).
export function RightPanel({
  shell,
  collapsed,
  width,
  onResize,
  onToggle,
  session,
  approvalRoles,
  onSessionUpdate,
  onJumpToPage,
  onStartOver,
  chain,
  onChainReview,
}: RightPanelProps) {
  const [filter, setFilter] = useState<RiskFilter>('All');
  // 2026-09-15 redesign — 匯出審查報告 opens this as a modal instead of its
  // own accordion/sticky section; 2026-09-27 the button itself moved from the
  // overview card up into the panel's top row (see below).
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const { reviewerName, approvalRoleCode, setReviewerName, setApprovalRoleCode } = useReviewerIdentity();
  const isMobile = useIsMobile();
  // 覆核 Agent (plimsoll-review-agent-spec.md §4). Its per-difference notes
  // feed the cards below; 建議先看 links open a card via focusRequest,
  // clearing the risk filter first so the card is actually in the list.
  // With only a chain open, the agent works on the chain's v1 → vN comparison
  // (its last anchor step), which can reach every version's pages.
  const chainAgentSessionId = chain ? chain.anchor_session_ids[chain.anchor_session_ids.length - 1] : null;
  const agent = useAgent(session?.session_id ?? chainAgentSessionId);
  const { hintFor } = useFocusHints();
  const [focusRequest, setFocusRequest] = useState<{ id: string; nonce: number } | null>(null);

  // 2026-09-28 使用者回饋 — every 「尚未填寫覆核人身分」 hint (IdentityHint) jumps
  // here: close the export dialog if that's where it was clicked (卡片模式
  // closes itself in DiffListMessage), then on the next frame — once the
  // overlay is gone — scroll the block into view, flash it, and put the caret
  // in the first empty field.
  const identityRef = useRef<HTMLDivElement>(null);
  function goToIdentity() {
    setExportModalOpen(false);
    requestAnimationFrame(() => {
      const el = identityRef.current;
      if (!el) return;
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      el.classList.remove('identity-flash');
      void el.offsetWidth; // restart the animation if it's clicked twice
      el.classList.add('identity-flash');
      // 2026-09-28 使用者回饋「縮小成按鈕」— compact mode only renders the
      // input/select once its popover is open, so there's nothing to focus
      // yet the first time: click the toggle button to open it instead
      // (ReviewerIdentityBar then focuses the first empty field itself).
      const field = el.querySelector<HTMLInputElement | HTMLSelectElement>(reviewerName.trim() ? 'select' : 'input');
      if (field) field.focus({ preventScroll: true });
      else el.querySelector<HTMLButtonElement>('button')?.click();
    });
  }
  function focusDifference(id: string) {
    setFilter('All');
    setFocusRequest({ id, nonce: Date.now() });
  }

  // 2026-09-28 使用者回饋「開始新的比對要有確認防呆，避免洗掉紀錄」— local,
  // session-lifetime-only flag (no server/session-summary field for this
  // exists — see StartOverGuard.tsx's sibling docs); reset whenever a
  // different session loads, set the moment ExportMessage reports a REAL
  // (non-guarded) export succeeded.
  const [hasExportedThisSession, setHasExportedThisSession] = useState(false);
  useEffect(() => {
    setHasExportedThisSession(false);
  }, [session?.session_id]);
  const { skip: skipStartOverGuard, setSkip: setSkipStartOverGuard } = useSkipStartOverGuard();
  const [startOverGuardOpen, setStartOverGuardOpen] = useState(false);

  function handleStartOverClick() {
    if (hasExportedThisSession || skipStartOverGuard) {
      onStartOver();
      return;
    }
    setStartOverGuardOpen(true);
  }
  function confirmStartOver(skipNextTime: boolean) {
    if (skipNextTime) setSkipStartOverGuard(true);
    setStartOverGuardOpen(false);
    onStartOver();
  }
  function exportInsteadOfStartOver() {
    setStartOverGuardOpen(false);
    setExportModalOpen(true);
  }

  // P5 W7a — semantic suggestions are an overlay on top of `session.
  // differences`, never a mutation of it: differences.json is write-once,
  // and a later review-event submission replaces `session` with a fresh
  // copy that has no ai_semantic_suggestion field, so keeping this keyed by
  // difference id (not baked into `session`) means it survives that.
  const [semanticSuggestions, setSemanticSuggestions] = useState<Record<string, AiSemanticSuggestion | null>>({});
  useEffect(() => {
    setSemanticSuggestions({});
  }, [session?.session_id]);

  const displayedDifferences = useMemo(() => {
    if (!session) return [];
    if (Object.keys(semanticSuggestions).length === 0) return session.differences;
    return session.differences.map((d) =>
      d.id in semanticSuggestions ? { ...d, ai_semantic_suggestion: semanticSuggestions[d.id] } : d,
    );
  }, [session, semanticSuggestions]);

  // 2026-09-27 使用者回饋 — 右欄預設完全不存在（不是收合成一條細窄的
  // placeholder），直到有比對文件或鏈才出現；出現後才有收合／展開的意義。
  if (!session && !chain) return null;

  if (collapsed) {
    return (
      <aside
        title="點擊展開右欄"
        onClick={onToggle}
        className="flex w-[46px] shrink-0 cursor-pointer flex-col items-center gap-2.5 border-l border-line bg-surface-2 py-4 hover:bg-accent-soft"
      >
        <ListChecks size={16} className="text-ink-500" />
        {session && <span className="text-[11px] font-medium text-ink-600">{session.differences.length}</span>}
      </aside>
    );
  }

  const scannedTotal = session ? session.scanned_old.length + session.scanned_new.length : 0;
  // 2026-09-28 使用者回饋 —「High 沒處理完，匯出鍵不亮」：官網承諾的字面兌現。
  // 按鈕永遠可按（同一顆、同一個 modal、同一套 guard 流程都不變），只有「亮不
  // 亮」隨這個數字變化，見下方按鈕的條件 className。
  const unreviewedHigh = session ? countUnreviewedHigh(session.differences, session.review_state) : 0;

  // 專注提示 — the one stage that applies now, pairwise comparisons only
  // (stage 1 lives in SourceTab). A comparison with no High at all goes
  // straight to export: there is no first High to point at.
  const reviewedCount = session ? session.differences.filter((d) => session.review_state[d.id]?.human_verdict != null).length : 0;
  const hintStage: FocusHintStage | null = !session
    ? null
    : unreviewedHigh === 0
      ? 'export'
      : reviewedCount === 0
        ? agent.available && !agent.briefing
          ? 'agent'
          : 'first-high'
        : null;
  const agentHint = hintFor(hintStage, 'agent');
  const firstHighHint = hintFor(hintStage, 'first-high');
  const exportHint = hintFor(hintStage, 'export');

  // P5 RWD — a phone-width viewport gets a full-screen panel instead of a
  // squeezed sliver, and the resizable width (inline style) is dropped since
  // there's no drag handle to resize a full-screen panel against.
  return (
    <div
      className={isMobile ? 'fixed inset-0 z-40 flex' : 'flex shrink-0'}
      style={isMobile ? undefined : { width }}
    >
      {!isMobile && <ResizeHandle edge="left" width={width} onResize={onResize} />}
      <aside className="min-w-0 flex-1 overflow-y-auto border-l border-line bg-surface-2 p-3">
        {/* 2026-09-27 使用者回饋 — 右欄由上到下：收合＋新的比對＋匯出（整個
            session 的出口，最常按，放最上面）→ AI 語意建議 → 篩選卡 →（鏈式
            趨勢分析）→ 待核准清單。新的比對／匯出原本在篩選卡最底下，AI 原本
            在清單正上方。 */}
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={onToggle}
            className="flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[12.5px] text-ink-600 hover:bg-accent-soft"
          >
            <X size={14} /> {isMobile ? '關閉' : '收合右欄'}
          </button>
          {/* The panel only renders with a session or a chain, so this is
              always here; export needs a pairwise session. */}
          <button
            type="button"
            onClick={handleStartOverClick}
            className="ml-auto rounded-md border border-line px-2.5 py-1.5 text-[12.5px] text-ink-600 hover:bg-accent-soft"
          >
            ＋ 開始新的比對
          </button>
          {session && (
            <button
              type="button"
              onClick={() => setExportModalOpen(true)}
              // 2026-09-28 使用者回饋（決議「變暗但可按」）— 未確認 High 存在時
              // 鍵本身仍可按、仍開同一個 modal、仍走同一套 UnreviewedExportGuard
              // 流程；只是外觀從實心變成 outline，提示「還沒亮」。title 講清楚
              // 這不是壞掉，是可以先匯出成修訂草稿。變色靠 index.css 全域的
              // button transition 補動畫，這裡不用另外加。
              // 同日再決議：筆數用紅底小徽章，不寫成「還差 N 筆 High」一串字——
              // 那串字讓頂列在預設寬度就擠不下三顆鍵，匯出鍵被擠到第二行。兩種
              // 狀態都帶 1px 邊框，亮起時尺寸不跳。
              title={
                unreviewedHigh > 0
                  ? `還差 ${unreviewedHigh} 筆 High 未確認；仍可匯出，會標記為「修訂草稿」`
                  : undefined
              }
              className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[12.5px] font-medium ${
                unreviewedHigh > 0
                  ? 'border-line bg-surface text-ink-700 hover:bg-accent-soft'
                  : 'border-ink-800 bg-ink-800 text-on-accent hover:opacity-90'
              }`}
            >
              <span>匯出審查報告 →</span>
              {unreviewedHigh > 0 && (
                <span className="rounded-full bg-high-fill px-1.5 text-[11px] font-semibold leading-[18px] tabular-nums text-high-on-fill">
                  {unreviewedHigh}
                  <span className="sr-only"> 筆 High 未確認</span>
                </span>
              )}
            </button>
          )}
        </div>
        {exportHint && (
          <div className="mb-3">
            <FocusHint hint={exportHint} />
          </div>
        )}
        <div className="space-y-3">
            {session && (
              <SemanticLayerBar
                sessionId={session.session_id}
                onSuggestions={(map) => setSemanticSuggestions(map)}
                agentAvailable={agent.available}
                onStartAgentBriefing={agent.startBriefing}
              />
            )}

            {session && scannedTotal > 0 && (
              <AlertMessage variant="scanned">
                偵測到 {scannedTotal} 頁疑似掃描頁或文字層不足，建議人工雙重校對以防漏看重大變更。
              </AlertMessage>
            )}

            {/* 2026-09-28 使用者回饋 — moved up from after OverviewMessage:
                Agent 現在跟 SemanticLayerBar 一樣是「可觸發的 AI 動作／結果」，
                跟下面那張「風險篩選＋待核准清單」合併卡分開放。 */}
            {(session || chain) && (
              <AgentSection
                agent={agent}
                session={session}
                chainVersions={chain?.ordered_versions}
                differences={displayedDifferences}
                reviewState={session?.review_state ?? {}}
                reviewerName={reviewerName}
                approvalRoleCode={approvalRoleCode}
                onSessionUpdate={onSessionUpdate}
                onJumpToPage={onJumpToPage}
                onFocusDifference={focusDifference}
                onGoToIdentity={goToIdentity}
                hint={agentHint}
              />
            )}

            {/* A chain can exist independently of a pairwise session (a
                user may only ever run the multi-version chain flow) — this
                must never be nested inside `session &&`. */}
            {chain && (
              <Section title="鏈式趨勢分析" defaultOpen>
                <ChainMessage
                  chain={chain}
                  reviewerName={reviewerName}
                  approvalRoleCode={approvalRoleCode}
                  onReview={onChainReview}
                  onGoToIdentity={goToIdentity}
                />
              </Section>
            )}

            {/* 2026-09-27 使用者回饋 — 「再加一版」（鏈式比對的第二個入口）
                整段移除：鏈式分析的入口只剩首屏（SourceTab）那一個，已經有比
                對時按上方「＋ 開始新的比對」回首屏就選得到。 */}

            {/* 2026-09-28 使用者回饋「風險篩選跟下方待覆核區塊整合成一個區塊」
                — OverviewMessage（篩選 tiles＋風險比例條）不再自己包卡片，
                跟 DiffListMessage（待核准清單）共用這一張卡，中間一條分隔線。 */}
            {session && (
              <div className="rounded-xl border border-line bg-surface p-4 shadow-[var(--sh-1)]">
                <OverviewMessage
                  session={session}
                  shell={shell}
                  filter={filter}
                  onFilterChange={setFilter}
                />
                <div className="my-3 border-t border-line" />
                <DiffListMessage
                  sessionId={session.session_id}
                  shell={shell}
                  differences={displayedDifferences}
                  filter={filter}
                  reviewState={session.review_state}
                  reviewerName={reviewerName}
                  approvalRoleCode={approvalRoleCode}
                  approvalRoles={approvalRoles}
                  setReviewerName={setReviewerName}
                  setApprovalRoleCode={setApprovalRoleCode}
                  identityRef={identityRef}
                  onSessionUpdate={onSessionUpdate}
                  onJumpToPage={onJumpToPage}
                  onGoToIdentity={goToIdentity}
                  agentNotes={agent.notesById}
                  focusRequest={focusRequest}
                  hint={firstHighHint}
                />
              </div>
            )}
        </div>
      </aside>

      {exportModalOpen && session && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setExportModalOpen(false)}
        >
          <div onClick={(e) => e.stopPropagation()} className="w-full max-w-[440px]">
            <ExportMessage
              sessionId={session.session_id}
              reviewerName={reviewerName}
              approvalRoleCode={approvalRoleCode}
              onClose={() => setExportModalOpen(false)}
              onGoToIdentity={goToIdentity}
              onExported={() => setHasExportedThisSession(true)}
            />
          </div>
        </div>
      )}

      {startOverGuardOpen && (
        <StartOverGuard
          canExport={session != null}
          onCancel={() => setStartOverGuardOpen(false)}
          onExportInstead={exportInsteadOfStartOver}
          onConfirm={confirmStartOver}
        />
      )}
    </div>
  );
}
