import { useState, type FormEvent } from 'react';
import type { AgentAnswer, AgentRun } from '../../types';
import { GlossaryList, PendingList } from './AgentBriefingView';
import { CitationRow } from './CitationPill';

type JumpToPage = (side: 'old' | 'new', pdfPage: number | null, differenceId?: string) => void;

const MAX_QUESTION = 500;
const DEFAULT_SUGGESTED = ['哪些變更需要停用舊版的檢查表？', '這次改版影響哪些檢查項目？', '這次改版的原因是什麼？'];

function AnswerView({ run, onJumpToPage, interactive }: { run: AgentRun<AgentAnswer>; onJumpToPage: JumpToPage; interactive: boolean }) {
  const answer = run.result;
  return (
    <li className="space-y-1">
      <p className="text-[12px] text-ink-500">問：{run.question}</p>
      {run.status === 'failed' && <p className="text-[12.5px] text-high-700">{run.error ?? 'Agent 執行失敗。'}</p>}
      {answer && (
        <div
          className={`rounded-md border px-2 py-1.5 text-[12.5px] ${
            answer.answer_type === 'answer' ? 'border-line bg-surface text-ink-800' : 'border-line bg-surface-2 text-ink-500'
          }`}
        >
          <p className="whitespace-pre-line">{answer.text}</p>
          {answer.citations.length > 0 && (
            <div className="mt-1">
              <CitationRow citations={answer.citations} onJumpToPage={onJumpToPage} interactive={interactive} />
            </div>
          )}
          {answer.pending.length > 0 && (
            <div className="mt-1.5">
              <PendingList pending={answer.pending} />
            </div>
          )}
          {answer.glossary.length > 0 && (
            <div className="mt-1.5">
              <GlossaryList entries={answer.glossary} />
            </div>
          )}
        </div>
      )}
    </li>
  );
}

// 問答 (spec §4.3, §4.6). Only questions about the two loaded documents get
// an answer; anything else comes back as fixed server text, and an answer
// without a verified citation is downgraded to 「文件中找不到依據」.
export function AgentQA({
  answers,
  pending,
  canAsk,
  onAsk,
  onJumpToPage,
  suggested = DEFAULT_SUGGESTED,
  interactive = true,
}: {
  answers: AgentRun<AgentAnswer>[];
  pending: AgentRun | null;
  canAsk: boolean;
  onAsk: (question: string) => void;
  onJumpToPage: JumpToPage;
  suggested?: string[];
  // false when nothing on screen can be jumped to (a chain without a
  // pairwise comparison open) — citations render as plain labels.
  interactive?: boolean;
}) {
  const [question, setQuestion] = useState('');
  const busy = pending !== null;

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const q = question.trim();
    if (!q || busy) return;
    onAsk(q);
    setQuestion('');
  }

  return (
    <div className="space-y-2">
      <h4 className="text-[12.5px] font-semibold text-ink-800">問文件</h4>

      {answers.length > 0 && (
        <ul className="space-y-2.5">
          {answers.map((run) => (
            <AnswerView key={run.run_id} run={run} onJumpToPage={onJumpToPage} interactive={interactive} />
          ))}
        </ul>
      )}

      {pending && (
        <p className="text-[12px] text-ink-500">
          問：{pending.question}
          <br />
          查證中…{pending.steps.length > 0 && `（${pending.steps[pending.steps.length - 1].label}）`}
        </p>
      )}

      {canAsk && (
        <>
          {answers.length === 0 && !busy && (
            <div className="flex flex-wrap gap-1">
              {suggested.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => onAsk(s)}
                  className="rounded-full border border-line px-2 py-0.5 text-[11.5px] text-ink-600 hover:bg-accent-soft hover:text-ink-900"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
          <form onSubmit={submit} className="flex gap-1.5">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value.slice(0, MAX_QUESTION))}
              placeholder="問載入文件的內容…"
              aria-label="問文件"
              disabled={busy}
              className="min-w-0 flex-1 rounded-md border border-line bg-surface px-2 py-1.5 text-[12.5px] text-ink-800 outline-none placeholder:text-ink-400 focus:border-ink-500 disabled:opacity-60"
            />
            <button
              type="submit"
              disabled={busy || question.trim() === ''}
              className="rounded-md bg-ink-800 px-3 py-1.5 text-[12.5px] font-medium text-on-accent disabled:cursor-not-allowed disabled:opacity-40"
            >
              送出
            </button>
          </form>
          <p className="text-[11px] text-ink-400">只回答與載入的文件有關的問題；回答是建議，判定由覆核人決定。</p>
        </>
      )}
    </div>
  );
}
