"""What the model must hand back (spec §4.3–§4.6), defined once as Pydantic
models and turned into the strict JSON Schema that `output_config.format`
takes — so the schema the API enforces and the validation we run afterwards
can't drift apart.

These are the model's *raw* claims. None of it reaches a user until
verify.py has checked every citation against the page text, every number
against the cited quotes, and every glossary term against the reviewed
glossary; anything that fails moves to `pending` (待確認)."""

from __future__ import annotations

import copy
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, WithJsonSchema


def _blank_to_none(value: object) -> object:
    return None if value == "" else value


# An id that may be absent, sent to the model as a plain string where ""
# means "none" and read back here as None. Not `str | None`: every nullable
# field becomes an anyOf union — the most expensive thing to compile — and
# Citation's two were inlined at every one of its uses.
OptionalId = Annotated[str | None, BeforeValidator(_blank_to_none), WithJsonSchema({"type": "string"})]

Side = Literal["old", "new"]
Action = Literal["重新檢查", "補充測試", "停用舊版", "更新文件", "僅存檔"]
Confidence = Literal["high", "medium", "low"]
# Same three the ReviewBar offers; FALSE_POSITIVE has no control in the UI.
SuggestedVerdict = Literal["CONFIRMED", "TRACK", "REJECTED"]


class Citation(BaseModel):
    # "" (None here) = this comparison. Another comparison's id when quoting
    # an earlier version in a chain or a historical case (search_history) —
    # verify.py checks the quote against *that* comparison's pages.
    session_id: OptionalId
    difference_id: OptionalId
    side: Side
    pdf_page: int
    # Verbatim from that page's text — verify.py rejects anything else.
    quote: str


class BriefingWarning(BaseModel):
    # missing_metadata is not here on purpose: the server builds those from
    # the extracted document info itself, so they can't be invented or missed.
    kind: Literal["low_confidence", "unsupported", "suspicious_instruction"]
    message: str
    citations: list[Citation]


class PriorityItem(BaseModel):
    difference_id: str
    reason: str
    citations: list[Citation]


class Impact(BaseModel):
    equipment: list[str]
    parts: list[str]
    procedures: list[str]
    inspections: list[str]


class BriefingItem(BaseModel):
    difference_ids: list[str]
    impact: Impact
    action: Action
    action_detail: str
    confidence: Confidence
    citations: list[Citation]


class VerdictSuggestion(BaseModel):
    difference_id: str
    verdict: SuggestedVerdict
    reason: str
    citations: list[Citation]


class CauseTrace(BaseModel):
    """變更原因追溯 (bonus item): in which version a parameter changed and
    why — the reason only as the documents state it, else 「文件未載明」."""

    parameter: str
    changed_in_version: str
    reason: str
    citations: list[Citation]


class HistoryCase(BaseModel):
    """歷史案例 (bonus item): a similar change in an earlier local comparison."""

    session_id: str
    difference_id: str
    note: str
    citations: list[Citation]


class PendingItem(BaseModel):
    topic: str
    reason: str


# The briefing is written by two conversations running side by side: the
# body, and the bonus items (BriefingExtras). One schema holding all of it
# compiled to a structured-output grammar over the API's limit (400 "The
# compiled grammar is too large", even with no union types left); each half
# alone compiles. ReviewBriefing is the two merged — what verify.py checks —
# and is never sent to the API as a schema.


class BriefingBody(BaseModel):
    summary: str
    warnings: list[BriefingWarning]
    priority: list[PriorityItem]
    items: list[BriefingItem]
    suggestions: list[VerdictSuggestion]
    pending: list[PendingItem]
    # Terms the reader may need explained. The model only names them — the
    # definitions come from the reviewed glossary, never from the model.
    glossary_terms: list[str]


class BriefingExtras(BaseModel):
    cause_trace: list[CauseTrace]
    history: list[HistoryCase]
    pending: list[PendingItem]
    glossary_terms: list[str]


class ReviewBriefing(BriefingBody):
    cause_trace: list[CauseTrace]
    history: list[HistoryCase]


def merge_briefing(body: BriefingBody, extras: BriefingExtras) -> ReviewBriefing:
    fields = dict(body)
    fields["pending"] = [*body.pending, *extras.pending]
    fields["glossary_terms"] = list(dict.fromkeys([*body.glossary_terms, *extras.glossary_terms]))
    return ReviewBriefing(**fields, cause_trace=extras.cause_trace, history=extras.history)


class AgentAnswer(BaseModel):
    answer_type: Literal["answer", "not_in_documents", "out_of_scope"]
    text: str
    citations: list[Citation]
    pending: list[PendingItem]
    glossary_terms: list[str]


def strict_json_schema(model: type[BaseModel]) -> dict:
    """Pydantic's schema, tightened to what structured outputs require: every
    object closed (`additionalProperties: false`) with every property
    required, and no `title`/`default` noise. Optional values stay
    expressible as `anyOf [..., null]`."""
    schema = copy.deepcopy(model.model_json_schema())

    def tighten(node: object) -> None:
        if isinstance(node, dict):
            node.pop("title", None)
            node.pop("default", None)
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for value in node.values():
                tighten(value)
        elif isinstance(node, list):
            for value in node:
                tighten(value)

    tighten(schema)
    return schema
