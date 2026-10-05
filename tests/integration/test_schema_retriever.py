"""Integration tests for :class:`PostgreSQLSchemaRetriever` against real PostgreSQL.

Every object these tests introspect is created dynamically inside a uniquely
named schema and dropped afterwards (``DROP SCHEMA ... CASCADE``). There is **no**
fixed demo schema: table, column, key, index, and view names are all
test-generated (a uuid suffix), so nothing about the retriever is allowed to
depend on a particular database's contents.

The suite covers the Phase 3 spec's required cases: multiple schemas; tables and
views (plain + materialized); columns with varied types, nullability, and
defaults; single and composite primary keys; a cross-schema foreign key; normal
and unique indexes; table/column/schema comments; non-trivial identifiers
(mixed case, spaces); fingerprint determinism and sensitivity; and fail-closed
behaviour on a connection failure (never an empty catalog).

Marked ``integration``; skips when ``QUERYSHIELD_TEST_DATABASE_URL`` is unset.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
import pytest_asyncio
from pydantic import SecretStr

from queryshield.config import DatabaseConfig
from queryshield.db import PostgreSQLAdapter
from queryshield.errors import DatabaseConnectionError
from queryshield.schema import PostgreSQLSchemaRetriever, SchemaCatalog, SchemaFilter

pytestmark = pytest.mark.integration


def _quote(identifier: str) -> str:
    """Quote a PostgreSQL identifier (test-generated names only)."""
    return '"' + identifier.replace('"', '""') + '"'


async def _run(adapter: PostgreSQLAdapter, *statements: str) -> None:
    """Run DDL statements in one read-write transaction."""
    async with adapter.transaction(read_only=False) as session:
        for statement in statements:
            await session.execute(statement)


def _retriever(adapter: PostgreSQLAdapter, *schemas: str) -> PostgreSQLSchemaRetriever:
    """A retriever scoped to exactly the named schemas."""
    return PostgreSQLSchemaRetriever(
        adapter, schema_filter=SchemaFilter.from_names(include=list(schemas))
    )


@pytest_asyncio.fixture
async def temp_schema(adapter: PostgreSQLAdapter) -> AsyncIterator[str]:
    """Create a uniquely named empty schema; drop it (CASCADE) afterwards."""
    name = f"qs_it_{uuid4().hex}"
    await adapter.execute(f"CREATE SCHEMA {_quote(name)}", read_only=False)
    try:
        yield name
    finally:
        await adapter.execute(f"DROP SCHEMA {_quote(name)} CASCADE", read_only=False)


# ---------------------------------------------------------------------------
# Tables, views, and columns
# ---------------------------------------------------------------------------


async def test_discovers_tables_views_and_columns(
    adapter: PostgreSQLAdapter, temp_schema: str
) -> None:
    s = _quote(temp_schema)
    widget = f"widget_{uuid4().hex}"
    view = f"widget_v_{uuid4().hex}"
    matview = f"widget_mv_{uuid4().hex}"
    await _run(
        adapter,
        f"""
        CREATE TABLE {s}.{_quote(widget)} (
            id integer PRIMARY KEY,
            name text NOT NULL,
            qty integer NOT NULL DEFAULT 0,
            price numeric(10,2),
            label text
        )
        """,
        f"CREATE VIEW {s}.{_quote(view)} AS SELECT id, name FROM {s}.{_quote(widget)}",
        f"CREATE MATERIALIZED VIEW {s}.{_quote(matview)} AS "
        f"SELECT id FROM {s}.{_quote(widget)}",
    )

    catalog = await _retriever(adapter, temp_schema).retrieve()
    schema = catalog.get_schema(temp_schema)
    assert schema is not None

    table = schema.get_table(widget)
    assert table is not None
    assert [c.name for c in table.columns] == ["id", "name", "qty", "price", "label"]
    assert [c.ordinal for c in table.columns] == [1, 2, 3, 4, 5]

    id_col = table.get_column("id")
    name_col = table.get_column("name")
    qty_col = table.get_column("qty")
    price_col = table.get_column("price")
    label_col = table.get_column("label")
    assert id_col is not None and id_col.nullable is False
    assert id_col.data_type == "integer"
    assert name_col is not None and name_col.nullable is False
    assert qty_col is not None and qty_col.nullable is False and qty_col.default == "0"
    assert price_col is not None and price_col.nullable is True
    assert price_col.data_type == "numeric(10,2)"
    assert label_col is not None and label_col.nullable is True
    assert label_col.default is None

    plain = schema.get_view(view)
    materialized = schema.get_view(matview)
    assert plain is not None and plain.materialized is False
    assert [c.name for c in plain.columns] == ["id", "name"]
    assert materialized is not None and materialized.materialized is True
    # A view is not reported as a table and vice versa.
    assert schema.get_table(view) is None
    assert schema.get_view(widget) is None


async def test_discovers_multiple_schemas(adapter: PostgreSQLAdapter) -> None:
    first = f"qs_it_{uuid4().hex}"
    second = f"qs_it_{uuid4().hex}"
    await _run(
        adapter,
        f"CREATE SCHEMA {_quote(first)}",
        f"CREATE SCHEMA {_quote(second)}",
        f"CREATE TABLE {_quote(first)}.t (id integer)",
        f"CREATE TABLE {_quote(second)}.t (id integer)",
    )
    try:
        catalog = await _retriever(adapter, first, second).retrieve()
        assert catalog.schema_names == tuple(sorted((first, second)))
        assert catalog.get_table(first, "t") is not None
        assert catalog.get_table(second, "t") is not None
    finally:
        await _run(
            adapter,
            f"DROP SCHEMA {_quote(first)} CASCADE",
            f"DROP SCHEMA {_quote(second)} CASCADE",
        )


# ---------------------------------------------------------------------------
# Keys, constraints, indexes
# ---------------------------------------------------------------------------


async def test_single_composite_keys_and_unique_constraint(
    adapter: PostgreSQLAdapter, temp_schema: str
) -> None:
    s = _quote(temp_schema)
    single = f"single_{uuid4().hex}"
    composite = f"composite_{uuid4().hex}"
    await _run(
        adapter,
        f"CREATE TABLE {s}.{_quote(single)} "
        f"(id integer PRIMARY KEY, email text UNIQUE)",
        f"CREATE TABLE {s}.{_quote(composite)} "
        f"(x integer, y integer, PRIMARY KEY (x, y))",
    )

    catalog = await _retriever(adapter, temp_schema).retrieve()

    single_t = catalog.get_table(temp_schema, single)
    assert single_t is not None
    assert single_t.primary_key is not None
    assert single_t.primary_key.columns == ("id",)
    assert len(single_t.unique_constraints) == 1
    assert single_t.unique_constraints[0].columns == ("email",)

    composite_t = catalog.get_table(temp_schema, composite)
    assert composite_t is not None
    assert composite_t.primary_key is not None
    assert composite_t.primary_key.columns == ("x", "y")


async def test_foreign_key_across_schemas(
    adapter: PostgreSQLAdapter, temp_schema: str
) -> None:
    parent_schema = temp_schema
    child_schema = f"qs_it_{uuid4().hex}"
    parent = f"parent_{uuid4().hex}"
    child = f"child_{uuid4().hex}"
    fk_name = f"fk_{uuid4().hex}"
    ps = _quote(parent_schema)
    cs = _quote(child_schema)
    await _run(
        adapter,
        f"CREATE SCHEMA {cs}",
        f"CREATE TABLE {ps}.{_quote(parent)} (id integer PRIMARY KEY)",
        f"CREATE TABLE {cs}.{_quote(child)} (\n"
        f"    parent_id integer,\n"
        f"    CONSTRAINT {_quote(fk_name)} FOREIGN KEY (parent_id)\n"
        f"        REFERENCES {ps}.{_quote(parent)} (id)\n"
        f")",
    )
    try:
        catalog = await _retriever(adapter, parent_schema, child_schema).retrieve()
        child_t = catalog.get_table(child_schema, child)
        assert child_t is not None
        assert len(child_t.foreign_keys) == 1
        fk = child_t.foreign_keys[0]
        assert fk.name == fk_name
        assert fk.columns == ("parent_id",)
        assert fk.referenced_schema == parent_schema
        assert fk.referenced_table == parent
        assert fk.referenced_columns == ("id",)
    finally:
        await _run(adapter, f"DROP SCHEMA {cs} CASCADE")


async def test_normal_and_unique_indexes(
    adapter: PostgreSQLAdapter, temp_schema: str
) -> None:
    s = _quote(temp_schema)
    table = f"indexed_{uuid4().hex}"
    normal_idx = f"ix_normal_{uuid4().hex}"
    unique_idx = f"ix_unique_{uuid4().hex}"
    await _run(
        adapter,
        f"CREATE TABLE {s}.{_quote(table)} (a integer, b integer)",
        f"CREATE INDEX {_quote(normal_idx)} ON {s}.{_quote(table)} (a)",
        f"CREATE UNIQUE INDEX {_quote(unique_idx)} ON {s}.{_quote(table)} (b)",
    )

    catalog = await _retriever(adapter, temp_schema).retrieve()
    found = catalog.get_table(temp_schema, table)
    assert found is not None
    by_name = {i.name: i for i in found.indexes}

    assert normal_idx in by_name
    assert by_name[normal_idx].unique is False
    assert by_name[normal_idx].primary is False
    assert by_name[normal_idx].columns == ("a",)

    assert unique_idx in by_name
    assert by_name[unique_idx].unique is True
    assert by_name[unique_idx].primary is False
    assert by_name[unique_idx].columns == ("b",)


# ---------------------------------------------------------------------------
# Comments and identifier edge cases
# ---------------------------------------------------------------------------


async def test_schema_table_and_column_comments(
    adapter: PostgreSQLAdapter, temp_schema: str
) -> None:
    s = _quote(temp_schema)
    table = f"documented_{uuid4().hex}"
    await _run(
        adapter,
        f"CREATE TABLE {s}.{_quote(table)} (id integer)",
        f"COMMENT ON SCHEMA {s} IS 'schema doc'",
        f"COMMENT ON TABLE {s}.{_quote(table)} IS 'table doc'",
        f"COMMENT ON COLUMN {s}.{_quote(table)}.id IS 'column doc'",
    )

    catalog = await _retriever(adapter, temp_schema).retrieve()
    schema = catalog.get_schema(temp_schema)
    assert schema is not None and schema.comment == "schema doc"
    found = schema.get_table(table)
    assert found is not None and found.comment == "table doc"
    id_col = found.get_column("id")
    assert id_col is not None and id_col.comment == "column doc"


async def test_identifier_edge_cases_are_preserved_verbatim(
    adapter: PostgreSQLAdapter, temp_schema: str
) -> None:
    # A mixed-case name with a space, and a column likewise — PostgreSQL keeps
    # them exactly, and QueryShield must not case-fold or otherwise rewrite them.
    s = _quote(temp_schema)
    table = f"Mixed Case {uuid4().hex}"
    column = "Col With Space"
    await _run(
        adapter,
        f"CREATE TABLE {s}.{_quote(table)} ({_quote(column)} integer NOT NULL)",
    )

    catalog = await _retriever(adapter, temp_schema).retrieve()
    schema = catalog.get_schema(temp_schema)
    assert schema is not None

    found = schema.get_table(table)
    assert found is not None  # exact-match lookup on the verbatim name
    assert schema.get_table(table.lower()) is None  # case-sensitive
    col = found.get_column(column)
    assert col is not None and col.nullable is False
    assert found.get_column(column.lower()) is None


# ---------------------------------------------------------------------------
# Fingerprint behaviour
# ---------------------------------------------------------------------------


async def test_fingerprint_is_deterministic_and_structural(
    adapter: PostgreSQLAdapter, temp_schema: str
) -> None:
    s = _quote(temp_schema)
    table = f"fp_{uuid4().hex}"
    await _run(adapter, f"CREATE TABLE {s}.{_quote(table)} (a integer)")
    retriever = _retriever(adapter, temp_schema)

    first = (await retriever.retrieve()).fingerprint
    second = (await retriever.retrieve()).fingerprint
    assert first.startswith("sha256:")
    assert first == second  # same structure -> same fingerprint

    # A comment is documentation, not structure: the fingerprint must not move.
    await _run(adapter, f"COMMENT ON TABLE {s}.{_quote(table)} IS 'noise'")
    assert (await retriever.retrieve()).fingerprint == first

    # Adding a column is a structural change: the fingerprint must move.
    await _run(adapter, f"ALTER TABLE {s}.{_quote(table)} ADD COLUMN b text")
    assert (await retriever.retrieve()).fingerprint != first


# ---------------------------------------------------------------------------
# Fail-closed behaviour
# ---------------------------------------------------------------------------


async def test_connection_failure_raises_rather_than_empty_catalog(
    test_dsn: str,
) -> None:
    # A failed introspection must be distinguishable from an empty database: the
    # retriever raises, never returns a fake empty catalog.
    parts = urlsplit(test_dsn)
    wrong = "wrong_" + uuid4().hex
    netloc = (
        f"{parts.username or 'postgres'}:{wrong}@"
        f"{parts.hostname or 'localhost'}"
        f"{':' + str(parts.port) if parts.port else ''}"
    )
    bad_dsn = urlunsplit(
        (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
    )
    config = DatabaseConfig(
        url=SecretStr(bad_dsn),
        pool_min_size=0,
        pool_max_size=2,
        connect_timeout=3.0,
        pool_timeout=3.0,
    )
    adapter = PostgreSQLAdapter(config)
    await adapter.open()
    try:
        retriever = PostgreSQLSchemaRetriever(adapter)
        with pytest.raises(DatabaseConnectionError):
            await retriever.retrieve()
    finally:
        await adapter.close()


async def test_empty_selection_returns_empty_catalog(
    adapter: PostgreSQLAdapter, temp_schema: str
) -> None:
    # Selecting no schema is a legitimate empty result (not a failure): an empty
    # but real catalog, distinct from the raised errors above.
    await _run(adapter, f"CREATE TABLE {_quote(temp_schema)}.t (id integer)")
    retriever = PostgreSQLSchemaRetriever(
        adapter, schema_filter=SchemaFilter.from_names(include=[])
    )
    catalog: SchemaCatalog = await retriever.retrieve()
    assert catalog.is_empty
