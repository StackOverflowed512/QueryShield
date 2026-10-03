"""The database abstraction and its trust boundary.

This module defines *what* QueryShield needs from a database — a small, typed,
async surface — without binding to a concrete driver. The PostgreSQL
implementation lives in :mod:`queryshield.db.postgres`.

Trust boundary (read this before extending the adapter)
-------------------------------------------------------
A :class:`DatabaseAdapter` is a **trusted, lower-level executor**. It runs the
SQL it is handed, inside a transaction, against a least-privilege database
principal. It is deliberately **not** responsible for deciding whether a query
is *authorized*: that decision belongs to the (future) deterministic security
layers — SQL parser/AST, policy engine, rewriter, cost checks — which run
*before* anything reaches this adapter. See ``docs/ARCHITECTURE.md`` and
ADR-0019.

Consequences of that boundary:

* The adapter must never be wired directly to user- or LLM-supplied SQL. In the
  full pipeline it only ever executes SQL that the deterministic controls have
  already validated.
* Values are always passed **separately** from the SQL text (parameterised
  execution). The adapter never string-interpolates caller-supplied values into
  a statement.
* There is intentionally **no** public "run whatever string you like" API that
  bypasses the transaction/least-privilege machinery just because it would be
  convenient.
* Every operation defaults to a **read-only** transaction. Writes must be
  requested explicitly (``read_only=False``) — security by default.
"""

from __future__ import annotations

import abc
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol, Self

#: A database row as returned by the adapter: a positional tuple of values.
Row = tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class HealthCheckResult:
    """Outcome of a real connectivity check against the database.

    ``healthy`` is ``True`` only when a live connection was acquired *and* a
    trivial statement executed successfully. A failed check never masquerades as
    healthy; ``error`` carries a sanitised (secret-free) explanation.
    """

    healthy: bool
    latency_ms: float | None = None
    error: str | None = None


class DatabaseSession(Protocol):
    """A handle to a single in-progress transaction.

    Obtained from :meth:`DatabaseAdapter.transaction`. All statements issued
    through a session run inside that one transaction and share its read-only /
    read-write mode. ``params`` are always supplied separately from ``query``
    and bound by the driver — never interpolated into the SQL text.
    """

    async def execute(self, query: str, params: Sequence[Any] | None = None) -> None:
        """Execute a statement whose result set (if any) is ignored."""
        ...

    async def fetch_all(
        self, query: str, params: Sequence[Any] | None = None
    ) -> list[Row]:
        """Execute a query and return every result row."""
        ...

    async def fetch_one(
        self, query: str, params: Sequence[Any] | None = None
    ) -> Row | None:
        """Execute a query and return the first row, or ``None`` if empty."""
        ...


class DatabaseAdapter(abc.ABC):
    """Abstract, driver-agnostic database gateway.

    Lifecycle: :meth:`open` acquires resources (e.g. a connection pool),
    :meth:`close` releases them, and the adapter also works as an async context
    manager. :meth:`health_check` reports real connectivity. :meth:`transaction`
    yields a :class:`DatabaseSession`; the convenience methods
    (:meth:`execute`/:meth:`fetch_all`/:meth:`fetch_one`) each run inside their
    own short transaction.

    See the module docstring for the trust boundary this type enforces.
    """

    @abc.abstractmethod
    async def open(self) -> None:
        """Acquire connection resources. Idempotent; safe to call once."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Release all connection resources. Idempotent."""

    @abc.abstractmethod
    async def health_check(self) -> HealthCheckResult:
        """Verify real connectivity, never reporting healthy when unreachable."""

    @abc.abstractmethod
    def transaction(
        self, *, read_only: bool = True
    ) -> AbstractAsyncContextManager[DatabaseSession]:
        """Open a transaction and yield a session bound to it.

        The transaction commits on clean exit and rolls back if the body raises.
        Defaults to read-only; pass ``read_only=False`` to permit writes.
        """

    @abc.abstractmethod
    async def execute(
        self,
        query: str,
        params: Sequence[Any] | None = None,
        *,
        read_only: bool = True,
    ) -> None:
        """Run a single statement in its own transaction."""

    @abc.abstractmethod
    async def fetch_all(
        self,
        query: str,
        params: Sequence[Any] | None = None,
        *,
        read_only: bool = True,
    ) -> list[Row]:
        """Run a query in its own transaction and return all rows."""

    @abc.abstractmethod
    async def fetch_one(
        self,
        query: str,
        params: Sequence[Any] | None = None,
        *,
        read_only: bool = True,
    ) -> Row | None:
        """Run a query in its own transaction and return the first row."""

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()
