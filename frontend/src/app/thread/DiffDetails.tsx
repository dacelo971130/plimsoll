import { useState } from 'react';
import { charDiff } from '../../lib/charDiff';
import { ruleLabel } from '../../lib/ruleLabels';
import type { DifferenceRecord } from '../../types';
import { CharDiffText } from './CharDiffText';
import { pageLabel } from './diffFormat';

// The expanded body of one difference, shared by the right-panel list card
// (size md) and the 專注簽核 deck's enlarged card (size lg, 2026-09-27 使用者
// 回饋「卡牌置中，文字與卡牌都放大」) so the two never drift apart in what
// they show — only in how big they show it.
export type DetailSize = 'md' | 'lg';

// 2026-09-28 使用者回饋「內文過長需要先大量滑動才能看到其他按鈕」— a whole-
// page insert/delete (常見於大幅改版的真實文件，如 SOLAS 整頁位移) can dump
// thousands of characters into d.old/d.new; collapsed by default past this
// many characters (either side), with a toggle to see the full text. Short
// diffs (the common case) render exactly as before, no toggle at all.
const LONG_TEXT_CHAR_THRESHOLD = 50;

// Char-level old→new diff with its page reference.
export function DiffTextBlock({ d, size = 'md' }: { d: DifferenceRecord; size?: DetailSize }) {
  const lg = size === 'lg';
  const longestSide = Math.max(d.old?.text.length ?? 0, d.new?.text.length ?? 0);
  const isLong = longestSide > LONG_TEXT_CHAR_THRESHOLD;
  const [expanded, setExpanded] = useState(false);
  const collapsed = isLong && !expanded;
  const baseTextClass = lg ? 'text-[21px] leading-[1.7]' : 'text-[13px] leading-relaxed';

  return (
    <div className={lg ? 'mt-4 rounded-xl bg-surface-2 p-5' : 'mt-1.5 rounded-md bg-surface-2 p-2'}>
      <div className={`font-medium uppercase text-ink-500 ${lg ? 'mb-1.5 text-[13px]' : 'text-[10.5px]'}`}>
        舊 {pageLabel(d.old)} → 新 {pageLabel(d.new)}
      </div>
      <CharDiffText
        oldText={d.old?.text ?? ''}
        newText={d.new?.text ?? ''}
        className={collapsed ? `${baseTextClass} line-clamp-3` : baseTextClass}
      />
      {isLong && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="mt-1.5 text-[11.5px] font-medium text-ink-500 hover:text-ink-700"
        >
          {expanded ? '收合內文 ▲' : '內文較長，點擊顯示完整內容 ▼'}
        </button>
      )}
    </div>
  );
}

// 2026-09-28 「專注簽核」卡牌改版採用產品網站 .diffcard 格式 — the deck's own
// pieces (only FocusReviewDeck.tsx uses these; DiffTextBlock above stays the
// right-panel list's md rendering, untouched).

// A quick per-side character budget for ChangeDelta below: past this, the
// changed span no longer compresses into one glanceable "10 bar → 8 bar"
// line (it starts wrapping into a paragraph, which is what the source
// quotes underneath are for), so the delta line is omitted instead of
// overflowing. Checked AFTER the token-widen pass below, since that's what
// actually gets rendered.
const CHANGE_DELTA_MAX_CHARS = 40;

// Characters a widen pass (below) may cross into an adjacent `equal` run
// without cutting a number or part code in half.
const DELTA_TOKEN_RE = /[A-Za-z0-9.%_/-]/;

// Longest run of DELTA_TOKEN_RE chars at one end of `text`: its suffix when
// widening backward (before the changed range), its prefix when widening
// forward (after it).
function tokenRun(text: string, fromEnd: boolean): string {
  if (fromEnd) {
    let i = text.length;
    while (i > 0 && DELTA_TOKEN_RE.test(text[i - 1])) i--;
    return text.slice(i);
  }
  let i = 0;
  while (i < text.length && DELTA_TOKEN_RE.test(text[i])) i++;
  return text.slice(0, i);
}

// old→new delta line (site's .dc-delta: "10 bar → 8 bar", old struck through,
// new bold). Derived from charDiff's own segments, not a separate diff —
// same algorithm the source quotes below use, so the two never disagree.
//
// 2026-09-28 修正 — this used to join every `del` run and every `ins` run
// across the WHOLE text, which silently drops any `equal` run that sits
// BETWEEN two changes. For "20.0%"→"19.8%" the shared "." is one such run:
// joining only the del/ins fragments produced "200"→"198" — a different
// number, not just a cosmetic gap (this line feeds a safety review). Fixed
// by taking ONE contiguous slice of segments, first changed run to last
// changed run inclusive, and keeping every `equal` run inside that slice on
// BOTH sides (it reads the same either way) instead of dropping it — so
// "20.0%"→"19.8%" now keeps its "." correctly. A number or part code can
// still straddle the slice's own edge (D05: "CP-1[00→20]" would otherwise
// render as a lone struck "0"), so both edges are then widened outward
// through the adjacent `equal` run's matching token chars only.
export function ChangeDelta({ d }: { d: DifferenceRecord }) {
  if (!d.old || !d.new) return null;
  const segments = charDiff(d.old.text, d.new.text);
  const firstChanged = segments.findIndex((s) => s.type !== 'equal');
  if (firstChanged === -1) return null; // texts are char-for-char identical — not a real difference
  let lastChanged = firstChanged;
  for (let i = segments.length - 1; i > firstChanged; i--) {
    if (segments[i].type !== 'equal') {
      lastChanged = i;
      break;
    }
  }

  let oldStr = '';
  let newStr = '';
  for (let i = firstChanged; i <= lastChanged; i++) {
    const seg = segments[i];
    if (seg.type !== 'ins') oldStr += seg.text; // equal + del
    if (seg.type !== 'del') newStr += seg.text; // equal + ins
  }

  // charDiff only ever merges consecutive same-type runs, so there's at
  // most one `equal` run immediately outside each edge of the slice.
  const before = firstChanged > 0 && segments[firstChanged - 1].type === 'equal' ? segments[firstChanged - 1].text : '';
  const after = lastChanged < segments.length - 1 && segments[lastChanged + 1].type === 'equal' ? segments[lastChanged + 1].text : '';
  const prefix = tokenRun(before, true);
  const suffix = tokenRun(after, false);
  oldStr = prefix + oldStr + suffix;
  newStr = prefix + newStr + suffix;

  if (!oldStr || !newStr) return null; // pure insertion/deletion inside an otherwise-unchanged sentence
  if (oldStr.length > CHANGE_DELTA_MAX_CHARS || newStr.length > CHANGE_DELTA_MAX_CHARS) return null;
  return (
    <div className="mt-5 flex flex-wrap items-center gap-2.5 font-mono text-[22px]">
      <span className="line-through decoration-2" style={{ color: 'var(--diff-del)', textDecorationColor: 'var(--diff-del)' }}>
        {oldStr}
      </span>
      <span className="text-ink-400">→</span>
      <span className="font-bold text-ink-900">{newStr}</span>
    </div>
  );
}

// Deck-only page-label formatting (2026-09-28 品牌對齊): the site's cite
// reads "舊版 p.12 → 新版 p.14", but pageLabel() (diffFormat.ts) alone
// returns a bare print label like "3" whenever the PDF has a real print
// label — no unit prefix at all. Only wrap a PURELY numeric label in "p.";
// a non-numeric print label, an already-prefixed "p.3" fallback, or the "—"
// no-page placeholder all fail the digits-only test and pass through
// unchanged. pageLabel() itself is untouched — DiffListMessage's 查看
// button and DiffTextBlock's md rendering above still show the bare label.
// Not exported (FocusReviewDeck.tsx keeps its own copy for the head cite) —
// a plain-function export alongside this file's component exports breaks
// Fast Refresh.
function deckPageLabel(span: DifferenceRecord['old']): string {
  const label = pageLabel(span);
  return /^\d+$/.test(label) ? `p.${label}` : label;
}

// Site's two-column .dc-src: 舊版原文／新版原文, each quoting that version's
// text with the changed characters marked (CharDiffText's `side` prop) so a
// reviewer can read either version on its own, not just the merged delta
// above. A side with no span at all (the other half of an addition/deletion)
// shows a muted placeholder instead of an empty box.
export function SourceColumns({ d }: { d: DifferenceRecord }) {
  const textSize = 'text-[18px] leading-[1.7]';
  return (
    <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div className="rounded-xl border border-line bg-surface-2 p-4">
        <div className="mb-1.5 text-[13px] font-semibold text-ink-500">舊版原文 · {deckPageLabel(d.old)}</div>
        {d.old ? (
          <CharDiffText oldText={d.old.text} newText={d.new?.text ?? ''} side="old" className={textSize} />
        ) : (
          <p className={`text-ink-400 ${textSize}`}>（這一版沒有這段）</p>
        )}
      </div>
      <div className="rounded-xl border border-line bg-surface-2 p-4">
        <div className="mb-1.5 text-[13px] font-semibold text-ink-500">新版原文 · {deckPageLabel(d.new)}</div>
        {d.new ? (
          <CharDiffText oldText={d.old?.text ?? ''} newText={d.new.text} side="new" className={textSize} />
        ) : (
          <p className={`text-ink-400 ${textSize}`}>（這一版沒有這段）</p>
        )}
      </div>
    </div>
  );
}

// 變更解讀／觸發規則／建議處置.
export function DiffReadout({ d, size = 'md' }: { d: DifferenceRecord; size?: DetailSize }) {
  const lg = size === 'lg';
  const gap = lg ? 'mt-2' : 'mt-1';
  return (
    <div
      className={`border border-line text-ink-600 ${
        lg ? 'mt-4 rounded-xl p-4 text-[15px] leading-relaxed' : 'mt-2 rounded-md p-2 text-[12px]'
      }`}
    >
      <p>
        <span className="text-ink-400">變更解讀：</span>
        {d.explanation}
      </p>
      {d.rule_id && (
        <p className={gap}>
          <span className="text-ink-400">觸發規則：</span>
          {ruleLabel(d.rule_id)}
        </p>
      )}
      <p className={gap}>
        <span className="text-ink-400">建議處置：</span>
        {d.recommended_action}
      </p>
    </div>
  );
}

const PAGE_ALIGNMENT_LABEL: Record<string, string> = {
  matched: '兩版本頁面已對齊，以下為像素比對偵測到的變更區塊',
  unmatched_old: '舊版本存在此工程圖頁，新版本已移除',
  unmatched_new: '新版本新增此工程圖頁，舊版本沒有對應頁面',
  size_mismatch: '新舊版本頁面尺寸不同，無法逐像素比對，請人工並排確認',
};

// P5 §26 — the expanded body for a `kind: "drawing"` difference: pixel-diff
// crop thumbnails (before/after) instead of a text-based char diff, since
// there's no meaningful text to align here.
export function DrawingRegions({ d }: { d: DifferenceRecord }) {
  return (
    <div className="mt-1.5 space-y-2 rounded-md bg-surface-2 p-2">
      <p className="text-[11.5px] text-ink-500">{PAGE_ALIGNMENT_LABEL[d.page_alignment ?? 'matched']}</p>
      {(d.regions ?? []).map((region, i) => (
        <div key={i} className="rounded-md border border-line bg-surface p-2">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <div>
              <div className="text-[10.5px] font-medium uppercase text-ink-500">舊版</div>
              {region.old_crop_png_b64 ? (
                <img
                  src={`data:image/png;base64,${region.old_crop_png_b64}`}
                  alt="舊版工程圖區塊"
                  className="mt-1 w-full rounded border border-line"
                />
              ) : (
                <div className="mt-1 rounded border border-dashed border-line p-3 text-center text-[11px] text-ink-400">
                  （此區塊為新增）
                </div>
              )}
            </div>
            <div>
              <div className="text-[10.5px] font-medium uppercase text-ink-500">新版</div>
              {region.new_crop_png_b64 ? (
                <img
                  src={`data:image/png;base64,${region.new_crop_png_b64}`}
                  alt="新版工程圖區塊"
                  className="mt-1 w-full rounded border border-line"
                />
              ) : (
                <div className="mt-1 rounded border border-dashed border-line p-3 text-center text-[11px] text-ink-400">
                  （此區塊已刪除）
                </div>
              )}
            </div>
          </div>
          {(region.component_label || region.change_summary) && (
            <div className="mt-1.5 flex items-start gap-1.5 text-[11.5px] text-ink-600">
              <span className="rounded-full border border-line bg-accent-soft px-1.5 py-0.5 text-ink-700">AI 讀圖</span>
              <span>
                {region.component_label && <strong className="text-ink-800">{region.component_label}：</strong>}
                {region.change_summary}
                {region.confidence != null && (
                  <span className="ml-1 text-ink-400">（信心 {(region.confidence * 100).toFixed(0)}%）</span>
                )}
              </span>
            </div>
          )}
        </div>
      ))}
      {(d.regions ?? []).length === 0 && <p className="text-[11.5px] text-ink-400">此變更沒有可標示的像素區塊。</p>}
    </div>
  );
}

const SEMANTIC_CHANGE_TYPE_LABEL: Record<string, string> = {
  clarification: '用詞更精確（語意未變）',
  scope_narrowing: '適用範圍／條件收窄',
  scope_widening: '適用範圍／條件擴大',
  procedure_change: '操作程序實質變更',
  responsibility_shift: '負責角色／單位變更',
  no_semantic_change: '純文字潤飾（語意不變）',
  unclear: '模型無法判斷',
};

// W7a — the model's suggestion is ALWAYS presented as a suggestion, never a
// verdict: it never replaces the RiskPill/ai_risk shown elsewhere on this
// card, only adds context alongside it.
export function SemanticSuggestionPanel({ d, size = 'md' }: { d: DifferenceRecord; size?: DetailSize }) {
  const s = d.ai_semantic_suggestion;
  if (!s) return null;
  return (
    <div
      className={`rounded-md border border-dashed border-accent-soft bg-accent-soft/40 text-ink-700 ${
        size === 'lg' ? 'mt-4 p-3 text-[14px]' : 'mt-2 p-2 text-[12px]'
      }`}
    >
      <div className="flex items-center gap-1.5">
        <span className="rounded-full border border-line bg-surface px-1.5 py-0.5 text-[11px] font-medium">
          AI 語意建議
        </span>
        <span className="text-ink-600">{SEMANTIC_CHANGE_TYPE_LABEL[s.semantic_change_type] ?? s.semantic_change_type}</span>
        {s.suggest_escalate && s.suggested_risk && (
          <span className="rounded-full border border-med-200 bg-med-50 px-1.5 py-0.5 text-[11px] text-med-700">
            建議調高至 {s.suggested_risk}
          </span>
        )}
      </div>
      <p className="mt-1 text-ink-600">{s.rationale}</p>
      <p className="mt-1 text-[11px] text-ink-400">此為 AI 建議，非定論；最終風險等級仍由規則引擎與人工覆核決定。</p>
    </div>
  );
}
