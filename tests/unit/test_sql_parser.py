"""Tests for the PostgreSQL SQL parser (pglast / libpg_query).

These are unit tests: pglast parses in-process, deterministically and fast, so
they never touch a database and never call an LLM. They assert the *structural*
contract of the parser — classification, reference extraction, multi-statement
detection, verbatim identifiers, and fail-closed behaviour — and deliberately say
nothing about policy, because the parser makes no security decision.
"""

from __future__ import annotations

import pytest

from queryshield.errors import SQLParseError
from queryshield.sql import (
    JoinType,
    PostgreSQLSQLParser,
    SetOperationType,
    StatementType,
)


def _parser() -> PostgreSQLSQLParser:
    return PostgreSQLSQLParser()


@pytest.mark.unit
def test_parser_reports_its_dialect() -> None:
    assert _parser().dialect == "postgresql"


@pytest.mark.unit
async def test_simple_select_is_classified() -> None:
    parsed = await _parser().parse("SELECT id FROM customers")
    assert parsed.statement_type is StatementType.SELECT
    assert parsed.statement_count == 1
    assert parsed.is_multi_statement is False
    assert parsed.table_names == ("customers",)
    assert parsed.original_sql == "SELECT id FROM customers"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("INSERT INTO t (a) VALUES (1)", StatementType.INSERT),
        ("UPDATE t SET a = 1 WHERE b = 2", StatementType.UPDATE),
        ("DELETE FROM t WHERE a = 1", StatementType.DELETE),
        ("CREATE TABLE t (a int)", StatementType.CREATE),
        ("ALTER TABLE t ADD COLUMN b int", StatementType.ALTER),
        ("DROP TABLE t", StatementType.DROP),
        ("TRUNCATE t", StatementType.TRUNCATE),
        ("GRANT SELECT ON t TO someone", StatementType.GRANT),
        ("REVOKE SELECT ON t FROM someone", StatementType.REVOKE),
    ],
)
async def test_statement_kinds_are_ast_driven(
    sql: str, expected: StatementType
) -> None:
    parsed = await _parser().parse(sql)
    assert parsed.statement_type is expected


@pytest.mark.unit
async def test_unmodelled_statement_is_unknown_not_select() -> None:
    # SET is a real statement QueryShield does not model here. It must land in the
    # fail-safe bucket — and must NOT be misreported as a SELECT because it does
    # not start with the word "select". Classification reads the AST.
    parsed = await _parser().parse("SET search_path TO public")
    assert parsed.statement_type is StatementType.UNKNOWN


@pytest.mark.unit
async def test_leading_comment_does_not_confuse_classification() -> None:
    # A prefix/regex classifier could be fooled by a comment; an AST classifier
    # cannot. The statement is a DROP regardless of what the comment says.
    sql = "-- SELECT is not the statement here\nDROP TABLE t"
    parsed = await _parser().parse(sql)
    assert parsed.statement_type is StatementType.DROP


@pytest.mark.unit
async def test_schema_qualified_table_and_alias_are_preserved() -> None:
    # `Customers` is written unquoted, so PostgreSQL's grammar folds it to
    # `customers` while parsing — the parser faithfully reports that folded form.
    # (Case preservation for *quoted* identifiers is covered separately.)
    parsed = await _parser().parse("SELECT c.id FROM analytics.Customers AS c")
    assert parsed.table_names == ("customers",)
    table = parsed.tables[0]
    assert table.schema == "analytics"
    assert table.name == "customers"
    assert table.alias == "c"


@pytest.mark.unit
async def test_identifiers_keep_their_original_case() -> None:
    parsed = await _parser().parse('SELECT "MixedCase" FROM "Weird Name"')
    assert parsed.table_names == ("Weird Name",)
    column_names = {column.name for column in parsed.columns}
    assert "MixedCase" in column_names


@pytest.mark.unit
async def test_columns_and_star_are_extracted() -> None:
    parsed = await _parser().parse("SELECT t.a, t.b, t.* FROM t")
    non_star = {(c.qualifier, c.name) for c in parsed.columns if not c.is_star}
    assert ("t", "a") in non_star
    assert ("t", "b") in non_star
    assert any(c.is_star for c in parsed.columns)


@pytest.mark.unit
async def test_functions_are_extracted_and_qualified() -> None:
    parsed = await _parser().parse("SELECT count(*), pg_catalog.now() FROM t")
    assert "count" in parsed.function_names
    assert "pg_catalog.now" in parsed.function_names


@pytest.mark.unit
async def test_cte_reference_is_separated_from_physical_tables() -> None:
    # `sales` in the FROM is the CTE, not a physical relation; `orders` inside the
    # CTE body is physical. The parser exposes the CTE name and filters the
    # matching bare reference out of the table list.
    sql = "WITH sales AS (SELECT amount FROM orders) SELECT * FROM sales"
    parsed = await _parser().parse(sql)
    assert parsed.cte_names == ("sales",)
    assert parsed.table_names == ("orders",)


@pytest.mark.unit
async def test_join_types_are_recorded() -> None:
    sql = "SELECT * FROM a JOIN b ON a.id = b.id LEFT JOIN c ON b.id = c.id"
    parsed = await _parser().parse(sql)
    assert JoinType.INNER in parsed.joins
    assert JoinType.LEFT in parsed.joins


@pytest.mark.unit
async def test_union_and_union_all_are_distinguished() -> None:
    plain = await _parser().parse("SELECT a FROM t UNION SELECT a FROM u")
    all_rows = await _parser().parse("SELECT a FROM t UNION ALL SELECT a FROM u")
    assert plain.set_operations[0].operation is SetOperationType.UNION
    assert all_rows.set_operations[0].operation is SetOperationType.UNION_ALL


@pytest.mark.unit
async def test_subquery_is_flagged() -> None:
    parsed = await _parser().parse("SELECT * FROM t WHERE id IN (SELECT id FROM u)")
    assert parsed.has_subqueries is True


@pytest.mark.unit
async def test_parameters_and_literals_are_counted_separately() -> None:
    # A bound parameter ($1) is not a literal (42). The parser records the
    # parameter index and counts literals; it never interpolates or executes.
    parsed = await _parser().parse("SELECT * FROM t WHERE a = $1 AND b = 42")
    assert parsed.parameters == (1,)
    assert parsed.literal_count >= 1


@pytest.mark.unit
async def test_select_features_are_flagged() -> None:
    sql = (
        "SELECT DISTINCT a, count(*) OVER () AS c "
        "FROM t GROUP BY a HAVING count(*) > 1 "
        "ORDER BY a LIMIT 10 OFFSET 5"
    )
    parsed = await _parser().parse(sql)
    assert parsed.has_distinct is True
    assert parsed.has_grouping is True
    assert parsed.has_having is True
    assert parsed.has_ordering is True
    assert parsed.has_limit is True
    assert parsed.has_offset is True
    assert parsed.has_window_functions is True


@pytest.mark.unit
async def test_locking_clause_is_flagged() -> None:
    parsed = await _parser().parse("SELECT * FROM t FOR UPDATE")
    assert parsed.has_locking_clause is True


@pytest.mark.unit
async def test_multi_statement_batch_is_detected_not_truncated() -> None:
    # A semicolon batch must be represented, never silently reduced to its first
    # statement. The parser reports both statements and flags the batch.
    parsed = await _parser().parse("SELECT 1; DROP TABLE t")
    assert parsed.statement_count == 2
    assert parsed.is_multi_statement is True


@pytest.mark.unit
async def test_semicolon_inside_a_literal_is_not_a_statement_break() -> None:
    # The classic reason `sql.split(";")` is wrong: a semicolon inside a string
    # literal does not separate statements.
    parsed = await _parser().parse("SELECT 'a;b' AS s")
    assert parsed.statement_count == 1
    assert parsed.is_multi_statement is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "sql",
    [
        "SELCT * FROM t",
        "SELECT FROM",
        "DROP",
        "",
        "   ",
        "-- just a comment",
        "/* nothing but a comment */",
    ],
)
async def test_bad_input_fails_closed(sql: str) -> None:
    with pytest.raises(SQLParseError):
        await _parser().parse(sql)


@pytest.mark.unit
async def test_parse_error_chains_the_parser_cause() -> None:
    with pytest.raises(SQLParseError) as excinfo:
        await _parser().parse("SELCT 1")
    # The vendor parser's exception must survive as __cause__ for diagnostics.
    assert excinfo.value.__cause__ is not None


@pytest.mark.unit
async def test_non_string_input_is_rejected() -> None:
    with pytest.raises(SQLParseError):
        await _parser().parse(123)  # type: ignore[arg-type]


@pytest.mark.unit
async def test_parsing_is_deterministic() -> None:
    sql = "SELECT t.a FROM t JOIN u ON t.id = u.id WHERE t.a > 1"
    first = await _parser().parse(sql)
    second = await _parser().parse(sql)
    assert first == second


@pytest.mark.unit
async def test_result_carries_no_safety_verdict() -> None:
    # A well-formed DROP is still just structure — never a claim that it is safe
    # or allowed. Both the destructive statement and the SELECT carry no verdict.
    destructive = await _parser().parse("DROP TABLE t")
    benign = await _parser().parse("SELECT 1")
    assert destructive.statement_type is StatementType.DROP
    assert not hasattr(destructive, "is_safe")
    assert not hasattr(benign, "is_safe")
