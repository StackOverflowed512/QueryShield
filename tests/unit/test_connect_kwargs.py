"""Tests for libpq connect-kwargs derivation (:func:`_build_connect_kwargs`).

These need no database. They prove the security-relevant translation of a
configured ``statement_timeout`` (seconds) into the libpq ``options`` string
(milliseconds) is fail-closed: a positive timeout can never collapse to
``statement_timeout=0``, which PostgreSQL interprets as *no* limit.
"""

from __future__ import annotations

import pytest

from queryshield.config import DatabaseConfig
from queryshield.db.postgres import _build_connect_kwargs

pytestmark = pytest.mark.unit

_DSN = "postgresql://alice:pw@db.internal:5432/payments"


def _config(**overrides: object) -> DatabaseConfig:
    data: dict[str, object] = {"url": _DSN}
    data.update(overrides)
    return DatabaseConfig.model_validate(data)


def test_statement_timeout_seconds_become_milliseconds() -> None:
    kwargs = _build_connect_kwargs(_config(statement_timeout=30.0))
    assert kwargs["options"] == "-c statement_timeout=30000"


def test_positive_statement_timeout_is_never_silently_disabled() -> None:
    # 0.0005 s * 1000 == 0.5 ms; the old int() truncation produced
    # statement_timeout=0 (PostgreSQL "no limit"), silently disabling the
    # control. The 1 ms floor keeps a positive timeout positive.
    kwargs = _build_connect_kwargs(_config(statement_timeout=0.0005))
    assert kwargs["options"] == "-c statement_timeout=1"
    assert "statement_timeout=0" not in kwargs["options"]


def test_statement_timeout_none_adds_no_option() -> None:
    kwargs = _build_connect_kwargs(_config(statement_timeout=None))
    assert "options" not in kwargs
