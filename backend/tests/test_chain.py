"""W5/W6 chain coordinator tests: parameter-series extraction and drift
computation against synthetic fixtures (fast, deterministic), plus an
end-to-end pass over the real demo PDFs (session/chain creation, review
event)."""

from __future__ import annotations

import shutil

import pytest

from backend.config import REPO_ROOT, SESSIONS_ROOT
from backend.services import chain as chain_service
from backend.services import session_store
from backend.services.extraction import ExtractedDocument, PageContent
from backend.storage.config_loader import get_ruleset

DEMO_DIR = REPO_ROOT / "data" / "demo"
DEMO_OLD = DEMO_DIR / "Main_Engine_Cooling_v1.0.pdf"
DEMO_NEW = DEMO_DIR / "Main_Engine_Cooling_v1.1.pdf"
DEMO_CHAIN_FILES = [DEMO_DIR / f"Main_Engine_Cooling_v1.{i}.pdf" for i in range(5)]


def _mk_page(pdf_page: int, lines: list[str], heading: str | None = None) -> PageContent:
    return PageContent(
        pdf_page=pdf_page,
        print_label=None,
        label_source="unknown",
        raw_text="\n".join(lines),
        lines=lines,
        lines_canonical=list(lines),
        char_count=sum(len(l) for l in lines),
        is_scanned=False,
        heading=heading,
    )


def _mk_doc(lines: list[str], heading: str | None) -> ExtractedDocument:
    page = _mk_page(1, lines, heading=heading)
    return ExtractedDocument(pages=[page], page_count=1, size_bytes=0)


@pytest.fixture
def ruleset_v2():
    return get_ruleset("v2")


def test_extract_parameter_points_keys_by_heading_and_unit():
    doc = _mk_doc(["3. 監控", "效率係數為 92.0%，供參考。"], heading="3. 監控")
    points = chain_service.extract_parameter_points(doc, "v1.0")
    assert list(points.keys()) == ["3._監控::%"]
    p = points["3._監控::%"][0]
    assert p.value == 92.0 and p.unit == "%" and p.version == "v1.0" and p.pdf_page == 1
    assert "92.0%" in p.source_text


def test_extract_parameter_points_uses_canonical_view_but_raw_source_text():
    from backend.models.config_models import TermAlias, TermAliasTable
    from backend.services.normalize import apply_term_aliases

    aliases = TermAliasTable(version="test", aliases=[TermAlias(canonical="溫度上限", variants=["最高溫度限值"])])
    doc = _mk_doc(["3. 監控", "最高溫度限值為 90.0°C。"], heading="3. 監控")
    doc = apply_term_aliases(doc, aliases)

    points = chain_service.extract_parameter_points(doc, "v1.0")
    key = "3._監控::°c"
    assert key in points
    # source_text is the ORIGINAL wording — W4 never rewrites reviewer-facing text.
    assert points[key][0].source_text == "最高溫度限值為 90.0°C。"


def test_merge_parameter_series_keeps_only_versions_where_the_key_appears():
    v1 = chain_service.extract_parameter_points(_mk_doc(["1. 段", "A 為 10.0%。"], "1. 段"), "v1.0")
    v2 = chain_service.extract_parameter_points(_mk_doc(["1. 段", "沒有數值的句子。"], "1. 段"), "v1.1")
    v3 = chain_service.extract_parameter_points(_mk_doc(["1. 段", "A 為 8.0%。"], "1. 段"), "v1.2")

    merged = chain_service._merge_parameter_series([v1, v2, v3])
    series = merged["1._段::%"]
    assert [p.version for p in series] == ["v1.0", "v1.2"]
    assert [p.value for p in series] == [10.0, 8.0]


def test_compute_drift_report_flags_a_consistent_series_as_high(ruleset_v2):
    from backend.models.chain import ParameterPoint

    series = [
        ParameterPoint(version=f"v1.{i}", value=20.0 - 0.2 * i, unit="%", pdf_page=1, source_text=f"line {i}")
        for i in range(5)
    ]
    findings = chain_service.compute_drift_report({"demo::%": series}, ruleset_v2)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.is_drift is True
    assert finding.risk == "High"
    assert finding.rule_id == "cumulative_drift"
    assert finding.series_length == 5
    assert finding.direction_consistent is True
    assert finding.first_version == "v1.0" and finding.last_version == "v1.4"


def test_compute_drift_report_does_not_flag_a_short_or_flat_series(ruleset_v2):
    from backend.models.chain import ParameterPoint

    flat = [ParameterPoint(version="v1.0", value=20.0, unit="%", pdf_page=1, source_text="x")]
    findings = chain_service.compute_drift_report({"demo::%": flat}, ruleset_v2)
    assert findings[0].is_drift is False
    assert findings[0].rule_id == "default"


# --------------------------------------------------------------------------
# end-to-end: real demo PDFs
# --------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    not (DEMO_OLD.exists() and DEMO_NEW.exists()), reason="run scripts/generate_demo_pdfs.py first"
)


@pytest.fixture
def cleanup_chain():
    created: list[str] = []
    yield created
    for session_id in created:
        shutil.rmtree(SESSIONS_ROOT / session_id, ignore_errors=True)


def test_build_chain_over_the_two_demo_versions_end_to_end(cleanup_chain):
    result = chain_service.build_chain(
        [(DEMO_OLD.read_bytes(), "old.pdf"), (DEMO_NEW.read_bytes(), "new.pdf")]
    )
    cleanup_chain.append(result["chain_id"])
    cleanup_chain.extend(result["manifest"].adjacent_session_ids)
    cleanup_chain.extend(result["manifest"].anchor_session_ids)

    manifest = result["manifest"]
    assert manifest.ordered_versions == ["v1.0", "v1.1"]
    assert manifest.anchor_session_ids == manifest.adjacent_session_ids  # v1→v2 shared (§02)
    assert len(manifest.adjacent_session_ids) == 1

    # The headline temperature parameter must show up as a tracked series
    # (section 3 also carries the W6 drift-demo %, hence the unit filter).
    temp_series = next(v for k, v in result["parameter_series"].items() if "冷卻溫度檢查" in k and k.endswith("::°c"))
    assert [p.value for p in temp_series] == [85.0, 80.0]

    got = chain_service.get_chain(result["chain_id"])
    assert got is not None
    assert got["chain_id"] == result["chain_id"]
    assert got["review_state"] == {}  # no CHAIN_REVIEW submitted yet


@pytest.mark.skipif(
    not all(p.exists() for p in DEMO_CHAIN_FILES), reason="run scripts/generate_demo_pdfs.py first"
)
def test_build_chain_over_five_demo_versions_flags_the_cumulative_drift(cleanup_chain):
    # W6 acceptance criterion verbatim: the drift-demo series (-0.2/version,
    # never enough on its own to trip any per-step rule) must end up High
    # once the whole chain is considered, while every other tracked series
    # (constant after v1.1) stays Low — and N=5 must cost 4 adjacent + 4
    # anchor comparisons with v1→v2 shared, i.e. 7 distinct sessions, per §02.
    files = [(p.read_bytes(), p.name) for p in DEMO_CHAIN_FILES]
    result = chain_service.build_chain(files)
    cleanup_chain.append(result["chain_id"])
    cleanup_chain.extend(result["manifest"].adjacent_session_ids)
    cleanup_chain.extend(result["manifest"].anchor_session_ids)

    manifest = result["manifest"]
    assert manifest.ordered_versions == ["v1.0", "v1.1", "v1.2", "v1.3", "v1.4"]
    assert len(manifest.adjacent_session_ids) == 4
    assert len(manifest.anchor_session_ids) == 4
    assert manifest.anchor_session_ids[0] == manifest.adjacent_session_ids[0]  # v1→v2 shared
    assert len({*manifest.adjacent_session_ids, *manifest.anchor_session_ids}) == 7  # 2*5-3

    findings = {f.canonical_param: f for f in result["drift_report"]}
    drift_key = next(k for k in findings if k.endswith("::%"))
    assert findings[drift_key].is_drift is True
    assert findings[drift_key].risk == "High"
    assert findings[drift_key].rule_id == "cumulative_drift"
    assert [p.value for p in findings[drift_key].series] == [20.0, 19.8, 19.6, 19.4, 19.2]

    # Everything else (temp/pressure, unchanged after v1.1) must stay Low —
    # the drift rule must not blanket-flag every tracked parameter.
    for key, finding in findings.items():
        if key != drift_key:
            assert finding.is_drift is False, f"{key} unexpectedly flagged as drift"


def test_submit_chain_review_records_a_chain_level_event_excluded_from_fold(cleanup_chain):
    result = chain_service.build_chain(
        [(DEMO_OLD.read_bytes(), "old.pdf"), (DEMO_NEW.read_bytes(), "new.pdf")]
    )
    cleanup_chain.append(result["chain_id"])
    cleanup_chain.extend(result["manifest"].adjacent_session_ids)
    cleanup_chain.extend(result["manifest"].anchor_session_ids)

    with pytest.raises(session_store.MissingReviewerName):
        chain_service.submit_chain_review(
            result["chain_id"], human_verdict="CONFIRMED", reviewer_name=" ", approval_role_code="DPA"
        )

    review = chain_service.submit_chain_review(
        result["chain_id"], human_verdict="CONFIRMED", reviewer_name="陳○○", approval_role_code="DPA"
    )
    assert review["event"]["event_type"] == "CHAIN_REVIEW"
    assert review["event"]["chain_id"] == result["chain_id"]
    # CHAIN_REVIEW is chain-level, not per-difference — fold must stay empty.
    assert review["chain"]["review_state"] == {}
    assert review["chain"]["review_events"][0]["event_type"] == "CHAIN_REVIEW"
