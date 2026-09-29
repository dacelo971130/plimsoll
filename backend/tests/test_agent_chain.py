"""覆核 Agent bonus items (spec §4.2 item 6): 變更原因追溯 across a
multi-version chain and 歷史案例 from earlier local comparisons — plus the
cross-comparison citations both rely on, which verify.py must check against
*that* comparison's pages, not this one's."""

from __future__ import annotations

import importlib.util
import json
import shutil

import pytest

from backend.config import REPO_ROOT, SESSIONS_ROOT
from backend.services import chain as chain_service
from backend.services import session_store
from backend.services.agent.schemas import ReviewBriefing
from backend.services.agent.tools import SessionContext, ToolInputError, run_tool
from backend.services.agent.verify import Verifier

DEMO = REPO_ROOT / "data" / "demo"
_spec = importlib.util.spec_from_file_location("generate_demo_pdfs", REPO_ROOT / "scripts" / "generate_demo_pdfs.py")
_generator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_generator)
REASONS = _generator.REVISION_REASONS


@pytest.fixture(scope="module")
def chain():
    versions = [(DEMO / f"Main_Engine_Cooling_v1.{i}.pdf").read_bytes() for i in range(5)]
    built = chain_service.build_chain([(b, f"v1.{i}.pdf") for i, b in enumerate(versions)])
    manifest = built["manifest"]
    yield manifest
    for sid in {*manifest.adjacent_session_ids, *manifest.anchor_session_ids, manifest.chain_id}:
        shutil.rmtree(SESSIONS_ROOT / sid, ignore_errors=True)


@pytest.fixture
def anchor_ctx(chain) -> SessionContext:
    return SessionContext.load(chain.anchor_session_ids[-1])  # v1.0 → v1.4


@pytest.fixture
def pair_id():
    old, new = DEMO / "Main_Engine_Cooling_v1.0.pdf", DEMO / "Main_Engine_Cooling_v1.1.pdf"
    sid = session_store.process_upload(old.read_bytes(), old.name, new.read_bytes(), new.name)["session"]["session_id"]
    yield sid
    session_store.delete_session(sid)


def _norm(text: str) -> str:
    # Same folding as verify._norm: chain source_text uses half-width
    # punctuation where the page text has full-width.
    import unicodedata

    return "".join(unicodedata.normalize("NFKC", text).split())


def test_session_knows_its_chain(anchor_ctx):
    overview = json.loads(run_tool(anchor_ctx, "get_session_overview", {}))
    assert overview["chain"]["versions"] == ["v1.0", "v1.1", "v1.2", "v1.3", "v1.4"]


def test_parameter_trail_points_are_citable(anchor_ctx):
    listing = json.loads(run_tool(anchor_ctx, "get_parameter_trail", {}))
    drift = next(p for p in listing["parameters"] if p["parameter"].endswith("（%）"))
    assert "::" not in drift["parameter"] and "_" not in drift["parameter"]
    trail = json.loads(run_tool(anchor_ctx, "get_parameter_trail", {"parameter": drift["parameter"]}))
    assert [p["value"] for p in trail["points"]] == [20.0, 19.8, 19.6, 19.4, 19.2]
    for point in trail["points"]:
        where = point["cite_as"]
        page = next(p for p in session_store.get_pages(where["session_id"])[where["side"]] if p["pdf_page"] == where["pdf_page"])
        assert _norm(point["source_text"]) in _norm(page["text"])


def test_version_page_carries_the_revision_reason(anchor_ctx):
    page = json.loads(run_tool(anchor_ctx, "read_version_page", {"version": "v1.2", "pdf_page": 7}))
    assert _norm(REASONS["v1.2"]) in _norm(page["text"])
    with pytest.raises(ToolInputError):
        run_tool(anchor_ctx, "read_version_page", {"version": "v9.9", "pdf_page": 1})


def test_chain_tools_refuse_outside_a_chain(pair_id):
    ctx = SessionContext.load(pair_id)
    assert json.loads(run_tool(ctx, "get_session_overview", {}))["chain"] is None
    with pytest.raises(ToolInputError):
        run_tool(ctx, "get_parameter_trail", {})


def test_history_search_finds_other_comparisons_only(chain, pair_id):
    ctx = SessionContext.load(pair_id)
    hits = json.loads(run_tool(ctx, "search_history", {"query": "料號"}))["hits"]
    assert hits and all(h["session_id"] != pair_id for h in hits)
    assert {h["session_id"] for h in hits} & {*chain.adjacent_session_ids, *chain.anchor_session_ids}


def _briefing(**overrides) -> ReviewBriefing:
    body = {
        "summary": "摘要。", "warnings": [], "priority": [], "items": [], "suggestions": [],
        "cause_trace": [], "history": [], "pending": [], "glossary_terms": [],
    }
    body.update(overrides)
    return ReviewBriefing.model_validate(body)


def _reason_citation(anchor_ctx, version="v1.1"):
    page = json.loads(run_tool(anchor_ctx, "read_version_page", {"version": version, "pdf_page": 7}))
    where = page["cite_as"]
    return {"session_id": where["session_id"], "difference_id": None, "side": where["side"], "pdf_page": 7, "quote": REASONS[version]}


def test_cause_trace_with_a_documented_reason(anchor_ctx):
    citation = _reason_citation(anchor_ctx)
    raw = _briefing(cause_trace=[{"parameter": "冷卻液出口溫度", "changed_in_version": "v1.1", "reason": "例行巡檢發現冷卻液出口讀值偏高，因此收緊出口門檻。", "citations": [citation]}])
    result = Verifier(anchor_ctx, None).briefing(raw)
    trace = result["cause_trace"][0]
    assert trace["changed_in_version"] == "v1.1"
    cited = trace["citations"][0]
    assert cited["session_id"] == citation["session_id"] and cited["version_label"] == "v1.1"


def test_cause_trace_rejects_unknown_versions_and_unverifiable_quotes(anchor_ctx):
    citation = _reason_citation(anchor_ctx)
    bad_quote = {**citation, "quote": "因應新法規要求下修門檻"}
    raw = _briefing(
        cause_trace=[
            {"parameter": "x", "changed_in_version": "v9.9", "reason": "文件未載明", "citations": [citation]},
            {"parameter": "y", "changed_in_version": "v1.2", "reason": "因應新法規要求下修門檻", "citations": [bad_quote]},
        ]
    )
    result = Verifier(anchor_ctx, None).briefing(raw)
    assert result["cause_trace"] == []
    assert len(result["pending"]) == 2


def test_history_must_point_elsewhere_and_exist(chain, pair_id):
    ctx = SessionContext.load(pair_id)
    other = chain.adjacent_session_ids[0]  # v1.0 → v1.1 inside the chain
    d05 = session_store.get_session(other)["differences"]
    part = next(d for d in d05 if "料號" in ((d.get("new") or {}).get("text") or ""))
    citation = {"session_id": other, "difference_id": part["id"], "side": "new", "pdf_page": part["new"]["page"]["pdf_page"], "quote": part["new"]["text"]}
    raw = _briefing(
        history=[
            {"session_id": other, "difference_id": part["id"], "note": "同樣是密封件料號更換。", "citations": [citation]},
            {"session_id": pair_id, "difference_id": "D01", "note": "自己。", "citations": [citation]},
            {"session_id": "s-nope", "difference_id": "D01", "note": "不存在。", "citations": [citation]},
        ]
    )
    result = Verifier(ctx, None).briefing(raw)
    assert [h["session_id"] for h in result["history"]] == [other]
    assert result["history"][0]["versions"] == "v1.0 → v1.1"
    assert len(result["pending"]) == 2


def test_trail_source_text_is_citable_despite_punctuation_width(anchor_ctx):
    # The trail's source_text has a half-width comma, the page a full-width
    # one; the model will quote source_text, and that must verify.
    listing = json.loads(run_tool(anchor_ctx, "get_parameter_trail", {}))
    label = next(p["parameter"] for p in listing["parameters"] if p["parameter"].endswith("（%）"))
    point = json.loads(run_tool(anchor_ctx, "get_parameter_trail", {"parameter": label}))["points"][1]  # v1.1
    where = point["cite_as"]
    citation = {"session_id": where["session_id"], "difference_id": None, "side": where["side"], "pdf_page": where["pdf_page"], "quote": point["source_text"]}
    raw = _briefing(cause_trace=[{"parameter": label, "changed_in_version": "v1.1", "reason": "文件未載明", "citations": [citation]}])
    assert Verifier(anchor_ctx, None).briefing(raw)["cause_trace"][0]["citations"][0]["version_label"] == "v1.1"
