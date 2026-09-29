import { Sparkles } from 'lucide-react';
import type { AgentState } from '../../state/useAgent';
import type { FocusHintHandle } from '../../state/useFocusHints';
import type { AgentAnswer, AgentRun, DifferenceRecord, ReviewState, SessionSummary } from '../../types';
import { FocusHint } from '../FocusHint';
import { AgentBriefingView } from './AgentBriefingView';
import { AgentQA } from './AgentQA';
import { AiTag } from './AgentNotePanel';
import { BatchConfirm } from './BatchConfirm';

const CHAIN_SUGGESTED = ['溫度門檻是哪一版改的？為什麼？', '效率係數在各版之間怎麼變化？', 'v1.2 改了什麼、原因是什麼？'];

interface AgentSectionProps {
  agent: AgentState;
  // null = only a multi-version chain is open: the agent answers across the
  // chain (its v1 → vN comparison plus every version's pages), Q&A only —
  // no briefing or verdict prefill, since chain findings are signed in the
  // chain's own 鏈級簽核.
  session: SessionSummary | null;
  chainVersions?: string[];
  differences: DifferenceRecord[];
  reviewState: Record<string, ReviewState>;
  reviewerName: string;
  approvalRoleCode: string;
  onSessionUpdate: (session: SessionSummary) => void;
  onJumpToPage: (side: 'old' | 'new', pdfPage: number | null, differenceId?: string) => void;
  onFocusDifference: (id: string) => void;
  onGoToIdentity: () => void;
  // 專注提示, non-null only while RightPanel says this is the active stage.
  hint?: FocusHintHandle | null;
}

// 覆核 Agent (plimsoll-review-agent-spec.md §4) — button-triggered (定案),
// read-only, every claim verified server-side. The section doesn't exist
// unless the agent can actually run or has past results to show: no
// disabled placeholder for a missing key (不做假的).
export function AgentSection({
  agent,
  session,
  chainVersions,
  differences,
  reviewState,
  reviewerName,
  approvalRoleCode,
  onSessionUpdate,
  onJumpToPage,
  onFocusDifference,
  onGoToIdentity,
  hint,
}: AgentSectionProps) {
  const { available, briefing, answers, active, error } = agent;
  if (!available && !briefing && answers.length === 0 && !active) return null;

  if (!session) {
    return (
      <section className="space-y-3 rounded-xl border border-line bg-surface p-3 shadow-[var(--sh-1)]">
        <header className="flex items-center gap-1.5">
          <Sparkles size={14} className="text-ink-500" />
          <h3 className="text-[13px] font-semibold text-ink-800">覆核 Agent</h3>
          <AiTag />
        </header>
        <p className="text-[12.5px] text-ink-600">
          依多版本鏈{chainVersions && chainVersions.length > 0 ? `（${chainVersions[0]} → ${chainVersions[chainVersions.length - 1]}）` : ''}
          回答：可以問某個數值在哪一版改變、文件寫的原因是什麼。
        </p>
        {error && (
          <p role="alert" className="rounded-md border border-high-200 bg-high-50 px-2 py-1.5 text-[12px] text-high-700">
            {error}
          </p>
        )}
        <AgentQA
          answers={answers as AgentRun<AgentAnswer>[]}
          pending={active?.kind === 'question' ? active : null}
          canAsk={available}
          onAsk={agent.ask}
          onJumpToPage={onJumpToPage}
          suggested={CHAIN_SUGGESTED}
          interactive={false}
        />
      </section>
    );
  }

  const briefingRunning = active?.kind === 'briefing' ? active : null;
  const questionRunning = active?.kind === 'question' ? active : null;
  const result = briefing?.result ?? null;

  return (
    <section className="space-y-3 rounded-xl border border-line bg-surface p-3 shadow-[var(--sh-1)]">
      <header className="flex items-center gap-1.5">
        <Sparkles size={14} className="text-ink-500" />
        <h3 className="text-[13px] font-semibold text-ink-800">覆核 Agent</h3>
        <AiTag />
        {result && available && !active && (
          <button
            type="button"
            onClick={agent.startBriefing}
            className="ml-auto rounded-md border border-line px-2 py-1 text-[11.5px] text-ink-600 hover:bg-accent-soft"
          >
            重新準備
          </button>
        )}
      </header>

      {/* 2026-09-28 使用者回饋「AI 覆核功能也納入／不需要切這麼多功能按鈕」—
          自己的「請 Agent 準備覆核」主按鈕拿掉，改由 SemanticLayerBar 的
          「AI 語意建議」一次觸發（見那邊的 onStartAgentBriefing）。這裡的
          「重新準備」（下面 header 裡）留著，跑完一次以後想再跑一次還是要
          按得到。 */}
      {!result && !briefingRunning && available && (
        <div className="space-y-2">
          <p className="text-[12.5px] text-ink-600">
            Agent 會逐筆查證 High 與信心較低的差異，整理影響範圍、建議動作與覆核順序，並替差異預填建議判定。每個結論都附原文引用；判定仍由你決定。按上方「AI
            語意建議」開始。
          </p>
          {hint && <FocusHint hint={hint} />}
        </div>
      )}

      {briefingRunning && (
        <div className="space-y-1 text-[12px] text-ink-600" aria-live="polite">
          <p className="font-medium text-ink-800">Agent 查證中…（已完成 {briefingRunning.steps.length} 步）</p>
          <ol className="space-y-0.5">
            {briefingRunning.steps.slice(-6).map((s, i) => (
              <li key={i} className={s.ok ? 'text-ink-500' : 'text-med-700'}>
                · {s.label}
              </li>
            ))}
          </ol>
        </div>
      )}

      {error && (
        <p role="alert" className="rounded-md border border-high-200 bg-high-50 px-2 py-1.5 text-[12px] text-high-700">
          {error}
        </p>
      )}

      {result && briefing && (
        <details open className="group">
          <summary className="cursor-pointer select-none text-[12.5px] font-semibold text-ink-800">覆核簡報</summary>
          <div className="mt-2">
            <AgentBriefingView
              briefing={result}
              onJumpToPage={onJumpToPage}
              onFocusDifference={onFocusDifference}
              batch={
                result.suggestions.length > 0 ? (
                  <BatchConfirm
                    sessionId={session.session_id}
                    runId={briefing.run_id}
                    suggestions={result.suggestions}
                    differences={differences}
                    reviewState={reviewState}
                    reviewerName={reviewerName}
                    approvalRoleCode={approvalRoleCode}
                    onSessionUpdate={onSessionUpdate}
                    onGoToIdentity={onGoToIdentity}
                  />
                ) : null
              }
            />
          </div>
        </details>
      )}

      {(available || answers.length > 0) && (
        <div className="border-t border-line pt-3">
          <AgentQA
            answers={answers as AgentRun<AgentAnswer>[]}
            pending={questionRunning}
            canAsk={available}
            onAsk={agent.ask}
            onJumpToPage={onJumpToPage}
          />
        </div>
      )}
    </section>
  );
}
