import { useEffect, useState } from 'react';
import { Check } from 'lucide-react';
import { submitReviewEvent } from '../../lib/api';
import { hasReviewerIdentity } from '../../state/useReviewerIdentity';
import type { DifferenceRecord, ReviewState, RiskLevel, SessionSummary } from '../../types';
import type { RiskFilter } from './DiffListMessage';
import { RISK_FILL } from './riskStyle';

interface BulkReviewButtonProps {
  sessionId: string;
  differences: DifferenceRecord[];
  reviewState: Record<string, ReviewState>;
  filter: RiskFilter;
  reviewerName: string;
  approvalRoleCode: string;
  onSessionUpdate: (session: SessionSummary) => void;
}

// 批次覆核 — 2026-09-28 使用者回饋。同一顆鍵、位置固定在覆核人身分旁邊，行為
// 跟著下方風險篩選卡目前選的等級走（不另外加一組設定）：
//   Low    — 不提示，點一下直接送出。
//   Medium — 點開一個小面板要求確認，再次點主鍵＝取消（面板關掉，什麼都不送）。
//   High   — 同 Medium，但送出前強制填理由（可勾「統一理由」或逐筆各填）。
// 這是刻意推翻 plimsoll-review-agent-spec.md §4.4「High 不能批次」的例外——那
//條規則管的是 Agent 建議觸發的 BatchConfirm.tsx，這裡是另一條、由使用者本輪
// 明確要求開的路（見該文件同日附註）；BatchConfirm.tsx 本身不受影響，仍然排除
// High。跟 BatchConfirm 一樣，每一筆都各自呼叫 submitReviewEvent、各自過伺服器
// 端角色/風險授權檢查——沒有新增批次後端 API。
// 「批次取消」是取消「面板裡還沒送出的這次批次」，不是撤銷已經送出的覆核事件
// ——覆核事件本身是只能新增、不能覆寫的稽核紀錄（architecture-decisions-A-B.md
// §19），已送出的判定要改就跟平常一樣，展開那張卡用 ReviewBar 重新送一次。
export function BulkReviewButton({
  sessionId,
  differences,
  reviewState,
  filter,
  reviewerName,
  approvalRoleCode,
  onSessionUpdate,
}: BulkReviewButtonProps) {
  const tier: RiskLevel | null = filter === 'All' ? null : filter;
  const tierDiffs = tier ? differences.filter((d) => d.ai_risk === tier) : [];
  const eligible = tierDiffs.filter((d) => reviewState[d.id]?.human_verdict == null);
  const allDone = tier !== null && tierDiffs.length > 0 && eligible.length === 0;
  const identitySet = hasReviewerIdentity(reviewerName, approvalRoleCode);

  const [open, setOpen] = useState(false);
  const [deselected, setDeselected] = useState<Set<string>>(new Set());
  const [useSharedReason, setUseSharedReason] = useState(true);
  const [sharedReason, setSharedReason] = useState('');
  const [perItemReason, setPerItemReason] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  // 切換風險篩選＝換了作用範圍，任何還沒送出的面板狀態都不該沿用到新的等級。
  useEffect(() => {
    setOpen(false);
    setDeselected(new Set());
    setSharedReason('');
    setPerItemReason({});
    setErrors([]);
  }, [tier]);

  if (tier === null) {
    return (
      <button
        type="button"
        disabled
        title="請先在下方篩選卡選一個風險等級（High／Medium／Low），才能批次覆核"
        className="inline-flex shrink-0 items-center gap-1 rounded-md border border-line px-2 py-1 text-[12px] font-medium text-ink-400"
      >
        批次覆核
      </button>
    );
  }

  const selected = eligible.filter((d) => !deselected.has(d.id));
  const highReasonsFilled =
    tier !== 'High' ||
    (useSharedReason ? sharedReason.trim() !== '' : selected.length > 0 && selected.every((d) => (perItemReason[d.id] ?? '').trim() !== ''));

  async function submitAll(note: (id: string) => string) {
    setSubmitting(true);
    setErrors([]);
    const failed: string[] = [];
    for (const d of selected) {
      try {
        const result = await submitReviewEvent(sessionId, {
          difference_id: d.id,
          human_verdict: 'CONFIRMED',
          risk_override: null,
          reviewer_name: reviewerName,
          approval_role_code: approvalRoleCode,
          reviewer_note: note(d.id),
        });
        onSessionUpdate(result.session);
      } catch (err) {
        failed.push(`${d.id}：${err instanceof Error ? err.message : String(err)}`);
      }
    }
    setErrors(failed);
    setSubmitting(false);
    if (failed.length === 0) setOpen(false);
  }

  function handleMainClick() {
    if (allDone || submitting) return;
    if (tier === 'Low') {
      void submitAll(() => '批次覆核（Low，未逐筆檢視原文）');
      return;
    }
    setOpen((o) => !o); // 再次點擊＝取消：面板關掉，尚未送出的一律不算數
  }

  function toggleDeselect(id: string) {
    setDeselected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={handleMainClick}
        disabled={allDone || submitting || (!identitySet && tier === 'Low')}
        aria-label={allDone ? '已批次覆核' : '批次覆核'}
        title={!identitySet ? '尚未填寫覆核人身分，請見上方' : undefined}
        className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12px] font-medium disabled:cursor-not-allowed disabled:opacity-60 ${RISK_FILL[tier]}`}
      >
        {/* Decorative only — a real <input> nested in a <button> is invalid
            interactive-in-interactive markup and was hijacking the button's
            accessible name (browser fell back to the `title` text instead of
            this label). aria-hidden + the button's own aria-label above are
            the real accessibility surface; this is just the checked-mark
            visual "checkbox 打勾辨識" the user asked for. */}
        <span aria-hidden="true" className="flex h-3 w-3 shrink-0 items-center justify-center rounded-sm border border-current">
          {allDone && <Check size={10} strokeWidth={3} />}
        </span>
        {allDone ? '已批次覆核' : '批次覆核'}
      </button>

      {!open && errors.length === 0 && !identitySet && tier !== 'Low' && (
        <p className="absolute left-0 top-full mt-1 w-56 text-[11px] text-med-700">尚未填寫覆核人身分，請見上方。</p>
      )}

      {open && (
        // left-0, not right-0: this button sits near the LEFT edge of its
        // header row (設定覆核人／卡片模式 are to its right), and the right
        // panel column can be narrow when the PDF preview is open. Anchoring
        // right-0 pushed this w-72 panel's left edge past the column's own
        // left boundary — the column's overflow-y-auto forces overflow-x to
        // auto too (CSS spec: an axis can't stay `visible` once its pair
        // isn't), so the overflowing part was clipped from both paint AND
        // hit-testing. Checkboxes in the clipped zone looked present but
        // never received clicks, and a click landing on that same screen
        // point instead fell through to whatever diff card sat underneath —
        // its "查看" button, which jumps the PDF preview to that page.
        <div className="absolute left-0 top-full z-10 mt-1 w-72 space-y-2 rounded-lg border border-line bg-surface p-3 shadow-[var(--sh-2)]">
          <div className="text-[12.5px] font-medium text-ink-800">一次核准 {selected.length} 筆 {tier} 風險差異？</div>
          <ul className="max-h-32 space-y-1.5 overflow-y-auto">
            {eligible.map((d) => (
              <li key={d.id}>
                <label className="flex items-start gap-2 text-[12px] text-ink-700">
                  <input type="checkbox" checked={!deselected.has(d.id)} onChange={() => toggleDeselect(d.id)} className="mt-0.5" />
                  <span>
                    <strong className="font-medium text-ink-900">{d.id}</strong>：{d.explanation}
                  </span>
                </label>
                {tier === 'High' && !useSharedReason && !deselected.has(d.id) && (
                  <input
                    value={perItemReason[d.id] ?? ''}
                    onChange={(e) => setPerItemReason((p) => ({ ...p, [d.id]: e.target.value }))}
                    placeholder="這筆的核准理由（必填）"
                    className="mt-1 w-full rounded-md border border-line bg-surface-2 px-2 py-1 text-[11.5px] text-ink-800"
                  />
                )}
              </li>
            ))}
          </ul>

          {tier === 'High' && (
            <div className="space-y-1.5 border-t border-line pt-2">
              <label className="flex items-center gap-1.5 text-[11.5px] text-ink-600">
                <input type="checkbox" checked={useSharedReason} onChange={(e) => setUseSharedReason(e.target.checked)} />
                所有筆用同一個理由
              </label>
              {useSharedReason && (
                <textarea
                  value={sharedReason}
                  onChange={(e) => setSharedReason(e.target.value)}
                  placeholder="核准理由（必填，套用到勾選的每一筆）"
                  rows={2}
                  className="w-full rounded-md border border-line bg-surface-2 px-2 py-1 text-[11.5px] text-ink-800"
                />
              )}
            </div>
          )}

          {!identitySet && <p className="text-[11.5px] text-med-700">尚未填寫覆核人身分，請見上方。</p>}
          {errors.length > 0 && (
            <ul className="rounded-md border border-high-200 bg-high-50 px-2 py-1.5 text-[11px] text-high-700">
              {errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}

          <div className="flex gap-1.5">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="flex-1 rounded-md border border-line py-1.5 text-[12px] text-ink-600 hover:bg-accent-soft"
            >
              取消
            </button>
            <button
              type="button"
              disabled={!identitySet || submitting || selected.length === 0 || !highReasonsFilled}
              onClick={() =>
                void submitAll((id) =>
                  tier === 'High' ? (useSharedReason ? sharedReason : (perItemReason[id] ?? '')) : `批次覆核（${tier}）`,
                )
              }
              className="flex-1 rounded-md bg-ink-800 py-1.5 text-[12px] font-medium text-on-accent disabled:cursor-not-allowed disabled:opacity-40"
            >
              {submitting ? '送出中…' : `核准 ${selected.length} 筆`}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
