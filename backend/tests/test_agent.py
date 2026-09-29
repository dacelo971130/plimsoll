"""覆核 Agent — tools, deterministic verification, the loop and the API,
all against a scripted fake client (no test here ever calls a model).

The properties that matter most, per the spec:
- tools are read-only and never leak rule ids;
- a claim survives only with a verbatim citation whose quotes contain its
  numbers and units; glossary terms need an approved glossary;
- out-of-scope and unsupported answers become fixed server text;
- running the agent leaves review_events.jsonl byte-for-byte unchanged."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.config import REPO_ROOT, SESSIONS_ROOT
from backend.main import app
from backend.services import session_store
from backend.services.agent import runs
from backend.services.agent.labels import RULE_LABEL
from backend.services.agent.runner import FALLBACK_BETA, MODEL_ID, AgentError, RunLimits, run_loop
from backend.services.agent.schemas import AgentAnswer, ReviewBriefing, strict_json_schema
from backend.services.agent.tools import TOOLS, SessionContext, ToolInputError, run_tool
from backend.services.agent.verify import NOT_IN_DOCUMENTS_TEXT, OUT_OF_SCOPE_TEXT, Verifier
from backend.models.config_models import Glossary

DEMO_OLD = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.0.pdf"
DEMO_NEW = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.1.pdf"


@pytest.fixture
def session_id():
    result = session_store.process_upload(DEMO_OLD.read_bytes(), DEMO_OLD.name, DEMO_NEW.read_bytes(), DEMO_NEW.name)
    sid = result["session"]["session_id"]
    yield sid
    session_store.delete_session(sid)


@pytest.fixture
def ctx(session_id) -> SessionContext:
    return SessionContext.load(session_id)


def _d01_quote(ctx: SessionContext, side: str) -> tuple[int, str]:
    span = ctx.difference("D01")[side]
    return span["page"]["pdf_page"], span["text"]


# ---- fake client -----------------------------------------------------------


def _usage():
    return SimpleNamespace(input_tokens=100, output_tokens=40, cache_creation_input_tokens=0, cache_read_input_tokens=60)


def tool_use(block_id: str, name: str, arguments: dict):
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=arguments)


def text(value: str):
    return SimpleNamespace(type="text", text=value)


def response(content: list, stop: str):
    return SimpleNamespace(content=content, stop_reason=stop, usage=_usage(), model=MODEL_ID)


class FakeClient:
    def __init__(self, script: list):
        self.calls: list[dict] = []
        self._script = list(script)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        # Snapshot: the loop keeps appending to the same messages list.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._script.pop(0)


def briefing_json(ctx: SessionContext, **overrides) -> str:
    page, quote = _d01_quote(ctx, "new")
    citation = {"session_id": None, "difference_id": "D01", "side": "new", "pdf_page": page, "quote": quote}
    body = {
        "summary": "新版調降冷卻液出口溫度上限。",
        "warnings": [],
        "priority": [{"difference_id": "D01", "reason": "出口溫度改為 80°C，涉及安全門檻。", "citations": [citation]}],
        "items": [
            {
                "difference_ids": ["D01"],
                "impact": {"equipment": ["冷卻液"], "parts": [], "procedures": [], "inspections": ["冷卻液出口溫度"]},
                "action": "停用舊版",
                "action_detail": "舊版以 85°C 為準的檢查表應停用。",
                "confidence": "high",
                "citations": [citation, {"session_id": None, "difference_id": "D01", "side": "old", "pdf_page": _d01_quote(ctx, "old")[0], "quote": _d01_quote(ctx, "old")[1]}],
            }
        ],
        "suggestions": [{"difference_id": "D01", "verdict": "TRACK", "reason": "門檻改為 80°C，需確認現場設定。", "citations": [citation]}],
        "cause_trace": [],
        "history": [],
        "pending": [],
        "glossary_terms": ["風險等級"],
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)


# ---- schema ----------------------------------------------------------------


@pytest.mark.parametrize("model", [ReviewBriefing, AgentAnswer])
def test_output_schema_is_strict(model):
    def walk(node):
        if isinstance(node, dict):
            assert "title" not in node
            if node.get("type") == "object" and "properties" in node:
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(strict_json_schema(model))


# ---- tools -----------------------------------------------------------------


def test_tools_are_read_only_and_never_show_rule_ids(ctx):
    outputs = [
        run_tool(ctx, "get_session_overview", {}),
        run_tool(ctx, "list_differences", {}),
        run_tool(ctx, "get_difference", {"difference_id": "D01"}),
        run_tool(ctx, "explain_rule", {"rule": RULE_LABEL["numeric_safety"]}),
    ]
    for out in outputs:
        for rule_id in RULE_LABEL:
            assert f'"{rule_id}"' not in out
    assert json.loads(outputs[1])["count"] == 13
    assert json.loads(run_tool(ctx, "list_differences", {"risk": "High"}))["count"] == 8
    detail = json.loads(outputs[2])
    assert detail["rule"] == RULE_LABEL["numeric_safety"]
    assert "85°C" in detail["old"]["text"] and "80°C" in detail["new"]["text"]


def test_tool_input_errors_go_back_to_the_model(ctx):
    with pytest.raises(ToolInputError):
        run_tool(ctx, "read_page", {"side": "new", "pdf_page": 999})
    with pytest.raises(ToolInputError):
        run_tool(ctx, "get_difference", {"difference_id": "D99"})
    with pytest.raises(ToolInputError):
        run_tool(ctx, "get_difference", {"difference_id": "D01", "extra": 1})
    with pytest.raises(ToolInputError):
        run_tool(ctx, "no_such_tool", {})


def test_search_and_glossary_tools(ctx):
    hits = json.loads(run_tool(ctx, "search_text", {"query": "80°C"}))["hits"]
    assert hits and all(h["side"] in ("old", "new") for h in hits)
    # The repo's glossary is still a draft, so the agent may not use it.
    looked_up = json.loads(run_tool(ctx, "lookup_glossary", {"term": "風險等級"}))
    assert looked_up["found"] is False


def test_every_tool_schema_is_closed():
    for spec in TOOLS:
        assert spec.input_schema["additionalProperties"] is False


# ---- verification ----------------------------------------------------------


def _approved_glossary() -> Glossary:
    return Glossary(
        version="v1",
        status="approved",
        terms=[{"term": "風險等級", "category": "c", "definition": "受控定義", "sources": ["x"], "status": "approved"}],
    )


def test_verified_briefing_keeps_supported_claims(ctx):
    result = Verifier(ctx, _approved_glossary()).briefing(ReviewBriefing.model_validate_json(briefing_json(ctx)))
    assert [p["difference_id"] for p in result["priority"]] == ["D01"]
    assert result["items"][0]["action"] == "停用舊版"
    assert result["suggestions"][0]["verdict"] == "TRACK"
    assert result["glossary"] == [{"term": "風險等級", "definition": "受控定義"}]
    assert result["verification"].get("citations_rejected", 0) == 0


def test_paraphrased_quote_moves_claim_to_pending(ctx):
    page, _ = _d01_quote(ctx, "new")
    bad = {"session_id": None, "difference_id": "D01", "side": "new", "pdf_page": page, "quote": "出口溫度大約八十度"}
    raw = ReviewBriefing.model_validate_json(
        briefing_json(ctx, priority=[{"difference_id": "D01", "reason": "溫度下修。", "citations": [bad]}])
    )
    result = Verifier(ctx, None).briefing(raw)
    assert result["priority"] == []
    assert any("逐字" in p["reason"] for p in result["pending"])


def test_changed_unit_is_caught(ctx):
    page, quote = _d01_quote(ctx, "new")
    citation = {"session_id": None, "difference_id": "D01", "side": "new", "pdf_page": page, "quote": quote}
    raw = ReviewBriefing.model_validate_json(
        briefing_json(ctx, priority=[{"difference_id": "D01", "reason": "溫度上限改為 80 度。", "citations": [citation]}])
    )
    result = Verifier(ctx, None).briefing(raw)
    assert result["priority"] == []
    assert any("數字" in p["reason"] for p in result["pending"])


def test_wrong_number_is_caught(ctx):
    page, quote = _d01_quote(ctx, "new")
    citation = {"session_id": None, "difference_id": "D01", "side": "new", "pdf_page": page, "quote": quote}
    raw = ReviewBriefing.model_validate_json(
        briefing_json(ctx, priority=[{"difference_id": "D01", "reason": "溫度上限改為 75°C。", "citations": [citation]}])
    )
    assert Verifier(ctx, None).briefing(raw)["priority"] == []


def test_unapproved_glossary_sends_terms_to_pending(ctx):
    draft = Glossary(version="v1", status="draft", terms=[])
    result = Verifier(ctx, draft).briefing(ReviewBriefing.model_validate_json(briefing_json(ctx)))
    assert result["glossary"] == []
    assert {"topic": "風險等級", "reason": "詞彙表尚未經人工核准"} in result["pending"]
    # Counted by cause: an undefined term is not a failed citation.
    assert result["verification"]["terms_to_pending"] == 1
    assert "claims_to_pending" not in result["verification"]


def test_rule_ids_are_scrubbed_and_unknown_ids_dropped(ctx):
    page, quote = _d01_quote(ctx, "new")
    citation = {"session_id": None, "difference_id": "D01", "side": "new", "pdf_page": page, "quote": quote}
    raw = ReviewBriefing.model_validate_json(
        briefing_json(
            ctx,
            priority=[
                {"difference_id": "D01", "reason": "命中 numeric_safety。", "citations": [citation]},
                {"difference_id": "D99", "reason": "不存在。", "citations": [citation]},
            ],
        )
    )
    result = Verifier(ctx, None).briefing(raw)
    assert [p["difference_id"] for p in result["priority"]] == ["D01"]
    assert "numeric_safety" not in result["priority"][0]["reason"]
    assert RULE_LABEL["numeric_safety"] in result["priority"][0]["reason"]


def test_priority_is_capped_at_five(ctx):
    page, quote = _d01_quote(ctx, "new")
    citation = {"session_id": None, "difference_id": "D01", "side": "new", "pdf_page": page, "quote": quote}
    raw = ReviewBriefing.model_validate_json(
        briefing_json(ctx, priority=[{"difference_id": "D01", "reason": f"理由{c}", "citations": [citation]} for c in "甲乙丙丁戊己庚"])
    )
    result = Verifier(ctx, None).briefing(raw)
    assert len(result["priority"]) == 5
    assert result["verification"]["priority_truncated"] == 2


def test_missing_metadata_warning_comes_from_the_server(ctx):
    ctx.session["new_meta"]["missing_fields"] = ["version"]
    result = Verifier(ctx, None).briefing(ReviewBriefing.model_validate_json(briefing_json(ctx)))
    first = result["warnings"][0]
    assert first["kind"] == "missing_metadata" and first["source"] == "system" and "版本號" in first["message"]


def test_unverifiable_number_in_summary_is_replaced(ctx):
    raw = ReviewBriefing.model_validate_json(briefing_json(ctx, summary="溫度門檻從 90°C 降到 70°C。"))
    result = Verifier(ctx, None).briefing(raw)
    assert "90°C" not in result["summary"]
    assert result["verification"]["summary_replaced"] == 1


def test_out_of_scope_answer_is_fixed_server_text(ctx):
    raw = AgentAnswer(answer_type="out_of_scope", text="今天天氣晴。", citations=[], pending=[], glossary_terms=[])
    result = Verifier(ctx, None).answer(raw, "今天天氣如何？")
    assert result == {**result, "answer_type": "out_of_scope", "text": OUT_OF_SCOPE_TEXT, "citations": []}


def test_answer_without_valid_citation_is_downgraded(ctx):
    raw = AgentAnswer(answer_type="answer", text="依一般規範應為 75°C。", citations=[], pending=[], glossary_terms=[])
    result = Verifier(ctx, None).answer(raw, "標準溫度是多少？")
    assert result["answer_type"] == "not_in_documents"
    assert result["text"] == NOT_IN_DOCUMENTS_TEXT
    assert result["pending"][0]["topic"] == "標準溫度是多少？"


def test_supported_answer_passes(ctx):
    page, quote = _d01_quote(ctx, "new")
    raw = AgentAnswer(
        answer_type="answer",
        text="新版出口溫度上限是 80°C。",
        citations=[{"session_id": None, "difference_id": "D01", "side": "new", "pdf_page": page, "quote": quote}],
        pending=[],
        glossary_terms=[],
    )
    result = Verifier(ctx, None).answer(raw, "新版溫度上限？")
    assert result["answer_type"] == "answer" and result["citations"][0]["print_label"]


# ---- loop ------------------------------------------------------------------


def test_loop_runs_tools_then_returns_verified_shape(ctx):
    client = FakeClient(
        [
            response([tool_use("t1", "get_session_overview", {})], "tool_use"),
            response([tool_use("t2", "get_difference", {"difference_id": "D01"})], "tool_use"),
            response([text(briefing_json(ctx))], "end_turn"),
        ]
    )
    steps = []
    raw, loop = run_loop(
        client, system="s", user_content="u", ctx=ctx, output_model=ReviewBriefing,
        limits=RunLimits(max_tool_calls=5, max_seconds=60), on_step=steps.append,
    )
    assert isinstance(raw, ReviewBriefing)
    assert [s.label for s in steps] == ["讀取比對概況", "讀取 D01"]
    assert loop.usage["cache_read_input_tokens"] == 180
    first = client.calls[0]
    assert first["model"] == MODEL_ID
    assert first["thinking"] == {"type": "adaptive"}
    assert first["output_config"]["format"]["type"] == "json_schema"
    assert first["fallbacks"] == "default" and first["betas"] == [FALLBACK_BETA]
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    # The tool result for t2 went back in the third request.
    assert client.calls[2]["messages"][-1]["content"][0]["tool_use_id"] == "t2"


def test_tool_error_is_returned_as_error_result(ctx):
    client = FakeClient(
        [
            response([tool_use("t1", "get_difference", {"difference_id": "D99"})], "tool_use"),
            response([text(briefing_json(ctx))], "end_turn"),
        ]
    )
    run_loop(client, system="s", user_content="u", ctx=ctx, output_model=ReviewBriefing, limits=RunLimits(5, 60))
    result = client.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "D99" in result["content"]


def test_tool_limit_asks_to_finish_then_aborts(ctx):
    over = [response([tool_use(f"t{i}", "get_session_overview", {})], "tool_use") for i in range(3)]
    client = FakeClient(over)
    with pytest.raises(AgentError):
        run_loop(client, system="s", user_content="u", ctx=ctx, output_model=ReviewBriefing, limits=RunLimits(1, 60))
    notice = client.calls[2]["messages"][-1]["content"][0]
    assert notice["is_error"] is True and "上限" in notice["content"]


def test_refusal_and_bad_json_fail_cleanly(ctx):
    with pytest.raises(AgentError):
        run_loop(FakeClient([response([], "refusal")]), system="s", user_content="u", ctx=ctx, output_model=ReviewBriefing, limits=RunLimits(5, 60))
    with pytest.raises(AgentError):
        run_loop(FakeClient([response([text("{not json")], "end_turn")]), system="s", user_content="u", ctx=ctx, output_model=ReviewBriefing, limits=RunLimits(5, 60))


def test_time_limit(ctx):
    ticks = iter([0.0, 999.0])
    with pytest.raises(AgentError):
        run_loop(
            FakeClient([response([tool_use("t1", "get_session_overview", {})], "tool_use")]),
            system="s", user_content="u", ctx=ctx, output_model=ReviewBriefing, limits=RunLimits(5, 10), clock=lambda: next(ticks),
        )


# ---- runs + API --------------------------------------------------------------


def _wait(client: TestClient, sid: str, run_id: str) -> dict:
    for _ in range(100):
        body = client.get(f"/api/sessions/{sid}/agent/runs/{run_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError("agent run did not finish")


def test_api_briefing_end_to_end_is_read_only(session_id, ctx, monkeypatch):
    events = SESSIONS_ROOT / session_id / "review_events.jsonl"
    before = events.read_bytes()
    fake = FakeClient(
        [
            response([tool_use("t1", "get_difference", {"difference_id": "D01"})], "tool_use"),
            response([text(briefing_json(ctx))], "end_turn"),
        ]
    )
    monkeypatch.setattr("backend.api.agent.resolve_agent_client", lambda *_: (fake, None))
    api = TestClient(app)

    started = api.post(f"/api/sessions/{session_id}/agent/briefing")
    assert started.status_code == 202
    done = _wait(api, session_id, started.json()["run_id"])
    assert done["status"] == "done"
    assert done["steps"][0]["label"] == "讀取 D01"
    assert done["result"]["priority"][0]["difference_id"] == "D01"

    assert events.read_bytes() == before  # A5: the agent never writes a review event
    record = json.loads((SESSIONS_ROOT / session_id / runs.RUNS_FILE).read_text(encoding="utf-8").splitlines()[-1])
    assert record["kind"] == "briefing" and record["provider"] == "anthropic" and record["usage"]["input_tokens"] == 200
    assert api.get(f"/api/sessions/{session_id}/agent/latest").json()["briefing"]["run_id"] == done["run_id"]


def test_api_question_out_of_scope(session_id, monkeypatch):
    fake = FakeClient([response([text(json.dumps({"answer_type": "out_of_scope", "text": "", "citations": [], "pending": [], "glossary_terms": []}))], "end_turn")])
    monkeypatch.setattr("backend.api.agent.resolve_agent_client", lambda *_: (fake, None))
    api = TestClient(app)
    started = api.post(f"/api/sessions/{session_id}/agent/questions", json={"question": "幫我寫一段 Python"})
    done = _wait(api, session_id, started.json()["run_id"])
    assert done["result"]["answer_type"] == "out_of_scope" and done["result"]["text"] == OUT_OF_SCOPE_TEXT


def test_api_rejects_blank_questions_and_unknown_sessions(session_id, monkeypatch):
    monkeypatch.setattr("backend.api.agent.resolve_agent_client", lambda *_: (FakeClient([]), None))
    api = TestClient(app)
    assert api.post(f"/api/sessions/{session_id}/agent/questions", json={"question": "   "}).status_code == 422
    assert api.post("/api/sessions/s-nope/agent/briefing").status_code == 404


def test_status_and_no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    api = TestClient(app)
    body = api.get("/api/agent/status").json()
    assert body["available"] is False and body["reason"]
    other = api.get("/api/agent/status", headers={"X-Llm-Provider": "gemini", "X-Llm-Api-Key": "k"}).json()
    assert other["available"] is False and "Claude" in other["reason"]
    mine = api.get("/api/agent/status", headers={"X-Llm-Provider": "anthropic", "X-Llm-Api-Key": "k"}).json()
    assert mine["available"] is True


def test_briefing_without_key_is_409_not_a_crash(session_id, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert TestClient(app).post(f"/api/sessions/{session_id}/agent/briefing").status_code == 409
