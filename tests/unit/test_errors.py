"""Tests for the QueryShield error hierarchy.

These assert the *shape* of the hierarchy that the rest of the codebase (and
callers) rely on: a single root, and config / database / schema errors that are
distinguishable from one another. Later phases add more branches under the same
root.
"""

from __future__ import annotations

import pytest

from queryshield.errors import (
    ConfigError,
    DatabaseConnectionError,
    DatabaseError,
    DatabaseExecutionError,
    QueryShieldError,
    SchemaError,
    SchemaMetadataError,
    SchemaRetrievalError,
    SQLParseError,
)


@pytest.mark.unit
def test_all_errors_share_one_root() -> None:
    for exc_type in (
        ConfigError,
        DatabaseError,
        DatabaseConnectionError,
        DatabaseExecutionError,
        SchemaError,
        SchemaRetrievalError,
        SchemaMetadataError,
        SQLParseError,
    ):
        assert issubclass(exc_type, QueryShieldError)


@pytest.mark.unit
def test_database_connection_and_execution_are_database_errors() -> None:
    assert issubclass(DatabaseConnectionError, DatabaseError)
    assert issubclass(DatabaseExecutionError, DatabaseError)


@pytest.mark.unit
def test_config_errors_are_distinct_from_database_errors() -> None:
    # A caller must be able to tell a configuration failure apart from a database
    # failure — they are handled very differently.
    assert not issubclass(ConfigError, DatabaseError)
    assert not issubclass(DatabaseError, ConfigError)
    assert not issubclass(DatabaseConnectionError, ConfigError)


@pytest.mark.unit
def test_schema_retrieval_and_metadata_are_schema_errors() -> None:
    assert issubclass(SchemaRetrievalError, SchemaError)
    assert issubclass(SchemaMetadataError, SchemaError)


@pytest.mark.unit
def test_schema_errors_are_distinct_from_database_errors() -> None:
    # A connection failure during introspection is reported as a
    # DatabaseConnectionError; the schema-specific errors must NOT also be
    # database errors, or a caller catching DatabaseError would swallow them.
    assert not issubclass(SchemaError, DatabaseError)
    assert not issubclass(SchemaRetrievalError, DatabaseError)
    assert not issubclass(SchemaMetadataError, DatabaseError)
    assert not issubclass(DatabaseError, SchemaError)


@pytest.mark.unit
def test_schema_retrieval_and_metadata_are_distinct() -> None:
    # "the catalog query failed" and "the catalog returned nonsense" are
    # different failure modes a caller may want to handle separately.
    assert not issubclass(SchemaRetrievalError, SchemaMetadataError)
    assert not issubclass(SchemaMetadataError, SchemaRetrievalError)


@pytest.mark.unit
def test_sql_parse_error_is_distinct_from_the_other_branches() -> None:
    # Parsing is its own layer: a parse failure must not be catchable as a
    # database or schema error (a caller catching DatabaseError during a
    # connection problem must not swallow a parse failure, and vice versa).
    assert not issubclass(SQLParseError, DatabaseError)
    assert not issubclass(SQLParseError, SchemaError)
    assert not issubclass(SQLParseError, ConfigError)
    assert not issubclass(DatabaseError, SQLParseError)
    assert not issubclass(SchemaError, SQLParseError)


@pytest.mark.unit
def test_sql_parse_error_preserves_its_cause() -> None:
    # Fail-closed parsing chains the vendor parser's exception as __cause__ so
    # internal diagnostics survive even though callers depend on the QueryShield
    # type alone.
    vendor = ValueError('syntax error at or near "SELCT"')
    try:
        raise SQLParseError("could not parse candidate SQL") from vendor
    except SQLParseError as exc:
        assert exc.__cause__ is vendor


@pytest.mark.unit
def test_catching_the_root_catches_every_queryshield_error() -> None:
    for exc in (
        ConfigError("bad config"),
        DatabaseConnectionError("cannot connect"),
        DatabaseExecutionError("bad statement"),
        SchemaRetrievalError("catalog query failed"),
        SchemaMetadataError("inconsistent catalog"),
        SQLParseError("unparseable SQL"),
    ):
        assert isinstance(exc, QueryShieldError)
