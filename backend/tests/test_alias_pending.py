"""P5 term_aliases 核准流程 tests — pending-candidate queue + approve/reject,
all against a throwaway `tmp_path` config root so the real
data/store/config/term_aliases/*.json seed files are never touched."""

from __future__ import annotations

import json

import pytest

from backend.storage.config_loader import (
    UnknownPendingAlias,
    append_pending_alias,
    get_pending_aliases,
    get_term_aliases,
    resolve_pending_alias,
)


@pytest.fixture
def config_root(tmp_path):
    root = tmp_path / "config"
    (root / "term_aliases").mkdir(parents=True)
    (root / "term_aliases" / "v1.json").write_text(
        json.dumps({"version": "v1", "aliases": [{"canonical": "溫度上限", "variants": ["最高溫度限值"]}]}),
        encoding="utf-8",
    )
    yield root
    get_term_aliases.cache_clear()


def test_no_pending_file_returns_empty_list(config_root):
    assert get_pending_aliases(config_root=config_root) == []


def test_append_then_list_pending(config_root):
    entry = append_pending_alias(canonical="巡防艦", variant="巡防艦艇", rationale="同一件事", config_root=config_root)
    assert entry.status == "pending"
    assert entry.id.startswith("pa-")

    pending = get_pending_aliases(config_root=config_root)
    assert [p.id for p in pending] == [entry.id]


def test_approve_creates_new_version_and_merges_into_existing_canonical(config_root):
    entry = append_pending_alias(canonical="溫度上限", variant="溫度上限值", rationale="同一件事", config_root=config_root)

    resolved = resolve_pending_alias(entry.id, decision="approve", approved_by="tester", config_root=config_root)

    assert resolved.status == "approved"
    assert resolved.approved_by == "tester"

    new_table = get_term_aliases("v2", config_root=config_root)
    row = next(a for a in new_table.aliases if a.canonical == "溫度上限")
    assert set(row.variants) == {"最高溫度限值", "溫度上限值"}

    # original v1.json is untouched — never rewrite an existing version.
    v1 = get_term_aliases("v1", config_root=config_root)
    assert v1.aliases[0].variants == ["最高溫度限值"]

    # resolved entries drop out of the default pending listing.
    assert get_pending_aliases(config_root=config_root) == []


def test_approve_adds_a_new_canonical_row_when_none_matches(config_root):
    entry = append_pending_alias(canonical="巡防艦", variant="巡防艦艇", rationale="同一件事", config_root=config_root)
    resolve_pending_alias(entry.id, decision="approve", approved_by="tester", config_root=config_root)

    new_table = get_term_aliases("v2", config_root=config_root)
    canonicals = {a.canonical for a in new_table.aliases}
    assert canonicals == {"溫度上限", "巡防艦"}


def test_reject_does_not_create_a_new_version(config_root):
    entry = append_pending_alias(canonical="巡防艦", variant="巡防艦艇", rationale="同一件事", config_root=config_root)
    resolved = resolve_pending_alias(entry.id, decision="reject", config_root=config_root)

    assert resolved.status == "rejected"
    assert not (config_root / "term_aliases" / "v2.json").exists()
    assert get_pending_aliases(config_root=config_root) == []


def test_resolving_unknown_id_raises(config_root):
    with pytest.raises(UnknownPendingAlias):
        resolve_pending_alias("pa-doesnotexist", decision="reject", config_root=config_root)


def test_resolving_an_already_resolved_entry_raises(config_root):
    entry = append_pending_alias(canonical="巡防艦", variant="巡防艦艇", rationale="同一件事", config_root=config_root)
    resolve_pending_alias(entry.id, decision="reject", config_root=config_root)
    with pytest.raises(UnknownPendingAlias):
        resolve_pending_alias(entry.id, decision="reject", config_root=config_root)


def test_approve_without_approved_by_raises(config_root):
    entry = append_pending_alias(canonical="巡防艦", variant="巡防艦艇", rationale="同一件事", config_root=config_root)
    with pytest.raises(ValueError):
        resolve_pending_alias(entry.id, decision="approve", config_root=config_root)
