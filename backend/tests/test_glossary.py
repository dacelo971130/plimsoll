"""The controlled glossary (the highest data/store/config/glossary/v{N}.json)
is the only place the review agent, the sign-off report appendix and the help
page may take a term definition from — "不自創" rests on it. These checks keep
it honest: every entry carries a definition and a status, and every source it
cites still resolves — a repo path that exists, or a link to one of the
authorities the glossary is built from (全國法規資料庫 for statutory
definitions, 樂詞網 for standard term pairs) — so a renamed file or a mistyped
link surfaces here instead of leaving a definition that points at nothing."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from backend.config import CONFIG_ROOT, REPO_ROOT

GLOSSARY_DIR = CONFIG_ROOT / "glossary"

# Where an https source may point. Anything else is a typo or an unvetted site.
LAW_HOST = "law.moj.gov.tw"
SOURCE_HOSTS = {LAW_HOST, "opendata.naer.edu.tw", "terms.naer.edu.tw"}


def _latest_path():
    return max(GLOSSARY_DIR.glob("v*.json"), key=lambda p: int(p.stem.lstrip("v")))


def _load() -> dict:
    return json.loads(_latest_path().read_text(encoding="utf-8"))


def _source_target(source: str) -> str:
    """The link or repo path of a source — what's left of the 「（…）」 remark."""
    return source.split("（", 1)[0].strip()


def _names(entry: dict) -> list[str]:
    return [entry["term"], *entry.get("aliases", [])]


def test_top_level_status_is_known_and_unapproved_until_reviewed():
    data = _load()
    assert data["status"] in {"draft", "approved"}
    if data["status"] == "approved":
        assert data["reviewed_by"] and data["reviewed_at"]
    if data.get("simulated"):
        # A stand-in table is approved only so the agent may cite it; the
        # sign-off record must still say whose call that was and that it's 模擬版.
        assert data["status"] == "approved" and "模擬版" in data["reviewed_by"]


def test_every_term_has_definition_sources_and_status():
    for entry in _load()["terms"]:
        assert entry["term"].strip()
        assert entry["definition"].strip()
        assert entry["sources"], entry["term"]
        assert entry["status"] in {"draft", "pending", "approved"}, entry["term"]


def test_terms_are_unique_including_aliases():
    seen: set[str] = set()
    for entry in _load()["terms"]:
        for name in _names(entry):
            assert name not in seen, f"duplicate glossary name: {name}"
            seen.add(name)


def test_no_two_entries_share_a_name_once_case_and_spacing_are_ignored():
    # "A 級隔艙" vs "A級隔艙", "Turbocharger" vs "turbocharger": the agent matches
    # exact strings, but a reader sees one name twice. Within one entry that's
    # fine (a spaced term plus its unspaced alias); across entries it isn't.
    owner: dict[str, str] = {}
    for entry in _load()["terms"]:
        for name in _names(entry):
            key = re.sub(r"\s+", "", name).lower()
            assert owner.setdefault(key, entry["term"]) == entry["term"], f"{name!r}: {entry['term']} vs {owner[key]}"


def test_every_cited_source_resolves():
    for entry in _load()["terms"]:
        for source in entry["sources"]:
            target = _source_target(source)
            if target.startswith("https://"):
                assert urlparse(target).hostname in SOURCE_HOSTS, f"{entry['term']}: unexpected source host in {target}"
                assert re.fullmatch(r"https://\S+", target), f"{entry['term']}: malformed link {target!r}"
                continue
            matches = list(REPO_ROOT.glob(target)) if "*" in target else [REPO_ROOT / target]
            assert matches and all(m.exists() for m in matches), f"{entry['term']}: {target} not found"


def test_statutory_sources_name_their_law_and_article():
    # 「https://law.moj.gov.tw/…?pcode=K0070004（船舶法 第3條第1款）」 — the link alone
    # doesn't say which clause the definition was copied from.
    for entry in _load()["terms"]:
        for source in entry["sources"]:
            if _source_target(source).startswith(f"https://{LAW_HOST}/"):
                assert "pcode=" in source, f"{entry['term']}: law link without pcode"
                assert re.search(r"（\S+ 第\d+(?:-\d+)?條", source),f"{entry['term']}: law source lacks 法規名稱 第N條 — {source}"


def test_a_definition_that_is_not_statutory_says_it_is_a_draft():
    # Standard-term pairs come from 樂詞網, but the definition text is an AI draft;
    # an entry resting only on such links must carry that mark in a source.
    for entry in _load()["terms"]:
        targets = [_source_target(s) for s in entry["sources"]]
        if all(t.startswith("https://") for t in targets) and not any(f"//{LAW_HOST}/" in t for t in targets):
            assert any("模擬版草稿" in s for s in entry["sources"]), f"{entry['term']}: draft definition isn't marked"


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
