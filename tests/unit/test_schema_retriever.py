"""Unit tests for the PostgreSQL schema retriever's *logic*, without a database.

Two things are tested here, both without touching PostgreSQL:

* **The pure assembler** (:func:`_assemble_catalog`) — fed synthetic catalog
  rows, it must build the right :class:`SchemaCatalog`, and it must **fail
  closed** (raise :class:`SchemaMetadataError`) on any internally inconsistent
  catalog rather than silently dropping the offending object.
* **The retriever's error contract and query shape** — exercised through a fully
  typed fake :class:`~queryshield.db.base.DatabaseAdapter`. A reachable-but-
  failing catalog query becomes a :class:`SchemaRetrievalError` (chained); a
  connection failure propagates unchanged; a malformed catalog surfaces as a
  :class:`SchemaMetadataError`; introspection runs in **one read-only
  transaction**; selected schema names are passed as a **bound parameter**, never
  interpolated; and an empty selection short-circuits the per-object queries.

The real catalog SQL is validated against a live database in
``tests/integration/test_schema_retriever.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import pytest

from queryshield.db import DatabaseAdapter, DatabaseSession, HealthCheckResult, Row
from queryshield.errors import (
    DatabaseConnectionError,
    DatabaseExecutionError,
    SchemaError,
    SchemaMetadataError,
    SchemaRetrievalError,
)
from queryshield.schema import PostgreSQLSchemaRetriever, SchemaCatalog, SchemaFilter
from queryshield.schema.postgres import _assemble_catalog, _RawRows


def _row(*values: Any) -> Row:
    """Build one positional catalog row (``Row`` is ``tuple[Any, ...]``)."""
    return tuple(values)


# ---------------------------------------------------------------------------
# A fake adapter + session. The session dispatches each catalog query to a
# canned result by matching a marker unique to that statement, so the tests do
# not depend on the exact SQL text — only on which logical query ran.
# ---------------------------------------------------------------------------


def _tag(query: str) -> str:
    """Classify a catalog statement by a substring unique to it."""
    if "pg_index ix" in query:
        return "indexes"
    if "con.contype = 'f'" in query:
        return "foreign_keys"
    if "con.contype IN ('p', 'u')" in query:
        return "keys"
    if "a.attnotnull" in query:
        return "columns"
    if "c.relkind," in query:
        return "relations"
    return "schemas"


class _FakeSession:
    """Structurally satisfies :class:`~queryshield.db.base.DatabaseSession`."""

    def __init__(
        self,
        responses: dict[str, list[Row]],
        *,
        fail_on: str | None = None,
        failure: Exception | None = None,
    ) -> None:
        self._responses = responses
        self._fail_on = fail_on
        self._failure = failure
        self.calls: list[str] = []
        self.bound: dict[str, Sequence[Any] | None] = {}

    async def execute(
        self, query: str, params: Sequence[Any] | None = None
    ) -> None:  # pragma: no cover - introspection never issues execute()
        raise NotImplementedError

    async def fetch_all(
        self, query: str, params: Sequence[Any] | None = None
    ) -> list[Row]:
        tag = _tag(query)
        self.calls.append(tag)
        self.bound[tag] = params
        if self._fail_on == tag and self._failure is not None:
            raise self._failure
        return self._responses.get(tag, [])

    async def fetch_one(
        self, query: str, params: Sequence[Any] | None = None
    ) -> Row | None:  # pragma: no cover - introspection never issues fetch_one()
        raise NotImplementedError


class _FakeAdapter(DatabaseAdapter):
    """A minimal adapter whose only live method is :meth:`transaction`."""

    def __init__(
        self,
        session: _FakeSession,
        *,
        connect_error: Exception | None = None,
    ) -> None:
        self._session = session
        self._connect_error = connect_error
        self.transactions: list[bool] = []

    async def open(self) -> None:  # pragma: no cover - lifecycle unused here
        raise NotImplementedError

    async def close(self) -> None:  # pragma: no cover - lifecycle unused here
        raise NotImplementedError

    async def health_check(self) -> HealthCheckResult:  # pragma: no cover
        raise NotImplementedError

    def transaction(
        self, *, read_only: bool = True
    ) -> AbstractAsyncContextManager[DatabaseSession]:
        self.transactions.append(read_only)
        return self._open_transaction()

    @asynccontextmanager
    async def _open_transaction(self) -> AsyncIterator[DatabaseSession]:
        if self._connect_error is not None:
            raise self._connect_error
        yield self._session

    async def execute(
        self,
        query: str,
        params: Sequence[Any] | None = None,
        *,
        read_only: bool = True,
    ) -> None:  # pragma: no cover - convenience method unused here
        raise NotImplementedError

    async def fetch_all(
        self,
        query: str,
        params: Sequence[Any] | None = None,
        *,
        read_only: bool = True,
    ) -> list[Row]:  # pragma: no cover - convenience method unused here
        raise NotImplementedError

    async def fetch_one(
        self,
        query: str,
        params: Sequence[Any] | None = None,
        *,
        read_only: bool = True,
    ) -> Row | None:  # pragma: no cover - convenience method unused here
        raise NotImplementedError


def _full_responses() -> dict[str, list[Row]]:
    """A small but complete, internally consistent catalog across two schemas."""
    return {
        # (nspname, comment) — intentionally app-before-analytics to prove the
        # catalog sorts regardless of discovery order.
        "schemas": [_row("app", "application"), _row("analytics", None)],
        # (schema, relname, relkind, comment)
        "relations": [
            _row("app", "users", "r", "people"),
            _row("app", "active", "v", None),
            _row("analytics", "events", "r", None),
            _row("analytics", "report", "m", "rollup"),
        ],
        # (schema, relname, attname, attnum, attnotnull, type, default, comment)
        "columns": [
            _row("app", "users", "id", 1, True, "integer", None, None),
            _row("app", "users", "email", 2, False, "text", None, "contact"),
            _row("app", "active", "id", 1, False, "integer", None, None),
            _row("analytics", "events", "id", 1, True, "bigint", None, None),
            _row("analytics", "events", "user_id", 2, False, "integer", None, None),
            _row("analytics", "report", "total", 1, False, "bigint", None, None),
        ],
        # (schema, relname, conname, contype, columns[])
        "keys": [
            _row("app", "users", "users_pkey", "p", ["id"]),
            _row("app", "users", "users_email_key", "u", ["email"]),
            _row("analytics", "events", "events_pkey", "p", ["id"]),
        ],
        # (schema, relname, conname, columns[], ref_schema, ref_table, ref_cols[])
        "foreign_keys": [
            _row(
                "analytics",
                "events",
                "events_user_fk",
                ["user_id"],
                "app",
                "users",
                ["id"],
            ),
        ],
        # (schema, table, index_name, is_unique, is_primary, key_columns[])
        "indexes": [
            _row("app", "users", "users_pkey", True, True, ["id"]),
            _row("analytics", "events", "events_pkey", True, True, ["id"]),
            _row("analytics", "report", "report_idx", False, False, ["total"]),
        ],
    }


# ---------------------------------------------------------------------------
# The pure assembler: structure
# ---------------------------------------------------------------------------


def _assemble(
    *,
    schemas: list[Row] | None = None,
    relations: list[Row] | None = None,
    columns: list[Row] | None = None,
    keys: list[Row] | None = None,
    foreign_keys: list[Row] | None = None,
    indexes: list[Row] | None = None,
    selected: list[str] | None = None,
) -> SchemaCatalog:
    return _assemble_catalog(
        _RawRows(
            schemas=schemas or [],
            relations=relations or [],
            columns=columns or [],
            keys=keys or [],
            foreign_keys=foreign_keys or [],
            indexes=indexes or [],
            selected=selected or [],
        )
    )


@pytest.mark.unit
def test_assemble_classifies_relkinds() -> None:
    catalog = _assemble(
        relations=[
            _row("s", "reg", "r", None),
            _row("s", "part", "p", None),
            _row("s", "vw", "v", None),
            _row("s", "mv", "m", None),
        ],
        selected=["s"],
    )
    schema = catalog.get_schema("s")
    assert schema is not None
    assert {t.name for t in schema.tables} == {"reg", "part"}
    assert {v.name for v in schema.views} == {"vw", "mv"}
    mv = schema.get_view("mv")
    vw = schema.get_view("vw")
    assert mv is not None and mv.materialized is True
    assert vw is not None and vw.materialized is False


@pytest.mark.unit
def test_assemble_composite_primary_key() -> None:
    catalog = _assemble(
        relations=[_row("s", "t", "r", None)],
        keys=[_row("s", "t", "t_pk", "p", ["a", "b"])],
        selected=["s"],
    )
    table = catalog.get_table("s", "t")
    assert table is not None
    assert table.primary_key is not None
    assert table.primary_key.columns == ("a", "b")


@pytest.mark.unit
def test_assemble_cross_schema_foreign_key() -> None:
    catalog = _assemble(
        relations=[_row("app", "users", "r", None), _row("sales", "orders", "r", None)],
        foreign_keys=[
            _row("sales", "orders", "fk", ["buyer"], "app", "users", ["id"]),
        ],
        selected=["app", "sales"],
    )
    orders = catalog.get_table("sales", "orders")
    assert orders is not None
    (fk,) = orders.foreign_keys
    assert fk.columns == ("buyer",)
    assert fk.referenced_schema == "app"
    assert fk.referenced_table == "users"
    assert fk.referenced_columns == ("id",)


@pytest.mark.unit
def test_assemble_builds_the_full_catalog() -> None:
    r = _full_responses()
    catalog = _assemble(
        schemas=r["schemas"],
        relations=r["relations"],
        columns=r["columns"],
        keys=r["keys"],
        foreign_keys=r["foreign_keys"],
        indexes=r["indexes"],
        selected=["app", "analytics"],
    )
    assert catalog.schema_names == ("analytics", "app")

    users = catalog.get_table("app", "users")
    assert users is not None
    assert [c.name for c in users.columns] == ["id", "email"]
    id_col = users.get_column("id")
    assert id_col is not None and id_col.nullable is False
    assert id_col.data_type == "integer"
    assert users.primary_key is not None
    assert users.primary_key.columns == ("id",)
    assert users.unique_constraints[0].columns == ("email",)
    assert any(i.primary for i in users.indexes)

    report = catalog.get_view("analytics", "report")
    assert report is not None and report.materialized is True
    assert [i.name for i in report.indexes] == ["report_idx"]


# ---------------------------------------------------------------------------
# The pure assembler: fail-closed on an inconsistent catalog
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.security
def test_column_for_unknown_relation_is_metadata_error() -> None:
    with pytest.raises(SchemaMetadataError):
        _assemble(
            columns=[_row("app", "ghost", "c", 1, True, "text", None, None)],
            selected=["app"],
        )


@pytest.mark.unit
@pytest.mark.security
def test_constraint_for_unknown_table_is_metadata_error() -> None:
    with pytest.raises(SchemaMetadataError):
        _assemble(keys=[_row("app", "ghost", "pk", "p", ["id"])], selected=["app"])


@pytest.mark.unit
@pytest.mark.security
def test_constraint_without_columns_is_metadata_error() -> None:
    with pytest.raises(SchemaMetadataError):
        _assemble(
            relations=[_row("app", "t", "r", None)],
            keys=[_row("app", "t", "pk", "p", None)],
            selected=["app"],
        )


@pytest.mark.unit
@pytest.mark.security
def test_multiple_primary_keys_is_metadata_error() -> None:
    with pytest.raises(SchemaMetadataError):
        _assemble(
            relations=[_row("app", "t", "r", None)],
            keys=[
                _row("app", "t", "pk1", "p", ["id"]),
                _row("app", "t", "pk2", "p", ["other"]),
            ],
            selected=["app"],
        )


@pytest.mark.unit
@pytest.mark.security
def test_foreign_key_for_unknown_table_is_metadata_error() -> None:
    with pytest.raises(SchemaMetadataError):
        _assemble(
            foreign_keys=[_row("app", "ghost", "fk", ["c"], "app", "o", ["id"])],
            selected=["app"],
        )


@pytest.mark.unit
@pytest.mark.security
def test_foreign_key_with_mismatched_columns_is_metadata_error() -> None:
    with pytest.raises(SchemaMetadataError):
        _assemble(
            relations=[_row("app", "t", "r", None)],
            foreign_keys=[_row("app", "t", "fk", ["a", "b"], "app", "o", ["id"])],
            selected=["app"],
        )


@pytest.mark.unit
@pytest.mark.security
def test_index_without_columns_is_metadata_error() -> None:
    with pytest.raises(SchemaMetadataError):
        _assemble(
            relations=[_row("app", "t", "r", None)],
            indexes=[_row("app", "t", "idx", False, False, None)],
            selected=["app"],
        )


@pytest.mark.unit
@pytest.mark.security
def test_index_for_unknown_relation_is_metadata_error() -> None:
    with pytest.raises(SchemaMetadataError):
        _assemble(
            indexes=[_row("app", "ghost", "idx", False, False, ["c"])],
            selected=["app"],
        )


# ---------------------------------------------------------------------------
# The retriever: end-to-end through the fake adapter, and the error contract
# ---------------------------------------------------------------------------


async def test_retrieve_returns_assembled_catalog() -> None:
    session = _FakeSession(_full_responses())
    retriever = PostgreSQLSchemaRetriever(_FakeAdapter(session))

    catalog = await retriever.retrieve()

    assert catalog.schema_names == ("analytics", "app")
    assert catalog.fingerprint.startswith("sha256:")
    events = catalog.get_table("analytics", "events")
    assert events is not None
    assert events.foreign_keys[0].referenced_table == "users"
    # Every logical catalog query ran exactly once, in dependency order.
    assert session.calls == [
        "schemas",
        "relations",
        "columns",
        "keys",
        "foreign_keys",
        "indexes",
    ]


async def test_retrieve_uses_a_single_read_only_transaction() -> None:
    session = _FakeSession(_full_responses())
    adapter = _FakeAdapter(session)
    await PostgreSQLSchemaRetriever(adapter).retrieve()
    # Exactly one transaction, and it was read-only (security by default).
    assert adapter.transactions == [True]


@pytest.mark.security
async def test_selected_schema_names_are_passed_as_bound_parameter() -> None:
    # The discovered schema names must reach the catalog queries as a *bound*
    # array parameter, never interpolated into the SQL text.
    session = _FakeSession(_full_responses())
    await PostgreSQLSchemaRetriever(_FakeAdapter(session)).retrieve()
    assert session.bound["schemas"] is None  # the schema sweep binds nothing
    assert session.bound["relations"] == [["app", "analytics"]]
    assert session.bound["indexes"] == [["app", "analytics"]]


@pytest.mark.security
async def test_execution_failure_becomes_retrieval_error_with_cause() -> None:
    cause = DatabaseExecutionError("statement timeout")
    session = _FakeSession(
        {"schemas": [_row("app", None)]}, fail_on="relations", failure=cause
    )
    retriever = PostgreSQLSchemaRetriever(_FakeAdapter(session))

    with pytest.raises(SchemaRetrievalError) as exc_info:
        await retriever.retrieve()
    # Fail closed, and preserve the diagnostic chain.
    assert exc_info.value.__cause__ is cause


@pytest.mark.security
async def test_connection_failure_propagates_unchanged() -> None:
    # A connection failure is a database-reachability problem, not a schema
    # problem: it must NOT be re-wrapped as a SchemaError.
    session = _FakeSession(_full_responses())
    adapter = _FakeAdapter(session, connect_error=DatabaseConnectionError("down"))
    retriever = PostgreSQLSchemaRetriever(adapter)

    with pytest.raises(DatabaseConnectionError) as exc_info:
        await retriever.retrieve()
    assert not isinstance(exc_info.value, SchemaError)
    assert session.calls == []  # we never got a session


@pytest.mark.security
async def test_inconsistent_catalog_surfaces_as_metadata_error() -> None:
    # Reachable database, every query succeeds, but the rows are inconsistent (a
    # column for a relation the relations query did not report). This must be a
    # SchemaMetadataError raised from assembly — distinct from a retrieval error.
    responses = {
        "schemas": [_row("app", None)],
        "columns": [_row("app", "ghost", "c", 1, True, "text", None, None)],
    }
    retriever = PostgreSQLSchemaRetriever(_FakeAdapter(_FakeSession(responses)))

    with pytest.raises(SchemaMetadataError):
        await retriever.retrieve()


@pytest.mark.security
async def test_empty_selection_short_circuits_object_queries() -> None:
    # An explicit empty allow-list selects no schema; the retriever must return an
    # empty catalog WITHOUT issuing any per-object query (and never claim failure).
    session = _FakeSession(_full_responses())
    retriever = PostgreSQLSchemaRetriever(
        _FakeAdapter(session), schema_filter=SchemaFilter.from_names(include=[])
    )

    catalog = await retriever.retrieve()

    assert catalog.is_empty
    assert session.calls == ["schemas"]


async def test_default_filter_excludes_system_schemas_end_to_end() -> None:
    session = _FakeSession(
        {
            "schemas": [_row("pg_catalog", None), _row("app", None)],
            "relations": [_row("app", "t", "r", None)],
        }
    )
    retriever = PostgreSQLSchemaRetriever(_FakeAdapter(session))

    catalog = await retriever.retrieve()

    assert catalog.schema_names == ("app",)
    assert session.bound["relations"] == [["app"]]
