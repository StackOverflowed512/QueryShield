"""QueryShield — secure, auditable text-to-SQL infrastructure for PostgreSQL.

**Phase 4** adds the deterministic **SQL parsing & AST foundation**: a
:class:`~queryshield.sql.SQLParser` abstraction with a concrete PostgreSQL
implementation that independently parses a candidate SQL string into a
QueryShield-owned, strongly-typed structure (statement kind, referenced tables
and columns, joins, CTEs, set operations, parameters, and so on). The parser
*describes* structure — it makes no security decision and never executes SQL.

The remaining deterministic security pipeline (policy engine, rewriting, cost
checks), the Mistral provider, caching, and audit are still **not** implemented
— see ``docs/IMPLEMENTATION_STATUS.md`` for the authoritative status and
``docs/ARCHITECTURE.md`` for the intended design.

The public API is intentionally small: the validated configuration model and its
loader, and the typed error hierarchy. The database adapter lives under
:mod:`queryshield.db`, the schema types under :mod:`queryshield.schema`, and the
parsing types under :mod:`queryshield.sql`, because each is a lower-level
component (see the trust boundary in ``docs/ARCHITECTURE.md``), not a
user-facing query API.
"""

from __future__ import annotations

import logging

from queryshield.config import DatabaseConfig, QueryShieldConfig, load_config
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

__all__ = [
    "ConfigError",
    "DatabaseConfig",
    "DatabaseConnectionError",
    "DatabaseError",
    "DatabaseExecutionError",
    "QueryShieldConfig",
    "QueryShieldError",
    "SQLParseError",
    "SchemaError",
    "SchemaMetadataError",
    "SchemaRetrievalError",
    "__version__",
    "load_config",
]

#: Single source of truth for the package version. The build backend (Hatchling)
#: reads this literal at build time — see ``[tool.hatch.version]`` in
#: ``pyproject.toml`` — so the installed distribution's metadata and this value
#: never drift.
__version__ = "0.4.0"

# Library best practice: attach a no-op handler so importing QueryShield never
# emits "No handlers could be found" warnings and never configures logging on the
# application's behalf. Applications opt in by configuring their own handlers.
logging.getLogger("queryshield").addHandler(logging.NullHandler())
