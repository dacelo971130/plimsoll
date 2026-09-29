"""W4 term canonicalization tests (docs/redesign/plimsoll-improvement-plan.html
§02): normalize_text()/apply_term_aliases() never touch the reviewer-facing
`lines`, and comparison.py must end up seeing zero differences for a pure
synonym swap."""

from __future__ import annotations

import pytest

from backend.models.config_models import TermAlias, TermAliasTable
from backend.services.comparison import compare_documents
from backend.services.extraction import ExtractedDocument, PageContent
from backend.services.normalize import apply_term_aliases, normalize_text
from backend.storage.config_loader import get_ruleset, get_term_aliases, latest_term_aliases_version


@pytest.fixture
def aliases() -> TermAliasTable:
    return TermAliasTable(
        version="test",
        aliases=[
            TermAlias(canonical="溫度上限", variants=["最高溫度限值", "溫度上限值"]),
        ],
    )


def test_normalize_text_substitutes_variants_to_canonical(aliases):
    assert normalize_text("最高溫度限值為 85°C。", aliases) == "溫度上限為 85°C。"
    assert normalize_text("溫度上限值為 85°C。", aliases) == "溫度上限為 85°C。"
    assert normalize_text("已是標準用語的句子。", aliases) == "已是標準用語的句子。"


def test_normalize_text_prefers_longer_variant_over_its_substring(aliases):
    # "溫度上限值" contains "上限值" — a naive shortest-first substitution could
    # partially rewrite it. Longest-variant-first must win cleanly.
    table = TermAliasTable(
        version="test",
        aliases=[
            TermAlias(canonical="溫度上限", variants=["溫度上限值"]),
            TermAlias(canonical="上限額度", variants=["上限值"]),
        ],
    )
    assert normalize_text("溫度上限值。", table) == "溫度上限。"


def _mk_page(lines: list[str]) -> PageContent:
    return PageContent(
        pdf_page=1,
        print_label=None,
        label_source="unknown",
        raw_text="\n".join(lines),
        lines=lines,
        lines_canonical=list(lines),  # pre-normalization identity
        char_count=sum(len(l) for l in lines),
        is_scanned=False,
        heading=None,
    )


def test_apply_term_aliases_leaves_raw_lines_untouched(aliases):
    doc = ExtractedDocument(pages=[_mk_page(["最高溫度限值為 85°C。"])], page_count=1, size_bytes=0)
    normalized = apply_term_aliases(doc, aliases)

    # Reviewer-facing text must be byte-for-byte the original.
    assert normalized.pages[0].lines == ["最高溫度限值為 85°C。"]
    # Only the canonical view changed.
    assert normalized.pages[0].lines_canonical == ["溫度上限為 85°C。"]


def test_pure_synonym_swap_produces_zero_differences(aliases):
    # The W4 acceptance criterion verbatim: a pair of sentences that differ
    # only by an approved synonym must diff to zero, using the same
    # comparison.compare_documents() pipeline as everything else.
    ruleset = get_ruleset("v1")
    old_doc = ExtractedDocument(
        pages=[_mk_page(["1. 標題", "冷卻液出口溫度必須維持在最高溫度限值以下。"])], page_count=1, size_bytes=0
    )
    new_doc = ExtractedDocument(
        pages=[_mk_page(["1. 標題", "冷卻液出口溫度必須維持在溫度上限值以下。"])], page_count=1, size_bytes=0
    )
    old_doc = apply_term_aliases(old_doc, aliases)
    new_doc = apply_term_aliases(new_doc, aliases)

    differences = compare_documents(old_doc, new_doc, ruleset)
    assert differences == []


def test_seed_term_aliases_v1_config_loads_and_normalizes_the_documented_example():
    # docs/redesign/plimsoll-improvement-plan.html §01's own worked example.
    assert latest_term_aliases_version() == "v1"
    table = get_term_aliases("v1")
    assert normalize_text("最高溫度限值", table) == "溫度上限"
    assert normalize_text("溫度上限值", table) == "溫度上限"
