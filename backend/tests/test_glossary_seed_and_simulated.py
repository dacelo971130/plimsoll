"""Two glossary behaviours added 2026-10-02:

- The Docker image keeps its own glossary copy outside the data volume
  (config.GLOSSARY_SEED_ROOT), because a named volume only takes seed config
  on its first run — the running container had no glossary at all.
- A `simulated` glossary (the user's stand-in table, switched on before an
  expert review) is labelled wherever a definition is shown, and kept out of
  the formal sign-off report."""

from __future__ import annotations

import json

import pytest

from backend.models.config_models import Glossary, GlossaryTerm
from backend.storage import config_loader


def _write(dir_, version: str, label: str) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    term = {"term": "主機", "aliases": [], "category": "c", "definition": f"{version}-{label}", "sources": ["x"], "status": "approved"}
    (dir_ / f"{version}.json").write_text(json.dumps({"version": version, "status": "draft", "terms": [term]}, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def roots(tmp_path, monkeypatch):
    config_root, seed_root = tmp_path / "volume" / "config", tmp_path / "image" / "glossary"
    monkeypatch.setattr(config_loader, "CONFIG_ROOT", config_root)
    monkeypatch.setattr(config_loader, "GLOSSARY_SEED_ROOT", seed_root)
    config_loader.get_glossary.cache_clear()
    yield config_root, seed_root
    config_loader.get_glossary.cache_clear()


def test_a_volume_without_a_glossary_reads_the_images_copy(roots):
    config_root, seed_root = roots
    _write(seed_root, "v2", "image")
    assert config_loader.latest_glossary_version(config_root) == "v2"
    assert config_loader.get_glossary("v2", config_root).terms[0].definition == "v2-image"


def test_the_highest_version_wins_and_the_volume_wins_a_tie(roots):
    config_root, seed_root = roots
    _write(config_root / "glossary", "v1", "volume")
    _write(seed_root, "v1", "image")
    _write(seed_root, "v2", "image")
    assert config_loader.latest_glossary_version(config_root) == "v2"
    assert config_loader.get_glossary("v1", config_root).terms[0].definition == "v1-volume"


def test_other_config_roots_ignore_the_image_copy(roots, tmp_path):
    _, seed_root = roots
    _write(seed_root, "v9", "image")
    assert config_loader.latest_glossary_version(tmp_path / "elsewhere") is None


def _simulated(**overrides) -> Glossary:
    term = GlossaryTerm(term="主機", category="主機與推進", definition="推動船舶前進的主要動力機械。", sources=["https://example.test"], status="approved")
    return Glossary(version="v2", status="approved", reviewed_by="r", reviewed_at="2026-10-02", simulated=True, terms=[term], **overrides)


def test_agent_glossary_entries_are_labelled_simulated():
    from backend.services.agent.verify import Verifier

    verifier = Verifier.__new__(Verifier)  # glossary_entries needs only these two
    verifier.glossary, verifier.stats = _simulated(), __import__("collections").Counter()
    pending: list[dict] = []
    assert verifier.glossary_entries(["主機"], pending) == [{"term": "主機", "definition": "推動船舶前進的主要動力機械。", "simulated": True}]
    assert pending == []


def test_signed_report_leaves_a_simulated_glossary_out():
    from backend.services.export import build_appendix

    session = {"differences": [], "review_state": {}, "old_meta": {}, "new_meta": {}, "title": "t"}
    appendix = build_appendix(session, is_draft=False, glossary=_simulated())
    assert appendix.glossary == [] and "模擬版" in (appendix.glossary_note or "")
