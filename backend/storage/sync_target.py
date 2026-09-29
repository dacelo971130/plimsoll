"""Pluggable upstream `SyncTarget` contract (architecture-decisions-A-B.md §23).

LocalStore is always the commit point; a `SyncTarget` is a best-effort,
optional downstream mirror. P0 ships the interface plus `NullSyncTarget`
(always disconnected — the correct default so startup never depends on a
database, per §24). A real adapter (SQLAlchemy Core against
SQLite/Postgres/MySQL) is deliberately deferred to a later phase; wiring it
in should not require touching `events.py`.
"""

from __future__ import annotations

from typing import Protocol


class SyncTarget(Protocol):
    def is_connected(self) -> bool: ...

    def ingest_events(self, events: list[dict]) -> None: ...

    def ingest_config(self, *, approval_roles: list[dict], rulesets: list[dict], approval_policies: list[dict]) -> None: ...


class NullSyncTarget:
    """The P0 default: no DB configured. Always reports disconnected so the
    global status dot is grey and every session stays tagged `本機`."""

    def is_connected(self) -> bool:
        return False

    def ingest_events(self, events: list[dict]) -> None:  # pragma: no cover - never called
        raise NotImplementedError("NullSyncTarget never accepts writes; is_connected() gates this")

    def ingest_config(self, **kwargs) -> None:  # pragma: no cover - never called
        raise NotImplementedError("NullSyncTarget never accepts writes; is_connected() gates this")


_singleton: SyncTarget = NullSyncTarget()


def get_sync_target() -> SyncTarget:
    """Single process-wide sync target. A future phase swaps this for a
    config-driven adapter (config/app.json `db_connection_string`), without
    changing any caller."""
    return _singleton
