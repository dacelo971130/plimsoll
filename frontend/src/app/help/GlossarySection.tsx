import { useEffect, useMemo, useState } from 'react';
import { getGlossary } from '../../lib/api';
import type { Glossary, GlossaryTerm } from '../../types';

// 使用說明 → 名詞解釋. Definitions come only from the controlled glossary
// (data/store/config/glossary/v{N}.json via GET /api/config/glossary) — the
// same file the review agent and the sign-off report appendix will cite, so
// the three can never disagree. Nothing here writes a definition of its own:
// a draft table says it's a draft, a pending term says 待確認, a missing file
// says so (a Docker volume seeded before the glossary existed has none).
type LoadState = { kind: 'loading' } | { kind: 'error' } | { kind: 'ready'; glossary: Glossary };

function matches(term: GlossaryTerm, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [term.term, ...term.aliases, term.definition].some((text) => text.toLowerCase().includes(q));
}

function groupByCategory(terms: GlossaryTerm[]): [string, GlossaryTerm[]][] {
  // Keep the file's own category order — the glossary is authored in reading
  // order (差異 → 風險 → 頁碼 → 覆核 …), not alphabetically.
  const groups = new Map<string, GlossaryTerm[]>();
  for (const term of terms) {
    const list = groups.get(term.category) ?? [];
    list.push(term);
    groups.set(term.category, list);
  }
  return [...groups.entries()];
}

export function GlossarySection() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' });
  const [query, setQuery] = useState('');

  useEffect(() => {
    let cancelled = false;
    getGlossary()
      .then((glossary) => !cancelled && setState({ kind: 'ready', glossary }))
      .catch(() => !cancelled && setState({ kind: 'error' }));
    return () => {
      cancelled = true;
    };
  }, []);

  const groups = useMemo(
    () => (state.kind === 'ready' ? groupByCategory(state.glossary.terms.filter((t) => matches(t, query))) : []),
    [state, query],
  );

  if (state.kind === 'loading') return <p className="text-[13px] text-ink-500">載入名詞解釋中…</p>;
  if (state.kind === 'error') return <p className="text-[13px] text-ink-500">名詞解釋暫時無法載入，請稍後再開一次使用說明。</p>;

  const { glossary } = state;
  if (glossary.terms.length === 0) return <p className="text-[13px] text-ink-500">目前沒有提供名詞解釋。</p>;

  return (
    <div className="space-y-4">
      {glossary.simulated && (
        <p className="rounded-lg border border-med-200 bg-med-50 px-3 py-2 text-[12.5px] text-med-700">
          這份名詞解釋是模擬版：船舶與輪機名詞的定義參考全國法規資料庫的法定用詞定義與國家教育研究院的標準譯名整理，尚未經專業人員審核。請以文件原文與覆核人判斷為準；正式簽核報告暫不附這些定義。
        </p>
      )}

      {glossary.status !== 'approved' && (
        <p className="rounded-lg border border-med-200 bg-med-50 px-3 py-2 text-[12.5px] text-med-700">
          這份名詞解釋還是草稿，尚未經人工審核。標示「待確認」的名詞，定義還沒有定案，請以文件原文與覆核人判斷為準。
        </p>
      )}

      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="搜尋名詞"
        aria-label="搜尋名詞"
        className="w-full rounded-md border border-line bg-surface px-3 py-1.5 text-[13px] text-ink-800 outline-none placeholder:text-ink-400 focus:border-ink-500 sm:w-72"
      />

      {groups.length === 0 && <p className="text-[13px] text-ink-500">找不到符合「{query.trim()}」的名詞。</p>}

      {groups.map(([category, terms]) => (
        <div key={category}>
          <h4 className="mb-2 text-[12px] font-medium tracking-wide text-ink-500">{category}</h4>
          <dl className="divide-y divide-line-soft rounded-lg border border-line bg-surface">
            {terms.map((t) => (
              <div key={t.term} className="px-3 py-2.5">
                <dt className="flex flex-wrap items-center gap-2 text-[13.5px] font-medium text-ink-900">
                  {t.term}
                  {t.status === 'pending' && (
                    <span className="rounded-full bg-med-50 px-1.5 py-0.5 text-[11px] font-medium text-med-700">待確認</span>
                  )}
                </dt>
                {t.aliases.length > 0 && <dd className="text-[12px] text-ink-500">也稱：{t.aliases.join('、')}</dd>}
                <dd className="mt-1 text-[13px] leading-relaxed text-ink-700">{t.definition}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </div>
  );
}
