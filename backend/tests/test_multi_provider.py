"""P5 multi-provider support — Gemini/OpenAI `LlmProvider` implementations.
Construction never touches the network (same guarantee as AnthropicProvider);
the request-building/response-parsing logic for batch methods is verified by
monkeypatching the underlying SDK client's methods directly (no real network
call, no real API key), the same spirit as test_llm.py's FakeProvider but
exercising the REAL provider classes' internals instead of a hand-rolled
fake — this is what "no half-measures" for multi-provider support means:
the Gemini/OpenAI adapters must actually build correct requests and parse
correct responses, not just construct without crashing."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.services.llm.gemini_provider import GeminiOcrProvider, GeminiProvider
from backend.services.llm.openai_provider import OpenAIOcrProvider, OpenAIProvider
from backend.services.llm.provider import LlmUnavailable
from backend.services.llm.schemas import ResidualSuggestion

# --------------------------------------------------------------------------
# construction — every provider implements the full LlmProvider surface
# --------------------------------------------------------------------------

REQUIRED_METHODS = [
    "classify_residual",
    "analyze_trail",
    "describe_drawing_region",
    "suggest_term_alias",
    "classify_residual_batch",
    "get_batch_status",
    "fetch_batch_results",
]


@pytest.mark.parametrize("cls", [GeminiProvider, OpenAIProvider])
def test_provider_implements_full_llm_provider_surface(cls):
    provider = cls(api_key="not-a-real-key")
    assert isinstance(provider.model_id, str) and provider.model_id
    assert isinstance(provider.provider_name, str) and provider.provider_name
    for method in REQUIRED_METHODS:
        assert callable(getattr(provider, method)), f"{cls.__name__} is missing {method}"


def test_gemini_and_openai_have_distinct_provider_names():
    assert GeminiProvider(api_key="x").provider_name == "gemini"
    assert OpenAIProvider(api_key="x").provider_name == "openai"


def test_ocr_providers_construct_without_network():
    assert GeminiOcrProvider(api_key="x").provider_name == "gemini-vision"
    assert OpenAIOcrProvider(api_key="x").provider_name == "openai-vision"


# --------------------------------------------------------------------------
# OpenAI batch — real request-building / response-parsing logic
# --------------------------------------------------------------------------


def test_openai_classify_residual_batch_uploads_a_correct_jsonl_and_creates_the_batch():
    provider = OpenAIProvider(api_key="x")
    uploaded_files: list[bytes] = []

    def fake_files_create(*, file, purpose):
        assert purpose == "batch"
        _, fileobj = file
        uploaded_files.append(fileobj.read())
        return SimpleNamespace(id="file-123")

    created_batches = []

    def fake_batches_create(*, input_file_id, endpoint, completion_window):
        created_batches.append((input_file_id, endpoint, completion_window))
        return SimpleNamespace(id="batch-abc")

    provider._client.files.create = fake_files_create
    provider._client.batches.create = fake_batches_create

    batch_id = provider.classify_residual_batch([("s1:D01", "舊文字", "新文字"), ("s1:D02", "A", "B")])

    assert batch_id == "batch-abc"
    assert created_batches == [("file-123", "/v1/chat/completions", "24h")]
    lines = uploaded_files[0].decode("utf-8").strip().splitlines()
    assert len(lines) == 2
    row0 = json.loads(lines[0])
    assert row0["custom_id"] == "s1:D01"
    assert row0["method"] == "POST"
    assert row0["url"] == "/v1/chat/completions"
    assert row0["body"]["model"] == provider.model_id
    assert row0["body"]["response_format"]["json_schema"]["name"] == "ResidualSuggestion"
    user_message = json.loads(row0["body"]["messages"][1]["content"])
    assert user_message == {"old_text": "舊文字", "new_text": "新文字"}


def test_openai_get_batch_status_maps_openai_statuses_to_ended_or_in_progress():
    provider = OpenAIProvider(api_key="x")
    for status in ("completed", "failed", "expired", "cancelled"):
        provider._client.batches.retrieve = lambda batch_id, _s=status: SimpleNamespace(status=_s)
        assert provider.get_batch_status("batch-abc") == "ended"
    for status in ("validating", "in_progress", "finalizing", "cancelling"):
        provider._client.batches.retrieve = lambda batch_id, _s=status: SimpleNamespace(status=_s)
        assert provider.get_batch_status("batch-abc") == "in_progress"


def test_openai_fetch_batch_results_parses_succeeded_and_errored_lines():
    provider = OpenAIProvider(api_key="x")
    suggestion = ResidualSuggestion(
        semantic_change_type="clarification", suggest_escalate=False, rationale="用詞更精確"
    )
    ok_line = json.dumps(
        {
            "custom_id": "s1:D01",
            "response": {"status_code": 200, "body": {"choices": [{"message": {"content": suggestion.model_dump_json()}}]}},
            "error": None,
        }
    )
    error_line = json.dumps({"custom_id": "s1:D02", "response": None, "error": {"message": "boom"}})

    provider._client.batches.retrieve = lambda batch_id: SimpleNamespace(output_file_id="file-out")
    provider._client.files.content = lambda file_id: SimpleNamespace(text=f"{ok_line}\n{error_line}\n")

    results = provider.fetch_batch_results("batch-abc")

    assert results["s1:D01"] == suggestion
    assert results["s1:D02"] is None


def test_openai_fetch_batch_results_returns_empty_when_batch_has_no_output_file():
    provider = OpenAIProvider(api_key="x")
    provider._client.batches.retrieve = lambda batch_id: SimpleNamespace(output_file_id=None)
    assert provider.fetch_batch_results("batch-abc") == {}


# --------------------------------------------------------------------------
# Gemini batch — metadata-based custom_id correlation (no native custom_id field)
# --------------------------------------------------------------------------


def test_gemini_classify_residual_batch_stamps_custom_id_into_metadata():
    provider = GeminiProvider(api_key="x")
    captured = {}

    def fake_batches_create(*, model, src):
        captured["model"] = model
        captured["src"] = src
        return SimpleNamespace(name="batches/xyz")

    provider._client.batches.create = fake_batches_create

    batch_id = provider.classify_residual_batch([("s1:D01", "舊文字", "新文字")])

    assert batch_id == "batches/xyz"
    assert captured["model"] == provider.model_id
    assert len(captured["src"]) == 1
    assert captured["src"][0].metadata == {"custom_id": "s1:D01"}


def test_gemini_get_batch_status_maps_job_states():
    provider = GeminiProvider(api_key="x")
    from google.genai import types as genai_types

    for state in (
        genai_types.JobState.JOB_STATE_SUCCEEDED,
        genai_types.JobState.JOB_STATE_FAILED,
        genai_types.JobState.JOB_STATE_CANCELLED,
    ):
        provider._client.batches.get = lambda name, _s=state: SimpleNamespace(state=_s)
        assert provider.get_batch_status("batches/xyz") == "ended"

    for state in (genai_types.JobState.JOB_STATE_RUNNING, genai_types.JobState.JOB_STATE_QUEUED):
        provider._client.batches.get = lambda name, _s=state: SimpleNamespace(state=_s)
        assert provider.get_batch_status("batches/xyz") == "in_progress"


def test_gemini_fetch_batch_results_reads_inlined_responses_by_metadata_custom_id():
    provider = GeminiProvider(api_key="x")
    suggestion = ResidualSuggestion(semantic_change_type="unclear", suggest_escalate=False, rationale="不確定")

    ok_response = SimpleNamespace(metadata={"custom_id": "s1:D01"}, error=None, response=SimpleNamespace(text=suggestion.model_dump_json()))
    errored_response = SimpleNamespace(metadata={"custom_id": "s1:D02"}, error="boom", response=None)

    provider._client.batches.get = lambda name: SimpleNamespace(
        dest=SimpleNamespace(inlined_responses=[ok_response, errored_response])
    )

    results = provider.fetch_batch_results("batches/xyz")

    assert results["s1:D01"] == suggestion
    assert results["s1:D02"] is None


def test_gemini_fetch_batch_results_handles_missing_dest():
    provider = GeminiProvider(api_key="x")
    provider._client.batches.get = lambda name: SimpleNamespace(dest=None)
    assert provider.fetch_batch_results("batches/xyz") == {}


# --------------------------------------------------------------------------
# SDK error -> LlmUnavailable translation (never let a raw SDK exception escape)
# --------------------------------------------------------------------------


def test_openai_batch_submit_failure_raises_llm_unavailable():
    import openai

    provider = OpenAIProvider(api_key="x")

    def raise_error(*args, **kwargs):
        raise openai.APIError("boom", request=SimpleNamespace(), body=None)

    provider._client.files.create = raise_error
    with pytest.raises(LlmUnavailable):
        provider.classify_residual_batch([("s1:D01", "A", "B")])


def test_gemini_batch_submit_failure_raises_llm_unavailable():
    from google.genai import errors as genai_errors

    provider = GeminiProvider(api_key="x")

    def raise_error(*args, **kwargs):
        raise genai_errors.APIError(500, {"error": {"message": "boom"}})

    provider._client.batches.create = raise_error
    with pytest.raises(LlmUnavailable):
        provider.classify_residual_batch([("s1:D01", "A", "B")])
