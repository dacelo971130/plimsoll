"""覆核 Agent（docs/redesign/plimsoll-review-agent-spec.md §4）: a read-only,
tool-using agent that prepares a review briefing and answers questions about
the loaded documents. Everything it says is re-checked deterministically
(verify.py) before anyone sees it; it can never write a review event."""
