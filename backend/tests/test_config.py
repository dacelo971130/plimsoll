"""Config-driven approval roles / rulesets / policies — sourced from the real
seed files under data/store/config/ so this also regression-tests the Risk 1
naming fix (船舶技術監督, not the login-role-colliding 安全品質主管) and the
Risk 3 approval-policy enforcement decision (v4 決定 #3: enforced server-side).
"""

from __future__ import annotations

import pytest

from backend.storage.config_loader import (
    get_approval_policy,
    get_role_label_snapshot,
    get_ruleset,
    latest_ruleset_version,
    list_approval_roles,
)


def test_approval_roles_seed_matches_risk1_fix():
    roles = {r.code: r for r in list_approval_roles()}
    assert set(roles) == {"DPA", "TECH_SUPT", "FLEET_MGR", "OTHER"}
    # Risk 1: renamed away from 安全品質主管 (which collides with the login role).
    assert roles["TECH_SUPT"].label_zh == "船舶技術監督"
    assert "安全品質主管" not in roles["TECH_SUPT"].label_zh


def test_role_label_snapshot_does_not_double_up_dpas_self_bilingual_label():
    # DPA's seed label_zh already embeds "（Designated Person Ashore）";
    # TECH_SUPT's doesn't. The snapshot builder must handle both shapes
    # without ever printing the English name twice.
    assert get_role_label_snapshot("DPA") == "DPA（Designated Person Ashore）"
    assert get_role_label_snapshot("TECH_SUPT") == "船舶技術監督（Technical Superintendent）"
    assert get_role_label_snapshot("NOT_A_ROLE") is None


def test_latest_ruleset_version_is_v2():
    # W1 added rulesets/v2.json — latest_ruleset_version() is filesystem-driven
    # (highest v{N}.json present), so this flips the moment v2 exists.
    assert latest_ruleset_version() == "v2"


def test_ruleset_v1_rules_are_config_not_hardcoded():
    ruleset = get_ruleset("v1")
    rule_ids = [r.id for r in ruleset.rules]
    assert "numeric_safety" in rule_ids
    assert "default" in rule_ids


def test_ruleset_v2_adds_parts_applicability_step_order_rules():
    ruleset = get_ruleset("v2")
    rule_ids = [r.id for r in ruleset.rules]
    assert "parts_change" in rule_ids
    assert "applicability_change" in rule_ids
    assert "step_order_change" in rule_ids
    assert "numeric_safety" in rule_ids  # v1 rules still present
    assert "default" in rule_ids
    assert get_approval_policy("v2").can_approve("TECH_SUPT", "High")


@pytest.mark.parametrize(
    "role_code,risk,expected",
    [
        ("DPA", "High", True),
        ("TECH_SUPT", "High", True),
        ("FLEET_MGR", "High", False),   # ceiling is Medium
        ("FLEET_MGR", "Medium", True),
        ("OTHER", "Low", True),
        ("OTHER", "Medium", False),     # ceiling is Low
        ("UNKNOWN_ROLE", "Low", False),  # not in policy at all -> deny
    ],
)
def test_approval_policy_enforces_max_risk_per_role(role_code, risk, expected):
    policy = get_approval_policy("v1")
    assert policy.can_approve(role_code, risk) is expected
