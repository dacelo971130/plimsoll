"""The accuracy benchmark's scorer (scripts/accuracy_bench.py): answer-key
loading, result-CSV parsing, anchor/page matching, and the metrics — plus
one end-to-end check that the engine still finds every answer-key item in
the demo case. Competitor tools aren't run here; the word-level fixture
below only imitates the shape of their output."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

from backend.config import REPO_ROOT, SESSIONS_ROOT

_spec = importlib.util.spec_from_file_location("accuracy_bench", REPO_ROOT / "scripts" / "accuracy_bench.py")
bench = importlib.util.module_from_spec(_spec)
sys.modules["accuracy_bench"] = bench  # @dataclass resolves annotations through sys.modules
_spec.loader.exec_module(bench)

DEMO_CASE = REPO_ROOT / "data" / "benchmark" / "cases" / "demo-cooling-v1.0-v1.1" / "case.json"
HEADER = ",".join(bench.RESULT_COLUMNS)


def _case(items: list[dict], **extra) -> bench.Case:
    defaults = {"change_type": "修改", "expected_risk": "Low", "scored": True}
    return bench.Case(
        id="t",
        title="t",
        old_pdf="a.pdf",
        new_pdf="b.pdf",
        items=tuple(
            bench.TruthItem(
                id=i["id"],
                summary="",
                change_type=i.get("change_type", defaults["change_type"]),
                old_pages=bench._pages(i.get("old_pages")),
                new_pages=bench._pages(i.get("new_pages")),
                old_anchors=tuple(i.get("old_anchors", ())),
                new_anchors=tuple(i.get("new_anchors", ())),
                expected_risk=i.get("expected_risk", defaults["expected_risk"]),
                scored=i.get("scored", defaults["scored"]),
            )
            for i in items
        ),
        **extra,
    )


def _rows(tmp_path: Path, case: bench.Case, *lines: str) -> list[bench.Reported]:
    path = tmp_path / "tool.csv"
    path.write_text("﻿" + HEADER + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return bench.load_results(path, case)


def _score(case: bench.Case, rows: list[bench.Reported]) -> bench.ToolScore:
    return bench.score_tool("tool", case, rows, bench.match_all(rows, case))


# ── answer key ───────────────────────────────────────────────────────────


def test_demo_answer_key_is_well_formed():
    case = bench.load_case(DEMO_CASE)
    assert (REPO_ROOT / case.old_pdf).exists() and (REPO_ROOT / case.new_pdf).exists()
    scored = [i for i in case.items if i.scored]
    assert len(scored) == 13
    assert all(i.old_anchors or i.new_anchors for i in scored)  # the demo is text-only: every item is anchorable
    assert case.home_field  # the report must keep flagging it as our home ground


def test_load_case_rejects_an_unmatchable_item(tmp_path):
    path = tmp_path / "case.json"
    path.write_text(
        json.dumps({"id": "x", "old_pdf": "a", "new_pdf": "b", "items": [
            {"id": "G1", "change_type": "修改", "expected_risk": "High"},
        ]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="永遠對不到"):
        bench.load_case(path)


def test_page_ranges_expand():
    assert bench._pages([3, "10-12"]) == (3, 10, 11, 12)


# ── parsing a tool's CSV ─────────────────────────────────────────────────


def test_normalize_ignores_width_and_whitespace():
    assert bench.normalize_text("80 °C，A 型") == bench.normalize_text("80°C,A型")
    assert bench.normalize_text("80℃") == bench.normalize_text("80°C")


def test_load_results_accepts_aliases_and_adjudication(tmp_path):
    case = _case([{"id": "G1", "new_anchors": ["x"]}, {"id": "G2", "new_anchors": ["y"]}])
    rows = _rows(
        tmp_path, case,
        "1,added,,p.3,,x,高,,",
        "2,Modified,2,2,a,b,medium,G1;G2,",
        "3,,,,a,b,,noise,",
        ",,,,,,,,",  # blank line is skipped
    )
    assert [(r.change_type, r.new_page, r.risk) for r in rows] == [("新增", 3, "High"), ("修改", 2, "Medium"), (None, None, None)]
    assert [r.gt_ids for r in rows] == [None, ("G1", "G2"), ()]


@pytest.mark.parametrize(
    "line, message",
    [("1,修改,,,a,b,severe,,", "風險等級"), ("1,修改,,,a,b,,G9,", "不在答案裡"), ("1,moved,,,a,b,,,", "變更類型")],
)
def test_load_results_rejects_what_it_cannot_score(tmp_path, line, message):
    case = _case([{"id": "G1", "new_anchors": ["x"]}])
    with pytest.raises(ValueError, match=message):
        _rows(tmp_path, case, line)


# ── matching ─────────────────────────────────────────────────────────────


def test_anchor_must_sit_on_a_compatible_page(tmp_path):
    case = _case([{"id": "G1", "old_pages": [3], "new_pages": [3], "new_anchors": ["80°C"]}])
    on_page, off_page, no_page = _rows(
        tmp_path, case, "1,,3,3,,維持在 80 °C 以下,,,", "2,,5,5,,80°C,,,", "3,,,,,80°C,,,"
    )
    assert bench.auto_match(on_page, case) == ("G1",)
    assert bench.auto_match(off_page, case) == ()
    assert bench.auto_match(no_page, case) == ("G1",)  # a tool that reports no page can't contradict one

    tolerant = _case([{"id": "G1", "new_pages": [3], "new_anchors": ["80°C"]}], page_tolerance=2)
    assert bench.auto_match(off_page, tolerant) == ("G1",)


def test_location_only_item_needs_a_page_hit(tmp_path):
    case = _case([{"id": "C1", "change_type": "新增", "new_pages": ["120-125"]}])
    inside, outside, no_page = _rows(tmp_path, case, "1,,,122,,任何文字,,,", "2,,,130,,任何文字,,,", "3,,,,,任何文字,,,")
    assert bench.auto_match(inside, case) == ("C1",)
    assert bench.auto_match(outside, case) == ()
    assert bench.auto_match(no_page, case) == ()


def test_one_row_quoting_a_whole_page_covers_several_items(tmp_path):
    case = _case([{"id": "G1", "new_anchors": ["80°C"]}, {"id": "G2", "new_anchors": ["每週"]}])
    (row,) = _rows(tmp_path, case, '1,,,,,"80°C 以下。每週檢查一次",,,')
    assert bench.auto_match(row, case) == ("G1", "G2")


# ── metrics ──────────────────────────────────────────────────────────────


def _two_item_case(**extra) -> bench.Case:
    return _case(
        [
            {"id": "G1", "old_pages": [3], "new_pages": [3], "old_anchors": ["85°C"], "new_anchors": ["80°C"], "expected_risk": "High"},
            {"id": "G2", "old_pages": [4], "new_pages": [4], "new_anchors": ["CP-120"], "expected_risk": "Low"},
            {"id": "X1", "old_anchors": ["v1.0"], "new_anchors": ["v1.1"], "scored": False},
        ],
        **extra,
    )


def test_word_level_tool_fragments_noise_and_dont_care(tmp_path):
    """The shape a word-level compare tool produces: G1 split into two
    fragments (one with no anchor), the version header on two pages, one
    real false positive, and G2 never reported."""
    case = _two_item_case()
    rows = _rows(
        tmp_path, case,
        "a,修改,3,3,85°C,80°C,,,",
        "b,修改,3,3,建議,必須,,,",  # G1 fragment — no anchor, so unmatched until a person says otherwise
        "c,修改,1,1,v1.0,v1.1,,,",
        "d,修改,2,2,v1.0,v1.1,,,",
        "e,修改,5,5,舊字,新字,,,",
    )
    s = _score(case, rows)
    assert (s.detected, s.scored_total) == (1, 2)
    assert s.missed_high == []
    assert [r.item_id for r in s.noise] == ["b", "e"]
    assert s.dont_care == 2  # version headers are neither credit nor noise
    assert bench.precision(s) == pytest.approx(3 / 5)
    assert not s.risk_graded

    adjudicated = [r if r.item_id != "b" else bench.Reported(**{**r.__dict__, "gt_ids": ("G1",)}) for r in rows]
    s2 = _score(case, adjudicated)
    assert [r.item_id for r in s2.noise] == ["e"]
    assert s2.on_scored == 2 and s2.detected == 1  # two cards for one real change
    assert s2.manual == 1


def test_missed_and_underrated_high_risk(tmp_path):
    case = _two_item_case()
    missed = _score(case, _rows(tmp_path, case, "a,修改,4,4,CP-100,CP-120,Low,,"))
    assert missed.missed_high == ["G1"]

    underrated = _score(case, _rows(tmp_path, case, "a,修改,3,3,85°C,80°C,Low,,", "b,修改,3,3,85°C,80°C,Medium,,"))
    assert underrated.outcomes[0].tool_risk == "Medium"  # highest card among the hits
    assert underrated.high_underrated == ["G1"]
    assert underrated.missed_high == []

    over = _score(case, _rows(tmp_path, case, "a,修改,4,4,CP-100,CP-120,High,,"))
    assert over.over_rated == ["G2"]


def test_a_revised_clause_accepts_line_level_types(tmp_path):
    case = _case([{"id": "G1", "new_anchors": ["x"]}])
    strict = _score(case, _rows(tmp_path, case, "a,新增,,,,x,,,"))
    assert strict.type_ok == 0 and strict.type_known == 1

    lenient = bench.Case(**{**case.__dict__, "items": (bench.TruthItem(**{**case.items[0].__dict__, "accept_change_types": ("修改", "新增")}),)})
    assert _score(lenient, _rows(tmp_path, lenient, "a,新增,,,,x,,,")).type_ok == 1


def test_recall_only_case_has_no_precision_and_does_not_dilute_totals(tmp_path):
    full = _two_item_case()
    partial = _two_item_case(recall_only=True)
    s_full = _score(full, _rows(tmp_path, full, "a,修改,3,3,85°C,80°C,,,", "b,修改,9,9,x,y,,,"))
    s_partial = _score(partial, _rows(tmp_path, partial, "a,修改,9,9,x,y,,,", "b,修改,9,9,x,y,,,"))
    assert bench.precision(s_partial) is None
    total = bench.combine([s_full, s_partial])
    assert bench.precision(total) == pytest.approx(1 / 2)  # only the complete case counts
    assert (total.detected, total.scored_total) == (1, 4)


def test_empty_scaffold_is_skipped_but_a_dated_empty_run_is_scored():
    assert bench.not_run_yet([], {"run_date": "YYYY-MM-DD"})
    assert bench.not_run_yet([], {})
    assert not bench.not_run_yet([], {"run_date": "2026-10-01"})  # ran, found nothing — that's a result


def test_unmatched_rows_on_answer_pages_are_flagged_for_a_person(tmp_path):
    case = _case([{"id": "C1", "new_pages": ["10-12"], "new_anchors": ["網路韌性"]}], recall_only=True)
    on_page, off_page = _rows(tmp_path, case, "1,新增,,11,,(a) 船東應制定,,,", "2,新增,,40,,別處的改動,,,")
    assert bench.auto_match(on_page, case) == ()  # no anchor: could be a fragment of C1, or another change
    assert bench.on_answer_pages(on_page, case)
    assert not bench.on_answer_pages(off_page, case)


def test_carry_over_keeps_a_persons_judgement_only_for_identical_rows(tmp_path):
    previous = tmp_path / "plimsoll.csv"
    bench.write_rows(previous, [
        {**dict.fromkeys(bench.RESULT_COLUMNS, ""), "old_text": "a", "new_text": "b", "gt_id": "G1"},
        {**dict.fromkeys(bench.RESULT_COLUMNS, ""), "old_text": "c", "new_text": "d", "gt_id": "noise"},
    ])
    rows = [
        {**dict.fromkeys(bench.RESULT_COLUMNS, ""), "old_text": "a", "new_text": "b"},
        {**dict.fromkeys(bench.RESULT_COLUMNS, ""), "old_text": "c", "new_text": "d2"},
    ]
    assert bench.carry_over_adjudication(rows, previous) == 1
    assert [r["gt_id"] for r in rows] == ["G1", ""]


def test_report_renders_and_escapes(tmp_path):
    case = _two_item_case()
    rows = _rows(tmp_path, case, 'a,修改,3,3,85°C,80°C,High,,', 'b,修改,5,5,<script>,x,,,')
    s = _score(case, rows)
    page = bench.render_report([(case, [s])], [bench.combine([s])], tmp_path, {("t", "tool"): {"display_name": "T"}})
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "漏報" in page  # G2 was never reported


def test_registry_rejects_duplicates_and_our_own_name(tmp_path):
    (tmp_path / "competitors.json").write_text(json.dumps({"products": [{"tool": "a", "name": "A"}, {"tool": "a", "name": "A2"}]}), encoding="utf-8")
    with pytest.raises(SystemExit):
        bench.load_registry(tmp_path)
    (tmp_path / "competitors.json").write_text(json.dumps({"products": [{"tool": "plimsoll", "name": "x"}]}), encoding="utf-8")
    with pytest.raises(SystemExit):
        bench.load_registry(tmp_path)
    assert bench.load_registry(tmp_path / "missing") == []


def test_coverage_lists_products_nobody_has_run_yet(tmp_path):
    case = _two_item_case()
    s = _score(case, _rows(tmp_path, case, "a,修改,3,3,85°C,80°C,,,"))
    registry = [{"tool": "tool", "name": "Ran It"}, {"tool": "other", "name": "Not Yet"}]
    page = bench.render_report([(case, [s])], [bench.combine([s])], tmp_path, {}, registry)
    assert "清單共 2 項產品" in page and "目前 1 項有評分結果" in page
    assert "Not Yet" in page and "未跑" in page


# ── the engine on the demo case ──────────────────────────────────────────


@pytest.mark.skipif(not DEMO_CASE.exists(), reason="benchmark case missing")
def test_engine_still_finds_every_demo_item():
    """Regression guard, not an accuracy claim: the demo was designed with
    the ruleset (case.json says home_field), so anything short of full
    recall here means the engine itself regressed."""
    from backend.services import session_store

    case = bench.load_case(DEMO_CASE)
    old, new = REPO_ROOT / case.old_pdf, REPO_ROOT / case.new_pdf
    response = session_store.process_upload(old.read_bytes(), old.name, new.read_bytes(), new.name)
    session_dir = SESSIONS_ROOT / response["session"]["session_id"]
    try:
        differences = json.loads((session_dir / "differences.json").read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(session_dir, ignore_errors=True)

    rows = [
        bench.Reported(
            row=i, item_id=r["item_id"], change_type=r["change_type"],
            old_page=r["old_page"] or None, new_page=r["new_page"] or None,
            old_text=r["old_text"], new_text=r["new_text"], risk=r["risk"], gt_ids=None,
        )
        for i, r in enumerate(bench.plimsoll_rows(differences), start=2)
    ]
    s = _score(case, rows)
    assert s.missed_high == []
    assert s.detected == s.scored_total
    assert s.noise == []
