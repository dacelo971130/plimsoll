import { useEffect, useRef, useState, type RefObject } from 'react';
import { Layers } from 'lucide-react';
import { submitReviewEvent } from '../../lib/api';
import { SHELL_CONFIG, type ShellVariant } from '../../state/shellConfig';
import type { AgentNote } from '../../state/useAgent';
import type { FocusHintHandle } from '../../state/useFocusHints';
import { hasReviewerIdentity } from '../../state/useReviewerIdentity';
import type { ApprovalRole, DifferenceRecord, ReviewState, ReviewVerdict, RiskLevel, SessionSummary } from '../../types';
import { adoptedNote } from '../agent/agentLabels';
import { AgentNotePanel } from '../agent/AgentNotePanel';
import { FocusHint } from '../FocusHint';
import { BulkReviewButton } from './BulkReviewButton';
import { DiffReadout, DiffTextBlock, DrawingRegions, SemanticSuggestionPanel } from './DiffDetails';
import { countUnreviewedHigh, jumpTarget, pageLabel, VERDICT_BADGE, type ReviewDraft } from './diffFormat';
import { FocusReviewDeck } from './FocusReviewDeck';
import { ReviewBar } from './ReviewBar';
import { ReviewerIdentityBar } from './ReviewerIdentityBar';
import { RiskPill } from './RiskPill';
import { RISK_STRIPE } from './riskStyle';

export type RiskFilter = 'All' | RiskLevel;

interface DiffListMessageProps {
  sessionId: string;
  shell: ShellVariant;
  differences: DifferenceRecord[];
  filter: RiskFilter;
  reviewState: Record<string, ReviewState>;
  reviewerName: string;
  approvalRoleCode: string;
  // 2026-09-28 使用者回饋「覆核人身分放到待核准清單區塊最上方」— RightPanel
  // still owns the identity state (ReviewerIdentityBar's setters + the ref
  // goToIdentity scrolls/flashes), this list just renders it now.
  approvalRoles: ApprovalRole[];
  setReviewerName: (name: string) => void;
  setApprovalRoleCode: (code: string) => void;
  identityRef: RefObject<HTMLDivElement | null>;
  onSessionUpdate: (session: SessionSummary) => void;
  onJumpToPage: (side: 'old' | 'new', pdfPage: number | null, differenceId?: string) => void;
  // Scrolls the right panel to the 覆核人身分 block (RightPanel owns it).
  onGoToIdentity: () => void;
  // 覆核 Agent (spec §4.4): per-difference notes from the latest briefing, and
  // a request to open a card (the briefing's 建議先看 links). Both optional so
  // the list works exactly as before without an agent.
  agentNotes?: Record<string, AgentNote>;
  focusRequest?: { id: string; nonce: number } | null;
  // 專注提示, non-null only while RightPanel says this is the active stage;
  // shown under the first unconfirmed High card.
  hint?: FocusHintHandle | null;
}

const EMPTY_DRAFT: ReviewDraft = { verdict: null, riskOverride: null, note: '' };

function isTypingTarget(el: Element | null): boolean {
  const tag = el?.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
}

// ui-spec §3.2 `diff-list` + DiffCard 完整態。收合態可掃視；展開（focus）態是
// 逐字 diff + 讀出區 + ReviewBar，鍵盤 J/K 換筆、A/T/D 選判定、Enter 送出並
//跳下一筆（覆核事件寫入 §21 稽核骨幹，並經 approval_policies 伺服器端攔截）。
export function DiffListMessage({
  sessionId,
  shell,
  differences,
  filter,
  reviewState,
  reviewerName,
  approvalRoleCode,
  approvalRoles,
  setReviewerName,
  setApprovalRoleCode,
  identityRef,
  onSessionUpdate,
  onJumpToPage,
  agentNotes,
  focusRequest,
  onGoToIdentity,
  hint,
}: DiffListMessageProps) {
  const shown = differences.filter((d) => filter === 'All' || d.ai_risk === filter);
  // Not rendered when the current filter hides that card.
  const firstHighId = hint ? (shown.find((d) => d.ai_risk === 'High' && reviewState[d.id]?.human_verdict !== 'CONFIRMED')?.id ?? null) : null;

  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<ReviewDraft>(EMPTY_DRAFT);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // 專注簽核 deck — open flag, which way the last move went (the incoming
  // card slides in from that side), and the end-of-round card.
  const [deckOpen, setDeckOpen] = useState(false);
  const [deckDirection, setDeckDirection] = useState<1 | -1>(1);
  const [deckDone, setDeckDone] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  function focus(id: string) {
    setFocusedId(id);
    const existing = reviewState[id];
    // An agent suggestion prefills the verdict only when nobody has judged
    // this difference yet; it's still the reviewer's press that submits it.
    const suggested = existing?.human_verdict == null ? agentNotes?.[id]?.suggestion?.verdict ?? null : null;
    setDraft({
      verdict: (existing?.human_verdict as ReviewVerdict | null) ?? suggested,
      riskOverride: (existing?.risk_override as RiskLevel | null) ?? null,
      note: existing?.reviewer_note ?? '',
    });
    setSubmitError(null);
  }

  function jumpTo(d: DifferenceRecord) {
    const { side, pdfPage } = jumpTarget(d);
    onJumpToPage(side, pdfPage, d.id);
  }

  function scrollCardIntoView(id: string) {
    requestAnimationFrame(() => {
      listRef.current?.querySelector(`[data-difference-id="${id}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
  }

  // 2026-09-27 使用者回饋「點擊區塊或查看時自動跳轉比對位置，同時展開區塊詳細
  // 內容」— one action, not two buttons: every way of landing on a card (click,
  // 查看, J/K, 送出後的下一筆, 殼 B 上一筆／下一筆) both expands it here and moves
  // the center viewer to it, so the two never point at different differences.
  function open(d: DifferenceRecord) {
    focus(d.id);
    jumpTo(d);
    scrollCardIntoView(d.id);
  }

  function moveFocus(delta: number) {
    if (shown.length === 0) return;
    const currentIndex = shown.findIndex((d) => d.id === focusedId);
    const nextIndex = currentIndex === -1 ? 0 : Math.min(Math.max(currentIndex + delta, 0), shown.length - 1);
    setDeckDirection(delta < 0 ? -1 : 1);
    if (delta < 0) setDeckDone(false);
    // The deck covers the viewer, so it only moves the focus; closeDeck()
    // jumps once, to wherever the reviewer ended up.
    if (deckOpen) focus(shown[nextIndex].id);
    else open(shown[nextIndex]);
  }

  function openDeck() {
    // Start where the work is: the first card in the current filter without
    // a verdict yet, else the first card.
    const start = shown.find((d) => reviewState[d.id]?.human_verdict == null) ?? shown[0];
    if (!start) return;
    focus(start.id);
    setDeckDirection(1);
    setDeckDone(false);
    setDeckOpen(true);
  }

  function closeDeck() {
    setDeckOpen(false);
    setDeckDone(false);
    const current = shown.find((d) => d.id === focusedId);
    if (current) {
      jumpTo(current);
      scrollCardIntoView(current.id);
    }
  }

  // The identity block sits in the right panel, which the 卡片模式 overlay
  // covers — leave the deck first (no viewer jump: the reviewer is going to
  // fill in a name, not look at a passage).
  function goToIdentity() {
    if (deckOpen) {
      setDeckOpen(false);
      setDeckDone(false);
    }
    onGoToIdentity();
  }

  function handleCardClick(e: React.MouseEvent, d: DifferenceRecord, expanded: boolean) {
    // Controls inside the card (查看, ReviewBar, the note box…) keep their own
    // meaning, and dragging to select text to copy isn't a click on the card.
    if ((e.target as HTMLElement).closest('button, a, input, textarea, select, label')) return;
    if (window.getSelection()?.toString()) return;
    // 2026-09-28 使用者回饋「點開但收合不回去」— clicking the card body must be
    // a symmetric toggle, matching the 查看/收合 button below (line ~427)
    // exactly, not a one-way jumpTo that leaves it stuck open.
    if (expanded) setFocusedId(null);
    else open(d);
  }

  // Same gate as ReviewBar's button (canSubmit) — Enter used to skip the
  // identity and in-flight checks and post an unsigned review.
  const canSubmit =
    focusedId !== null && draft.verdict !== null && hasReviewerIdentity(reviewerName, approvalRoleCode) && !submitting;

  async function handleSubmit() {
    if (!canSubmit || !focusedId || draft.verdict === null) return;
    setSubmitting(true);
    setSubmitError(null);
    // Kept the agent's suggested verdict → the note records which run it came
    // from; a changed verdict means the suggestion wasn't adopted.
    const note = agentNotes?.[focusedId];
    const reviewerNote = note?.suggestion && note.suggestion.verdict === draft.verdict ? adoptedNote(note.runId, draft.note) : draft.note;
    try {
      const result = await submitReviewEvent(sessionId, {
        difference_id: focusedId,
        human_verdict: draft.verdict,
        risk_override: draft.riskOverride,
        reviewer_name: reviewerName,
        approval_role_code: approvalRoleCode,
        reviewer_note: reviewerNote,
      });
      onSessionUpdate(result.session);
      if (deckOpen && shown.findIndex((d) => d.id === focusedId) === shown.length - 1) setDeckDone(true);
      else moveFocus(1);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  useEffect(() => {
    if (!focusRequest) return;
    // 建議先看 lands on a card the same way a click does (open(): expand, jump
    // the viewer, scroll the card into view within this list — a document-wide
    // [data-difference-id] query can hit CenterStage's mark instead).
    const target = differences.find((d) => d.id === focusRequest.id);
    if (target) open(target);
    else focus(focusRequest.id);
    // Only a new request (nonce) should refocus — not every re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRequest?.nonce]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      // Esc leaves the deck even from inside the note box.
      if (deckOpen && e.key === 'Escape') {
        e.preventDefault();
        closeDeck();
        return;
      }
      if (isTypingTarget(document.activeElement)) return;
      switch (e.key.toLowerCase()) {
        case 'arrowright':
          if (deckOpen) {
            e.preventDefault();
            moveFocus(1);
          }
          break;
        case 'arrowleft':
          if (deckOpen) {
            e.preventDefault();
            moveFocus(-1);
          }
          break;
        case 'j':
          e.preventDefault();
          moveFocus(1);
          break;
        case 'k':
          e.preventDefault();
          moveFocus(-1);
          break;
        case 'a':
          if (focusedId) setDraft((d) => ({ ...d, verdict: 'CONFIRMED' }));
          break;
        case 't':
          if (focusedId) setDraft((d) => ({ ...d, verdict: 'TRACK' }));
          break;
        case 'd':
          if (focusedId) setDraft((d) => ({ ...d, verdict: 'REJECTED' }));
          break;
        case 'enter':
          // Swallowed whenever a verdict is picked, even if handleSubmit
          // then refuses (no identity) — otherwise the browser's own Enter
          // "clicks" whatever button has focus, e.g. collapsing the card.
          if (deckOpen && deckDone) {
            e.preventDefault();
            closeDeck();
          } else if (focusedId && draft.verdict !== null) {
            e.preventDefault();
            void handleSubmit();
          }
          break;
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
    // No dependency array on purpose: re-subscribing every render is cheap
    // and keeps the closure's focusedId/draft/reviewer fields fresh without
    // hand-maintaining a long dependency list.
  });

  // 2026-09-27 使用者回饋「待簽核和已覆核根本不能按」— they used to sit in
  // the overview card's filter-chip row looking exactly like the chips next
  // to them. Moved here as plain text (no border, no pill) in the list's own
  // title row: they describe this list's progress, not a filter.
  // plimsoll-subtraction-matrix.html 小win #04「未覆核 High 只講一次」——殼 A
  // 的一句話已經講過「還有 N 筆 High 沒人看過」，所以待簽核 High 只在殼 B 出現。
  // 2026-09-28 使用者回饋「這裡有點擁擠」— 已覆核 x／N 拿掉；「專注簽核」改名
  // 「卡片模式」並固定在標題列最右邊（殼 B 在待簽核 High 的右側，殼 A 沒有那個
  // 數字，按鈕仍在同一個最右位置）。
  const unreviewedHigh = countUnreviewedHigh(differences, reviewState);
  const showPendingHigh = SHELL_CONFIG[shell].overviewPresentation !== 'sentence';

  // 2026-09-28 使用者回饋「縮小成按鈕放在卡片模式左側」— moved out of its own
  // full-width row (originally in RightPanel, then briefly its own row here)
  // into a compact button right in this title row, left of 卡片模式.
  // FocusReviewDeck's 卡片模式 header still gets the full-width bar (see its
  // own file) — same state either way, only the presentation differs.
  const header = (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-1">
      <h3 className="text-[13px] font-semibold text-ink-800">待核准清單</h3>
      <div className="ml-auto flex items-center gap-2 text-[12px] text-ink-500">
        {showPendingHigh && (
          <span className={`inline-flex items-center gap-1 ${unreviewedHigh > 0 ? 'text-high-700' : ''}`}>
            {unreviewedHigh > 0 && <span className="h-2 w-2 rounded-full bg-high-fill" />}
            待簽核 High <strong className="font-semibold tabular-nums">{unreviewedHigh}</strong>
          </span>
        )}
        <BulkReviewButton
          sessionId={sessionId}
          differences={differences}
          reviewState={reviewState}
          filter={filter}
          reviewerName={reviewerName}
          approvalRoleCode={approvalRoleCode}
          onSessionUpdate={onSessionUpdate}
        />
        <ReviewerIdentityBar
          compact
          containerRef={identityRef}
          reviewerName={reviewerName}
          approvalRoleCode={approvalRoleCode}
          approvalRoles={approvalRoles}
          setReviewerName={setReviewerName}
          setApprovalRoleCode={setApprovalRoleCode}
        />
        <button
          type="button"
          onClick={openDeck}
          disabled={shown.length === 0}
          className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[12px] font-medium text-ink-700 hover:bg-accent-soft disabled:opacity-40"
        >
          <Layers size={13} /> 卡片模式
        </button>
      </div>
    </div>
  );

  const deck = deckOpen && shown.length > 0 && (
    <FocusReviewDeck
      cards={shown}
      currentId={focusedId}
      direction={deckDirection}
      done={deckDone}
      reviewState={reviewState}
      agentNotes={agentNotes}
      onJumpToPage={onJumpToPage}
      draft={draft}
      onDraftChange={(patch) => setDraft((prev) => ({ ...prev, ...patch }))}
      reviewerName={reviewerName}
      approvalRoleCode={approvalRoleCode}
      approvalRoles={approvalRoles}
      setReviewerName={setReviewerName}
      setApprovalRoleCode={setApprovalRoleCode}
      onSubmit={handleSubmit}
      submitting={submitting}
      error={submitError}
      onPrev={() => moveFocus(-1)}
      onNext={() => moveFocus(1)}
      onClose={closeDeck}
      onGoToIdentity={goToIdentity}
    />
  );

  if (shown.length === 0) {
    return (
      <div className="space-y-2">
        {header}
        <div className="list-in rounded-xl border border-dashed border-line p-4 text-center text-[12.5px] text-ink-500">
          沒有符合篩選條件的差異。
        </div>
        {deck}
      </div>
    );
  }

  // plimsoll-two-shell-spec.md §3 #18 — 殼 B 一次只看一筆：once a card is
  // focused, every other card in `shown` stops rendering entirely (not just
  // visually hidden) and a progress/prev-next/exit rail replaces the list.
  // Falls back to the full list (same as 殼 A) if the focused id fell out of
  // `shown` (e.g. a filter change mid-review) instead of showing nothing.
  const stepperCard = SHELL_CONFIG[shell].reviewMode === 'stepper' ? (shown.find((d) => d.id === focusedId) ?? null) : null;
  const isStepper = stepperCard !== null;
  const cardsToRender = isStepper ? [stepperCard] : shown;
  const stepperIndex = isStepper ? shown.findIndex((d) => d.id === focusedId) : -1;

  return (
    <div className="space-y-2">
      {header}
      {isStepper && (
        <div className="text-[12.5px] font-medium text-ink-600">
          第 {stepperIndex + 1}／{shown.length} 筆
        </div>
      )}
      {/* Keyed on the active risk filter so switching it remounts the list
          and every card replays `.list-in` (staggered) — the list half of
          「點選時要有切換的動畫」; expanding a card or submitting a verdict
          leaves the key alone, so neither of those replays it. */}
      <div key={filter} ref={listRef} className="space-y-2">
      {cardsToRender.map((d, i) => {
        const state = reviewState[d.id];
        const expanded = focusedId === d.id;
        const isDrawing = d.kind === 'drawing';
        const displayRisk = draft.riskOverride && expanded ? draft.riskOverride : d.ai_risk;
        return (
          <div
            key={d.id}
            data-difference-id={d.id}
            style={{ animationDelay: `${Math.min(i, 8) * 30}ms` }}
            onClick={(e) => handleCardClick(e, d, expanded)}
            className={`list-in rounded-xl border border-l-4 bg-surface p-3 shadow-[var(--sh-1)] ${
              expanded ? 'border-ink-800' : 'cursor-pointer border-line hover:shadow-[var(--sh-2)]'
            } ${RISK_STRIPE[displayRisk]}`}
          >
            <div className="flex items-center gap-1.5">
              <RiskPill risk={displayRisk} />
              <span className="rounded-full border border-line px-1.5 py-0.5 text-[11px] text-ink-600">{d.change_type}</span>
              {isDrawing && (
                <span className="rounded-full border border-line bg-surface-2 px-1.5 py-0.5 text-[11px] text-ink-600">
                  工程圖
                </span>
              )}
              <span className="text-[11px] text-ink-400">信心 {d.ai_confidence}</span>
              {d.component_ref && (
                <span className="rounded-full border border-line px-1.5 py-0.5 text-[11px] text-ink-600">
                  {d.component_ref}
                </span>
              )}
              {state?.human_verdict && (
                <span className="rounded-full border border-low-200 bg-low-50 px-1.5 py-0.5 text-[11px] text-low-700">
                  {VERDICT_BADGE[state.human_verdict]} · {state.reviewer_name}
                </span>
              )}
              <span className="ml-auto font-mono text-[11px] text-ink-400">{d.id}</span>
            </div>

            {isDrawing ? (
              expanded && <DrawingRegions d={d} />
            ) : expanded ? (
              <DiffTextBlock d={d} />
            ) : isDrawing ? (
              <p className="mt-1.5 line-clamp-2 text-[12.5px] text-ink-600">{d.explanation}</p>
            ) : (
              // User feedback: some diffs' text runs very long — showing it
              // in full made the collapsed list (meant for scanning many
              // items at a glance) unusably tall. Clamped to 2 lines here;
              // the full text is always one click away (the card itself or
              // 查看 below), in CharDiffText's char-level diff view.
              <div className="mt-1.5 text-[12.5px]">
                {d.old && (
                  <p style={{ color: 'var(--diff-del)' }} className="line-clamp-2 line-through">
                    {d.old.text}
                  </p>
                )}
                {d.new && <p style={{ color: 'var(--diff-add)' }} className="line-clamp-2">{d.new.text}</p>}
              </div>
            )}

            {expanded && !isDrawing && <SemanticSuggestionPanel d={d} />}

            {expanded && (
              <AgentNotePanel
                differenceId={d.id}
                note={agentNotes?.[d.id]}
                prefilled={state?.human_verdict == null}
                onJumpToPage={onJumpToPage}
              />
            )}

            {expanded && <DiffReadout d={d} />}

            {/* 2026-09-27 使用者回饋 — 「舊」「新」兩顆跳頁按鈕和「展開」合成
                一顆「查看」，按下去同時跳頁＋展開（見 open()）。觸控範圍維持
                先前「定位按鈕太小很難點」回饋後放大的尺寸。
                2026-09-28 使用者回饋 — 頁碼改回跟 d.affected 一樣的獨立標籤
                （不再塞進按鈕文字裡），按鈕文字只留「查看」。 */}
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12.5px] text-ink-600">
              {d.affected && <span className="rounded-full border border-line bg-surface-2 px-1.5 py-0.5 text-[11px]">{d.affected}</span>}
              {!expanded && (
                <span className="rounded-full border border-line bg-surface-2 px-1.5 py-0.5 text-[11px]">
                  舊 {pageLabel(d.old)} → 新 {pageLabel(d.new)}
                </span>
              )}
              <button
                type="button"
                onClick={() => (expanded ? setFocusedId(null) : open(d))}
                className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 font-medium text-ink-700 hover:border-ink-400 hover:bg-accent-soft hover:text-ink-900"
              >
                {expanded ? '收合' : '查看'}
              </button>
            </div>

            {hint && d.id === firstHighId && (
              <div className="mt-2">
                <FocusHint hint={hint} />
              </div>
            )}

            {expanded && (
              <ReviewBar
                aiRisk={d.ai_risk}
                draftVerdict={draft.verdict}
                draftRiskOverride={draft.riskOverride}
                draftNote={draft.note}
                onVerdictChange={(v) => setDraft((prev) => ({ ...prev, verdict: v }))}
                onRiskOverrideChange={(r) => setDraft((prev) => ({ ...prev, riskOverride: r }))}
                onNoteChange={(n) => setDraft((prev) => ({ ...prev, note: n }))}
                reviewerName={reviewerName}
                approvalRoleCode={approvalRoleCode}
                onSubmit={handleSubmit}
                submitting={submitting}
                error={submitError}
                onGoToIdentity={goToIdentity}
              />
            )}

            {isStepper && (
              <div className="mt-2 space-y-1.5">
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => moveFocus(-1)}
                    disabled={stepperIndex <= 0}
                    className="rounded-md border border-line py-2 text-[13px] font-medium text-ink-700 hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    ← 上一筆
                  </button>
                  <button
                    type="button"
                    onClick={() => moveFocus(1)}
                    disabled={stepperIndex >= shown.length - 1}
                    className="rounded-md border border-line py-2 text-[13px] font-medium text-ink-700 hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    下一筆 →
                  </button>
                </div>
                <button
                  type="button"
                  onClick={() => setFocusedId(null)}
                  className="w-full rounded-md py-1.5 text-[12px] text-ink-500 hover:text-ink-700"
                >
                  結束逐項覆核，回到清單
                </button>
              </div>
            )}
          </div>
        );
      })}
      </div>
      <p className="text-[11px] text-ink-400">鍵盤：J／K 上下筆・A／T／D 選判定・Enter 送出並前往下一筆</p>
      {deck}
    </div>
  );
}
