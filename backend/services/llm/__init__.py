"""LLM semantic layer (W7): docs/redesign/plimsoll-improvement-plan.html §03.

Everything under this package is a value-add, never a dependency — the rest
of the app (extraction/normalize/comparison/chain) never imports from here.
`ai_risk` is always, only, ever set by the deterministic rule engine
(backend.services.comparison.classify()); nothing in this package is
permitted to write it. See provider.py's module docstring for why this is a
Strategy over single structured-output calls, not an agent.
"""
