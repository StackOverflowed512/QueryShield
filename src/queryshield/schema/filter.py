"""Generic, configurable filtering of which schemas get introspected.

The filter is deliberately content-agnostic: it works purely on schema *names*
supplied by configuration and never references any application object. Its only
built-in behaviour is a **safe, documented, overridable default** — PostgreSQL's
own internal namespaces (``pg_catalog``, ``pg_toast``, ``pg_temp_*``, and
``information_schema``) are skipped unless the operator explicitly asks for them,
because they are system metadata, not application schema.

This is *schema visibility*, which is not the same thing as database
authorization: narrowing introspection here only decides what QueryShield looks
at. What a role may actually read is enforced by PostgreSQL privileges (the
retriever additionally honours ``has_table_privilege``) and, ultimately, by the
database itself.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


def _is_system_schema(name: str) -> bool:
    """True for a PostgreSQL-internal namespace (not application schema)."""
    return name == "information_schema" or name.startswith("pg_")


@dataclass(frozen=True, slots=True)
class SchemaFilter:
    """Decides whether a schema name should be introspected.

    * ``include`` — if not ``None``, *only* these exact names are considered
      (an allow-list). ``None`` means "every schema that is not excluded".
    * ``exclude`` — exact names to skip (a deny-list), applied after ``include``.

    An explicitly included name is honoured even if it is a system schema, so an
    operator can introspect ``pg_catalog`` on purpose; otherwise system schemas
    are skipped by default. Matching is exact and case-sensitive, because
    PostgreSQL identifiers are case-sensitive and QueryShield never case-folds
    them.
    """

    include: frozenset[str] | None = None
    exclude: frozenset[str] = frozenset()

    @classmethod
    def default(cls) -> SchemaFilter:
        """The safe default: all application schemas, no system schemas."""
        return cls(include=None, exclude=frozenset())

    @classmethod
    def from_names(
        cls,
        include: Iterable[str] | None = None,
        exclude: Iterable[str] | None = None,
    ) -> SchemaFilter:
        """Build a filter from optional name iterables (e.g. from config)."""
        return cls(
            include=None if include is None else frozenset(include),
            exclude=frozenset(exclude or ()),
        )

    def allows(self, name: str) -> bool:
        """Return whether the schema named ``name`` should be introspected."""
        if self.include is not None:
            if name not in self.include:
                return False
            return name not in self.exclude
        if name in self.exclude:
            return False
        return not _is_system_schema(name)

    def select(self, names: Iterable[str]) -> list[str]:
        """Return the subset of ``names`` this filter allows, order preserved."""
        return [name for name in names if self.allows(name)]
