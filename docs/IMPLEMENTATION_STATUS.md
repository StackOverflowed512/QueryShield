# QueryShield — Implementation Status

> **This file is the authoritative source of truth for what actually exists.**
> If any other document implies a feature works, this file overrides it.
> Last updated: **2026-10-08** (Phase 4 — SQL parsing & AST foundation).

Legend: ✅ done · 🚧 in progress · ⬜ not started · ⏸️ deferred (intentional)

---

## Current phase

**Phase 4 — SQL parsing & AST foundation.** 🚧 (built; CI validation pending)

Phases 1 (installable, testable project skeleton), 2 (configuration system +
PostgreSQL adapter foundation), and 3 (dynamic schema introspection) are complete
and merged to `main` — Phase 2 via PR #3, Phase 3 via PR #4 and follow-ups on
`main` (commits `ad26b02`, `ac77b7b`, `666bdb9`, `e8bbe06`, merged as PR #5). The
Phase 3 CI gate has run **green** on `main`. Phase 4 adds **one capability and
nothing else**: a deterministic **SQL parsing & AST foundation**.

A `SQLParser` abstraction with a concrete `PostgreSQLSQLParser` parses an
untrusted SQL string into a QueryShield-owned, immutable **`ParsedQuery`** using
**pglast** — Python bindings for **libpg_query**, which *is* PostgreSQL's own
parser — so the parser differential is removed by construction (ADR-0003).
Statement classification and multi-statement detection are read from the **AST**,
never from the string: no `str.startswith`, no `sql.split(";")`, no regex
(ADR-0030). The parser is **fail-closed and all-or-nothing**: it returns a
complete structure or raises a chained `SQLParseError`, never a partial result,
never a dialect retry (ADR-0031). Identifiers are preserved **verbatim** — never
case-folded (ADR-0032) — and the original SQL is retained unchanged. Everything
it returns is a QueryShield-owned type, not a pglast node (ADR-0029). The parser
is stateless: it takes no database session and never executes SQL.

**Deliberately *not* in Phase 4** (deferred to later phases): a query
*fingerprint* (deferred until the cache/cost layers need it), the Mistral LLM
provider, the deterministic policy engine, query rewriting/validation, cost
checks, caching, audit, and any execution path for *arbitrary user- or
LLM-supplied* SQL. The parser only *describes* structure: it makes **no** security
or authorization decision, performs no NL→SQL generation, and never executes
candidate SQL.

> **⚠️ Validation status (read this before trusting the checkmarks below):**
> Phases 1–3 are merged and green in CI. The Phase 4 source and tests have been
> **written**, but the mandated "actually run the tooling" validation —
> `pip install -e ".[dev]"`, `pytest -m "not integration"`, `ruff check .`,
> `ruff format --check .`, `mypy` — has **not yet been executed in this
> environment**: the only local interpreter is Python 3.9 while the package
> requires ≥ 3.11 (so `queryshield` cannot be imported locally) and pglast is not
> installed, and the sandbox's command-safety classifier is intermittently
> unavailable, so Bash invocations are refused. The **CI workflow**
> (`.github/workflows/ci.yml`) is the authoritative gate: it runs the full quality
> matrix on Python 3.11–3.13 and the integration tests against a `postgres:16`
> service container. Phase 4 therefore stays 🚧 until that gate has actually run
> green. This is recorded honestly rather than assumed.

---

## Phase checklist

### Phase 0 — Context & documentation infrastructure ✅
- [x] Inspect repository
- [x] `CLAUDE.md`
- [x] `docs/ARCHITECTURE.md`
- [x] `docs/IMPLEMENTATION_STATUS.md` (this file)
- [x] `docs/DECISIONS.md`
- [x] `README.md`
- [x] `.gitignore` (Python + secrets)
- [x] Git repository initialized and Phase 0 committed (branch `main`); Phase 1
      work continues on branch `phase_1`

### Phase 1 — Project foundation ✅

Installable, testable project foundation (merged to `main` via PR #1).
- [x] `pyproject.toml` (PEP 621) with Hatchling build backend + dynamic version
- [x] `src/queryshield/` package: `__init__.py` (single-source `__version__`)
      and `py.typed` (PEP 561)
- [x] Test harness: `tests/unit/test_package.py` (real tests), an
      `tests/integration/` placeholder doc, pytest config + marker taxonomy
- [x] Code quality: `ruff` (lint + format) and `mypy --strict` configured
- [x] CI (`.github/workflows/ci.yml`): lint, format-check, type-check, tests on
      Python 3.11 / 3.12 / 3.13
- [x] `.env.example` documenting configuration (placeholders only)
- [x] Toolchain validated via CI on the merged PR

> The original "Phase 1b — core library skeleton" has been folded in: its
> configuration model, error hierarchy, and logging landed in **Phase 2**
> (below). The remaining abstract interfaces (`LLMProvider`, `SchemaRetriever`,
> `CacheBackend`, `PolicyRule`, `AuditStore`, `EventPublisher`) and
> `RequestContext` are intentionally **not** created up-front — each is
> introduced in the phase that gives it a first real consumer, per the
> "avoid speculative abstraction" rule in `CLAUDE.md`.

### Phase 2 — Configuration system + PostgreSQL adapter foundation ✅

**2a. Configuration system**
- [x] `pydantic` v2 models: `DatabaseConfig` (`extra="forbid"`) and
      `QueryShieldConfig` (`extra="ignore"`)
- [x] Deterministic `load_config()` loader — precedence
      overrides > env (`QUERYSHIELD_*`, nested via `__`) > YAML file > defaults
- [x] Optional YAML layer (`QUERYSHIELD_CONFIG_FILE`) with fail-closed `${VAR}`
      interpolation
- [x] Fail-closed validation: invalid/security-relevant values raise a
      structured `ConfigError`; nothing silently dropped
- [x] Secrets held as `SecretStr`; never logged or echoed in errors
- [x] Unit tests: precedence, env/YAML parsing, validation failures, secret
      non-leakage (`tests/unit/test_config.py`)

**2b. Error hierarchy & logging**
- [x] `QueryShieldError` → `ConfigError`, `DatabaseError` →
      `DatabaseConnectionError` / `DatabaseExecutionError` (`errors.py`)
- [x] Config errors are distinguishable from database/SQL/policy/LLM errors
- [x] Library `NullHandler` on the `queryshield` logger; `log_level` configurable
- [x] Unit tests for the hierarchy shape (`tests/unit/test_errors.py`)

**2c. Database abstraction**
- [x] Abstract `DatabaseAdapter` + `DatabaseSession` Protocol + `HealthCheckResult`
      (`db/base.py`), with a documented trust boundary
- [x] No public "run any string" API; read-only-by-default transactions;
      values always bound as parameters

**2d. PostgreSQL adapter**
- [x] `PostgreSQLAdapter` on psycopg 3 + `psycopg_pool` (async-only)
- [x] Configurable connection pool; explicit `open()` / `close()` lifecycle
- [x] Real `health_check()` (acquires a connection, runs `SELECT 1`; never
      reports healthy when unreachable)
- [x] `statement_timeout` + `sslmode` applied at connect time
- [x] Driver errors mapped to QueryShield errors with chaining; DSN sanitised
      and secrets scrubbed from messages (`db/postgres.py`)
- [x] DSN helpers unit-tested (`tests/unit/test_dsn.py`)

**2e. Integration tests (real PostgreSQL)**
- [x] Tests covering connection+health, pool acquire/release, parameterised ops,
      commit, rollback, read-only write rejection, shutdown, invalid credentials
      (`tests/integration/test_postgres_adapter.py`)
- [x] Skip (not fail) when `QUERYSHIELD_TEST_DATABASE_URL` is unset; unique
      dynamically-created tables; no fixed demo schema
- [x] CI integration job runs them against a `postgres:16` service container
- [x] **CI gate run green** and merged to `main` via PR #3

### Phase 3 — Dynamic schema introspection ✅

> Merged to `main` (PR #4, plus the follow-up fixes folded in via PR #5); the
> Phase 3 CI gate has run **green** (quality matrix on 3.11–3.13 and the
> PostgreSQL integration job). The Phase 3 "validation pending" caveat is now
> resolved.

**3a. Domain model**
- [x] Frozen, slotted dataclasses: `Column`, `PrimaryKey`, `UniqueConstraint`,
      `ForeignKey`, `Index`, `Table`, `View` (modelled separately from `Table`),
      `Schema`, and the top-level `SchemaCatalog` (`schema/models.py`, ADR-0024)
- [x] Identifiers preserved verbatim — exact case / spaces / Unicode / reserved
      words; exact-match lookup helpers; no case-folding (ADR-0026)
- [x] PostgreSQL types kept as `pg_catalog.format_type` renders them (no coercion)
- [x] Deterministic structural `fingerprint` (`sha256:…` over canonical JSON;
      excludes comments / time / DB identity; order-independent) (ADR-0027)

**3b. `SchemaRetriever` abstraction**
- [x] Abstract `SchemaRetriever` with `async retrieve() -> SchemaCatalog`
      (`schema/base.py`); concrete adapters not re-exported at the package root
- [x] `SchemaError` → `SchemaRetrievalError` / `SchemaMetadataError`, a hierarchy
      **separate from** `DatabaseError` (`errors.py`)

**3c. Generic schema filtering**
- [x] Config-driven `SchemaFilter` (`schema/filter.py`): skips system schemas
      (`pg_*`, `information_schema`) by default; optional exact-match `include`
      allow-list, then `exclude` deny-list; case-sensitive; order-preserving;
      an explicit empty allow-list selects nothing. No hard-coded schema names.

**3d. PostgreSQL introspection**
- [x] `PostgreSQLSchemaRetriever` (`schema/postgres.py`) reuses the Phase 2
      `DatabaseAdapter` — no second connection path (ADR-0023)
- [x] One **read-only** transaction; six bounded, parameterised `pg_catalog`
      queries (schemas, relations, columns, keys, foreign keys, indexes); no N+1
- [x] `has_table_privilege(oid, 'SELECT')`-filtered; selected schema names passed
      as a single **bound array** (`= ANY(%s)`), never interpolated (ADR-0025)
- [x] Pure `_assemble_catalog` runs **outside** the transaction so an inconsistent
      catalog is a `SchemaMetadataError`, distinct from a `SchemaRetrievalError`
- [x] Fail-closed: a reachable-but-failing query → `SchemaRetrievalError`
      (chained); a connection failure propagates as `DatabaseConnectionError`
      unchanged; never a fabricated empty catalog on failure
- [x] Snapshot semantics: `retrieve()` always re-introspects; no implicit cache,
      no staleness concept (ADR-0028)

**3e. Tests**
- [x] Unit: domain models + fingerprint (`tests/unit/test_schema_models.py`),
      `SchemaFilter` (`tests/unit/test_schema_filter.py`), and the retriever's
      logic / error contract / query shape via a typed fake adapter
      (`tests/unit/test_schema_retriever.py`)
- [x] Integration against real PostgreSQL with uuid-named temp objects
      (`tests/integration/test_schema_retriever.py`); skips unless
      `QUERYSHIELD_TEST_DATABASE_URL` is set; CI runs them on `postgres:16`
- [x] **CI gate run green** and merged to `main` (PR #4 + follow-ups via PR #5)

### Phase 4 — SQL parsing & AST foundation 🚧 (built; CI validation pending)

**4a. Parser choice & dependency**
- [x] **pglast** (Python bindings for libpg_query — PostgreSQL's *own* parser)
      adopted, finalising ADR-0003; pinned `pglast>=6,<8` in `pyproject.toml`
      (the upper bound stops a future major from silently swapping the bundled
      grammar). Introduced lazily, so importing QueryShield does not load the
      compiled extension until a parse is requested.

**4b. Abstraction & owned model**
- [x] `SQLParser` ABC (`sql/base.py`) with
      `async parse(sql) -> ParsedQuery`; documents independent structural
      analysis, fail-closed semantics, verbatim identifiers, and no execution
- [x] QueryShield-owned model (`sql/models.py`): frozen, slotted `ParsedQuery`
      plus `TableReference`, `ColumnReference`, `FunctionCall`,
      `CommonTableExpression`, `SetOperation`, and the `StatementType` /
      `JoinType` / `SetOperationType` enums — never a pglast type (ADR-0029)
- [x] No safety verdict anywhere in the model: no `is_safe` / `allowed` field or
      property; a well-formed `DROP` is structure, not a claim (ADR-0029)

**4c. PostgreSQL parser (pglast)**
- [x] `PostgreSQLSQLParser` (`sql/postgres.py`) — stateless, no DB session, no
      execution; reflective AST walk over node `__slots__`, dispatching on the
      node class name (depends only on pglast's stable surface)
- [x] Statement classification **from the AST** (`StatementType`), including the
      fail-safe `UNKNOWN` bucket — never `str.startswith`, never regex, never a
      text scan (ADR-0030)
- [x] Multi-statement detection from the number of parsed statements — never
      `sql.split(";")`; a batch is represented, never truncated (ADR-0030)
- [x] References extracted: tables (schema / name / alias), columns (incl. `*`),
      functions (schema-qualified), joins, CTEs, subqueries, parameters vs.
      literals, and the SELECT feature flags (DISTINCT, GROUP BY, HAVING,
      ORDER BY, LIMIT/OFFSET, window functions, locking clause)
- [x] CTE reference separated from physical relations: a bare `FROM sales` whose
      name matches a `WITH` CTE is not reported as a table
- [x] Identifiers preserved **verbatim** — original case / quoting / Unicode; no
      case-folding (ADR-0026 / ADR-0032); original SQL retained unchanged
- [x] Fail-closed: any unparseable input raises a `SQLParseError` with the
      vendor parser's exception chained as `__cause__`; never a partial result,
      never a dialect retry (ADR-0031); non-string input and empty /
      comment-only input also raise
- [x] `SQLParseError(QueryShieldError)` added to `errors.py`, exported at the
      package root; parser internals (`PostgreSQLSQLParser`, `ParsedQuery`) are
      **not** top-level exports — they live under `queryshield.sql`

**4d. Tests**
- [x] Model unit tests (`tests/unit/test_sql_models.py`): immutability, verbatim
      identifiers, deterministic dedup views, and the absence of any safety
      verdict
- [x] Parser unit tests (`tests/unit/test_sql_parser.py`): AST-driven
      classification per statement kind, the `UNKNOWN` bucket, a leading comment
      that must not fool classification, table/alias/column/function extraction,
      CTE separation, join and UNION/UNION-ALL distinction, subqueries,
      parameters vs. literals, SELECT feature flags, multi-statement detection,
      a semicolon inside a string literal, adversarial fail-closed inputs,
      `__cause__` chaining, determinism, and no-verdict
- [ ] **CI gate actually run green** — pending; see the Validation status note.

### Phase 5 — Deterministic policy engine ⬜
- [ ] `PolicyEngine` composing `PolicyRule`s from config
- [ ] Core rules: statement-type allowlist, table/column access vs. schema+grants,
      forbidden constructs, JOIN/subquery-depth limits
- [ ] Deny-by-default + structured `PolicyDecision`
- [ ] Fail-closed tests (rule error ⇒ deny)

### Phase 6 — Query rewriting & validation ⬜
- [ ] Deterministic rewrites (enforced `LIMIT`, tenant predicates, qualification)
- [ ] Re-parse/validate invariants post-rewrite
- [ ] Reject when safety cannot be proven

### Phase 7 — Cost & complexity checks ⬜
- [ ] Static complexity metrics
- [ ] `EXPLAIN`-based planner cost (never `EXPLAIN ANALYZE`)
- [ ] Configurable thresholds + fail-closed policy when unavailable

### Phase 8 — LLM provider (Mistral) ⬜
- [ ] `MistralProvider` behind `LLMProvider` (API key from env)
- [ ] Prompt construction from access-filtered schema
- [ ] Timeouts/retries; **mocked** unit tests + contract tests (no paid calls in CI)

### Phase 9 — Secure cache ⬜
- [ ] `CacheBackend` with principal-partitioned keys + schema version
- [ ] `InMemoryCache` (default) and `RedisCache`
- [ ] TTL config; cross-principal isolation tests

### Phase 10 — Execution ⬜
- [ ] Principal→DB-role mapping, read-only transactions, `statement_timeout`
- [ ] Result shaping & typed `PipelineResult`
- [ ] Integration tests against real PostgreSQL (incl. RLS enforcement)

### Phase 11 — Audit & analytics ⬜
- [ ] `AuditStore` (append-only, structured records incl. denials/errors)
- [ ] `EventPublisher` + analytics aggregation
- [ ] Tests proving audit occurs on allow/deny/error paths

### Phase 12 — API surface & end-to-end hardening ⬜
- [ ] FastAPI adapter over the library core
- [ ] Full end-to-end integration (real PG + mocked LLM)
- [ ] Security hardening pass, docs polish, example app/notebook

> Phase ordering is a plan, not a contract. Phases 4–7 (the deterministic core)
> can proceed independently of Phase 8 (LLM) because they operate on SQL strings
> directly. Re-sequencing is allowed if dependency-justified and recorded.

---

## Implemented modules

- `queryshield` (`src/queryshield/__init__.py`) — package root. `__version__` is
  now **`0.4.0`**. Curated public API: `__version__`, `DatabaseConfig`,
  `QueryShieldConfig`, `load_config`, and the nine error types. Installs a
  `NullHandler` on the `queryshield` logger. Concrete adapters
  (`PostgreSQLAdapter`, `PostgreSQLSchemaRetriever`) and the parser
  (`PostgreSQLSQLParser`) are **not** re-exported here.
- `queryshield.errors` — typed exception hierarchy: `QueryShieldError` (root) →
  `ConfigError`, `DatabaseError` → `DatabaseConnectionError` /
  `DatabaseExecutionError`, `SchemaError` → `SchemaRetrievalError` /
  `SchemaMetadataError` (the schema hierarchy is **not** a `DatabaseError`
  subclass), and `SQLParseError` (its own branch, not a `DatabaseError` /
  `SchemaError`). No secrets or raw driver text in messages.
- `queryshield.config` — `pydantic` v2 `DatabaseConfig` / `QueryShieldConfig`
  models and the deterministic `load_config()` loader (layer precedence, YAML
  `${VAR}` interpolation, fail-closed validation, `SecretStr` secrets).
- `queryshield.db` (`base.py`, `postgres.py`) — vendor-neutral
  `DatabaseAdapter` ABC + `DatabaseSession` Protocol + `HealthCheckResult`, and
  the `PostgreSQLAdapter` implementation (psycopg 3 + `psycopg_pool`, async,
  pooled, read-only-by-default, real health check, parameterised execution, DSN
  sanitisation + secret scrubbing). Also exports `sanitize_dsn`.
- `queryshield.schema` (`base.py`, `models.py`, `filter.py`, `postgres.py`) —
  the `SchemaRetriever` ABC (`async retrieve() -> SchemaCatalog`), the immutable
  frozen domain models + structural `fingerprint`, the generic config-driven
  `SchemaFilter`, and the `PostgreSQLSchemaRetriever` (reuses the Phase 2
  adapter; one read-only transaction of six bounded, parameterised `pg_catalog`
  queries; `has_table_privilege`-filtered; fail-closed). Re-exports the models,
  `SchemaRetriever`, `SchemaFilter`, and `PostgreSQLSchemaRetriever`.
- `queryshield.sql` (`base.py`, `models.py`, `postgres.py`) — the `SQLParser`
  ABC (`async parse() -> ParsedQuery`), the QueryShield-owned frozen model
  (`ParsedQuery` + supporting types + `StatementType` / `JoinType` /
  `SetOperationType`), and the `PostgreSQLSQLParser` built on pglast
  (libpg_query). AST-driven classification and multi-statement detection;
  fail-closed `SQLParseError`; verbatim identifiers; no execution, no DB session,
  no security decision.

No other modules exist. The LLM provider, policy engine, rewriter, cost checks,
cache, audit, and the orchestrator/pipeline described in
[`ARCHITECTURE.md`](ARCHITECTURE.md) are still unimplemented.

## Tests implemented

Unit tests (`tests/unit/`, run with `pytest -m "not integration"`):
- `test_package.py` — package imports; `__version__` well-formed; in-code
  version matches installed distribution metadata; public API is curated and
  small (and `PostgreSQLAdapter` is **not** top-level).
- `test_config.py` — layer precedence (overrides > env > YAML > defaults),
  env/YAML parsing, fail-closed validation errors, and secret non-leakage
  (`SecretStr` not echoed in reprs/errors).
- `test_errors.py` — exception hierarchy shape and `isinstance` relationships
  (including the `SchemaError` branch and its separation from `DatabaseError`).
- `test_dsn.py` — `sanitize_dsn` (password dropped, host/port/db/user kept) and
  `scrub_secrets`.
- `test_schema_models.py` — the frozen domain models and `compute_fingerprint`:
  immutability, exact-match lookups, verbatim identifiers, and fingerprint
  determinism / order-independence / structural sensitivity.
- `test_schema_filter.py` — `SchemaFilter` selection: default system-schema skip,
  exact-match `include` allow-list then `exclude` deny-list, case-sensitivity,
  order preservation, and empty allow-list selecting nothing.
- `test_schema_retriever.py` — the retriever's logic without a database, via a
  fully typed fake adapter: the pure assembler builds the right catalog and
  **fails closed** (`SchemaMetadataError`) on an inconsistent one; introspection
  runs in one read-only transaction; selected names are passed as a bound
  parameter; a failing query becomes a chained `SchemaRetrievalError`; a
  connection failure propagates unchanged; an empty selection short-circuits.
- `test_sql_models.py` — the parsed-SQL model in isolation (no pglast, no
  database): frozen dataclasses, verbatim identifiers, deterministic dedup
  views (`table_names` / `cte_names` / `function_names`), `is_multi_statement`,
  enum coverage, and the deliberate **absence** of any safety verdict.
- `test_sql_parser.py` — the real pglast parser (in-process, deterministic, no
  database): AST-driven classification for each statement kind and the
  `UNKNOWN` bucket, a leading comment that must not fool classification,
  schema-qualified tables / aliases, verbatim identifiers, column and `*`
  extraction, qualified functions, CTE-vs-physical separation, join types,
  `UNION` vs `UNION ALL`, subquery flag, parameters vs. literals, SELECT
  feature flags, locking clause, multi-statement detection, a semicolon inside a
  string literal, adversarial fail-closed inputs (incl. empty / comment-only),
  `__cause__` chaining, non-string rejection, determinism, and no-verdict.

Integration tests (`tests/integration/`, run with `pytest -m integration`):
- `test_postgres_adapter.py` — nine tests against a real PostgreSQL: health
  check, pool acquire/release under concurrency, parameterised fetch,
  proof-of-non-interpolation, commit across connections, rollback on error,
  write blocked in the default read-only transaction, clean shutdown, and
  invalid-credential reporting without leaking the password. Skips when
  `QUERYSHIELD_TEST_DATABASE_URL` is unset.
- `test_schema_retriever.py` — the real catalog SQL against a live PostgreSQL,
  using uuid-named temporary schemas/objects: tables, views, and materialized
  views; columns with verbatim identifiers and types; single + composite primary
  and unique keys; cross-schema foreign keys; normal and unique indexes; the
  default filter excluding system schemas; fingerprint determinism and
  sensitivity; a connection failure raising (never an empty catalog). Skips when
  `QUERYSHIELD_TEST_DATABASE_URL` is unset.

> These tests have been **written** but **not yet executed in this environment**
> (see the Validation status note: Bash classifier unavailable + local Python is
> 3.9 while the package needs ≥ 3.11). CI is the authoritative run. Do not read
> their presence as a passing run until CI has actually run them.

---

## Known limitations (as of Phase 4)

- The repository implements **only** the configuration system, the database
  foundation, dynamic schema introspection, and the SQL parsing foundation.
  There is **no** LLM integration, policy engine, rewriting, cost checks, cache,
  execution path for arbitrary user/LLM SQL, audit, or API.
- Schema introspection is **not** yet scoped by a per-request `RequestContext`
  principal (deferred, ADR-0028). The retriever filters relations by the
  `has_table_privilege` of the **single configured DSN role**, and schema
  selection comes from a directly-constructed `SchemaFilter` — there is no
  `SchemaConfig` section wiring it to configuration yet.
- The `SchemaCatalog` is a point-in-time snapshot with **no** caching: every
  `retrieve()` re-introspects. Schema versioning / drift detection beyond the
  structural fingerprint is left to the layers that will consume it.
- The `PostgreSQLAdapter` connects as the single configured DSN role.
  Principal→least-privilege-role mapping and RLS-scoped execution are **not**
  implemented (Phase 10); the adapter is the executor primitive those phases
  will build on.
- The SQL parser **describes** structure only. It does **not** resolve references
  against a catalog, and it makes no security decision. Deliberate, accepted
  limitations in this phase:
  - DDL target names (e.g. the table in `DROP TABLE x` / `ALTER TABLE x`) are not
    lowered to `TableReference` — the AST names them through a different node
    shape than a `FROM` reference, and modelling DDL targets is a later concern.
  - An implicit comma join is not represented as a `JoinType`, and a `CROSS JOIN`
    is reported as `INNER` — PostgreSQL represents both with the same join node.
    The referenced tables themselves are still captured (both sides of `FROM a, b`
    appear in `tables`); only the join-*type* distinction is not modelled, and it
    remains recoverable from the original SQL, which the parser retains.
  - No query **fingerprint** yet (deliberately deferred, ADR-0032).
- The pglast AST walk reads node `__slots__` reflectively rather than using a
  typed `Visitor`; this is a deliberate robustness choice (it depends only on
  pglast's stable surface) and is covered by the parser unit tests.
- Phase 4 validation (running the toolchain) has **not** been executed in this
  environment: the local interpreter is Python 3.9 while the package requires
  ≥ 3.11 (so `queryshield` cannot be imported), pglast is not installed locally,
  and the Bash command-safety classifier is intermittently unavailable. CI is the
  authoritative gate and has not yet been confirmed green for the Phase 4 branch.
  (Phases 2 and 3 are green.)
- The async execution model is the only one shipped; there is intentionally no
  sync adapter (ADR-0019).

## Technical debt

- None accrued. All code is covered by unit tests (deterministic parts) or
  integration tests (the PostgreSQL adapter), pending the CI run that executes
  them.

## Intentionally deferred (⏸️)

- **Remaining abstract interfaces** (`LLMProvider`, `CacheBackend`, `PolicyRule`,
  `AuditStore`, `EventPublisher`) and `RequestContext` — not created up-front;
  each is introduced in the phase that gives it a first real consumer (avoid
  speculative abstraction). (`SchemaRetriever` was introduced in Phase 3, and
  `SQLParser` in Phase 4.)
- **Binding schema introspection to a principal** — a per-request
  `RequestContext` and a dedicated `SchemaConfig` section are deferred; Phase 3
  ships the retriever with a directly-constructed `SchemaFilter` and
  `has_table_privilege`-based filtering only (ADR-0028).
- **A query fingerprint** — a deterministic fingerprint of a *parsed query* (as
  opposed to the schema fingerprint of ADR-0027) is deliberately deferred until
  the cache/cost layers need it (ADR-0032).
- **All remaining QueryShield security/execution functionality** — Phases 5–12.
- **Mistral client and Redis** runtime dependencies — each is introduced only in
  the phase that actually needs it (ADR-0012). (psycopg 3 and pydantic/PyYAML
  were added in Phase 2; pglast was added in Phase 4 because the parsing
  foundation consumes it.)
- **CLI / `__main__` entry point** — deferred until there is behavior to expose
  (ADR-0015).
- **LICENSE / open-source license selection** — deferred to the repository
  owner; `pyproject.toml` omits the `license` field accordingly (ADR-0006).
- **Local/offline LLM inference (Ollama etc.)** — out of scope unless a future
  phase explicitly requests it (ADR-0009).
