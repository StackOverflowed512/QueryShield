"""Integration tests for :class:`queryshield.db.postgres.PostgreSQLAdapter`.

Exercises the real behaviours the Phase 2 spec requires against a live
PostgreSQL: connection + health check, pool acquire/release, a parameterised
operation, commit, rollback, clean pool shutdown, and a connection failure
(invalid credentials) that is reported clearly and without leaking the password.

Every test here is marked ``integration`` and skips when
``QUERYSHIELD_TEST_DATABASE_URL`` is unset (see ``conftest.py``).
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
from pydantic import SecretStr

from queryshield.config import DatabaseConfig
from queryshield.db import PostgreSQLAdapter
from queryshield.errors import DatabaseConnectionError, DatabaseExecutionError

pytestmark = pytest.mark.integration


async def test_health_check_reports_healthy(adapter: PostgreSQLAdapter) -> None:
    result = await adapter.health_check()
    assert result.healthy is True
    assert result.error is None
    assert result.latency_ms is not None
    assert result.latency_ms >= 0.0


async def test_pool_acquire_and_release_under_concurrency(
    adapter: PostgreSQLAdapter,
) -> None:
    # More concurrent queries than max pool size: forces acquire/wait/release.
    results = await asyncio.gather(
        *(adapter.fetch_one("SELECT %s::int", [i]) for i in range(20))
    )
    values = sorted(row[0] for row in results if row is not None)
    assert values == list(range(20))
    # Pool is usable again afterwards (connections were returned, not leaked).
    assert (await adapter.health_check()).healthy is True


async def test_parameterized_fetch_one(adapter: PostgreSQLAdapter) -> None:
    row = await adapter.fetch_one("SELECT %s::int + %s::int", [2, 40])
    assert row == (42,)


async def test_parameterized_values_are_not_interpolated(
    adapter: PostgreSQLAdapter,
) -> None:
    # A value that would be catastrophic if string-interpolated must come back as
    # plain data, proving it was bound as a parameter, not spliced into the SQL.
    hostile = "1); DROP TABLE does_not_exist; --"
    row = await adapter.fetch_one("SELECT %s::text", [hostile])
    assert row == (hostile,)


async def test_commit_persists_across_connections(
    adapter: PostgreSQLAdapter, temp_table: str
) -> None:
    async with adapter.transaction(read_only=False) as session:
        await session.execute(
            f'INSERT INTO "{temp_table}" (id, label) VALUES (%s, %s)', [1, "kept"]
        )
    # Separate transaction (possibly a different pooled connection) sees it.
    row = await adapter.fetch_one(
        f'SELECT label FROM "{temp_table}" WHERE id = %s', [1]
    )
    assert row == ("kept",)


async def test_rollback_discards_on_error(
    adapter: PostgreSQLAdapter, temp_table: str
) -> None:
    class _Boom(Exception):
        pass

    with pytest.raises(_Boom):
        async with adapter.transaction(read_only=False) as session:
            await session.execute(
                f'INSERT INTO "{temp_table}" (id, label) VALUES (%s, %s)',
                [2, "discarded"],
            )
            raise _Boom

    row = await adapter.fetch_one(
        f'SELECT label FROM "{temp_table}" WHERE id = %s', [2]
    )
    assert row is None


async def test_write_blocked_in_readonly_transaction(
    adapter: PostgreSQLAdapter, temp_table: str
) -> None:
    # Security-by-default: the default transaction is READ ONLY, so a write is
    # rejected by PostgreSQL and surfaced as a QueryShield execution error.
    with pytest.raises(DatabaseExecutionError):
        await adapter.execute(
            f'INSERT INTO "{temp_table}" (id, label) VALUES (%s, %s)', [3, "nope"]
        )


async def test_operations_fail_after_shutdown(db_config: DatabaseConfig) -> None:
    adapter = PostgreSQLAdapter(db_config)
    await adapter.open()
    assert (await adapter.health_check()).healthy is True
    await adapter.close()

    # Health check on a closed adapter reports unhealthy, not a crash.
    closed = await adapter.health_check()
    assert closed.healthy is False

    # And using it raises a clear connection error rather than silently working.
    with pytest.raises(DatabaseConnectionError):
        await adapter.fetch_one("SELECT 1")


async def test_invalid_credentials_reported_without_leaking_secret(
    test_dsn: str,
) -> None:
    bad_dsn, bad_password = _with_wrong_password(test_dsn)
    # min_size=0 so open() does not eagerly connect; the auth failure surfaces at
    # health-check time, quickly and clearly.
    config = DatabaseConfig(
        url=SecretStr(bad_dsn),
        pool_min_size=0,
        pool_max_size=2,
        connect_timeout=3.0,
        pool_timeout=3.0,
    )
    adapter = PostgreSQLAdapter(config)
    await adapter.open()
    try:
        result = await adapter.health_check()
        assert result.healthy is False
        assert result.error
        assert bad_password not in result.error  # never leak the password
    finally:
        await adapter.close()


def _with_wrong_password(dsn: str) -> tuple[str, str]:
    """Return ``dsn`` with its password replaced by a fresh wrong one."""
    parts = urlsplit(dsn)
    wrong_password = "wrong_" + uuid4().hex
    user = parts.username or "postgres"
    host = parts.hostname or "localhost"
    port = f":{parts.port}" if parts.port else ""
    netloc = f"{user}:{wrong_password}@{host}{port}"
    bad = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return bad, wrong_password
