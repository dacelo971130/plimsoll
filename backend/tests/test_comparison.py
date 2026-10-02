"""P1 comparison-engine tests: rule classification (config-driven, no LLM)
and end-to-end diffing against the real demo PDFs."""

from __future__ import annotations

import pytest

from backend.config import REPO_ROOT
from backend.services.comparison import classify, compare_documents
from backend.services.extraction import ExtractedDocument, PageContent, extract_document
from backend.storage.config_loader import get_ruleset

DEMO_OLD = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.0.pdf"
DEMO_NEW = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.1.pdf"

pytestmark = pytest.mark.skipif(
    not (DEMO_OLD.exists() and DEMO_NEW.exists()), reason="run scripts/generate_demo_pdfs.py first"
)


@pytest.fixture
def ruleset():
    return get_ruleset("v1")


@pytest.fixture
def ruleset_v2():
    return get_ruleset("v2")


def test_numeric_plus_safety_term_change_is_high_risk(ruleset):
    result = classify("冷卻液出口溫度建議維持在 85°C 以下。", "冷卻液出口溫度必須維持在 80°C 以下。", ruleset)
    assert result["risk"] == "High"
    assert result["rule_id"] == "numeric_safety"


def test_obligation_only_change_is_medium_risk(ruleset):
    result = classify("每次檢查應記錄。", "每次檢查必須記錄並簽名。", ruleset)
    assert result["rule_id"] in ("obligation_only", "obligation_plus")


def test_unrelated_text_change_falls_back_to_default_low_risk(ruleset):
    result = classify("舊的說明文字。", "新的說明文字，純文字修訂。", ruleset)
    assert result["risk"] == "Low"
    assert result["rule_id"] == "default"


def test_compare_documents_finds_at_least_five_differences_on_demo_pdfs(ruleset):
    old_doc = extract_document(DEMO_OLD.read_bytes())
    new_doc = extract_document(DEMO_NEW.read_bytes())
    differences = compare_documents(old_doc, new_doc, ruleset)

    assert len(differences) >= 5  # AC2 floor
    ids = [d.id for d in differences]
    assert ids == sorted(ids)  # D01, D02, ... in encounter order, no gaps skipped

    # The headline safety-threshold change from the demo narrative must show up,
    # be traceable to old/new page 3, and be classified High.
    temp_change = next(d for d in differences if d.new and "80°C" in d.new.text)
    assert temp_change.ai_risk == "High"
    assert temp_change.old is not None and "85°C" in temp_change.old.text
    assert temp_change.old.page.pdf_page == 3
    assert temp_change.new.page.pdf_page == 3
    # "受影響設備/流程" stand-in (§28 taxonomy is Someday) — the section heading.
    assert temp_change.affected == "3. 冷卻溫度檢查"


def test_every_difference_has_a_non_empty_affected_section(ruleset):
    old_doc = extract_document(DEMO_OLD.read_bytes())
    new_doc = extract_document(DEMO_NEW.read_bytes())
    differences = compare_documents(old_doc, new_doc, ruleset)
    assert all(d.affected for d in differences)


def test_every_difference_carries_traceable_source_and_data_origin(ruleset):
    old_doc = extract_document(DEMO_OLD.read_bytes())
    new_doc = extract_document(DEMO_NEW.read_bytes())
    differences = compare_documents(old_doc, new_doc, ruleset)

    for d in differences:
        assert d.old is not None or d.new is not None  # never a fully-empty diff
        assert d.data_origin == "computed"
        assert d.ruleset_version == "v1"
        if d.old:
            assert d.old.page.pdf_page is not None
        if d.new:
            assert d.new.page.pdf_page is not None


def test_part_number_change_alone_is_high_risk_under_v2(ruleset_v2):
    # D04 (compliance audit): CP-100 → CP-120 has no unit-bearing number, so
    # numeric_change never fires — v1 falls through to default/Low.
    result = classify("使用零件料號 CP-100 的密封件。", "使用零件料號 CP-120 的耐熱密封件。", ruleset_v2)
    assert result["risk"] == "High"
    assert result["rule_id"] == "parts_change"


def test_applicability_change_alone_is_high_risk_under_v2(ruleset_v2):
    # D06: 適用船型擴大, no obligation/safety/numeric term involved.
    result = classify("適用船型：巡防艦 A 型。", "適用船型：巡防艦 A 型及 B 型。", ruleset_v2)
    assert result["risk"] == "High"
    assert result["rule_id"] == "applicability_change"


def test_step_order_change_alone_is_high_risk_under_v2(ruleset_v2):
    # D07: same two actions, order reversed — no numeric/safety/obligation term.
    result = classify("先停止循環泵浦，再關閉冷卻液出口閥。", "先關閉冷卻液出口閥，再停止循環泵浦。", ruleset_v2)
    assert result["risk"] == "High"
    assert result["rule_id"] == "step_order_change"


def test_v1_ruleset_still_misses_d04_d06_d07(ruleset):
    # Regression pin for the exact gap v2 closes — must stay Low/default on v1.
    assert classify("使用零件料號 CP-100 的密封件。", "使用零件料號 CP-120 的耐熱密封件。", ruleset)["rule_id"] == "default"
    assert classify("適用船型：巡防艦 A 型。", "適用船型：巡防艦 A 型及 B 型。", ruleset)["rule_id"] == "default"


def test_safety_term_bar_does_not_match_inside_unrelated_english_word(ruleset_v2):
    # docs/redesign/plimsoll-real-document-smoketest-2026-09.html §1: "bar"
    # used to substring-match inside "embarkation", "mpa" inside
    # "compartment"/"impaired"/"compatible" — real SOLAS/UNECE text tripped
    # numeric_safety/safety_only for the wrong reason. Neither of these two
    # sentences contains the ruleset's literal safety terms as whole words.
    result = classify(
        "The embarkation deck layout was revised for clarity.",
        "The embarkation deck layout was revised for clarity and safety.",
        ruleset_v2,
    )
    assert result["rule_id"] == "default"


def test_safety_term_mpa_matches_whole_word_case_insensitively(ruleset_v2):
    # A real "0.5 MPa -> 0.6 MPa" change: numeric_change already fires
    # case-insensitively (_NUMBER_WITH_UNIT_RE has re.IGNORECASE), but the
    # safety_terms gate used to require a literal lowercase "mpa" and so
    # never matched "MPa" — the whole numeric_safety rule silently missed a
    # real pressure-limit change.
    result = classify("設計值為 0.5 MPa。", "設計值為 0.6 MPa。", ruleset_v2)
    assert result["risk"] == "High"
    assert result["rule_id"] == "numeric_safety"


def test_safety_term_mpa_still_does_not_match_inside_compartment(ruleset_v2):
    result = classify(
        "The compartment layout was relabelled for the new deck plan.",
        "The compartment layout was relabelled for the updated deck plan.",
        ruleset_v2,
    )
    assert result["rule_id"] == "default"


def test_v2_rules_do_not_change_existing_high_or_low_classifications(ruleset_v2):
    # Existing correct calls (D01/D02/D08-style) must be unaffected by v2.
    high = classify("冷卻液出口溫度建議維持在 85°C 以下。", "冷卻液出口溫度必須維持在 80°C 以下。", ruleset_v2)
    assert high["risk"] == "High" and high["rule_id"] == "numeric_safety"
    low = classify("舊的說明文字。", "新的說明文字，純文字修訂。", ruleset_v2)
    assert low["risk"] == "Low" and low["rule_id"] == "default"


def test_compare_documents_now_includes_insert_and_delete_change_types(ruleset_v2):
    # W2: demo now has genuine 新增/刪除 instances, not just 修改.
    old_doc = extract_document(DEMO_OLD.read_bytes())
    new_doc = extract_document(DEMO_NEW.read_bytes())
    differences = compare_documents(old_doc, new_doc, ruleset_v2)
    change_types = {d.change_type for d in differences}
    assert change_types == {"新增", "刪除", "修改"}


def _mk_page(
    pdf_page: int, lines: list[str], heading: str | None = None, is_scanned: bool = False
) -> PageContent:
    return PageContent(
        pdf_page=pdf_page,
        print_label=None,
        label_source="unknown",
        raw_text="\n".join(lines),
        lines=lines,
        lines_canonical=list(lines),
        char_count=sum(len(l) for l in lines),
        is_scanned=is_scanned,
        heading=heading,
    )


def test_inserting_a_page_in_the_middle_does_not_explode_diff_count(ruleset):
    # W3: naive positional (index-based) alignment would compare old[2]
    # against new[2] (the brand-new page) and old-page-3-worth-of-content
    # against nothing, exploding the diff count. Page-to-page mapping should
    # instead recognize old page 3 moved to new page 4 and only report the
    # one real edit (page 2) plus the one real insert (the new page 3).
    old_pages = [
        _mk_page(1, ["1. 標題", "第一段內容維持不變的說明文字。"], heading="1. 標題"),
        _mk_page(2, ["2. 次頁", "第二頁內容大致不變，僅補充少量細節。"], heading="2. 次頁"),
        _mk_page(3, ["3. 末頁", "第三頁內容也維持不變。"], heading="3. 末頁"),
    ]
    new_pages = [
        _mk_page(1, ["1. 標題", "第一段內容維持不變的說明文字。"], heading="1. 標題"),
        _mk_page(2, ["2. 次頁", "第二頁內容大致不變，僅補充少量細節，多了一句。"], heading="2. 次頁"),
        _mk_page(3, ["3. 全新插入頁", "這是全新插入的一整頁，舊版完全沒有這個內容。"], heading="3. 全新插入頁"),
        # Same heading text as old page 3 — only its physical page number
        # shifted because of the insertion above it, which isn't a content change.
        _mk_page(4, ["3. 末頁", "第三頁內容也維持不變。"], heading="3. 末頁"),
    ]
    old_doc = ExtractedDocument(pages=old_pages, page_count=len(old_pages), size_bytes=0)
    new_doc = ExtractedDocument(pages=new_pages, page_count=len(new_pages), size_bytes=0)

    differences = compare_documents(old_doc, new_doc, ruleset)

    assert len(differences) == 2
    modify = next(d for d in differences if d.change_type == "修改")
    insert = next(d for d in differences if d.change_type == "新增")
    assert modify.new is not None and "多了一句" in modify.new.text
    assert insert.old is None
    assert insert.new is not None and "全新插入" in insert.new.text


def test_deleting_a_page_in_the_middle_does_not_explode_diff_count(ruleset):
    old_pages = [
        _mk_page(1, ["1. 標題", "第一段內容維持不變。"], heading="1. 標題"),
        _mk_page(2, ["2. 即將刪除的頁", "這一整頁在新版中被整頁移除。"], heading="2. 即將刪除的頁"),
        _mk_page(3, ["3. 末頁", "第三頁內容也維持不變。"], heading="3. 末頁"),
    ]
    new_pages = [
        _mk_page(1, ["1. 標題", "第一段內容維持不變。"], heading="1. 標題"),
        # Same heading text as old page 3 — only its physical page number
        # shifted because of the deletion, which isn't a content change.
        _mk_page(2, ["3. 末頁", "第三頁內容也維持不變。"], heading="3. 末頁"),
    ]
    old_doc = ExtractedDocument(pages=old_pages, page_count=len(old_pages), size_bytes=0)
    new_doc = ExtractedDocument(pages=new_pages, page_count=len(new_pages), size_bytes=0)

    differences = compare_documents(old_doc, new_doc, ruleset)

    assert len(differences) == 1
    assert differences[0].change_type == "刪除"
    assert differences[0].old is not None and "整頁移除" in differences[0].old.text


def test_line_wrap_reflow_does_not_produce_a_spurious_difference(ruleset):
    # docs/redesign/plimsoll-real-document-smoketest-2026-09.html §1 (UNECE
    # D776): a paragraph re-typeset with the line-wrap boundary moved by one
    # word — same words, cut at a different point — used to surface as a
    # "operating sequence reordered" High-risk false alarm. It must produce
    # no difference at all, same as a byte-identical line.
    old_pages = [
        _mk_page(
            1,
            ["1. 標題", "of the seating position in a row, as viewed in the direction of forward motion"],
            heading="1. 標題",
        )
    ]
    new_pages = [
        _mk_page(
            1,
            ["1. 標題", "the seating position in a row, as viewed in the direction of forward motion of"],
            heading="1. 標題",
        )
    ]
    old_doc = ExtractedDocument(pages=old_pages, page_count=1, size_bytes=0)
    new_doc = ExtractedDocument(pages=new_pages, page_count=1, size_bytes=0)
    assert compare_documents(old_doc, new_doc, ruleset) == []


def test_genuine_step_order_change_is_not_suppressed_as_reflow(ruleset_v2):
    # The reflow suppression must not swallow a real reorder: these two
    # sentences are the same clauses swapped, not a rotation of the exact
    # same character stream (the punctuation lands on a different clause),
    # so step_order_change must still fire.
    # A stable heading line keeps the page-level fingerprint match well above
    # threshold, isolating the swapped clause as the only line-level change.
    old_pages = [_mk_page(1, ["1. 標題", "先停止循環泵浦，再關閉冷卻液出口閥。"], heading="1. 標題")]
    new_pages = [_mk_page(1, ["1. 標題", "先關閉冷卻液出口閥，再停止循環泵浦。"], heading="1. 標題")]
    old_doc = ExtractedDocument(pages=old_pages, page_count=1, size_bytes=0)
    new_doc = ExtractedDocument(pages=new_pages, page_count=1, size_bytes=0)
    differences = compare_documents(old_doc, new_doc, ruleset_v2)
    assert len(differences) == 1
    assert differences[0].rule_id == "step_order_change"


def test_two_scanned_pages_are_never_silently_treated_as_identical(ruleset):
    # docs/redesign/plimsoll-real-document-smoketest-2026-09.html §4: two
    # pages with no extractable text layer used to compare as "identical"
    # (similarity 1.0) and vanish with zero diffs even if the underlying
    # scan changed. Each side must instead surface as its own explicit
    # "can't verify" record.
    old_pages = [_mk_page(1, [], is_scanned=True)]
    new_pages = [_mk_page(1, [], is_scanned=True)]
    old_doc = ExtractedDocument(pages=old_pages, page_count=1, size_bytes=0)
    new_doc = ExtractedDocument(pages=new_pages, page_count=1, size_bytes=0)

    differences = compare_documents(old_doc, new_doc, ruleset)

    assert len(differences) == 2
    assert {d.change_type for d in differences} == {"新增", "刪除"}
    assert all(d.rule_id == "unscannable_page" and d.ai_risk == "High" for d in differences)


def test_scanned_counterpart_still_surfaces_an_unverifiable_record(ruleset):
    # A page that turned into a scan in the new version (no text layer) must
    # not just silently disappear — even though its old-side deletion isn't
    # specially flagged yet (a known remaining gap, see the smoketest report
    # §7 conflict 1), the new side must produce an explicit unscannable_page
    # record instead of nothing.
    old_pages = [
        _mk_page(1, ["1. 標題"], heading="1. 標題"),
        _mk_page(2, ["2. 次頁", "重要安全條文，維持不變。"], heading="2. 次頁"),
    ]
    new_pages = [
        _mk_page(1, ["1. 標題"], heading="1. 標題"),
        _mk_page(2, [], is_scanned=True),
    ]
    old_doc = ExtractedDocument(pages=old_pages, page_count=2, size_bytes=0)
    new_doc = ExtractedDocument(pages=new_pages, page_count=2, size_bytes=0)

    differences = compare_documents(old_doc, new_doc, ruleset)

    assert any(d.rule_id == "unscannable_page" and d.ai_risk == "High" for d in differences)


def test_cumulative_drift_fires_on_a_consistent_series_under_v2(ruleset_v2):
    # W6: 5-point series, -0.2 each step, no per-step numeric_safety-style
    # text involved (chain_history is the only signal) — total drop is 4%,
    # comfortably over the 1% threshold.
    result = classify(None, None, ruleset_v2, chain_history=[20.0, 19.8, 19.6, 19.4, 19.2])
    assert result["risk"] == "High"
    assert result["rule_id"] == "cumulative_drift"


def test_cumulative_drift_does_not_fire_below_thresholds(ruleset_v2):
    # Too short a series.
    assert classify(None, None, ruleset_v2, chain_history=[20.0, 19.8])["rule_id"] == "default"
    # Long enough but direction flips (not a steady drift).
    assert classify(None, None, ruleset_v2, chain_history=[20.0, 19.8, 20.0, 19.8])["rule_id"] == "default"
    # Long enough and consistent, but total change is under 1%.
    assert classify(None, None, ruleset_v2, chain_history=[20.0, 19.99, 19.98, 19.97])["rule_id"] == "default"


def test_chain_history_is_ignored_under_v1_ruleset(ruleset):
    # v1.json has no cumulative_drift rule at all — passing chain_history is
    # harmless (falls through to default), matching "adding v2 doesn't change v1".
    result = classify(None, None, ruleset, chain_history=[20.0, 19.8, 19.6, 19.4, 19.2])
    assert result["rule_id"] == "default"


def test_classify_without_chain_history_is_unaffected_by_w6(ruleset_v2):
    # The exact pre-W6 call shape must classify identically.
    result = classify("冷卻液出口溫度建議維持在 85°C 以下。", "冷卻液出口溫度必須維持在 80°C 以下。", ruleset_v2)
    assert result["risk"] == "High" and result["rule_id"] == "numeric_safety"


def test_identical_pages_are_short_circuited(ruleset):
    # Pages 1-2 are byte-identical between v1.0/v1.1 (COMMON_PAGES) — none of
    # their content should surface as a difference.
    old_doc = extract_document(DEMO_OLD.read_bytes())
    new_doc = extract_document(DEMO_NEW.read_bytes())
    differences = compare_documents(old_doc, new_doc, ruleset)
    assert not any((d.old and d.old.page.pdf_page in (1, 2)) or (d.new and d.new.page.pdf_page in (1, 2)) for d in differences)


# W3 page-matching signal (TF-IDF bigram cosine) unit tests moved to
# backend/tests/test_text_similarity.py once the logic was generalized from
# PageContent objects to plain strings (backend/services/text_similarity.py)
# for reuse by backend/services/agent/tools.py's search tools. _align_pages'
# own page-alignment behavior (tested below via compare_documents) is
# unaffected by that move.
