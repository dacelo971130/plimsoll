"""LLM baselines for the accuracy benchmark: give each vendor's flagship
model the same two documents and the same fixed prompt
(data/benchmark/templates/llm_prompt.md) through its API, and write what
comes back as an ordinary result CSV — scored by scripts/accuracy_bench.py
exactly like every other tool. This is the "why not just ask an AI" answer.

What it measures, on purpose: each model's own comparison ability given
identical input. Every model gets the PDF text layer (PyMuPDF, page by
page, with page markers), not the PDF file — native PDF input would also
send a page image per page (a 362-page pair would crowd a 1M window) and
make the comparison about each vendor's PDF parser instead of the model.
The chat products (chatgpt / gemini / claude-ai in competitors.json) stay
separate entries, run by a person through the real upload UI.

Same protocol as a person following llm_prompt.md: one request, and only
when the output was cut off by the output-token cap, up to two "請繼續列完"
follow-ups. Reasoning effort is "high" on all three. Claude's server-side
refusal fallback is deliberately not enabled: a fallback would answer with
a different model and the result would no longer be Claude Opus 5.5's.

Spends real money (see --estimate). A (case, model) pair that already has
a dated result is skipped unless --force, so a re-run never pays twice.
Keys come from the environment or a gitignored .env at the repo root:
ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY.

    python3 scripts/llm_baseline.py --estimate      # no model call
    python3 scripts/llm_baseline.py --case demo-cooling-v1.0-v1.1
    python3 scripts/llm_baseline.py --budget 40
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_FILE = REPO_ROOT / "data" / "benchmark" / "templates" / "llm_prompt.md"
EFFORT = "high"
CONTINUE = "請繼續列完"
MAX_CONTINUES = 2

_spec = importlib.util.spec_from_file_location("accuracy_bench", REPO_ROOT / "scripts" / "accuracy_bench.py")
bench = importlib.util.module_from_spec(_spec)
sys.modules["accuracy_bench"] = bench
_spec.loader.exec_module(bench)


@dataclass(frozen=True)
class Model:
    tool: str  # results/<case>/<tool>.csv
    display_name: str
    vendor: str
    model: str
    key_env: str
    max_output: int
    price: tuple[float, float]  # US$ per 1M (input, output)
    cached_price: float  # US$ per 1M cached input
    long_threshold: int | None = None  # above this many input tokens, the whole request is billed at long_price
    long_price: tuple[float, float] | None = None
    long_cached_price: float | None = None


# Prices from each vendor's official pricing page, checked 2026-10-01 —
# what the cost note in each result is estimated from, not a bill.
MODELS = {
    "claude-api": Model(
        "claude-api", "Claude Opus 5.5（API 基準線）", "Anthropic", "claude-opus-5-5", "ANTHROPIC_API_KEY",
        128_000, (4.0, 20.0), 0.20,
    ),
    "gpt-api": Model(
        "gpt-api", "GPT-6 Astra（API 基準線）", "OpenAI", "gpt-6-astra", "OPENAI_API_KEY",
        128_000, (10.0, 50.0), 1.0, 272_000, (20.0, 75.0), 2.0,
    ),
    "gemini-api": Model(
        "gemini-api", "Gemini 3.1 Pro（API 基準線）", "Google", "gemini-3.1-pro-preview", "GEMINI_API_KEY",
        65_536, (2.0, 12.0), 0.20, 200_000, (4.0, 18.0), 0.40,
    ),
}


# ── input ────────────────────────────────────────────────────────────────


def load_prompt() -> str:
    """The first ```text block of llm_prompt.md — the same words a person
    pastes into ChatGPT, so the file stays the single source of truth."""
    match = re.search(r"```text\n(.*?)\n```", PROMPT_FILE.read_text(encoding="utf-8"), re.S)
    if not match:
        raise SystemExit(f"{PROMPT_FILE} 裡找不到 ```text 提示詞區塊")
    return match.group(1)


def document_text(old_pdf: Path, new_pdf: Path) -> str:
    import fitz  # PyMuPDF, same as backend/services/extraction.py

    parts = []
    for n, (label, path) in enumerate((("舊版", old_pdf), ("新版", new_pdf)), start=1):
        with fitz.open(path) as doc:
            parts.append(f"########## 檔案 {n}（{label}）：{path.name}，共 {doc.page_count} 頁 ##########")
            for i, page in enumerate(doc, start=1):
                parts.append(f"===== 檔案 {n} 第 {i} 頁 =====\n{page.get_text().strip()}")
    return "\n\n".join(parts)


# ── output ───────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)(?:```|\Z)", re.S)
_HEADER = ["change_type", "old_page", "new_page", "old_text", "new_text", "risk", "note"]


@dataclass
class Turn:
    text: str
    truncated: bool
    stop: str
    usage: dict
    cost: float


def extract_rows(turns: list[Turn]) -> list[dict]:
    """Every CSV row across all turns. A turn cut off mid-row loses that
    last partial line (the follow-up turn repeats or continues it); a
    continuation that skips the header line reuses the expected one."""
    rows: list[dict] = []
    seen: set[tuple] = set()
    for turn in turns:
        blocks = _FENCE_RE.findall(turn.text) or [turn.text]
        for b_idx, block in enumerate(blocks):
            lines = block.strip("\n").split("\n")
            if turn.truncated and b_idx == len(blocks) - 1 and lines:
                lines = lines[:-1]
            if not lines:
                continue
            has_header = "change_type" in lines[0] and "old_text" in lines[0]
            reader = csv.DictReader(io.StringIO("\n".join(lines)), fieldnames=None if has_header else _HEADER)
            for raw in reader:
                row = {k.strip(): (v or "").strip() for k, v in raw.items() if isinstance(k, str)}
                if not (row.get("old_text") or row.get("new_text")):
                    continue
                key = tuple(row.get(c, "") for c in _HEADER)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
    return rows


def _choice(value: str, aliases: dict[str, str]) -> tuple[str, str]:
    """(normalized, leftover) — a value the scorer can't read is blanked
    rather than failing the whole file, and kept in the note."""
    value = value.strip()
    if not value:
        return "", ""
    resolved = aliases.get(value) or aliases.get(value.casefold())
    return (resolved, "") if resolved else ("", value)


def to_result_rows(tool: str, rows: list[dict]) -> list[dict]:
    out = []
    for n, row in enumerate(rows, start=1):
        change_type, odd_type = _choice(row.get("change_type", ""), bench._CHANGE_TYPE_ALIASES)
        risk, odd_risk = _choice(row.get("risk", ""), bench._RISK_ALIASES)
        note = row.get("note", "")
        extras = []
        if odd_type:
            extras.append(f"原 change_type「{odd_type}」")
        if odd_risk:
            extras.append(f"原 risk「{odd_risk}」")
        out.append(
            {
                "item_id": f"{tool}-{n}",
                "change_type": change_type,
                "old_page": row.get("old_page", ""),
                "new_page": row.get("new_page", ""),
                "old_text": row.get("old_text", ""),
                "new_text": row.get("new_text", ""),
                "risk": risk,
                "gt_id": "",
                "note": "；".join([note, *extras]) if extras else note,
            }
        )
    return out


# ── cost ─────────────────────────────────────────────────────────────────


def request_cost(spec: Model, *, input_tokens: int, cached_tokens: int, cache_write_tokens: int, output_tokens: int) -> float:
    """One request's estimated cost. `input_tokens` is everything sent
    (cached included); the long-context tier applies to the whole request
    once the input crosses the threshold, as all three vendors bill it."""
    long = spec.long_threshold is not None and input_tokens > spec.long_threshold
    price_in, price_out = spec.long_price if long else spec.price
    cached = spec.long_cached_price if long else spec.cached_price
    uncached = max(input_tokens - cached_tokens - cache_write_tokens, 0)
    return (
        uncached * price_in + cached_tokens * cached + cache_write_tokens * price_in * 1.25 + output_tokens * price_out
    ) / 1_000_000


def estimate_tokens(text: str) -> int:
    """Offline guess when no counting API is reachable: CJK text runs about
    one token per character or a little more; 1.2 per character overall is
    on the safe side for these documents."""
    return int(len(text) * 1.2)


def typical_output(spec: Model, input_tokens: int) -> int:
    return min(spec.max_output, 4_000 + input_tokens // 8)


# ── providers ────────────────────────────────────────────────────────────


def run_claude(spec: Model, docs: str, prompt: str, remaining: float) -> tuple[list[Turn], str]:
    import anthropic

    client = anthropic.Anthropic()
    messages: list = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": docs, "cache_control": {"type": "ephemeral"}},  # follow-ups re-read it from cache
                {"type": "text", "text": prompt},
            ],
        }
    ]
    turns: list[Turn] = []
    model_used = spec.model
    for _ in range(1 + MAX_CONTINUES):
        with client.messages.stream(
            model=spec.model,
            max_tokens=spec.max_output,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            messages=messages,
        ) as stream:
            msg = stream.get_final_message()
        model_used = msg.model
        u = msg.usage
        cached, written = u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0
        total_in = u.input_tokens + cached + written
        usage = {"input_tokens": total_in, "cached_tokens": cached, "cache_write_tokens": written, "output_tokens": u.output_tokens}
        text = "".join(b.text for b in msg.content if b.type == "text")
        truncated = msg.stop_reason == "max_tokens"
        turns.append(Turn(text, truncated, msg.stop_reason, usage, request_cost(spec, **usage)))
        if not truncated or not _can_follow_up(turns, remaining):
            break
        messages += [{"role": "assistant", "content": msg.content}, {"role": "user", "content": CONTINUE}]
    return turns, model_used


def run_openai(spec: Model, docs: str, prompt: str, remaining: float) -> tuple[list[Turn], str]:
    import openai

    client = openai.OpenAI()
    turns: list[Turn] = []
    previous: str | None = None
    model_used = spec.model
    for _ in range(1 + MAX_CONTINUES):
        kwargs = {"previous_response_id": previous, "input": CONTINUE} if previous else {"input": f"{docs}\n\n{prompt}"}
        with client.responses.stream(
            model=spec.model,
            reasoning={"effort": EFFORT},
            max_output_tokens=spec.max_output,
            **kwargs,
        ) as stream:
            resp = stream.get_final_response()
        model_used = resp.model
        u = resp.usage
        cached = (u.input_tokens_details.cached_tokens or 0) if u.input_tokens_details else 0
        usage = {"input_tokens": u.input_tokens, "cached_tokens": cached, "cache_write_tokens": 0, "output_tokens": u.output_tokens}
        truncated = resp.status == "incomplete" and getattr(resp.incomplete_details, "reason", None) == "max_output_tokens"
        turns.append(Turn(resp.output_text or "", truncated, resp.status, usage, request_cost(spec, **usage)))
        if not truncated or not _can_follow_up(turns, remaining):
            break
        previous = resp.id
    return turns, model_used


def run_gemini(spec: Model, docs: str, prompt: str, remaining: float) -> tuple[list[Turn], str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ[spec.key_env])
    config = types.GenerateContentConfig(
        max_output_tokens=spec.max_output,
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH),
    )
    contents = [types.Content(role="user", parts=[types.Part(text=docs), types.Part(text=prompt)])]
    turns: list[Turn] = []
    for _ in range(1 + MAX_CONTINUES):
        texts, parts, last = [], [], None
        for chunk in client.models.generate_content_stream(model=spec.model, contents=contents, config=config):
            last = chunk
            candidate = (chunk.candidates or [None])[0]
            for part in (candidate.content.parts if candidate and candidate.content and candidate.content.parts else []):
                parts.append(part)  # keeps thought signatures for the follow-up turn
                if part.text and not part.thought:
                    texts.append(part.text)
        finish = last.candidates[0].finish_reason if last and last.candidates else None
        meta = last.usage_metadata if last else None
        output = ((meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)) if meta else 0
        usage = {
            "input_tokens": (meta.prompt_token_count or 0) if meta else 0,
            "cached_tokens": (meta.cached_content_token_count or 0) if meta else 0,
            "cache_write_tokens": 0,
            "output_tokens": output,
        }
        truncated = finish == types.FinishReason.MAX_TOKENS
        turns.append(Turn("".join(texts), truncated, str(finish), usage, request_cost(spec, **usage)))
        if not truncated or not _can_follow_up(turns, remaining):
            break
        contents += [types.Content(role="model", parts=parts), types.Content(role="user", parts=[types.Part(text=CONTINUE)])]
    return turns, spec.model


def _can_follow_up(turns: list[Turn], remaining: float) -> bool:
    """A follow-up resends the whole input; assume it costs what the last
    turn did and don't start one the budget can't cover."""
    if sum(t.cost for t in turns) + turns[-1].cost <= remaining:
        return True
    print(f"  輸出被截斷，但再追問會超過花費上限，停在第 {len(turns)} 輪")
    return False


RUNNERS = {"claude-api": run_claude, "gpt-api": run_openai, "gemini-api": run_gemini}


def count_input_tokens(spec: Model, text: str) -> tuple[int, str]:
    """Free counting endpoints when a key is set; the offline guess otherwise."""
    if not os.environ.get(spec.key_env):
        return estimate_tokens(text), "估計"
    try:
        if spec.tool == "claude-api":
            import anthropic

            n = anthropic.Anthropic().messages.count_tokens(model=spec.model, messages=[{"role": "user", "content": text}])
            return n.input_tokens, "計數 API"
        if spec.tool == "gpt-api":
            import openai

            n = openai.OpenAI().responses.input_tokens.count(model=spec.model, input=text)
            return n.input_tokens, "計數 API"
        from google import genai

        n = genai.Client(api_key=os.environ[spec.key_env]).models.count_tokens(model=spec.model, contents=text)
        return n.total_tokens, "計數 API"
    except Exception as exc:  # counting is a convenience; never block the estimate on it
        print(f"  （{spec.tool} 計數 API 失敗，改用估計：{type(exc).__name__}）")
        return estimate_tokens(text), "估計"


# ── main ─────────────────────────────────────────────────────────────────


def _already_run(meta_path: Path) -> bool:
    if not meta_path.exists():
        return False
    return bool(re.match(r"\d{4}-\d{2}-\d{2}", str(json.loads(meta_path.read_text(encoding="utf-8")).get("run_date") or "")))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case", nargs="*", help="只跑這些案例")
    parser.add_argument("--model", nargs="*", choices=sorted(MODELS), help="只跑這些模型")
    parser.add_argument("--estimate", action="store_true", help="只估 token 與費用，不呼叫模型")
    parser.add_argument("--budget", type=float, default=40.0, help="總花費上限（US$，依估算）；下一筆預估會超過就停")
    parser.add_argument("--force", action="store_true", help="已有結果也重跑（會再花一次錢）")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env", override=False)  # gitignored; never printed
    except ImportError:
        pass

    root = bench.DEFAULT_ROOT
    cases = bench.discover(root, args.case)
    # cheapest first: a broken parser shows up on the demo, not after paying for the long case
    cases.sort(key=lambda c: sum(p.stat().st_size for p in bench.case_pdfs(c, root)))
    models = [MODELS[m] for m in (args.model or MODELS)]
    prompt = load_prompt()
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]

    spent = 0.0
    for case in cases:
        old_pdf, new_pdf = bench.case_pdfs(case, root)
        docs = document_text(old_pdf, new_pdf)
        for spec in models:
            out = root / "results" / case.id / f"{spec.tool}.csv"
            n_in, how = count_input_tokens(spec, f"{docs}\n\n{prompt}")
            guess = request_cost(spec, input_tokens=n_in, cached_tokens=0, cache_write_tokens=0, output_tokens=typical_output(spec, n_in))
            # every request fills its output cap and is followed up twice, with no cache hits
            worst = (1 + MAX_CONTINUES) * request_cost(
                spec, input_tokens=n_in, cached_tokens=0, cache_write_tokens=0, output_tokens=spec.max_output
            )
            label = f"{case.id} × {spec.model}"
            print(f"{label}：輸入約 {n_in:,} token（{how}），預估 US${guess:.2f}，最壞 US${worst:.2f}（輸出全滿＋追問兩次）")
            if args.estimate:
                continue
            if _already_run(out.with_suffix(".json")) and not args.force:
                print("  已有結果，略過（--force 重跑）")
                continue
            if not os.environ.get(spec.key_env):
                print(f"  沒有 {spec.key_env}，略過")
                continue
            if spent + guess > args.budget:
                print(f"  再跑會超過花費上限 US${args.budget:.2f}（已花約 US${spent:.2f}），略過")
                continue
            started = time.perf_counter()
            try:
                turns, model_used = RUNNERS[spec.tool](spec, docs, prompt, args.budget - spent)
            except Exception as exc:  # one vendor failing must not stop the others
                print(f"  失敗：{type(exc).__name__}：{str(exc)[:300]}")
                continue
            elapsed = time.perf_counter() - started
            cost = sum(t.cost for t in turns)
            spent += cost
            rows = to_result_rows(spec.tool, extract_rows(turns))
            bench.write_rows(out, rows)
            usage = {k: sum(t.usage[k] for t in turns) for k in turns[0].usage}
            stops = [t.stop for t in turns]
            meta = {
                "tool": spec.tool,
                "display_name": spec.display_name,
                "kind": "llm-baseline",
                "tool_version": model_used,
                "run_date": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "run_by": "scripts/llm_baseline.py",
                "settings": (
                    f"effort={EFFORT}，max_output={spec.max_output:,}，輸入＝兩份 PDF 的文字層逐頁（PyMuPDF，附頁碼標記），"
                    f"提示詞 templates/llm_prompt.md（sha256 {prompt_hash}），追問「{CONTINUE}」{len(turns) - 1} 次"
                ),
                "runtime_seconds": round(elapsed, 1),
                "cost_note": (
                    f"約 US${cost:.2f}（輸入 {usage['input_tokens']:,}、其中快取 {usage['cached_tokens']:,}、"
                    f"輸出含推理 {usage['output_tokens']:,} token；依 2026-10-01 官方定價估算，非帳單）"
                ),
                "data_handling": f"文件文字以 API 傳送到 {spec.vendor}",
                "risk_mapping": "模型依提示詞的 High/Medium/Low 定義自行分級",
                "usage": usage,
                "stop_reasons": stops,
                "notes": "；".join(
                    n
                    for n in (
                        "" if rows else "模型沒有輸出任何可解析的變更列，見 .raw.md",
                        "最後一輪仍被截斷（追問次數或花費上限已到），清單可能不完整" if turns[-1].truncated else "",
                    )
                    if n
                ),
            }
            out.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raw = "\n\n".join(f"<!-- turn {i + 1}: stop={t.stop} usage={t.usage} -->\n{t.text}" for i, t in enumerate(turns))
            out.with_suffix(".raw.md").write_text(raw + "\n", encoding="utf-8")
            print(f"  完成：{len(rows)} 筆，{elapsed:.0f}s，約 US${cost:.2f}，stop={stops}")
    if not args.estimate:
        print(f"\n本次約花 US${spent:.2f}。接著跑：python3 scripts/accuracy_bench.py score")


if __name__ == "__main__":
    main()
