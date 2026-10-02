import { useEffect, useRef, useState } from 'react';
import { Layers } from 'lucide-react';
import { getSemanticBatch, submitSemanticBatch } from '../../lib/api';
import { useRequestedLlmProvider } from '../../state/useRequestedLlmProvider';

const POLL_INTERVAL_MS = 5000;

interface BatchAnalysisBarProps {
  chainId: string;
}

type Status = 'idle' | 'submitting' | 'polling' | 'completed' | 'unavailable' | 'error';

// P5 Message Batches — a chain can easily have dozens of qualifying
// residuals across its adjacent+anchor sessions; this submits them all as
// ONE Anthropic Batch job (§03's "非即時任務，五折") instead of the
// single-session "AI 語意建議" button's one-call-per-difference path.
// Results apply directly to each session's audit trail server-side
// (backend.services.llm.batch_jobs.poll_batch) — this bar just reports
// progress, it doesn't need to hold or merge the suggestion content itself.
export function BatchAnalysisBar({ chainId }: BatchAnalysisBarProps) {
  const [status, setStatus] = useState<Status>('idle');
  const [batchId, setBatchId] = useState<string | null>(null);
  const [differenceCount, setDifferenceCount] = useState(0);
  const [appliedCount, setAppliedCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Bedrock has no Message Batches (the backend answers 409) — say so up
  // front instead of letting the click fail.
  const noBatch = useRequestedLlmProvider() === 'bedrock';

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  function startPolling(id: string) {
    setStatus('polling');
    pollRef.current = setInterval(async () => {
      try {
        const poll = await getSemanticBatch(chainId, id);
        if (poll.status === 'completed') {
          if (pollRef.current) clearInterval(pollRef.current);
          setAppliedCount(Object.values(poll.results ?? {}).filter((v) => v != null).length);
          setStatus('completed');
        }
      } catch (err) {
        if (pollRef.current) clearInterval(pollRef.current);
        setError(err instanceof Error ? err.message : String(err));
        setStatus('error');
      }
    }, POLL_INTERVAL_MS);
  }

  async function handleSubmit() {
    setStatus('submitting');
    setError(null);
    try {
      const result = await submitSemanticBatch(chainId);
      if (!result.semantic_layer_available) {
        setStatus('unavailable');
        return;
      }
      if (!result.batch_id) {
        setDifferenceCount(0);
        setStatus('completed'); // nothing qualified — trivially "done"
        return;
      }
      setBatchId(result.batch_id);
      setDifferenceCount(result.difference_count ?? 0);
      startPolling(result.batch_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    }
  }

  return (
    <div className="mt-3 rounded-md border border-line bg-surface-2 p-2.5 text-[12px]">
      <div className="flex flex-wrap items-center gap-2">
        <Layers size={14} className="text-ink-500" />
        <span className="font-medium text-ink-700">批次語意分析</span>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={noBatch || status === 'submitting' || status === 'polling'}
          className="ml-auto rounded-md border border-line px-2.5 py-1 text-ink-700 hover:bg-accent-soft disabled:opacity-50"
        >
          {status === 'submitting' ? '提交中…' : status === 'polling' ? '分析中…' : '對整條鏈執行批次分析'}
        </button>
      </div>
      {noBatch && <p className="mt-1 text-ink-500">Bedrock 不支援批次語意分析；可以在各次比對裡用「AI 語意分析」逐次分析。</p>}
      {status === 'unavailable' && <p className="mt-1 text-ink-400">未設定 AI 金鑰，此功能未啟用。</p>}
      {status === 'polling' && batchId && (
        <p className="mt-1 text-ink-500">
          已提交 {differenceCount} 筆殘差差異（batch {batchId}），每 5 秒查詢一次進度——這是非即時批次工作，可先做其他事再回來看。
        </p>
      )}
      {status === 'completed' && (
        <p className="mt-1 text-low-700">
          {differenceCount === 0 ? '此鏈目前沒有符合條件的殘差差異需要分析。' : `批次分析完成，已套用 ${appliedCount}/${differenceCount} 筆建議至各比對的稽核紀錄。`}
        </p>
      )}
      {status === 'error' && error && <p className="mt-1 text-high-700">{error}</p>}
      <p className="mt-1 text-[11px] text-ink-400">
        沒有即時保證，適合非急迫、批量的殘差複核；結果一律只是建議，最終風險等級仍由規則引擎與人工覆核決定。
      </p>
    </div>
  );
}
