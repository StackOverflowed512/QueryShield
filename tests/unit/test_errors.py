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
def test_catching_the_root_catches_every_queryshield_error() -> None:
    for exc in (
        ConfigError("bad config"),
        DatabaseConnectionError("cannot connect"),
        DatabaseExecutionError("bad statement"),
        SchemaRetrievalError("catalog query failed"),
        SchemaMetadataError("inconsistent catalog"),
    ):
        assert isinstance(exc, QueryShieldError)
