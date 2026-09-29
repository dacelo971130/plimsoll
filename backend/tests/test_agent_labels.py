"""The agent's rule labels must match the UI's word for word — otherwise the
briefing and the difference card call the same rule two different names."""

from __future__ import annotations

import re

from backend.config import REPO_ROOT
from backend.services.agent.labels import RULE_LABEL


def test_backend_rule_labels_match_frontend_rule_labels():
    ts = (REPO_ROOT / "frontend" / "src" / "lib" / "ruleLabels.ts").read_text(encoding="utf-8")
    frontend = dict(re.findall(r"^\s*(\w+):\s*'([^']*)',", ts, flags=re.M))
    assert frontend == RULE_LABEL
