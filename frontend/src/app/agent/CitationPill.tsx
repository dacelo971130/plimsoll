import type { AgentCitation } from '../../types';

interface CitationPillProps {
  citation: AgentCitation;
  onJumpToPage: (side: 'old' | 'new', pdfPage: number | null, differenceId?: string) => void;
  interactive?: boolean;
}

// ui-spec §3.2 引用 pill「D01 · 新 p.4」— click jumps the compare view to that
// page (and flashes the mark when it's tied to a difference); the verbatim
// quote the server verified is in the tooltip.
export function CitationPill({ citation, onJumpToPage, interactive = true }: CitationPillProps) {
  const page = citation.print_label ?? citation.pdf_page;
  const id = citation.difference_id ? `${citation.difference_id} · ` : '';
  // Another comparison (an earlier chain version, a historical case) isn't
  // on screen, so there's nothing to jump to: a plain label, not a button
  // that does nothing (不做假的).
  if (citation.session_id || !interactive) {
    return (
      <span title={`原文：${citation.quote}`} className="rounded-full border border-line-soft bg-surface-2 px-1.5 py-0.5 text-[11px] text-ink-500">
        {id}
        {citation.version_label ?? (citation.side === 'old' ? '舊' : '新')} p.{page}
      </span>
    );
  }
  const side = citation.side === 'old' ? '舊' : '新';
  return (
    <button
      type="button"
      title={`原文：${citation.quote}`}
      onClick={() => onJumpToPage(citation.side, citation.pdf_page, citation.difference_id ?? undefined)}
      className="rounded-full border border-line bg-surface px-1.5 py-0.5 text-[11px] text-ink-600 hover:border-ink-400 hover:bg-accent-soft hover:text-ink-900"
    >
      {id}
      {side} p.{page}
    </button>
  );
}

export function CitationRow({ citations, onJumpToPage, interactive }: { citations: AgentCitation[] } & Omit<CitationPillProps, 'citation'>) {
  if (citations.length === 0) return null;
  return (
    <span className="inline-flex flex-wrap gap-1 align-middle">
      {citations.map((c, i) => (
        <CitationPill key={`${c.session_id ?? ''}-${c.side}-${c.pdf_page}-${i}`} citation={c} onJumpToPage={onJumpToPage} interactive={interactive} />
      ))}
    </span>
  );
}
