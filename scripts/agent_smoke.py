"""One live run of the review agent against the demo PDFs — the check the
fake-client tests can't do: does the real API accept the request shape
(tools + adaptive thinking + output_config.format + caching + fallbacks),
and what does a run actually cost?

Spends real money (roughly US$0.5–1.5 on claude-opus-5 for all three runs).
Uses ANTHROPIC_API_KEY from your environment and a throwaway store under a
temp dir, so nothing touches data/store/.

    ANTHROPIC_API_KEY=... .venv/bin/python3 scripts/agent_smoke.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ANTHROPIC_API_KEY is not set — nothing was sent.")

# Must be set before backend.config is imported.
_store = Path(tempfile.mkdtemp(prefix="plimsoll-agent-smoke-"))
shutil.copytree(REPO_ROOT / "data" / "store" / "config", _store / "config")
os.environ["PLIMSOLL_STORE_ROOT"] = str(_store)
sys.path.insert(0, str(REPO_ROOT))

from backend.services import session_store  # noqa: E402
from backend.services.agent import runs  # noqa: E402
from backend.services.agent.client import resolve_agent_client  # noqa: E402

# claude-opus-5 list prices, US$ per million tokens (cache write = 5-minute TTL).
PRICE = {"input_tokens": 5.0, "output_tokens": 25.0, "cache_creation_input_tokens": 6.25, "cache_read_input_tokens": 0.5}


def cost(usage: dict) -> float:
    return sum(usage.get(k, 0) * p for k, p in PRICE.items()) / 1_000_000


def show(title: str, run: runs.AgentRun) -> float:
    print(f"\n=== {title}: {run.status} ({run.model}) ===")
    for step in run.steps:
        print(f"  · {step['label']}{'' if step['ok'] else '（工具回報錯誤）'}")
    if run.error:
        print(f"  error: {run.error}")
    if run.result:
        print(json.dumps(run.result, ensure_ascii=False, indent=2)[:4000])
    spent = cost(run.usage)
    print(f"  usage: {run.usage}  ≈ US${spent:.3f}")
    return spent


def main() -> None:
    client, reason = resolve_agent_client(None, None)
    if client is None:
        sys.exit(reason)
    demo = REPO_ROOT / "data" / "demo"
    old, new = demo / "Main_Engine_Cooling_v1.0.pdf", demo / "Main_Engine_Cooling_v1.1.pdf"
    sid = session_store.process_upload(old.read_bytes(), old.name, new.read_bytes(), new.name)["session"]["session_id"]

    total = show("覆核簡報", runs.start_run(sid, "briefing", client, background=False))
    total += show("問答（文件內）", runs.start_run(sid, "question", client, "D01 的溫度門檻從多少改成多少？", background=False))
    total += show("問答（範圍外）", runs.start_run(sid, "question", client, "幫我寫一段 Python 爬蟲", background=False))
    print(f"\nTotal ≈ US${total:.3f}. Throwaway store: {_store}")


if __name__ == "__main__":
    main()
