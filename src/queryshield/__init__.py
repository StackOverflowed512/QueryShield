"""QueryShield — secure, auditable text-to-SQL infrastructure for PostgreSQL.

This is the **Phase 1 (foundation)** package. No security, database, LLM, SQL
parsing, or execution functionality is implemented yet; see
``docs/IMPLEMENTATION_STATUS.md`` for the roadmap and
``docs/ARCHITECTURE.md`` for the intended design.

The package intentionally exposes only its version metadata at this stage. It
does **not** define a ``QueryShield`` orchestrator, policy engine, database
adapter, or any other future component — those are added in later phases.
"""

from __future__ import annotations

__all__ = ["__version__"]

#: Single source of truth for the package version. The build backend
#: (Hatchling) reads this literal at build time — see ``[tool.hatch.version]``
#: in ``pyproject.toml`` — so the installed distribution's metadata and this
#: value never drift.
__version__ = "0.1.0"
