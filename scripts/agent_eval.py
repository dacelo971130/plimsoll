"""Scope-guard evaluation for the review agent (spec §4.6, acceptance A7–A9):
asks every question in scripts/agent_eval_questions.json against the demo
PDFs and checks the *verified* result — what a reviewer would actually see.

Spends real money: roughly US$1–3 on claude-opus-5 for the full set. Stops
early once --budget (default US$5) is reached. Uses ANTHROPIC_API_KEY and a
throwaway store under a temp dir; every question gets a fresh comparison so
earlier answers can't leak into later ones — a question with
`"context": "chain"` gets a fresh 5-version demo chain instead (v1.0 → v1.4,
built with no model cost) and is asked on that chain's last anchor comparison.

    ANTHROPIC_API_KEY=... .venv/bin/python3 scripts/agent_eval.py
    ANTHROPIC_API_KEY=... .venv/bin/python3 scripts/agent_eval.py --only oos-18 doc-01
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = REPO_ROOT / "scripts" / "agent_eval_questions.json"

# claude-opus-5 list prices, US$ per million tokens (cache write = 5-minute TTL).
PRICE = {"input_tokens": 5.0, "output_tokens": 25.0, "cache_creation_input_tokens": 6.25, "cache_read_input_tokens": 0.5}


def cost(usage: dict) -> float:
    return sum(usage.get(k, 0) * p for k, p in PRICE.items()) / 1_000_000


def check(
    expect: str,
    result: dict | None,
    term: str | None = None,
    *,
    version: str | None = None,
    min_citations: int | None = None,
) -> tuple[bool, str]:
    """Pure: does one verified result meet its expectation? Returns (ok, why).

    `version` / `min_citations` are only used by the chain question types
    (answer_cites_version / answer_multi) — see scripts/agent_eval_questions.json's
    "expectations" map for what each type actually checks.
    """
    if result is None:
        return False, "沒有結果（執行失敗）"
    kind, citations = result["answer_type"], result["citations"]
    if expect == "refuse":
        ok = kind in ("out_of_scope", "not_in_documents") and not citations
        return ok, f"{kind}，引用 {len(citations)} 個"
    if expect == "answer":
        ok = kind == "answer" and len(citations) >= 1
        return ok, f"{kind}，引用 {len(citations)} 個"
    if expect == "not_found":
        return kind in ("not_in_documents", "out_of_scope"), kind
    if expect == "glossary_pending":
        topics = [p["topic"] for p in result["pending"]]
        ok = not result["glossary"] and (term in topics or kind != "answer")
        return ok, f"{kind}，定義 {len(result['glossary'])} 條，待確認 {topics}"
    if expect == "answer_cites_version":
        # version_label is the cited side's document version. Chain questions
        # are asked on v1.0 → v1.4, so v1.1–v1.3 can only come from a citation
        # into another comparison of the chain.
        cited_versions = [c.get("version_label") for c in citations]
        ok = kind == "answer" and version in cited_versions
        return ok, f"{kind}，引用版本 {cited_versions}（需要 {version}）"
    if expect == "answer_multi":
        ok = kind == "answer" and len(citations) >= (min_citations or 1)
        return ok, f"{kind}，引用 {len(citations)} 個（需要 ≥{min_citations}）"
    return False, f"未知的預期類型 {expect}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*", help="只跑這些題號")
    parser.add_argument("--budget", type=float, default=5.0, help="總花費上限（US$），達到就停")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set — nothing was sent.")

    store = Path(tempfile.mkdtemp(prefix="plimsoll-agent-eval-"))
    shutil.copytree(REPO_ROOT / "data" / "store" / "config", store / "config")
    os.environ["PLIMSOLL_STORE_ROOT"] = str(store)  # must precede backend imports
    sys.path.insert(0, str(REPO_ROOT))

    from backend.services import chain as chain_service
    from backend.services import session_store
    from backend.services.agent import runs
    from backend.services.agent.client import resolve_agent_client

    client, reason = resolve_agent_client(None, None)
    if client is None:
        sys.exit(reason)

    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    if args.only:
        questions = [q for q in questions if q["id"] in set(args.only)]

    demo = REPO_ROOT / "data" / "demo"
    old, new = demo / "Main_Engine_Cooling_v1.0.pdf", demo / "Main_Engine_Cooling_v1.1.pdf"
    # W5/W6 chain demo (spec §4.2 item 6 bonus): v1.0 → v1.4, 5 versions.
    chain_pdfs = [demo / f"Main_Engine_Cooling_v1.{i}.pdf" for i in range(5)]

    def new_session_id(q: dict) -> str:
        """A brand-new comparison for this one question — no state, no cost,
        carried over from an earlier question."""
        if q.get("context") == "chain":
            built = chain_service.build_chain([(p.read_bytes(), p.name) for p in chain_pdfs])
            return built["manifest"].anchor_session_ids[-1]  # v1.0 → v1.4
        return session_store.process_upload(old.read_bytes(), old.name, new.read_bytes(), new.name)["session"]["session_id"]

    total, failures, asked = 0.0, [], 0
    for q in questions:
        if total >= args.budget:
            print(f"\n已達花費上限 US${args.budget:.2f}，停止（剩 {len(questions) - asked} 題未跑）。")
            break
        sid = new_session_id(q)
        run = runs.start_run(sid, "question", client, q["question"], background=False)
        asked += 1
        spent = cost(run.usage)
        total += spent
        ok, why = check(q["expect"], run.result, q.get("term"), version=q.get("version"), min_citations=q.get("min_citations"))
        if not ok:
            failures.append(q["id"])
        answer = (run.result or {}).get("text") or run.error or ""
        print(f"{'PASS' if ok else 'FAIL'}  {q['id']:<7} [{q['category']}] {q['question']}")
        print(f"      → {why}；US${spent:.3f}；{answer[:80]}")

    print(f"\n{asked - len(failures)}/{asked} 通過，總花費約 US${total:.3f}。暫存資料夾：{store}")
    if failures:
        print("未通過：" + "、".join(failures))
        sys.exit(1)


if __name__ == "__main__":
    main()
