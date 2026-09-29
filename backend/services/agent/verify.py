"""Deterministic checks on everything the model claims (spec §4.5, §4.6) —
the reason 「不臆測、不自創、不偷換概念」 is enforced by code, not by asking
nicely in the prompt:

- citations: every quote must appear verbatim (whitespace aside) on the page
  it names; a claim left without a valid citation moves to 待確認.
- numbers: every number (and its unit) in a claim must appear in that
  claim's own cited quotes — "80°C" can't quietly become "80 度" or "85°C".
- glossary: definitions come only from the reviewed glossary; a term it
  doesn't cover (or a glossary still in draft) goes to 待確認.
- implementation names: rule ids become their 中文名; internal mode names
  are replaced — nothing from the config vocabulary reaches the reader.
- document-info warnings (missing version/date, scanned pages) are built
  here from the extracted metadata, never taken from the model, so they can
  be neither invented nor forgotten.

Nothing here calls a model; every check is reproducible from the session
files alone."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from backend.models.config_models import Glossary
from backend.services import session_store
from backend.services.agent.labels import RULE_LABEL
from backend.services.agent.schemas import AgentAnswer, Citation, ReviewBriefing
from backend.services.agent.tools import UNSTATED_REASON, SessionContext, parameter_label

OUT_OF_SCOPE_TEXT = "我只能回答與目前載入的船舶技術文件有關的問題。"
NOT_IN_DOCUMENTS_TEXT = "文件中找不到依據，已列為待確認。"
PRIORITY_LIMIT = 5

_FIELD_LABEL = {"title": "文件名稱", "version": "版本號", "date": "發布日期", "applicable_equipment": "適用設備"}
_SIDE_LABEL = {"old": "舊版", "new": "新版"}

# Config vocabulary that must never reach a reader. Rule ids map to their
# 中文名; the rest to the wording the settings panel itself uses.
_NAME_REPLACEMENTS: dict[str, str] = {
    **RULE_LABEL,
    "rules_first": "一般（預設）",
    "model_heavy": "寬鬆語意複核",
    "model_only": "全面 AI 分類",
    "SequenceMatcher": "文字比對",
    "ai_inferred": "AI 推論",
    "demo_seed": "示範資料",
}
_NAME_PATTERN = re.compile("|".join(re.escape(k) for k in sorted(_NAME_REPLACEMENTS, key=len, reverse=True)))

# Numerals that are structure, not facts from the document: difference ids,
# page refs, version labels, ordinal/count phrases.
_STRUCTURAL = re.compile(
    r"[Dd]\d+|[pP]\.\s*\d+|[vV]\d+(?:\.\d+)*|第\s*\d+\s*[頁筆版步項章節條]|\d+\s*[筆項]|\d+\s*／\s*\d+"
)
_UNITS = (
    "°C|°F|MPa|kPa|bar|rpm|kW|mm|cm|km|kg|ml|Hz|Pa|%|m|g|L|V|A|"
    "小時|分鐘|個月|秒|天|日|週|周|月|年|次|度"
)
_NUMBER = re.compile(rf"(?<![\d.])(\d+(?:\.\d+)?)\s*({_UNITS})?")


def _norm(text: str | None) -> str:
    # NFKC folds width variants (，→, ℃→°C, full-width digits) — extraction
    # normalises some lines (e.g. chain source_text) but not page text, and a
    # quote shouldn't fail over a comma's width. Wording must still match.
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or ""))


class Verifier:
    def __init__(self, ctx: SessionContext, glossary: Glossary | None):
        self.ctx = ctx
        self.glossary = glossary
        self.stats: Counter[str] = Counter()
        # (session, pages) per comparison a citation may point at: this one,
        # plus earlier chain versions and historical cases, loaded on demand.
        self._sources: dict[str, tuple[dict, dict] | None] = {ctx.session_id: (ctx.session, ctx.pages)}

    # ---- building blocks -------------------------------------------------

    def scrub(self, text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            self.stats["names_scrubbed"] += 1
            return _NAME_REPLACEMENTS[match.group(0)]

        return _NAME_PATTERN.sub(replace, text)

    def _source(self, session_id: str | None) -> tuple[dict, dict] | None:
        sid = session_id or self.ctx.session_id
        if sid not in self._sources:
            session, pages = session_store.get_session(sid), session_store.get_pages(sid)
            self._sources[sid] = (session, pages) if session is not None and pages is not None else None
        return self._sources[sid]

    def _page(self, session_id: str | None, side: str, pdf_page: int) -> dict | None:
        source = self._source(session_id)
        if source is None:
            return None
        return next((p for p in source[1].get(side, []) if p.get("pdf_page") == pdf_page), None)

    def _difference(self, session_id: str | None, difference_id: str) -> dict | None:
        source = self._source(session_id)
        if source is None:
            return None
        return next((d for d in source[0]["differences"] if d["id"] == difference_id), None)

    def _citation_ok(self, c: Citation) -> bool:
        quote = _norm(c.quote)
        if not quote:
            return False
        if c.difference_id is not None and self._difference(c.session_id, c.difference_id) is None:
            return False
        page = self._page(c.session_id, c.side, c.pdf_page)
        if page and quote in _norm(page.get("text")):
            return True
        # The difference's own span is lifted from that page; line joins in
        # page text can differ, so accept a verbatim match against the span.
        if c.difference_id:
            span = (self._difference(c.session_id, c.difference_id) or {}).get(c.side) or {}
            if (span.get("page") or {}).get("pdf_page") == c.pdf_page and quote in _norm(span.get("text")):
                return True
        return False

    def citations(self, citations: list[Citation]) -> list[dict]:
        kept = []
        for c in citations:
            self.stats["citations_checked"] += 1
            if not self._citation_ok(c):
                self.stats["citations_rejected"] += 1
                continue
            foreign = c.session_id not in (None, self.ctx.session_id)
            session = self._source(c.session_id)[0]
            kept.append(
                {
                    "session_id": c.session_id if foreign else None,
                    "difference_id": c.difference_id,
                    "side": c.side,
                    "pdf_page": c.pdf_page,
                    "print_label": (self._page(c.session_id, c.side, c.pdf_page) or {}).get("print_label"),
                    "version_label": session[f"{c.side}_meta"].get("version"),
                    "quote": c.quote.strip(),
                }
            )
        return kept

    def _headings(self, ids: list[str], session_id: str | None = None) -> list[str]:
        return [(self._difference(session_id, i) or {}).get("affected") or "" for i in ids]

    def _numbers_ok(self, texts: list[str], citations: list[dict], headings: list[str]) -> bool:
        # Section headings of the differences involved count as cited text
        # too (a heading like 「3. 冷卻溫度檢查」 names a section, not a fact).
        cited_headings = [
            (self._difference(c["session_id"], c["difference_id"]) or {}).get("affected") or ""
            for c in citations
            if c["difference_id"]
        ]
        allowed = _norm(" ".join(c["quote"] for c in citations) + " " + " ".join([*headings, *cited_headings]))
        for text in texts:
            for match in _NUMBER.finditer(_STRUCTURAL.sub(" ", text.replace("℃", "°C"))):
                number, unit = match.group(1), match.group(2)
                needle = _norm(number + (unit or ""))
                found = re.search(rf"(?<![\d.]){re.escape(needle)}(?!\d)", allowed) is not None
                if not found:
                    self.stats["numbers_rejected"] += 1
                    return False
        return True

    def _known_ids(self, ids: list[str]) -> list[str]:
        known = [i for i in ids if self.ctx.difference(i) is not None]
        self.stats["unknown_ids_dropped"] += len(ids) - len(known)
        return known

    def _to_pending(self, pending: list[dict], topic: str, reason: str, *, counter: str) -> None:
        # Counted per cause, so the UI can say *why* things moved to 待確認
        # instead of lumping a draft glossary in with failed citations.
        self.stats[counter] += 1
        pending.append({"topic": topic, "reason": reason})

    def _claim(self, pending: list[dict], topic: str, texts: list[str], citations: list[Citation], headings: list[str]) -> list[dict] | None:
        """Shared gate for one claim: valid citations required, numbers must
        match them. Returns the kept citations, or None after moving the
        claim to 待確認."""
        kept = self.citations(citations)
        if not kept:
            self._to_pending(pending, topic, "引用無法在原文中逐字找到", counter="claims_to_pending")
            return None
        if not self._numbers_ok(texts, kept, headings):
            self._to_pending(pending, topic, "數字或單位與引用的原文不一致", counter="claims_to_pending")
            return None
        return kept

    def glossary_entries(self, terms: list[str], pending: list[dict]) -> list[dict]:
        entries: list[dict] = []
        seen: set[str] = set()
        for term in (t.strip() for t in terms):
            if not term or term in seen:
                continue
            seen.add(term)
            if self.glossary is None:
                self._to_pending(pending, term, "目前沒有詞彙表", counter="terms_to_pending")
                continue
            if self.glossary.status != "approved":
                self._to_pending(pending, term, "詞彙表尚未經人工核准", counter="terms_to_pending")
                continue
            match = next((e for e in self.glossary.terms if term == e.term or term in e.aliases), None)
            if match is None:
                self._to_pending(pending, term, "詞彙表沒有這個名詞", counter="terms_to_pending")
            elif match.status != "approved":
                self._to_pending(pending, term, "這個名詞的定義還沒定案", counter="terms_to_pending")
            else:
                entries.append({"term": match.term, "definition": match.definition})
        return entries

    def document_warnings(self) -> list[dict]:
        warnings = []
        for side in ("old", "new"):
            meta = self.ctx.session[f"{side}_meta"]
            missing = [_FIELD_LABEL.get(f, f) for f in meta.get("missing_fields", [])]
            if missing:
                warnings.append(
                    {"kind": "missing_metadata", "message": f"{_SIDE_LABEL[side]}文件缺少：{'、'.join(missing)}。", "citations": [], "source": "system"}
                )
            scanned = self.ctx.scanned(side)
            if scanned:
                pages = "、".join(f"p.{p}" for p in scanned)
                warnings.append(
                    {
                        "kind": "low_confidence",
                        "message": f"{_SIDE_LABEL[side]}第 {pages} 疑似掃描頁或文字層不足，這幾頁的比對需要人工雙重校對。",
                        "citations": [],
                        "source": "system",
                    }
                )
        return warnings

    # ---- briefing ---------------------------------------------------------

    def briefing(self, raw: ReviewBriefing) -> dict:
        pending: list[dict] = [{"topic": self.scrub(p.topic), "reason": self.scrub(p.reason)} for p in raw.pending]

        warnings = self.document_warnings()
        for w in raw.warnings:
            message = self.scrub(w.message)
            kept = self._claim(pending, message, [message], w.citations, [])
            if kept is not None:
                warnings.append({"kind": w.kind, "message": message, "citations": kept, "source": "agent"})

        priority = []
        for p in raw.priority:
            if not self._known_ids([p.difference_id]):
                continue
            reason = self.scrub(p.reason)
            kept = self._claim(pending, f"{p.difference_id} 的優先理由", [reason], p.citations, self._headings([p.difference_id]))
            if kept is not None:
                priority.append({"difference_id": p.difference_id, "reason": reason, "citations": kept})
        if len(priority) > PRIORITY_LIMIT:
            self.stats["priority_truncated"] += len(priority) - PRIORITY_LIMIT
            priority = priority[:PRIORITY_LIMIT]

        items = []
        for it in raw.items:
            ids = self._known_ids(it.difference_ids)
            if not ids:
                continue
            impact = {k: [self.scrub(v) for v in getattr(it.impact, k)] for k in ("equipment", "parts", "procedures", "inspections")}
            detail = self.scrub(it.action_detail)
            texts = [detail, *(v for values in impact.values() for v in values)]
            kept = self._claim(pending, f"{'、'.join(ids)} 的影響與建議", texts, it.citations, self._headings(ids))
            if kept is not None:
                items.append(
                    {"difference_ids": ids, "impact": impact, "action": it.action, "action_detail": detail, "confidence": it.confidence, "citations": kept}
                )

        suggestions = []
        suggested: set[str] = set()
        for s in raw.suggestions:
            if s.difference_id in suggested or not self._known_ids([s.difference_id]):
                continue
            reason = self.scrub(s.reason)
            kept = self._claim(pending, f"{s.difference_id} 的覆核建議", [reason], s.citations, self._headings([s.difference_id]))
            if kept is not None:
                suggested.add(s.difference_id)
                suggestions.append({"difference_id": s.difference_id, "verdict": s.verdict, "reason": reason, "citations": kept})

        cause_trace = self._cause_trace(raw, pending)
        history = self._history(raw, pending)

        summary = self.scrub(raw.summary)
        all_citations = [c for group in (priority, items, suggestions, cause_trace) for entry in group for c in entry["citations"]]
        if not self._numbers_ok([summary], all_citations, self._headings([d["id"] for d in self.ctx.differences])):
            self.stats["summary_replaced"] += 1
            summary = self._fallback_summary(len(items), len(priority))

        glossary = self.glossary_entries(raw.glossary_terms, pending)
        return {
            "summary": summary,
            "warnings": warnings,
            "priority": priority,
            "items": items,
            "suggestions": suggestions,
            "cause_trace": cause_trace,
            "history": history,
            "pending": pending,
            "glossary": glossary,
            "verification": dict(self.stats),
        }

    def _cause_trace(self, raw: ReviewBriefing, pending: list[dict]) -> list[dict]:
        """變更原因追溯: only for a comparison inside a chain, only naming a
        version the chain really has. The reason is either backed by the
        entry's citations (checked like any claim) or exactly 「文件未載明」."""
        chain = self.ctx.chain
        versions = set(chain["ordered_versions"]) if chain else set()
        labels = {parameter_label(k) for k in chain["parameter_series"]} if chain else set()
        traces = []
        for t in raw.cause_trace:
            parameter, reason = self.scrub(t.parameter), self.scrub(t.reason.strip())
            topic = f"「{parameter}」的變更原因"
            if t.changed_in_version not in versions:
                self._to_pending(pending, topic, "版本不在這次比對所屬的多版本鏈中", counter="claims_to_pending")
                continue
            texts = [parameter] if reason == UNSTATED_REASON else [parameter, reason]
            kept = self._claim(pending, topic, texts, t.citations, [parameter] if parameter in labels else [])
            if kept is not None:
                traces.append({"parameter": parameter, "changed_in_version": t.changed_in_version, "reason": reason, "citations": kept})
        return traces

    def _history(self, raw: ReviewBriefing, pending: list[dict]) -> list[dict]:
        """歷史案例: must point at a different, existing comparison and a
        difference that really is in it."""
        cases = []
        for h in raw.history:
            topic = f"歷史案例 {h.session_id} {h.difference_id}"
            if h.session_id == self.ctx.session_id or self._difference(h.session_id, h.difference_id) is None:
                self._to_pending(pending, topic, "找不到這筆歷史比對", counter="claims_to_pending")
                continue
            note = self.scrub(h.note)
            kept = self._claim(pending, topic, [note], h.citations, self._headings([h.difference_id], h.session_id))
            if kept is not None:
                session = self._source(h.session_id)[0]
                cases.append(
                    {
                        "session_id": h.session_id,
                        "difference_id": h.difference_id,
                        "title": session.get("title"),
                        "versions": f"{session['old_meta'].get('version') or '?'} → {session['new_meta'].get('version') or '?'}",
                        "note": note,
                        "citations": kept,
                    }
                )
        return cases

    def _fallback_summary(self, item_count: int, priority_count: int) -> str:
        diffs = self.ctx.differences
        high = sum(1 for d in diffs if d["ai_risk"] == "High")
        return f"共 {len(diffs)} 筆差異，其中 {high} 筆 High；整理出 {item_count} 項影響說明與 {priority_count} 筆優先覆核項。"

    # ---- answer -----------------------------------------------------------

    def answer(self, raw: AgentAnswer, question: str) -> dict:
        pending: list[dict] = [{"topic": self.scrub(p.topic), "reason": self.scrub(p.reason)} for p in raw.pending]
        glossary = self.glossary_entries(raw.glossary_terms, pending)

        if raw.answer_type == "out_of_scope":
            return self._answer("out_of_scope", OUT_OF_SCOPE_TEXT, [], [], [])

        if raw.answer_type == "answer":
            text = self.scrub(raw.text)
            kept = self._claim(pending, question, [text], raw.citations, [])
            if kept is not None:
                return self._answer("answer", text, kept, pending, glossary)
            self.stats["answer_downgraded"] += 1
        else:
            self._to_pending(pending, question, "文件中找不到依據", counter="claims_to_pending")
        return self._answer("not_in_documents", NOT_IN_DOCUMENTS_TEXT, [], pending, glossary)

    def _answer(self, answer_type: str, text: str, citations: list[dict], pending: list[dict], glossary: list[dict]) -> dict:
        return {
            "answer_type": answer_type,
            "text": text,
            "citations": citations,
            "pending": pending,
            "glossary": glossary,
            "verification": dict(self.stats),
        }
