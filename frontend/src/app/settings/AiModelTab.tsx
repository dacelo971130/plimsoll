import { useEffect, useState } from 'react';
import { LLM_PROVIDER_OPTIONS, NO_LLM_LABEL, apiKeyStorageKey } from '../../lib/llmProviders';
import type { Settings } from '../../state/useSettings';
import type { AnalysisMode } from '../../types';

const ANALYSIS_MODE_OPTIONS: { value: AnalysisMode; label: string; hint: string }[] = [
  { value: 'rules_first', label: '一般（預設）', hint: '規則引擎為主，只有大幅改寫且未命中規則的差異會請 AI 複核' },
  { value: 'model_heavy', label: '寬鬆語意複核', hint: '規則引擎優先，但放寬門檻，更多差異會請 AI 複核' },
  { value: 'model_only', label: '全面 AI 分類', hint: '每一筆「修改」都會請 AI 提供語意建議' },
];

function formatUsd(perM: number): string {
  return `$${perM.toFixed(2)}`;
}

// The backend's ACTUAL model per working provider (backend/services/llm/
// {anthropic,gemini,openai}_provider.py's `MODEL_ID`) — fixed, and NOT
// affected by the `模型` dropdown below (see its own note). Kept separate
// from `settings.llmModel` so the status pill never claims a model is
// running requests when it isn't.
const BACKEND_MODEL_ID_BY_PROVIDER: Record<string, string> = {
  anthropic: 'claude-opus-5',
  gemini: 'gemini-2.5-flash',
  openai: 'gpt-4o',
};

interface AiModelTabProps {
  settings: Settings;
  update: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
}

// P5 — Claude/Gemini/ChatGPT are REAL, working providers (backend/services/
// llm/{anthropic,gemini,openai}_provider.py). Bedrock (P6) is listed too, but
// only for its model catalog/pricing — the backend has no Bedrock adapter,
// so selecting it behaves exactly like leaving no key pasted (see `isBedrock`
// below and llmProviders.ts's module docstring). The key you paste for a
// working provider is sent ONLY as the `X-Llm-Api-Key` header on requests you
// make (never logged, never written to localStorage/code/VCS — see
// frontend/src/lib/llmProviders.ts's llmHeaders()); the backend constructs
// a provider instance for that one request and never persists it.
//
// `provider` lives in the persisted `settings` (useSettings/localStorage),
// NOT a local useState — SettingsPopover unmounts/remounts this component on
// every tab switch (plain `{tab === 'ai-model' && <AiModelTab/>}`), and a
// local default would silently reset to "不使用 LLM" every time you left and
// came back to this tab, hiding the API key field entirely. Only the key
// itself (`apiKey`) stays local + sessionStorage-backed, which is correct —
// it must never touch localStorage/code/VCS.
export function AiModelTab({ settings, update }: AiModelTabProps) {
  const provider = settings.llmProvider || NO_LLM_LABEL;
  const [apiKey, setApiKey] = useState('');

  useEffect(() => {
    setApiKey(sessionStorage.getItem(apiKeyStorageKey(provider)) ?? '');
  }, [provider]);

  const selectedOption = LLM_PROVIDER_OPTIONS.find((o) => o.label === provider);
  const models = selectedOption?.models ?? [];

  // Each provider's model list is disjoint (Claude/Gemini/OpenAI/Bedrock
  // each only offer their own models — the whole point of this dropdown),
  // so switching provider always invalidates the old `llmModel`. Reset to
  // that provider's first (cheapest-listed) model rather than leaving a
  // stale id that doesn't belong to the new list.
  useEffect(() => {
    if (models.length > 0 && !models.some((m) => m.id === settings.llmModel)) {
      update('llmModel', models[0].id);
    }
  }, [provider]);

  function handleKeyChange(value: string) {
    setApiKey(value);
    if (value) {
      sessionStorage.setItem(apiKeyStorageKey(provider), value);
    } else {
      sessionStorage.removeItem(apiKeyStorageKey(provider));
    }
  }

  const usesLlm = selectedOption != null;
  const selectedModel = models.find((m) => m.id === settings.llmModel) ?? models[0];
  // Bedrock is listed for its models/pricing only — not one of the backend's
  // `_REQUEST_SCOPED_PROVIDERS` (see llmProviders.ts). Selecting it is never
  // an error, but it's also never "enabled" the way the other three are.
  const isBedrock = selectedOption?.id === 'bedrock';
  const enabled = usesLlm && !isBedrock && apiKey.trim().length > 0;

  return (
    <div className="space-y-5">
      <section>
        <div className="mb-1.5 text-[12.5px] font-medium text-ink-700">分析模型</div>
        <select
          value={provider}
          onChange={(e) => update('llmProvider', e.target.value)}
          className="w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px] text-ink-800"
        >
          {LLM_PROVIDER_OPTIONS.map((opt) => (
            <option key={opt.id} value={opt.label}>
              {opt.label}
            </option>
          ))}
          <option value={NO_LLM_LABEL}>{NO_LLM_LABEL}</option>
        </select>
        <p className="mt-1 text-[11.5px] text-ink-500">切換分析模型會顯示該模型各自儲存的金鑰，不會清空其他模型的設定。</p>
      </section>

      {usesLlm && models.length > 0 && (
        <section>
          <div className="mb-1.5 text-[12.5px] font-medium text-ink-700">模型</div>
          <select
            value={selectedModel?.id ?? ''}
            onChange={(e) => update('llmModel', e.target.value)}
            className="w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px] text-ink-800"
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}（{m.tier}）
              </option>
            ))}
          </select>
          {selectedModel && (
            <p className="mt-1 text-[11.5px] text-ink-500">
              每 100 萬 tokens：輸入 {formatUsd(selectedModel.inputPerM)}・輸出 {formatUsd(selectedModel.outputPerM)}（官方牌價，實際費用以供應商帳單為準）。此選單用於模型與成本比較，本機比對實際呼叫的模型固定由伺服器設定，不受此選擇影響。
            </p>
          )}
        </section>
      )}

      {usesLlm && (
        <section>
          <div className="mb-1.5 text-[12.5px] font-medium text-ink-700">API Key / Token</div>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => handleKeyChange(e.target.value)}
            placeholder="貼上金鑰"
            className="w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px] text-ink-800"
          />
          <p className="mt-1 text-[11.5px] text-ink-500">Key 只存瀏覽器工作階段（sessionStorage），只會隨此瀏覽器發出的請求以標頭送到本機後端，不寫入原始碼或版控。</p>
        </section>
      )}

      <div className={`flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-[12.5px] ${
        enabled ? 'border-low-200 bg-low-50 text-low-700' : 'border-line bg-surface-2 text-ink-600'
      }`}
      >
        <span className={`h-2 w-2 rounded-full ${enabled ? 'bg-low-500' : 'bg-ink-400'}`} />
        {isBedrock
          ? 'Bedrock 目前僅提供模型與成本比較，尚未串接為可用的分析引擎（AI 功能維持停用，比對本身不受影響）'
          : enabled
            ? `已啟用 ${provider} LLM 模式（${BACKEND_MODEL_ID_BY_PROVIDER[selectedOption!.id]}）`
            : '未設定，使用本機精準規則引擎'}
      </div>

      <section>
        <div className="mb-1.5 text-[12.5px] font-medium text-ink-700">分析模式</div>
        <div className="flex flex-col gap-1.5">
          {ANALYSIS_MODE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => update('analysisMode', opt.value)}
              aria-pressed={settings.analysisMode === opt.value}
              className={`flex flex-col items-start gap-0.5 rounded-md border px-2.5 py-1.5 text-left text-[12.5px] ${
                settings.analysisMode === opt.value
                  ? 'border-ink-800 bg-accent-soft'
                  : 'border-line text-ink-600 hover:bg-accent-soft'
              }`}
            >
              <span className="font-medium text-ink-800">{opt.label}</span>
              <span className="text-[11.5px] text-ink-500">{opt.hint}</span>
            </button>
          ))}
        </div>
        <p className="mt-1.5 text-[11.5px] text-ink-500">
          套用於下一次上傳／載入示範資料時建立的比對；不會改變已建立比對的規則引擎判定。
        </p>
      </section>

      <section>
        <div className="mb-1.5 text-[12.5px] font-medium text-ink-700">關於這幾個選項</div>
        <p className="text-[11.5px] text-ink-500">
          Claude、Gemini、ChatGPT 都是真的接上（結構化輸出＋圖片辨識＋批次 API），差異僅在模型與費率；沒有貼金鑰時，AI 相關功能一律停用，比對本身完全不受影響。Bedrock
          目前只用於上方的模型與成本比較，選擇它等同未貼金鑰。
        </p>
      </section>
    </div>
  );
}
