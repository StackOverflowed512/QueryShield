"""QueryShield — secure, auditable text-to-SQL infrastructure for PostgreSQL.

**Phase 3** adds dynamic PostgreSQL **schema introspection**: a
:class:`~queryshield.schema.SchemaRetriever` abstraction with a concrete
PostgreSQL implementation that turns a live database into an immutable
:class:`~queryshield.schema.SchemaCatalog` snapshot (on top of the Phase 2
configuration foundation and database adapter). The remaining deterministic
security pipeline (SQL parsing/AST, policy engine, rewriting, cost checks), the
Mistral provider, caching, and audit are still **not** implemented — see
``docs/IMPLEMENTATION_STATUS.md`` for the authoritative status and
``docs/ARCHITECTURE.md`` for the intended design.

The public API is intentionally small: the validated configuration model and its
loader, and the typed error hierarchy. The database adapter lives under
:mod:`queryshield.db` and the schema types under :mod:`queryshield.schema`,
because each is a lower-level component (see the trust boundary in
``docs/ARCHITECTURE.md``), not a user-facing query API.
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
)

__all__ = [
    "ConfigError",
    "DatabaseConfig",
    "DatabaseConnectionError",
    "DatabaseError",
    "DatabaseExecutionError",
    "QueryShieldConfig",
    "QueryShieldError",
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
__version__ = "0.3.0"

# Library best practice: attach a no-op handler so importing QueryShield never
# emits "No handlers could be found" warnings and never configures logging on the
# application's behalf. Applications opt in by configuring their own handlers.
logging.getLogger("queryshield").addHandler(logging.NullHandler())
