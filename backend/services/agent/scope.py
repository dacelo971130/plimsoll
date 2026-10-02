"""Questions the review agent refuses before any model sees them.

The agent answers questions about the loaded documents and nothing else
(spec §4.6). Most out-of-scope questions — code, privacy, politics, race,
the system itself — are judged by the model under ANSWER_SYSTEM_PROMPT's
rules and come back as the fixed OUT_OF_SCOPE_TEXT. This module catches the
ones that try to change the rules themselves (prompt injection, role swaps,
asking for the system prompt) or smuggle in a command, so they never reach
the model at all.

The patterns are deliberately narrow, because ordinary document questions
use the same words: 「這個閥門扮演什麼角色」, 「可以忽略哪些指示燈」,
「系統提示訊息代表什麼」, 「這個步驟何時執行」 must all still get through.
Each pattern needs the attack's own framing (「忽略以上的指示」, 「你現在是」,
「system prompt」), not just a keyword."""

from __future__ import annotations

import re

_PATTERNS = [
    # Prompt injection: overriding the instructions.
    r"(忽略|無視|不要理會|跳過|拋開)\s*(以上|上述|前面|先前|之前|所有|你的|原本的?)\s*的?\s*(所有|全部)?\s*(指示|指令|規則|設定|限制|提示)",
    r"(ignore|disregard|forget)\s+(all\s+|any\s+)?(the\s+)?(previous|above|prior|earlier|your|system)\s+(instructions?|rules|prompts?|messages?)",
    # Asking for the system prompt / internals.
    r"system\s*prompt|系統提示詞|你的(提示詞|系統指令|內部指令|設定檔)|(列出|顯示|告訴我|給我|輸出).{0,6}(你的)?(提示詞|prompt)",
    r"開發者模式|developer\s*mode|jailbreak|越獄|\bDAN\b",
    # Role swaps.
    r"你現在是|從現在(起|開始)你是|假裝你是|你不再是|(請|你)(來)?扮演|角色扮演|pretend\s+(to\s+be|you\s+are)|you\s+are\s+now|role\s*-?\s*play",
    # Commands / code to run.
    r"\brm\s+-rf\b|\bsudo\b|\bcurl\s+https?://|\bwget\s|\bDROP\s+TABLE\b|\bos\.system\b|\bsubprocess\b|<script\b",
]
_BLOCKED = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.IGNORECASE)


def blocked(question: str) -> bool:
    """True when the question tries to change the agent's rules or run
    something — answered with OUT_OF_SCOPE_TEXT, no model call."""
    return _BLOCKED.search(question) is not None
