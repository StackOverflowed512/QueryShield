"""QueryShield's typed error hierarchy.

Phase 2 introduces only the errors the configuration and database foundations
need. The hierarchy is intentionally small but designed to grow: later phases
add sibling errors (SQL parsing, policy denials, LLM failures, cost limits)
under the same :class:`QueryShieldError` root, so a caller can catch the whole
family or one specific failure mode.

Design rules (see ``docs/ARCHITECTURE.md`` and ADR-0022):

* Every error QueryShield raises derives from :class:`QueryShieldError`, so
  callers never have to catch a third-party driver's exception type directly.
* A configuration failure is distinguishable from a database failure, which is
  distinguishable from the (future) SQL-parsing / policy / LLM failures.
* These errors may carry *diagnostic* context, but they must never embed secrets
  (database passwords, API keys, full DSNs). Whatever raises them is responsible
  for passing already-sanitised text — see
  :func:`queryshield.db.postgres.scrub_secrets`.
"""

from __future__ import annotations


class QueryShieldError(Exception):
    """Base class for every error QueryShield raises.

    Catching this catches all QueryShield-specific failures while letting
    unrelated exceptions propagate unchanged.
    """


class ConfigError(QueryShieldError):
    """Configuration is missing, malformed, or fails validation.

    Raised at load/validation time. Invalid configuration is a fail-closed
    startup error, never a silently-applied unsafe default.
    """


class DatabaseError(QueryShieldError):
    """Base class for database-layer failures."""


class DatabaseConnectionError(DatabaseError):
    """A database connection could not be established or maintained.

    Covers unreachable servers, failed authentication, exhausted or unopened
    pools, and connection timeouts. The message is sanitised and must not
    contain credentials.
    """


class DatabaseExecutionError(DatabaseError):
    """A database statement or transaction failed to execute.

    Wraps driver-level execution failures (constraint violations, syntax errors
    in *trusted* internal SQL, errors raised while committing, and so on) so
    callers depend on QueryShield's error model rather than a specific driver's
    exception classes.
    """
