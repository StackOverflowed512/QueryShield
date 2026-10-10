"""Concrete PostgreSQL SQL parser, built on pglast (libpg_query).

pglast binds **libpg_query**, which is PostgreSQL's *own* parser extracted into a
standalone library. Using it means QueryShield parses SQL with the same grammar
the database will execute it with, which removes the parser differential by
construction — the security concern called out in ``CLAUDE.md`` §3 and decided in
ADR-0003. This module is the only place that knows about pglast; everything it
returns is a QueryShield-owned :class:`~queryshield.sql.models.ParsedQuery`
(ADR-0029).

How the analysis works, and why:

* **Classification comes from the AST, never the string** (ADR-0030). The
  statement kind is read from the parsed node's type, and "is this a batch of
  statements?" is read from how many statements ``parse_sql`` returned. There is
  no ``str.startswith``, no ``sql.split(";")``, and no regular expression
  anywhere in this file.
* **The walk is reflective, not typed against pglast's class tree.** pglast's
  node classes are generated from PostgreSQL's ``parsenodes`` and expose their
  field names through ``__slots__``. The analyzer reads those slots and recurses,
  dispatching on ``type(node).__name__``. It therefore depends only on pglast's
  *stable* surface — ``parse_sql``, ``ParseError``, node class names, and
  ``__slots__`` — and not on node constructors or a ``Visitor`` API, so a pglast
  release that reshapes its Python wrapper does not silently change what we see.
* **Fail closed, all-or-nothing** (ADR-0031). Any input pglast cannot parse
  raises :class:`~queryshield.errors.SQLParseError` with pglast's exception
  chained as ``__cause__``. Nothing here returns a partial structure, and there
  is no fallback to another dialect.

Known limitations, deliberately accepted in this phase (see
``docs/IMPLEMENTATION_STATUS.md``): the analyzer does **not** resolve names to
catalog objects (that needs the schema catalog and the policy layer); DDL target
names such as ``DROP TABLE x`` are not lowered to
:class:`~queryshield.sql.models.TableReference` (the AST names them through a
different node shape than a ``FROM`` reference); an implicit comma join is not
represented as a :class:`~queryshield.sql.models.JoinType` (PostgreSQL models it
as a list, not a join node); and a ``CROSS JOIN`` is reported as
:attr:`~queryshield.sql.models.JoinType.INNER` because PostgreSQL represents both
with the same join node. None of these is a safety claim — they are simply the
shape of what the parser reports.
"""

from __future__ import annotations

from typing import Any

from queryshield.errors import SQLParseError
from queryshield.sql.base import SQLParser
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

#: The dialect this parser understands. QueryShield's SQL layer is PostgreSQL by
#: construction — pglast binds libpg_query, which *is* PostgreSQL's parser — so
#: there is no other dialect to fall back to (ADR-0003, ADR-0031).
_DIALECT = "postgresql"

#: Maps a top-level statement node's class name to its kind. A name absent from
#: this table is classified :attr:`StatementType.UNKNOWN` — the fail-safe bucket,
#: never a stand-in for "harmless".
_STATEMENT_TYPES: dict[str, StatementType] = {
    "SelectStmt": StatementType.SELECT,
    "InsertStmt": StatementType.INSERT,
    "UpdateStmt": StatementType.UPDATE,
    "DeleteStmt": StatementType.DELETE,
    "MergeStmt": StatementType.MERGE,
    "CreateStmt": StatementType.CREATE,
    "CreateTableAsStmt": StatementType.CREATE,
    "CreateIndexStmt": StatementType.CREATE,
    "CreateSeqStmt": StatementType.CREATE,
    "CreateSchemaStmt": StatementType.CREATE,
    "CreateExtensionStmt": StatementType.CREATE,
    "CreateFunctionStmt": StatementType.CREATE,
    "CreateRoleStmt": StatementType.CREATE,
    "CreateDatabaseStmt": StatementType.CREATE,
    "ViewStmt": StatementType.CREATE,
    "AlterTableStmt": StatementType.ALTER,
    "AlterDomainStmt": StatementType.ALTER,
    "AlterEnumStmt": StatementType.ALTER,
    "AlterOwnerStmt": StatementType.ALTER,
    "AlterRoleStmt": StatementType.ALTER,
    "RenameStmt": StatementType.ALTER,
    "DropStmt": StatementType.DROP,
    "DropdbStmt": StatementType.DROP,
    "DropRoleStmt": StatementType.DROP,
    "TruncateStmt": StatementType.TRUNCATE,
    "CallStmt": StatementType.CALL,
    # GRANT and REVOKE share one node type each (GrantStmt for privileges,
    # GrantRoleStmt for role membership) and are told apart by the `is_grant`
    # flag, so they are classified in _classify(), not through this table.
}

_JOIN_TYPES: dict[str, JoinType] = {
    "JOIN_INNER": JoinType.INNER,
    "JOIN_LEFT": JoinType.LEFT,
    "JOIN_RIGHT": JoinType.RIGHT,
    "JOIN_FULL": JoinType.FULL,
}


def _load_pglast() -> tuple[Any, Any, Any]:
    """Import pglast lazily and return ``(parse_sql, Error, ast_module)``.

    ``pglast.Error`` (defined in ``pglast.error``) is the base exception pglast
    raises when libpg_query cannot parse a statement — catching it is how an
    unparseable candidate becomes a fail-closed :class:`SQLParseError`. pglast
    does not export a ``ParseError`` name.

    Kept lazy so that importing :mod:`queryshield` or the SQL *models* does not
    load the compiled libpg_query extension until a parse is actually requested.
    """
    from pglast import Error, ast, parse_sql

    return parse_sql, Error, ast


def _field_names(node: object) -> tuple[str, ...]:
    """Return the public field names of a pglast node, gathered from ``__slots__``.

    pglast exposes each node's fields through ``__slots__`` (this is how it
    renders nodes). Collecting them across the MRO and dropping private slots
    yields the attributes worth walking. A node with no such slots is a leaf.
    """
    names: list[str] = []
    for klass in type(node).__mro__:
        slots = klass.__dict__.get("__slots__", ())
        if isinstance(slots, str):
            slots = (slots,)
        for name in slots:
            if isinstance(name, str) and not name.startswith("_"):
                names.append(name)
    return tuple(dict.fromkeys(names))


def _classify(node: object) -> StatementType:
    """Classify a statement node from the AST — never from its text.

    GRANT and REVOKE share a single node type (``GrantStmt`` for object
    privileges, ``GrantRoleStmt`` for role membership); PostgreSQL distinguishes
    the two with the boolean ``is_grant`` field, not a separate node and not the
    leading keyword. Reading that flag is still AST-driven classification.
    """
    type_name = type(node).__name__
    if type_name in ("GrantStmt", "GrantRoleStmt"):
        is_grant = bool(getattr(node, "is_grant", True))
        return StatementType.GRANT if is_grant else StatementType.REVOKE
    return _STATEMENT_TYPES.get(type_name, StatementType.UNKNOWN)


def _outer_select(root: object) -> object | None:
    """Return the outermost ``SELECT`` node of a statement, if it has one.

    The structural flags (DISTINCT, GROUP BY, ORDER BY, LIMIT, …) describe the
    *outermost* query of the statement — for ``EXPLAIN SELECT …`` or
    ``INSERT … SELECT …`` that is the inner select, reached through a small set
    of known wrapper fields. Returns ``None`` for a statement with no select.
    """
    node: object | None = root
    for _ in range(8):
        if node is None:
            return None
        if type(node).__name__ == "SelectStmt":
            return node
        child = getattr(node, "query", None)
        if child is None:
            child = getattr(node, "selectStmt", None)
        node = child
    return None


def _present(node: object | None, field: str) -> bool:
    """True when ``node`` carries a non-``None`` value for ``field``."""
    if node is None:
        return False
    return getattr(node, field, None) is not None


def _string_values(items: object) -> list[str]:
    """Return the ``sval`` strings of a list of pglast ``String`` nodes, in order."""
    values: list[str] = []
    if not isinstance(items, (list, tuple)):
        return values
    for item in items:
        sval = getattr(item, "sval", None)
        if isinstance(sval, str):
            values.append(sval)
    return values


class _Analyzer:
    """Walks one pglast statement node and accumulates its structure.

    The accumulator is a plain mutable object during the walk; :class:`ParsedQuery`
    is frozen only once it is assembled, so no partially-built result can escape.
    """

    def __init__(self, ast_module: Any) -> None:
        self._ast = ast_module
        self.tables: list[TableReference] = []
        self.columns: list[ColumnReference] = []
        self.functions: list[FunctionCall] = []
        self.ctes: list[CommonTableExpression] = []
        self.joins: list[JoinType] = []
        self.set_operations: list[SetOperation] = []
        self.parameters: set[int] = set()
        self.literal_count = 0
        self.has_subqueries = False
        self.has_window_functions = False
        self._visitors = {
            "RangeVar": self._visit_range_var,
            "CommonTableExpr": self._visit_common_table_expr,
            "ColumnRef": self._visit_column_ref,
            "FuncCall": self._visit_func_call,
            "WindowDef": self._visit_window_def,
            "SubLink": self._visit_sub_link,
            "RangeSubselect": self._visit_range_subselect,
            "ParamRef": self._visit_param_ref,
            "A_Const": self._visit_a_const,
            "JoinExpr": self._visit_join_expr,
            "SelectStmt": self._visit_select_stmt,
        }

    def analyze(self, root: object) -> None:
        self._walk(root)

    def _is_node(self, obj: object) -> bool:
        return isinstance(obj, self._ast.Node)

    def _walk(self, node: object) -> None:
        if node is None:
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                self._walk(item)
            return
        if not self._is_node(node):
            return
        visitor = self._visitors.get(type(node).__name__)
        if visitor is not None:
            visitor(node)
        for field in _field_names(node):
            self._walk(getattr(node, field, None))

    # -- visitors -----------------------------------------------------------

    def _visit_range_var(self, node: Any) -> None:
        relname = getattr(node, "relname", None)
        if not isinstance(relname, str):
            return
        schemaname = getattr(node, "schemaname", None)
        alias = getattr(node, "alias", None)
        alias_name = getattr(alias, "aliasname", None)
        self.tables.append(
            TableReference(
                schema=schemaname if isinstance(schemaname, str) else None,
                name=relname,
                alias=alias_name if isinstance(alias_name, str) else None,
            )
        )

    def _visit_common_table_expr(self, node: Any) -> None:
        name = getattr(node, "ctename", None)
        if isinstance(name, str):
            self.ctes.append(
                CommonTableExpression(
                    name=name,
                    recursive=bool(getattr(node, "cterecursive", False)),
                )
            )

    def _visit_column_ref(self, node: Any) -> None:
        fields = getattr(node, "fields", None)
        names = _string_values(fields)
        is_star = any(type(item).__name__ == "A_Star" for item in (fields or ()))
        if is_star:
            qualifier = ".".join(names) if names else None
            self.columns.append(ColumnReference(qualifier, "", is_star=True))
        elif names:
            qualifier = ".".join(names[:-1]) if len(names) > 1 else None
            self.columns.append(ColumnReference(qualifier, names[-1]))

    def _visit_func_call(self, node: Any) -> None:
        names = _string_values(getattr(node, "funcname", None))
        if not names:
            return
        schema = ".".join(names[:-1]) if len(names) > 1 else None
        self.functions.append(FunctionCall(schema=schema, name=names[-1]))

    def _visit_window_def(self, node: Any) -> None:
        self.has_window_functions = True

    def _visit_sub_link(self, node: Any) -> None:
        self.has_subqueries = True

    def _visit_range_subselect(self, node: Any) -> None:
        self.has_subqueries = True

    def _visit_param_ref(self, node: Any) -> None:
        number = getattr(node, "number", None)
        if isinstance(number, int):
            self.parameters.add(number)

    def _visit_a_const(self, node: Any) -> None:
        self.literal_count += 1

    def _visit_join_expr(self, node: Any) -> None:
        jointype = getattr(node, "jointype", None)
        name = getattr(jointype, "name", None)
        key = name if isinstance(name, str) else ""
        self.joins.append(_JOIN_TYPES.get(key, JoinType.OTHER))

    def _visit_select_stmt(self, node: Any) -> None:
        # In a *raw* parse tree a set operation (UNION/INTERSECT/EXCEPT) is a
        # SelectStmt whose ``op`` is not ``SETOP_NONE``, with the two operands in
        # ``larg``/``rarg``. libpg_query only lowers this into a distinct
        # ``SetOperationStmt`` during parse *analysis*, which ``parse_sql`` does
        # not run — so the set operator must be read here, off the SelectStmt.
        # A plain SELECT has ``op == SETOP_NONE`` and records nothing.
        op = getattr(node, "op", None)
        name = getattr(op, "name", None)
        if name is None or name == "SETOP_NONE":
            return
        all_flag = bool(getattr(node, "all", False))
        self.set_operations.append(SetOperation(_set_operation_type(name, all_flag)))


def _set_operation_type(op_name: object, all_flag: bool) -> SetOperationType:
    """Map pglast's set-operation enum name plus the ``ALL`` flag to our type."""
    if op_name == "SETOP_UNION":
        return SetOperationType.UNION_ALL if all_flag else SetOperationType.UNION
    if op_name == "SETOP_INTERSECT":
        return (
            SetOperationType.INTERSECT_ALL if all_flag else SetOperationType.INTERSECT
        )
    if op_name == "SETOP_EXCEPT":
        return SetOperationType.EXCEPT_ALL if all_flag else SetOperationType.EXCEPT
    return SetOperationType.OTHER


def _parse_error_message(exc: BaseException) -> str:
    """Build a SQLParseError message, preserving the parser's diagnostic text."""
    detail = str(exc).strip()
    if detail:
        return f"could not parse SQL in the {_DIALECT} dialect: {detail}"
    return f"could not parse SQL in the {_DIALECT} dialect"


class PostgreSQLSQLParser(SQLParser):
    """The concrete :class:`~queryshield.sql.base.SQLParser` for PostgreSQL.

    Stateless and side-effect free: it holds no connection, takes no database
    session, and executes nothing. Every call is independent and deterministic —
    the same SQL string always yields the same :class:`ParsedQuery`.
    """

    @property
    def dialect(self) -> str:
        """The SQL dialect this parser speaks — always ``"postgresql"``."""
        return _DIALECT

    async def parse(self, sql: str) -> ParsedQuery:
        if not isinstance(sql, str):
            raise SQLParseError("candidate SQL must be a string")

        parse_sql, parse_error, ast_module = _load_pglast()

        try:
            parsed = parse_sql(sql)
        except parse_error as exc:
            raise SQLParseError(_parse_error_message(exc)) from exc

        statements = tuple(parsed)
        if not statements:
            # Empty, whitespace-only, or comment-only input: there is no
            # statement to describe, which is not the same as "safe".
            raise SQLParseError("no SQL statement found in the candidate input")

        # Analyse *every* statement, not just the first. A multi-statement batch
        # must be described completely or not at all (ADR-0031): reporting
        # ``statement_count > 1`` while only extracting the first statement's
        # relations would silently hide the rest — e.g. the DROP in
        # ``SELECT ...; DROP TABLE ...`` — which is the opposite of fail-closed.
        roots: list[object] = []
        tables: list[TableReference] = []
        columns: list[ColumnReference] = []
        functions: list[FunctionCall] = []
        ctes: list[CommonTableExpression] = []
        joins: list[JoinType] = []
        set_operations: list[SetOperation] = []
        parameters: set[int] = set()
        literal_count = 0
        has_subqueries = False
        has_window_functions = False

        for statement in statements:
            root = getattr(statement, "stmt", None)
            if root is None or not isinstance(root, ast_module.Node):
                raise SQLParseError("the parser returned no statement node")
            roots.append(root)

            analyzer = _Analyzer(ast_module)
            analyzer.analyze(root)

            # CTE shadowing is resolved *within* a statement: a bare name that
            # matches a CTE declared in the same statement is a reference to that
            # CTE, not a physical relation. Scoping this per statement avoids a
            # CTE in one statement erasing a real table of the same name in
            # another (which would under-report the relations touched).
            statement_cte_names = {cte.name for cte in analyzer.ctes}
            tables.extend(
                table
                for table in analyzer.tables
                if not (table.schema is None and table.name in statement_cte_names)
            )
            columns.extend(analyzer.columns)
            functions.extend(analyzer.functions)
            ctes.extend(analyzer.ctes)
            joins.extend(analyzer.joins)
            set_operations.extend(analyzer.set_operations)
            parameters.update(analyzer.parameters)
            literal_count += analyzer.literal_count
            has_subqueries = has_subqueries or analyzer.has_subqueries
            has_window_functions = has_window_functions or analyzer.has_window_functions

        # The structural flags describe the whole input: a flag is set when the
        # feature appears in *any* statement's outermost query.
        outers = [_outer_select(root) for root in roots]

        return ParsedQuery(
            # ``statement_type`` is the kind of the first statement; a batch is
            # signalled by ``statement_count``/``is_multi_statement``, and the
            # relation/column/function lists above cover every statement.
            statement_type=_classify(roots[0]),
            original_sql=sql,
            statement_count=len(statements),
            tables=tuple(tables),
            columns=tuple(columns),
            functions=tuple(functions),
            ctes=tuple(ctes),
            joins=tuple(joins),
            set_operations=tuple(set_operations),
            parameters=tuple(sorted(parameters)),
            literal_count=literal_count,
            has_subqueries=has_subqueries,
            has_distinct=any(_present(o, "distinctClause") for o in outers),
            has_grouping=any(_present(o, "groupClause") for o in outers),
            has_having=any(_present(o, "havingClause") for o in outers),
            has_ordering=any(_present(o, "sortClause") for o in outers),
            has_limit=any(_present(o, "limitCount") for o in outers),
            has_offset=any(_present(o, "limitOffset") for o in outers),
            has_window_functions=has_window_functions,
            has_locking_clause=any(_present(o, "lockingClause") for o in outers),
        )
