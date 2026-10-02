"""Deterministic diff + rule classification (architecture-decisions-A-B.md
§25-26 Stage 1/2): "確定性層決定哪裡變/變什麼類型（免 token、可稽核）；LLM 只做
語意解讀；規則引擎＋人工擁有最終判定。" No LLM call anywhere in this module.

Alignment happens in two layers (W3): a document-level page-to-page mapping
(`_align_pages`) finds which old page corresponds to which new page — so an
inserted/deleted page doesn't misalign every page after it — then, within
each matched page pair, a page-hash short-circuit (§27a: identical text
skips straight to 'equal') followed by `difflib.SequenceMatcher` per page
(handles inserted/deleted lines correctly, unlike naive positional diffing).
Within an equal-length `replace` run we still zip line-for-line for
sentence-level granularity — the common case of "N sentences reworded into N
sentences" — falling back to a whole-block diff only when lengths don't line
up 1:1.

Both layers align on the W4 term-canonicalized view (`lines_canonical`), not
the reviewer-facing original text (`lines`) — see backend.services.normalize.
"""

from __future__ import annotations

import difflib
import functools
import re
from dataclasses import dataclass

from backend.models.config_models import Ruleset
from backend.services import text_similarity
from backend.services.extraction import ExtractedDocument, PageContent

RiskLevel = str  # 'High' | 'Medium' | 'Low' — see backend.models.config_models

_NUMBER_WITH_UNIT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:°C|bar|mpa|%)", re.IGNORECASE)

# v2 rules (rulesets/v2.json: parts_change / applicability_change /
# step_order_change) — three deterministic flags that close the "大改但無規
# 則觸發" gap without any LLM call (see docs/redesign/plimsoll-improvement-plan.html §02).
_PART_NUMBER_RE = re.compile(r"[A-Z]{2,4}-\d{2,4}")
# A "word" for order-only-changed detection: a run of Latin letters/digits
# (so part numbers stay one token) or a single CJK character — there's no
# dictionary-based Chinese segmenter in this project, so per-character is the
# cheapest deterministic proxy for "斷詞", and it's exact for pure clause
# reordering (the only case this flag is meant to catch).
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[一-鿿]")

# W3 page-to-page mapping (docs/redesign/plimsoll-improvement-plan.html §02):
# the minimum page-similarity for two pages to be considered the same page
# across versions rather than an unrelated insert/delete, for the PRIMARY
# (strict) alignment pass — see _PAGE_RECONCILE_THRESHOLD below for the
# second, more lenient pass. 0.6 carries over numerically from the old
# 6-line-fingerprint signal, but it's re-validated here for the TF-IDF
# signal, not assumed: sweeping 0.6 vs 0.5 against both SOLAS and CCS (see
# docs/redesign/plimsoll-real-document-smoketest-2026-09.html §7 conflict 1,
# option 丙) produced the same matched-page counts either way, so 0.6 is kept
# as the more conservative choice for the pass that has no leftover-only
# safety net.
_PAGE_MATCH_THRESHOLD = 0.6


@dataclass
class PageRef:
    pdf_page: int | None
    print_label: str | None
    label_source: str


@dataclass
class SourceSpan:
    page: PageRef
    text: str


@dataclass
class DifferenceRecord:
    id: str
    change_type: str  # '新增' | '刪除' | '修改'
    ai_risk: str
    ai_confidence: str
    explanation: str
    affected: str
    recommended_action: str
    old: SourceSpan | None
    new: SourceSpan | None
    ruleset_version: str
    rule_id: str
    data_origin: str = "computed"
    # W7a: optional model-proposed reading of a `default`-rule difference —
    # NEVER written by anything in this module. Set only by
    # backend.services.llm.residual.enrich_differences_with_semantic_suggestions(),
    # an explicit, separate, opt-in step (see that module's docstring for why).
    ai_semantic_suggestion: dict | None = None


_WHITESPACE_RE = re.compile(r"\s+")
# Below this many characters, a "same characters, rotated" match is too
# likely to be coincidental (short/repetitive fragments) to trust.
_MIN_REFLOW_CHARS = 20


def _is_reflow_only(old_text: str, new_text: str) -> bool:
    """True when `old_text`/`new_text` hold exactly the same characters and
    differ only in where a line-wrap boundary falls — a PDF re-typesetting
    artifact (an edit elsewhere on the page nudges every following line's
    word-wrap point) rather than a real content change. Checked as a cyclic
    rotation after removing ALL whitespace: a pure respacing is a rotation by
    zero, and a word that crossed the line boundary is a rotation by that
    word's length — both are the same underlying phenomenon. A short
    minimum-length guard avoids false matches on short, repetitive
    fragments. See docs/redesign/plimsoll-real-document-smoketest-2026-09.html
    §1 (the UNECE "operating sequence reordered" false alarm, D776) — that
    line pair is a rotation-by-2-characters of the same words."""
    a, b = _WHITESPACE_RE.sub("", old_text), _WHITESPACE_RE.sub("", new_text)
    if len(a) < _MIN_REFLOW_CHARS or len(a) != len(b):
        return False
    return a in (b + b)


@dataclass
class _LinePair:
    """One aligned (or unmatched) line, carrying both views: `*_raw` is what
    the reviewer sees (DifferenceRecord.old/new), `*_key` is what actually
    drove the alignment and is what gets fed to classify() — normally the
    same text, but W4 canonicalization means they can differ (see
    _diff_page_lines)."""

    old_raw: str | None
    new_raw: str | None
    old_key: str | None
    new_key: str | None


# --------------------------------------------------------------------------
# line-pair alignment
# --------------------------------------------------------------------------

def _diff_page_lines(old_raw: list[str], new_raw: list[str], old_key: list[str], new_key: list[str]) -> list[_LinePair]:
    """Returns one `_LinePair` per non-equal run. Equal-length replace/insert/
    delete runs are zipped line-for-line; uneven-length replace runs fall
    back to one whole-block pair.

    Alignment (`SequenceMatcher`, and the "equal" skip) runs on `*_key` — the
    W4 term-canonicalized view — not `*_raw`: a line that changed only by a
    synonym swap has identical `_key` text on both sides, so it's tagged
    "equal" and never surfaces as a difference at all, exactly like a
    byte-identical line always has. `*_raw` rides along on the same index
    ranges purely for display; it never drives what counts as a match."""
    sm = difflib.SequenceMatcher(None, old_key, new_key, autojunk=False)
    pairs: list[_LinePair] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        old_raw_seg, new_raw_seg = old_raw[i1:i2], new_raw[j1:j2]
        old_key_seg, new_key_seg = old_key[i1:i2], new_key[j1:j2]
        if tag == "replace" and _is_reflow_only("\n".join(old_raw_seg), "\n".join(new_raw_seg)):
            continue  # line-wrap reflow, not a content change — treat like "equal"
        if tag == "replace" and len(old_raw_seg) == len(new_raw_seg):
            pairs.extend(
                _LinePair(o_r, n_r, o_k, n_k)
                for o_r, n_r, o_k, n_k in zip(old_raw_seg, new_raw_seg, old_key_seg, new_key_seg)
            )
        elif tag == "delete":
            pairs.extend(_LinePair(o_r, None, o_k, None) for o_r, o_k in zip(old_raw_seg, old_key_seg))
        elif tag == "insert":
            pairs.extend(_LinePair(None, n_r, None, n_k) for n_r, n_k in zip(new_raw_seg, new_key_seg))
        else:  # uneven replace — no natural 1:1 line correspondence
            pairs.append(
                _LinePair(
                    "\n".join(old_raw_seg), "\n".join(new_raw_seg), "\n".join(old_key_seg), "\n".join(new_key_seg)
                )
            )
    return pairs


# --------------------------------------------------------------------------
# rule classification
# --------------------------------------------------------------------------

def _numbers_with_unit(text: str | None) -> set[str]:
    return set(_NUMBER_WITH_UNIT_RE.findall(text or ""))


_NUMBER_PREFIX_RE = re.compile(r"[\d.]+")


def numbers_with_unit(text: str | None) -> list[tuple[float, str]]:
    """Public, ORDER-preserving counterpart to `_numbers_with_unit` (which
    only needs a set for the numeric_change flag) — e.g. "85°C" -> (85.0,
    "°C"). Used by backend.services.chain (W5) to build per-version
    parameter series from a document's own text, independent of any diff."""
    out: list[tuple[float, str]] = []
    for raw in _NUMBER_WITH_UNIT_RE.findall(text or ""):
        num_match = _NUMBER_PREFIX_RE.match(raw)
        out.append((float(num_match.group()), raw[num_match.end() :].strip()))
    return out


def _part_numbers(text: str | None) -> set[str]:
    return set(_PART_NUMBER_RE.findall(text or ""))


@functools.lru_cache(maxsize=None)
def _ascii_word_pattern(term: str) -> re.Pattern:
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)


def _term_present(text: str, term: str) -> bool:
    """Whole-word, case-insensitive match for an ASCII alnum term (e.g. the
    ruleset's "bar"/"mpa"). A plain substring check also fires inside
    unrelated English words — "bar" inside "embarkation", "mpa" inside
    "compartment"/"impaired"/"compatible" — and, being case-sensitive, would
    never match the "MPa" unit-symbol capitalization that `numeric_change`
    itself already accepts via `_NUMBER_WITH_UNIT_RE`'s re.IGNORECASE (see
    docs/redesign/plimsoll-real-document-smoketest-2026-09.html §1). CJK
    terms fall back to plain substring — this project has no Chinese word
    segmenter (see `_TOKEN_RE`), so substring is the same proxy already used
    everywhere else for Chinese text."""
    if term.isascii() and term.isalnum():
        return bool(_ascii_word_pattern(term).search(text))
    return term in text


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


_THRESHOLD_RE = re.compile(r"^(>=|<=|>|<|==)\s*(-?\d+(?:\.\d+)?)$")
_THRESHOLD_OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}


def _condition_matches(expected, actual) -> bool:
    """Plain equality for boolean `when` values (every rule before v2's
    cumulative_drift). A string like ">=3" or ">=0.01" (cumulative_drift's
    series_length/total_delta_ratio thresholds — W6) is instead parsed as a
    numeric comparison against `actual`. Existing boolean rules never take
    this branch, so this is purely additive."""
    if isinstance(expected, str) and (m := _THRESHOLD_RE.match(expected)):
        if actual is None:
            return False
        op, threshold = m.group(1), float(m.group(2))
        return _THRESHOLD_OPS[op](actual, threshold)
    return actual == expected


def _rule_matches(when: dict, flags: dict) -> bool:
    for key, expected in when.items():
        if key == "any_of":
            if not any(flags.get(k) for k in expected):
                return False
        elif not _condition_matches(expected, flags.get(key)):
            return False
    return True


def _chain_drift_flags(chain_history: list[float] | None) -> dict:
    """W6: series_length / direction_consistent / total_delta_ratio, derived
    from a plain ordered list of values for one canonical parameter across a
    chain (see backend.services.chain.extract_parameter_points). Absent
    chain_history, these simply never match any threshold (None fails every
    comparison in _condition_matches) — a pairwise-only call is unaffected."""
    if not chain_history or len(chain_history) < 2:
        return {"series_length": len(chain_history or []), "direction_consistent": False, "total_delta_ratio": None}
    deltas = [b - a for a, b in zip(chain_history, chain_history[1:])]
    direction_consistent = all(d > 0 for d in deltas) or all(d < 0 for d in deltas)
    first, last = chain_history[0], chain_history[-1]
    total_delta_ratio = abs(last - first) / abs(first) if first else 0.0
    return {
        "series_length": len(chain_history),
        "direction_consistent": direction_consistent,
        "total_delta_ratio": total_delta_ratio,
    }


def classify(
    old_text: str | None, new_text: str | None, ruleset: Ruleset, *, chain_history: list[float] | None = None
) -> dict:
    """Returns the matching rule's `then` dict plus `rule_id`. Raises if the
    ruleset has no catch-all `default` rule — that is a config authoring bug,
    not a runtime state we should silently paper over.

    `chain_history` (W6, keyword-only, default None) is an ordered list of a
    single parameter's values across a chain of versions — see
    backend.services.chain. It's the ONLY way this function's behavior can
    change relative to before W6 landed: every existing caller passes two
    args positionally and gets flags identical to pre-W6 classify(), so none
    of the ~70 pre-existing tests needed to change."""
    old_nums = _numbers_with_unit(old_text)
    new_nums = _numbers_with_unit(new_text)
    old_parts = _part_numbers(old_text)
    new_parts = _part_numbers(new_text)
    combined = f"{old_text or ''}\n{new_text or ''}"

    # step_order_change needs both sides present — a 新增/刪除 pair (one side
    # None) can never be a pure reorder of an existing sentence.
    old_tokens = _tokenize(old_text) if old_text is not None else None
    new_tokens = _tokenize(new_text) if new_text is not None else None

    flags = {
        "numeric_change": bool(old_nums or new_nums) and old_nums != new_nums,
        "safety_terms": any(_term_present(combined, term) for term in ruleset.safety_terms),
        "obligation_change": (
            {t for t in ruleset.obligation_terms if _term_present(old_text or "", t)}
            != {t for t in ruleset.obligation_terms if _term_present(new_text or "", t)}
        ),
        # v2: 零件料號／型號樣式（如 CP-100 → CP-120）變更 —— 不帶單位，
        # _NUMBER_WITH_UNIT_RE 抓不到，需要獨立的 token 集合比對。
        "part_number_change": bool(old_parts or new_parts) and old_parts != new_parts,
        # v2: 適用範圍詞（詞表見 ruleset.applicability_terms）出現在這句變動裡。
        "applicability_change": (
            any(_term_present(combined, term) for term in ruleset.applicability_terms) and old_text != new_text
        ),
        # v2: 斷詞後的多重集合相同（同樣的詞、同樣的次數）但序列不同 —— 純步驟
        # 順序對調，不是一般改寫。
        "step_order_change": (
            old_tokens is not None
            and new_tokens is not None
            and old_tokens != new_tokens
            and sorted(old_tokens) == sorted(new_tokens)
        ),
    }
    flags.update(_chain_drift_flags(chain_history))

    for rule in sorted(ruleset.rules, key=lambda r: r.priority):
        if _rule_matches(rule.when, flags):
            return {**rule.then, "rule_id": rule.id}

    raise ValueError(f"ruleset {ruleset.version} has no matching rule (missing a default?) for flags={flags}")


# --------------------------------------------------------------------------
# document-level comparison
# --------------------------------------------------------------------------

def _page_ref(page: PageContent | None) -> PageRef:
    if page is None:
        return PageRef(pdf_page=None, print_label=None, label_source="unknown")
    return PageRef(pdf_page=page.pdf_page, print_label=page.print_label, label_source=page.label_source)


def _align_pages(old_pages: list[PageContent], new_pages: list[PageContent]) -> list[tuple[int | None, int | None]]:
    """Global (Needleman-Wunsch-style) alignment over page fingerprints —
    replaces naive positional zip so inserting/deleting a page anywhere in
    the document doesn't misalign every page after it (W3:
    docs/redesign/plimsoll-improvement-plan.html §02, "插入一頁全盤崩壞").

    Returns (old_idx, new_idx) pairs in document order; one side is None for
    a page with no match above `_PAGE_MATCH_THRESHOLD` on the other side
    (i.e. a whole-page insert or delete). Zero-cost gaps + a hard threshold
    (rather than a soft penalty) means a weakly-similar pair is never forced
    to "match" just because skipping both pages scores the same as skipping
    one — the diagonal transition is only ever available when the fingerprint
    similarity actually clears the bar.
    """
    m, n = len(old_pages), len(new_pages)
    # One shared corpus (old + new together) so the IDF weighting reflects
    # the whole document pair, not each side separately; computed once, not
    # per (i, j) — see text_similarity.build_vectors.
    all_texts = ["".join(p.lines_canonical) for p in old_pages + new_pages]
    all_vectors = text_similarity.build_vectors(all_texts)
    old_vecs, new_vecs = all_vectors[:m], all_vectors[m:]
    sim = [[text_similarity.cosine(old_vecs[i], new_vecs[j]) for j in range(n)] for i in range(m)]

    dp = [[0.0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            best = max(dp[i - 1][j], dp[i][j - 1])
            if sim[i - 1][j - 1] >= _PAGE_MATCH_THRESHOLD:
                best = max(best, dp[i - 1][j - 1] + sim[i - 1][j - 1])
            dp[i][j] = best

    pairs: list[tuple[int | None, int | None]] = []
    i, j = m, n
    while i > 0 or j > 0:
        can_match = i > 0 and j > 0 and sim[i - 1][j - 1] >= _PAGE_MATCH_THRESHOLD
        if can_match and dp[i][j] == dp[i - 1][j - 1] + sim[i - 1][j - 1]:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j]:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    pairs.reverse()
    return _reconcile_shifted_pages(pairs, old_vecs, new_vecs)


# Lower than _PAGE_MATCH_THRESHOLD — used only as a second pass over the
# (small) leftover of pages the primary alignment above left unmatched.
#
# Calibrated empirically for the TF-IDF signal against both real target
# documents (see docs/redesign/plimsoll-real-document-smoketest-2026-09.html
# §7 conflict 1, option 丙), not reused from the old fingerprint signal's 0.5:
# - SOLAS 2004->2020 (409 old pages, the motivating "big rewrite" case):
#   spot-checked the 17-126 lowest-scoring reconciled pairs at several
#   candidate thresholds down to 0.35; every pair down to ~0.40 was a genuine
#   same-regulation match, just diluted by 2020's per-paragraph "Effective
#   Date / For Ships Constructed" amendment-history insertions (the same
#   phenomenon that sank the old signal). Below ~0.40 quality was untested at
#   scale — 0.40 is the floor actually validated, not an arbitrary round
#   number. Both of Opus's originally-validated cases clear it: old p101 (see
#   _PAGE_MATCH_THRESHOLD above) matches in the PRIMARY pass at 0.63; old p41
#   -> new p17 needs this reconcile pass, scoring 0.496.
# - CCS 2026->2027 (the actual target document, ~1900 pages, mostly
#   incremental revision): only 17 pairs needed this second pass at 0.40, all
#   spot-checked as genuine (same section/table, renumbered or reworded).
#   Lowering this further didn't recover more real pages on CCS (the
#   remaining gap is almost entirely pages with zero extractable tokens,
#   which text_similarity.cosine deliberately never matches — see its
#   docstring) so there was nothing to trade the higher false-match risk
#   against.
_PAGE_RECONCILE_THRESHOLD = 0.4


def _reconcile_shifted_pages(
    pairs: list[tuple[int | None, int | None]],
    old_vecs: list[text_similarity.Vector],
    new_vecs: list[text_similarity.Vector],
) -> list[tuple[int | None, int | None]]:
    """Second, lower-threshold pass over pages the primary alignment left
    unmatched (i.e. a `(idx, None)`/`(None, idx)` entry above) — recovers
    pages that merely shifted position (an insert/delete elsewhere in the
    document nudged every following page) rather than genuinely changing.

    Without this, a shifted page is reported as an unrelated whole-page
    delete + insert, and `_whole_page_record` runs `classify()` once over
    each page's ENTIRE text — a part number or section heading appearing
    ANYWHERE on that page then reads as a high-risk change, even when the
    two pages are 80-90% identical (docs/redesign/plimsoll-real-document-
    smoketest-2026-09.html §1: EASA's "GEN-11"/parts_change false alarm was
    exactly this — two pages at 0.869 similarity, just below the primary
    0.6 threshold at first pass position but recoverable here; on the CCS
    target document 51 of 64 "unmatched" pages had a >=0.5 counterpart).

    Deliberately does NOT touch the primary alignment's threshold or DP —
    this only reconciles what's left over, so it can't change the outcome
    for any page the primary pass already matched, and stays cheap (the
    leftover set is always a small fraction of the document, never the
    full m×n matrix). Reconciled pages flow into the normal matched-page
    path in `compare_documents`, so what would have been one crude
    whole-page record becomes a precise line-level diff instead."""
    leftover_old = [idx for idx, (o, n) in enumerate(pairs) if o is not None and n is None]
    leftover_new = [idx for idx, (o, n) in enumerate(pairs) if o is None and n is not None]
    if not leftover_old or not leftover_new:
        return pairs

    candidates = []
    for oi in leftover_old:
        old_vec = old_vecs[pairs[oi][0]]
        for ni in leftover_new:
            new_vec = new_vecs[pairs[ni][1]]
            sim = text_similarity.cosine(old_vec, new_vec)
            if sim >= _PAGE_RECONCILE_THRESHOLD:
                candidates.append((sim, oi, ni))
    if not candidates:
        return pairs
    candidates.sort(key=lambda c: c[0], reverse=True)

    used_old: set[int] = set()
    used_new: set[int] = set()
    merged: dict[int, int] = {}  # index into `pairs` (old slot) -> index into `pairs` (new slot)
    for _sim, oi, ni in candidates:
        if oi in used_old or ni in used_new:
            continue
        used_old.add(oi)
        used_new.add(ni)
        merged[oi] = ni

    if not merged:
        return pairs

    consumed_new_slots = set(merged.values())
    result: list[tuple[int | None, int | None]] = []
    for idx, pair in enumerate(pairs):
        if idx in consumed_new_slots:
            continue  # folded into its matched old-slot entry below
        if idx in merged:
            result.append((pair[0], pairs[merged[idx]][1]))
        else:
            result.append(pair)
    return result


_UNSCANNABLE_EXPLANATION = "無法可信比對：此頁沒有可擷取的文字，請對照原始 PDF"


def _whole_page_record(*, counter: int, page: PageContent, change_type: str, ruleset: Ruleset) -> DifferenceRecord | None:
    text = "\n".join(page.lines)
    if not text:
        if not page.is_scanned:
            return None  # genuinely blank page — nothing to report
        # Scanned/unreadable page with no text layer: we cannot tell whether
        # its content changed, so surface it for human review rather than
        # silently dropping it (docs/redesign/plimsoll-real-document-
        # smoketest-2026-09.html §4 — a page's scanned status was detected at
        # the session level but never reached the per-diff record).
        is_delete = change_type == "刪除"
        return DifferenceRecord(
            id=f"D{counter:02d}",
            change_type=change_type,
            ai_risk="High",
            ai_confidence="低",
            explanation=_UNSCANNABLE_EXPLANATION,
            affected=page.heading or "",
            recommended_action="人工比對原始 PDF 頁面影像，確認內容是否變更",
            old=SourceSpan(page=_page_ref(page), text="") if is_delete else None,
            new=None if is_delete else SourceSpan(page=_page_ref(page), text=""),
            ruleset_version=ruleset.version,
            rule_id="unscannable_page",
        )
    text_canonical = "\n".join(page.lines_canonical)  # W4: classify() sees the canonical view, never the raw one
    is_delete = change_type == "刪除"
    result = classify(text_canonical if is_delete else None, None if is_delete else text_canonical, ruleset)
    return DifferenceRecord(
        id=f"D{counter:02d}",
        change_type=change_type,
        ai_risk=result["risk"],
        ai_confidence=result["confidence"],
        explanation=result["rationale"],
        affected=page.heading or "",
        recommended_action=result["recommended_action"],
        old=SourceSpan(page=_page_ref(page), text=text) if is_delete else None,
        new=None if is_delete else SourceSpan(page=_page_ref(page), text=text),
        ruleset_version=ruleset.version,
        rule_id=result["rule_id"],
    )


def align_pages(old: ExtractedDocument, new: ExtractedDocument) -> list[tuple[int | None, int | None]]:
    """Public entry point for W3 page alignment alone, with no line-level
    diffing or classification — for a caller that needs to know which
    physical page corresponds to which without paying for a full
    compare_documents() run (e.g. session_store.process_upload(), which
    persists this into pages.json's page_alignment for the source viewer's
    page-by-page navigation — see that field's own docstring for why the
    viewer needs it at all). compare_documents() calls this internally when
    `page_pairs` isn't passed in, so a caller that already computed it can
    hand it back via that parameter to avoid recomputing."""
    return _align_pages(old.pages, new.pages)


def compare_documents(
    old: ExtractedDocument,
    new: ExtractedDocument,
    ruleset: Ruleset,
    *,
    page_pairs: list[tuple[int | None, int | None]] | None = None,
) -> list[DifferenceRecord]:
    records: list[DifferenceRecord] = []
    seen_pairs: set[tuple[str | None, str | None]] = set()
    counter = 0

    for old_idx, new_idx in page_pairs if page_pairs is not None else _align_pages(old.pages, new.pages):
        if old_idx is not None and new_idx is not None:
            old_page, new_page = old.pages[old_idx], new.pages[new_idx]
            # §27a page-hash short-circuit — on the W4 canonical view: a page
            # that only changed by synonym swaps is, for comparison purposes,
            # unchanged, exactly like a byte-identical page always was.
            if old_page.lines_canonical == new_page.lines_canonical:
                continue
            for pair in _diff_page_lines(old_page.lines, new_page.lines, old_page.lines_canonical, new_page.lines_canonical):
                old_text, new_text = pair.old_raw, pair.new_raw
                key = (old_text, new_text)
                if key in seen_pairs:  # e.g. a summary table re-stating a body line
                    continue
                seen_pairs.add(key)

                change_type = "新增" if old_text is None else "刪除" if new_text is None else "修改"
                result = classify(pair.old_key, pair.new_key, ruleset)  # W4: classify on the canonical view
                counter += 1
                # Best deterministic stand-in for "受影響設備/流程" without a full
                # component taxonomy (§28, Someday): the section heading the
                # change lives under.
                affected = new_page.heading or old_page.heading or ""
                records.append(
                    DifferenceRecord(
                        id=f"D{counter:02d}",
                        change_type=change_type,
                        ai_risk=result["risk"],
                        ai_confidence=result["confidence"],
                        explanation=result["rationale"],
                        affected=affected,
                        recommended_action=result["recommended_action"],
                        old=SourceSpan(page=_page_ref(old_page), text=old_text) if old_text is not None else None,
                        new=SourceSpan(page=_page_ref(new_page), text=new_text) if new_text is not None else None,
                        ruleset_version=ruleset.version,
                        rule_id=result["rule_id"],
                    )
                )
        else:
            # Unmatched page (W3 alignment found nothing above threshold on
            # the other side) — a whole-page 新增/刪除, no per-line detail to
            # align against.
            page = old.pages[old_idx] if old_idx is not None else new.pages[new_idx]
            record = _whole_page_record(
                counter=counter + 1, page=page, change_type="刪除" if old_idx is not None else "新增", ruleset=ruleset
            )
            if record is not None:
                counter += 1
                records.append(record)

    return records
