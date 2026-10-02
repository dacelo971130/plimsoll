"""Bigram TF-IDF cosine similarity (backend/services/text_similarity.py) —
moved here from test_comparison.py (W3 page-matching signal, docs/redesign/
plimsoll-real-document-smoketest-2026-09.html §7 conflict 1, option 丙) once
the logic was generalized from PageContent objects to plain strings so
backend/services/agent/tools.py's search_text/search_history could reuse it
for ranked free-text search instead of substring matching."""

from __future__ import annotations

from backend.services.text_similarity import build_vectors, cosine, rank


def test_identical_page_text_scores_close_to_one():
    text = "1. 標題\n第一段內容維持不變的說明文字，內容足夠長以產生穩定的 bigram 集合。"
    [vec_a, vec_b] = build_vectors([text, text])
    assert cosine(vec_a, vec_b) > 0.99


def test_unrelated_pages_score_near_zero():
    old_text = "1. 標題\n第一段內容維持不變的說明文字，內容足夠長以產生穩定的 bigram 集合。"
    new_text = "9. 完全不同主題\nThis entire page discusses an unrelated aircraft maintenance schedule instead."
    [vec_a, vec_b] = build_vectors([old_text, new_text])
    assert cosine(vec_a, vec_b) < 0.2


def test_list_to_prose_rewrite_scores_higher_than_the_old_fingerprint_would():
    # Shape of the real SOLAS p101/p57 case: same regulation, same vocabulary,
    # rewritten from a bulleted list into prose so the wording that would have
    # anchored a fixed-length line-prefix comparison moves down the page.
    old_text = "4.4.2 緊急照明配電盤\n位置：機艙控制室\n電源：緊急發電機\n測試週期：每月"
    new_text = "生效日期：2020 年新增修訂\n4.4.2 緊急照明配電盤應設置於機艙控制室內，由緊急發電機供電，並應每月測試一次其功能是否正常。"
    [old_vec, new_vec] = build_vectors([old_text, new_text])
    rewritten_score = cosine(old_vec, new_vec)

    unrelated_text = "9. 完全不同主題\n與上述規定完全無關的另一段落內容。"
    [_, unrelated_vec] = build_vectors([old_text, unrelated_text])
    unrelated_score = cosine(old_vec, unrelated_vec)

    # The real threshold calibration happens against actual documents — this
    # synthetic case only needs to show the rewritten pair is clearly closer
    # than an unrelated pair, not hit a specific number.
    assert rewritten_score > unrelated_score + 0.2


def test_two_blank_texts_never_score_as_identical():
    # An empty text has an empty vector, and two empty vectors must never be
    # treated as "perfectly similar" (e.g. two scanned pages with no
    # extractable text layer are NOT necessarily unchanged).
    [vec_a, vec_b] = build_vectors(["", ""])
    assert vec_a == {} and vec_b == {}
    assert cosine(vec_a, vec_b) == 0.0


def test_very_short_texts_do_not_crash_or_give_nonsensical_scores():
    # A single short line yields zero or one bigram — must not raise, and
    # must not spuriously score 1.0 against an unrelated short text.
    tiny_a, tiny_b, single_token = "1. 標題", "2. 次頁", "A"
    [vec_a, vec_b, vec_single] = build_vectors([tiny_a, tiny_b, single_token])
    for vec in (vec_a, vec_b, vec_single):
        assert isinstance(cosine(vec, vec_a), float)
    assert 0.0 <= cosine(vec_a, vec_b) <= 1.0
    assert vec_single == {}  # "A" alone has no adjacent-token pair to form a bigram


# --- rank(): the retrieval primitive search_text/search_history use in place
# of substring matching (backend/services/agent/tools.py) ---


def test_rank_puts_the_literal_match_first():
    candidates = [
        "冷卻液出口溫度必須維持在 80°C 以下，超過限值應立即停止主機並通知工程主管。",
        "本章說明船舶一般構造與穩度相關規定，適用於所有新建船舶。",
        "機艙通風系統每月應檢查一次，確保空氣流通順暢。",
    ]
    results = rank("冷卻液出口溫度必須維持在 80°C 以下", candidates)
    assert results[0][0] == 0
    # The query is a strict prefix of candidate 0, not its full text, so the
    # score isn't ~1.0 — what matters is it ranks clearly above the rest.
    assert results[0][1] > 0.5
    assert len(results) == 1 or results[0][1] > results[1][1] + 0.2


def test_rank_finds_a_differently_worded_paraphrase_of_the_right_candidate():
    # The actual capability gain over substring matching: the query shares no
    # exact substring with its target, just the same distinctive vocabulary.
    candidates = [
        "冷卻液出口溫度必須維持在 80°C 以下，超過限值應立即停止主機並通知工程主管。",
        "本章說明船舶一般構造與穩度相關規定，適用於所有新建船舶。",
        "機艙通風系統每月應檢查一次，確保空氣流通順暢。",
    ]
    query = "主機冷卻液的出口溫度上限是多少？超過的話要怎麼處理？"
    assert query not in candidates[0] and candidates[0].find(query) == -1  # no literal substring relationship
    results = rank(query, candidates)
    assert results and results[0][0] == 0


def test_rank_returns_empty_list_for_no_candidates():
    assert rank("隨便問點什麼", []) == []


def test_rank_drops_candidates_below_the_floor():
    candidates = ["冷卻液出口溫度必須維持在 80°C 以下", "完全無關的另一段英文 unrelated aircraft maintenance text"]
    results = rank("冷卻液出口溫度必須維持在 80°C 以下", candidates, floor=0.9)
    assert all(score >= 0.9 for _, score in results)
    assert len(results) == 1  # the unrelated candidate is filtered out
