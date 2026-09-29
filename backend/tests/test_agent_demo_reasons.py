"""The demo PDFs carry a fictional revision reason on each version's
版本異動摘要 page (review-agent bonus item 「變更原因追溯」). Adding them must
not change what the demo shows: no digits (a number-with-unit would start a
parameter series and muddy the drift demo) and no ruleset vocabulary (a
safety/obligation term would turn a revision note into a High change —
padding the demo, which the subtraction matrix's not-do list forbids)."""

from __future__ import annotations

import importlib.util
import re

import pymupdf
import pytest

from backend.config import REPO_ROOT
from backend.storage.config_loader import get_ruleset, latest_ruleset_version

_spec = importlib.util.spec_from_file_location("generate_demo_pdfs", REPO_ROOT / "scripts" / "generate_demo_pdfs.py")
generator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generator)
REASONS: dict[str, str] = generator.REVISION_REASONS


def test_reasons_have_no_digits_and_no_rule_vocabulary():
    ruleset = get_ruleset(latest_ruleset_version())
    vocabulary = {*ruleset.safety_terms, *ruleset.obligation_terms, *ruleset.applicability_terms}
    for version, reason in REASONS.items():
        assert not re.search(r"\d", reason), version
        hits = [term for term in vocabulary if term.lower() in reason.lower()]
        assert hits == [], f"{version} uses rule vocabulary {hits}"


@pytest.mark.parametrize("version", sorted(REASONS))
def test_each_demo_pdf_states_its_reason(version):
    doc = pymupdf.open(REPO_ROOT / "data" / "demo" / f"Main_Engine_Cooling_{version}.pdf")
    text = re.sub(r"\s+", "", doc[-1].get_text())
    assert re.sub(r"\s+", "", REASONS[version]) in text
