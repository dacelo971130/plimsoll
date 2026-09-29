import { useState } from 'react';
import { hasReviewerIdentity } from '../../state/useReviewerIdentity';
import type { ChainSummary, ReviewVerdict } from '../../types';
import { BatchAnalysisBar } from './BatchAnalysisBar';
import { IdentityHint } from '../IdentityHint';
import { RiskPill } from './RiskPill';

interface ChainReviewEvent {
  event_type: string;
  human_verdict?: string;
  reviewer_name?: string;
  approval_role_label_snapshot?: string;
  reviewer_note?: string;
  created_at?: string;
}

interface ChainMessageProps {
  chain: ChainSummary;
  reviewerName: string;
  approvalRoleCode: string;
  onReview: (submission: { human_verdict: ReviewVerdict; reviewer_name: string; approval_role_code: string; reviewer_note?: string }) => void;
  onGoToIdentity: () => void;
}

const VERDICT_OPTIONS: { value: ReviewVerdict; label: string }[] = [
  { value: 'CONFIRMED', label: '確認為刻意調整' },
  { value: 'TRACK', label: '列入追蹤' },
  { value: 'REJECTED', label: '不採納此判讀' },
];

// W8: 鏈式檢視 — 對照計劃 §02/§03，一條鏈只需要一次判斷，不必對每個 pairwise
// session 各簽一次（CHAIN_REVIEW 事件永遠被 fold_review_state() 排除，見
// backend/storage/events.py）。
export function ChainMessage({
  chain,
  reviewerName,
  approvalRoleCode,
  onReview,
  onGoToIdentity,
}: ChainMessageProps) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const driftFindings = chain.drift_report.filter((f) => f.is_drift);
  const otherFindings = chain.drift_report.filter((f) => !f.is_drift);
  const chainReviews = chain.review_events.filter((e) => e.event_type === 'CHAIN_REVIEW') as unknown as ChainReviewEvent[];
  const lastReview = chainReviews.length > 0 ? chainReviews[chainReviews.length - 1] : null;

  const canReview = hasReviewerIdentity(reviewerName, approvalRoleCode) && !busy;

  async function submit(verdict: ReviewVerdict) {
    setBusy(true);
    try {
      await onReview({
        human_verdict: verdict,
        reviewer_name: reviewerName,
        approval_role_code: approvalRoleCode,
        reviewer_note: note,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-line bg-surface p-4 shadow-[var(--sh-1)]">
      <h3 className="text-[13.5px] font-semibold text-ink-900">鏈式趨勢分析</h3>
      <p className="mt-1 text-[12px] text-ink-500">
        {chain.ordered_versions.join(' → ')} · {chain.adjacent_session_ids.length} 次相鄰比對 +{' '}
        {chain.anchor_session_ids.length} 次錨點比對（v1→v2 共用一次）
      </p>

      {driftFindings.length > 0 && (
        <div className="mt-3 space-y-2">
          {driftFindings.map((f) => (
            <div key={f.canonical_param} className="rounded-lg border border-high-200 bg-high-50 p-2.5">
              <div className="flex items-center gap-2">
                <RiskPill risk={f.risk} />
                <span className="text-[12.5px] font-medium text-ink-900">{f.canonical_param}</span>
                <span className="ml-auto text-[11px] text-ink-500">
                  {f.first_version} → {f.last_version} · {f.series_length} 個版本
                </span>
              </div>
              <p className="mt-1 text-[12px] text-ink-700">{f.rationale}</p>
              <p className="mt-1 text-[11.5px] text-ink-500">
                累積變化 {(f.total_delta_ratio * 100).toFixed(1)}%（{f.total_delta > 0 ? '+' : ''}
                {f.total_delta.toFixed(2)}） · 建議：{f.recommended_action}
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1 text-[11px] text-ink-500">
                {f.series.map((p) => (
                  <span key={p.version} className="rounded border border-line bg-surface px-1.5 py-0.5">
                    {p.version}: {p.value}
                    {p.unit}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {otherFindings.length > 0 && (
        <details className="mt-2.5">
          <summary className="cursor-pointer text-[11.5px] text-ink-500">
            其餘 {otherFindings.length} 條追蹤參數（未達累積漂移門檻）
          </summary>
          <div className="mt-1.5 space-y-1">
            {otherFindings.map((f) => (
              <div key={f.canonical_param} className="flex items-center gap-2 text-[11.5px] text-ink-500">
                <RiskPill risk={f.risk} />
                <span>{f.canonical_param}</span>
                <span className="ml-auto">
                  {f.series_length} 點 · 累積 {(f.total_delta_ratio * 100).toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        </details>
      )}

      {driftFindings.length === 0 && otherFindings.length === 0 && (
        <p className="mt-3 text-[12px] text-ink-500">此鏈未偵測到任何可追蹤的數值型參數。</p>
      )}

      <BatchAnalysisBar chainId={chain.chain_id} />

      <div className="mt-3 border-t border-line pt-3">
        <h4 className="text-[12px] font-medium text-ink-700">鏈級簽核</h4>
        {lastReview ? (
          <p className="mt-1 rounded-md border border-low-200 bg-low-50 px-2.5 py-1.5 text-[12px] text-low-700">
            {lastReview.reviewer_name}（{lastReview.approval_role_label_snapshot}）已判定：
            {VERDICT_OPTIONS.find((o) => o.value === lastReview.human_verdict)?.label ?? lastReview.human_verdict}
            {lastReview.reviewer_note ? ` — ${lastReview.reviewer_note}` : ''}
          </p>
        ) : (
          <p className="mt-1 text-[11.5px] text-ink-500">
            尚未對整條鏈下判斷 — 一次判斷即可涵蓋所有相鄰／錨點比對，不必逐一簽核。
          </p>
        )}

        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="覆核備註（選填，例如：累積調整已確認為刻意調整）"
          className="mt-2 w-full rounded-md border border-line bg-surface-2 px-2 py-1 text-[12px] text-ink-800"
        />
        <div className="mt-2 flex gap-1.5">
          {VERDICT_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              disabled={!canReview}
              onClick={() => submit(opt.value)}
              className="flex-1 rounded-md border border-line px-2 py-1 text-[12px] text-ink-700 hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-40"
            >
              {opt.label}
            </button>
          ))}
        </div>
        {!canReview && !busy && <IdentityHint onGo={onGoToIdentity} className="mt-1.5 text-[11.5px]" />}
      </div>
    </div>
  );
}
