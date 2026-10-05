"""Tests for the ``queryshield`` package foundation.

Phase 1 ships no application behavior, so these tests assert the one thing that
genuinely exists and must stay true: the package is importable, its version is a
well-formed string, and the in-code version agrees with the installed
distribution's metadata (i.e. the Hatchling dynamic-version wiring works). These
are real invariants, not ``assert True`` placeholders.
"""

from __future__ import annotations

import importlib
import importlib.metadata

import queryshield


def test_package_is_importable() -> None:
    module = importlib.import_module("queryshield")
    assert module is queryshield


def test_version_is_non_empty_string() -> None:
    assert isinstance(queryshield.__version__, str)
    assert queryshield.__version__


def test_version_has_dotted_numeric_form() -> None:
    parts = queryshield.__version__.split(".")
    assert len(parts) >= 2
    assert parts[0].isdigit()
    assert parts[1].isdigit()


def test_in_code_version_matches_distribution_metadata() -> None:
    # Guards the single-source-of-truth wiring: the literal in
    # src/queryshield/__init__.py is what Hatchling records as the distribution
    # version. If these ever diverge, the packaging is misconfigured.
    assert importlib.metadata.version("queryshield") == queryshield.__version__


def test_public_api_is_curated_and_small() -> None:
    # The top level exposes the config model/loader and the error hierarchy —
    # and nothing more. Neither the database adapter nor the schema retriever is
    # a top-level export: they live under ``queryshield.db`` and
    # ``queryshield.schema`` as lower-level components. Phase 3 adds only the
    # three schema *errors* to the top-level hierarchy.
    expected = {
        "__version__",
        "QueryShieldConfig",
        "DatabaseConfig",
        "load_config",
        "QueryShieldError",
        "ConfigError",
        "DatabaseError",
        "DatabaseConnectionError",
        "DatabaseExecutionError",
        "SchemaError",
        "SchemaRetrievalError",
        "SchemaMetadataError",
    }
    assert set(queryshield.__all__) == expected
    assert "PostgreSQLAdapter" not in queryshield.__all__
    assert not hasattr(queryshield, "PostgreSQLAdapter")
    # The retriever is reachable through its subpackage, not the top level.
    assert "PostgreSQLSchemaRetriever" not in queryshield.__all__
    assert not hasattr(queryshield, "PostgreSQLSchemaRetriever")


def test_every_exported_name_is_resolvable() -> None:
    for name in queryshield.__all__:
        assert hasattr(queryshield, name), name
