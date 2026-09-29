import { useEffect, useState } from 'react';
import { approvePendingAlias, listPendingAliases, rejectPendingAlias } from '../../lib/api';
import { useReviewerIdentity } from '../../state/useReviewerIdentity';
import type { PendingAlias } from '../../types';

// P5 term_aliases 核准流程 — the management UI the audit called out as most
// worth prioritizing: previously the ONLY way to add a term_alias was
// hand-editing data/store/config/term_aliases/v1.json. Candidates are
// produced per-session ("AI 語意建議" bar → "產生詞彙別名候選"); this tab is
// the shared, session-independent queue where a human actually approves or
// rejects them — an LLM proposal never reaches the live comparison path on
// its own (backend/models/config_models.py::TermAlias docstring).
export function AliasApprovalTab() {
  const { reviewerName, setReviewerName } = useReviewerIdentity();
  const [pending, setPending] = useState<PendingAlias[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      setPending(await listPendingAliases('pending'));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function handleApprove(id: string) {
    if (!reviewerName.trim()) {
      setError('請先填寫核准人姓名');
      return;
    }
    setBusyId(id);
    setError(null);
    try {
      await approvePendingAlias(id, reviewerName.trim());
      setPending((prev) => prev.filter((p) => p.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function handleReject(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await rejectPendingAlias(id);
      setPending((prev) => prev.filter((p) => p.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-4">
      <section>
        <div className="mb-1.5 text-[12.5px] font-medium text-ink-700">核准人姓名</div>
        <input
          value={reviewerName}
          onChange={(e) => setReviewerName(e.target.value)}
          placeholder="核准這批詞彙別名的人員姓名"
          className="w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px] text-ink-800"
        />
      </section>

      <section>
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[12.5px] font-medium text-ink-700">待核准候選（{pending.length}）</span>
          <button type="button" onClick={() => void refresh()} className="text-[11.5px] text-ink-500 hover:text-ink-800">
            重新整理
          </button>
        </div>

        {loading ? (
          <p className="text-[12.5px] text-ink-400">載入中…</p>
        ) : pending.length === 0 ? (
          <div className="rounded-lg border border-dashed border-line p-4 text-center text-[12.5px] text-ink-500">
            目前沒有待核准的詞彙別名候選。可在比對結果的「AI 語意建議」區塊產生候選。
          </div>
        ) : (
          <div className="space-y-2">
            {pending.map((p) => (
              <div key={p.id} className="rounded-lg border border-line bg-surface p-2.5 text-[12.5px]">
                <div className="flex items-center gap-1.5">
                  <span className="font-medium text-ink-800">{p.canonical}</span>
                  <span className="text-ink-400">≈</span>
                  <span className="text-ink-700">{p.variant}</span>
                </div>
                <p className="mt-1 text-ink-500">{p.rationale}</p>
                <div className="mt-2 flex gap-1.5">
                  <button
                    type="button"
                    disabled={busyId === p.id}
                    onClick={() => void handleApprove(p.id)}
                    className="rounded-md border border-low-200 bg-low-50 px-2.5 py-1 text-low-700 hover:opacity-80 disabled:opacity-50"
                  >
                    核准
                  </button>
                  <button
                    type="button"
                    disabled={busyId === p.id}
                    onClick={() => void handleReject(p.id)}
                    className="rounded-md border border-line px-2.5 py-1 text-ink-600 hover:bg-accent-soft disabled:opacity-50"
                  >
                    拒絕
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        {error && <p className="mt-1.5 text-[11.5px] text-high-700">{error}</p>}
      </section>

      <p className="text-[11.5px] text-ink-400">
        核准後會建立新版 term_aliases 設定並立即生效於下一次比對；拒絕不會留下任何設定變更。
      </p>
    </div>
  );
}
