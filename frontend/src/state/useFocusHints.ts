import { useCallback, useSyncExternalStore } from 'react';

// 專注提示 — one small inline hint at a time, pointing at the next action.
// This module only remembers which stages were acknowledged (or that hints
// are off); callers decide which single stage applies.
export type FocusHintStage = 'demo' | 'agent' | 'first-high' | 'export';

export interface FocusHintHandle {
  stage: FocusHintStage;
  onAcknowledge: () => void;
  onDisableAll: () => void;
}

// Button names are quoted from SourceTab, AgentSection, DiffListMessage and
// RightPanel — keep them in sync when those labels change.
export const FOCUS_HINT_COPY: Record<FocusHintStage, string[]> = {
  demo: ['還沒上傳文件？', '按下面的「載入示範資料（6 頁合成文件）」，一次看完整個比對流程。'],
  agent: ['文件比對完成了，還沒有人覆核過。', '按「請 Agent 準備覆核」，讓 Agent 先查證一次。'],
  'first-high': ['文件比對完成了，還沒有人覆核過。', '先看第一筆 High 風險差異，按「查看」展開。'],
  export: ['所有 High 風險差異都已標為「已確認」。', '可以按「匯出審查報告」了。'],
};

const STORAGE_KEY = 'plimsoll.focusHints.v1';

interface StoredState {
  disabled: boolean;
  dismissed: FocusHintStage[];
}

const DEFAULT_STATE: StoredState = { disabled: false, dismissed: [] };

function readStored(): StoredState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_STATE;
    const parsed = JSON.parse(raw);
    const dismissed = Array.isArray(parsed?.dismissed)
      ? parsed.dismissed.filter((s: unknown): s is FocusHintStage => typeof s === 'string')
      : [];
    return { disabled: parsed?.disabled === true, dismissed };
  } catch {
    // Private mode / storage disabled / corrupt value — fall back to
    // "nothing dismissed yet" rather than breaking the app.
    return DEFAULT_STATE;
  }
}

function writeStored(state: StoredState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Private-mode / storage disabled — hints just stop persisting across
    // reloads; the app keeps working for the rest of this page load.
  }
}

// One shared store rather than useState per caller: RightPanel stays mounted
// from the first screen on, so its own copy would miss a 「不再顯示提示」
// pressed in SourceTab or a reset on the help page.
let sharedState: StoredState = readStored();
const listeners = new Set<() => void>();

function setSharedState(next: StoredState) {
  sharedState = next;
  writeStored(next);
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): StoredState {
  return sharedState;
}

// 使用說明頁「重新顯示操作提示」.
export function resetFocusHints() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignored — see writeStored above.
  }
  sharedState = DEFAULT_STATE;
  listeners.forEach((listener) => listener());
}

export function useFocusHints() {
  const state = useSyncExternalStore(subscribe, getSnapshot);

  const isDismissed = useCallback((stage: FocusHintStage) => state.disabled || state.dismissed.includes(stage), [state]);

  const dismissStage = useCallback((stage: FocusHintStage) => {
    if (sharedState.dismissed.includes(stage)) return;
    setSharedState({ ...sharedState, dismissed: [...sharedState.dismissed, stage] });
  }, []);

  const disableAll = useCallback(() => {
    if (sharedState.disabled) return;
    setSharedState({ ...sharedState, disabled: true });
  }, []);

  // null unless `stage` is the active one and not yet dismissed.
  const hintFor = useCallback(
    (activeStage: FocusHintStage | null, stage: FocusHintStage): FocusHintHandle | null => {
      if (activeStage !== stage || isDismissed(stage)) return null;
      return { stage, onAcknowledge: () => dismissStage(stage), onDisableAll: disableAll };
    },
    [isDismissed, dismissStage, disableAll],
  );

  return { isDismissed, dismissStage, disableAll, hintFor };
}
