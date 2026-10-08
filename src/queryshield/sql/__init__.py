"""QueryShield's SQL parsing & AST foundation.

This subpackage turns an untrusted SQL string into a QueryShield-owned,
immutable structural description:

* :class:`~queryshield.sql.base.SQLParser` — the abstraction.
* :class:`~queryshield.sql.postgres.PostgreSQLSQLParser` — the concrete parser,
  built on pglast (libpg_query, PostgreSQL's own grammar).
* :class:`~queryshield.sql.models.ParsedQuery` and its supporting types — the
  owned model a caller reasons about.

The parser *describes* structure. It makes no security decision, resolves no
names against a catalog, and executes nothing — see the trust boundary in
``docs/ARCHITECTURE.md``.
"""

from __future__ import annotations

from queryshield.sql.base import SQLParser
from queryshield.sql.models import (
    ColumnReference,
    CommonTableExpression,
    FunctionCall,
    JoinType,
    ParsedQuery,
    SetOperation,
    SetOperationType,
    StatementType,
    TableReference,
)
from queryshield.sql.postgres import PostgreSQLSQLParser

__all__ = [
    "ColumnReference",
    "CommonTableExpression",
    "FunctionCall",
    "JoinType",
    "ParsedQuery",
    "PostgreSQLSQLParser",
    "SQLParser",
    "SetOperation",
    "SetOperationType",
    "StatementType",
    "TableReference",
]
