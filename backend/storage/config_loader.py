"""Load approval roles / rulesets / approval policies from `data/store/config/`.

Nothing here is a hardcoded enum or threshold — adding a role means adding a
row to `approval_roles.json`; adjusting a threshold means adding a new
`rulesets/v{N}.json` and pointing new sessions at it. See
architecture-decisions-A-B.md §20.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal

from backend.config import CONFIG_ROOT, GLOSSARY_SEED_ROOT
from backend.models.config_models import (
    ApprovalPolicy,
    ApprovalRole,
    Glossary,
    PendingAlias,
    Ruleset,
    TermAlias,
    TermAliasTable,
)


def _read_json(path: Path) -> dict | list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=None)
def list_approval_roles(config_root: Path = CONFIG_ROOT) -> list[ApprovalRole]:
    raw = _read_json(config_root / "approval_roles.json")
    return [ApprovalRole(**row) for row in raw]


def get_role_label(code: str, *, lang: str = "zh", config_root: Path = CONFIG_ROOT) -> str | None:
    for role in list_approval_roles(config_root):
        if role.code == code:
            return role.label_en if lang == "en" else role.label_zh
    return None


def get_role_label_snapshot(code: str, config_root: Path = CONFIG_ROOT) -> str | None:
    """`approval_role_label_snapshot` — "船舶技術監督（Technical Superintendent）"
    exactly as architecture-decisions-A-B.md's worked example. Frozen onto
    the event at write time so a later config edit never rewrites history."""
    for role in list_approval_roles(config_root):
        if role.code == code:
            # DPA's seed label_zh already embeds its English name in
            # parens ("DPA（Designated Person Ashore）") — don't double it up.
            if role.label_en in role.label_zh:
                return role.label_zh
            return f"{role.label_zh}（{role.label_en}）"
    return None


@lru_cache(maxsize=None)
def get_ruleset(version: str, config_root: Path = CONFIG_ROOT) -> Ruleset:
    raw = _read_json(config_root / "rulesets" / f"{version}.json")
    return Ruleset(**raw)


def latest_ruleset_version(config_root: Path = CONFIG_ROOT) -> str:
    """Highest `v{N}.json` present — the default for newly created sessions."""
    versions = sorted(
        (p.stem for p in (config_root / "rulesets").glob("v*.json")),
        key=lambda v: int(v.lstrip("v")),
    )
    if not versions:
        raise FileNotFoundError(f"No rulesets found under {config_root / 'rulesets'}")
    return versions[-1]


@lru_cache(maxsize=None)
def get_approval_policy(ruleset_version: str, config_root: Path = CONFIG_ROOT) -> ApprovalPolicy:
    raw = _read_json(config_root / "approval_policies" / f"{ruleset_version}.json")
    return ApprovalPolicy(**raw)


@lru_cache(maxsize=None)
def get_term_aliases(version: str, config_root: Path = CONFIG_ROOT) -> TermAliasTable:
    raw = _read_json(config_root / "term_aliases" / f"{version}.json")
    return TermAliasTable(**raw)


def latest_term_aliases_version(config_root: Path = CONFIG_ROOT) -> str:
    """Highest `v{N}.json` present under term_aliases/ — the default table
    for newly created sessions (W4), same convention as latest_ruleset_version."""
    versions = sorted(
        (p.stem for p in (config_root / "term_aliases").glob("v*.json")),
        key=lambda v: int(v.lstrip("v")),
    )
    if not versions:
        raise FileNotFoundError(f"No term_aliases found under {config_root / 'term_aliases'}")
    return versions[-1]


def _glossary_dirs(config_root: Path) -> list[Path]:
    """Where glossary versions live: the config root, plus — for the real
    config root — the Docker image's own copy outside the data volume. A
    named volume copies seed config only on its first run, so a volume made
    before the glossary (or before a newer version) existed would otherwise
    never see it. The config root comes first, so a version edited there
    (e.g. approved by hand) wins over the image's copy of the same version."""
    return [config_root / "glossary", GLOSSARY_SEED_ROOT] if config_root == CONFIG_ROOT else [config_root / "glossary"]


@lru_cache(maxsize=None)
def get_glossary(version: str, config_root: Path = CONFIG_ROOT) -> Glossary:
    path = next((d / f"{version}.json" for d in _glossary_dirs(config_root) if (d / f"{version}.json").exists()), None)
    if path is None:
        raise FileNotFoundError(f"glossary {version} not found")
    return Glossary(**_read_json(path))


def latest_glossary_version(config_root: Path = CONFIG_ROOT) -> str | None:
    """Highest `v{N}.json` across _glossary_dirs(), or None when there isn't
    one — the help page must still open without it."""
    versions = sorted(
        {p.stem for d in _glossary_dirs(config_root) for p in d.glob("v*.json")},
        key=lambda v: int(v.lstrip("v")),
    )
    return versions[-1] if versions else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class UnknownPendingAlias(Exception):
    pass


def _pending_aliases_path(config_root: Path) -> Path:
    return config_root / "term_aliases" / "pending.json"


def get_pending_aliases(*, status: str | None = "pending", config_root: Path = CONFIG_ROOT) -> list[PendingAlias]:
    """The term_aliases 核准 queue. Not lru_cache'd — unlike the versioned
    config files, this changes on every suggest/approve/reject call, far
    more often than a process lifetime should keep stale. `status=None`
    returns the full history (pending + approved + rejected); the default
    only returns entries still awaiting a decision."""
    path = _pending_aliases_path(config_root)
    if not path.exists():
        return []
    entries = [PendingAlias(**row) for row in _read_json(path)]
    if status is None:
        return entries
    return [e for e in entries if e.status == status]


def append_pending_alias(
    *,
    canonical: str,
    variant: str,
    rationale: str,
    source_session_id: str | None = None,
    config_root: Path = CONFIG_ROOT,
) -> PendingAlias:
    path = _pending_aliases_path(config_root)
    existing = _read_json(path) if path.exists() else []
    entry = PendingAlias(
        id=f"pa-{uuid.uuid4().hex[:8]}",
        canonical=canonical,
        variant=variant,
        rationale=rationale,
        source_session_id=source_session_id,
        status="pending",
        created_at=_now_iso(),
    )
    existing = list(existing) + [entry.model_dump()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry


def resolve_pending_alias(
    pending_id: str,
    *,
    decision: Literal["approve", "reject"],
    approved_by: str | None = None,
    config_root: Path = CONFIG_ROOT,
) -> PendingAlias:
    """`approve` writes a NEW immutable term_aliases/v{N+1}.json — merging
    the candidate's variant into an existing canonical row if one already
    matches, else adding a new row — and clears get_term_aliases()'s cache
    so the next session created picks it up. `reject` only flips the pending
    entry's status. Neither ever rewrites an existing term_aliases/v{N}.json:
    versioned config here follows the same "append a new version, never
    mutate an old one" discipline as rulesets (architecture-decisions-A-B.md
    §20)."""
    path = _pending_aliases_path(config_root)
    entries = [PendingAlias(**row) for row in (_read_json(path) if path.exists() else [])]
    match = next((e for e in entries if e.id == pending_id), None)
    if match is None:
        raise UnknownPendingAlias(pending_id)
    if match.status != "pending":
        raise UnknownPendingAlias(f"{pending_id} already resolved (status={match.status})")

    if decision == "approve":
        if not approved_by:
            raise ValueError("approved_by is required to approve a pending alias")
        current_version = latest_term_aliases_version(config_root)
        current_table = get_term_aliases(current_version, config_root)
        next_version = f"v{int(current_version.lstrip('v')) + 1}"
        approved_at = _now_iso()

        new_aliases = [a.model_copy(deep=True) for a in current_table.aliases]
        target = next((a for a in new_aliases if a.canonical == match.canonical), None)
        if target is not None:
            if match.variant not in target.variants:
                target.variants.append(match.variant)
        else:
            new_aliases.append(
                TermAlias(
                    canonical=match.canonical,
                    variants=[match.variant],
                    approved_by=approved_by,
                    approved_at=approved_at,
                )
            )
        new_table = TermAliasTable(version=next_version, aliases=new_aliases)
        (config_root / "term_aliases" / f"{next_version}.json").write_text(
            json.dumps(new_table.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        get_term_aliases.cache_clear()
        match.status = "approved"
        match.approved_by = approved_by
        match.approved_at = approved_at
    else:
        match.status = "rejected"

    path.write_text(
        json.dumps([e.model_dump() for e in entries], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return match


def clear_config_cache() -> None:
    """Test helper — config is `lru_cache`d per-process for perf."""
    list_approval_roles.cache_clear()
    get_ruleset.cache_clear()
    get_approval_policy.cache_clear()
    get_term_aliases.cache_clear()
    get_glossary.cache_clear()
