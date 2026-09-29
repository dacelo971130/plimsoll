"""Deterministic document processing — extraction, alignment, rule
classification. No LLM call is required anywhere in this package
(`analysis_mode=rules_first` default per architecture-decisions-A-B.md §25);
an LLM provider is a future, optional upgrade layered on top, never a
dependency of the P0–P4 critical path.
"""
