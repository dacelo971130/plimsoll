"""The scope-guard question set and its pass/fail logic (scripts/agent_eval.py).
Running the set costs money, so it's a manual script; what can be checked
offline is that the set is well-formed and that `check()` grades correctly."""

from __future__ import annotations

import importlib.util
import json

import pytest

from backend.config import REPO_ROOT

_spec = importlib.util.spec_from_file_location("agent_eval", REPO_ROOT / "scripts" / "agent_eval.py")
agent_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent_eval)

DATA = json.loads((REPO_ROOT / "scripts" / "agent_eval_questions.json").read_text(encoding="utf-8"))


def test_question_set_is_well_formed():
    questions = DATA["questions"]
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids))
    assert all(q["expect"] in DATA["expectations"] for q in questions)
    assert sum(q["expect"] == "refuse" for q in questions) >= 20  # spec §4.6: 20 題範圍外題組
    assert all(q.get("term") for q in questions if q["expect"] == "glossary_pending")


def test_chain_question_set_is_well_formed():
    """W5/W6 chain demo bonus (spec §4.2 item 6) — multi-version questions
    asked against a fresh v1.0 → v1.4 chain instead of the pairwise demo."""
    chain_questions = [q for q in DATA["questions"] if q.get("context") == "chain"]
    assert len(chain_questions) >= 6
    for q in chain_questions:
        assert q["expect"] in DATA["expectations"]
        if q["expect"] == "answer_cites_version":
            assert isinstance(q.get("version"), str) and q["version"]
        if q["expect"] == "answer_multi":
            assert isinstance(q.get("min_citations"), int) and q["min_citations"] >= 2
    # Every other question is implicitly pairwise (no "context", or
    # "context" omitted) — scripts/agent_eval.py's new_session_id() only
    # special-cases "chain", so nothing here may silently fall through.
    assert all(q.get("context") in (None, "chain") for q in DATA["questions"])


def _result(answer_type="answer", citations=1, glossary=(), pending=(), versions=None):
    # `versions`, when given, replaces the generic `citations` count with one
    # citation per version label — the only shape answer_cites_version cares
    # about (see verify.py's Citation.version_label, quoted in agent_eval.py's
    # check()).
    cite_list = [{"quote": "q", "version_label": v} for v in versions] if versions is not None else [{"quote": "q"}] * citations
    return {
        "answer_type": answer_type,
        "text": "",
        "citations": cite_list,
        "glossary": list(glossary),
        "pending": [{"topic": t, "reason": "r"} for t in pending],
    }


@pytest.mark.parametrize(
    ("expect", "result", "ok"),
    [
        ("refuse", _result("out_of_scope", 0), True),
        ("refuse", _result("not_in_documents", 0), True),
        ("refuse", _result("answer", 1), False),
        ("answer", _result("answer", 2), True),
        ("answer", _result("answer", 0), False),
        ("answer", _result("not_in_documents", 0), False),
        ("not_found", _result("not_in_documents", 0), True),
        ("not_found", _result("answer", 1), False),
        ("glossary_pending", _result("not_in_documents", 0, pending=["風險等級"]), True),
        ("glossary_pending", _result("answer", 1, glossary=[{"term": "風險等級", "definition": "d"}]), False),
    ],
)
def test_check_grades_verified_results(expect, result, ok):
    assert agent_eval.check(expect, result, "風險等級")[0] is ok


@pytest.mark.parametrize(
    ("result", "version", "ok"),
    [
        (_result("answer", versions=["v1.1"]), "v1.1", True),
        (_result("answer", versions=["v1.0", "v1.1"]), "v1.1", True),  # any one citation matching is enough
        (_result("answer", versions=["v1.0"]), "v1.1", False),  # cited, but not the version asked about
        (_result("answer", versions=[]), "v1.1", False),  # answer_type answer but no citations at all
        (_result("not_in_documents", versions=[]), "v1.1", False),
    ],
)
def test_check_grades_answer_cites_version(result, version, ok):
    assert agent_eval.check("answer_cites_version", result, version=version)[0] is ok


@pytest.mark.parametrize(
    ("result", "min_citations", "ok"),
    [
        (_result("answer", citations=2), 2, True),
        (_result("answer", citations=3), 2, True),
        (_result("answer", citations=1), 2, False),
        (_result("not_in_documents", citations=0), 2, False),
    ],
)
def test_check_grades_answer_multi(result, min_citations, ok):
    assert agent_eval.check("answer_multi", result, min_citations=min_citations)[0] is ok


def test_failed_run_never_passes():
    assert agent_eval.check("refuse", None, None)[0] is False


def test_script_refuses_to_run_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["agent_eval.py"])
    with pytest.raises(SystemExit) as exc:
        agent_eval.main()
    assert "not set" in str(exc.value)
