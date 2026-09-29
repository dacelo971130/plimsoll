"""Create five clearly fictional maintenance manual versions for the demo
(v1.0: six pages, v1.1-v1.4: seven — v1.1 adds a whole new closing section so
the pairwise demo shows a genuine 新增, not just 修改; v1.2-v1.4 extend the
chain for W5/W6's cumulative-drift demo. See W2/W5/W6 in
docs/redesign/plimsoll-improvement-plan.html).

IMPORTANT — CJK font embedding: `getSampleStyleSheet()`'s default fonts
(Helvetica/base-14) have no Chinese glyphs, so reportlab silently draws
tofu/garbage for every Traditional-Chinese character while still "succeeding"
— the PDF looks fine on screen but PyMuPDF (and any other text extractor)
reads back garbage, which would break the whole comparison engine. We embed
a real CJK-capable TTF/TTC (subset, baked into the output PDF) so the
generated files are portable and self-contained regardless of what fonts the
*reading* machine has. Regenerating this script's output, however, needs a
CJK-capable font available on the *build* machine — see
`backend/services/cjk_font.py` (shared with the P4 PDF export service).
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # so `python3 scripts/generate_demo_pdfs.py` can `import backend`

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfdoc import PDFPageLabel
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from backend.services.cjk_font import ensure_cjk_font_registered

OUTPUT_DIR = REPO_ROOT / "data" / "demo"

COMMON_PAGES = [
    ("1. 文件識別與適用範圍", [
        "文件名稱：Main Engine Cooling System Maintenance Procedure",
        "適用設備：主機冷卻系統、循環泵浦與溫度感測器。",
        "本文件為虛構 Demo 資料，不得用於真實船舶操作。",
    ]),
    ("2. 安全準備", [
        "維修前應確認主機停止、隔離電源，並穿戴防護裝備。",
        "任何警告標示不清楚時，應停止作業並通知工程主管。",
    ]),
]

def _drift_line(value: float) -> str:
    # W5/W6 demo: a monitored value that deliberately uses NONE of ruleset
    # v1/v2's safety_terms/obligation_terms/applicability_terms vocabulary —
    # every single-step change to it classifies as default/Low no matter the
    # ruleset, exactly the "regulär text change" gap cumulative_drift exists
    # to close. -0.2 per version across v1.1→v1.4 (4% total over the chain,
    # every step direction-consistent) is what the chain drift demo tracks.
    return f"本系統目前量測效率係數為 {value:.1f}%，供廠內趨勢紀錄參考。"


def _with_drift_value(pages: list[tuple[str, list[str]]], value: float) -> list[tuple[str, list[str]]]:
    """v1.2-v1.4 are v1.1 with only the drift line's value changed (plus the
    revision-reason line, see _with_reason) — every other section stays
    byte-identical, so each adjacent step in the chain surfaces just the
    drift change and its stated reason."""
    new_pages = list(pages)
    heading, lines = new_pages[0]
    new_pages[0] = (heading, lines[:-1] + [_drift_line(value)])
    return new_pages


# Review-agent bonus item 「變更原因追溯」 (plimsoll-review-agent-spec.md §4.2):
# each version's 版本異動摘要 page states why it was revised, as a real
# revision page would — so the agent has a documented reason to quote
# instead of guessing. Two constraints keep the demo's results unchanged:
# no digits (a number-with-unit would start a parameter series of its own
# and muddy the drift demo), and none of the ruleset's safety/obligation/
# applicability terms (溫度、每週、定期… would make a revision note classify
# as a High safety change — padding the demo, which the not-do list forbids).
# test_agent_demo_reasons.py pins both.
# v1.2-v1.4 all say "latest measurement" — individually harmless, which is
# exactly the story cumulative drift tells across the chain. Fictional.
REVISION_REASONS = {
    "v1.1": "修訂原因（虛構示範）：例行巡檢發現冷卻液出口讀值偏高，因此收緊出口門檻，並提高感測器的檢查頻率。",
    "v1.2": "修訂原因（虛構示範）：效率係數依最新量測結果更新，其餘內容未變。",
    "v1.3": "修訂原因（虛構示範）：效率係數依最新量測結果更新，其餘內容未變。",
    "v1.4": "修訂原因（虛構示範）：效率係數依最新量測結果更新，其餘內容未變。",
}


def _with_reason(pages: list[tuple[str, list[str]]], version: str) -> list[tuple[str, list[str]]]:
    """Swap the 版本異動摘要 page's reason line for this version's."""
    heading, lines = pages[-1]
    return [*pages[:-1], (heading, lines[:-1] + [REVISION_REASONS[version]])]


V10_PAGES = [
    ("3. 冷卻溫度檢查", [
        "2.1 冷卻液出口溫度建議維持在 85°C 以下。",
        "工程人員應每月檢查一次溫度感測器讀值。",
        "超過建議值時，記錄於維修日誌。",
        _drift_line(20.0),
    ]),
    ("4. 循環泵浦保養", [
        "使用零件料號 CP-100 的密封件。",
        "啟動前建議檢查循環泵浦是否有洩漏。",
        "適用船型：巡防艦 A 型。",
    ]),
    ("5. 停機程序", [
        "先停止循環泵浦，再關閉冷卻液出口閥。",
        "如發現壓力高於 10 bar，請記錄並通報。",
    ]),
    ("6. 維修紀錄", [
        "維修完成後，由工程人員填寫維修日誌。",
        "保留最近一次檢查結果即可。",
        "本記錄應留存至少三年以供稽核。",
        "如有缺漏，應由品保主管簽核補正。",
        # W2: this line only exists in v1.0 — a genuine 刪除 instance once
        # v1.1 drops it (the two lines above stay identical across versions
        # so SequenceMatcher anchors on them and tags this line alone as a
        # clean delete, instead of folding into the replace run above).
        "本文件如有疑問，請洽船東技術部門。",
    ]),
]

V11_PAGES = [
    ("3. 冷卻溫度檢查", [
        "2.1 冷卻液出口溫度必須維持在 80°C 以下。",
        "工程人員必須每週檢查一次溫度感測器讀值。",
        "超過限值時，應立即停止主機並通知工程主管。",
        _drift_line(19.8),
    ]),
    ("4. 循環泵浦保養", [
        "使用零件料號 CP-120 的耐熱密封件。",
        "每次啟動前必須檢查循環泵浦是否有洩漏。",
        "適用船型：巡防艦 A 型及 B 型。",
    ]),
    ("5. 停機程序", [
        "先關閉冷卻液出口閥，再停止循環泵浦。",
        "如發現壓力高於 8 bar，必須停止作業並通報。",
    ]),
    ("6. 維修紀錄", [
        "維修完成後，由工程人員填寫維修日誌與驗證紀錄。",
        "保留最近三次檢查結果，供安全品質人員覆核。",
        "本記錄應留存至少三年以供稽核。",
        "如有缺漏，應由品保主管簽核補正。",
    ]),
    # W2: a whole new section that only exists in v1.1 — a genuine 新增
    # instance (old.page_count < new.page_count triggers compare_documents()'s
    # whole-page 新增 path).
    ("7. 版本異動摘要", [
        "本頁彙整本次改版與前一版本之差異重點，僅供內部參考。",
        "完整逐項比對結果請見系統產出之差異清單。",
        REVISION_REASONS["v1.1"],
    ]),
]

# W5/W6 chain demo: v1.2-v1.4 extend the chain past v1.1 with no change
# except the drift line — each adjacent step (v1.1→v1.2→v1.3→v1.4) is a
# single default/Low 修改, but across the full v1.0→v1.4 chain the same
# series drops 20.0→19.2 (4% over 4 consistent steps), which the chain's
# own cumulative_drift rule (W6) picks up even though no single step did.
V12_PAGES = _with_reason(_with_drift_value(V11_PAGES, 19.6), "v1.2")
V13_PAGES = _with_reason(_with_drift_value(V11_PAGES, 19.4), "v1.3")
V14_PAGES = _with_reason(_with_drift_value(V11_PAGES, 19.2), "v1.4")


def footer(canvas, doc):
    if doc.page == 1:
        # W2: give the PDF real /PageLabels (Arabic, starting at 1) so
        # extraction.py's `page.get_label()` returns a value and
        # label_source flips from "unknown" to "page_labels". Set once on
        # the first page — reportlab's PDFPageLabels apply from `pageNum`
        # (0-indexed) onward until the next label definition, so this alone
        # covers every page of the document.
        canvas.addPageLabel(0, style=PDFPageLabel.ARABIC, start=1)
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#607276"))
    canvas.drawString(18 * mm, 12 * mm, "Fictional training data - not an operational instruction")
    canvas.drawRightString(192 * mm, 12 * mm, f"PDF p.{doc.page}")
    canvas.restoreState()


def build(version: str, pages: list[tuple[str, list[str]]], filename: str) -> None:
    cjk_font_name = ensure_cjk_font_registered()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(str(OUTPUT_DIR / filename), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm)
    base = getSampleStyleSheet()
    # One CJK-capable font applied to every style used below — it covers
    # Latin + digits + punctuation too, so English lines render identically.
    styles = {
        name: ParagraphStyle(name, parent=base[name], fontName=cjk_font_name)
        for name in ("Title", "Heading1", "Heading2", "BodyText")
    }
    story = []
    all_pages = COMMON_PAGES + pages
    total_pages = len(all_pages)
    for idx, (heading, lines) in enumerate(all_pages, start=1):
        story.append(Paragraph("AI Ship Document Comparison Demo", styles["Title"]))
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(f"Version: {version} | Issue date: 2026-08-15", styles["Heading2"]))
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph(heading, styles["Heading1"]))
        story.append(Spacer(1, 3 * mm))
        for line in lines:
            story.append(Paragraph(line, styles["BodyText"]))
            story.append(Spacer(1, 3 * mm))
        if idx == 4:
            table = Table([["檢查項目", "舊/新要求"], ["冷卻液溫度", lines[0]], ["檢查頻率", lines[1]]], colWidths=[42 * mm, 120 * mm])
            table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), cjk_font_name),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#159B91")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9E5E3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]))
            story.extend([Spacer(1, 5 * mm), table])
        if idx < total_pages:
            story.append(PageBreak())
    document.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    build("v1.0", V10_PAGES, "Main_Engine_Cooling_v1.0.pdf")
    build("v1.1", V11_PAGES, "Main_Engine_Cooling_v1.1.pdf")
    build("v1.2", V12_PAGES, "Main_Engine_Cooling_v1.2.pdf")
    build("v1.3", V13_PAGES, "Main_Engine_Cooling_v1.3.pdf")
    build("v1.4", V14_PAGES, "Main_Engine_Cooling_v1.4.pdf")
    print(f"Created demo PDFs in {OUTPUT_DIR}")

