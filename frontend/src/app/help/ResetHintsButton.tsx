import { useState } from 'react';
import { resetFocusHints } from '../../state/useFocusHints';

// A real control, unlike helpBlocks' <Ui> label chips.
export function ResetHintsButton() {
  const [justReset, setJustReset] = useState(false);

  function handleClick() {
    resetFocusHints();
    setJustReset(true);
    window.setTimeout(() => setJustReset(false), 2500);
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={handleClick}
        className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px] font-medium text-ink-700 hover:bg-accent-soft"
      >
        重新顯示操作提示
      </button>
      {justReset && <span className="text-[12px] text-ink-500">已重設，提示會再次出現。</span>}
    </div>
  );
}
