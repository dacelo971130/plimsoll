import type { ReactNode } from 'react';
import type { AgentBriefing, AgentGlossaryEntry, AgentPending } from '../../types';
import { CONFIDENCE_LABEL, WARNING_LABEL } from './agentLabels';
import { CitationRow } from './CitationPill';
import { ImpactList } from './AgentNotePanel';

type JumpToPage = (side: 'old' | 'new', pdfPage: number | null, differenceId?: string) => void;

// Same wording the server uses when the documents don't state a reason.
const UNSTATED_REASON = '文件未載明';

function Block({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <h4 className="text-[12.5px] font-semibold text-ink-800">
        {title}
        {count !== undefined && <span className="ml-1 font-normal tabular-nums text-ink-400">{count}</span>}
      </h4>
      {children}
    </div>
  );
}

function DiffLink({ id, onFocus }: { id: string; onFocus: (id: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onFocus(id)}
      title="在待核准清單中打開這筆"
      className="rounded-md border border-line px-1.5 py-0.5 text-[11.5px] font-medium text-ink-800 hover:border-ink-400 hover:bg-accent-soft"
    >
      {id}
    </button>
  );
}

export function PendingList({ pending }: { pending: AgentPending[] }) {
  if (pending.length === 0) return null;
  return (
    <ul className="space-y-1 text-[12px]">
      {pending.map((p, i) => (
        <li key={i} className="rounded-md border border-med-200 bg-med-50 px-2 py-1 text-med-700">
          <span className="font-medium">{p.topic}</span>・{p.reason}
        </li>
      ))}
    </ul>
  );
}

export function GlossaryList({ entries }: { entries: AgentGlossaryEntry[] }) {
  if (entries.length === 0) return null;
  return (
    <dl className="space-y-1 text-[12px]">
      {entries.map((g) => (
        <div key={g.term}>
          <dt className="font-medium text-ink-800">{g.term}</dt>
          <dd className="text-ink-600">{g.definition}</dd>
        </div>
      ))}
    </dl>
  );
}

// 覆核簡報 (spec §4.2, §4.5). Fixed order: 一句話結論 → 警示 → 優先覆核 →
// 影響與建議 → 批次確認 → 變更原因追溯 → 歷史案例 → 待確認 → 名詞解釋. Every line here passed the server's
// citation / number / glossary checks; whatever didn't is under 待確認.
export function AgentBriefingView({
  briefing,
  onJumpToPage,
  onFocusDifference,
  batch,
}: {
  briefing: AgentBriefing;
  onJumpToPage: JumpToPage;
  onFocusDifference: (id: string) => void;
  batch: ReactNode;
}) {
  const checked = briefing.verification.citations_checked ?? 0;
  const failedClaims = briefing.verification.claims_to_pending ?? 0;
  const undefinedTerms = briefing.verification.terms_to_pending ?? 0;

  return (
    <div className="space-y-3 text-[12.5px] text-ink-700">
      <p className="text-[13px] leading-relaxed text-ink-900">{briefing.summary}</p>

      {briefing.warnings.length > 0 && (
        <Block title="警示" count={briefing.warnings.length}>
          <ul className="space-y-1">
            {briefing.warnings.map((w, i) => (
              <li key={i} className="rounded-md border border-line bg-surface-2 px-2 py-1">
                <span className="font-medium text-ink-800">{WARNING_LABEL[w.kind]}</span>・{w.message}{' '}
                <CitationRow citations={w.citations} onJumpToPage={onJumpToPage} />
              </li>
            ))}
          </ul>
        </Block>
      )}

      {briefing.priority.length > 0 && (
        <Block title="建議先看" count={briefing.priority.length}>
          <ol className="space-y-1.5">
            {briefing.priority.map((p, i) => (
              <li key={p.difference_id} className="flex gap-2">
                <span className="mt-0.5 w-4 shrink-0 text-right tabular-nums text-ink-400">{i + 1}</span>
                <span>
                  <DiffLink id={p.difference_id} onFocus={onFocusDifference} /> {p.reason}{' '}
                  <CitationRow citations={p.citations} onJumpToPage={onJumpToPage} />
                </span>
              </li>
            ))}
          </ol>
        </Block>
      )}

      {briefing.items.length > 0 && (
        <Block title="影響與建議動作" count={briefing.items.length}>
          <ul className="space-y-2">
            {briefing.items.map((item, i) => (
              <li key={i} className="rounded-md border border-line bg-surface-2 p-2">
                <div className="flex flex-wrap items-center gap-1">
                  {item.difference_ids.map((id) => (
                    <DiffLink key={id} id={id} onFocus={onFocusDifference} />
                  ))}
                  <span className="rounded-full border border-line bg-surface px-1.5 py-0.5 text-[11px] font-medium text-ink-800">
                    {item.action}
                  </span>
                  <span className="text-[11px] text-ink-400">{CONFIDENCE_LABEL[item.confidence]}</span>
                </div>
                <p className="mt-1">{item.action_detail}</p>
                <ImpactList item={item} />
                <div className="mt-1">
                  <CitationRow citations={item.citations} onJumpToPage={onJumpToPage} />
                </div>
              </li>
            ))}
          </ul>
        </Block>
      )}

      {batch}

      {briefing.cause_trace.length > 0 && (
        <Block title="變更原因追溯" count={briefing.cause_trace.length}>
          <ul className="space-y-1.5">
            {briefing.cause_trace.map((t, i) => (
              <li key={i} className="rounded-md border border-line bg-surface-2 p-2">
                <p>
                  <span className="font-medium text-ink-800">{t.parameter}</span>
                  <span className="text-ink-400">・在 </span>
                  <span className="font-medium text-ink-800">{t.changed_in_version}</span>
                  <span className="text-ink-400"> 改變</span>
                </p>
                <p className={`mt-0.5 ${t.reason === UNSTATED_REASON ? 'text-ink-400' : ''}`}>原因：{t.reason}</p>
                <div className="mt-1">
                  <CitationRow citations={t.citations} onJumpToPage={onJumpToPage} />
                </div>
              </li>
            ))}
          </ul>
        </Block>
      )}

      {briefing.history.length > 0 && (
        <Block title="歷史案例" count={briefing.history.length}>
          <ul className="space-y-1.5">
            {briefing.history.map((h) => (
              <li key={`${h.session_id}-${h.difference_id}`} className="rounded-md border border-line bg-surface-2 p-2">
                <p className="text-[11.5px] text-ink-500">
                  {h.title ?? '過去的比對'}・{h.versions}・{h.difference_id}
                </p>
                <p className="mt-0.5">{h.note}</p>
                <div className="mt-1">
                  <CitationRow citations={h.citations} onJumpToPage={onJumpToPage} />
                </div>
              </li>
            ))}
          </ul>
        </Block>
      )}

      {briefing.pending.length > 0 && (
        <Block title="待確認" count={briefing.pending.length}>
          <PendingList pending={briefing.pending} />
        </Block>
      )}

      {briefing.glossary.length > 0 && (
        <Block title="名詞解釋">
          <GlossaryList entries={briefing.glossary} />
        </Block>
      )}

      <p className="text-[11px] text-ink-400">
        已逐字核對 {checked} 個引用
        {failedClaims > 0 && `；${failedClaims} 項說法因引用或數字對不上原文，移到「待確認」`}
        {undefinedTerms > 0 && `；${undefinedTerms} 個名詞沒有核准的定義，移到「待確認」`}。這是建議，判定由你決定。
      </p>
    </div>
  );
}
