"""Term canonicalization — Stage 0.5, between extraction and comparison
(W4: docs/redesign/plimsoll-improvement-plan.html §01/§02).

Wording drift across versions ("溫度上限" → "最高溫度限值" → "溫度上限值") can
sink the W3 page/anchor matching before it ever reaches rule classification —
that's why this stage runs *before* comparison, not as a rule-time lookup.

This module produces a rule-matching *view*, never a rewrite of what the
reviewer sees: every `PageContent.lines` is left untouched; only
`lines_canonical` (fed exclusively to `comparison.classify()`, never rendered
in a report) gets alias-substituted. Keeping the two separate is the whole
point — a report where the displayed original text doesn't match what the
engine actually compared would be an audit hole (the same reasoning as
architecture-decisions-A-B.md §22's dual page numbers: never silently merge
a "for the reviewer" value with a "for the engine" value).

Alias table governance: an LLM may PROPOSE a candidate alias offline (W7's
by-product, not on the live comparison path), but only a human-approved
entry (`approved_by`/`approved_at` on the `TermAlias`) ever reaches this
module — the engine never decides synonymy on its own.
"""

from __future__ import annotations

from dataclasses import replace

from backend.models.config_models import TermAliasTable
from backend.services.extraction import ExtractedDocument, PageContent


def _substitution_order(table: TermAliasTable) -> list[tuple[str, str]]:
    """(variant, canonical) pairs, longest variant first, so a longer alias
    is substituted before a shorter one that happens to be its substring
    (e.g. "溫度上限值" before "上限值") isn't pre-empted by the shorter match."""
    pairs = [
        (variant, alias.canonical)
        for alias in table.aliases
        for variant in alias.variants
        if variant != alias.canonical
    ]
    return sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)


def _apply_substitutions(text: str, pairs: list[tuple[str, str]]) -> str:
    for variant, canonical in pairs:
        text = text.replace(variant, canonical)
    return text


def normalize_text(text: str, table: TermAliasTable) -> str:
    """Single-string entry point — mainly for tests/tools. The document-level
    path (`apply_term_aliases`) precomputes the substitution order once
    instead of re-sorting it per line."""
    return _apply_substitutions(text, _substitution_order(table))


def apply_term_aliases(doc: ExtractedDocument, table: TermAliasTable) -> ExtractedDocument:
    """Returns a new `ExtractedDocument` — `lines`/`raw_text` untouched on
    every page, `lines_canonical` replaced with the alias-normalized view."""
    pairs = _substitution_order(table)

    def _canonicalize(page: PageContent) -> PageContent:
        return replace(page, lines_canonical=[_apply_substitutions(line, pairs) for line in page.lines])

    return ExtractedDocument(
        pages=[_canonicalize(p) for p in doc.pages],
        page_count=doc.page_count,
        size_bytes=doc.size_bytes,
    )
