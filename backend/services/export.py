"""P4 report export — HTML / DOCX / PDF, all built from the same session
dict `get_session()` already returns (differences + folded review_state).

情境四 Human Control: exporting while High-risk items are unreviewed is
never blocked outright — it's watermarked "修訂草稿" and requires explicit
acknowledgement (see session_store.export_session / ExportRequiresAck).
Nothing here decides that; these functions just render whatever `is_draft`
they're told.
"""

from __future__ import annotations

import html
import io
from dataclasses import dataclass, field

from backend.models.config_models import Glossary
from backend.storage.config_loader import get_glossary, latest_glossary_version

VERDICT_LABEL = {
    "CONFIRMED": "已確認",
    "TRACK": "需追蹤",
    "REJECTED": "不採納",
    "FALSE_POSITIVE": "誤報",
    None: "未覆核",
}


@dataclass
class ExportMeta:
    reviewer_name: str
    approval_role_code: str
    role_label: str
    report_no: str
    dept: str
    is_draft: bool
    exported_at: str


def _page_label(span: dict | None) -> str:
    if span is None:
        return "—"
    page = span["page"]
    return page["print_label"] or (f"PDF p.{page['pdf_page']}" if page["pdf_page"] is not None else "—")


def _effective_risk(d: dict, state: dict) -> str:
    return state.get("risk_override") or d["ai_risk"]


def _draft_banner_text(meta: ExportMeta, unreviewed_count: int) -> str:
    return f"本報告為修訂草稿：仍有 {unreviewed_count} 筆 High 風險變更尚未完成人工覆核，由 {meta.reviewer_name} 承擔簽核責任後匯出。"


# --------------------------------------------------------------------------
# Appendix: 待確認事項 + 名詞解釋 (plimsoll-review-agent-spec.md §4.5)
# --------------------------------------------------------------------------
#
# Both are derived deterministically from the session and the controlled
# glossary — no model is involved, so the appendix can't invent anything.
# The report body still carries only human verdicts.

_FIELD_LABEL = {"title": "文件名稱", "version": "版本號", "date": "發布日期", "applicable_equipment": "適用設備"}
_SIDE_LABEL = {"old": "舊版", "new": "新版"}
# Column headers and fixed labels every report prints — part of what a
# reader might need explained, so glossary matching looks at them too.
_REPORT_FIXED_TEXT = "類型 風險 變更解讀 受影響設備/流程 建議處置 舊版來源 新版來源 人工覆核與決策 新增 刪除 修改"
_UNSET = object()


@dataclass
class Appendix:
    pending: list[tuple[str, str]] = field(default_factory=list)  # (事項, 原因)
    glossary: list[tuple[str, str]] = field(default_factory=list)  # (名詞, 定義)
    glossary_note: str | None = None


def _load_glossary() -> Glossary | None:
    version = latest_glossary_version()
    return get_glossary(version) if version else None


def _pending_items(session: dict) -> list[tuple[str, str]]:
    review_state = session["review_state"]
    items: list[tuple[str, str]] = []
    for side in ("old", "new"):
        missing = [_FIELD_LABEL.get(f, f) for f in session[f"{side}_meta"].get("missing_fields", [])]
        if missing:
            items.append((f"{_SIDE_LABEL[side]}文件資訊", f"缺少{'、'.join(missing)}"))
        scanned = session.get(f"scanned_{side}") or []
        if scanned:
            items.append((f"{_SIDE_LABEL[side]} {'、'.join(f'p.{p}' for p in scanned)}", "疑似掃描頁或文字層不足，需人工雙重校對"))
    for d in session["differences"]:
        state = review_state.get(d["id"], {})
        verdict = state.get("human_verdict")
        if d["ai_risk"] == "High" and verdict != "CONFIRMED":
            reason = "尚未覆核" if verdict is None else f"判定為「{VERDICT_LABEL[verdict]}」，尚未確認"
            items.append((f"{d['id']}（High）", reason))
        elif verdict == "TRACK":
            items.append((f"{d['id']}（{_effective_risk(d, state)}）", "覆核人標為「需追蹤」"))
        if d.get("ai_confidence") == "低":
            items.append((f"{d['id']}", "系統對這筆的判讀信心低，需人工比對原文"))
    return items


def _report_corpus(session: dict, is_draft: bool, pending: list[tuple[str, str]]) -> str:
    review_state = session["review_state"]
    parts = [_REPORT_FIXED_TEXT, "修訂草稿" if is_draft else ""]
    for d in session["differences"]:
        state = review_state.get(d["id"], {})
        parts += [
            d["explanation"],
            d["affected"] or "",
            d["recommended_action"],
            _effective_risk(d, state),
            VERDICT_LABEL.get(state.get("human_verdict"), "未覆核"),
            state.get("reviewer_note") or "",
        ]
    parts += [f"{item} {reason}" for item, reason in pending]
    return " ".join(parts).replace("／", "/")


def build_appendix(session: dict, is_draft: bool, glossary: Glossary | None | object = _UNSET) -> Appendix:
    """Pending items always; glossary definitions only from an approved
    glossary, and only for terms this report actually uses — never the
    whole table, never a definition the glossary doesn't have."""
    appendix = Appendix(pending=_pending_items(session))
    table = _load_glossary() if glossary is _UNSET else glossary
    if table is None:
        appendix.glossary_note = "目前沒有詞彙表，本報告不附名詞解釋。"
        return appendix
    if table.status != "approved":
        appendix.glossary_note = "詞彙表尚未經人工核准，本報告暫不附名詞解釋。"
        return appendix
    corpus = _report_corpus(session, is_draft, appendix.pending)
    for entry in table.terms:
        names = [entry.term, *entry.aliases]
        if not any(name.replace("／", "/") in corpus for name in names):
            continue
        if entry.status == "approved":
            appendix.glossary.append((entry.term, entry.definition))
        else:
            appendix.pending.append((f"名詞「{entry.term}」", "定義尚未定案"))
    if not appendix.glossary:
        appendix.glossary_note = "本報告沒有需要解釋的名詞。"
    return appendix


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

_HTML_STYLE = """
body{font-family:Arial,'Noto Sans TC',sans-serif;margin:40px;color:#172a2c;background:#fcfefe}
h1{color:#0e766e}
.meta-bar{background:#e8f7f5;padding:14px;border-radius:8px;margin-bottom:16px;font-size:13px}
.draft-banner{background:#ffebe9;border:1px solid #b43b37;color:#b43b37;padding:12px;border-radius:8px;margin-bottom:16px;font-weight:bold}
.metrics{display:flex;gap:12px;margin:16px 0}
.metric{border:1px solid #d9e5e3;border-radius:8px;padding:12px;min-width:120px;background:#fff}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{border:1px solid #d9e5e3;padding:8px;vertical-align:top;text-align:left}
th{background:#e8f7f5;color:#0e766e}
.risk-high{color:#b43b37;font-weight:700}
.risk-medium{color:#a86000;font-weight:700}
.risk-low{color:#14603f;font-weight:700}
code{background:#f0f7f6;padding:2px 4px;font-size:12px;display:block;white-space:pre-wrap;margin-top:4px}
footer{margin-top:20px;color:#607276;font-size:11.5px}
h2{color:#0e766e;font-size:16px;margin-top:28px}
.appendix-note{color:#607276;font-size:12.5px}
dl{font-size:12.5px}
dt{font-weight:700;margin-top:8px}
dd{margin:2px 0 0 0}
"""


def build_html_report(session: dict, meta: ExportMeta) -> bytes:
    review_state = session["review_state"]
    differences = session["differences"]

    high = sum(1 for d in differences if d["ai_risk"] == "High")
    reviewed = sum(1 for d in differences if review_state.get(d["id"], {}).get("human_verdict") is not None)
    unreviewed_high = sum(
        1 for d in differences if d["ai_risk"] == "High" and review_state.get(d["id"], {}).get("human_verdict") != "CONFIRMED"
    )

    rows = []
    for d in differences:
        state = review_state.get(d["id"], {})
        verdict = state.get("human_verdict")
        risk = _effective_risk(d, state)
        old_text = html.escape(d["old"]["text"]) if d["old"] else "（新增項目）"
        new_text = html.escape(d["new"]["text"]) if d["new"] else "（刪除項目）"
        decision = f"<strong>{VERDICT_LABEL.get(verdict, '未覆核')}</strong>"
        if verdict:
            decision += f"<br>{html.escape(state.get('reviewer_name') or '')} · {html.escape(state.get('approval_role_label_snapshot') or '')}"
        if state.get("reviewer_note"):
            decision += f"<br>{html.escape(state['reviewer_note'])}"
        rows.append(
            f"<tr><td>{d['id']}</td><td>{d['change_type']}</td>"
            f"<td class='risk-{risk.lower()}'>{risk}</td>"
            f"<td>{html.escape(d['explanation'])}</td><td>{html.escape(d['affected'] or '—')}</td>"
            f"<td>{html.escape(d['recommended_action'])}</td>"
            f"<td>{html.escape(_page_label(d['old']))}<code>{old_text}</code></td>"
            f"<td>{html.escape(_page_label(d['new']))}<code>{new_text}</code></td>"
            f"<td>{decision}</td></tr>"
        )

    draft_banner = (
        f"<div class='draft-banner'>⚠ {_draft_banner_text(meta, unreviewed_high)}</div>" if meta.is_draft else ""
    )

    appendix = build_appendix(session, meta.is_draft)
    if appendix.pending:
        pending_rows = "".join(f"<tr><td>{html.escape(item)}</td><td>{html.escape(reason)}</td></tr>" for item, reason in appendix.pending)
        pending_html = f"<table><thead><tr><th>事項</th><th>原因</th></tr></thead><tbody>{pending_rows}</tbody></table>"
    else:
        pending_html = "<p class='appendix-note'>沒有待確認事項。</p>"
    if appendix.glossary:
        terms = "".join(f"<dt>{html.escape(term)}</dt><dd>{html.escape(definition)}</dd>" for term, definition in appendix.glossary)
        glossary_html = f"<dl>{terms}</dl>"
    else:
        glossary_html = f"<p class='appendix-note'>{html.escape(appendix.glossary_note or '')}</p>"

    document = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>{html.escape(session['title'])} — 版本差異審查報告</title><style>{_HTML_STYLE}</style></head><body>
<h1>船舶技術文件版本差異審查報告{' （修訂草稿）' if meta.is_draft else ''}</h1>
<div class="meta-bar">
  <strong>文件：</strong>{html.escape(session['title'])}
  <strong>舊版：</strong>{html.escape(session['old_meta']['version'] or '—')}
  <strong>新版：</strong>{html.escape(session['new_meta']['version'] or '—')}
  <strong>報告編號：</strong>{html.escape(meta.report_no or '—')}
  <strong>部門：</strong>{html.escape(meta.dept or '—')}<br>
  <strong>簽核人：</strong>{html.escape(meta.reviewer_name)}（{html.escape(meta.role_label)}）
  <strong>產生時間：</strong>{html.escape(meta.exported_at)}
</div>
{draft_banner}
<div class="metrics">
  <div class="metric">總差異筆數<br><strong style="font-size:20px">{len(differences)}</strong></div>
  <div class="metric">High 重大變更<br><strong style="font-size:20px;color:#b43b37">{high}</strong></div>
  <div class="metric">已完成覆核<br><strong style="font-size:20px;color:#159b91">{reviewed}</strong></div>
  <div class="metric">待簽核 High<br><strong style="font-size:20px;color:#a86000">{unreviewed_high}</strong></div>
</div>
<p>本報告由 Plimsoll 依據原文頁碼與段落生成；語意與風險判讀僅供草稿與提示參考，工程與安全品質審查
人員仍為最終決策者。</p>
<table><thead><tr><th>ID</th><th>類型</th><th>風險</th><th>變更解讀</th><th>受影響設備/流程</th>
<th>建議處置</th><th>舊版來源</th><th>新版來源</th><th>人工覆核與決策</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<h2>待確認事項</h2>
{pending_html}
<h2>名詞解釋</h2>
{glossary_html}
<footer>Plimsoll — 船舶技術文件版本差異比對。本報告為草稿與風險提示輔助，非正式工程結論。</footer>
</body></html>"""
    return document.encode("utf-8")


# --------------------------------------------------------------------------
# DOCX
# --------------------------------------------------------------------------

def build_docx_report(session: dict, meta: ExportMeta) -> bytes:
    from docx import Document  # local import: only needed on the export path
    from docx.shared import Pt, RGBColor

    review_state = session["review_state"]
    differences = session["differences"]

    doc = Document()
    doc.add_heading(f"船舶技術文件版本差異審查報告{'（修訂草稿）' if meta.is_draft else ''}", level=1)

    meta_p = doc.add_paragraph()
    meta_p.add_run(
        f"文件：{session['title']}　舊版：{session['old_meta']['version'] or '—'}　"
        f"新版：{session['new_meta']['version'] or '—'}\n"
        f"報告編號：{meta.report_no or '—'}　部門：{meta.dept or '—'}\n"
        f"簽核人：{meta.reviewer_name}（{meta.role_label}）　產生時間：{meta.exported_at}"
    )

    if meta.is_draft:
        unreviewed_high = sum(
            1 for d in differences if d["ai_risk"] == "High" and review_state.get(d["id"], {}).get("human_verdict") != "CONFIRMED"
        )
        warn = doc.add_paragraph()
        run = warn.add_run(f"⚠ {_draft_banner_text(meta, unreviewed_high)}")
        run.bold = True
        run.font.color.rgb = RGBColor(0xB4, 0x3B, 0x37)

    doc.add_paragraph(
        "本報告之語意與風險判讀僅供草稿與提示參考；工程與安全品質審查人員仍為最終決策者。"
    )

    headers = ["ID", "類型", "風險", "變更解讀", "受影響設備/流程", "建議處置", "舊版來源", "新版來源", "人工覆核與決策"]
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Grid Accent 1"
    for cell, header in zip(table.rows[0].cells, headers):
        cell.text = header
        cell.paragraphs[0].runs[0].bold = True

    for d in differences:
        state = review_state.get(d["id"], {})
        verdict = state.get("human_verdict")
        risk = _effective_risk(d, state)
        old_text = d["old"]["text"] if d["old"] else "（新增項目）"
        new_text = d["new"]["text"] if d["new"] else "（刪除項目）"
        decision_lines = [VERDICT_LABEL.get(verdict, "未覆核")]
        if verdict:
            decision_lines.append(f"{state.get('reviewer_name') or ''} · {state.get('approval_role_label_snapshot') or ''}")
        if state.get("reviewer_note"):
            decision_lines.append(state["reviewer_note"])

        row = table.add_row().cells
        row[0].text = d["id"]
        row[1].text = d["change_type"]
        risk_run = row[2].paragraphs[0].add_run(risk)
        risk_run.bold = True
        if risk == "High":
            risk_run.font.color.rgb = RGBColor(0xB4, 0x3B, 0x37)
        elif risk == "Medium":
            risk_run.font.color.rgb = RGBColor(0xA8, 0x60, 0x00)
        else:
            risk_run.font.color.rgb = RGBColor(0x14, 0x60, 0x3F)
        row[3].text = d["explanation"]
        row[4].text = d["affected"] or "—"
        row[5].text = d["recommended_action"]
        row[6].text = f"{_page_label(d['old'])}\n{old_text}"
        row[7].text = f"{_page_label(d['new'])}\n{new_text}"
        row[8].text = "\n".join(decision_lines)

    for row in table.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(9)

    appendix = build_appendix(session, meta.is_draft)
    doc.add_heading("待確認事項", level=2)
    if appendix.pending:
        pending_table = doc.add_table(rows=1, cols=2)
        pending_table.style = "Light Grid Accent 1"
        pending_table.rows[0].cells[0].text = "事項"
        pending_table.rows[0].cells[1].text = "原因"
        for item, reason in appendix.pending:
            cells = pending_table.add_row().cells
            cells[0].text = item
            cells[1].text = reason
    else:
        doc.add_paragraph("沒有待確認事項。")
    doc.add_heading("名詞解釋", level=2)
    if appendix.glossary:
        for term, definition in appendix.glossary:
            p = doc.add_paragraph()
            p.add_run(f"{term}：").bold = True
            p.add_run(definition)
    else:
        doc.add_paragraph(appendix.glossary_note or "")

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------

def build_pdf_report(session: dict, meta: ExportMeta) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from backend.services.cjk_font import ensure_cjk_font_registered

    font_name = ensure_cjk_font_registered()
    base = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=base["Title"], fontName=font_name, fontSize=16)
    body_style = ParagraphStyle("body", parent=base["BodyText"], fontName=font_name, fontSize=8.5, leading=11)
    cell_style = ParagraphStyle("cell", parent=body_style, fontSize=7.5, leading=9.5)

    review_state = session["review_state"]
    differences = session["differences"]
    # Paragraph parses its text as mini-markup, so every value that came
    # from an uploaded document or a person must be escaped: raw source text
    # like "x<y" raises ValueError (→ export 500) and "A&B" silently renders
    # as "A &B;". Only the <br/> this function adds itself stays markup.
    esc = html.escape

    story = [Paragraph(f"船舶技術文件版本差異審查報告{'（修訂草稿）' if meta.is_draft else ''}", title_style), Spacer(1, 4 * mm)]
    story.append(
        Paragraph(
            f"文件：{esc(session['title'])}　舊版：{esc(session['old_meta']['version'] or '—')}　"
            f"新版：{esc(session['new_meta']['version'] or '—')}　報告編號：{esc(meta.report_no or '—')}　部門：{esc(meta.dept or '—')}<br/>"
            f"簽核人：{esc(meta.reviewer_name)}（{esc(meta.role_label)}）　產生時間：{esc(meta.exported_at)}",
            body_style,
        )
    )
    story.append(Spacer(1, 3 * mm))

    if meta.is_draft:
        unreviewed_high = sum(
            1 for d in differences if d["ai_risk"] == "High" and review_state.get(d["id"], {}).get("human_verdict") != "CONFIRMED"
        )
        warn_style = ParagraphStyle("warn", parent=body_style, textColor=colors.HexColor("#B43B37"))
        story.append(Paragraph(f"⚠ {esc(_draft_banner_text(meta, unreviewed_high))}", warn_style))
        story.append(Spacer(1, 3 * mm))

    story.append(
        Paragraph("本報告之語意與風險判讀僅供草稿與提示參考；工程與安全品質審查人員仍為最終決策者。", body_style)
    )
    story.append(Spacer(1, 4 * mm))

    header = ["ID", "類型", "風險", "變更解讀", "受影響設備/流程", "建議處置", "舊版來源", "新版來源", "覆核決策"]
    data = [[Paragraph(h, cell_style) for h in header]]
    for d in differences:
        state = review_state.get(d["id"], {})
        verdict = state.get("human_verdict")
        risk = _effective_risk(d, state)
        old_text = d["old"]["text"] if d["old"] else "（新增項目）"
        new_text = d["new"]["text"] if d["new"] else "（刪除項目）"
        decision = VERDICT_LABEL.get(verdict, "未覆核")
        if verdict:
            decision += f"<br/>{esc(state.get('reviewer_name') or '')}"
        data.append(
            [
                Paragraph(esc(d["id"]), cell_style),
                Paragraph(esc(d["change_type"]), cell_style),
                Paragraph(esc(risk), cell_style),
                Paragraph(esc(d["explanation"]), cell_style),
                Paragraph(esc(d["affected"] or "—"), cell_style),
                Paragraph(esc(d["recommended_action"]), cell_style),
                Paragraph(f"{esc(_page_label(d['old']))}<br/>{esc(old_text)}", cell_style),
                Paragraph(f"{esc(_page_label(d['new']))}<br/>{esc(new_text)}", cell_style),
                Paragraph(decision, cell_style),
            ]
        )

    col_widths = [12, 12, 12, 38, 28, 34, 38, 38, 30]
    col_widths = [w * mm for w in col_widths]
    # A real document's whole-section add/delete puts 2000+ characters into
    # one source cell — a row taller than the page. With the default
    # splitByRow-only behaviour that's a LayoutError (export 500), so rows
    # must be allowed to break across pages, like a Word table's default.
    # splitByRow=0 matters too: with splitByRow=1 + splitInRow, ReportLab
    # first splits at a row boundary and then again inside the row, and each
    # piece repeats the header — two header rows on the same page.
    table = Table(data, colWidths=col_widths, repeatRows=1, splitByRow=0, splitInRow=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#159B91")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9E5E3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)

    appendix = build_appendix(session, meta.is_draft)
    heading_style = ParagraphStyle("h2", parent=body_style, fontSize=11, leading=14, spaceBefore=8, spaceAfter=4)
    story.append(Paragraph("待確認事項", heading_style))
    if appendix.pending:
        pending_data = [[Paragraph("事項", cell_style), Paragraph("原因", cell_style)]]
        pending_data += [[Paragraph(html.escape(item), cell_style), Paragraph(html.escape(reason), cell_style)] for item, reason in appendix.pending]
        pending_table = Table(pending_data, colWidths=[60 * mm, 150 * mm], repeatRows=1)
        pending_table.hAlign = "LEFT"  # line up with the section heading, not centred
        pending_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F7F5")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9E5E3")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(pending_table)
    else:
        story.append(Paragraph("沒有待確認事項。", body_style))
    story.append(Paragraph("名詞解釋", heading_style))
    if appendix.glossary:
        for term, definition in appendix.glossary:
            story.append(Paragraph(f"<b>{html.escape(term)}</b>：{html.escape(definition)}", body_style))
    else:
        story.append(Paragraph(html.escape(appendix.glossary_note or ""), body_style))

    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm, topMargin=10 * mm, bottomMargin=10 * mm
    ).build(story)
    return buffer.getvalue()
