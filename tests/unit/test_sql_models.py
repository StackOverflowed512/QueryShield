"""Tests for the QueryShield-owned parsed-SQL model.

These exercise the model in isolation — no parser, no pglast, no database — so
they assert the invariants the rest of the pipeline relies on: the types are
immutable, identifiers are preserved verbatim, and the derived views
(``table_names``/``cte_names``/``function_names``) deduplicate deterministically.
"""

from __future__ import annotations

import dataclasses

import pytest

from queryshield.sql.models import (
    ColumnReference,
    CommonTableExpression,
    FunctionCall,
    JoinType,
    ParsedQuery,
    SetOperation,
    SetOperationType,
    StatementType,
    TableReference,
)


def _query(**overrides: object) -> ParsedQuery:
    base: dict[str, object] = {
        "statement_type": StatementType.SELECT,
        "original_sql": "SELECT 1",
        "statement_count": 1,
    }
    base.update(overrides)
    return ParsedQuery(**base)  # type: ignore[arg-type]


@pytest.mark.unit
def test_statement_types_cover_the_modelled_kinds() -> None:
    # UNKNOWN must exist and must be distinct from every real kind: it is the
    # fail-safe bucket, not an alias for anything.
    assert StatementType.UNKNOWN == "UNKNOWN"
    kinds = {member.value for member in StatementType}
    assert {"SELECT", "INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE"} <= kinds
    assert len(kinds) == len(list(StatementType))


@pytest.mark.unit
def test_union_and_union_all_are_distinct() -> None:
    assert len({SetOperationType.UNION, SetOperationType.UNION_ALL}) == 2
    assert SetOperationType.UNION.value == "UNION"
    assert SetOperationType.UNION_ALL.value == "UNION ALL"


@pytest.mark.unit
def test_parsed_query_is_frozen() -> None:
    parsed = _query()
    with pytest.raises(dataclasses.FrozenInstanceError):
        parsed.statement_type = StatementType.DROP  # type: ignore[misc]


@pytest.mark.unit
def test_reference_types_are_frozen_and_immutable() -> None:
    table = TableReference(schema=None, name="orders")
    with pytest.raises(dataclasses.FrozenInstanceError):
        table.name = "customers"  # type: ignore[misc]

    column = ColumnReference(qualifier=None, name="id")
    with pytest.raises(dataclasses.FrozenInstanceError):
        column.name = "other"  # type: ignore[misc]


@pytest.mark.unit
def test_identifiers_are_preserved_verbatim() -> None:
    # The model never case-folds: a quoted mixed-case identifier and an unquoted
    # lower-case one must survive exactly as written (ADR-0026 / ADR-0032).
    parsed = _query(
        tables=(
            TableReference(schema=None, name="Orders"),
            TableReference(schema="MySchema", name="LineItems"),
        ),
    )
    assert parsed.tables[0].name == "Orders"
    assert parsed.tables[1].schema == "MySchema"
    assert parsed.tables[1].name == "LineItems"


@pytest.mark.unit
def test_is_multi_statement_reflects_the_count() -> None:
    assert _query(statement_count=1).is_multi_statement is False
    assert _query(statement_count=2).is_multi_statement is True


@pytest.mark.unit
def test_table_names_deduplicates_and_preserves_first_seen_order() -> None:
    parsed = _query(
        tables=(
            TableReference(schema=None, name="orders"),
            TableReference(schema=None, name="customers"),
            TableReference(schema=None, name="orders"),
        ),
    )
    assert parsed.table_names == ("orders", "customers")


@pytest.mark.unit
def test_table_names_keep_schema_qualified_relations_distinct() -> None:
    # Two same-named relations in different schemas are different objects; the
    # derived view must not collapse them to one bare name (that would hide a
    # relation a downstream policy layer needs to see). A bare-named relation is
    # returned unqualified, a schema-qualified one keeps its schema.
    parsed = _query(
        tables=(
            TableReference(schema="public", name="users"),
            TableReference(schema="sales", name="users"),
            TableReference(schema=None, name="users"),
            TableReference(schema="public", name="users"),
        ),
    )
    assert parsed.table_names == ("public.users", "sales.users", "users")


@pytest.mark.unit
def test_cte_names_deduplicates_in_first_seen_order() -> None:
    parsed = _query(
        ctes=(
            CommonTableExpression(name="recent"),
            CommonTableExpression(name="totals"),
            CommonTableExpression(name="recent"),
        ),
    )
    assert parsed.cte_names == ("recent", "totals")


@pytest.mark.unit
def test_function_names_qualify_when_schema_is_present() -> None:
    parsed = _query(
        functions=(
            FunctionCall(schema=None, name="count"),
            FunctionCall(schema="pg_catalog", name="now"),
            FunctionCall(schema=None, name="count"),
        ),
    )
    assert parsed.function_names == ("count", "pg_catalog.now")


@pytest.mark.unit
def test_defaults_are_the_empty_and_false_forms() -> None:
    parsed = _query()
    assert parsed.tables == ()
    assert parsed.columns == ()
    assert parsed.functions == ()
    assert parsed.ctes == ()
    assert parsed.joins == ()
    assert parsed.set_operations == ()
    assert parsed.parameters == ()
    assert parsed.literal_count == 0
    assert parsed.has_subqueries is False
    assert parsed.has_distinct is False
    assert parsed.has_locking_clause is False


@pytest.mark.unit
def test_the_model_exposes_no_safety_verdict() -> None:
    # The parser describes structure; it must never carry a "safe"/"allowed"
    # field a downstream layer could be tempted to trust (the LLM is untrusted,
    # and so is a naive reading of this structure). Anything that looks like a
    # verdict would be a security bug.
    field_names = {field.name for field in dataclasses.fields(ParsedQuery)}
    for forbidden in ("is_safe", "safe", "allowed", "authorized", "permitted"):
        assert forbidden not in field_names
    parsed = _query()
    assert not hasattr(parsed, "is_safe")
    assert not hasattr(parsed, "is_allowed")


@pytest.mark.unit
def test_original_sql_is_retained_unchanged() -> None:
    text = "SELECT  *\n  FROM orders -- keep me"
    parsed = _query(original_sql=text)
    assert parsed.original_sql == text


@pytest.mark.unit
def test_joins_and_set_operations_are_recorded_in_order() -> None:
    parsed = _query(
        joins=(JoinType.LEFT, JoinType.INNER),
        set_operations=(
            SetOperation(SetOperationType.UNION),
            SetOperation(SetOperationType.EXCEPT),
        ),
    )
    assert parsed.joins == (JoinType.LEFT, JoinType.INNER)
    assert parsed.set_operations[0].operation is SetOperationType.UNION
    assert parsed.set_operations[1].operation is SetOperationType.EXCEPT
