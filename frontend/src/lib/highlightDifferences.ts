import type { DifferenceRecord } from '../types';

export type MarkKind = 'add' | 'del' | 'mod';

export interface TextSegment {
  key: string;
  text: string;
  kind: MarkKind | null; // null = ordinary page text, not part of any difference
  differenceId: string | null;
}

const KIND_BY_CHANGE_TYPE: Record<DifferenceRecord['change_type'], MarkKind> = {
  新增: 'add',
  刪除: 'del',
  修改: 'mod',
};

/** Finds every `differences` entry whose `old`/`new` text (for the given
 * `side`) is a substring of this page's reconstructed text, and splits the
 * page text into a sequence of segments — some plain, some tagged with
 * which difference they belong to and what kind of change it was. Purely a
 * frontend computation over data the API already returns (page text +
 * difference old/new text); no backend change needed.
 *
 * Overlapping matches (rare — e.g. one line quoted inside another's
 * context) keep only the first (leftmost, then longest) match; a
 * difference whose text isn't found on this page (extraction/normalization
 * can shift wording slightly) is simply skipped rather than guessed at.
 *
 * One normalization DOES need explicit handling: `pages.json` serves each
 * page's raw `page.raw_text` (untouched PyMuPDF output), while
 * `DifferenceRecord.old/new.text` comes from `extraction.py`'s NFKC-
 * normalized `lines` — so e.g. a full-width "，" in the raw page text is an
 * ASCII "," in the difference text, and a plain `indexOf` never matches. We
 * fall back to matching against an NFKC-normalized copy of the page text;
 * since NFKC is length-preserving for the punctuation this project actually
 * hits (fullwidth→halfwidth, one code unit each), the resulting offsets are
 * still valid into the ORIGINAL page text — verified via the length check
 * below rather than assumed. */
export function markDifferencesInPageText(
  pageText: string,
  differences: DifferenceRecord[],
  side: 'old' | 'new',
): TextSegment[] {
  interface Range {
    start: number;
    end: number;
    kind: MarkKind;
    differenceId: string;
  }

  const normalizedPage = pageText.normalize('NFKC');
  const canUseNormalizedOffsets = normalizedPage.length === pageText.length;

  const candidates: Range[] = [];
  for (const d of differences) {
    const span = side === 'old' ? d.old : d.new;
    const text = span?.text;
    if (!text) continue;
    let start = pageText.indexOf(text);
    if (start === -1 && canUseNormalizedOffsets) {
      start = normalizedPage.indexOf(text.normalize('NFKC'));
    }
    if (start === -1) continue;
    candidates.push({ start, end: start + text.length, kind: KIND_BY_CHANGE_TYPE[d.change_type], differenceId: d.id });
  }

  candidates.sort((a, b) => a.start - b.start || b.end - a.end);
  const ranges: Range[] = [];
  let lastEnd = -1;
  for (const r of candidates) {
    if (r.start >= lastEnd) {
      ranges.push(r);
      lastEnd = r.end;
    }
  }

  const segments: TextSegment[] = [];
  let cursor = 0;
  let plainIndex = 0;
  for (const r of ranges) {
    if (r.start > cursor) {
      segments.push({ key: `plain-${plainIndex++}`, text: pageText.slice(cursor, r.start), kind: null, differenceId: null });
    }
    segments.push({
      key: `mark-${r.differenceId}`,
      text: pageText.slice(r.start, r.end),
      kind: r.kind,
      differenceId: r.differenceId,
    });
    cursor = r.end;
  }
  if (cursor < pageText.length) {
    segments.push({ key: `plain-${plainIndex++}`, text: pageText.slice(cursor), kind: null, differenceId: null });
  }
  return segments;
}
