export interface DiffSegment {
  type: 'equal' | 'del' | 'ins';
  text: string;
}

// ui-spec §3.2 DiffCard 展開態 — "逐字級 diff：<del> 紅刪除線 / <ins> 綠加粗"。
// Classic LCS dynamic programming over individual characters (not words —
// Chinese has no whitespace word boundaries). Sentences here are short
// (tens of characters), so the O(n·m) table is trivial cost.
export function charDiff(oldText: string, newText: string): DiffSegment[] {
  const a = Array.from(oldText);
  const b = Array.from(newText);
  const n = a.length;
  const m = b.length;

  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const segments: DiffSegment[] = [];
  function push(type: DiffSegment['type'], ch: string) {
    const last = segments[segments.length - 1];
    if (last && last.type === type) last.text += ch;
    else segments.push({ type, text: ch });
  }

  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      push('equal', a[i]);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      push('del', a[i]);
      i++;
    } else {
      push('ins', b[j]);
      j++;
    }
  }
  while (i < n) push('del', a[i++]);
  while (j < m) push('ins', b[j++]);

  return segments;
}
