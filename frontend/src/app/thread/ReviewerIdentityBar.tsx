import { useEffect, useRef, useState, type RefObject } from 'react';
import { User } from 'lucide-react';
import { hasReviewerIdentity } from '../../state/useReviewerIdentity';
import type { ApprovalRole } from '../../types';

// plimsoll-subtraction-matrix.html 小win #06「覆核人身分填一次」— reviewerName/
// approvalRoleCode already persist via useReviewerIdentity; the UI didn't:
// ReviewBar／ExportMessage／ChainMessage each had their own editable copy, so
// the same two fields got typed up to three times per session. This is the
// ONE place that ever sets them; every consumer (list, card mode, export,
// chain) only reads.
//
// 2026-09-28 使用者回饋 — moved here from a local RightPanel.tsx function so
// it can be mounted twice off the same state: once (compact) in
// DiffListMessage's 待核准清單 title row, left of 卡片模式, and once (full)
// inside FocusReviewDeck's 卡片模式 header.
//
// `compact` collapses the whole thing into one small button (icon + name)
// that opens the same edit form in a popover, instead of its own full-width
// row — there's no room for the full bar next to 卡片模式 in that title row.
export function ReviewerIdentityBar({
  reviewerName,
  approvalRoleCode,
  approvalRoles,
  setReviewerName,
  setApprovalRoleCode,
  compact = false,
  containerRef,
}: {
  reviewerName: string;
  approvalRoleCode: string;
  approvalRoles: ApprovalRole[];
  setReviewerName: (name: string) => void;
  setApprovalRoleCode: (code: string) => void;
  compact?: boolean;
  // RightPanel's identityRef, for goToIdentity()'s scroll/flash/click — only
  // meaningful in compact mode (see DiffListMessage's usage); falls back to
  // a local ref so the non-compact FocusReviewDeck usage doesn't need one.
  containerRef?: RefObject<HTMLDivElement | null>;
}) {
  const isSet = hasReviewerIdentity(reviewerName, approvalRoleCode);
  const [editing, setEditing] = useState(false);
  const roleLabel = approvalRoles.find((r) => r.code === approvalRoleCode)?.label_zh ?? approvalRoleCode;
  const localRef = useRef<HTMLDivElement>(null);
  const popoverRef = containerRef ?? localRef;

  // Compact popover: click outside closes it. Opening it — by the toggle
  // button below, or by RightPanel's goToIdentity() clicking that same
  // button programmatically — always focuses the first empty field, taking
  // over what goToIdentity used to do itself by querying the DOM directly
  // (it can't reach into a form that isn't rendered yet).
  useEffect(() => {
    if (!compact || !editing) return;
    function onPointerDown(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) setEditing(false);
    }
    document.addEventListener('mousedown', onPointerDown);
    const focusTimer = window.setTimeout(() => {
      popoverRef.current
        ?.querySelector<HTMLInputElement | HTMLSelectElement>(reviewerName.trim() ? 'select' : 'input')
        ?.focus();
    }, 0);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      window.clearTimeout(focusTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compact, editing]);

  const editForm = (
    <div className="rounded-lg border border-line bg-surface-2 p-2.5">
      <div className="mb-1.5 text-[11.5px] font-medium text-ink-700">覆核人身分（填一次，之後每筆判定都用這個身分送出）</div>
      <div className="grid grid-cols-2 gap-2">
        <input
          value={reviewerName}
          onChange={(e) => setReviewerName(e.target.value)}
          placeholder="覆核人姓名"
          className="rounded-md border border-line bg-surface px-2 py-1 text-[12px] text-ink-800"
        />
        <select
          value={approvalRoleCode}
          onChange={(e) => setApprovalRoleCode(e.target.value)}
          className="rounded-md border border-line bg-surface px-2 py-1 text-[12px] text-ink-800"
        >
          <option value="">選擇核准角色…</option>
          {approvalRoles.map((role) => (
            <option key={role.code} value={role.code}>
              {role.label_zh.includes(role.label_en) ? role.label_zh : `${role.label_zh}（${role.label_en}）`}
            </option>
          ))}
        </select>
      </div>
      {isSet && (
        <button type="button" onClick={() => setEditing(false)} className="mt-1.5 text-[11.5px] text-ink-500 hover:text-ink-700">
          完成
        </button>
      )}
    </div>
  );

  if (compact) {
    return (
      <div ref={popoverRef} className="relative shrink-0">
        <button
          type="button"
          onClick={() => setEditing((e) => !e)}
          aria-expanded={editing}
          className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[12px] font-medium text-ink-700 hover:bg-accent-soft"
        >
          <User size={13} />
          <span className="max-w-[110px] truncate">{isSet ? `${reviewerName} 覆核` : '設定覆核人'}</span>
        </button>
        {editing && <div className="absolute right-0 top-full z-20 mt-1.5 w-[260px]">{editForm}</div>}
      </div>
    );
  }

  if (isSet && !editing) {
    return (
      <div className="flex items-center justify-between gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-[12.5px] text-ink-700">
        <span>
          以 <strong className="font-medium text-ink-900">{reviewerName}</strong>（{roleLabel}）覆核
        </span>
        <button type="button" onClick={() => setEditing(true)} className="shrink-0 text-ink-500 hover:text-ink-800">
          變更
        </button>
      </div>
    );
  }

  return editForm;
}
