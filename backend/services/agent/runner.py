"""The agent loop (spec §4.8). A hand-written loop over the stable Messages
API rather than the SDK's beta tool runner, for three things this feature
needs on every turn: a hard cap on tool calls and wall time, a progress
step the UI can poll after each tool call, and a fake client in tests that
never touches the network.

Each request: adaptive thinking at effort `medium`; the final answer
constrained by `output_config.format` (the model reads with tools, then
answers in schema-valid JSON); a cache breakpoint on the stable system
prompt (tools + system are the reused prefix across runs) plus automatic
caching for the growing conversation; and server-side `fallbacks: "default"`
so a safety-classifier decline is retried on Anthropic's recommended
fallback model instead of failing the run."""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from backend.services.agent.schemas import strict_json_schema
from backend.services.agent.tools import TOOLS, TOOLS_BY_NAME, SessionContext, ToolInputError, run_tool

MODEL_ID = "claude-opus-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000
LIMIT_NOTICE = "已達工具呼叫上限。請立即根據目前已取得的資料輸出結果，資料不足的部分放進 pending。"
FORMAT_NUDGE = "請依規定的格式輸出結果。"


class AgentError(Exception):
    """A failure the reviewer should see, worded for them (繁體中文)."""


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


def _add_usage(total: Counter[str], usage: Any) -> None:
    for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        total[key] += getattr(usage, key, None) or 0


def _final_text(content: list[Any]) -> str | None:
    texts = [b.text for b in content if getattr(b, "type", None) == "text" and getattr(b, "text", "").strip()]
    return texts[-1] if texts else None


def run_loop(
    client: Any,
    *,
    system: str,
    user_content: str,
    ctx: SessionContext,
    output_model: type[BaseModel],
    limits: RunLimits,
    on_step: Callable[[Step], None] = lambda _step: None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[BaseModel, LoopResult]:
    schema = strict_json_schema(output_model)
    tools = [t.definition for t in TOOLS]
    messages: list[dict] = [{"role": "user", "content": user_content}]
    result = LoopResult()
    started = clock()
    tool_calls = 0
    turns_over_limit = 0
    nudged = False

    while True:
        if clock() - started > limits.max_seconds:
            raise AgentError("Agent 執行超過時間上限，請再試一次。")

        response = client.beta.messages.create(
            model=MODEL_ID,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=tools,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            cache_control={"type": "ephemeral"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        _add_usage(result.usage, response.usage)
        result.model = getattr(response, "model", None) or result.model
        stop = response.stop_reason

        if stop == "refusal":
            raise AgentError("AI 服務拒絕處理這次請求。")
        if stop == "max_tokens":
            raise AgentError("AI 的輸出超過長度上限，請再試一次。")

        if stop == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            rejected_for_limit = False
            for block in (b for b in response.content if getattr(b, "type", None) == "tool_use"):
                if tool_calls >= limits.max_tool_calls:
                    rejected_for_limit = True
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": LIMIT_NOTICE, "is_error": True})
                    continue
                tool_calls += 1
                arguments = dict(block.input or {})
                spec = TOOLS_BY_NAME.get(block.name)
                label = spec.step_label(arguments) if spec else block.name
                try:
                    content, ok = run_tool(ctx, block.name, arguments), True
                except ToolInputError as exc:
                    content, ok = str(exc), False
                step = Step(label=label, tool=block.name, input=arguments, ok=ok)
                result.steps.append(step)
                on_step(step)
                entry = {"type": "tool_result", "tool_use_id": block.id, "content": content}
                if not ok:
                    entry["is_error"] = True
                tool_results.append(entry)
            if rejected_for_limit:
                turns_over_limit += 1
                if turns_over_limit > 1:
                    raise AgentError("Agent 查證的步驟超過上限，請再試一次。")
            messages.append({"role": "user", "content": tool_results})
            continue

        if stop == "end_turn":
            text = _final_text(response.content)
            if text is None:
                if nudged:
                    raise AgentError("AI 沒有輸出結果，請再試一次。")
                nudged = True
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": FORMAT_NUDGE})
                continue
            try:
                return output_model.model_validate(json.loads(text)), result
            except (json.JSONDecodeError, ValidationError) as exc:
                raise AgentError("AI 的輸出格式不符，請再試一次。") from exc

        raise AgentError("AI 服務回傳了無法處理的結果，請再試一次。")
