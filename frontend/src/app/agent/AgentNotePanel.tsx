import type { AgentItem } from '../../types';
import type { AgentNote } from '../../state/useAgent';
import { CONFIDENCE_LABEL, IMPACT_LABEL, VERDICT_LABEL } from './agentLabels';
import { CitationRow } from './CitationPill';

type JumpToPage = (side: 'old' | 'new', pdfPage: number | null, differenceId?: string) => void;

export function AiTag() {
  return <span className="rounded-full bg-accent-soft px-1.5 py-0.5 text-[10.5px] font-medium text-ink-600">AI 推論</span>;
}

export function ImpactList({ item }: { item: AgentItem }) {
  const rows = (Object.keys(IMPACT_LABEL) as (keyof typeof IMPACT_LABEL)[]).filter((k) => item.impact[k].length > 0);
  if (rows.length === 0) return null;
  return (
    <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5">
      {rows.map((k) => (
        <div key={k} className="contents">
          <dt className="text-ink-400">{IMPACT_LABEL[k]}</dt>
          <dd className="text-ink-700">{item.impact[k].join('、')}</dd>
        </div>
      ))}
    </dl>
  );
}

// 差異卡展開後的「Agent 說明」(spec §4.4). The suggestion only prefills the
// ReviewBar — nothing is written until the reviewer presses 確認.
export function AgentNotePanel({
  differenceId,
  note,
  prefilled,
  onJumpToPage,
}: {
  differenceId: string;
  note: AgentNote | undefined;
  prefilled: boolean;
  onJumpToPage: JumpToPage;
}) {
  if (!note || (note.items.length === 0 && !note.suggestion)) return null;
  const { suggestion } = note;
  return (
    <div className="mt-2 space-y-2 rounded-md border border-line bg-surface-2 p-2 text-[12px]">
      <div className="flex items-center gap-1.5">
        <span className="font-medium text-ink-800">Agent 說明</span>
        <AiTag />
      </div>

      {suggestion && (
        <div>
          <p className="text-ink-700">
            <span className="text-ink-400">建議判定：</span>
            <strong className="font-medium text-ink-900">{VERDICT_LABEL[suggestion.verdict]}</strong>
            <span className="text-ink-400">・</span>
            {suggestion.reason} <CitationRow citations={suggestion.citations} onJumpToPage={onJumpToPage} />
          </p>
          <p className="mt-0.5 text-[11px] text-ink-400">
            {prefilled ? '已在下方預先選好；按「確認並前往下一筆」才會送出，你也可以改掉。' : '這筆已有人工判定，Agent 建議僅供對照。'}
          </p>
        </div>
      )}

      {note.items.map((item, i) => {
        const siblings = item.difference_ids.filter((id) => id !== differenceId);
        return (
        <div key={i} className="border-t border-line-soft pt-1.5 first:border-t-0 first:pt-0">
          <p className="text-ink-700">
            <span className="rounded-full border border-line bg-surface px-1.5 py-0.5 text-[11px] font-medium text-ink-800">{item.action}</span>{' '}
            {item.action_detail}
          </p>
          <ImpactList item={item} />
          <p className="mt-1 flex flex-wrap items-center gap-1 text-[11px] text-ink-400">
            {CONFIDENCE_LABEL[item.confidence]}
            {siblings.length > 0 && <span>・與 {siblings.join('、')} 同一項</span>}
            <CitationRow citations={item.citations} onJumpToPage={onJumpToPage} />
          </p>
        </div>
        );
      })}
    </div>
  );
}
