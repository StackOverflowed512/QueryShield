"""Unit tests for :class:`queryshield.schema.SchemaFilter`.

The filter is the generic, configurable "which schemas do we look at" control.
These tests pin its documented behaviour: a safe system-schema-skipping default,
an optional allow-list, a deny-list applied after it, order-preserving
selection, and exact case-sensitive matching (QueryShield never case-folds a
PostgreSQL identifier).
"""

from __future__ import annotations

import pytest

from queryshield.schema import SchemaFilter

# A representative mix: PostgreSQL's own namespaces plus application schemas.
_SYSTEM = [
    "pg_catalog",
    "pg_toast",
    "pg_temp_1",
    "pg_toast_temp_1",
    "information_schema",
]
_APP = ["public", "app", "analytics", "Billing"]


@pytest.mark.unit
def test_default_skips_system_schemas_only() -> None:
    f = SchemaFilter.default()
    for name in _SYSTEM:
        assert not f.allows(name), name
    for name in _APP:
        assert f.allows(name), name


@pytest.mark.unit
def test_default_select_preserves_input_order() -> None:
    f = SchemaFilter.default()
    names = ["public", "pg_catalog", "analytics", "information_schema", "app"]
    assert f.select(names) == ["public", "analytics", "app"]


@pytest.mark.unit
def test_include_is_an_exact_allow_list() -> None:
    f = SchemaFilter.from_names(include=["app", "analytics"])
    assert f.allows("app")
    assert f.allows("analytics")
    # An application schema not on the list is excluded...
    assert not f.allows("public")
    # ...and selection honours the allow-list, preserving order.
    assert f.select(["public", "analytics", "app"]) == ["analytics", "app"]


@pytest.mark.unit
def test_include_can_name_a_system_schema_on_purpose() -> None:
    # An operator may deliberately introspect a system schema by naming it.
    f = SchemaFilter.from_names(include=["pg_catalog"])
    assert f.allows("pg_catalog")
    assert not f.allows("public")


@pytest.mark.unit
def test_exclude_is_applied_after_include() -> None:
    f = SchemaFilter.from_names(include=["app", "analytics"], exclude=["analytics"])
    assert f.allows("app")
    assert not f.allows("analytics")


@pytest.mark.unit
def test_exclude_without_include_denies_named_app_schema() -> None:
    f = SchemaFilter.from_names(exclude=["app"])
    assert not f.allows("app")
    assert f.allows("public")
    # System schemas remain excluded by the default rule.
    assert not f.allows("pg_catalog")


@pytest.mark.unit
def test_matching_is_case_sensitive() -> None:
    f = SchemaFilter.from_names(include=["app"])
    assert f.allows("app")
    assert not f.allows("App")
    assert not f.allows("APP")


@pytest.mark.unit
def test_from_names_with_no_arguments_matches_default() -> None:
    f = SchemaFilter.from_names()
    assert f.include is None
    assert f.exclude == frozenset()
    assert f.select(_SYSTEM + _APP) == _APP


@pytest.mark.unit
def test_empty_include_selects_nothing() -> None:
    # An explicit empty allow-list is "allow nothing", distinct from None.
    f = SchemaFilter.from_names(include=[])
    assert f.include == frozenset()
    assert f.select(_APP) == []
