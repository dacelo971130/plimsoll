"""P5 engineering-drawing pixel diff tests. Uses the same FakeProvider as
test_llm.py for the opt-in vision-description step — no real vision call."""

from __future__ import annotations

import fitz
from PIL import Image

from backend.services.drawing_diff import (
    DrawingRegion,
    build_drawing_differences,
    describe_regions,
    diff_regions,
    rasterize_page,
)
from backend.services.extraction import extract_document
from backend.tests.test_llm import FakeProvider


def _blank_image(size=(200, 200), color=(255, 255, 255)) -> Image.Image:
    return Image.new("RGB", size, color)


def test_diff_regions_finds_a_real_changed_block_and_ignores_nothing_changed():
    old_img = _blank_image()
    new_img = old_img.copy()
    # Paint a solid block far above the noise threshold and well above the
    # minimum region area.
    for x in range(50, 80):
        for y in range(50, 80):
            new_img.putpixel((x, y), (0, 0, 0))

    regions = diff_regions(old_img, new_img)

    assert regions is not None
    assert len(regions) == 1
    x0, y0, x1, y1 = regions[0].bbox
    assert x0 <= 50 and y0 <= 50 and x1 >= 80 and y1 >= 80
    assert regions[0].old_crop_png_b64 and regions[0].new_crop_png_b64


def test_diff_regions_ignores_tiny_noise_blobs():
    old_img = _blank_image()
    new_img = old_img.copy()
    new_img.putpixel((10, 10), (0, 0, 0))  # single pixel — below MIN_REGION_AREA_PX

    regions = diff_regions(old_img, new_img)

    assert regions == []


def test_diff_regions_returns_none_for_size_mismatch():
    old_img = _blank_image((200, 200))
    new_img = _blank_image((300, 300))

    assert diff_regions(old_img, new_img) is None


def test_identical_images_produce_no_regions():
    img = _blank_image()
    assert diff_regions(img, img.copy()) == []


def test_describe_regions_attaches_suggestion_without_mutating_input():
    region = DrawingRegion(bbox=(0, 0, 10, 10), old_crop_png_b64="AA==", new_crop_png_b64="AQ==")
    provider = FakeProvider()

    described = describe_regions([region], provider)

    assert region.component_label is None  # input untouched
    assert described[0].component_label == "CP-120"
    assert described[0].confidence == 0.7
    assert provider.calls[0][0] == "describe_drawing_region"


def test_describe_regions_keeps_region_when_vision_call_fails():
    region = DrawingRegion(bbox=(0, 0, 10, 10), old_crop_png_b64="AA==", new_crop_png_b64="AQ==")
    provider = FakeProvider(fail=True)

    described = describe_regions([region], provider)

    assert len(described) == 1
    assert described[0].component_label is None


def _make_diagram_pdf_with_lines(n_extra_lines: int = 0) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    shape = page.new_shape()
    for i in range(60):
        shape.draw_line((10, 10 + i * 5), (400, 10 + i * 5))
    for i in range(n_extra_lines):
        shape.draw_line((450, 10 + i * 5), (500, 10 + i * 5))
    shape.finish(color=(0, 0, 0), width=0.5)
    shape.commit()
    return doc.tobytes()


def test_build_drawing_differences_detects_changed_matched_pages():
    old_bytes = _make_diagram_pdf_with_lines(n_extra_lines=0)
    new_bytes = _make_diagram_pdf_with_lines(n_extra_lines=20)
    old_doc = extract_document(old_bytes)
    new_doc = extract_document(new_bytes)
    assert old_doc.pages[0].page_kind == "diagram"
    assert new_doc.pages[0].page_kind == "diagram"

    records = build_drawing_differences(
        old_bytes, new_bytes, old_doc.pages, new_doc.pages, start_id=0, provider=None
    )

    assert len(records) == 1
    record = records[0]
    assert record.kind == "drawing"
    assert record.change_type == "修改"
    assert record.page_alignment == "matched"
    assert len(record.regions) >= 1
    assert record.id == "D01"


def test_build_drawing_differences_reports_nothing_for_identical_pages():
    pdf_bytes = _make_diagram_pdf_with_lines()
    doc = extract_document(pdf_bytes)

    records = build_drawing_differences(pdf_bytes, pdf_bytes, doc.pages, doc.pages, start_id=0, provider=None)

    assert records == []


def test_build_drawing_differences_flags_unmatched_pages_as_added_or_removed():
    old_bytes = _make_diagram_pdf_with_lines()
    old_doc = extract_document(old_bytes)

    records = build_drawing_differences(old_bytes, old_bytes, old_doc.pages, [], start_id=0, provider=None)

    assert len(records) == 1
    assert records[0].change_type == "刪除"
    assert records[0].page_alignment == "unmatched_old"


def test_rasterize_page_returns_an_image_matching_page_size_ratio():
    pdf_bytes = _make_diagram_pdf_with_lines()
    img = rasterize_page(pdf_bytes, 0, dpi=72)
    assert img.size[0] > 0 and img.size[1] > 0
