"""The SQL-parsing abstraction.

A :class:`SQLParser` turns an untrusted SQL string into a QueryShield-owned
:class:`~queryshield.sql.models.ParsedQuery`. The parser is one of the
deterministic, security-relevant components of the pipeline: the structure it
derives is what later layers reason about, so it must be derived from the SQL
string itself — never from anything the LLM *claimed* about its query, and never
by matching the string against prefixes or regular expressions (ADR-0030).

Contract (every implementation must honour all of it):

* **Independent structural analysis.** The parser reads the candidate SQL text
  and nothing else. It does not consult the LLM's claimed tables, claimed
  statement kind, or claimed safety, and it does not take a database session, so
  it can neither resolve names nor execute anything.
* **Fail closed, all-or-nothing.** Parsing yields a *complete*
  :class:`~queryshield.sql.models.ParsedQuery` or raises
  :class:`~queryshield.errors.SQLParseError`. It never returns an empty or
  partial result, never "best-effort" parses, and never silently falls back to a
  different dialect to make something parse (ADR-0031).
* **Describe, never decide.** A parsed result is structure, not a verdict. It
  may describe a destructive statement; the parser does not judge safety and does
  not authorize anything.
* **Preserve identifiers verbatim.** Names are recorded exactly as written —
  original case, quoting, and Unicode — never case-folded (ADR-0026, ADR-0032).
* **No execution.** The parser never talks to a database or runs SQL.

Error contract:

* :class:`~queryshield.errors.SQLParseError` — the SQL is not valid in the
  configured dialect, or could not be lowered into the owned model. The
  underlying parser's exception is chained as ``__cause__``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from queryshield.sql.models import ParsedQuery


class SQLParser(ABC):
    """Abstract base class for a SQL parser.

    Concrete implementations bind a specific dialect / parsing library.
    """

    @abstractmethod
    async def parse(self, sql: str) -> ParsedQuery:
        """Parse ``sql`` into a QueryShield-owned structure.

        Args:
            sql: The candidate SQL string. It is untrusted input.

        Returns:
            A complete, immutable :class:`~queryshield.sql.models.ParsedQuery`
            describing the statement(s) in ``sql``.

        Raises:
            queryshield.errors.SQLParseError: The SQL is not valid in the
                configured dialect and no trustworthy structure could be
                derived. Fail closed — never return a partial result.
        """
        ...
        raise NotImplementedError
