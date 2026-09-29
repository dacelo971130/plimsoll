"""Engineering-drawing comparison (§26 P5) for pages classified
`page_kind == "diagram"` by backend.services.extraction — piping/wiring/
instrumentation drawings that carry almost no diffable text, only vector
line-work. Text diff (backend.services.comparison) is meaningless here; this
module instead: rasterizes both versions of a page, finds the pixel regions
that actually changed (deterministic, no LLM), and — only when an LLM
provider is configured — asks Claude Vision to describe each changed region
(component label + summary), exactly the same "deterministic layer decides
WHERE, LLM only helps read WHAT" split as the rest of the pipeline.

Explicitly NOT built here (see the P5 plan's Follow-up list): a full §28 SFI
component taxonomy or a 2D system-schematic view — `component_label` is a
best-effort AI-read string, not a controlled vocabulary lookup, and
`DrawingDifferenceRecord` carries no taxonomy key.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field

import fitz  # PyMuPDF
import numpy as np
from PIL import Image
from scipy import ndimage

from backend.services.comparison import PageRef, SourceSpan
from backend.services.extraction import PageContent
from backend.services.llm.provider import LlmProvider, LlmUnavailable

RASTERIZE_DPI = 150
# Per-channel (0-255) intensity delta above which a pixel counts as "changed".
# Well above normal PNG re-encoding/anti-aliasing noise between two renders
# of what could be an unchanged drawing.
DIFF_INTENSITY_THRESHOLD = 30
# Ignore connected-component blobs smaller than this many pixels — single
# anti-aliased edge pixels and JPEG-ish rasterization noise, not real changes.
MIN_REGION_AREA_PX = 64
# Extra context around a region's tight bounding box, so a cropped valve
# symbol isn't cut off right at its outline.
REGION_PADDING_PX = 12


@dataclass
class DrawingRegion:
    bbox: tuple[int, int, int, int]  # pixel coords in the rasterized page image: (x0, y0, x1, y1)
    old_crop_png_b64: str | None
    new_crop_png_b64: str | None
    component_label: str | None = None
    change_summary: str | None = None
    confidence: float | None = None


@dataclass
class DrawingDifferenceRecord:
    """The `kind: "drawing"` counterpart to comparison.DifferenceRecord —
    deliberately a separate, smaller dataclass rather than bolting
    drawing-only fields onto DifferenceRecord, since almost none of that
    record's fields (rule_id, ruleset_version, ai_semantic_suggestion) apply
    to a pixel-diff finding."""

    id: str
    change_type: str  # '新增' | '刪除' | '修改' — matches DifferenceRecord's vocabulary
    ai_risk: str  # always a conservative default (never High/Low guessed from pixels alone) — see build_drawing_differences()
    ai_confidence: str  # '低' | '中' — reflects pixel-diff/vision uncertainty, not a rule-engine judgement
    explanation: str
    affected: str
    recommended_action: str
    old: SourceSpan | None
    new: SourceSpan | None
    regions: list[DrawingRegion] = field(default_factory=list)
    page_alignment: str = "matched"  # 'matched' | 'unmatched_old' | 'unmatched_new' | 'size_mismatch'
    data_origin: str = "computed"
    kind: str = "drawing"


def rasterize_page(pdf_bytes: bytes, page_index: int, *, dpi: int = RASTERIZE_DPI) -> Image.Image:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pix = doc[page_index].get_pixmap(dpi=dpi)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()


def _png_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def diff_regions(old_img: Image.Image, new_img: Image.Image) -> list[DrawingRegion] | None:
    """Returns None — not an empty list — when the two renders aren't the
    same pixel size (a rescaled/rotated/reformatted page can't be diffed
    pixel-for-pixel); the caller must surface that as "無法像素比對，請人工
    確認", never silently report "no changes". Returns [] when the images
    are the same size and genuinely identical (or only differ by
    sub-threshold rendering noise) — that page pair simply has no drawing
    difference to report."""
    if old_img.size != new_img.size:
        return None

    old_arr = np.asarray(old_img.convert("RGB"), dtype=np.int16)
    new_arr = np.asarray(new_img.convert("RGB"), dtype=np.int16)
    delta = np.abs(old_arr - new_arr).max(axis=2)
    mask = delta >= DIFF_INTENSITY_THRESHOLD

    labeled, count = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    if count == 0:
        return []

    width, height = old_img.size
    regions: list[DrawingRegion] = []
    for label_id, sl in enumerate(ndimage.find_objects(labeled), start=1):
        if sl is None:
            continue
        ys, xs = sl
        area = int(np.count_nonzero(labeled[sl] == label_id))
        if area < MIN_REGION_AREA_PX:
            continue
        x0 = max(0, xs.start - REGION_PADDING_PX)
        y0 = max(0, ys.start - REGION_PADDING_PX)
        x1 = min(width, xs.stop + REGION_PADDING_PX)
        y1 = min(height, ys.stop + REGION_PADDING_PX)
        regions.append(
            DrawingRegion(
                bbox=(x0, y0, x1, y1),
                old_crop_png_b64=_png_b64(old_img.crop((x0, y0, x1, y1))),
                new_crop_png_b64=_png_b64(new_img.crop((x0, y0, x1, y1))),
            )
        )
    return regions


def describe_regions(regions: list[DrawingRegion], provider: LlmProvider) -> list[DrawingRegion]:
    """Opt-in (only called when get_llm_provider() returned something).
    Returns a NEW list — never mutates in place, same discipline as
    backend.services.llm.residual's enrich_*() functions. A region whose
    vision call fails keeps component_label/change_summary as None rather
    than dropping the (deterministic, pixel-diff-confirmed) region entirely —
    losing the LLM's read is never a reason to lose the finding itself."""
    described: list[DrawingRegion] = []
    for region in regions:
        old_bytes = base64.b64decode(region.old_crop_png_b64) if region.old_crop_png_b64 else None
        new_bytes = base64.b64decode(region.new_crop_png_b64) if region.new_crop_png_b64 else None
        try:
            suggestion = provider.describe_drawing_region(old_bytes, new_bytes)
        except LlmUnavailable:
            described.append(region)
            continue
        described.append(
            DrawingRegion(
                bbox=region.bbox,
                old_crop_png_b64=region.old_crop_png_b64,
                new_crop_png_b64=region.new_crop_png_b64,
                component_label=suggestion.component_label,
                change_summary=suggestion.change_summary,
                confidence=suggestion.confidence,
            )
        )
    return described


def _page_ref(page: PageContent) -> PageRef:
    return PageRef(pdf_page=page.pdf_page, print_label=page.print_label, label_source=page.label_source)


def build_drawing_differences(
    old_bytes: bytes,
    new_bytes: bytes,
    old_pages: list[PageContent],
    new_pages: list[PageContent],
    *,
    start_id: int,
    provider: LlmProvider | None = None,
) -> list[DrawingDifferenceRecord]:
    """`old_pages`/`new_pages` are the `page_kind == "diagram"` pages of each
    document, in document order. Paired positionally (1st diagram page vs 1st
    diagram page, etc.) — engineering drawings overwhelmingly keep their
    position across versions; a genuinely reordered drawing page is out of
    scope for this pass (documented in the P5 plan's Follow-up list) and
    would show up here as a same-position "changed" region set instead, which
    is still a correct "something to look at" signal, just not perfectly
    attributed.

    IDs continue from `start_id` so they don't collide with the text-diff
    records in the same session; the caller is responsible for merging both
    lists before writing differences.json."""
    records: list[DrawingDifferenceRecord] = []
    counter = start_id
    paired = max(len(old_pages), len(new_pages))

    for i in range(paired):
        old_page = old_pages[i] if i < len(old_pages) else None
        new_page = new_pages[i] if i < len(new_pages) else None

        if old_page is not None and new_page is None:
            counter += 1
            records.append(
                DrawingDifferenceRecord(
                    id=f"D{counter:02d}",
                    change_type="刪除",
                    ai_risk="Medium",
                    ai_confidence="低",
                    explanation="舊版本存在此工程圖頁，新版本已移除，需人工確認是否為刻意刪除。",
                    affected=old_page.heading or f"第 {old_page.pdf_page} 頁工程圖",
                    recommended_action="請人工確認此工程圖頁移除是否為預期變更。",
                    old=SourceSpan(page=_page_ref(old_page), text=f"第 {old_page.pdf_page} 頁工程圖"),
                    new=None,
                    regions=[],
                    page_alignment="unmatched_old",
                )
            )
            continue

        if new_page is not None and old_page is None:
            counter += 1
            records.append(
                DrawingDifferenceRecord(
                    id=f"D{counter:02d}",
                    change_type="新增",
                    ai_risk="Medium",
                    ai_confidence="低",
                    explanation="新版本新增此工程圖頁，舊版本沒有對應頁面。",
                    affected=new_page.heading or f"第 {new_page.pdf_page} 頁工程圖",
                    recommended_action="請人工確認此工程圖頁新增內容。",
                    old=None,
                    new=SourceSpan(page=_page_ref(new_page), text=f"第 {new_page.pdf_page} 頁工程圖"),
                    regions=[],
                    page_alignment="unmatched_new",
                )
            )
            continue

        assert old_page is not None and new_page is not None
        old_img = rasterize_page(old_bytes, old_page.pdf_page - 1)
        new_img = rasterize_page(new_bytes, new_page.pdf_page - 1)
        regions = diff_regions(old_img, new_img)

        if regions is None:
            counter += 1
            records.append(
                DrawingDifferenceRecord(
                    id=f"D{counter:02d}",
                    change_type="修改",
                    ai_risk="Medium",
                    ai_confidence="低",
                    explanation="新舊版本工程圖頁尺寸不同，無法逐像素比對。",
                    affected=new_page.heading or f"第 {new_page.pdf_page} 頁工程圖",
                    recommended_action="請人工並排比對此工程圖頁。",
                    old=SourceSpan(page=_page_ref(old_page), text=f"第 {old_page.pdf_page} 頁工程圖"),
                    new=SourceSpan(page=_page_ref(new_page), text=f"第 {new_page.pdf_page} 頁工程圖"),
                    regions=[],
                    page_alignment="size_mismatch",
                )
            )
            continue

        if not regions:
            continue  # genuinely unchanged drawing page — no difference to report

        if provider is not None:
            regions = describe_regions(regions, provider)

        counter += 1
        records.append(
            DrawingDifferenceRecord(
                id=f"D{counter:02d}",
                change_type="修改",
                ai_risk="Medium",
                ai_confidence="中",
                explanation=f"像素比對偵測到 {len(regions)} 處工程圖變更區塊。",
                affected=new_page.heading or f"第 {new_page.pdf_page} 頁工程圖",
                recommended_action="請人工比對標示區塊確認變更內容。",
                old=SourceSpan(page=_page_ref(old_page), text=f"第 {old_page.pdf_page} 頁工程圖"),
                new=SourceSpan(page=_page_ref(new_page), text=f"第 {new_page.pdf_page} 頁工程圖"),
                regions=regions,
                page_alignment="matched",
            )
        )

    return records
