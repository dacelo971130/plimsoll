"""W7b trail trend analysis: docs/redesign/plimsoll-improvement-plan.html
§03. Input is a single parameter's series (values + each point's source
sentence) — NOT the five versions' full text; a 5-point series is ~400
tokens vs. ~30K for five whole documents, and the model isn't left to guess
which number belongs to which parameter.

Same opt-in discipline as residual.py: nothing here is called automatically
by backend.services.chain.build_chain(). A caller explicitly runs this over
a DriftFinding it already has (typically one `compute_drift_report()`
flagged `is_drift=True`) and passes a provider from `get_llm_provider()`.
"""

from __future__ import annotations

from backend.models.chain import ParameterPoint
from backend.services.llm.provider import LlmProvider, LlmUnavailable
from backend.services.llm.schemas import TrailAnalysis


def analyze_trail(series: list[ParameterPoint], provider: LlmProvider) -> TrailAnalysis | None:
    """Returns None (not a guessed default) if the series is too short to
    say anything about a trend, or if the provider call fails — the caller
    should treat None exactly like "no suggestion available", the same
    contract as the rest of the W7 layer."""
    if len(series) < 2:
        return None
    try:
        return provider.analyze_trail(series)
    except LlmUnavailable:
        return None
