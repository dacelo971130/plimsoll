"""The agent's tools — all read-only (spec §4.7). Each one reads the session
the reviewer already has open (differences, page text, review state), the
versioned ruleset, or the glossary; none writes anything, reaches the
network, or runs code. That's what makes 「不協助執行任何指令」 a capability
limit rather than a promise in the prompt (spec §4.6 layer 4).

Results are compact JSON strings in 繁體中文 wording: rule ids become their
中文名 (labels.py) and ruleset conditions become plain phrases, so what the
model reads is what it may repeat to a user."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.config import SESSIONS_ROOT
from backend.services import session_store, text_similarity
from backend.services.agent.labels import CONDITION_LABEL, RULE_LABEL, rule_label
from backend.services.agent.records import latest_briefing
from backend.storage.config_loader import get_glossary, get_ruleset, latest_glossary_version

EXCERPT_CHARS = 80
SEARCH_HIT_LIMIT = 10
SNIPPET_RADIUS = 40
HISTORY_HIT_LIMIT = 8
UNSTATED_REASON = "文件未載明"
# Below this, text_similarity.rank()/rank_against() drop a candidate as noise
# rather than a real (if weak) match — conservative on purpose: cutting only
# clearly-unrelated pages, not replacing the model's own judgment about a
# low-but-nonzero score.
SEARCH_SCORE_FLOOR = 0.05


def find_chain_for_session(session_id: str) -> dict | None:
    """The multi-version chain this comparison belongs to, if any — a chain
    is built out of ordinary pairwise sessions (chain.py), so membership is
    just "is this session one of its adjacent/anchor steps"."""
    if not SESSIONS_ROOT.exists():
        return None
    for chain_dir in sorted(SESSIONS_ROOT.iterdir()):
        manifest_path = chain_dir / "chain.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if session_id in {*manifest["adjacent_session_ids"], *manifest["anchor_session_ids"]}:
            series_path = chain_dir / "parameter_series.json"
            series = json.loads(series_path.read_text(encoding="utf-8")) if series_path.exists() else {}
            return {**manifest, "parameter_series": series}
    return None


def parameter_label(key: str) -> str:
    """`{heading}::{unit}` (a config-style key) → 「heading（unit）」 — the
    only form the model ever sees, so it can't echo the key to a reader."""
    heading, _, unit = key.partition("::")
    heading = heading.replace("_", " ")  # chain._slug() turned spaces into underscores
    return f"{heading}（{unit}）" if unit else heading


@dataclass
class SessionContext:
    """Everything the tools read, loaded once per agent run so a run sees one
    consistent snapshot even if the reviewer keeps working meanwhile."""

    session: dict
    pages: dict[str, list[dict]]
    chain: dict | None = None
    # Lazily built, reused across every search_text call in this run (a run
    # can call tools up to RunLimits.max_tool_calls times — runner.py) rather
    # than re-fitting a TF-IDF corpus over the whole document per query. Keyed
    # by side so "old"/"new"/both reuse the same fitted corpus regardless of
    # which combination a given call asks for. pages.json is write-once
    # (session_store.py) so nothing here can go stale within a run's lifetime.
    _search_index: dict[str, tuple[text_similarity.Corpus, list[text_similarity.Vector]]] = field(
        default_factory=dict, repr=False, compare=False
    )

    def _page_search_index(self, side: str) -> tuple[text_similarity.Corpus, list[text_similarity.Vector]]:
        if side not in self._search_index:
            texts = [p.get("text") or "" for p in self.pages.get(side, [])]
            corpus = text_similarity.fit_corpus(texts)
            vectors = [text_similarity.vectorize(t, corpus) for t in texts]
            self._search_index[side] = (corpus, vectors)
        return self._search_index[side]

    @classmethod
    def load(cls, session_id: str) -> "SessionContext | None":
        session = session_store.get_session(session_id)
        pages = session_store.get_pages(session_id)
        if session is None or pages is None:
            return None
        return cls(
            session=session,
            pages={"old": pages.get("old", []), "new": pages.get("new", [])},
            chain=find_chain_for_session(session_id),
        )

    @property
    def session_id(self) -> str:
        return self.session["session_id"]

    def version_location(self, version: str) -> tuple[str, str]:
        """Where a chain version's pages can be read (and cited): v1 is the
        old side of the first adjacent step, every later version the new
        side of the step that produced it."""
        if self.chain is None:
            raise ToolInputError("這次比對不屬於任何多版本鏈，無法追溯其他版本。")
        versions = self.chain["ordered_versions"]
        if version not in versions:
            raise ToolInputError(f"鏈中沒有版本 {version}；可用版本：{'、'.join(versions)}。")
        index = versions.index(version)
        adjacent = self.chain["adjacent_session_ids"]
        return (adjacent[0], "old") if index == 0 else (adjacent[index - 1], "new")

    @property
    def differences(self) -> list[dict]:
        return self.session["differences"]

    def difference(self, difference_id: str) -> dict | None:
        return next((d for d in self.differences if d["id"] == difference_id), None)

    def page(self, side: str, pdf_page: int) -> dict | None:
        return next((p for p in self.pages.get(side, []) if p.get("pdf_page") == pdf_page), None)

    def scanned(self, side: str) -> list[int]:
        return list(self.session.get(f"scanned_{side}") or [])


class ToolInputError(ValueError):
    """Bad arguments from the model — returned to it as an error result so it
    can correct itself, never raised to the user."""


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _excerpt(text: str | None) -> str | None:
    if not text:
        return None
    return text if len(text) <= EXCERPT_CHARS else text[:EXCERPT_CHARS] + "…"


def _span(span: dict | None, *, full: bool) -> dict | None:
    if not span:
        return None
    page = span.get("page") or {}
    return {
        "pdf_page": page.get("pdf_page"),
        "print_label": page.get("print_label"),
        "text": span.get("text") if full else _excerpt(span.get("text")),
    }


def _verdict(ctx: SessionContext, difference_id: str) -> str | None:
    return (ctx.session.get("review_state", {}).get(difference_id) or {}).get("human_verdict")


def get_session_overview(ctx: SessionContext) -> str:
    diffs = ctx.differences
    unreviewed_high = [d["id"] for d in session_store.unreviewed_high_differences(ctx.session)]

    def meta(side: str) -> dict:
        m = ctx.session[f"{side}_meta"]
        return {
            "title": m.get("title"),
            "version": m.get("version"),
            "date": m.get("date"),
            "applicable_equipment": m.get("applicable_equipment"),
            "page_count": m.get("page_count"),
            "missing_fields": m.get("missing_fields", []),
            "scanned_pages": ctx.scanned(side),
        }

    return _dump(
        {
            "old": meta("old"),
            "new": meta("new"),
            "difference_count": len(diffs),
            "by_risk": dict(Counter(d["ai_risk"] for d in diffs)),
            "by_change_type": dict(Counter(d["change_type"] for d in diffs)),
            "sections": sorted({d["affected"] for d in diffs if d.get("affected")}),
            "unreviewed_high": unreviewed_high,
            "chain": {"versions": ctx.chain["ordered_versions"]} if ctx.chain else None,
        }
    )


def list_differences(ctx: SessionContext, risk: str | None = None, change_type: str | None = None, section: str | None = None) -> str:
    rows = []
    for d in ctx.differences:
        if risk and d["ai_risk"] != risk:
            continue
        if change_type and d["change_type"] != change_type:
            continue
        if section and section not in (d.get("affected") or ""):
            continue
        rows.append(
            {
                "id": d["id"],
                "risk": d["ai_risk"],
                "confidence": d.get("ai_confidence"),
                "change_type": d["change_type"],
                "kind": d.get("kind", "text"),
                "rule": rule_label(d.get("rule_id")),
                "section": d.get("affected"),
                "old": _span(d.get("old"), full=False),
                "new": _span(d.get("new"), full=False),
                "verdict": _verdict(ctx, d["id"]),
            }
        )
    return _dump({"count": len(rows), "differences": rows})


def get_difference(ctx: SessionContext, difference_id: str) -> str:
    d = ctx.difference(difference_id)
    if d is None:
        raise ToolInputError(f"沒有編號為 {difference_id} 的差異；請先用 list_differences 查看現有編號。")
    state = ctx.session.get("review_state", {}).get(difference_id) or {}
    out = {
        "id": d["id"],
        "risk": d["ai_risk"],
        "confidence": d.get("ai_confidence"),
        "change_type": d["change_type"],
        "kind": d.get("kind", "text"),
        "rule": rule_label(d.get("rule_id")),
        "explanation": d.get("explanation"),
        "recommended_action": d.get("recommended_action"),
        "section": d.get("affected"),
        "old": _span(d.get("old"), full=True),
        "new": _span(d.get("new"), full=True),
        "review": {"verdict": state.get("human_verdict"), "risk_override": state.get("risk_override")},
    }
    if d.get("ai_semantic_suggestion"):
        out["ai_semantic_suggestion"] = d["ai_semantic_suggestion"]
    if d.get("regions"):
        out["drawing_regions"] = [
            {"component_label": r.get("component_label"), "change_summary": r.get("change_summary"), "confidence": r.get("confidence")}
            for r in d["regions"]
        ]
    return _dump(out)


def read_page(ctx: SessionContext, side: str, pdf_page: int) -> str:
    if side not in ("old", "new"):
        raise ToolInputError("side 只能是 old 或 new。")
    page = ctx.page(side, pdf_page)
    if page is None:
        pages = [p.get("pdf_page") for p in ctx.pages.get(side, [])]
        raise ToolInputError(f"{side} 沒有第 {pdf_page} 頁；可用頁碼：{pages}。")
    return _dump(
        {
            "side": side,
            "pdf_page": pdf_page,
            "print_label": page.get("print_label"),
            "scanned": pdf_page in ctx.scanned(side),
            "text": page.get("text") or "",
        }
    )


def _snippet(text: str, needle_lower: str) -> str:
    """Precise, position-anchored snippet when the query is a literal
    substring (unchanged from the old behavior); otherwise a representative
    excerpt from the top of the page — there's no single "position" to
    anchor a snippet to for a similarity match, only a whole-page score."""
    at = text.lower().find(needle_lower)
    if at >= 0:
        start, end = max(0, at - SNIPPET_RADIUS), min(len(text), at + len(needle_lower) + SNIPPET_RADIUS)
        return text[start:end]
    return text[: 2 * SNIPPET_RADIUS]


def search_text(ctx: SessionContext, query: str, side: str = "both") -> str:
    """Ranked by similarity (text_similarity.rank_against), not substring
    position — a query phrased differently from the document's own wording
    can still find the right page, as long as it shares enough of the page's
    distinctive (rare, hence highly-weighted) vocabulary. A literal match
    still gets a precise, position-anchored snippet (see _snippet); a
    similarity-only match gets a representative excerpt plus `score` so the
    model can judge how confident the hit is."""
    needle = query.strip().lower()
    if not needle:
        raise ToolInputError("query 不可為空。")
    sides = ("old", "new") if side == "both" else (side,)
    hits = []
    for s in sides:
        pages = ctx.pages.get(s, [])
        corpus, vectors = ctx._page_search_index(s)
        ranked = text_similarity.rank_against(query, corpus, vectors, floor=SEARCH_SCORE_FLOOR)
        for idx, score in ranked:
            page = pages[idx]
            text = page.get("text") or ""
            hits.append(
                {
                    "side": s,
                    "pdf_page": page.get("pdf_page"),
                    "print_label": page.get("print_label"),
                    "snippet": _snippet(text, needle),
                    "score": round(score, 2),
                }
            )
    hits.sort(key=lambda h: h["score"], reverse=True)
    return _dump({"query": query, "hits": hits[:SEARCH_HIT_LIMIT], "truncated": len(hits) > SEARCH_HIT_LIMIT})


def get_parameter_trail(ctx: SessionContext, parameter: str | None = None) -> str:
    if ctx.chain is None:
        raise ToolInputError("這次比對不屬於任何多版本鏈，無法追溯各版本數值。")
    series: dict[str, list[dict]] = ctx.chain["parameter_series"]
    if parameter is None:
        return _dump(
            {
                "versions": ctx.chain["ordered_versions"],
                "parameters": [
                    {"parameter": parameter_label(k), "values": [f"{p['version']} {p['value']:g}{p['unit']}" for p in pts]}
                    for k, pts in series.items()
                ],
            }
        )
    key = next((k for k in series if parameter in (k, parameter_label(k))), None)
    if key is None:
        raise ToolInputError(f"找不到參數「{parameter}」；先不帶參數呼叫一次，查看可追溯的參數。")
    points = []
    for p in series[key]:
        session_id, side = ctx.version_location(p["version"])
        points.append(
            {
                "version": p["version"],
                "value": p["value"],
                "unit": p["unit"],
                "source_text": p["source_text"],
                "cite_as": {"session_id": session_id, "side": side, "pdf_page": p["pdf_page"]},
            }
        )
    return _dump({"parameter": parameter_label(key), "points": points})


def read_version_page(ctx: SessionContext, version: str, pdf_page: int) -> str:
    session_id, side = ctx.version_location(version)
    pages = (session_store.get_pages(session_id) or {}).get(side, [])
    page = next((p for p in pages if p.get("pdf_page") == pdf_page), None)
    if page is None:
        raise ToolInputError(f"{version} 沒有第 {pdf_page} 頁；可用頁碼：{[p.get('pdf_page') for p in pages]}。")
    return _dump(
        {
            "version": version,
            "pdf_page": pdf_page,
            "print_label": page.get("print_label"),
            "text": page.get("text") or "",
            "cite_as": {"session_id": session_id, "side": side, "pdf_page": pdf_page},
        }
    )


def search_history(ctx: SessionContext, query: str) -> str:
    """歷史案例: similar changes in *earlier* local comparisons (never this
    one). Local only — §30's corpus rule: no external class-society rules.

    Ranked by similarity (text_similarity.rank), not substring containment —
    same reasoning as search_text. Re-fits its corpus fresh on every call
    (unlike search_text, which caches per session): it scans a different set
    of past sessions' differences each time, so there's no stable per-run
    corpus worth caching here."""
    if not query.strip():
        raise ToolInputError("query 不可為空。")
    chain_members = set()
    if ctx.chain:
        chain_members = {*ctx.chain["adjacent_session_ids"], *ctx.chain["anchor_session_ids"]}
    candidates: list[str] = []
    records: list[tuple[dict, dict]] = []  # (past session, difference) per candidate, same index
    for past in session_store.list_sessions():
        if past["session_id"] == ctx.session_id:
            continue
        for d in past.get("differences", []):
            haystack = " ".join(filter(None, [(d.get("old") or {}).get("text"), (d.get("new") or {}).get("text"), d.get("affected")]))
            candidates.append(haystack)
            records.append((past, d))

    ranked = text_similarity.rank(query, candidates, floor=SEARCH_SCORE_FLOOR)
    hits = []
    for idx, score in ranked[:HISTORY_HIT_LIMIT]:
        past, d = records[idx]
        state = past.get("review_state", {})
        hits.append(
            {
                "session_id": past["session_id"],
                "title": past.get("title"),
                "versions": f"{past['old_meta'].get('version') or '?'} → {past['new_meta'].get('version') or '?'}",
                "created_at": past.get("created_at"),
                "same_chain": past["session_id"] in chain_members,
                "difference_id": d["id"],
                "risk": d["ai_risk"],
                "change_type": d["change_type"],
                "rule": rule_label(d.get("rule_id")),
                "old": _span(d.get("old"), full=True),
                "new": _span(d.get("new"), full=True),
                "verdict": (state.get(d["id"]) or {}).get("human_verdict"),
                "score": round(score, 2),
            }
        )
    return _dump({"query": query, "hits": hits, "truncated": len(ranked) > HISTORY_HIT_LIMIT})


CONTEXT_CHAR_BUDGET = 30_000
_RISK_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def question_context(ctx: SessionContext) -> str:
    """Handed to every question up front (runs.py), so an overview-type
    question — 「如果我只有五分鐘…」 — can be answered from what's already in
    the prompt instead of a long tool hunt: the session overview plus every
    difference with its full old/new text, High first, until the character
    budget runs out. Ids that didn't fit are listed so the model knows to
    fetch them with get_difference. Same data the tools return, so quotes
    taken from it pass verification."""
    rows: list[dict] = []
    left_out: list[str] = []
    used = 0
    for d in sorted(ctx.differences, key=lambda d: _RISK_ORDER.get(d["ai_risk"], 3)):
        row = {
            "id": d["id"],
            "risk": d["ai_risk"],
            "change_type": d["change_type"],
            "rule": rule_label(d.get("rule_id")),
            "section": d.get("affected"),
            "old": _span(d.get("old"), full=True),
            "new": _span(d.get("new"), full=True),
            "verdict": _verdict(ctx, d["id"]),
        }
        size = len(_dump(row))
        if used + size > CONTEXT_CHAR_BUDGET:
            left_out.append(d["id"])
            continue
        rows.append(row)
        used += size
    return _dump({"overview": json.loads(get_session_overview(ctx)), "differences": rows, "not_included": left_out})


def _as_citation(c: dict) -> dict:
    """A verified briefing citation, in the shape an answer's citations take
    ("" = this comparison / no difference) — the quote is already checked."""
    return {
        "session_id": c.get("session_id") or "",
        "difference_id": c.get("difference_id") or "",
        "side": c["side"],
        "pdf_page": c["pdf_page"],
        "quote": c["quote"],
    }


def get_briefing(ctx: SessionContext) -> str:
    """Q&A only: the latest finished 覆核簡報 of this comparison, so a
    question about its advice (which differences to 停用舊版, what to look at
    first) can be answered. Everything in it is the agent's earlier ADVICE,
    already verified (verify.py) — not something the documents say; the
    answer prompt makes the model say so, and runs.py flags the answer."""
    record = latest_briefing(ctx.session_id)
    if record is None or not record.get("result"):
        return _dump({"briefing": None, "note": "這次比對還沒有覆核簡報。"})
    r = record["result"]
    return _dump(
        {
            "note": "以下是覆核簡報裡 AI 的建議，不是文件規定。citations 都已逐字核對過原文，可以照抄沿用。",
            "summary": r.get("summary"),
            "priority": [{"difference_id": p["difference_id"], "reason": p["reason"], "citations": [_as_citation(c) for c in p["citations"]]} for p in r.get("priority", [])],
            "items": [
                {
                    "difference_ids": it["difference_ids"],
                    "action": it["action"],
                    "action_detail": it["action_detail"],
                    "impact": it["impact"],
                    "citations": [_as_citation(c) for c in it["citations"]],
                }
                for it in r.get("items", [])
            ],
            "suggestions": [
                {"difference_id": s["difference_id"], "verdict": s["verdict"], "reason": s["reason"], "citations": [_as_citation(c) for c in s["citations"]]}
                for s in r.get("suggestions", [])
            ],
            "cause_trace": [
                {"parameter": t["parameter"], "changed_in_version": t["changed_in_version"], "reason": t["reason"], "citations": [_as_citation(c) for c in t["citations"]]}
                for t in r.get("cause_trace", [])
            ],
        }
    )


def _describe_condition(when: dict) -> list[str]:
    parts = []
    for key, value in when.items():
        label = CONDITION_LABEL.get(key, key)
        if isinstance(value, bool):
            parts.append(label if value else f"不{label}")
        elif isinstance(value, list):
            parts.append(f"{label}：{'、'.join(CONDITION_LABEL.get(v, v) for v in value)}")
        else:
            parts.append(f"{label} {value}")
    return parts or ["沒有其他規則符合時套用"]


def explain_rule(ctx: SessionContext, rule: str) -> str:
    ruleset = get_ruleset(ctx.session["ruleset_version"])
    by_label = {label: rule_id for rule_id, label in RULE_LABEL.items()}
    rule_id = by_label.get(rule, rule)
    match = next((r for r in ruleset.rules if r.id == rule_id), None)
    if match is None:
        raise ToolInputError(f"找不到規則「{rule}」；可用規則：{'、'.join(RULE_LABEL.values())}。")
    then = match.then
    return _dump(
        {
            "rule": rule_label(match.id),
            "conditions": _describe_condition(match.when),
            "default_risk": then.get("risk"),
            "confidence": then.get("confidence"),
            "rationale": then.get("rationale"),
            "recommended_action": then.get("recommended_action"),
        }
    )


def lookup_glossary(ctx: SessionContext, term: str) -> str:
    version = latest_glossary_version()
    if version is None:
        return _dump({"term": term, "found": False, "reason": "目前沒有詞彙表，名詞一律列入待確認。"})
    table = get_glossary(version)
    if table.status != "approved":
        return _dump({"term": term, "found": False, "reason": "詞彙表尚未經人工核准，名詞一律列入待確認。"})
    for entry in table.terms:
        if term == entry.term or term in entry.aliases:
            if entry.status != "approved":
                return _dump({"term": term, "found": False, "reason": "這個名詞的定義還沒定案，列入待確認。"})
            found = {"term": entry.term, "found": True, "definition": entry.definition}
            if table.simulated:
                found["note"] = "模擬版詞彙表的定義，尚未經專業人員審核。"
            return _dump(found)
    return _dump({"term": term, "found": False, "reason": "詞彙表沒有這個名詞，列入待確認。"})


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    run: Callable[..., str]
    step_label: Callable[[dict], str] = field(default=lambda _args: "")

    @property
    def definition(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


def _object(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


SIDE_SCHEMA = {"type": "string", "enum": ["old", "new"], "description": "old＝舊版文件，new＝新版文件"}

TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="get_session_overview",
        description="讀取這次比對的概況：兩份文件的名稱、版本、日期、適用設備、缺漏欄位、疑似掃描頁、差異統計，以及還沒標為「已確認」的 High。每次工作先呼叫一次。",
        input_schema=_object({}, []),
        run=get_session_overview,
        step_label=lambda _a: "讀取比對概況",
    ),
    ToolSpec(
        name="list_differences",
        description="列出差異清單（只含摘要）。可依風險等級、變更類型或章節篩選。要看完整原文請用 get_difference。",
        input_schema=_object(
            {
                "risk": {"type": "string", "enum": ["High", "Medium", "Low"]},
                "change_type": {"type": "string", "enum": ["新增", "刪除", "修改"]},
                "section": {"type": "string", "description": "章節標題中的文字"},
            },
            [],
        ),
        run=list_differences,
        step_label=lambda a: "列出差異" + (f"（{a['risk']}）" if a.get("risk") else ""),
    ),
    ToolSpec(
        name="get_difference",
        description="讀取一筆差異的完整內容：新舊原文、雙頁碼、觸發規則、建議處置、目前的覆核狀態。",
        input_schema=_object({"difference_id": {"type": "string", "description": "例如 D01"}}, ["difference_id"]),
        run=get_difference,
        step_label=lambda a: f"讀取 {a.get('difference_id', '')}",
    ),
    ToolSpec(
        name="read_page",
        description="讀取某一版某一頁的完整文字，用來看差異的前後文。引用原文時，quote 必須逐字取自這裡或 get_difference 的文字。",
        input_schema=_object({"side": SIDE_SCHEMA, "pdf_page": {"type": "integer", "description": "PDF 頁碼（第幾頁）"}}, ["side", "pdf_page"]),
        run=read_page,
        step_label=lambda a: f"翻閱{'舊' if a.get('side') == 'old' else '新'}版 p.{a.get('pdf_page', '?')}",
    ),
    ToolSpec(
        name="search_text",
        description="在兩版（或指定一版）的全部頁面中搜尋文字，回傳命中的頁碼與前後片段。",
        input_schema=_object(
            {"query": {"type": "string"}, "side": {"type": "string", "enum": ["old", "new", "both"]}},
            ["query"],
        ),
        run=search_text,
        step_label=lambda a: f"搜尋「{a.get('query', '')}」",
    ),
    ToolSpec(
        name="explain_rule",
        description="說明一條分級規則的觸發條件、預設風險、理由與建議處置。可傳規則中文名。",
        input_schema=_object({"rule": {"type": "string", "description": "規則中文名，例如「數值變更 + 安全關鍵詞」"}}, ["rule"]),
        run=explain_rule,
        step_label=lambda a: f"查規則「{a.get('rule', '')}」",
    ),
    ToolSpec(
        name="get_parameter_trail",
        description="多版本鏈專用：不帶參數時列出可追溯的參數與各版數值；帶參數時回傳該參數在每一版的數值、原文句與引用位置（cite_as）。這次比對不屬於任何鏈時會回報錯誤。",
        input_schema=_object({"parameter": {"type": "string", "description": "參數名稱，照不帶參數時回傳的寫法"}}, []),
        run=get_parameter_trail,
        step_label=lambda a: f"追溯「{a['parameter']}」各版本數值" if a.get("parameter") else "列出可追溯的參數",
    ),
    ToolSpec(
        name="read_version_page",
        description="多版本鏈專用：讀取某一版某一頁的完整文字（例如版本異動摘要頁，找修訂原因）。引用時用回傳的 cite_as。",
        input_schema=_object(
            {"version": {"type": "string", "description": "例如 v1.2"}, "pdf_page": {"type": "integer"}},
            ["version", "pdf_page"],
        ),
        run=read_version_page,
        step_label=lambda a: f"翻閱 {a.get('version', '?')} p.{a.get('pdf_page', '?')}",
    ),
    ToolSpec(
        name="search_history",
        description="在本機過去的其他比對中搜尋相似的變更（歷史案例），回傳比對編號、版本、差異原文與當時的人工判定。引用時 session_id 填該比對的編號。",
        input_schema=_object({"query": {"type": "string", "description": "要找的文字，例如「料號」「溫度」"}}, ["query"]),
        run=search_history,
        step_label=lambda a: f"搜尋歷史比對「{a.get('query', '')}」",
    ),
    ToolSpec(
        name="lookup_glossary",
        description="查受控詞彙表裡某個名詞的定義。查不到或詞彙表未核准時，該名詞必須列入待確認，不可自行下定義。",
        input_schema=_object({"term": {"type": "string"}}, ["term"]),
        run=lookup_glossary,
        step_label=lambda a: f"查名詞「{a.get('term', '')}」",
    ),
]

# Q&A gets one more tool than the briefing: reading the latest briefing's
# advice. The briefing itself never sees an older briefing.
GET_BRIEFING = ToolSpec(
    name="get_briefing",
    description="讀取這次比對最新的覆核簡報（AI 的建議：優先順序、影響範圍、建議動作、建議判定、變更原因追溯）。只在問題問到簡報的建議時使用；回答必須寫明這是 AI 建議、不是文件規定。",
    input_schema=_object({}, []),
    run=get_briefing,
    step_label=lambda _a: "讀取覆核簡報",
)
QUESTION_TOOLS: list[ToolSpec] = [*TOOLS, GET_BRIEFING]

TOOLS_BY_NAME = {t.name: t for t in QUESTION_TOOLS}


def run_tool(ctx: SessionContext, name: str, arguments: dict) -> str:
    spec = TOOLS_BY_NAME.get(name)
    if spec is None:
        raise ToolInputError(f"沒有名為 {name} 的工具。")
    allowed = set(spec.input_schema["properties"])
    unknown = set(arguments) - allowed
    if unknown:
        raise ToolInputError(f"{name} 不接受參數：{'、'.join(sorted(unknown))}。")
    missing = [key for key in spec.input_schema["required"] if key not in arguments]
    if missing:
        raise ToolInputError(f"{name} 缺少參數：{'、'.join(missing)}。")
    return spec.run(ctx, **arguments)
