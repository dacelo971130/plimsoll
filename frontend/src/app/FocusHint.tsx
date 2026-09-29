import { FOCUS_HINT_COPY, type FocusHintHandle } from '../state/useFocusHints';

interface FocusHintProps {
  hint: FocusHintHandle;
}

// 專注提示 — rendered inline next to its target by the caller; no overlay
// or positioned coach mark.
export function FocusHint({ hint }: FocusHintProps) {
  const lines = FOCUS_HINT_COPY[hint.stage];
  return (
    <div role="status" className="space-y-1.5 rounded-md border border-line bg-accent-soft px-3 py-2 text-[12.5px] text-ink-700">
      {lines.map((line, i) => (
        <p key={i}>{line}</p>
      ))}
      <div className="flex items-center gap-3 pt-0.5">
        <button
          type="button"
          onClick={hint.onAcknowledge}
          className="rounded-md border border-line bg-surface px-2.5 py-1 text-[12px] font-medium text-ink-700 hover:bg-accent-soft"
        >
          知道了
        </button>
        <button type="button" onClick={hint.onDisableAll} className="text-[11.5px] text-ink-500 underline hover:text-ink-800">
          不再顯示提示
        </button>
      </div>
    </div>
  );
}
