"""Tests for DSN sanitisation and secret scrubbing.

These are security-critical and need no database: they prove that the adapter's
helpers never surface a password in a descriptor or an error message. They do
import :mod:`queryshield.db.postgres` (hence psycopg), but they never connect.
"""

from __future__ import annotations

import pytest

from queryshield.db.postgres import sanitize_dsn, scrub_secrets

pytestmark = pytest.mark.unit

_PASSWORD = "TOPSECRET-pw"
_URL = f"postgresql://alice:{_PASSWORD}@db.internal:5432/payments"


def test_sanitize_dsn_drops_password_keeps_target() -> None:
    descriptor = sanitize_dsn(_URL)
    assert _PASSWORD not in descriptor
    assert "alice" in descriptor
    assert "db.internal" in descriptor
    assert "payments" in descriptor


def test_sanitize_dsn_handles_unparseable_input_without_echoing_it() -> None:
    descriptor = sanitize_dsn("::: not a dsn :::")
    assert "not a dsn" not in descriptor
    assert descriptor.startswith("<")


def test_scrub_secrets_masks_every_occurrence() -> None:
    message = f"connection to {_URL} failed: password {_PASSWORD} rejected"
    scrubbed = scrub_secrets(message, (_PASSWORD, _URL))
    assert _PASSWORD not in scrubbed
    assert _URL not in scrubbed
    assert "***" in scrubbed


def test_scrub_secrets_ignores_empty_secrets() -> None:
    # An empty secret must not turn into a mask that corrupts the whole string.
    assert scrub_secrets("hello", ("",)) == "hello"
