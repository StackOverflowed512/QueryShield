"""QueryShield's typed error hierarchy.

Phase 2 introduced the errors the configuration and database foundations need;
Phase 3 adds the schema-introspection errors under the same root. The hierarchy
is intentionally small but designed to grow: later phases add sibling errors
(SQL parsing, policy denials, LLM failures, cost limits) under the same
:class:`QueryShieldError` root, so a caller can catch the whole family or one
specific failure mode.

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


class SchemaError(QueryShieldError):
    """Base class for schema-introspection failures.

    Schema retrieval sits on top of the database layer, so a *connection*
    failure during introspection is reported as a
    :class:`DatabaseConnectionError` (it is a database-reachability problem, not
    a schema problem). The two failures below are the ones that are specific to
    reading and interpreting the catalog.
    """


class SchemaRetrievalError(SchemaError):
    """A catalog query needed to introspect the schema failed to execute.

    The database was reachable, but a ``pg_catalog`` / ``information_schema``
    query QueryShield issued did not complete (for example, it was cancelled by
    ``statement_timeout`` or rejected by permissions). This is fail-closed: the
    retriever raises rather than returning a partial or empty catalog, because an
    empty database and a failed introspection must never look alike.
    """


class SchemaMetadataError(SchemaError):
    """The catalog returned metadata that was malformed or internally inconsistent.

    Raised when assembling the snapshot reveals something that should be
    impossible for a coherent catalog — e.g. a column, constraint, or index that
    refers to a relation the same introspection did not report. Fail-closed: a
    surprising catalog shape is surfaced, never silently discarded, so a parser
    differential or a privilege anomaly cannot pass unnoticed.
    """


class SQLParseError(QueryShieldError):
    """The supplied SQL could not be parsed into a trustworthy structure.

    Raised by the SQL-parsing layer when the candidate SQL is not valid in the
    configured dialect. This is a **fail-closed** error: the parser returns a
    complete, structurally analysed result or it raises; it never returns an
    empty or partial AST, never "best-effort" parses, and never falls back to a
    different dialect to make something parse (see ADR-0031). The underlying
    parser's exception is attached as ``__cause__`` so the diagnostic detail is
    preserved for logging, while callers depend only on this QueryShield type.

    That the untrusted SQL failed to parse is not itself a security decision —
    it simply means no trustworthy structure could be derived, and downstream
    layers that fail closed will therefore deny the request.
    """
