"""P1 extraction tests — real demo PDFs (metadata regex, dual page numbers)
plus synthetic fixtures for the scanned-page exception path."""

from __future__ import annotations

import fitz
import pytest

from backend.config import REPO_ROOT
from backend.services.extraction import (
    diagram_page_numbers,
    extract_document,
    extract_metadata,
    scanned_page_numbers,
)

DEMO_OLD = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.0.pdf"
DEMO_NEW = REPO_ROOT / "data" / "demo" / "Main_Engine_Cooling_v1.1.pdf"

pytestmark = pytest.mark.skipif(
    not (DEMO_OLD.exists() and DEMO_NEW.exists()), reason="run scripts/generate_demo_pdfs.py first"
)


def _make_scanned_pdf() -> bytes:
    """A page with an image and NO text layer — the scanned/exception path."""
    doc = fitz.open()
    page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20))
    pix.set_rect(pix.irect, (200, 200, 200))
    page.insert_image(fitz.Rect(50, 50, 300, 300), pixmap=pix)
    return doc.tobytes()


def _make_plain_text_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), text)
    return doc.tobytes()


def _make_multiline_pdf(lines: list[str]) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), "\n".join(lines))
    return doc.tobytes()


def _make_diagram_pdf() -> bytes:
    """A page with many vector line segments and NO text layer — the
    engineering-drawing exception path (piping/wiring diagrams are drawn as
    vector lines + fills, not raster images)."""
    doc = fitz.open()
    page = doc.new_page()
    shape = page.new_shape()
    for i in range(60):
        shape.draw_line((10, 10 + i * 5), (400, 10 + i * 5))
    shape.finish(color=(0, 0, 0), width=0.5)
    shape.commit()
    return doc.tobytes()


def test_demo_pdf_has_six_pages_and_extractable_cjk_text():
    extracted = extract_document(DEMO_OLD.read_bytes())
    assert extracted.page_count == 6
    page3 = extracted.pages[2]
    assert "85°C" in page3.raw_text
    assert page3.pdf_page == 3


def test_demo_new_pdf_has_seven_pages_with_the_new_closing_section():
    # W2: v1.1 adds "7. 版本異動摘要" as a whole new page not present in v1.0.
    extracted = extract_document(DEMO_NEW.read_bytes())
    assert extracted.page_count == 7
    assert extracted.pages[6].heading == "7. 版本異動摘要"


def test_running_header_and_footer_are_stripped_from_diffable_lines():
    extracted = extract_document(DEMO_OLD.read_bytes())
    for page in extracted.pages:
        assert not any(line.startswith("PDF p.") for line in page.lines)
        assert "AI Ship Document Comparison Demo" not in page.lines


def test_dual_page_number_reads_real_pdf_page_labels():
    # W2: generate_demo_pdfs.py now sets real /PageLabels (Arabic, from 1),
    # so this is a genuine page_labels source, not a guess (architecture-
    # decisions-A-B.md §22: never guess a print label — but reading a label
    # the PDF actually declares is exactly what this path is for).
    extracted = extract_document(DEMO_OLD.read_bytes())
    for page in extracted.pages:
        assert page.label_source == "page_labels"
        assert page.print_label == str(page.pdf_page)


def test_metadata_extraction_finds_version_date_title_and_equipment():
    extracted = extract_document(DEMO_OLD.read_bytes())
    meta = extract_metadata(extracted)
    assert meta.version == "v1.0"
    assert meta.date == "2026-08-15"
    assert meta.title == "Main Engine Cooling System Maintenance Procedure"
    assert meta.applicable_equipment is not None
    assert meta.is_complete
    assert meta.missing_fields == []


def test_metadata_reports_missing_fields_honestly_when_absent():
    extracted = extract_document(_make_plain_text_pdf("Just some unrelated page content."))
    meta = extract_metadata(extracted)
    assert meta.version is None
    assert meta.date is None
    assert not meta.is_complete
    assert "version" in meta.missing_fields
    assert "date" in meta.missing_fields


def test_section_heading_detected_but_not_confused_with_subclause_numbering():
    extracted = extract_document(DEMO_OLD.read_bytes())
    assert extracted.pages[2].heading == "3. 冷卻溫度檢查"
    # "2.1 冷卻液出口溫度..." is a numbered sub-clause, not a heading — must
    # not be picked up as one.
    assert extracted.pages[2].heading != "2.1 冷卻液出口溫度建議維持在 85°C 以下。"


def test_page_n_of_m_pagination_line_is_stripped():
    # docs/redesign/plimsoll-real-document-smoketest-2026-09.html §1/Fix D —
    # real-world EASA-style "Page N of M" running pagination, absent from
    # the demo PDFs' own header/footer format, used to survive as noise.
    extracted = extract_document(_make_multiline_pdf(["Page 1 of 118", "Real content line."]))
    assert "Page 1 of 118" not in extracted.pages[0].lines
    assert "Real content line." in extracted.pages[0].lines


def test_bare_page_number_stripped_only_at_page_edges():
    # A lone integer is a page number at the top/bottom of a page, but the
    # exact same text mid-page is real content (a table cell) and must
    # survive — otherwise a real "85 -> 80" table-value change would be
    # silently swallowed as if it were pagination noise.
    extracted = extract_document(_make_multiline_pdf(["115", "表格內容第一行", "85", "116"]))
    lines = extracted.pages[0].lines
    assert "115" not in lines
    assert "116" not in lines
    assert "85" in lines


def test_no_scanned_pages_in_demo_pdf():
    extracted = extract_document(DEMO_OLD.read_bytes())
    assert scanned_page_numbers(extracted) == []


def _make_blank_pdf() -> bytes:
    """A page with no text, no image, and no vector drawing at all — a
    deliberately blank page (e.g. a chapter divider), distinct from an
    unreadable scanned photo."""
    doc = fitz.open()
    doc.new_page()
    return doc.tobytes()


def _make_blank_pdf_with_background_fill() -> bytes:
    """A page with no text and no image, but ONE full-page white fill
    rectangle — a background-fill artifact some PDF generators emit even
    for a genuinely empty page (confirmed on 45 real pages of the CCS Rules
    for Steel Ships target document, all with exactly this shape)."""
    doc = fitz.open()
    page = doc.new_page()
    shape = page.new_shape()
    shape.draw_rect(page.rect)
    shape.finish(color=None, fill=(1, 1, 1))
    shape.commit()
    return doc.tobytes()


def test_blank_page_with_background_fill_rect_is_not_flagged_scanned():
    # docs/redesign/plimsoll-real-document-smoketest-2026-09.html §3 — a
    # single full-page fill rectangle is a background artifact, not content;
    # it must not defeat the blank-page detection just because
    # drawing_item_count is 1 instead of 0.
    extracted = extract_document(_make_blank_pdf_with_background_fill())
    assert extracted.pages[0].page_kind == "text"
    assert extracted.pages[0].is_scanned is False


def test_genuinely_blank_page_is_not_flagged_scanned():
    # docs/redesign/plimsoll-real-document-smoketest-2026-09.html §3 — a
    # blank page used to fall into the same "scanned_text" bucket as an
    # actual unreadable scan (124 of CCS's 152 low-text pages were this).
    extracted = extract_document(_make_blank_pdf())
    assert extracted.pages[0].page_kind == "text"
    assert extracted.pages[0].is_scanned is False
    assert scanned_page_numbers(extracted) == []


def _make_small_box_pdf() -> bytes:
    """A page with no text and no image, but a small drawn box far from
    covering the page — real (if sparse) graphical content, not a
    background-fill artifact."""
    doc = fitz.open()
    page = doc.new_page()
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(50, 50, 150, 100))
    shape.finish(color=(0, 0, 0))
    shape.commit()
    return doc.tobytes()


def test_small_box_drawing_still_flagged_scanned_not_blank():
    # The background-fill exemption must stay narrow — a small real box
    # (not a full-page fill) is still an ambiguous low-text page and must
    # keep the existing conservative "scanned_text" fallback.
    extracted = extract_document(_make_small_box_pdf())
    assert extracted.pages[0].page_kind == "scanned_text"
    assert extracted.pages[0].is_scanned is True


def test_image_only_page_is_flagged_scanned():
    extracted = extract_document(_make_scanned_pdf())
    assert scanned_page_numbers(extracted) == [1]
    assert extracted.pages[0].is_scanned is True
    assert extracted.pages[0].page_kind == "scanned_text"
    assert diagram_page_numbers(extracted) == []


def test_vector_heavy_page_with_no_text_is_classified_as_diagram():
    extracted = extract_document(_make_diagram_pdf())
    assert extracted.pages[0].page_kind == "diagram"
    assert extracted.pages[0].is_scanned is True  # back-compat: is_scanned still true for non-text pages
    assert diagram_page_numbers(extracted) == [1]


def test_normal_text_page_is_never_reclassified_as_diagram_or_scanned():
    extracted = extract_document(DEMO_OLD.read_bytes())
    assert all(p.page_kind == "text" for p in extracted.pages)


def test_text_page_spans_carry_bounding_boxes_for_the_pdf_overlay():
    extracted = extract_document(DEMO_OLD.read_bytes())
    page3 = extracted.pages[2]
    assert page3.spans, "a real text page should have word-level spans"
    for span in page3.spans[:5]:
        x0, y0, x1, y1 = span.bbox
        assert x1 > x0 and y1 > y0
        assert span.text
