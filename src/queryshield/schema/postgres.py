"""PostgreSQL implementation of :class:`~queryshield.schema.base.SchemaRetriever`.

Introspection reads ``pg_catalog`` (chosen over ``information_schema`` — see
ADR-0025 — because it preserves PostgreSQL-specific type and index detail and
avoids the information_schema views' overhead). It reuses the existing
:class:`~queryshield.db.base.DatabaseAdapter`: there is no second connection
implementation. All catalog reads happen inside a **single read-only
transaction**, so the snapshot is internally consistent (every query sees one
MVCC snapshot), and the discovered schema names are passed as **bound array
parameters** — identifiers are never interpolated into catalog SQL.

Privilege behaviour (see ADR-0025): introspection runs as whatever role the
adapter's DSN names, and relations are filtered by
``has_table_privilege(oid, 'SELECT')`` so QueryShield never reports an object the
configured role cannot read. Column-level privileges
(``GRANT SELECT (col) ...``) are not yet reflected — every column of a
SELECT-visible relation is reported; refining to column granularity is deferred.
This is schema *visibility*, not authorization: it decides what to look at, not
who may query it.

The number of catalog queries is a small fixed constant (six) regardless of how
many schemas, tables, or columns exist — there is no per-object (N+1) querying.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from queryshield.db import DatabaseAdapter, Row
from queryshield.errors import (
    DatabaseConnectionError,
    DatabaseExecutionError,
    SchemaMetadataError,
    SchemaRetrievalError,
)
from queryshield.schema.base import SchemaRetriever
from queryshield.schema.filter import SchemaFilter
from queryshield.schema.models import (
    Column,
    ForeignKey,
    Index,
    PrimaryKey,
    Schema,
    SchemaCatalog,
    Table,
    UniqueConstraint,
    View,
)

logger = logging.getLogger(__name__)

# relkinds QueryShield models: ordinary + partitioned tables, plain + mat. views.
_TABLE_KINDS = frozenset({"r", "p"})
_VIEW_KINDS = frozenset({"v", "m"})

# ---------------------------------------------------------------------------
# Catalog SQL. Each statement takes exactly one bound parameter: the list of
# selected schema names (an array). The leading comment on each constant records
# the result-column order the row-unpacking below relies on.
# ---------------------------------------------------------------------------

# (nspname, comment)
_SQL_SCHEMAS = """
SELECT n.nspname,
       pg_catalog.obj_description(n.oid, 'pg_namespace')
FROM pg_catalog.pg_namespace n
ORDER BY n.nspname
"""

# (schema, relname, relkind, comment)
_SQL_RELATIONS = """
SELECT n.nspname,
       c.relname,
       c.relkind,
       pg_catalog.obj_description(c.oid, 'pg_class')
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = ANY(%s)
  AND c.relkind IN ('r', 'p', 'v', 'm')
  AND pg_catalog.has_table_privilege(c.oid, 'SELECT')
ORDER BY n.nspname, c.relname
"""

# (schema, relname, attname, attnum, attnotnull, data_type, default, comment)
_SQL_COLUMNS = """
SELECT n.nspname,
       c.relname,
       a.attname,
       a.attnum,
       a.attnotnull,
       pg_catalog.format_type(a.atttypid, a.atttypmod),
       pg_catalog.pg_get_expr(ad.adbin, ad.adrelid),
       pg_catalog.col_description(c.oid, a.attnum)
FROM pg_catalog.pg_attribute a
JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_catalog.pg_attrdef ad
    ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
WHERE n.nspname = ANY(%s)
  AND c.relkind IN ('r', 'p', 'v', 'm')
  AND a.attnum > 0
  AND NOT a.attisdropped
  AND pg_catalog.has_table_privilege(c.oid, 'SELECT')
ORDER BY n.nspname, c.relname, a.attnum
"""

# (schema, relname, conname, contype, columns[])
_SQL_KEY_CONSTRAINTS = """
SELECT n.nspname,
       c.relname,
       con.conname,
       con.contype,
       (
           SELECT array_agg(a.attname ORDER BY k.ord)
           FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
           JOIN pg_catalog.pg_attribute a
               ON a.attrelid = con.conrelid AND a.attnum = k.attnum
       )
FROM pg_catalog.pg_constraint con
JOIN pg_catalog.pg_class c ON c.oid = con.conrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = ANY(%s)
  AND con.contype IN ('p', 'u')
  AND pg_catalog.has_table_privilege(c.oid, 'SELECT')
ORDER BY n.nspname, c.relname, con.conname
"""

# (schema, relname, conname, columns[], ref_schema, ref_table, ref_columns[])
_SQL_FOREIGN_KEYS = """
SELECT n.nspname,
       c.relname,
       con.conname,
       (
           SELECT array_agg(a.attname ORDER BY k.ord)
           FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
           JOIN pg_catalog.pg_attribute a
               ON a.attrelid = con.conrelid AND a.attnum = k.attnum
       ),
       fn.nspname,
       fc.relname,
       (
           SELECT array_agg(a.attname ORDER BY k.ord)
           FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
           JOIN pg_catalog.pg_attribute a
               ON a.attrelid = con.confrelid AND a.attnum = k.attnum
       )
FROM pg_catalog.pg_constraint con
JOIN pg_catalog.pg_class c ON c.oid = con.conrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
JOIN pg_catalog.pg_class fc ON fc.oid = con.confrelid
JOIN pg_catalog.pg_namespace fn ON fn.oid = fc.relnamespace
WHERE n.nspname = ANY(%s)
  AND con.contype = 'f'
  AND pg_catalog.has_table_privilege(c.oid, 'SELECT')
ORDER BY n.nspname, c.relname, con.conname
"""

# (schema, table, index_name, is_unique, is_primary, key_columns[])
_SQL_INDEXES = """
SELECT n.nspname,
       t.relname,
       i.relname,
       ix.indisunique,
       ix.indisprimary,
       (
           SELECT array_agg(
               CASE
                   WHEN k.attnum = 0 THEN pg_catalog.pg_get_indexdef(
                       ix.indexrelid, k.ord::int, true
                   )
                   ELSE a.attname
               END
               ORDER BY k.ord
           )
           FROM unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord)
           LEFT JOIN pg_catalog.pg_attribute a
               ON a.attrelid = t.oid AND a.attnum = k.attnum
           WHERE k.ord <= ix.indnkeyatts
       )
FROM pg_catalog.pg_index ix
JOIN pg_catalog.pg_class i ON i.oid = ix.indexrelid
JOIN pg_catalog.pg_class t ON t.oid = ix.indrelid
JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = ANY(%s)
  AND t.relkind IN ('r', 'p', 'm')
  AND pg_catalog.has_table_privilege(t.oid, 'SELECT')
ORDER BY n.nspname, t.relname, i.relname
"""


@dataclass(frozen=True, slots=True)
class _RawRows:
    """The raw catalog rows for one introspection pass, before assembly."""

    schemas: list[Row]
    relations: list[Row]
    columns: list[Row]
    keys: list[Row]
    foreign_keys: list[Row]
    indexes: list[Row]
    selected: list[str]


class PostgreSQLSchemaRetriever(SchemaRetriever):
    """Introspects a PostgreSQL database into a :class:`SchemaCatalog`.

    The ``adapter`` must already be open; its lifecycle (open/close) is the
    caller's responsibility, exactly as for direct adapter use. ``schema_filter``
    narrows which schemas are introspected and defaults to
    :meth:`SchemaFilter.default` (all application schemas, no system schemas).
    """

    def __init__(
        self,
        adapter: DatabaseAdapter,
        *,
        schema_filter: SchemaFilter | None = None,
    ) -> None:
        self._adapter = adapter
        self._schema_filter = schema_filter or SchemaFilter.default()

    async def retrieve(self) -> SchemaCatalog:
        raw = await self._introspect()
        catalog = _assemble_catalog(raw)
        logger.debug(
            "introspected %d schema(s) from PostgreSQL catalog",
            len(catalog.schemas),
        )
        return catalog

    async def _introspect(self) -> _RawRows:
        """Run every catalog query in one read-only transaction.

        Connection failures propagate as :class:`DatabaseConnectionError`;
        a catalog query that fails on a reachable database becomes a
        :class:`SchemaRetrievalError`.
        """
        try:
            async with self._adapter.transaction(read_only=True) as session:
                schema_rows = await session.fetch_all(_SQL_SCHEMAS)
                names = [_as_str(row[0]) for row in schema_rows]
                selected = self._schema_filter.select(names)
                if not selected:
                    return _RawRows(schema_rows, [], [], [], [], [], selected)
                relations = await session.fetch_all(_SQL_RELATIONS, [selected])
                columns = await session.fetch_all(_SQL_COLUMNS, [selected])
                keys = await session.fetch_all(_SQL_KEY_CONSTRAINTS, [selected])
                fks = await session.fetch_all(_SQL_FOREIGN_KEYS, [selected])
                indexes = await session.fetch_all(_SQL_INDEXES, [selected])
                return _RawRows(
                    schema_rows, relations, columns, keys, fks, indexes, selected
                )
        except DatabaseConnectionError:
            raise
        except DatabaseExecutionError as exc:
            raise SchemaRetrievalError(
                f"PostgreSQL schema introspection failed: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Row coercion. Catalog rows arrive as positional tuples of Any (the adapter
# returns psycopg TupleRow); these helpers pin each value to a concrete type.
# ---------------------------------------------------------------------------


def _as_str(value: Any) -> str:
    return str(value)


def _as_opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _as_int(value: Any) -> int:
    return int(value)


def _as_bool(value: Any) -> bool:
    return bool(value)


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    """A PostgreSQL array column -> a tuple of strings (``NULL`` -> empty)."""
    if value is None:
        return ()
    return tuple(str(item) for item in value)


# ---------------------------------------------------------------------------
# Assembly: pure, deterministic, and the only place that can raise
# SchemaMetadataError. Kept free of I/O so it is unit-testable with synthetic
# rows. A reference to a relation the relations query did not report is treated
# as a malformed catalog (fail closed), never silently dropped.
# ---------------------------------------------------------------------------


@dataclass
class _TableBuild:
    comment: str | None
    columns: list[Column] = field(default_factory=list)
    primary_key: PrimaryKey | None = None
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    unique_constraints: list[UniqueConstraint] = field(default_factory=list)
    indexes: list[Index] = field(default_factory=list)


@dataclass
class _ViewBuild:
    comment: str | None
    materialized: bool
    columns: list[Column] = field(default_factory=list)
    indexes: list[Index] = field(default_factory=list)


def _assemble_catalog(raw: _RawRows) -> SchemaCatalog:
    schema_comments = {_as_str(row[0]): _as_opt_str(row[1]) for row in raw.schemas}
    tables: dict[tuple[str, str], _TableBuild] = {}
    views: dict[tuple[str, str], _ViewBuild] = {}

    for row in raw.relations:
        key = (_as_str(row[0]), _as_str(row[1]))
        relkind = _as_str(row[2])
        comment = _as_opt_str(row[3])
        if relkind in _TABLE_KINDS:
            tables[key] = _TableBuild(comment=comment)
        elif relkind in _VIEW_KINDS:
            views[key] = _ViewBuild(comment=comment, materialized=relkind == "m")

    _attach_columns(raw.columns, tables, views)
    _attach_key_constraints(raw.keys, tables)
    _attach_foreign_keys(raw.foreign_keys, tables)
    _attach_indexes(raw.indexes, tables, views)

    schemas = tuple(
        _build_schema(name, schema_comments.get(name), tables, views)
        for name in raw.selected
    )
    return SchemaCatalog.from_schemas(schemas)


def _attach_columns(
    rows: Sequence[Row],
    tables: dict[tuple[str, str], _TableBuild],
    views: dict[tuple[str, str], _ViewBuild],
) -> None:
    for row in rows:
        key = (_as_str(row[0]), _as_str(row[1]))
        column = Column(
            name=_as_str(row[2]),
            ordinal=_as_int(row[3]),
            nullable=not _as_bool(row[4]),
            data_type=_as_str(row[5]),
            default=_as_opt_str(row[6]),
            comment=_as_opt_str(row[7]),
        )
        if key in tables:
            tables[key].columns.append(column)
        elif key in views:
            views[key].columns.append(column)
        else:
            raise SchemaMetadataError(
                f"column {column.name!r} refers to unknown relation {key[0]}.{key[1]}"
            )


def _attach_key_constraints(
    rows: Sequence[Row],
    tables: dict[tuple[str, str], _TableBuild],
) -> None:
    for row in rows:
        key = (_as_str(row[0]), _as_str(row[1]))
        name = _as_str(row[2])
        contype = _as_str(row[3])
        columns = _as_str_tuple(row[4])
        if key not in tables:
            raise SchemaMetadataError(
                f"constraint {name!r} refers to unknown table {key[0]}.{key[1]}"
            )
        if not columns:
            raise SchemaMetadataError(
                f"constraint {name!r} on {key[0]}.{key[1]} has no columns"
            )
        build = tables[key]
        if contype == "p":
            if build.primary_key is not None:
                raise SchemaMetadataError(
                    f"table {key[0]}.{key[1]} reports multiple primary keys"
                )
            build.primary_key = PrimaryKey(name=name, columns=columns)
        else:
            build.unique_constraints.append(
                UniqueConstraint(name=name, columns=columns)
            )


def _attach_foreign_keys(
    rows: Sequence[Row],
    tables: dict[tuple[str, str], _TableBuild],
) -> None:
    for row in rows:
        key = (_as_str(row[0]), _as_str(row[1]))
        name = _as_str(row[2])
        columns = _as_str_tuple(row[3])
        ref_columns = _as_str_tuple(row[6])
        if key not in tables:
            raise SchemaMetadataError(
                f"foreign key {name!r} refers to unknown table {key[0]}.{key[1]}"
            )
        if not columns or len(columns) != len(ref_columns):
            raise SchemaMetadataError(
                f"foreign key {name!r} on {key[0]}.{key[1]} has mismatched column lists"
            )
        tables[key].foreign_keys.append(
            ForeignKey(
                name=name,
                columns=columns,
                referenced_schema=_as_str(row[4]),
                referenced_table=_as_str(row[5]),
                referenced_columns=ref_columns,
            )
        )


def _attach_indexes(
    rows: Sequence[Row],
    tables: dict[tuple[str, str], _TableBuild],
    views: dict[tuple[str, str], _ViewBuild],
) -> None:
    for row in rows:
        key = (_as_str(row[0]), _as_str(row[1]))
        index = Index(
            name=_as_str(row[2]),
            unique=_as_bool(row[3]),
            primary=_as_bool(row[4]),
            columns=_as_str_tuple(row[5]),
        )
        if not index.columns:
            raise SchemaMetadataError(
                f"index {index.name!r} on {key[0]}.{key[1]} has no key columns"
            )
        if key in tables:
            tables[key].indexes.append(index)
        elif key in views:
            views[key].indexes.append(index)
        else:
            raise SchemaMetadataError(
                f"index {index.name!r} refers to unknown relation {key[0]}.{key[1]}"
            )


def _build_schema(
    name: str,
    comment: str | None,
    tables: dict[tuple[str, str], _TableBuild],
    views: dict[tuple[str, str], _ViewBuild],
) -> Schema:
    built_tables = tuple(
        Table(
            schema=name,
            name=rel,
            columns=tuple(build.columns),
            primary_key=build.primary_key,
            foreign_keys=tuple(build.foreign_keys),
            unique_constraints=tuple(build.unique_constraints),
            indexes=tuple(build.indexes),
            comment=build.comment,
        )
        for (schema, rel), build in sorted(tables.items())
        if schema == name
    )
    built_views = tuple(
        View(
            schema=name,
            name=rel,
            columns=tuple(build.columns),
            materialized=build.materialized,
            indexes=tuple(build.indexes),
            comment=build.comment,
        )
        for (schema, rel), build in sorted(views.items())
        if schema == name
    )
    return Schema(
        name=name,
        tables=built_tables,
        views=built_views,
        comment=comment,
    )
