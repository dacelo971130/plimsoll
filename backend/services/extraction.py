"""PDF text extraction — PyMuPDF (fitz), per architecture-decisions-A-B.md
§27(b): C-backed, faster than pypdf, and the same library we'll rasterize
with in P8.

Stage 0 normalization (§26): NFKC, drop blank lines, and strip running
headers/footers/page-number lines so they never masquerade as content
changes during comparison.

Dual page numbers (§22): `print_label` comes only from the PDF's own
PageLabels; if the document doesn't define any, we report `NULL` with
`label_source="unknown"` — never a guess.

Stage -1 page classification (§26, P5): a page with too little text to diff
is no longer just "scanned" — it's either a scanned TEXT page (OCR can help,
see backend.services.ocr) or an engineering DRAWING page (pixel diff +
entity extraction, see backend.services.drawing_diff). The split is a pure
PyMuPDF heuristic, no new dependency: a page dominated by one or few large
raster images looks like a scanned document photo; a page with many vector
line/fill objects and few/no raster images looks like a technical drawing
(pipe runs, panel outlines, callout lines). Either way this is only ever a
routing hint — never a confident classification — so a page that matches
neither signal strongly still falls back to `scanned_text` (the older,
safer "flag it, maybe OCR helps" behavior) rather than being silently
treated as ordinary text.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

import fitz  # PyMuPDF

# Below this many non-whitespace characters, a page is treated as having no
# usable text layer (scanned image / OCR needed) rather than genuinely blank.
MIN_TEXT_CHARS_FOR_NON_SCANNED = 20

PageKind = Literal["text", "scanned_text", "diagram"]

# A page with fewer than this many vector drawing primitives (lines/fills/
# curves from page.get_drawings()) is not "graphics-dense" enough to call a
# diagram — most low-text pages are just scans, not engineering drawings.
_MIN_DRAWING_ITEMS_FOR_DIAGRAM = 40
# A page needs at least this fractional image coverage of its own area to
# count as "a scanned photo of a page" rather than, say, a small logo.
_MIN_IMAGE_COVERAGE_FOR_SCANNED_TEXT = 0.5

_PAGE_NUMBER_LINE_PATTERNS = [
    re.compile(r"^(PDF\s*)?p\.?\s*\d+$", re.IGNORECASE),
    re.compile(r"^第\s*\d+\s*頁$"),
    re.compile(r"^-\s*\d+\s*-$"),
    re.compile(r"^Page\s+\d+\s+of\s+\d+$", re.IGNORECASE),  # e.g. real-world EASA TCDS pagination
]

# A lone integer ("115") is only a page number when it's the first or last
# line PyMuPDF extracted for that page — see _is_bare_page_number_at_edge.
_BARE_PAGE_NUMBER_RE = re.compile(r"^\d{1,4}$")

# Running header/footer detection: a line repeated across most pages of the
# SAME document is boilerplate, not content — regardless of what it says.
_BOILERPLATE_FREQUENCY_RATIO = 0.6

# A numbered section heading ("3. 冷卻溫度檢查") is the closest thing to a
# "受影響設備/流程" label we can extract deterministically without a full
# component/taxonomy pass (§28, Someday). Used to fill DifferenceRecord.affected.
# `\d+\.\s+` (digit, dot, then whitespace) deliberately excludes decimal
# sub-clause numbering like "2.1 冷卻液..." — there, the digit right after
# the dot means \s+ can't match, so it never qualifies as a heading.
_SECTION_HEADING_RE = re.compile(r"^\d+\.\s+\S.{0,20}$")


def _looks_like_heading(line: str) -> bool:
    return bool(_SECTION_HEADING_RE.match(line)) and not line.endswith(("。", "，"))


@dataclass
class TextSpan:
    """One PyMuPDF text span's bounding box, in PDF point coordinates
    (origin top-left, same convention `page.get_text("dict")` uses). Used
    only to let the frontend draw a difference's highlight box on top of the
    *rendered* PDF image (P5 §3c) — never used for anything in the diff
    logic itself, which stays purely text-based."""

    text: str
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    line_index: int  # index into the page's *raw* (pre-boilerplate-strip) line list


@dataclass
class PageContent:
    pdf_page: int  # 1-indexed
    print_label: str | None
    label_source: str  # 'page_labels' | 'unknown'
    raw_text: str
    lines: list[str]  # NFKC-normalized, boilerplate-stripped, blank-free
    # Term-canonicalized view of `lines`, fed to comparison.classify() instead
    # of the original wording (W4: docs/redesign/plimsoll-improvement-plan.html
    # §02) — identical to `lines` until backend.services.normalize.apply_term_
    # aliases() runs; never shown to the reviewer, who always sees `lines`.
    lines_canonical: list[str]
    char_count: int
    is_scanned: bool
    heading: str | None  # first numbered-section-style line on the page, if any
    # Stage -1 (§26, P5): 'text' | 'scanned_text' | 'diagram'. Kept alongside
    # `is_scanned` (= page_kind != "text") rather than replacing it, so every
    # pre-existing caller of scanned_page_numbers()/is_scanned is unaffected.
    page_kind: PageKind = "text"
    spans: list[TextSpan] = field(default_factory=list)
    # Set only by backend.services.ocr.pipeline.ocr_scanned_pages() — None
    # means "not OCR'd" (either a `text` page, or no OCR provider configured),
    # never "OCR'd with zero confidence".
    ocr_confidence: float | None = None


@dataclass
class ExtractedDocument:
    pages: list[PageContent] = field(default_factory=list)
    page_count: int = 0
    size_bytes: int = 0


def _normalize_line(raw: str) -> str:
    return unicodedata.normalize("NFKC", raw).strip()


def _looks_like_page_number(line: str) -> bool:
    return any(p.match(line) for p in _PAGE_NUMBER_LINE_PATTERNS)


def _is_bare_page_number_at_edge(line: str, *, is_edge: bool) -> bool:
    """A lone integer is only ever a page number when it sits at the very
    start or end of the page's line list — the same text appearing mid-page
    is real content (a table cell, a part number), and dropping it there
    would silently swallow a real change (e.g. a table value "85" changing
    to "80"). See docs/redesign/plimsoll-real-document-smoketest-2026-09.html
    §3, Fix D."""
    return is_edge and bool(_BARE_PAGE_NUMBER_RE.match(line))


def _filter_page_lines(lines: list[str], boilerplate: set[str]) -> list[str]:
    last = len(lines) - 1
    return [
        l
        for idx, l in enumerate(lines)
        if l not in boilerplate
        and not _looks_like_page_number(l)
        and not _is_bare_page_number_at_edge(l, is_edge=(idx == 0 or idx == last))
    ]


def _strip_running_boilerplate(all_pages_lines: list[list[str]]) -> list[list[str]]:
    n = len(all_pages_lines)
    if n <= 1:
        return [_filter_page_lines(lines, set()) for lines in all_pages_lines]

    freq: Counter[str] = Counter()
    for lines in all_pages_lines:
        for l in set(lines):
            freq[l] += 1
    threshold = max(2, int(n * _BOILERPLATE_FREQUENCY_RATIO))
    boilerplate = {l for l, c in freq.items() if c >= threshold}

    return [_filter_page_lines(lines, boilerplate) for lines in all_pages_lines]


def _resolve_print_label(doc: "fitz.Document", page_index: int) -> tuple[str | None, str]:
    try:
        label = doc[page_index].get_label()
    except Exception:
        label = ""
    if label:
        return label, "page_labels"
    return None, "unknown"


def _page_spans(page: "fitz.Page") -> list[TextSpan]:
    """Word-level bounding boxes via PyMuPDF's own word extraction — cheaper
    and simpler than walking the full `get_text("dict")` block/line/span tree
    for our purposes (P5 §3c only needs "roughly where on the page", not
    per-glyph precision). `line_index` is the word's row within
    `page.get_text("words")`'s own top-to-bottom, left-to-right ordering."""
    words = page.get_text("words")  # (x0, y0, x1, y1, word, block_no, line_no, word_no)
    return [
        TextSpan(text=w[4], bbox=(w[0], w[1], w[2], w[3]), line_index=idx)
        for idx, w in enumerate(words)
        if w[4].strip()
    ]


# A single drawing this close to covering the whole page is a background
# fill, not a border/box/diagram element with actual content.
_BACKGROUND_FILL_MIN_COVERAGE = 0.95


def _is_only_background_fill(page: "fitz.Page", drawings: list) -> bool:
    """True when every drawing on the page is a single full-page-sized fill
    rectangle — see `_classify_page_kind`'s blank-page check for why this
    matters (a PDF generator's "paint the whole page white" artifact, not
    real content)."""
    page_area = page.rect.width * page.rect.height
    if not drawings or not page_area:
        return False
    for d in drawings:
        items = d.get("items", [])
        if d.get("type") != "f" or len(items) != 1 or items[0][0] != "re":
            return False
        rect = items[0][1]
        if (rect.width * rect.height) / page_area < _BACKGROUND_FILL_MIN_COVERAGE:
            return False
    return True


def _classify_page_kind(page: "fitz.Page", *, is_scanned: bool) -> PageKind:
    """Stage -1 (§26): only called for pages whose text layer is too thin to
    diff (`is_scanned=True`) — a page with a real text layer is always
    `text`, no matter what images/drawings also sit on it. See module
    docstring for the two heuristics and why an ambiguous page defaults to
    the safer `scanned_text` bucket rather than `diagram`."""
    if not is_scanned:
        return "text"

    try:
        drawings = page.get_drawings()
        # Each dict in get_drawings() is one path; a single path can bundle
        # many line/curve/rect sub-operations (e.g. one Shape.commit() call
        # drawing 60 lines is ONE path, not 60) — count sub-items, not paths,
        # so a drawing built as one batched path still registers as dense.
        drawing_item_count = sum(len(d.get("items", [])) for d in drawings)
    except Exception:
        drawings = []
        drawing_item_count = 0
    if drawing_item_count >= _MIN_DRAWING_ITEMS_FOR_DIAGRAM:
        return "diagram"

    try:
        page_area = page.rect.width * page.rect.height
        image_area = 0.0
        for img in page.get_images(full=True):
            for rect in page.get_image_rects(img[0]):
                image_area += rect.width * rect.height
        coverage = (image_area / page_area) if page_area else 0.0
    except Exception:
        coverage = 0.0
    if coverage >= _MIN_IMAGE_COVERAGE_FOR_SCANNED_TEXT:
        return "scanned_text"

    if coverage == 0.0 and (drawing_item_count == 0 or _is_only_background_fill(page, drawings)):
        # No text, no image, and no MEANINGFUL vector drawing — a
        # deliberately blank page (e.g. a chapter divider), not an
        # unreadable one. Real-world confirmation on the CCS Rules for Steel
        # Ships target document: of 152 low-text pages, 16 had literally
        # zero drawings and 45 more had exactly one drawing that was a
        # single full-page white fill rectangle (a background-fill artifact
        # some PDF generators emit even for a genuinely empty page) — not
        # real content. Treating either as "scanned, can't verify" turned
        # every blank-page position shift between editions into a false
        # High-risk alarm (docs/redesign/plimsoll-real-document-smoketest-
        # 2026-09.html §3, Fix "把空白頁從「疑似掃描頁」裡拿掉"). A page
        # with ANY OTHER nonzero drawing or image signal — even below the
        # diagram/scanned-text thresholds above — still falls through to the
        # ambiguous case below, unchanged: there IS something there we can't
        # read.
        return "text"

    # Neither signal is strong but nonzero: could be a page with a small
    # logo, a thin border, or a mixed page. Defaults to the pre-existing,
    # safer "flag it as scanned, no rendering assumptions" behavior.
    return "scanned_text"


def extract_document(pdf_bytes: bytes) -> ExtractedDocument:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        raw_pages = []
        for i in range(doc.page_count):
            page = doc[i]
            raw_text = page.get_text("text")
            lines = [_normalize_line(l) for l in raw_text.split("\n")]
            lines = [l for l in lines if l]
            char_count = sum(len(l) for l in lines)
            is_scanned_candidate = char_count < MIN_TEXT_CHARS_FOR_NON_SCANNED
            page_kind = _classify_page_kind(page, is_scanned=is_scanned_candidate)
            # Derived FROM page_kind (not the raw char-count candidate above)
            # so a genuinely blank page — reclassified "text" by the check
            # just added to _classify_page_kind — is also is_scanned=False,
            # keeping the two fields consistent with the class's own
            # documented invariant ("is_scanned" = page_kind != "text").
            is_scanned = page_kind != "text"
            print_label, label_source = _resolve_print_label(doc, i)
            raw_pages.append(
                {
                    "raw_text": raw_text,
                    "lines": lines,
                    "char_count": char_count,
                    "is_scanned": is_scanned,
                    "page_kind": page_kind,
                    "spans": _page_spans(page),
                    "print_label": print_label,
                    "label_source": label_source,
                }
            )

        stripped = _strip_running_boilerplate([p["lines"] for p in raw_pages])

        pages = [
            PageContent(
                pdf_page=i + 1,
                print_label=p["print_label"],
                label_source=p["label_source"],
                raw_text=p["raw_text"],
                lines=stripped[i],
                lines_canonical=list(stripped[i]),  # identity until normalize.apply_term_aliases() runs
                char_count=p["char_count"],
                is_scanned=p["is_scanned"],
                heading=next((l for l in stripped[i] if _looks_like_heading(l)), None),
                page_kind=p["page_kind"],
                spans=p["spans"],
            )
            for i, p in enumerate(raw_pages)
        ]

        return ExtractedDocument(pages=pages, page_count=doc.page_count, size_bytes=len(pdf_bytes))
    finally:
        doc.close()


def scanned_page_numbers(doc: ExtractedDocument) -> list[int]:
    return [p.pdf_page for p in doc.pages if p.is_scanned]


def diagram_page_numbers(doc: ExtractedDocument) -> list[int]:
    return [p.pdf_page for p in doc.pages if p.page_kind == "diagram"]


# --------------------------------------------------------------------------
# Metadata (title / version / date / applicable equipment) — regex-based,
# NEVER guessed. A field that doesn't match stays None and is reported as
# missing (R1 / AC1 / AC4).
# --------------------------------------------------------------------------

_VERSION_DATE_EN_RE = re.compile(r"Version:\s*([^\|\n]+?)\s*\|\s*Issue date:\s*([\d\-/]+)", re.IGNORECASE)
_VERSION_ZH_RE = re.compile(r"版本[號号]?[:：]\s*(\S+)")
_DATE_ZH_RE = re.compile(r"(?:發布)?日期[:：]\s*([\d\-/]+)")
_TITLE_ZH_RE = re.compile(r"文件名稱[:：]\s*(.+)")
_EQUIPMENT_ZH_RE = re.compile(r"適用設備[:：]\s*(.+)")


@dataclass
class ExtractedMetadata:
    title: str | None
    version: str | None
    date: str | None
    applicable_equipment: str | None
    missing_fields: list[str]

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields


def extract_metadata(doc: ExtractedDocument, *, scan_pages: int = 2) -> ExtractedMetadata:
    scan_text = "\n".join(p.raw_text for p in doc.pages[:scan_pages])

    title = None
    if m := _TITLE_ZH_RE.search(scan_text):
        title = m.group(1).strip().rstrip("。")

    version = None
    date = None
    if m := _VERSION_DATE_EN_RE.search(scan_text):
        version, date = m.group(1).strip(), m.group(2).strip()
    if version is None and (m := _VERSION_ZH_RE.search(scan_text)):
        version = m.group(1).strip()
    if date is None and (m := _DATE_ZH_RE.search(scan_text)):
        date = m.group(1).strip()

    equipment = None
    if m := _EQUIPMENT_ZH_RE.search(scan_text):
        equipment = m.group(1).strip().rstrip("。")

    missing = [
        name
        for name, value in (("title", title), ("version", version), ("date", date))
        if value is None
    ]

    return ExtractedMetadata(
        title=title,
        version=version,
        date=date,
        applicable_equipment=equipment,
        missing_fields=missing,
    )
