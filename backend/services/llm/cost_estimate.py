"""P6 成本試算, real-document version: estimates how many differences THIS
session would actually send to an LLM, and roughly how many tokens that
would cost — grounded in the session's own `differences.json`, not a fixed
small/medium/large document-size guess (see the old CostEstimatorModal.tsx
presets, which this is meant to replace the backing data for).

Deliberately reuses `needs_semantic_review_dict()` — the exact same
deterministic trigger `enrich_session_differences()` uses to decide which
differences get sent to the model — so "how many would be sent" can never
drift from what actually happens if the user turns the semantic layer on.
Computing it here costs nothing and calls no provider: it's the same
zero-cost heuristic the real trigger already runs before ever touching the
network.

Token counts are still an ESTIMATE, not a real tokenizer: no provider's
tokenizer is vendored in this project (backend/services/llm/provider.py
talks to Anthropic/Gemini/OpenAI's own SDKs, none of which ship an offline
tokenizer here), so `_estimate_tokens()` is a character-count heuristic —
CJK characters counted ~1 token each (BPE tokenizers commonly spend a full
token per CJK character, sometimes more), everything else at ~4 chars/token
(the usual rule of thumb for English/Latin text). This will not match a
real bill exactly; it exists to turn a fixed demo guess into a number that
at least reflects this document's actual size and mix of scripts.
"""

from __future__ import annotations

import re

from backend.services.llm.prompts import RESIDUAL_SYSTEM_PROMPT
from backend.services.llm.residual import AnalysisMode, needs_semantic_review_dict

_CJK_RE = re.compile(r"[㐀-鿿豈-﫿]")

_ANALYSIS_MODES: tuple[AnalysisMode, ...] = ("rules_first", "model_heavy", "model_only")

# ResidualSuggestion (backend/services/llm/schemas.py) is a small fixed
# shape — an enum, a bool, an optional enum, and a 1-2 sentence rationale.
# Never measured against a real response (that would cost money just to
# calibrate an estimate), so this is a judgment call, not a fitted number.
_ESTIMATED_OUTPUT_TOKENS_PER_CALL = 90


def _estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    cjk_chars = len(_CJK_RE.findall(text))
    other_chars = len(text) - cjk_chars
    return cjk_chars + -(-other_chars // 4)  # ceil-division so a short ASCII string never rounds to 0


_SYSTEM_PROMPT_TOKENS = _estimate_tokens(RESIDUAL_SYSTEM_PROMPT)


def estimate_semantic_review_cost(differences: list[dict]) -> dict[str, dict]:
    """One entry per `AnalysisMode`, each with the differences that mode
    would actually send (`qualifying_count`) and the estimated input/output
    token totals across all of them. The mode the session is actually set to
    (`session["analysis_mode"]`) is what `enrich_session_differences()` uses
    for a real run — this returns all three so the frontend can show the
    full low (rules_first) to high (model_only) range regardless of which
    one is currently selected."""
    out: dict[str, dict] = {}
    for mode in _ANALYSIS_MODES:
        qualifying = [
            d for d in differences if d.get("kind") != "drawing" and needs_semantic_review_dict(d, analysis_mode=mode)
        ]
        input_tokens = 0
        for d in qualifying:
            old_text = (d.get("old") or {}).get("text")
            new_text = (d.get("new") or {}).get("text")
            input_tokens += _SYSTEM_PROMPT_TOKENS + _estimate_tokens(old_text) + _estimate_tokens(new_text)
        out[mode] = {
            "qualifying_count": len(qualifying),
            "estimated_input_tokens": input_tokens,
            "estimated_output_tokens": len(qualifying) * _ESTIMATED_OUTPUT_TOKENS_PER_CALL,
        }
    return out
