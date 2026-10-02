import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { ChevronLeft, ChevronRight, MessageSquare, X } from 'lucide-react';
import type { AgentAnswer, AgentRun } from '../../types';
import { LLM_PROVIDER_OPTIONS } from '../../lib/llmProviders';
import { GlossaryList, PendingList } from './AgentBriefingView';
import { CitationPill } from './CitationPill';

type JumpToPage = (side: 'old' | 'new', pdfPage: number | null, differenceId?: string) => void;

const MAX_QUESTION = 500;
const DEFAULT_SUGGESTED = ['如果我只有五分鐘，我最應該知道哪些事情？', '哪些變更需要停用舊版的檢查表？', '這次改版影響哪些檢查項目？'];

interface AgentQAProps {
  answers: AgentRun<AgentAnswer>[];
  pending: AgentRun | null;
  canAsk: boolean;
  onAsk: (question: string) => void;
  onJumpToPage: JumpToPage;
  suggested?: string[];
  // false when nothing on screen can be jumped to (a chain without a
  // pairwise comparison open) — citations render as plain labels.
  interactive?: boolean;
}

// 問答 (spec §4.3, §4.6). 2026-10-02 使用者回饋「對話匡太小看不清楚，希望像
// 卡牌一樣可以切換」— the Q&A itself lives in a large centred window, one
// question per card; the right panel keeps only this entry. Only questions
// about the loaded documents get an answer; anything else comes back as
// fixed server text, and an answer the server couldn't verify is withheld.
export function AgentQA(props: AgentQAProps) {
  const { answers, pending } = props;
  const [open, setOpen] = useState(false);
  const entryRef = useRef<HTMLButtonElement>(null);
  const latest = pending ?? answers[answers.length - 1] ?? null;

  function close() {
    setOpen(false);
    entryRef.current?.focus();
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <h4 className="text-[12.5px] font-semibold text-ink-800">問文件</h4>
        {answers.length > 0 && <span className="text-[11.5px] text-ink-500">已問 {answers.length} 題</span>}
        <button
          ref={entryRef}
          type="button"
          onClick={() => setOpen(true)}
          className="ml-auto inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[12px] text-ink-700 hover:bg-accent-soft"
        >
          <MessageSquare size={13} />
          {answers.length > 0 || pending ? '開啟問答' : '提問'}
        </button>
      </div>
      {latest && (
        <p className="truncate text-[12px] text-ink-500" title={latest.question ?? ''}>
          {pending ? '查證中：' : '最新：'}
          {latest.question}
        </p>
      )}
      {open && <AgentQADialog {...props} onClose={close} />}
    </div>
  );
}

function AgentQADialog({
  answers,
  pending,
  canAsk,
  onAsk,
  onJumpToPage,
  suggested = DEFAULT_SUGGESTED,
  interactive = true,
  onClose,
}: AgentQAProps & { onClose: () => void }) {
  const cards: AgentRun[] = pending ? [...answers, pending] : answers;
  const [index, setIndex] = useState(Math.max(cards.length - 1, 0));
  const [question, setQuestion] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const busy = pending !== null;
  const cardCount = cards.length;
  const current = cards[Math.min(index, cardCount - 1)] ?? null;

  // Follow the conversation: a newly asked or newly answered question
  // becomes the card on screen.
  useEffect(() => {
    setIndex(Math.max(cards.length - 1, 0));
  }, [cards.length, pending?.run_id]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // On the window, not the dialog element: reaching the first or last card
  // disables the button that was just clicked, which drops focus out of the
  // dialog — a listener on the dialog would stop hearing the arrow keys.
  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.isComposing) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return; // arrows move the caret there
      if (e.key === 'ArrowLeft') setIndex((i) => Math.max(i - 1, 0));
      if (e.key === 'ArrowRight') setIndex((i) => Math.min(i + 1, cardCount - 1));
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, cardCount]);

  function submit() {
    const q = question.trim();
    if (!q || busy) return;
    onAsk(q);
    setQuestion('');
  }

  function onInputKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter is a new line. Enter that confirms an IME
    // candidate (注音／倉頡選字) must not send the half-typed question.
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      submit();
    }
  }

  // Jumping to a cited page needs the document in view.
  const jumpAndClose: JumpToPage = (side, page, differenceId) => {
    onJumpToPage(side, page, differenceId);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3 sm:p-6" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="agent-qa-title"
        onClick={(e) => e.stopPropagation()}
        className="flex h-[min(88vh,920px)] w-full max-w-[880px] flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-[var(--sh-2)]"
      >
        <header className="flex items-center gap-2 border-b border-line px-4 py-3">
          <MessageSquare size={16} className="text-ink-500" />
          <h2 id="agent-qa-title" className="text-[15px] font-semibold text-ink-900">
            問文件
          </h2>
          <span className="hidden text-[12.5px] text-ink-500 sm:inline">只回答與載入文件有關的問題；回答是建議，判定由覆核人決定。</span>
          <button type="button" onClick={onClose} aria-label="關閉問答" className="ml-auto rounded-md p-1 text-ink-500 hover:bg-accent-soft hover:text-ink-900">
            <X size={18} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4 sm:px-7">
          {current ? (
            <QuestionCard run={current} onJumpToPage={jumpAndClose} interactive={interactive} />
          ) : (
            <div className="space-y-3">
              <p className="text-[15px] text-ink-600">可以問這次比對的兩份文件，例如：</p>
              {canAsk && (
                <div className="flex flex-wrap gap-2">
                  {suggested.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => onAsk(s)}
                      className="rounded-full border border-line px-3 py-1.5 text-[14px] text-ink-700 hover:bg-accent-soft hover:text-ink-900"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {cards.length > 1 && (
          <nav aria-label="切換問答" className="flex items-center justify-center gap-3 border-t border-line px-4 py-2">
            <button
              type="button"
              onClick={() => setIndex((i) => Math.max(i - 1, 0))}
              disabled={index <= 0}
              aria-label="上一題"
              className="rounded-md border border-line p-1.5 text-ink-700 hover:bg-accent-soft disabled:opacity-35"
            >
              <ChevronLeft size={18} />
            </button>
            <span className="min-w-[4.5rem] text-center text-[13.5px] tabular-nums text-ink-600" aria-live="polite">
              {Math.min(index, cards.length - 1) + 1} / {cards.length}
            </span>
            <button
              type="button"
              onClick={() => setIndex((i) => Math.min(i + 1, cards.length - 1))}
              disabled={index >= cards.length - 1}
              aria-label="下一題"
              className="rounded-md border border-line p-1.5 text-ink-700 hover:bg-accent-soft disabled:opacity-35"
            >
              <ChevronRight size={18} />
            </button>
          </nav>
        )}

        {canAsk && (
          <footer className="border-t border-line px-4 py-3">
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={question}
                onChange={(e) => setQuestion(e.target.value.slice(0, MAX_QUESTION))}
                onKeyDown={onInputKey}
                rows={2}
                placeholder="問載入文件的內容…"
                aria-label="問文件"
                disabled={busy}
                className="max-h-40 min-h-[3.25rem] min-w-0 flex-1 resize-y rounded-md border border-line bg-surface px-3 py-2 text-[14.5px] leading-relaxed text-ink-800 outline-none placeholder:text-ink-400 focus:border-ink-500 disabled:opacity-60"
              />
              <button
                type="button"
                onClick={submit}
                disabled={busy || question.trim() === ''}
                className="rounded-md bg-ink-800 px-4 py-2 text-[14px] font-medium text-on-accent disabled:cursor-not-allowed disabled:opacity-40"
              >
                送出
              </button>
            </div>
            <p className="mt-1 text-[11.5px] text-ink-400">Enter 送出・Shift + Enter 換行・← → 切換題目・Esc 關閉</p>
          </footer>
        )}
      </div>
    </div>
  );
}

const ANSWER_STYLE: Record<AgentAnswer['answer_type'], string> = {
  answer: 'border-line bg-surface text-ink-900',
  not_in_documents: 'border-line bg-surface-2 text-ink-600',
  out_of_scope: 'border-line bg-surface-2 text-ink-600',
  unverified: 'border-med-200 bg-med-50 text-med-700',
};

const PROVIDER_LABEL: Record<string, string> = { anthropic: 'Claude', gemini: 'Gemini', bedrock: 'Bedrock', openai: 'ChatGPT' };

function clock(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function duration(from: string, to: string | null): string | null {
  if (!to) return null;
  const seconds = Math.max(0, Math.round((new Date(to).getTime() - new Date(from).getTime()) / 1000));
  if (Number.isNaN(seconds)) return null;
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}

function modelLabel(run: AgentRun): string {
  if (!run.model) return 'AI';
  const known = LLM_PROVIDER_OPTIONS.flatMap((p) => p.models).find((m) => m.id === run.model)?.label;
  const provider = run.provider ? PROVIDER_LABEL[run.provider] ?? run.provider : null;
  return [provider, known ?? run.model].filter(Boolean).join(' · ');
}

// Time, duration, model and tokens for one answer (2026-10-02: 「備注時間與消耗 token」).
function RunMeta({ run }: { run: AgentRun }) {
  const usage = run.usage ?? {};
  const input = (usage.input_tokens ?? 0) + (usage.cache_read_input_tokens ?? 0) + (usage.cache_creation_input_tokens ?? 0);
  const output = usage.output_tokens ?? 0;
  const parts = [
    clock(run.finished_at) && `${clock(run.finished_at)} 回答`,
    duration(run.started_at, run.finished_at) && `耗時 ${duration(run.started_at, run.finished_at)}`,
    input + output > 0 && `輸入 ${input.toLocaleString()}・輸出 ${output.toLocaleString()} tokens`,
    (usage.cache_read_input_tokens ?? 0) > 0 && `其中快取 ${(usage.cache_read_input_tokens ?? 0).toLocaleString()}`,
  ].filter(Boolean);
  if (parts.length === 0) return null;
  return <p className="text-[12px] tabular-nums text-ink-400">{parts.join('・')}</p>;
}

function Speaker({ who, detail }: { who: string; detail?: string | null }) {
  return (
    <p className="mb-1 text-[12px] text-ink-500">
      <span className="font-semibold text-ink-700">{who}</span>
      {detail && <span>・{detail}</span>}
    </p>
  );
}

function QuestionCard({ run, onJumpToPage, interactive }: { run: AgentRun; onJumpToPage: JumpToPage; interactive: boolean }) {
  const answer = run.kind === 'question' ? (run.result as AgentAnswer | null) : null;
  return (
    <article className="space-y-5">
      {/* 使用者 — the question, on the right like a chat. */}
      <div className="flex justify-end">
        <div className="max-w-[85%]">
          <div className="text-right">
            <Speaker who="你" detail={clock(run.started_at) ? `${clock(run.started_at)} 提問` : null} />
          </div>
          <h3 className="rounded-2xl rounded-tr-sm bg-ink-800 px-4 py-2.5 text-[15.5px] font-medium leading-relaxed text-on-accent">{run.question}</h3>
        </div>
      </div>

      {/* AI — the answer, on the left. */}
      <div className="max-w-[92%] space-y-3">
        <Speaker who="AI" detail={modelLabel(run) === 'AI' ? null : modelLabel(run)} />

        {run.status === 'running' && (
          <div className="rounded-2xl rounded-tl-sm border border-line bg-surface-2 px-4 py-3 text-[14px] text-ink-600" aria-live="polite">
            <p className="font-medium text-ink-800">查證中…</p>
            <ol className="mt-1 space-y-0.5">
              {run.steps.slice(-6).map((s, i) => (
                <li key={i} className={s.ok ? 'text-ink-500' : 'text-med-700'}>
                  · {s.label}
                </li>
              ))}
            </ol>
          </div>
        )}

        {run.status === 'failed' && (
          <div className="rounded-2xl rounded-tl-sm border border-high-200 bg-high-50 px-4 py-3 text-[15px] text-high-700">{run.error ?? 'Agent 執行失敗。'}</div>
        )}

        {answer && (
          <>
            <div className={`rounded-2xl rounded-tl-sm border px-4 py-3 text-[15.5px] leading-relaxed ${ANSWER_STYLE[answer.answer_type]}`}>
              {answer.uses_briefing && (
                <p className="mb-2 inline-block rounded-md bg-accent-soft px-2 py-0.5 text-[12.5px] font-medium text-ink-700">含覆核簡報的 AI 建議，不是文件規定</p>
              )}
              <p className="whitespace-pre-line">{answer.text}</p>
              {answer.withheld ? (
                <p className="mt-2 text-[13px] text-med-700">有 {answer.withheld} 句的數字在引用原文裡找不到，沒有顯示，見下方「待確認」。</p>
              ) : null}
            </div>

            {answer.citations.length > 0 && (
              <section className="space-y-2">
                <h4 className="text-[13px] font-semibold text-ink-700">引用原文</h4>
                <ul className="space-y-2">
                  {answer.citations.map((c, i) => (
                    <li key={`${c.session_id ?? ''}-${c.side}-${c.pdf_page}-${i}`} className="flex items-start gap-2 text-[14px] text-ink-700">
                      <span className="shrink-0 pt-0.5">
                        <CitationPill citation={c} onJumpToPage={onJumpToPage} interactive={interactive} />
                      </span>
                      <span className="leading-relaxed">{c.quote}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {answer.pending.length > 0 && (
              <section className="space-y-2">
                <h4 className="text-[13px] font-semibold text-ink-700">待確認</h4>
                <PendingList pending={answer.pending} large />
              </section>
            )}

            {answer.glossary.length > 0 && (
              <section className="space-y-2">
                <h4 className="text-[13px] font-semibold text-ink-700">名詞解釋</h4>
                <GlossaryList entries={answer.glossary} large />
              </section>
            )}
          </>
        )}

        <RunMeta run={run} />
      </div>
    </article>
  );
}
