"""QueryShield schema layer: the retriever abstraction, its PostgreSQL
implementation, the immutable domain models, and schema-selection filtering.

A :class:`SchemaRetriever` turns a live database into an immutable
:class:`SchemaCatalog` snapshot — the answer to "what is the shape of this
database?". It is a **structure** layer, not an authorization layer: it reports
what the configured database role can see (honouring ``has_table_privilege``)
and never decides whether a given caller may query an object. See
``docs/ARCHITECTURE.md`` and ADR-0024..0028.
"""

from __future__ import annotations

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
    compute_fingerprint,
)
from queryshield.schema.postgres import PostgreSQLSchemaRetriever

__all__ = [
    "Column",
    "ForeignKey",
    "Index",
    "PostgreSQLSchemaRetriever",
    "PrimaryKey",
    "Schema",
    "SchemaCatalog",
    "SchemaFilter",
    "SchemaRetriever",
    "Table",
    "UniqueConstraint",
    "View",
    "compute_fingerprint",
]
