"""QueryShield database layer: the abstraction plus the PostgreSQL adapter.

This subpackage is a **trusted, lower-level** component. The adapter executes the
SQL it is handed; it does **not** decide whether a query is authorized. In the
full pipeline it runs *after* the (future) deterministic security layers have
validated a query, and it must never be wired directly to user- or LLM-supplied
SQL. See the trust boundary in :mod:`queryshield.db.base`, ``docs/ARCHITECTURE.md``,
and ADR-0019.
"""

from __future__ import annotations

from queryshield.db.base import DatabaseAdapter, DatabaseSession, HealthCheckResult, Row
from queryshield.db.postgres import PostgreSQLAdapter, sanitize_dsn

__all__ = [
    "DatabaseAdapter",
    "DatabaseSession",
    "HealthCheckResult",
    "PostgreSQLAdapter",
    "Row",
    "sanitize_dsn",
]
