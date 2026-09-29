"""Stage -1 OCR layer tests. Like test_llm.py, everything here runs against a
FAKE OcrProvider — no test makes a real network/vision call."""

from __future__ import annotations

import fitz
import pytest

from backend.services.extraction import extract_document
from backend.services.ocr.pipeline import LOW_CONFIDENCE_THRESHOLD, ocr_scanned_pages
from backend.services.ocr.provider import OcrUnavailable, get_ocr_provider, resolve_ocr_provider
from backend.services.ocr.schemas import OcrPageResult


class FakeOcrProvider:
    provider_name = "fake-ocr"

    def __init__(self, *, fail: bool = False, result: OcrPageResult | None = None):
        self.fail = fail
        self._result = result or OcrPageResult(text="辨識出的文字內容", confidence=0.9, illegible=False)
        self.calls: list[bytes] = []

    def recognize(self, image_bytes: bytes, *, media_type: str = "image/png", lang_hint: str = "zh-Hant"):
        self.calls.append(image_bytes)
        if self.fail:
            raise OcrUnavailable("boom")
        return self._result


def _make_scanned_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20))
    pix.set_rect(pix.irect, (200, 200, 200))
    page.insert_image(fitz.Rect(50, 50, 300, 300), pixmap=pix)
    return doc.tobytes()


def _make_text_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), "一般文字頁面，字數超過門檻不會被當成掃描頁。" * 3)
    return doc.tobytes()


def _clear_all_provider_env(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_get_ocr_provider_is_none_without_api_key(monkeypatch):
    _clear_all_provider_env(monkeypatch)
    assert get_ocr_provider() is None


def test_get_ocr_provider_picks_gemini_when_only_gemini_key_set(monkeypatch):
    _clear_all_provider_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    provider = get_ocr_provider()
    assert provider is not None
    assert provider.provider_name == "gemini-vision"


def test_get_ocr_provider_picks_openai_when_only_openai_key_set(monkeypatch):
    _clear_all_provider_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    provider = get_ocr_provider()
    assert provider is not None
    assert provider.provider_name == "openai-vision"


def test_resolve_ocr_provider_with_explicit_credentials(monkeypatch):
    _clear_all_provider_env(monkeypatch)
    assert resolve_ocr_provider("anthropic", "sk-ant-not-real").provider_name == "anthropic-vision"
    assert resolve_ocr_provider("gemini", "not-a-real-key").provider_name == "gemini-vision"
    assert resolve_ocr_provider("openai", "not-a-real-key").provider_name == "openai-vision"


def test_resolve_ocr_provider_unknown_provider_degrades_to_none(monkeypatch):
    _clear_all_provider_env(monkeypatch)
    assert resolve_ocr_provider("groq", "some-key") is None


def test_resolve_ocr_provider_falls_back_to_env(monkeypatch):
    _clear_all_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-real")
    assert resolve_ocr_provider(None, None).provider_name == "anthropic-vision"


def test_ocr_scanned_pages_leaves_text_pages_untouched():
    pdf_bytes = _make_text_pdf()
    doc = extract_document(pdf_bytes)
    provider = FakeOcrProvider()

    result = ocr_scanned_pages(pdf_bytes, doc, provider)

    assert provider.calls == []  # never invoked for a page_kind == "text" page
    assert result.pages[0].raw_text == doc.pages[0].raw_text


def test_ocr_scanned_pages_fills_in_text_for_scanned_page():
    pdf_bytes = _make_scanned_pdf()
    doc = extract_document(pdf_bytes)
    assert doc.pages[0].page_kind == "scanned_text"
    provider = FakeOcrProvider(result=OcrPageResult(text="第一行\n第二行", confidence=0.95, illegible=False))

    result = ocr_scanned_pages(pdf_bytes, doc, provider)

    assert len(provider.calls) == 1
    page = result.pages[0]
    assert page.lines == ["第一行", "第二行"]
    assert page.lines_canonical == ["第一行", "第二行"]
    assert page.ocr_confidence == 0.95
    # page_kind/is_scanned deliberately unchanged — it really was a scan.
    assert page.page_kind == "scanned_text"
    assert page.is_scanned is True


def test_low_confidence_ocr_result_is_recorded_but_text_is_not_trusted():
    pdf_bytes = _make_scanned_pdf()
    doc = extract_document(pdf_bytes)
    provider = FakeOcrProvider(
        result=OcrPageResult(text="模糊的猜測文字", confidence=LOW_CONFIDENCE_THRESHOLD - 0.1, illegible=False)
    )

    result = ocr_scanned_pages(pdf_bytes, doc, provider)

    page = result.pages[0]
    assert page.raw_text == doc.pages[0].raw_text  # untouched — never trust a low-confidence guess
    assert page.ocr_confidence == pytest.approx(LOW_CONFIDENCE_THRESHOLD - 0.1)


def test_illegible_page_is_left_untouched():
    pdf_bytes = _make_scanned_pdf()
    doc = extract_document(pdf_bytes)
    provider = FakeOcrProvider(result=OcrPageResult(text="", confidence=0.9, illegible=True))

    result = ocr_scanned_pages(pdf_bytes, doc, provider)

    page = result.pages[0]
    assert page.raw_text == doc.pages[0].raw_text
    assert page.ocr_confidence == 0.9


def test_provider_failure_leaves_page_exactly_as_extracted():
    pdf_bytes = _make_scanned_pdf()
    doc = extract_document(pdf_bytes)
    provider = FakeOcrProvider(fail=True)

    result = ocr_scanned_pages(pdf_bytes, doc, provider)

    assert result.pages[0] == doc.pages[0]
