"""Immutable domain models for a discovered PostgreSQL schema.

These types describe *what exists* in a database — schemas, tables, views,
columns, keys, constraints, and indexes — as a coherent, read-only **snapshot**.
They deliberately contain **no** security or governance information (no PII
classification, no sensitivity labels, no per-principal visibility): that is the
job of later layers. A :class:`SchemaCatalog` answers "what is the shape of this
database?", nothing more.

Design choices (see ``docs/DECISIONS.md``):

* **Frozen, slotted dataclasses** (ADR-0024). They are immutable (a snapshot must
  not be mutated after retrieval), cheap, dependency-light, and consistent with
  :class:`queryshield.db.base.HealthCheckResult`. We do not reuse ``pydantic``
  here because these objects are *produced* by trusted introspection code, not
  *parsed* from untrusted input, so runtime validation buys nothing.
* **Canonical identifiers, preserved verbatim** (ADR-0026). Every ``name`` is the
  exact identifier PostgreSQL reports (``pg_class.relname`` et al.): original
  case, spaces, Unicode, and reserved words are kept as-is. QueryShield never
  case-folds or otherwise normalises an identifier, so a lookup is an exact
  match on the stored string. (Rendering an identifier back into SQL — i.e.
  quoting — belongs to the query-construction layer, not here.)
* **Deterministic structural fingerprint** (ADR-0027).
  :meth:`SchemaCatalog.from_schemas` derives :attr:`SchemaCatalog.fingerprint`
  purely from the discovered *structure*; see :func:`compute_fingerprint` for
  the exact contributors.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Column:
    """A single column of a table or view.

    ``data_type`` is the PostgreSQL type exactly as ``pg_catalog.format_type``
    renders it (e.g. ``"integer"``, ``"character varying(255)"``,
    ``"numeric(10,2)"``, ``"timestamp with time zone"``, ``"integer[]"``, or a
    schema-qualified user type). It is kept as text, not coerced to a generic
    type, so PostgreSQL-specific information is never lost.
    """

    name: str
    data_type: str
    nullable: bool
    ordinal: int
    default: str | None = None
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class PrimaryKey:
    """A primary-key constraint. ``columns`` are ordered as the key is defined."""

    name: str
    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UniqueConstraint:
    """A ``UNIQUE`` constraint. ``columns`` are ordered as the constraint defines."""

    name: str
    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ForeignKey:
    """A foreign-key constraint from a table to a (possibly cross-schema) table.

    ``columns`` (local) and ``referenced_columns`` (on the referenced table) are
    positionally aligned and ordered as the constraint defines them. The
    referenced relation is identified by name only; it may or may not itself
    appear in the catalog (it can live in an excluded schema or be unreadable by
    the current role) — recording the reference is not a claim of access to it.
    """

    name: str
    columns: tuple[str, ...]
    referenced_schema: str
    referenced_table: str
    referenced_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Index:
    """An index on a table or materialized view.

    ``columns`` lists the *key* columns in order; an entry may be a column name
    or, for an expression index, the rendered index expression. ``INCLUDE``
    (non-key) columns are intentionally excluded.
    """

    name: str
    unique: bool
    primary: bool
    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Table:
    """A base table (ordinary or partitioned).

    ``columns`` are ordered by their PostgreSQL ordinal position. Keys,
    constraints, and indexes are present only when the current role can see them.
    """

    schema: str
    name: str
    columns: tuple[Column, ...]
    primary_key: PrimaryKey | None = None
    foreign_keys: tuple[ForeignKey, ...] = ()
    unique_constraints: tuple[UniqueConstraint, ...] = ()
    indexes: tuple[Index, ...] = ()
    comment: str | None = None

    def get_column(self, name: str) -> Column | None:
        """Return the column named ``name`` (exact match), or ``None``."""
        return next((c for c in self.columns if c.name == name), None)


@dataclass(frozen=True, slots=True)
class View:
    """A view or materialized view.

    Modelled separately from :class:`Table` because a view has no primary or
    foreign keys. A *materialized* view can carry indexes; a plain view's
    ``indexes`` is always empty.
    """

    schema: str
    name: str
    columns: tuple[Column, ...]
    materialized: bool = False
    indexes: tuple[Index, ...] = ()
    comment: str | None = None

    def get_column(self, name: str) -> Column | None:
        """Return the column named ``name`` (exact match), or ``None``."""
        return next((c for c in self.columns if c.name == name), None)


@dataclass(frozen=True, slots=True)
class Schema:
    """A namespace (PostgreSQL schema) and the relations discovered within it."""

    name: str
    tables: tuple[Table, ...] = ()
    views: tuple[View, ...] = ()
    comment: str | None = None

    def get_table(self, name: str) -> Table | None:
        """Return the table named ``name`` (exact match), or ``None``."""
        return next((t for t in self.tables if t.name == name), None)

    def get_view(self, name: str) -> View | None:
        """Return the view named ``name`` (exact match), or ``None``."""
        return next((v for v in self.views if v.name == name), None)


@dataclass(frozen=True, slots=True)
class SchemaCatalog:
    """An immutable snapshot of a database's discovered structure.

    Build one with :meth:`from_schemas`, which computes the structural
    :attr:`fingerprint`. Constructing it directly is allowed (tests may want to
    pin a fingerprint) but then the caller owns the fingerprint's correctness.

    This snapshot has **no** implicit caching and no concept of staleness: it is
    exactly the state introspection observed at the moment it ran. Re-running
    introspection yields a fresh, independent snapshot.
    """

    schemas: tuple[Schema, ...] = ()
    fingerprint: str = ""

    @classmethod
    def from_schemas(cls, schemas: tuple[Schema, ...]) -> SchemaCatalog:
        """Build a catalog from ``schemas``, deriving the structural fingerprint.

        Schemas are stored sorted by name so a catalog's ordering is canonical
        and independent of the order introspection happened to assemble them in.
        """
        ordered = tuple(sorted(schemas, key=lambda s: s.name))
        return cls(schemas=ordered, fingerprint=compute_fingerprint(ordered))

    @property
    def is_empty(self) -> bool:
        """True when no schema (and therefore no relation) was discovered."""
        return not self.schemas

    @property
    def schema_names(self) -> tuple[str, ...]:
        """The names of every discovered schema, in canonical (sorted) order."""
        return tuple(s.name for s in self.schemas)

    def get_schema(self, name: str) -> Schema | None:
        """Return the schema named ``name`` (exact match), or ``None``."""
        return next((s for s in self.schemas if s.name == name), None)

    def get_table(self, schema: str, name: str) -> Table | None:
        """Return the named table within the named schema, or ``None``."""
        found = self.get_schema(schema)
        return found.get_table(name) if found is not None else None

    def get_view(self, schema: str, name: str) -> View | None:
        """Return the named view within the named schema, or ``None``."""
        found = self.get_schema(schema)
        return found.get_view(name) if found is not None else None


# ---------------------------------------------------------------------------
# Structural fingerprint
# ---------------------------------------------------------------------------
#
# The fingerprint is a SHA-256 over a canonical JSON encoding of the catalog's
# *structure*. Two snapshots with the same structure produce the same
# fingerprint regardless of the order introspection assembled rows in; any
# structural change (a renamed/added/dropped schema, table, view, or column; a
# changed type, nullability, default, or ordinal; an altered key, unique
# constraint, foreign key, or index) produces a different fingerprint.
#
# Deliberately NOT part of the fingerprint: comments (documentation, not
# structure), the wall-clock time of retrieval, and the database identity. This
# keeps the fingerprint a pure function of shape, which is what a downstream
# cache or drift check wants.

_FINGERPRINT_ALGORITHM = "sha256"


def _column_obj(column: Column) -> dict[str, Any]:
    return {
        "name": column.name,
        "type": column.data_type,
        "nullable": column.nullable,
        "ordinal": column.ordinal,
        "default": column.default,
    }


def _table_obj(table: Table) -> dict[str, Any]:
    pk = table.primary_key
    pk_obj = None if pk is None else {"name": pk.name, "columns": list(pk.columns)}
    return {
        "name": table.name,
        # Columns carry their own ordinal; sort by it so assembly order is
        # irrelevant while the semantically meaningful order is still encoded.
        "columns": [_column_obj(c) for c in sorted(table.columns, key=_col_sort_key)],
        "primary_key": pk_obj,
        "unique_constraints": [
            {"name": u.name, "columns": list(u.columns)}
            for u in sorted(table.unique_constraints, key=lambda u: u.name)
        ],
        "foreign_keys": [
            {
                "name": fk.name,
                "columns": list(fk.columns),
                "references": {
                    "schema": fk.referenced_schema,
                    "table": fk.referenced_table,
                    "columns": list(fk.referenced_columns),
                },
            }
            for fk in sorted(table.foreign_keys, key=lambda fk: fk.name)
        ],
        "indexes": [_index_obj(i) for i in sorted(table.indexes, key=lambda i: i.name)],
    }


def _view_obj(view: View) -> dict[str, Any]:
    return {
        "name": view.name,
        "materialized": view.materialized,
        "columns": [_column_obj(c) for c in sorted(view.columns, key=_col_sort_key)],
        "indexes": [_index_obj(i) for i in sorted(view.indexes, key=lambda i: i.name)],
    }


def _index_obj(index: Index) -> dict[str, Any]:
    return {
        "name": index.name,
        "unique": index.unique,
        "primary": index.primary,
        "columns": list(index.columns),
    }


def _col_sort_key(column: Column) -> tuple[int, str]:
    return (column.ordinal, column.name)


def compute_fingerprint(schemas: tuple[Schema, ...]) -> str:
    """Return the deterministic structural fingerprint for ``schemas``.

    The result is ``"sha256:<hex>"``; the algorithm prefix makes the scheme
    self-describing and lets a future format be distinguished from this one.
    """
    canonical = [
        {
            "name": schema.name,
            "tables": [
                _table_obj(t) for t in sorted(schema.tables, key=lambda t: t.name)
            ],
            "views": [
                _view_obj(v) for v in sorted(schema.views, key=lambda v: v.name)
            ],
        }
        for schema in sorted(schemas, key=lambda s: s.name)
    ]
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"{_FINGERPRINT_ALGORITHM}:{digest}"
