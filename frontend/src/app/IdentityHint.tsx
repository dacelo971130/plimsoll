// 2026-09-28 使用者回饋 — 「尚未填寫覆核人身分」 used to say 「請見右欄頂端」 and
// leave the reviewer to go find it. It is now a link-style button that takes
// them there: RightPanel's goToIdentity() closes whatever covers the panel
// (卡片模式, the export dialog), scrolls to the 覆核人身分 block, flashes it and
// focuses its first empty field. Every place that shows this hint (ReviewBar,
// ExportMessage, ChainMessage, the agent's BatchConfirm) uses this one
// component, so the wording and the behaviour never drift apart.
export function IdentityHint({ onGo, className = 'text-[11.5px]' }: { onGo: () => void; className?: string }) {
  return (
    <button
      type="button"
      onClick={onGo}
      className={`block text-left text-med-700 underline decoration-dotted underline-offset-2 hover:decoration-solid ${className}`}
    >
      尚未填寫覆核人身分，請前往填寫（點擊跳轉）。
    </button>
  );
}
