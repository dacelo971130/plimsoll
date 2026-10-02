"""The LLM baseline runner (scripts/llm_baseline.py) without calling any
model: turning model output into result rows, cost estimation, and the
prompt/input the three models are given."""

from __future__ import annotations

import importlib.util
import sys

import pytest

from backend.config import REPO_ROOT

_spec = importlib.util.spec_from_file_location("llm_baseline", REPO_ROOT / "scripts" / "llm_baseline.py")
llm = importlib.util.module_from_spec(_spec)
sys.modules["llm_baseline"] = llm
_spec.loader.exec_module(llm)

HEADER = "change_type,old_page,new_page,old_text,new_text,risk,note"


def _turn(text: str, truncated: bool = False) -> llm.Turn:
    return llm.Turn(text=text, truncated=truncated, stop="x", usage={}, cost=0.0)


def test_rows_come_from_the_fenced_csv_block():
    text = f"說明文字\n```csv\n{HEADER}\n修改,3,3,85°C,80°C,High,溫度下修\n新增,,7,,\"新章節，含逗號\",Low,\n```\n結尾"
    rows = llm.extract_rows([_turn(text)])
    assert [(r["change_type"], r["new_text"]) for r in rows] == [("修改", "80°C"), ("新增", "新章節，含逗號")]


def test_unfenced_output_is_still_read():
    rows = llm.extract_rows([_turn(f"{HEADER}\n刪除,6,,舊句,,Low,")])
    assert rows[0]["old_text"] == "舊句"


def test_truncated_turn_drops_its_partial_last_row_and_continuation_without_header_is_read():
    first = _turn(f"```csv\n{HEADER}\n修改,3,3,a,b,High,\n修改,4,4,c,d", truncated=True)  # cut mid-row, no closing fence
    second = _turn("```csv\n修改,4,4,c,dd,Low,\n修改,3,3,a,b,High,\n```")  # resumes; repeats one row
    rows = llm.extract_rows([first, second])
    assert [(r["old_text"], r["new_text"]) for r in rows] == [("a", "b"), ("c", "dd")]


def test_unreadable_values_are_blanked_and_kept_in_the_note():
    (row,) = llm.to_result_rows("x", [{"change_type": "移動", "risk": "Critical", "old_text": "a", "new_text": "b", "note": "n"}])
    assert row["change_type"] == "" and row["risk"] == ""
    assert "移動" in row["note"] and "Critical" in row["note"]
    (ok,) = llm.to_result_rows("x", [{"change_type": "modified", "risk": "高", "old_text": "a", "new_text": "b"}])
    assert (ok["change_type"], ok["risk"], ok["item_id"]) == ("修改", "High", "x-1")


def test_long_context_tier_reprices_the_whole_request():
    gpt = llm.MODELS["gpt-api"]
    short = llm.request_cost(gpt, input_tokens=100_000, cached_tokens=0, cache_write_tokens=0, output_tokens=10_000)
    long = llm.request_cost(gpt, input_tokens=300_000, cached_tokens=0, cache_write_tokens=0, output_tokens=10_000)
    assert short == pytest.approx((100_000 * 10 + 10_000 * 50) / 1e6)
    assert long == pytest.approx((300_000 * 20 + 10_000 * 75) / 1e6)
    claude = llm.MODELS["claude-api"]
    cached = llm.request_cost(claude, input_tokens=500_000, cached_tokens=400_000, cache_write_tokens=0, output_tokens=0)
    assert cached == pytest.approx((100_000 * 4 + 400_000 * 0.20) / 1e6)


def test_follow_up_stops_before_the_budget_runs_out():
    turns = [llm.Turn("", True, "max_tokens", {}, cost=5.0)]
    assert llm._can_follow_up(turns, remaining=10.0)
    assert not llm._can_follow_up(turns, remaining=9.0)


def test_prompt_is_the_one_people_paste_and_reveals_no_answer():
    prompt = llm.load_prompt()
    assert prompt.startswith("我上傳了同一份文件的兩個版本")
    assert "change_type,old_page,new_page,old_text,new_text,risk,note" in prompt
    for leaked in ("1.10", "網路韌性", "操錨絞機", "80°C", "增修表"):
        assert leaked not in prompt


def test_document_text_marks_every_page_of_both_files():
    demo = REPO_ROOT / "data" / "demo"
    text = llm.document_text(demo / "Main_Engine_Cooling_v1.0.pdf", demo / "Main_Engine_Cooling_v1.1.pdf")
    assert "檔案 1（舊版）" in text and "檔案 2（新版）" in text
    assert "===== 檔案 1 第 6 頁 =====" in text and "===== 檔案 2 第 7 頁 =====" in text
    assert "===== 檔案 1 第 7 頁 =====" not in text  # v1.0 has six pages
