import { useRef } from 'react';

interface ResizeHandleProps {
  /** Which edge of the panel this handle drags — 'left' means dragging the
   * handle moves the panel's LEFT border (used by a panel anchored on the
   * right side of the screen, e.g. the right rail), 'right' means it moves
   * the panel's RIGHT border (used by a panel anchored on the left, e.g.
   * the left rail). */
  edge: 'left' | 'right';
  width: number;
  onResize: (width: number) => void;
}

// A thin, hover-highlighted drag handle sitting on a panel's border. No
// resize infrastructure existed anywhere in the app before this (every rail/
// panel width was a hard-coded Tailwind arbitrary value) — this is the one
// reusable primitive both the left rail and right panel use.
export function ResizeHandle({ edge, width, onResize }: ResizeHandleProps) {
  const dragState = useRef<{ startX: number; startWidth: number } | null>(null);

  function handleMouseDown(e: React.MouseEvent) {
    e.preventDefault();
    dragState.current = { startX: e.clientX, startWidth: width };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    function onMouseMove(ev: MouseEvent) {
      if (!dragState.current) return;
      const delta = ev.clientX - dragState.current.startX;
      const signedDelta = edge === 'right' ? delta : -delta;
      onResize(dragState.current.startWidth + signedDelta);
    }

    function onMouseUp() {
      dragState.current = null;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    }

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      title="拖曳調整寬度"
      onMouseDown={handleMouseDown}
      className="group relative w-[3px] shrink-0 cursor-col-resize bg-line"
    >
      <div className="absolute inset-y-0 -left-1 -right-1 group-hover:bg-accent-soft" />
      <div className="absolute inset-y-0 left-0 w-[3px] group-hover:bg-ink-500" />
    </div>
  );
}
