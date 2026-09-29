import { charDiff } from '../../lib/charDiff';

// ui-spec §3.2 DiffCard 展開態 — "逐字級 diff：<del> 紅刪除線 / <ins> 綠加粗"。
// plimsoll-two-shell-spec.md §2 問題 1 — `side` is now optional: omitted, all
// three segment kinds render together in one merged passage (new/old side by
// side in the same sentence) instead of two columns each repeating the
// unchanged `equal` text. `side` is kept for any future caller that still
// needs a single-version-only rendering.
export function CharDiffText({
  oldText,
  newText,
  side,
  className = 'text-[13px] leading-relaxed',
}: {
  oldText: string;
  newText: string;
  side?: 'old' | 'new';
  // Type size/leading only — the 專注簽核 deck passes a larger one.
  className?: string;
}) {
  const segments = charDiff(oldText, newText);
  const relevant = side === undefined ? ['equal', 'del', 'ins'] : side === 'old' ? ['equal', 'del'] : ['equal', 'ins'];

  return (
    <p className={`text-ink-800 ${className}`}>
      {segments
        .filter((seg) => relevant.includes(seg.type))
        .map((seg, idx) =>
          seg.type === 'equal' ? (
            <span key={idx}>{seg.text}</span>
          ) : seg.type === 'del' ? (
            <del key={idx} style={{ color: 'var(--diff-del)', textDecorationColor: 'var(--diff-del)' }}>
              {seg.text}
            </del>
          ) : (
            <ins key={idx} style={{ color: 'var(--diff-add)', textDecoration: 'none', fontWeight: 600 }}>
              {seg.text}
            </ins>
          ),
        )}
    </p>
  );
}
