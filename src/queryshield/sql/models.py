"""QueryShield-owned, strongly typed model of a parsed SQL statement.

These types are the *only* representation of parsed SQL that escapes the
:mod:`queryshield.sql` package. Nothing here is a pglast type: the concrete
parser (:mod:`queryshield.sql.postgres`) walks the pglast AST and lowers it into
these frozen dataclasses, so a caller never depends on — and can never be
confused by — a specific parser library's node objects (ADR-0029).

Design choices (see ``docs/DECISIONS.md``):

* **Structure, not a verdict.** A :class:`ParsedQuery` *describes* what a SQL
  string is (its statement kind, the relations and columns it references, its
  joins, CTEs, set operations, and so on). It carries **no** security decision:
  parsing is not authorization, and nothing here says a query is "safe".
* **Frozen, slotted dataclasses** (ADR-0024). A parsed result is immutable: a
  later stage must not be able to mutate the structure another stage already
  reasoned about.
* **Identifiers preserved verbatim** (ADR-0032, extending ADR-0026). Each name
  is stored exactly as the parser produced it; QueryShield adds no case-folding,
  truncation, or other rewriting of its own. (PostgreSQL's grammar lowercases
  *unquoted* identifiers as it parses — so unquoted ``Customers`` arrives as
  ``customers`` — while *quoted* identifiers keep their case. That folding is the
  database's, not ours, and re-folding here would only destroy information.)
* **Non-destructive and complete-or-nothing** (ADR-0031). The original SQL text
  is retained alongside the derived structure, and a parse either yields a
  complete :class:`ParsedQuery` or raises — there is no partial result.
* **No fingerprint yet.** Deliberately out of scope for this phase: a
  deterministic fingerprint of a *query* (as opposed to a *schema*, ADR-0027) is
  deferred until the cache/cost layers need it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class StatementType(StrEnum):
    """The kind of a top-level SQL statement, decided from the AST.

    The classification is driven entirely by the parsed statement node's type —
    never by matching a prefix or a regular expression against the raw string
    (ADR-0030). :attr:`UNKNOWN` is the fail-safe bucket for a statement kind this
    phase does not model; it is **never** treated as "safe" or "harmless".
    """

    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    MERGE = "MERGE"
    CREATE = "CREATE"
    ALTER = "ALTER"
    DROP = "DROP"
    TRUNCATE = "TRUNCATE"
    GRANT = "GRANT"
    REVOKE = "REVOKE"
    CALL = "CALL"
    UNKNOWN = "UNKNOWN"


class JoinType(StrEnum):
    """The kind of a SQL join, from the AST's join node."""

    INNER = "INNER"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    FULL = "FULL"
    CROSS = "CROSS"
    OTHER = "OTHER"


class SetOperationType(StrEnum):
    """A set operator combining two query results.

    ``UNION`` and ``UNION ALL`` are distinguished because they are semantically
    different (duplicate elimination vs. not) — the parser records which the SQL
    actually used and never collapses them.
    """

    UNION = "UNION"
    UNION_ALL = "UNION ALL"
    INTERSECT = "INTERSECT"
    INTERSECT_ALL = "INTERSECT ALL"
    EXCEPT = "EXCEPT"
    EXCEPT_ALL = "EXCEPT ALL"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class TableReference:
    """A reference to a relation in a ``FROM``/``JOIN``/``INSERT INTO`` clause.

    ``schema``/``name`` are exactly as written (``schema`` is ``None`` when the
    SQL did not qualify the relation). ``alias`` is the SQL alias when one was
    given, else ``None``. Whether the name resolves to a real table, a view, or
    a CTE is **not** decided here — a :class:`TableReference` records the
    reference, and :class:`ParsedQuery` records the statement's CTE names
    separately so a downstream layer can tell a CTE reference from a physical
    relation using the catalog it holds.
    """

    schema: str | None
    name: str
    alias: str | None = None


@dataclass(frozen=True, slots=True)
class ColumnReference:
    """A column referenced in the SQL.

    ``qualifier`` is the relation/alias the column was qualified with, or
    ``None`` when the SQL wrote a bare column name. ``is_star`` marks a
    ``*``/``alias.*`` reference, in which case :attr:`name` is empty.
    """

    qualifier: str | None
    name: str
    is_star: bool = False


@dataclass(frozen=True, slots=True)
class FunctionCall:
    """A function call. ``schema`` is set only when the SQL qualified it."""

    schema: str | None
    name: str


@dataclass(frozen=True, slots=True)
class CommonTableExpression:
    """A ``WITH`` common table expression."""

    name: str
    recursive: bool = False


@dataclass(frozen=True, slots=True)
class SetOperation:
    """One set operation found in the statement (possibly nested)."""

    operation: SetOperationType


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    """A complete, immutable structural description of one parsed SQL string.

    This is deliberately a *structural* description. It is produced for a single
    candidate statement; a statement that is not valid in the configured dialect
    does not produce a :class:`ParsedQuery` at all (the parser raises
    :class:`~queryshield.errors.SQLParseError` — ADR-0031).

    What this type does **not** claim:

    * It is not a safety verdict. A well-formed :class:`ParsedQuery` may describe
      a destructive statement (``DROP TABLE``, ``DELETE``) — that is a policy
      question for a later layer, not the parser's.
    * It is not a resolution of names to catalog objects. ``tables``/``columns``
      are the *references* the SQL made; deciding which of them exist, and
      whether the caller may touch them, needs the schema catalog and the policy
      layer.
    """

    statement_type: StatementType
    original_sql: str
    statement_count: int
    tables: tuple[TableReference, ...] = ()
    columns: tuple[ColumnReference, ...] = ()
    functions: tuple[FunctionCall, ...] = ()
    ctes: tuple[CommonTableExpression, ...] = ()
    joins: tuple[JoinType, ...] = ()
    set_operations: tuple[SetOperation, ...] = ()
    parameters: tuple[int, ...] = ()
    literal_count: int = 0
    has_subqueries: bool = False
    has_distinct: bool = False
    has_grouping: bool = False
    has_having: bool = False
    has_ordering: bool = False
    has_limit: bool = False
    has_offset: bool = False
    has_window_functions: bool = False
    has_locking_clause: bool = False

    @property
    def is_multi_statement(self) -> bool:
        """True when the input parsed into more than one statement.

        A multi-statement batch is represented, never silently split or reduced
        to its first statement (ADR-0030). Downstream fail-closed layers are
        expected to refuse such a batch; the parser's job is only to make the
        fact visible.
        """
        return self.statement_count > 1

    @property
    def table_names(self) -> tuple[str, ...]:
        """The referenced relations, in first-seen order, deduplicated.

        A relation the SQL qualified with a schema is returned schema-qualified
        (``public.users``) and deduplicated on that qualified identity, so a
        same-named relation in a different schema (``sales.users``) stays
        distinct. Collapsing them to a bare ``users`` would make a cross-schema
        query look like it touches fewer relations than it does — and these
        derived views are exactly what a downstream policy layer may read as the
        set of touched relations, so under-reporting here could hide a real
        access path. (This mirrors :attr:`function_names`.)
        """

        def qualified(table: TableReference) -> str:
            return (
                table.name if table.schema is None else f"{table.schema}.{table.name}"
            )

        return _dedupe(qualified(t) for t in self.tables)

    @property
    def cte_names(self) -> tuple[str, ...]:
        """The names of the statement's CTEs, deduplicated, in first-seen order.

        A CTE name is a simple, query-scoped identifier — it is never
        schema-qualified — so deduplicating on the name alone is already exact.
        """
        return _dedupe(cte.name for cte in self.ctes)

    @property
    def function_names(self) -> tuple[str, ...]:
        """The called function names (schema-qualified when the SQL said so)."""

        def qualified(func: FunctionCall) -> str:
            return func.name if func.schema is None else f"{func.schema}.{func.name}"

        return _dedupe(qualified(f) for f in self.functions)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    """Return ``values`` with duplicates removed, preserving first-seen order."""
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return tuple(seen)
