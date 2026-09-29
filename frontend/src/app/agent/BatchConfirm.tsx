import { useMemo, useState } from 'react';
import { submitReviewEvent } from '../../lib/api';
import { hasReviewerIdentity } from '../../state/useReviewerIdentity';
import type { AgentSuggestion, DifferenceRecord, ReviewState, SessionSummary } from '../../types';
import { adoptedNote, VERDICT_LABEL } from './agentLabels';
import { IdentityHint } from '../IdentityHint';

interface BatchConfirmProps {
  sessionId: string;
  runId: string;
  suggestions: AgentSuggestion[];
  differences: DifferenceRecord[];
  reviewState: Record<string, ReviewState>;
  reviewerName: string;
  approvalRoleCode: string;
  onSessionUpdate: (session: SessionSummary) => void;
  onGoToIdentity: () => void;
}

// 批次確認 Agent 建議 (spec §4.4). Only Low/Medium differences with no human
// verdict yet qualify — a High must be opened and confirmed one by one.
// Every event is still written by the reviewer's own action, under their
// identity, through the same endpoint the ReviewBar uses, so server-side
// approval policies apply exactly as they would card by card.
export function BatchConfirm({
  sessionId,
  runId,
  suggestions,
  differences,
  reviewState,
  reviewerName,
  approvalRoleCode,
  onSessionUpdate,
  onGoToIdentity,
}: BatchConfirmProps) {
  const risk = useMemo(() => new Map(differences.map((d) => [d.id, d.ai_risk])), [differences]);
  const eligible = suggestions.filter(
    (s) => (risk.get(s.difference_id) === 'Low' || risk.get(s.difference_id) === 'Medium') && reviewState[s.difference_id]?.human_verdict == null,
  );
  const highCount = suggestions.filter((s) => risk.get(s.difference_id) === 'High').length;
  const [deselected, setDeselected] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  if (eligible.length === 0 && highCount === 0) return null;

  const selected = eligible.filter((s) => !deselected.has(s.difference_id));
  const identitySet = hasReviewerIdentity(reviewerName, approvalRoleCode);

  function toggle(id: string) {
    setDeselected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function confirmSelected() {
    setSubmitting(true);
    setErrors([]);
    const failed: string[] = [];
    for (const s of selected) {
      try {
        const result = await submitReviewEvent(sessionId, {
          difference_id: s.difference_id,
          human_verdict: s.verdict,
          risk_override: null,
          reviewer_name: reviewerName,
          approval_role_code: approvalRoleCode,
          reviewer_note: adoptedNote(runId),
        });
        onSessionUpdate(result.session);
      } catch (err) {
        failed.push(`${s.difference_id}：${err instanceof Error ? err.message : String(err)}`);
      }
    }
    setErrors(failed);
    setSubmitting(false);
  }

  return (
    <div className="space-y-2">
      <h4 className="text-[12.5px] font-semibold text-ink-800">批次確認建議（Low／Medium）</h4>
      {eligible.length > 0 ? (
        <ul className="space-y-1">
          {eligible.map((s) => (
            <li key={s.difference_id}>
              <label className="flex cursor-pointer items-start gap-2 rounded-md px-1 py-0.5 hover:bg-accent-soft">
                <input
                  type="checkbox"
                  checked={!deselected.has(s.difference_id)}
                  onChange={() => toggle(s.difference_id)}
                  className="mt-0.5"
                />
                <span className="text-[12px] text-ink-700">
                  <strong className="font-medium text-ink-900">{s.difference_id}</strong>{' '}
                  {VERDICT_LABEL[s.verdict]}・{s.reason}
                </span>
              </label>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[12px] text-ink-500">沒有可以批次確認的建議（Low／Medium 的差異都已經有人工判定）。</p>
      )}
      {highCount > 0 && <p className="text-[11.5px] text-ink-500">High 的建議不能批次確認，請逐筆展開差異卡確認（共 {highCount} 筆）。</p>}
      {!identitySet && eligible.length > 0 && <IdentityHint onGo={onGoToIdentity} />}
      {errors.length > 0 && (
        <ul className="rounded-md border border-high-200 bg-high-50 px-2 py-1.5 text-[11.5px] text-high-700">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {eligible.length > 0 && (
        <button
          type="button"
          disabled={!identitySet || submitting || selected.length === 0}
          onClick={() => void confirmSelected()}
          className="w-full rounded-md bg-ink-800 py-1.5 text-[12.5px] font-medium text-on-accent disabled:cursor-not-allowed disabled:opacity-40"
        >
          {submitting ? '送出中…' : `以我的身分確認勾選的 ${selected.length} 筆`}
        </button>
      )}
    </div>
  );
}
