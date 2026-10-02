import { useState } from 'react';
import { Sparkles } from 'lucide-react';
import { previewSemanticSuggestions, suggestAliases } from '../../lib/api';
import type { AiSemanticSuggestion } from '../../types';
import { CostEstimatorModal } from './CostEstimatorModal';

interface SemanticLayerBarProps {
  sessionId: string;
  onSuggestions: (bySessionDifferenceId: Record<string, AiSemanticSuggestion | null>) => void;
  // 覆核 Agent (useAgent.ts) — folded into this same button's click instead
  // of keeping its own separate 請 Agent 準備覆核 trigger in AgentSection.
  // The Agent runs on Claude, Gemini or Bedrock but not ChatGPT (unlike
  // 語意建議／別名候選, which work with every provider), so this can be false
  // while the other two actions still run.
  agentAvailable: boolean;
  onStartAgentBriefing: () => void;
}

type Status = 'idle' | 'loading' | 'done' | 'unavailable' | 'error';

// P5 — the missing frontend half of W7a: `POST /{id}/semantic-preview`
// existed since W7 but nothing ever called it. This bar is the opt-in
// trigger; results are merged into the diff list's display state by the
// caller (RightPanel), never written back into `session.differences` itself
// — the permanent record stays the server's AI_INITIAL audit event.
//
// 2026-09-28 使用者回饋「只保留 AI 語意建議，但合併兩個按鈕的功能／AI 覆核功能
// 也納入／不需要切這麼多功能按鈕」— one button now triggers all three: 語意
// 建議、詞彙別名候選、覆核 Agent 簡報（Agent 可用時）。Each action's own
// result still lands wherever it always did (diff list overlay, 詞彙別名核准
// queue, AgentSection's briefing view) — only the TRIGGER is consolidated,
// not those displays.
export function SemanticLayerBar({ sessionId, onSuggestions, agentAvailable, onStartAgentBriefing }: SemanticLayerBarProps) {
  const [status, setStatus] = useState<Status>('idle');
  const [aliasStatus, setAliasStatus] = useState<Status>('idle');
  const [aliasCount, setAliasCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [costOpen, setCostOpen] = useState(false);

  async function handleSuggest() {
    setStatus('loading');
    setError(null);
    try {
      const result = await previewSemanticSuggestions(sessionId);
      if (!result.semantic_layer_available) {
        setStatus('unavailable');
        return;
      }
      const map: Record<string, AiSemanticSuggestion | null> = {};
      for (const d of result.differences) map[d.id] = d.ai_semantic_suggestion ?? null;
      onSuggestions(map);
      setStatus('done');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    }
  }

  async function handleSuggestAliases() {
    setAliasStatus('loading');
    setError(null);
    try {
      const result = await suggestAliases(sessionId);
      if (!result.semantic_layer_available) {
        setAliasStatus('unavailable');
        return;
      }
      setAliasCount(result.candidates.length);
      setAliasStatus('done');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setAliasStatus('error');
    }
  }

  function handleClick() {
    void handleSuggest();
    void handleSuggestAliases();
    if (agentAvailable) onStartAgentBriefing();
  }

  const loading = status === 'loading' || aliasStatus === 'loading';
  const tooltip = `按下後 AI 會一次處理：補上差異的語意判讀、找出可能的詞彙別名候選${
    agentAvailable ? '、準備覆核 Agent 簡報' : ''
  }。`;

  return (
    <div className="rounded-xl border border-line bg-surface p-3 text-[12.5px] shadow-[var(--sh-1)]">
      <div className="flex flex-wrap items-center gap-2">
        <Sparkles size={14} className="text-ink-500" />
        <button
          type="button"
          onClick={handleClick}
          disabled={loading}
          title={tooltip}
          className="rounded-md bg-ink-800 px-2.5 py-1 text-on-accent hover:opacity-90 disabled:opacity-50"
        >
          {loading ? '產生中…' : 'AI 語意建議'}
        </button>
        <button
          type="button"
          onClick={() => setCostOpen(true)}
          className="rounded-md border border-line px-2.5 py-1 text-ink-700 hover:bg-accent-soft"
        >
          AI 成本試算
        </button>
        {/* Both underlying actions hit the same missing-key condition — say
            it once, not twice. */}
        {(status === 'unavailable' || aliasStatus === 'unavailable') && (
          <span className="text-ink-400">未設定 AI 金鑰，此功能未啟用</span>
        )}
        {status === 'done' && <span className="text-low-700">已套用至下方差異清單</span>}
        {aliasStatus === 'done' && (
          <span className="text-low-700">
            已產生 {aliasCount} 筆候選，請至設定 → 進階 →「詞彙別名核准」處理
          </span>
        )}
        {error && <span className="text-high-700">{error}</span>}
      </div>
      <p className="mt-1 text-[11px] text-ink-400">AI 建議僅供參考，最終風險等級與詞彙採用仍由人工核准。</p>
      {costOpen && <CostEstimatorModal sessionId={sessionId} onClose={() => setCostOpen(false)} />}
    </div>
  );
}
