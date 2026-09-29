"""Local-first storage backbone (architecture-decisions-A-B.md §19-24).

- `events`: append-only `review_events.jsonl` + fold projection + prefix-hash
  integrity anchor.
- `config_loader`: versioned config (`approval_roles.json`,
  `rulesets/v{N}.json`, `approval_policies/v{N}.json`) — never hardcoded.
- `sync_target`: pluggable upstream DB contract. P0 ships the interface and a
  `NullSyncTarget`; a real adapter lands in a later phase.
"""
