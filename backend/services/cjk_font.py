"""Shared CJK font discovery/registration for reportlab (PDF export, P4;
and scripts/generate_demo_pdfs.py's demo data). See extraction.py's module
docstring for *why* this matters: reportlab's base-14 fonts have no Chinese
glyphs, so skipping this silently produces tofu that still "looks fine" in
the PDF viewer but breaks any text extraction downstream.

Regenerating demo data or actually generating a PDF export needs a
CJK-capable font available on *this* machine — set PLIMSOLL_CJK_FONT_PATH
if none of the built-in candidates exist here.
"""

from __future__ import annotations

import os
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

CJK_FONT_NAME = "PlimsollCJK"

# (path, subfont_index) pairs, checked in order.
_CJK_FONT_CANDIDATES = [
    ("/System/Library/Fonts/STHeiti Light.ttc", 0),  # macOS
    ("/System/Library/Fonts/Supplemental/Songti.ttc", 0),  # macOS fallback
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),  # common Linux
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),  # common Linux (WenQuanYi)
]

_registered = False


def find_cjk_font() -> tuple[str, int]:
    override = os.environ.get("PLIMSOLL_CJK_FONT_PATH")
    if override:
        return override, int(os.environ.get("PLIMSOLL_CJK_FONT_INDEX", "0"))
    for path, index in _CJK_FONT_CANDIDATES:
        if Path(path).exists():
            return path, index
    raise FileNotFoundError(
        "No CJK-capable font found to embed. Set PLIMSOLL_CJK_FONT_PATH to a "
        ".ttf/.ttc that covers Traditional Chinese (e.g. Noto Sans TC), and "
        "PLIMSOLL_CJK_FONT_INDEX if it's a multi-face .ttc."
    )


def ensure_cjk_font_registered() -> str:
    """Idempotent — safe to call on every export request. Returns the
    reportlab font name to use in ParagraphStyle/TableStyle."""
    global _registered
    if not _registered:
        path, index = find_cjk_font()
        pdfmetrics.registerFont(TTFont(CJK_FONT_NAME, path, subfontIndex=index))
        _registered = True
    return CJK_FONT_NAME
