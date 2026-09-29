import { hasReviewerIdentity } from '../../state/useReviewerIdentity';
import type { ReviewVerdict, RiskLevel } from '../../types';
import { IdentityHint } from '../IdentityHint';

const VERDICT_OPTIONS: { value: ReviewVerdict; label: string; key: string }[] = [
  { value: 'CONFIRMED', label: '✓ 已確認', key: 'A' },
  { value: 'TRACK', label: '◷ 需追蹤', key: 'T' },
  { value: 'REJECTED', label: '✕ 不採納', key: 'D' },
];

const RISK_OPTIONS: RiskLevel[] = ['High', 'Medium', 'Low'];

// lg = the 專注簽核 deck's enlarged card; same controls, bigger hit targets.
const SIZE = {
  md: {
    wrap: 'mt-3 space-y-2.5 pt-3',
    verdict: 'rounded-md py-1.5 text-[12.5px]',
    key: 'text-[10px]',
    label: 'text-[11.5px]',
    select: 'px-2 py-1 text-[12px]',
    note: 'px-2 py-1.5 text-[12px]',
    hint: 'text-[11.5px]',
    submit: 'rounded-md py-1.5 text-[12.5px]',
  },
  lg: {
    wrap: 'mt-6 space-y-3 pt-5',
    verdict: 'rounded-lg py-3 text-[15px]',
    key: 'text-[11px]',
    label: 'text-[13px]',
    select: 'px-3 py-1.5 text-[14px]',
    note: 'px-3 py-2 text-[14px]',
    hint: 'text-[13px]',
    submit: 'rounded-lg py-3 text-[15px]',
  },
};

interface ReviewBarProps {
  aiRisk: RiskLevel;
  draftVerdict: ReviewVerdict | null;
  draftRiskOverride: RiskLevel | null;
  draftNote: string;
  onVerdictChange: (v: ReviewVerdict) => void;
  onRiskOverrideChange: (r: RiskLevel | null) => void;
  onNoteChange: (n: string) => void;
  reviewerName: string;
  approvalRoleCode: string;
  onSubmit: () => void;
  submitting: boolean;
  error: string | null;
  size?: 'md' | 'lg';
  // Takes the reviewer to the 覆核人身分 block when it isn't filled in yet
  // (see IdentityHint / RightPanel.goToIdentity).
  onGoToIdentity: () => void;
}

// ui-spec §3.2 DiffCard 展開態 — "ReviewBar：三選一判定＋風險改判下拉（人工
// 覆蓋 AI 初判）＋覆核筆記＋「確認並前往下一筆」"。鍵盤 A/T/D 只改變下面的
// draftVerdict（見 DiffListMessage 的 keydown handler），Enter 才真正送出。
// plimsoll-subtraction-matrix.html 小win #06 — 覆核人姓名／核准角色不再每張
// 卡重填一次：身分在右欄頂端（RightPanel 的 ReviewerIdentityBar）填一次，這
// 裡只讀取，未填時顯示提示而不是輸入框。
export function ReviewBar({
  aiRisk,
  draftVerdict,
  draftRiskOverride,
  draftNote,
  onVerdictChange,
  onRiskOverrideChange,
  onNoteChange,
  reviewerName,
  approvalRoleCode,
  onSubmit,
  submitting,
  error,
  size = 'md',
  onGoToIdentity,
}: ReviewBarProps) {
  const z = SIZE[size];
  const identitySet = hasReviewerIdentity(reviewerName, approvalRoleCode);
  const canSubmit = draftVerdict !== null && identitySet && !submitting;

  return (
    <div className={`border-t border-line ${z.wrap}`}>
      <div className="flex gap-1.5">
        {VERDICT_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => onVerdictChange(opt.value)}
            aria-pressed={draftVerdict === opt.value}
            className={`flex-1 border font-medium ${z.verdict} ${
              draftVerdict === opt.value ? 'border-ink-800 bg-ink-800 text-on-accent' : 'border-line text-ink-600 hover:bg-accent-soft'
            }`}
          >
            {opt.label} <span className={`opacity-60 ${z.key}`}>{opt.key}</span>
          </button>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <label className={`text-ink-500 ${z.label}`}>風險改判</label>
        <select
          value={draftRiskOverride ?? ''}
          onChange={(e) => onRiskOverrideChange((e.target.value || null) as RiskLevel | null)}
          className={`rounded-md border border-line bg-surface text-ink-800 ${z.select}`}
        >
          <option value="">維持 AI 初判（{aiRisk}）</option>
          {RISK_OPTIONS.map((r) => (
            <option key={r} value={r}>
              改判為 {r}
            </option>
          ))}
        </select>
      </div>

      <textarea
        value={draftNote}
        onChange={(e) => onNoteChange(e.target.value)}
        placeholder="覆核筆記（選填）"
        rows={2}
        className={`w-full resize-none rounded-md border border-line bg-surface text-ink-800 ${z.note}`}
      />

      {!identitySet && (
        <IdentityHint onGo={onGoToIdentity} className={z.hint} />
      )}
      {error && <p className={`rounded-md border border-high-200 bg-high-50 px-2 py-1.5 text-high-700 ${z.hint}`}>{error}</p>}

      <button
        type="button"
        disabled={!canSubmit}
        onClick={onSubmit}
        className={`w-full bg-ink-800 font-medium text-on-accent disabled:cursor-not-allowed disabled:opacity-40 ${z.submit}`}
      >
        {submitting ? '送出中…' : '確認並前往下一筆 → (Enter)'}
      </button>
    </div>
  );
}
