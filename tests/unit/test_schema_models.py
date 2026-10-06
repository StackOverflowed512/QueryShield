"""Unit tests for the immutable schema domain models and the structural
fingerprint.

Two properties matter most and are tested hardest here:

* **Lookups** are exact-match and return ``None`` for a miss (QueryShield never
  case-folds an identifier).
* **The fingerprint is a pure function of structure.** The same structure yields
  the same fingerprint regardless of the order collections were assembled in;
  any structural change (type, nullability, ordinal, a new/renamed/removed
  object, an altered key/constraint/index) changes it; comments never do.
"""

from __future__ import annotations

from queryshield.schema import (
    Column,
    ForeignKey,
    Index,
    PrimaryKey,
    Schema,
    SchemaCatalog,
    Table,
    UniqueConstraint,
    View,
    compute_fingerprint,
)


def _col(
    name: str,
    data_type: str,
    ordinal: int,
    *,
    nullable: bool = True,
    default: str | None = None,
    comment: str | None = None,
) -> Column:
    return Column(
        name=name,
        data_type=data_type,
        nullable=nullable,
        ordinal=ordinal,
        default=default,
        comment=comment,
    )


def _users_table(
    *, id_type: str = "integer", comment: str | None = "people"
) -> Table:
    return Table(
        schema="app",
        name="users",
        columns=(
            _col("id", id_type, 1, nullable=False),
            _col("email", "text", 2),
        ),
        primary_key=PrimaryKey(name="users_pkey", columns=("id",)),
        unique_constraints=(
            UniqueConstraint(name="users_email_key", columns=("email",)),
        ),
        indexes=(
            Index(name="users_pkey", unique=True, primary=True, columns=("id",)),
        ),
        comment=comment,
    )


def _events_table() -> Table:
    return Table(
        schema="analytics",
        name="events",
        columns=(
            _col("id", "bigint", 1, nullable=False),
            _col("user_id", "integer", 2),
        ),
        primary_key=PrimaryKey(name="events_pkey", columns=("id",)),
        foreign_keys=(
            ForeignKey(
                name="events_user_fk",
                columns=("user_id",),
                referenced_schema="app",
                referenced_table="users",
                referenced_columns=("id",),
            ),
        ),
    )


def _active_view() -> View:
    return View(
        schema="app",
        name="active_users",
        columns=(_col("id", "integer", 1),),
    )


def _report_view() -> View:
    return View(
        schema="app",
        name="report",
        columns=(_col("id", "integer", 1),),
        materialized=True,
        indexes=(
            Index(name="report_idx", unique=False, primary=False, columns=("id",)),
        ),
    )


def _baseline() -> SchemaCatalog:
    app = Schema(
        name="app",
        tables=(_users_table(),),
        views=(_active_view(), _report_view()),
        comment="application",
    )
    analytics = Schema(name="analytics", tables=(_events_table(),))
    return SchemaCatalog.from_schemas((app, analytics))


# ---------------------------------------------------------------------------
# Lookups and container invariants
# ---------------------------------------------------------------------------


def test_from_schemas_sorts_and_reports_names() -> None:
    catalog = _baseline()
    assert catalog.schema_names == ("analytics", "app")
    assert [s.name for s in catalog.schemas] == ["analytics", "app"]
    assert not catalog.is_empty


def test_empty_catalog_is_empty() -> None:
    assert SchemaCatalog().is_empty
    assert SchemaCatalog().schema_names == ()


def test_exact_match_lookups() -> None:
    catalog = _baseline()
    assert catalog.get_schema("app") is not None
    assert catalog.get_schema("App") is None  # exact, case-sensitive
    assert catalog.get_table("app", "users") is not None
    assert catalog.get_table("app", "missing") is None
    assert catalog.get_view("app", "report") is not None
    assert catalog.get_view("app", "users") is None  # a table is not a view


def test_column_and_relation_lookups() -> None:
    users = _users_table()
    assert users.get_column("email") is not None
    assert users.get_column("Email") is None
    report = _report_view()
    assert report.materialized is True
    assert report.get_column("id") is not None


# ---------------------------------------------------------------------------
# Fingerprint: determinism and order-independence
# ---------------------------------------------------------------------------


def test_fingerprint_has_self_describing_prefix() -> None:
    fp = _baseline().fingerprint
    assert fp.startswith("sha256:")
    assert len(fp.split(":", 1)[1]) == 64


def test_fingerprint_is_schema_order_independent() -> None:
    app = Schema(name="app", tables=(_users_table(),))
    analytics = Schema(name="analytics", tables=(_events_table(),))
    assert compute_fingerprint((app, analytics)) == compute_fingerprint(
        (analytics, app)
    )


def test_fingerprint_is_relation_and_column_order_independent() -> None:
    active, report = _active_view(), _report_view()
    s1 = Schema(name="app", tables=(_users_table(),), views=(active, report))
    s2 = Schema(name="app", tables=(_users_table(),), views=(report, active))
    assert compute_fingerprint((s1,)) == compute_fingerprint((s2,))

    c_id = _col("id", "integer", 1, nullable=False)
    c_email = _col("email", "text", 2)
    t1 = Schema(name="s", tables=(Table(schema="s", name="t", columns=(c_id, c_email)),))
    t2 = Schema(name="s", tables=(Table(schema="s", name="t", columns=(c_email, c_id)),))
    assert compute_fingerprint((t1,)) == compute_fingerprint((t2,))


def test_from_schemas_fingerprint_matches_compute_fingerprint() -> None:
    app = Schema(name="app", tables=(_users_table(),))
    analytics = Schema(name="analytics", tables=(_events_table(),))
    # from_schemas sorts first; compute_fingerprint sorts internally too, so the
    # two agree regardless of the order passed in.
    assert SchemaCatalog.from_schemas((analytics, app)).fingerprint == (
        compute_fingerprint((app, analytics))
    )


# ---------------------------------------------------------------------------
# Fingerprint: sensitivity to structure
# ---------------------------------------------------------------------------


def _fp_with_users(users: Table) -> str:
    return compute_fingerprint((Schema(name="app", tables=(users,)),))


def test_fingerprint_changes_with_column_type() -> None:
    assert _fp_with_users(_users_table()) != _fp_with_users(
        _users_table(id_type="bigint")
    )


def test_fingerprint_changes_with_nullability() -> None:
    base = Table(schema="app", name="t", columns=(_col("c", "text", 1),))
    changed = Table(
        schema="app", name="t", columns=(_col("c", "text", 1, nullable=False),)
    )
    assert _fp_with_users(base) != _fp_with_users(changed)


def test_fingerprint_changes_with_ordinal() -> None:
    base = Table(schema="app", name="t", columns=(_col("c", "text", 1),))
    changed = Table(schema="app", name="t", columns=(_col("c", "text", 2),))
    assert _fp_with_users(base) != _fp_with_users(changed)


def test_fingerprint_changes_with_default() -> None:
    base = Table(schema="app", name="t", columns=(_col("c", "integer", 1),))
    changed = Table(
        schema="app", name="t", columns=(_col("c", "integer", 1, default="0"),)
    )
    assert _fp_with_users(base) != _fp_with_users(changed)


def test_fingerprint_changes_when_a_column_is_added() -> None:
    base = Table(schema="app", name="t", columns=(_col("a", "text", 1),))
    bigger = Table(
        schema="app",
        name="t",
        columns=(_col("a", "text", 1), _col("b", "text", 2)),
    )
    assert _fp_with_users(base) != _fp_with_users(bigger)


def test_fingerprint_changes_when_a_table_is_added() -> None:
    one = Schema(name="app", tables=(_users_table(),))
    two = Schema(
        name="app",
        tables=(_users_table(), Table(schema="app", name="extra", columns=())),
    )
    assert compute_fingerprint((one,)) != compute_fingerprint((two,))


def test_fingerprint_changes_with_primary_key() -> None:
    base = _users_table()
    changed = Table(
        schema="app",
        name="users",
        columns=base.columns,
        primary_key=PrimaryKey(name="users_pkey", columns=("id", "email")),
    )
    assert _fp_with_users(base) != _fp_with_users(changed)


def test_fingerprint_changes_with_unique_constraint() -> None:
    base = Table(schema="app", name="t", columns=(_col("c", "text", 1),))
    changed = Table(
        schema="app",
        name="t",
        columns=(_col("c", "text", 1),),
        unique_constraints=(UniqueConstraint(name="t_c_key", columns=("c",)),),
    )
    assert _fp_with_users(base) != _fp_with_users(changed)


def test_fingerprint_changes_with_foreign_key_target() -> None:
    def _with_ref(table: str) -> Table:
        return Table(
            schema="analytics",
            name="events",
            columns=(_col("user_id", "integer", 1),),
            foreign_keys=(
                ForeignKey(
                    name="fk",
                    columns=("user_id",),
                    referenced_schema="app",
                    referenced_table=table,
                    referenced_columns=("id",),
                ),
            ),
        )

    assert _fp_with_users(_with_ref("users")) != _fp_with_users(
        _with_ref("accounts")
    )


def test_fingerprint_changes_with_index_uniqueness() -> None:
    def _with_unique(unique: bool) -> Table:
        return Table(
            schema="app",
            name="t",
            columns=(_col("c", "text", 1),),
            indexes=(
                Index(name="t_idx", unique=unique, primary=False, columns=("c",)),
            ),
        )

    assert _fp_with_users(_with_unique(True)) != _fp_with_users(
        _with_unique(False)
    )


def test_fingerprint_changes_with_materialized_flag() -> None:
    plain = Schema(
        name="app",
        views=(View(schema="app", name="v", columns=(_col("c", "text", 1),)),),
    )
    materialized = Schema(
        name="app",
        views=(
            View(
                schema="app",
                name="v",
                columns=(_col("c", "text", 1),),
                materialized=True,
            ),
        ),
    )
    assert compute_fingerprint((plain,)) != compute_fingerprint((materialized,))


# ---------------------------------------------------------------------------
# Fingerprint: insensitivity to documentation
# ---------------------------------------------------------------------------


def test_fingerprint_ignores_comments() -> None:
    plain = Schema(
        name="app",
        tables=(_users_table(comment=None),),
        comment=None,
    )
    documented = Schema(
        name="app",
        tables=(
            Table(
                schema="app",
                name="users",
                columns=(
                    _col("id", "integer", 1, nullable=False, comment="the id"),
                    _col("email", "text", 2, comment="the email"),
                ),
                primary_key=PrimaryKey(name="users_pkey", columns=("id",)),
                unique_constraints=(
                    UniqueConstraint(name="users_email_key", columns=("email",)),
                ),
                indexes=(
                    Index(
                        name="users_pkey",
                        unique=True,
                        primary=True,
                        columns=("id",),
                    ),
                ),
                comment="all the people",
            ),
        ),
        comment="the application schema",
    )
    assert compute_fingerprint((plain,)) == compute_fingerprint((documented,))
