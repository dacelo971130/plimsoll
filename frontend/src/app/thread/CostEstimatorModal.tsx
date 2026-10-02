import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { getSessionCostEstimate, type CostEstimateResult } from '../../lib/api';
import { ALL_LLM_MODELS } from '../../lib/llmProviders';

function tokensToCost(inputTokens: number, outputTokens: number, inputPerM: number, outputPerM: number): number {
  return (inputTokens / 1_000_000) * inputPerM + (outputTokens / 1_000_000) * outputPerM;
}

function formatUsd(value: number): string {
  if (value === 0) return '$0';
  return `$${value.toFixed(value < 1 ? 4 : 2)}`;
}

interface CostEstimatorModalProps {
  sessionId: string;
  onClose: () => void;
}

// P6 成本試算 — estimates how many of THIS session's differences would
// actually be sent to an LLM (reusing the real semantic-layer trigger,
// backend/services/llm/cost_estimate.py) and roughly how much that would
// cost, instead of the old fixed small/medium/large document-size guesses.
// Still an ESTIMATE, not a real tokenizer or a billing integration — see
// the backend module's docstring for exactly what's approximated and why.
// Never calls any AI provider itself: the trigger heuristic and the token
// count are both free, offline computation over differences.json.
export function CostEstimatorModal({ sessionId, onClose }: CostEstimatorModalProps) {
  const [result, setResult] = useState<CostEstimateResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setResult(null);
    setError(null);
    getSessionCostEstimate(sessionId)
      .then((r) => {
        if (!cancelled) setResult(r);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const low = result?.modes.rules_first;
  const high = result?.modes.model_only;
  const mid = result?.modes.model_heavy;

  const rows = result
    ? ALL_LLM_MODELS.map((m) => ({
        ...m,
        lowCost: tokensToCost(low!.estimated_input_tokens, low!.estimated_output_tokens, m.inputPerM, m.outputPerM),
        highCost: tokensToCost(high!.estimated_input_tokens, high!.estimated_output_tokens, m.inputPerM, m.outputPerM),
      })).sort((a, b) => a.lowCost - b.lowCost)
    : [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="AI 成本試算"
        className="w-full max-w-[560px] rounded-xl border border-line bg-surface p-4 shadow-[var(--sh-3)]"
      >
        <div className="flex items-center justify-between">
          <h3 className="text-[14px] font-semibold text-ink-900">AI 成本試算</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="關閉"
            className="rounded-md p-1 text-ink-500 hover:bg-accent-soft"
          >
            <X size={16} />
          </button>
        </div>
        <p className="mt-1 text-[11.5px] text-ink-500">
          根據這份文件實際會送審的差異筆數與文字量估算，不是固定的文件大小假設；仍非真正的 tokenizer 計數，也不會呼叫任何 AI。實際費用請以供應商帳單為準。
        </p>

        {error && (
          <p className="mt-3 rounded-md border border-high-200 bg-high-50 px-2.5 py-1.5 text-[12px] text-high-700">
            估算失敗：{error}
          </p>
        )}
        {!error && !result && <p className="mt-3 text-[12.5px] text-ink-400">載入中…</p>}

        {result && low && high && mid && (
          <>
            <div className="mt-3 rounded-lg border border-line bg-surface-2 p-2.5 text-[11.5px] text-ink-600">
              低估（預設 rules_first 模式）會送審 <strong className="font-medium text-ink-900">{low.qualifying_count}</strong> 筆差異；
              中間（model_heavy）<strong className="font-medium text-ink-900">{mid.qualifying_count}</strong> 筆；
              高估（最寬鬆 model_only，每筆「修改」都送）
              <strong className="font-medium text-ink-900"> {high.qualifying_count}</strong> 筆——費用區間就是這兩端。
            </div>

            <div className="mt-3 max-h-[360px] overflow-y-auto rounded-lg border border-line">
              <table className="w-full border-collapse text-[12.5px]">
                <thead className="sticky top-0 bg-surface-2">
                  <tr className="text-left text-[11.5px] text-ink-500">
                    <th className="px-2.5 py-1.5 font-medium">模型</th>
                    <th className="px-2.5 py-1.5 font-medium">供應商</th>
                    <th className="px-2.5 py-1.5 text-right font-medium">估算費用區間</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line-soft">
                  {rows.map((r) => (
                    <tr key={`${r.providerId}-${r.id}`}>
                      <td className="px-2.5 py-1.5 text-ink-800">
                        {r.label}
                        <span className="ml-1 text-[11px] text-ink-400">（{r.tier}）</span>
                      </td>
                      <td className="px-2.5 py-1.5 text-ink-600">{r.providerLabel}</td>
                      <td className="px-2.5 py-1.5 text-right tabular-nums text-ink-800">
                        {formatUsd(r.lowCost)} – {formatUsd(r.highCost)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[11px] text-ink-400">
              token 數為字元數推算（中文字約 1 token／字，其餘約 4 字元／token），非各供應商實際 tokenizer 結果。
            </p>
          </>
        )}
      </div>
    </div>
  );
}
