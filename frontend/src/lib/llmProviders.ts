// P5 multi-provider BYOK — single source of truth for the provider list,
// shared between AiModelTab.tsx (which provider/model is selected + where
// its key is stored) and api.ts (which headers to attach to an AI-touching
// request). `llmHeaders()` below is generic over whatever's in this list —
// adding a provider here is enough to make its BYOK key flow to the backend.
//
// Bedrock is listed here (models + prices, P6 成本試算) purely for the
// Settings-page model picker and cost comparison — it is NOT one of
// backend/services/llm/provider.py's `_REQUEST_SCOPED_PROVIDERS`. Selecting
// it and pasting a key still resolves to "unavailable" server-side exactly
// like an unset key would (provider.py's deliberate design: never crash,
// never silently fall through to a DIFFERENT provider the user didn't ask
// for). Groq stays absent entirely — no models/pricing anyone asked to see.
//
// Prices are USD per 1,000,000 tokens, standard/on-demand tier, checked
// against each vendor's own pricing page on 2026-09-28 (see helpContent.tsx's
// AI 輔助功能 section for the cited sources shown to the user). They drift —
// this is a cost *estimate* feature, not a billing integration.

export type LlmProviderId = 'anthropic' | 'gemini' | 'openai' | 'bedrock';

export type LlmModelTier = '輕量' | '中階' | '旗艦';

export interface LlmModelOption {
  id: string;
  label: string;
  tier: LlmModelTier;
  inputPerM: number;
  outputPerM: number;
}

export interface LlmProviderOption {
  id: LlmProviderId;
  label: string;
  models: LlmModelOption[];
}

export const LLM_PROVIDER_OPTIONS: LlmProviderOption[] = [
  {
    id: 'anthropic',
    label: 'Claude（Anthropic）',
    models: [
      { id: 'claude-haiku-4-5', label: 'Claude Haiku 4.5', tier: '輕量', inputPerM: 1.0, outputPerM: 5.0 },
      { id: 'claude-sonnet-5', label: 'Claude Sonnet 5', tier: '中階', inputPerM: 2.0, outputPerM: 10.0 },
      { id: 'claude-opus-5-5', label: 'Claude Opus 5.5', tier: '旗艦', inputPerM: 4.0, outputPerM: 20.0 },
      { id: 'claude-fable-5-1', label: 'Claude Fable 5.1', tier: '旗艦', inputPerM: 10.0, outputPerM: 50.0 },
    ],
  },
  {
    id: 'gemini',
    label: 'Gemini（Google）',
    models: [
      { id: 'gemini-3.1-flash-lite', label: 'Gemini 3.1 Flash-Lite', tier: '輕量', inputPerM: 0.25, outputPerM: 1.5 },
      { id: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash', tier: '中階', inputPerM: 0.75, outputPerM: 3.75 },
      { id: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro', tier: '旗艦', inputPerM: 1.25, outputPerM: 10.0 },
    ],
  },
  {
    id: 'openai',
    label: 'ChatGPT（OpenAI）',
    models: [
      { id: 'gpt-6-luna', label: 'GPT-6 Luna', tier: '輕量', inputPerM: 0.1, outputPerM: 0.5 },
      { id: 'gpt-6-sol', label: 'GPT-6 Sol', tier: '中階', inputPerM: 2.0, outputPerM: 10.0 },
      { id: 'gpt-6-astra', label: 'GPT-6 Astra', tier: '旗艦', inputPerM: 10.0, outputPerM: 50.0 },
    ],
  },
  {
    id: 'bedrock',
    label: 'Bedrock（AWS）',
    models: [
      { id: 'amazon.nova-2-lite', label: 'Amazon Nova 2 Lite', tier: '輕量', inputPerM: 0.3, outputPerM: 2.5 },
      {
        id: 'anthropic.claude-haiku-4-5',
        label: 'Claude Haiku 4.5（Bedrock）',
        tier: '輕量',
        inputPerM: 1.0,
        outputPerM: 5.0,
      },
      {
        id: 'amazon.nova-2-pro',
        label: 'Amazon Nova 2 Pro（Preview）',
        tier: '中階',
        inputPerM: 1.25,
        outputPerM: 10.0,
      },
      {
        id: 'anthropic.claude-sonnet-5',
        label: 'Claude Sonnet 5（Bedrock）',
        tier: '中階',
        inputPerM: 2.0,
        outputPerM: 10.0,
      },
    ],
  },
];

/** Every model across every provider, tagged with its provider — the flat
 * shape the cost-estimator modal sorts/compares across vendors. */
export const ALL_LLM_MODELS: (LlmModelOption & { providerId: LlmProviderId; providerLabel: string })[] =
  LLM_PROVIDER_OPTIONS.flatMap((p) => p.models.map((m) => ({ ...m, providerId: p.id, providerLabel: p.label })));

export const NO_LLM_LABEL = '不使用 LLM（本機規則引擎）';

const SETTINGS_KEY = 'plimsoll.settings.v1';
const SESSION_KEY_PREFIX = 'plimsoll.apiKey.'; // sessionStorage only — never localStorage/code/VCS, see AiModelTab.tsx

export function apiKeyStorageKey(providerLabel: string): string {
  return SESSION_KEY_PREFIX + providerLabel;
}

/** Reads the currently-selected provider label out of useSettings'
 * localStorage blob directly — api.ts is a plain module with no React
 * state, so this avoids threading `settings` through every call site. */
function currentProviderLabel(): string | null {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return null;
    return (JSON.parse(raw) as { llmProvider?: string }).llmProvider ?? null;
  } catch {
    return null;
  }
}

/** Headers to attach to any AI-touching fetch — empty object when "不使用
 * LLM" is selected, or when the selected provider has no key pasted yet
 * (falls back to the backend's server-env-var behavior either way, see
 * resolve_llm_provider()'s "both None" branch). */
export function llmHeaders(): HeadersInit {
  const label = currentProviderLabel();
  if (!label || label === NO_LLM_LABEL) return {};
  const option = LLM_PROVIDER_OPTIONS.find((o) => o.label === label);
  if (!option) return {};
  const apiKey = sessionStorage.getItem(apiKeyStorageKey(label));
  if (!apiKey) return {};
  return { 'X-Llm-Provider': option.id, 'X-Llm-Api-Key': apiKey };
}
