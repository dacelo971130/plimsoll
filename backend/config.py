"""Filesystem layout for the local-first store.

Per architecture-decisions-A-B.md ("本機檔案配置 (P0 落地)"):

    data/store/
    ├── config/
    │   ├── approval_roles.json
    │   ├── rulesets/v1.json
    │   └── approval_policies/v1.json
    ├── sessions/<session_id>/
    │   ├── session.json
    │   ├── differences.json
    │   ├── review_events.jsonl   (append-only)
    │   └── sync_state.json
    ├── exports/
    └── .integrity/                (offline fallback for prefix-hash anchors)

``STORE_ROOT`` can be overridden (e.g. in tests) via the ``PLIMSOLL_STORE_ROOT``
environment variable so unit tests never touch the real `data/store/` tree.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _store_root() -> Path:
    override = os.environ.get("PLIMSOLL_STORE_ROOT")
    return Path(override).resolve() if override else REPO_ROOT / "data" / "store"


STORE_ROOT = _store_root()
CONFIG_ROOT = STORE_ROOT / "config"
# Docker image's own glossary copy, outside the data volume (see Dockerfile);
# absent outside Docker, where CONFIG_ROOT/glossary is the only copy.
GLOSSARY_SEED_ROOT = REPO_ROOT / "seed" / "glossary"
SESSIONS_ROOT = STORE_ROOT / "sessions"
EXPORTS_ROOT = STORE_ROOT / "exports"
INTEGRITY_ROOT = STORE_ROOT / ".integrity"

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def session_dir(session_id: str, store_root: Path = SESSIONS_ROOT) -> Path:
    path = store_root / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path
