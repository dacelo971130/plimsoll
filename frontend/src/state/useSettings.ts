import { useEffect, useState } from 'react';
import { NO_LLM_LABEL } from '../lib/llmProviders';
import type { ShellVariant } from './shellConfig';
import type { AnalysisMode, HighlightPalette, ThemeMode } from '../types';

// ui-spec §3.4 / §5 B12: all UI preferences persist to localStorage only.
// Nothing here is session/audit data — it never touches review_events.jsonl.
const STORAGE_KEY = 'plimsoll.settings.v1';

// plimsoll-subtraction-matrix.html §06 小win #07 — 語言切換（沒有翻譯）、整體
//色調選擇器（海軍藍已是使用者回饋定案的唯一色調）、介面字體／原文字體兩組選
// 擇、自訂背景圖，全部判「砍」：每一個設定都是一個沒做的決定。海軍藍／IBM
// Plex Sans／Noto Sans TC 現在是唯一值（2026-09-28 品牌對齊前是 Inter，已換
// 掉），寫死在下面的 effect 裡，不再是使用者的選擇。
export interface Settings {
  theme: ThemeMode;
  highlightPalette: HighlightPalette;
  // plimsoll-two-shell-spec.md §1.3 — the ONE new setting the two-shell work
  // adds. Picking a shell also seeds `fontSize` from that shell's preset
  // (see ShellTab) — this field only ever changes the initial value, never
  // fights a later manual `fontSize` change.
  shellVariant: ShellVariant;
  // Persisted so switching Settings tabs (AiModelTab unmounts/remounts on
  // every tab switch — see SettingsPopover) never resets the provider
  // selection and hides the API key field. The key itself stays in
  // sessionStorage, bucketed by provider (AiModelTab.tsx) — never here.
  // Combined with the sessionStorage key, this is what frontend/src/lib/
  // llmProviders.ts's llmHeaders() turns into the X-Llm-Provider/
  // X-Llm-Api-Key headers sent on every AI-touching request.
  llmProvider: string;
  // P6 成本試算 — which model within `llmProvider` the cost blurb/estimator
  // describes. Display/estimate only (see llmProviders.ts's module
  // docstring) — the backend still always uses its own hardcoded model per
  // provider; this never becomes a header. Empty string = no model chosen
  // yet, AiModelTab seeds it to the provider's first model on mount/switch.
  llmModel: string;
  // P5 — session-level knob sent with the next upload/demo request
  // (backend/services/llm/residual.py's needs_semantic_review()).
  analysisMode: AnalysisMode;
  // P5 — font size (4-tier), previously deferred as "P6 Someday".
  fontSize: 'sm' | 'md' | 'lg' | 'xl';
}

const DEFAULT_SETTINGS: Settings = {
  theme: 'system',
  highlightPalette: 'classic',
  shellVariant: 'A', // matches today's actual operating density — least surprise
  llmProvider: NO_LLM_LABEL,
  llmModel: '',
  analysisMode: 'rules_first',
  fontSize: 'md',
};

function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    return { ...DEFAULT_SETTINGS, ...(JSON.parse(raw) as Partial<Settings>) };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function useSettings() {
  const [settings, setSettings] = useState<Settings>(() => loadSettings());

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));

    const root = document.documentElement;
    if (settings.theme === 'system') {
      root.removeAttribute('data-theme');
    } else {
      root.setAttribute('data-theme', settings.theme);
    }

    if (settings.highlightPalette === 'colorblind') {
      root.setAttribute('data-highlight', 'colorblind');
    } else {
      root.removeAttribute('data-highlight');
    }

    // 海軍藍／IBM Plex Sans＋Noto Sans TC／Noto Sans TC 是使用者回饋定案的唯
    // 一值——不再是 [data-accent] 條件式或可選字體堆疊，這三行對每個 render 都
    // 一樣。2026-09-28 品牌對齊 — 介面字體從 Inter 換成行銷網站用的 IBM Plex
    // Sans（tokens.css 的 --font-ui 預設同步改了；這裡是唯一還會覆寫它的地
    // 方，所以也要跟著換，否則 render 時會被蓋回舊值）。
    root.setAttribute('data-accent', 'navy');
    root.style.setProperty(
      '--font-ui',
      "'IBM Plex Sans', 'Noto Sans TC', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
    );
    root.style.setProperty('--font-source', "'Noto Sans TC', ui-sans-serif, system-ui, sans-serif");

    const FONT_SCALE: Record<Settings['fontSize'], string> = { sm: '0.9', md: '1', lg: '1.125', xl: '1.25' };
    root.style.setProperty('--font-scale', FONT_SCALE[settings.fontSize]);
  }, [settings]);

  function update<K extends keyof Settings>(key: K, value: Settings[K]) {
    setSettings((prev) => ({ ...prev, [key]: value }));
  }

  return { settings, update };
}
