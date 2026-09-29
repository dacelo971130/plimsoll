"""P5 Message Batches tests. Like test_llm.py, everything runs against a
FAKE batch-capable provider — no real network/Batch API call."""

from __future__ import annotations

import shutil

import pytest

from backend.config import REPO_ROOT, SESSIONS_ROOT
from backend.services import chain as chain_service
from backend.services.llm.batch_jobs import BatchNotFound, get_batch_ledger, poll_batch, submit_batch
from backend.services.llm.provider import LlmUnavailable
from backend.services.llm.schemas import ResidualSuggestion
from backend.services.session_store import SessionNotFound

DEMO_CHAIN_FILES = [REPO_ROOT / "data" / "demo" / f"Main_Engine_Cooling_v1.{i}.pdf" for i in range(5)]

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in DEMO_CHAIN_FILES), reason="run scripts/generate_demo_pdfs.py first"
)


class FakeBatchProvider:
    """Implements just the batch slice of LlmProvider — a stateful fake so
    tests can control the in_progress -> ended transition explicitly."""

    model_id = "fake-model"
    provider_name = "fake"

    def __init__(self, *, results_by_custom_id: dict | None = None, fail_fetch: bool = False):
        self.batches: dict[str, dict] = {}
        self._next_id = 0
        self._results_by_custom_id = results_by_custom_id or {}
        self.fail_fetch = fail_fetch
        self.submitted_items: list[tuple[str, str | None, str | None]] = []

    def classify_residual_batch(self, items):
        self._next_id += 1
        batch_id = f"batch-{self._next_id}"
        self.batches[batch_id] = {"status": "in_progress", "items": list(items)}
        self.submitted_items = list(items)
        return batch_id

    def end_batch(self, batch_id: str):
        self.batches[batch_id]["status"] = "ended"

    def get_batch_status(self, batch_id):
        return self.batches[batch_id]["status"]

    def fetch_batch_results(self, batch_id):
        if self.fail_fetch:
            raise LlmUnavailable("boom")
        default = ResidualSuggestion(
            semantic_change_type="scope_widening", suggest_escalate=True, suggested_risk="Medium", rationale="範圍擴大"
        )
        out = {}
        for custom_id, _old, _new in self.batches[batch_id]["items"]:
            out[custom_id] = self._results_by_custom_id.get(custom_id, default)
        return out


@pytest.fixture
def demo_chain():
    pdf_versions = [(p.read_bytes(), p.name) for p in DEMO_CHAIN_FILES]
    result = chain_service.build_chain(pdf_versions)
    ids = [result["chain_id"], *result["manifest"].adjacent_session_ids, *result["manifest"].anchor_session_ids]
    yield result["chain_id"]
    for entity_id in ids:
        shutil.rmtree(SESSIONS_ROOT / entity_id, ignore_errors=True)


def test_submit_batch_gathers_qualifying_differences_across_every_session(demo_chain):
    provider = FakeBatchProvider()
    result = submit_batch(demo_chain, provider)

    assert result["batch_id"] is not None
    assert result["difference_count"] == len(provider.submitted_items)
    assert result["difference_count"] > 0  # demo chain has real residuals to find

    ledger = get_batch_ledger(demo_chain)
    assert len(ledger) == 1
    assert ledger[0]["batch_id"] == result["batch_id"]
    assert ledger[0]["status"] == "in_progress"


def test_submit_batch_on_unknown_chain_raises():
    with pytest.raises(SessionNotFound):
        submit_batch("c-doesnotexist", FakeBatchProvider())


def test_poll_batch_returns_in_progress_before_ended(demo_chain):
    provider = FakeBatchProvider()
    result = submit_batch(demo_chain, provider)

    status = poll_batch(demo_chain, result["batch_id"], provider)
    assert status == {"status": "in_progress"}


def test_poll_batch_applies_results_and_writes_audit_events(demo_chain):
    provider = FakeBatchProvider()
    result = submit_batch(demo_chain, provider)
    provider.end_batch(result["batch_id"])

    status = poll_batch(demo_chain, result["batch_id"], provider)
    assert status["status"] == "completed"
    assert len(status["results"]) == result["difference_count"]
    assert all(v is not None for v in status["results"].values())

    ledger = get_batch_ledger(demo_chain)
    assert ledger[0]["status"] == "completed"
    assert ledger[0]["applied_count"] == result["difference_count"]

    # audit trail: pick one custom_id and confirm the session actually got an event.
    from backend.storage import events as event_store

    custom_id = next(iter(status["results"]))
    session_id, difference_id = custom_id.split(":", 1)
    events = event_store.read_events(session_id)
    matching = [e for e in events if e["difference_id"] == difference_id and e.get("provider") == "fake"]
    assert len(matching) == 1
    assert matching[0]["analysis_mode"] == "rules_first"


def test_poll_batch_a_second_time_returns_stored_results_without_reapplying(demo_chain):
    provider = FakeBatchProvider()
    result = submit_batch(demo_chain, provider)
    provider.end_batch(result["batch_id"])
    first = poll_batch(demo_chain, result["batch_id"], provider)

    custom_id = next(iter(first["results"]))
    session_id, difference_id = custom_id.split(":", 1)
    from backend.storage import events as event_store

    before_count = len(event_store.read_events(session_id))

    second = poll_batch(demo_chain, result["batch_id"], provider)
    assert second == first
    assert len(event_store.read_events(session_id)) == before_count  # no duplicate audit events


def test_poll_batch_leaves_errored_items_unapplied(demo_chain):
    provider = FakeBatchProvider()
    result = submit_batch(demo_chain, provider)
    failing_custom_id = provider.submitted_items[0][0]
    provider._results_by_custom_id[failing_custom_id] = None  # simulate an errored/malformed individual result
    provider.end_batch(result["batch_id"])

    status = poll_batch(demo_chain, result["batch_id"], provider)
    assert status["results"][failing_custom_id] is None
    ledger = get_batch_ledger(demo_chain)
    assert ledger[0]["applied_count"] == result["difference_count"] - 1


def test_poll_batch_fetch_failure_stays_in_progress(demo_chain):
    provider = FakeBatchProvider(fail_fetch=True)
    result = submit_batch(demo_chain, provider)
    provider.end_batch(result["batch_id"])

    status = poll_batch(demo_chain, result["batch_id"], provider)
    assert status == {"status": "in_progress"}
    ledger = get_batch_ledger(demo_chain)
    assert ledger[0]["status"] == "in_progress"


def test_poll_batch_unknown_id_raises(demo_chain):
    with pytest.raises(BatchNotFound):
        poll_batch(demo_chain, "batch-doesnotexist", FakeBatchProvider())


def test_submit_batch_with_no_qualifying_differences_does_not_call_provider(demo_chain, monkeypatch):
    monkeypatch.setattr("backend.services.llm.batch_jobs.needs_semantic_review_dict", lambda d, **kw: False)
    provider = FakeBatchProvider()
    result = submit_batch(demo_chain, provider)

    assert result["batch_id"] is None
    assert result["difference_count"] == 0
    assert provider.batches == {}
    assert get_batch_ledger(demo_chain) == []
