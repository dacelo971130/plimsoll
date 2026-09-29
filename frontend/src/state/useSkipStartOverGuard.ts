import { useState } from 'react';

const STORAGE_KEY = 'plimsoll.skipStartOverGuard.v1';

function load(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

// 2026-09-28 使用者回饋 —「＋ 開始新的比對」確認防呆的「不再詢問」。A separate
// single-purpose key (mirrors useReviewerIdentity.ts's shape) rather than
// folding into useSettings.ts — that module's own docstring scopes it to
// non-destructive UI preferences, and this one gates a data-loss action.
export function useSkipStartOverGuard() {
  const [skip, setSkipState] = useState(() => load());

  function setSkip(value: boolean) {
    setSkipState(value);
    try {
      localStorage.setItem(STORAGE_KEY, value ? '1' : '0');
    } catch {
      // storage blocked (private mode) — preference just stops persisting
      // across reloads; the guard still works for the rest of this load.
    }
  }

  return { skip, setSkip };
}
