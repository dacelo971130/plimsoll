"""Runs `OcrProvider.recognize()` over a document's `scanned_text` pages and
returns a new `ExtractedDocument` with usable `lines`/`raw_text` for those
pages — the missing half of Stage -1 (extraction.py only ever detected and
flagged them before this existed).

Deliberately NOT wired into `session_store.process_upload()` unconditionally
— it's called there only when `get_ocr_provider()` returns a provider (see
that module), so a deployment with no `ANTHROPIC_API_KEY` behaves exactly as
before: scanned pages are flagged, never recognized.
"""

from __future__ import annotations

import unicodedata
from dataclasses import replace

import fitz  # PyMuPDF

from backend.services.extraction import ExtractedDocument, PageContent
from backend.services.ocr.provider import OcrProvider, OcrUnavailable

RASTERIZE_DPI = 200
# Below this confidence, the OCR attempt is recorded (so the UI can show it)
# but the page's text is left untouched — never treat a low-confidence guess
# as ground truth for comparison (§26: "低信心→標「無法可信比對」導人工").
LOW_CONFIDENCE_THRESHOLD = 0.6


def _rasterize_page_png(pdf_bytes: bytes, page_index: int, *, dpi: int = RASTERIZE_DPI) -> bytes:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pix = doc[page_index].get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()


def _lines_from_ocr_text(raw_text: str) -> list[str]:
    lines = [unicodedata.normalize("NFKC", l).strip() for l in raw_text.split("\n")]
    return [l for l in lines if l]


def ocr_scanned_pages(pdf_bytes: bytes, doc: ExtractedDocument, provider: OcrProvider) -> ExtractedDocument:
    """Returns a NEW ExtractedDocument — never mutates `doc` in place, same
    discipline as backend.services.llm.residual's enrich_*() functions. Only
    `page_kind == "scanned_text"` pages are touched; `diagram` pages go
    through backend.services.drawing_diff instead, and `text` pages pass
    through unchanged.

    `page_kind`/`is_scanned` are intentionally left as-is even after a
    successful, high-confidence OCR — the page really was a scan, and the
    UI should keep saying so, just now paired with recovered text and a
    confidence score instead of an empty warning."""
    new_pages: list[PageContent] = []
    for page in doc.pages:
        if page.page_kind != "scanned_text":
            new_pages.append(page)
            continue

        try:
            image_bytes = _rasterize_page_png(pdf_bytes, page.pdf_page - 1)
            result = provider.recognize(image_bytes)
        except OcrUnavailable:
            new_pages.append(page)  # leave untouched — still just "flagged", as before
            continue

        if result.illegible or result.confidence < LOW_CONFIDENCE_THRESHOLD:
            new_pages.append(replace(page, ocr_confidence=result.confidence))
            continue

        lines = _lines_from_ocr_text(result.text)
        new_pages.append(
            replace(
                page,
                raw_text=result.text,
                lines=lines,
                lines_canonical=list(lines),  # normalize.apply_term_aliases() runs AFTER this, same as extraction
                char_count=sum(len(l) for l in lines),
                ocr_confidence=result.confidence,
            )
        )
    return ExtractedDocument(pages=new_pages, page_count=doc.page_count, size_bytes=doc.size_bytes)
