"""The agent loop (spec §4.8). Hand-written rather than an SDK tool runner,
for three things this feature needs on every turn: a hard cap on tool calls
and wall time, a progress step the UI can poll after each tool call, and a
fake client in tests that never touches the network.

The loop itself is provider-neutral. Each AI backend (anthropic_backend.py
for Claude on the Claude API or on Bedrock, gemini_backend.py,
converse_backend.py for Amazon Nova) supplies a `Conversation` that sends
one turn and appends tool results in its own wire format; everything that
decides what the reviewer gets — limits, steps, nudges, validation — lives
here once.

The final answer arrives one of two ways. On the Claude API it is the turn's
text, constrained by `output_config.format`. Elsewhere structured output
can't be relied on (Bedrock's Claude endpoint lists it as unsupported, and
Gemini/Nova would each need their own schema dialect), so the backend adds a
`submit_result` tool whose input schema is the answer schema, and the model
hands its result in as that tool call — validated here like any other.

`review`, when given, sees each schema-valid answer before it is accepted
and may hand back one problem (a number not in its quotes, a quote not in
the document) for the model to fix — once. Q&A uses it so a single slip
doesn't throw away an otherwise supported answer; verify.py still has the
final say on whatever comes back."""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, ValidationError

from backend.services.agent.schemas import strict_json_schema
from backend.services.agent.tools import TOOLS, TOOLS_BY_NAME, SessionContext, ToolInputError, ToolSpec, run_tool

MODEL_ID = "claude-opus-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000
LIMIT_NOTICE = "已達工具呼叫上限。請立即根據目前已取得的資料輸出結果，資料不足的部分放進 pending。"
FORMAT_NUDGE = "請依規定的格式輸出結果。"
SUBMIT_TOOL = "submit_result"
SUBMIT_DESCRIPTION = "查證完成後，呼叫這個工具交出最終結果。只呼叫一次，參數就是完整的結果。"
SUBMIT_NUDGE = f"請呼叫 {SUBMIT_TOOL} 工具交出結果。"
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
# How hard the model thinks — each backend maps it to its own knob (Claude
# `effort`, Gemini `thinking_level`, Nova `maxReasoningEffort`). The briefing
# runs at medium; Q&A at low, since its context is handed over up front and
# a reviewer is waiting on the answer (2026-10-02: 30–50 s, mostly reasoning).
Effort = Literal["low", "medium"]


class AgentError(Exception):
    """A failure the reviewer should see, worded for them (繁體中文)."""


class AgentApiError(AgentError):
    """The AI service itself refused or failed the request. `str()` is the
    reviewer-facing wording; `detail` is the service's own message, for the
    log only — it can name parameters, billing state and the like."""

    def __init__(self, message: str, *, detail: str):
        super().__init__(message)
        self.detail = detail


@dataclass(frozen=True)
class RunLimits:
    max_tool_calls: int
    max_seconds: float


@dataclass
class Step:
    label: str
    tool: str
    input: dict
    ok: bool

    def as_dict(self) -> dict:
        return {"label": self.label, "tool": self.tool, "input": self.input, "ok": self.ok}


@dataclass
class LoopResult:
    steps: list[Step] = field(default_factory=list)
    usage: Counter[str] = field(default_factory=Counter)
    model: str | None = None


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Turn:
    """One model response, normalized. `stop` is one of "end_turn",
    "tool_use", "refusal", "max_tokens" or the provider's own value for
    anything else; `raw` is the provider's message, for the Conversation to
    append back verbatim (thinking blocks / thought signatures included)."""

    stop: str
    calls: list[ToolCall]
    text: str | None
    usage: dict[str, int]
    model: str | None
    raw: Any = None


ToolAnswer = tuple[ToolCall, str, bool]  # (call, content, ok)


class Conversation(Protocol):
    def send(self) -> Turn: ...

    def answer_tools(self, turn: Turn, answers: list[ToolAnswer]) -> None: ...

    def nudge(self, turn: Turn, text: str) -> None: ...


class AgentBackend(Protocol):
    provider: str
    model: str
    submits_by_tool: bool

    def start(
        self, *, system: str, user_content: str, output_model: type[BaseModel], tools: list[ToolSpec], effort: Effort
    ) -> Conversation: ...


def request_params(system: str, messages: list[dict], schema: dict, tools: list[ToolSpec] = TOOLS, effort: Effort = "medium") -> dict:
    """One agent request on the Claude API, as passed to
    client.beta.messages.create — shared with test_agent_live_schema.py so
    the live check sends exactly this."""
    return dict(
        model=MODEL_ID,
        max_tokens=MAX_TOKENS,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        tools=[t.definition for t in tools],
        messages=messages,
        thinking={"type": "adaptive"},
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        cache_control={"type": "ephemeral"},
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )


def submit_tool_schema(output_model: type[BaseModel]) -> dict:
    return strict_json_schema(output_model)


def _submit_problem(exc: ValidationError) -> str:
    problems = [f"{'.'.join(str(p) for p in e['loc'])}：{e['msg']}" for e in exc.errors()[:5]]
    return f"結果格式不符，請修正後再呼叫 {SUBMIT_TOOL}：" + "；".join(problems)


def run_loop(
    backend: AgentBackend,
    *,
    system: str,
    user_content: str,
    ctx: SessionContext,
    output_model: type[BaseModel],
    limits: RunLimits,
    tools: list[ToolSpec] = TOOLS,
    effort: Effort = "medium",
    review: Callable[[BaseModel], str | None] | None = None,
    on_step: Callable[[Step], None] = lambda _step: None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[BaseModel, LoopResult]:
    conversation = backend.start(system=system, user_content=user_content, output_model=output_model, tools=tools, effort=effort)
    result = LoopResult()
    started = clock()
    tool_calls = 0
    turns_over_limit = 0
    nudged = False
    bad_submits = 0
    reviewed = False

    def review_problem(candidate: BaseModel) -> str | None:
        nonlocal reviewed
        if review is None or reviewed:
            return None
        problem = review(candidate)
        reviewed = problem is not None
        return problem

    while True:
        if clock() - started > limits.max_seconds:
            raise AgentError("Agent 執行超過時間上限，請再試一次。")

        turn = conversation.send()
        result.usage.update({k: turn.usage.get(k, 0) for k in USAGE_KEYS})
        result.model = turn.model or result.model

        if turn.stop == "refusal":
            raise AgentError("AI 服務拒絕處理這次請求。")
        if turn.stop == "max_tokens":
            raise AgentError("AI 的輸出超過長度上限，請再試一次。")

        submit = next((c for c in turn.calls if c.name == SUBMIT_TOOL), None)
        submit_problem = None
        if submit is not None:
            try:
                candidate = output_model.model_validate(submit.arguments)
            except ValidationError as exc:
                bad_submits += 1
                if bad_submits > 1:
                    raise AgentError("AI 的輸出格式不符，請再試一次。") from exc
                submit_problem = _submit_problem(exc)
            else:
                submit_problem = review_problem(candidate)
                if submit_problem is None:
                    return candidate, result

        if turn.calls:
            answers: list[ToolAnswer] = []
            rejected_for_limit = False
            for call in turn.calls:
                if call is submit:
                    answers.append((call, submit_problem or "", False))
                    continue
                if tool_calls >= limits.max_tool_calls:
                    rejected_for_limit = True
                    answers.append((call, LIMIT_NOTICE, False))
                    continue
                tool_calls += 1
                spec = TOOLS_BY_NAME.get(call.name)
                label = spec.step_label(call.arguments) if spec else call.name
                try:
                    content, ok = run_tool(ctx, call.name, call.arguments), True
                except ToolInputError as exc:
                    content, ok = str(exc), False
                step = Step(label=label, tool=call.name, input=call.arguments, ok=ok)
                result.steps.append(step)
                on_step(step)
                answers.append((call, content, ok))
            if rejected_for_limit:
                turns_over_limit += 1
                if turns_over_limit > 1:
                    raise AgentError("Agent 查證的步驟超過上限，請再試一次。")
            conversation.answer_tools(turn, answers)
            continue

        if turn.stop == "end_turn":
            if turn.text is not None:
                try:
                    candidate = output_model.model_validate(json.loads(turn.text))
                except (json.JSONDecodeError, ValidationError) as exc:
                    # With a submit tool, text is the model talking, not its
                    # answer — ask for the tool call instead of failing.
                    if not backend.submits_by_tool:
                        raise AgentError("AI 的輸出格式不符，請再試一次。") from exc
                else:
                    problem = review_problem(candidate)
                    if problem is None:
                        return candidate, result
                    conversation.nudge(turn, problem)
                    continue
            if nudged:
                raise AgentError("AI 沒有輸出結果，請再試一次。")
            nudged = True
            conversation.nudge(turn, SUBMIT_NUDGE if backend.submits_by_tool else FORMAT_NUDGE)
            continue

        raise AgentError("AI 服務回傳了無法處理的結果，請再試一次。")
