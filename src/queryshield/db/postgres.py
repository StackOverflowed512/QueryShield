"""PostgreSQL implementation of :class:`~queryshield.db.base.DatabaseAdapter`.

Uses **psycopg 3** and its async connection pool (``psycopg_pool``). The choice
of a single modern driver, async I/O, and pooling is recorded in ADR-0018,
ADR-0019, and ADR-0020.

Security properties enforced here:

* **No secret leakage.** The connection password (and the full DSN) are scrubbed
  from every error message, and only a sanitised ``host=… dbname=… user=…``
  descriptor is ever logged. See :func:`sanitize_dsn` / :func:`scrub_secrets`.
* **Parameterised execution only.** Values are passed to the driver separately
  from the SQL text; this module never interpolates caller values into a
  statement.
* **Read-only by default.** Every transaction is ``BEGIN READ ONLY`` unless the
  caller explicitly asks for a read-write transaction.
* **Least privilege / fail-closed.** The adapter connects as whatever principal
  the DSN names (operators are expected to supply a least-privilege role — see
  ADR-0002); when the database cannot be reached, operations raise
  :class:`~queryshield.errors.DatabaseConnectionError` and the health check
  reports unhealthy. There is no insecure fallback.

See the trust boundary in :mod:`queryshield.db.base`: this adapter executes
already-validated SQL; it does not authorize queries.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg import AsyncConnection, AsyncCursor
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import TupleRow
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from queryshield.config import DatabaseConfig
from queryshield.db.base import DatabaseAdapter, DatabaseSession, HealthCheckResult, Row
from queryshield.errors import DatabaseConnectionError, DatabaseExecutionError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # Only the type checker evaluates this subscription; ``from __future__ import
    # annotations`` keeps every runtime annotation a string, so the generic alias
    # never needs to exist at import time.
    _Pool = AsyncConnectionPool[AsyncConnection[TupleRow]]


def sanitize_dsn(dsn: str) -> str:
    """Return a non-secret, human-readable descriptor of a connection string.

    Keeps the connection *target* (host, port, database, user) for diagnostics
    and drops the password entirely. Unparseable input yields a placeholder
    rather than echoing the raw string.
    """
    try:
        info = conninfo_to_dict(dsn)
    except psycopg.Error:
        return "<unparseable postgresql dsn>"
    parts = [
        f"{key}={info[key]}"
        for key in ("host", "hostaddr", "port", "dbname", "user")
        if info.get(key)
    ]
    return " ".join(parts) if parts else "<postgresql>"


def scrub_secrets(text: str, secrets: Iterable[str]) -> str:
    """Replace every occurrence of each secret in ``text`` with ``***``."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


class PostgreSQLAdapter(DatabaseAdapter):
    """Async PostgreSQL adapter backed by a psycopg 3 connection pool."""

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        raw_dsn = config.url.get_secret_value()
        self._dsn = raw_dsn
        self._display = sanitize_dsn(raw_dsn)
        self._secrets = _collect_secrets(raw_dsn)
        self._connect_kwargs = _build_connect_kwargs(config)
        self._pool: _Pool | None = None

    async def open(self) -> None:
        if self._pool is not None:
            return
        pool: _Pool = AsyncConnectionPool(
            conninfo=self._dsn,
            min_size=self._config.pool_min_size,
            max_size=self._config.pool_max_size,
            timeout=self._config.pool_timeout,
            kwargs=self._connect_kwargs,
            open=False,
            name="queryshield",
        )
        try:
            await pool.open(wait=True, timeout=self._config.connect_timeout)
        except (PoolTimeout, psycopg.Error, OSError) as exc:
            await pool.close()
            raise DatabaseConnectionError(self._safe_error(exc)) from exc
        self._pool = pool
        logger.debug("opened PostgreSQL connection pool (%s)", self._display)

    async def close(self) -> None:
        pool, self._pool = self._pool, None
        if pool is not None:
            await pool.close()
            logger.debug("closed PostgreSQL connection pool (%s)", self._display)

    async def health_check(self) -> HealthCheckResult:
        pool = self._pool
        if pool is None:
            return HealthCheckResult(
                healthy=False, error="database adapter is not open"
            )
        start = time.perf_counter()
        try:
            async with pool.connection(timeout=self._config.pool_timeout) as conn:
                conn.read_only = True
                await conn.execute("SELECT 1")
        except (PoolTimeout, psycopg.Error, OSError, TimeoutError) as exc:
            logger.warning("PostgreSQL health check failed (%s)", self._display)
            return HealthCheckResult(healthy=False, error=self._safe_error(exc))
        latency_ms = (time.perf_counter() - start) * 1000.0
        return HealthCheckResult(healthy=True, latency_ms=latency_ms)

    @asynccontextmanager
    async def transaction(
        self, *, read_only: bool = True
    ) -> AsyncIterator[DatabaseSession]:
        pool = self._require_pool()
        try:
            async with pool.connection(timeout=self._config.pool_timeout) as conn:
                conn.read_only = read_only
                async with conn.transaction():
                    yield _PsycopgSession(conn, self._secrets)
        except (PoolTimeout, psycopg.OperationalError, OSError) as exc:
            raise DatabaseConnectionError(self._safe_error(exc)) from exc
        except psycopg.Error as exc:
            raise DatabaseExecutionError(self._safe_error(exc)) from exc

    async def execute(
        self,
        query: str,
        params: Sequence[Any] | None = None,
        *,
        read_only: bool = True,
    ) -> None:
        async with self.transaction(read_only=read_only) as session:
            await session.execute(query, params)

    async def fetch_all(
        self,
        query: str,
        params: Sequence[Any] | None = None,
        *,
        read_only: bool = True,
    ) -> list[Row]:
        async with self.transaction(read_only=read_only) as session:
            return await session.fetch_all(query, params)

    async def fetch_one(
        self,
        query: str,
        params: Sequence[Any] | None = None,
        *,
        read_only: bool = True,
    ) -> Row | None:
        async with self.transaction(read_only=read_only) as session:
            return await session.fetch_one(query, params)

    def _require_pool(self) -> _Pool:
        if self._pool is None:
            raise DatabaseConnectionError(
                "database adapter is not open; call open() before using it"
            )
        return self._pool

    def _safe_error(self, exc: BaseException) -> str:
        message = scrub_secrets(f"{type(exc).__name__}: {exc}", self._secrets)
        return f"{message} [target: {self._display}]"


class _PsycopgSession:
    """Concrete :class:`~queryshield.db.base.DatabaseSession` over one connection."""

    def __init__(
        self, conn: AsyncConnection[TupleRow], secrets: tuple[str, ...]
    ) -> None:
        self._conn = conn
        self._secrets = secrets

    async def execute(self, query: str, params: Sequence[Any] | None = None) -> None:
        await self._run(query, params)

    async def fetch_all(
        self, query: str, params: Sequence[Any] | None = None
    ) -> list[Row]:
        cursor = await self._run(query, params)
        return await cursor.fetchall()

    async def fetch_one(
        self, query: str, params: Sequence[Any] | None = None
    ) -> Row | None:
        cursor = await self._run(query, params)
        return await cursor.fetchone()

    async def _run(
        self, query: str, params: Sequence[Any] | None
    ) -> AsyncCursor[TupleRow]:
        try:
            return await self._conn.execute(query, params)
        except psycopg.Error as exc:
            message = scrub_secrets(f"{type(exc).__name__}: {exc}", self._secrets)
            raise DatabaseExecutionError(message) from exc


def _collect_secrets(raw_dsn: str) -> tuple[str, ...]:
    """Secret substrings to scrub from any outgoing message for this adapter."""
    secrets = [raw_dsn]
    try:
        password = conninfo_to_dict(raw_dsn).get("password")
    except psycopg.Error:
        password = None
    if password:
        secrets.append(password)
    return tuple(secrets)


def _build_connect_kwargs(config: DatabaseConfig) -> dict[str, Any]:
    """Per-connection libpq keyword arguments derived from the config.

    ``statement_timeout`` is applied via the libpq ``options`` parameter at
    connection start-up (no runtime ``SET`` needed), so it covers every session
    handed out by the pool.
    """
    kwargs: dict[str, Any] = {"connect_timeout": max(1, round(config.connect_timeout))}
    options: list[str] = []
    if config.statement_timeout is not None:
        options.append(f"-c statement_timeout={int(config.statement_timeout * 1000)}")
    if options:
        kwargs["options"] = " ".join(options)
    if config.sslmode is not None:
        kwargs["sslmode"] = config.sslmode
    return kwargs
