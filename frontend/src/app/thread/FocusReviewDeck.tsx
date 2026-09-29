import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import type { AgentNote } from '../../state/useAgent';
import type { ApprovalRole, DifferenceRecord, ReviewState } from '../../types';
import { AgentNotePanel } from '../agent/AgentNotePanel';
import { ChangeDelta, DiffReadout, DrawingRegions, SemanticSuggestionPanel, SourceColumns } from './DiffDetails';
import { pageLabel, VERDICT_BADGE, type ReviewDraft } from './diffFormat';
import { ReviewBar } from './ReviewBar';
import { ReviewerIdentityBar } from './ReviewerIdentityBar';
import { RiskPill } from './RiskPill';
import { RISK_STRIPE } from './riskStyle';

// Deck-only page-label formatting — see the identical copy (and its full
// rationale) next to DiffDetails.tsx's SourceColumns, which needs the same
// thing. Kept as a local, unexported duplicate rather than a shared export:
// a plain-function export placed alongside DiffDetails.tsx's component
// exports breaks Fast Refresh there.
function deckPageLabel(span: DifferenceRecord['old']): string {
  const label = pageLabel(span);
  return /^\d+$/.test(label) ? `p.${label}` : label;
}

interface FocusReviewDeckProps {
  cards: DifferenceRecord[];
  currentId: string | null;
  // Which way the last move went — the incoming card slides in from that side.
  direction: 1 | -1;
  // Set once the LAST card's verdict is sent: shows the end-of-round card.
  done: boolean;
  reviewState: Record<string, ReviewState>;
  // 覆核 Agent notes (spec §4.4) — its suggested verdict already prefills the
  // shared draft via DiffListMessage.focus(); the deck shows the reasoning so a
  // one-key Enter never confirms a suggestion the reviewer hasn't read.
  agentNotes?: Record<string, AgentNote>;
  onJumpToPage: (side: 'old' | 'new', pdfPage: number | null, differenceId?: string) => void;
  draft: ReviewDraft;
  onDraftChange: (patch: Partial<ReviewDraft>) => void;
  reviewerName: string;
  approvalRoleCode: string;
  // 2026-09-28 使用者回饋「卡牌模式也要顯示」覆核人身分 — same state RightPanel
  // already owns, just rendered a second time in this overlay's own header.
  approvalRoles: ApprovalRole[];
  setReviewerName: (name: string) => void;
  setApprovalRoleCode: (code: string) => void;
  onSubmit: () => void;
  submitting: boolean;
  error: string | null;
  onPrev: () => void;
  onNext: () => void;
  onClose: () => void;
  onGoToIdentity: () => void;
}

function NavButton({ dir, disabled, onClick }: { dir: 'prev' | 'next'; disabled: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={dir === 'prev' ? '上一筆' : '下一筆'}
      className="hidden h-12 w-12 shrink-0 items-center justify-center rounded-full border border-line bg-surface text-ink-700 shadow-[var(--sh-2)] hover:bg-accent-soft disabled:opacity-30 sm:flex"
    >
      {dir === 'prev' ? <ChevronLeft size={22} /> : <ChevronRight size={22} />}
    </button>
  );
}

// 2026-09-27 使用者回饋「專注簽核模式（像英文單字卡牌那樣），卡牌置中，文字
// 與卡牌都放大」— one difference at a time on a centred, enlarged card, over a
// full-screen backdrop that hides everything else. It is only a different
// view of DiffListMessage's own state: the same focused id, the same draft,
// the same submit and J/K/A/T/D/Enter keys (plus ←/→ and Esc), so opening or
// leaving it mid-review never loses a half-made verdict.
export function FocusReviewDeck({
  cards,
  currentId,
  direction,
  done,
  reviewState,
  agentNotes,
  onJumpToPage,
  draft,
  onDraftChange,
  reviewerName,
  approvalRoleCode,
  approvalRoles,
  setReviewerName,
  setApprovalRoleCode,
  onSubmit,
  submitting,
  error,
  onPrev,
  onNext,
  onClose,
  onGoToIdentity,
}: FocusReviewDeckProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  // Pull keyboard focus off the 「專注簽核」 button that opened this: left
  // there, the next Enter (meant as 「送出」) would also re-click it.
  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  const index = Math.max(0, cards.findIndex((c) => c.id === currentId));
  const d = cards[index];
  const reviewed = cards.filter((c) => reviewState[c.id]?.human_verdict != null).length;
  const remaining = cards.length - index - 1;
  const progress = done ? 100 : ((index + 1) / cards.length) * 100;

  const state = d ? reviewState[d.id] : undefined;
  const displayRisk = d ? (draft.riskOverride ?? d.ai_risk) : 'Low';
  const isDrawing = d?.kind === 'drawing';

  return createPortal(
    <div
      ref={dialogRef}
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-label="卡片模式"
      className="deck-fade fixed inset-0 z-50 flex flex-col bg-canvas/95 outline-none backdrop-blur-sm"
    >
      <div className="mx-auto flex w-full max-w-[920px] flex-wrap items-center gap-x-3 gap-y-1 px-4 pt-4">
        <span className="text-[16px] font-semibold text-ink-900">卡片模式</span>
        <span className="text-[14px] tabular-nums text-ink-500">
          第 {index + 1}／{cards.length} 筆
        </span>
        <span className="ml-auto text-[13px] text-ink-500">
          已覆核 <strong className="font-semibold tabular-nums text-ink-800">{reviewed}</strong>／{cards.length}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-[13px] text-ink-600 hover:bg-accent-soft"
        >
          <X size={15} /> 離開（Esc）
        </button>
      </div>
      <div className="mx-auto mt-2 w-full max-w-[920px] px-4">
        <ReviewerIdentityBar
          reviewerName={reviewerName}
          approvalRoleCode={approvalRoleCode}
          approvalRoles={approvalRoles}
          setReviewerName={setReviewerName}
          setApprovalRoleCode={setApprovalRoleCode}
        />
      </div>
      <div className="mx-auto mt-3 w-full max-w-[920px] px-4">
        <div className="h-1.5 overflow-hidden rounded-full bg-line">
          <div className="h-full rounded-full bg-ink-800 transition-[width] duration-300" style={{ width: `${progress}%` }} />
        </div>
      </div>

      <div className="flex min-h-0 flex-1 justify-center overflow-y-auto px-4 pb-4 pt-6">
        <div className="my-auto flex w-full max-w-[920px] items-center gap-4">
          <NavButton dir="prev" disabled={index === 0 && !done} onClick={onPrev} />

          <div className="relative min-w-0 flex-1 pb-6">
            {/* The rest of the deck peeking out underneath — purely visual.
                top-0/bottom-6 matches the real card (the wrapper's pb-6 is
                the room they peek into), and origin-bottom keeps the shrink
                from pulling their bottom edge back up under the card. */}
            {!done && remaining > 1 && (
              <div
                aria-hidden
                className="absolute inset-x-0 top-0 bottom-6 origin-bottom translate-y-6 scale-[0.92] rounded-2xl border border-line bg-surface opacity-70 shadow-[var(--sh-2)]"
              />
            )}
            {!done && remaining > 0 && (
              <div
                aria-hidden
                className="absolute inset-x-0 top-0 bottom-6 origin-bottom translate-y-3 scale-[0.96] rounded-2xl border border-line bg-surface shadow-[var(--sh-2)]"
              />
            )}

            {done || !d ? (
              <div className="deck-in-next relative rounded-2xl border border-line bg-surface p-10 text-center shadow-[var(--sh-3)]">
                <div className="text-[22px] font-semibold text-ink-900">這一輪 {cards.length} 筆都看過了</div>
                <p className="mt-2 text-[15px] text-ink-600">
                  已覆核 {reviewed}／{cards.length}
                  {reviewed < cards.length && `，還有 ${cards.length - reviewed} 筆沒有送出判定`}
                </p>
                <div className="mt-6 flex justify-center gap-2">
                  <button
                    type="button"
                    onClick={onPrev}
                    className="rounded-lg border border-line px-4 py-2.5 text-[14px] font-medium text-ink-700 hover:bg-accent-soft"
                  >
                    ← 回上一筆
                  </button>
                  <button
                    type="button"
                    onClick={onClose}
                    className="rounded-lg bg-ink-800 px-4 py-2.5 text-[14px] font-medium text-on-accent hover:opacity-90"
                  >
                    回到清單
                  </button>
                </div>
              </div>
            ) : (
              // Keyed on the card id: every move remounts it, replaying the
              // slide-in from the side the move came from. Layout follows
              // the product website's .diffcard format (2026-09-28 使用者
              // 指示採用網站卡片格式), scaled up ~1.3–1.5× for the deck's
              // own "卡牌置中，文字與卡牌都放大": overflow-hidden so the
              // head strip's own background respects the card's rounded
              // corners, while border-l-8/RISK_STRIPE stays on the article
              // itself so the risk stripe still runs the full height,
              // through the head strip too.
              <article
                key={d.id}
                className={`${direction === 1 ? 'deck-in-next' : 'deck-in-prev'} relative overflow-hidden rounded-2xl border border-l-8 border-line bg-surface shadow-[var(--sh-3)] ${RISK_STRIPE[displayRisk]}`}
              >
                {/* dc-head: mono cite left ("D03 · 舊版 p.12 → 新版 p.14"), risk pill right. */}
                <div className="flex items-center justify-between gap-3 border-b border-line bg-accent-soft px-6 py-4 sm:px-8">
                  <span className="font-mono text-[16px] text-ink-800">
                    {d.id} · 舊版 {deckPageLabel(d.old)} → 新版 {deckPageLabel(d.new)}
                  </span>
                  <RiskPill risk={displayRisk} size="lg" />
                </div>

                <div className="p-6 sm:p-8">
                  {/* dc-body h4: d.affected is the section heading affected by the
                      change and is usually present, but comparison.py falls back to
                      `""` when neither the old nor new page has a heading
                      (`affected = new_page.heading or old_page.heading or ""`) — in
                      that case fall back to the explanation, which classify() always
                      populates, so the card never shows a blank subject line. */}
                  <h4 className="line-clamp-2 text-[19px] font-semibold text-ink-900">{d.affected || d.explanation}</h4>

                  <div className="mt-2.5 flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-line px-2.5 py-1 text-[13px] text-ink-600">{d.change_type}</span>
                    {isDrawing && (
                      <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[13px] text-ink-600">工程圖</span>
                    )}
                    {d.component_ref && (
                      <span className="rounded-full border border-line px-2.5 py-1 text-[13px] text-ink-600">{d.component_ref}</span>
                    )}
                    <span className="text-[13px] text-ink-400">信心 {d.ai_confidence}</span>
                    {state?.human_verdict && (
                      <span className="rounded-full border border-low-200 bg-low-50 px-2.5 py-1 text-[13px] text-low-700">
                        {VERDICT_BADGE[state.human_verdict]} · {state.reviewer_name}
                      </span>
                    )}
                  </div>

                  {!isDrawing && <ChangeDelta d={d} />}
                  {isDrawing ? <DrawingRegions d={d} /> : <SourceColumns d={d} />}
                  {!isDrawing && <SemanticSuggestionPanel d={d} size="lg" />}
                  {/* AgentNotePanel only has the list's md sizes; zoom scales
                      the whole panel (text, pills, citation links) to the
                      deck's type size instead of forking a lg copy of it. */}
                  <div style={{ zoom: 1.25 }}>
                    <AgentNotePanel
                      differenceId={d.id}
                      note={agentNotes?.[d.id]}
                      prefilled={state?.human_verdict == null}
                      onJumpToPage={onJumpToPage}
                    />
                  </div>
                  <DiffReadout d={d} size="lg" />

                  <ReviewBar
                    size="lg"
                    aiRisk={d.ai_risk}
                    draftVerdict={draft.verdict}
                    draftRiskOverride={draft.riskOverride}
                    draftNote={draft.note}
                    onVerdictChange={(v) => onDraftChange({ verdict: v })}
                    onRiskOverrideChange={(r) => onDraftChange({ riskOverride: r })}
                    onNoteChange={(n) => onDraftChange({ note: n })}
                    reviewerName={reviewerName}
                    approvalRoleCode={approvalRoleCode}
                    onSubmit={onSubmit}
                    submitting={submitting}
                    error={error}
                    onGoToIdentity={onGoToIdentity}
                  />
                </div>
              </article>
            )}
          </div>

          <NavButton dir="next" disabled={done || index >= cards.length - 1} onClick={onNext} />
        </div>
      </div>

      {/* Phone width: the side arrows are hidden, so the same two moves
          live in a bottom row instead. */}
      <div className="grid grid-cols-2 gap-2 px-4 pb-2 sm:hidden">
        <button
          type="button"
          onClick={onPrev}
          disabled={index === 0 && !done}
          className="rounded-lg border border-line bg-surface py-2.5 text-[14px] font-medium text-ink-700 disabled:opacity-30"
        >
          ← 上一筆
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={done || index >= cards.length - 1}
          className="rounded-lg border border-line bg-surface py-2.5 text-[14px] font-medium text-ink-700 disabled:opacity-30"
        >
          下一筆 →
        </button>
      </div>
      <p className="hidden px-4 pb-4 text-center text-[12.5px] text-ink-400 sm:block">
        ← → 或 J／K 換筆・A／T／D 選判定・Enter 送出並前往下一筆・Esc 離開
      </p>
    </div>,
    document.body,
  );
}
