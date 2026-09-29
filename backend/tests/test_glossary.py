"""The controlled glossary (data/store/config/glossary/v1.json) is the only
place the review agent, the sign-off report appendix and the help page may
take a term definition from — "不自創" rests on it. These checks keep it
honest: every entry carries a definition and a status, and every source it
cites still exists in the repo, so a renamed or deleted file surfaces here
instead of leaving a definition that points at nothing."""

from __future__ import annotations

import json

from backend.config import CONFIG_ROOT, REPO_ROOT

GLOSSARY = CONFIG_ROOT / "glossary" / "v1.json"


def _load() -> dict:
    return json.loads(GLOSSARY.read_text(encoding="utf-8"))


def test_top_level_status_is_known_and_unapproved_until_reviewed():
    data = _load()
    assert data["status"] in {"draft", "approved"}
    if data["status"] == "approved":
        assert data["reviewed_by"] and data["reviewed_at"]


def test_every_term_has_definition_sources_and_status():
    for entry in _load()["terms"]:
        assert entry["term"].strip()
        assert entry["definition"].strip()
        assert entry["sources"], entry["term"]
        assert entry["status"] in {"draft", "pending", "approved"}, entry["term"]


def test_terms_are_unique_including_aliases():
    seen: set[str] = set()
    for entry in _load()["terms"]:
        for name in [entry["term"], *entry.get("aliases", [])]:
            assert name not in seen, f"duplicate glossary name: {name}"
            seen.add(name)


def test_every_cited_source_path_exists():
    for entry in _load()["terms"]:
        for source in entry["sources"]:
            path = source.split("（", 1)[0].strip()
            matches = list(REPO_ROOT.glob(path)) if "*" in path else [REPO_ROOT / path]
            assert matches and all(m.exists() for m in matches), f"{entry['term']}: {path} not found"


def test_file_parses_as_the_glossary_model():
    from backend.storage.config_loader import get_glossary, latest_glossary_version

    version = latest_glossary_version()
    assert version == _load()["version"]
    assert len(get_glossary(version).terms) == len(_load()["terms"])


def test_api_serves_definitions_without_repo_paths():
    from fastapi.testclient import TestClient

    from backend.main import app

    body = TestClient(app).get("/api/config/glossary").json()
    assert body["status"] == _load()["status"]
    assert len(body["terms"]) == len(_load()["terms"])
    assert all("sources" not in t for t in body["terms"])
    assert {"term", "category", "definition", "status"} <= set(body["terms"][0])


def test_api_survives_a_missing_glossary(monkeypatch):
    # A Docker volume seeded before glossary/ existed has no file at all.
    from fastapi.testclient import TestClient

    import backend.api.system as system
    from backend.main import app

    monkeypatch.setattr(system, "latest_glossary_version", lambda: None)
    res = TestClient(app).get("/api/config/glossary")
    assert res.status_code == 200
    assert res.json()["terms"] == []
