import { useEffect, useRef, type ReactNode } from 'react';
import { ChevronDown, X } from 'lucide-react';
import { HELP_SECTIONS } from './helpContent';

interface HelpPageProps {
  open: boolean;
  onClose: () => void;
}

// 使用說明 — full-page overlay opened from TopBar (plimsoll-review-agent-spec.md
// §5). Static copy lives in helpContent.tsx so the page chrome and the words
// can change independently; 名詞解釋 is the one live section (GlossarySection).
// Unmounted when closed, so nothing underneath — comparison, review drafts,
// scroll positions — is touched by opening it.
//
// 2026-09-28 改版（降低閱讀成本＋圖文示範）— 兩層結構：「三步上手」一直展開，
// 在 1280×800 不捲動就看得到；其餘 7 節收進原生 <details>，預設收合。
// HELP_SECTIONS 裡只有第一節（quickstart）標 alwaysOpen，其餘一律是收合面板。
export function HelpPage({ open, onClose }: HelpPageProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  function jumpTo(id: string) {
    const container = scrollRef.current;
    const target = container?.querySelector<HTMLElement>(`#help-${id}`);
    if (!container || !target) return;
    // A collapsed reference panel is a native <details>: open it before
    // measuring offsetTop, or the scroll lands on its (still-collapsed)
    // summary instead of showing the content the TOC promised.
    if (target instanceof HTMLDetailsElement && !target.open) target.open = true;
    // Instant, not smooth: a jump in a reference page should land now, and
    // this respects reduced-motion preferences without extra handling.
    container.scrollTo({ top: target.offsetTop - 16 });
  }

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="help-title" className="fixed inset-0 z-50 flex flex-col bg-canvas">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
        <h2 id="help-title" className="text-[15px] font-semibold text-ink-900">
          使用說明
        </h2>
        <span className="hidden text-[12.5px] text-ink-500 sm:inline">如何用 Plimsoll 比對兩版船舶技術文件、覆核差異並匯出報告</span>
        <button
          ref={closeRef}
          type="button"
          onClick={onClose}
          title="關閉（Esc）"
          aria-label="關閉使用說明"
          className="ml-auto rounded-md p-1.5 text-ink-500 hover:bg-accent-soft hover:text-ink-800"
        >
          <X size={18} />
        </button>
      </header>

      {/* Narrow screens (a judge opening the tunnel URL on a phone) lose the
          side nav, so the same list becomes a scrollable row under the header. */}
      <nav aria-label="使用說明目錄" className="flex shrink-0 gap-1 overflow-x-auto border-b border-line bg-surface px-3 py-2 md:hidden">
        {HELP_SECTIONS.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => jumpTo(s.id)}
            className="shrink-0 rounded-full border border-line px-2.5 py-1 text-[12px] text-ink-600 hover:bg-accent-soft hover:text-ink-900"
          >
            {s.title}
          </button>
        ))}
      </nav>

      <div className="flex min-h-0 flex-1">
        <nav aria-label="使用說明目錄" className="hidden w-52 shrink-0 overflow-y-auto border-r border-line bg-surface p-3 md:block">
          <ol className="space-y-0.5">
            {HELP_SECTIONS.map((s, i) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => jumpTo(s.id)}
                  className="w-full rounded-md px-2 py-1.5 text-left text-[13px] text-ink-600 hover:bg-accent-soft hover:text-ink-900"
                >
                  <span className="mr-1.5 tabular-nums text-ink-400">{i + 1}</span>
                  {s.title}
                </button>
              </li>
            ))}
          </ol>
        </nav>

        <div ref={scrollRef} className="relative min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-4xl space-y-5 px-5 py-6">
            {HELP_SECTIONS.map((s, i) =>
              s.alwaysOpen ? (
                <QuickstartSection key={s.id} id={s.id} index={i + 1} title={s.title}>
                  {s.body}
                </QuickstartSection>
              ) : (
                <ReferencePanel key={s.id} id={s.id} index={i + 1} title={s.title}>
                  {s.body}
                </ReferencePanel>
              ),
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// 一直展開的「三步上手」——不是 <details>，讀者一開啟使用說明就看到，不需要
// 點開任何東西。
function QuickstartSection({ id, index, title, children }: { id: string; index: number; title: string; children: ReactNode }) {
  return (
    <section id={`help-${id}`} aria-labelledby={`help-${id}-title`}>
      <h3 id={`help-${id}-title`} className="mb-2 flex items-baseline gap-2 text-[16px] font-semibold text-ink-900">
        <span className="text-[13px] tabular-nums text-ink-400">{String(index).padStart(2, '0')}</span>
        {title}
      </h3>
      {children}
    </section>
  );
}

// 其餘 7 節：原生 <details>/<summary>，預設收合，讀起來只是一份目錄；點開
// 才看到內容。TOC 點擊會由 jumpTo() 直接設定 .open 再捲動過來。
function ReferencePanel({ id, index, title, children }: { id: string; index: number; title: string; children: ReactNode }) {
  return (
    <details id={`help-${id}`} className="group rounded-xl border border-line bg-surface">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-[14.5px] font-semibold text-ink-900 hover:bg-accent-soft [&::-webkit-details-marker]:hidden">
        <span className="text-[13px] tabular-nums text-ink-400">{String(index).padStart(2, '0')}</span>
        <span className="flex-1">{title}</span>
        <ChevronDown size={16} className="shrink-0 text-ink-400 transition-transform duration-150 group-open:rotate-180" />
      </summary>
      <div className="space-y-3 border-t border-line px-4 py-4 text-[13.5px] leading-relaxed text-ink-700">{children}</div>
    </details>
  );
}
