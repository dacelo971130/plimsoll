"""The append-only agent run record, sessions/<id>/agent_runs.jsonl (spec
§4.8) — read by runs.py (history, polling, reload) and by the Q&A tool that
lets a question refer to the latest briefing (tools.get_briefing). Kept on
its own so tools.py can read it without importing runs.py, which imports
tools.py."""

from __future__ import annotations

import json
from pathlib import Path

from backend.config import SESSIONS_ROOT

RUNS_FILE = "agent_runs.jsonl"


def runs_path(session_id: str) -> Path:
    return SESSIONS_ROOT / session_id / RUNS_FILE


def read_records(session_id: str) -> list[dict]:
    path = runs_path(session_id)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def latest_briefing(session_id: str) -> dict | None:
    """The newest finished briefing's record, or None."""
    return next((r for r in reversed(read_records(session_id)) if r["kind"] == "briefing" and r["status"] == "done"), None)
