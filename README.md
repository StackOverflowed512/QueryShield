# QueryShield

**Secure, Auditable Text-to-SQL Infrastructure for PostgreSQL.**

QueryShield is a security, governance, execution, caching, auditing, and
analytics layer that sits between an LLM that *generates* candidate SQL and a
PostgreSQL database that *executes* it. It exists to close the gap between "an
LLM can write SQL" and "it is safe to run LLM-written SQL against a production
database."

> ### ⚠️ Project status: Phase 3 — dynamic PostgreSQL schema introspection
>
> This repository implements, so far: a typed, validated **configuration
> system**; a **PostgreSQL database adapter** (pooled, with a real health check,
> read-only-by-default transactions, and parameterised execution); and — new in
> Phase 3 — **dynamic schema introspection** that turns a live database into an
> immutable, fingerprinted `SchemaCatalog` snapshot. The rest of the
> architecture below — the LLM, SQL parsing, the policy engine, rewriting, cost
> checks, caching, execution of arbitrary user/LLM SQL, audit, and the HTTP API
> — is still **planned**, and the schema layer itself makes **no** security
> decision and generates/executes **no** SQL. Track what actually exists in
> [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md), which is the
> authoritative source of truth.

## Core idea

The LLM is **never** a trusted security component. Mistral only proposes
candidate SQL; QueryShield independently and **deterministically** parses,
validates, rewrites, cost-checks, caches, executes, and audits that SQL, and
**PostgreSQL remains the authoritative, database-level enforcement layer** via
least-privilege roles and row-level security.

```
Caller → QueryShield → Schema Retrieval → Mistral (candidate SQL) →
Parser/AST → Deterministic Policy Engine → Rewrite/Validate →
Cost/Complexity → Secure Cache → PostgreSQL → Result → Audit/Analytics
```

## Principles

- **LLM is untrusted** — security decisions are deterministic, never model-driven.
- **Fail closed** — if a security check can't run, deny by default; no silent fallbacks.
- **Security by default** — read-only, SELECT-only, deny-by-default, audited.
- **Nothing deployment-specific is hard-coded** — tables, tenants, limits,
  timeouts, credentials, model names, and policies all come from configuration
  or per-request context.
- **Multi-everything** — many tenants, users, roles, policies, and databases.
- **Extensible by interface** — `LLMProvider`, `DatabaseAdapter`,
  `SchemaRetriever`, `CacheBackend`, `PolicyRule`, `AuditStore`,
  `EventPublisher`.

## Status at a glance

**Implemented so far:**

- *Phase 1 — foundation:* installable `src/`-layout package (PEP 621
  `pyproject.toml`, Hatchling dynamic version), `pytest` harness with a marker
  taxonomy, `ruff` + `mypy --strict`, and GitHub Actions CI across Python
  3.11 / 3.12 / 3.13.
- *Phase 2 — configuration:* typed, validated config (`pydantic` v2) with a
  deterministic loader — precedence **overrides > env (`QUERYSHIELD_*`) > YAML
  file > defaults** — fail-closed validation, and `SecretStr` secrets that never
  leak into logs or errors.
- *Phase 2 — database:* a vendor-neutral `DatabaseAdapter` abstraction and a
  `PostgreSQLAdapter` (psycopg 3 + `psycopg_pool`, async): connection pooling, a
  real health check, read-only-by-default transactions, parameterised execution,
  clean shutdown, and driver errors mapped to a typed hierarchy without leaking
  credentials. Integration tests run against a real PostgreSQL (a `postgres:16`
  service container in CI).
- *Phase 3 — schema introspection:* a `SchemaRetriever` abstraction and a
  `PostgreSQLSchemaRetriever` that reuses the Phase 2 adapter to introspect a
  live database through `pg_catalog` — one read-only transaction, six bounded
  parameterised queries, `has_table_privilege`-filtered — producing an
  **immutable `SchemaCatalog`** of frozen, strongly typed models (schemas,
  tables, views, columns, primary/foreign/unique keys, indexes) with a
  deterministic structural **fingerprint**. Identifiers are preserved verbatim;
  schema selection is a generic, config-driven `SchemaFilter` (no hard-coded
  schema names). Covered by unit tests and real-PostgreSQL integration tests.

**Not implemented yet (planned):** the Mistral LLM provider, SQL parsing/AST,
the deterministic policy engine, query rewriting/validation, cost/complexity
checks, the secure cache, execution of arbitrary user/LLM SQL, audit/analytics,
the HTTP API, and `RequestContext`. See
[`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).

## Requirements

- Python ≥ 3.11

## Development setup

```bash
# from the repository root
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

This installs QueryShield in editable mode together with the development tools
(`pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `mypy`). Runtime dependencies
(`pydantic`, `PyYAML`, `psycopg`) are pulled in automatically.

## Common tasks

```bash
pytest -m "not integration"   # fast unit tests (no database needed)
ruff check .                  # lint
ruff format --check .         # verify formatting (drop --check to apply)
mypy                          # strict type checking
```

Configuration for all of these lives in `pyproject.toml`.

### Integration tests (real PostgreSQL)

The database adapter is tested against a **real, disposable** PostgreSQL. These
tests **skip** unless `QUERYSHIELD_TEST_DATABASE_URL` points at one, so they
never touch a developer's personal database.

```bash
# start a throwaway PostgreSQL (removed on stop)
docker run --rm -d --name queryshield-pg \
  -e POSTGRES_USER=queryshield_test \
  -e POSTGRES_PASSWORD=queryshield_test \
  -e POSTGRES_DB=queryshield_test \
  -p 5432:5432 postgres:16

export QUERYSHIELD_TEST_DATABASE_URL=postgresql://queryshield_test:queryshield_test@localhost:5432/queryshield_test
pytest -m integration

docker stop queryshield-pg    # tear it down
```

CI runs the same tests automatically against a `postgres:16` service container.

## Project layout

```
src/queryshield/       # the package
├── __init__.py        #   version + curated public API (config + errors)
├── errors.py          #   typed exception hierarchy
├── config.py          #   pydantic config models + load_config()
├── db/                #   DatabaseAdapter abstraction + PostgreSQLAdapter
└── schema/            #   SchemaRetriever + PostgreSQLSchemaRetriever + models
tests/unit/            # fast, isolated unit tests (no database)
tests/integration/     # real PostgreSQL-backed adapter + schema tests
docs/                  # architecture, status, and decision records
.github/workflows/     # continuous integration
```

## Configuration

QueryShield is configured through `pydantic`-validated settings loaded by
`queryshield.load_config()`. Values are resolved with a deterministic precedence
— **explicit overrides > environment variables > YAML file > built-in safe
defaults** — and validation is **fail-closed**: an invalid or security-relevant
bad value raises a structured `ConfigError` rather than being silently ignored.

Environment variables use the `QUERYSHIELD_` prefix with `__` for nesting (e.g.
`QUERYSHIELD_DATABASE__URL`). The database URL is held as a secret and never
appears in logs or error messages. Copy `.env.example` to `.env` to see every
supported variable with safe-default annotations. Never commit real secrets;
`.env` is git-ignored.

## Documentation

| Document | Purpose |
|----------|---------|
| [`CLAUDE.md`](CLAUDE.md) | Primary project context, principles, and development rules. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System architecture, data flow, trust/security boundaries, interfaces. |
| [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) | Authoritative checklist of what is done, planned, and deferred. |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Architecture Decision Records. |

## Technology

Python ≥ 3.11 · Hatchling · pytest (+pytest-asyncio) · ruff · mypy · **pydantic
v2** · **PyYAML** · **psycopg 3** (+`psycopg_pool`) — all adopted · PostgreSQL ·
Mistral API (hosted, via API key) · Redis (optional) — introduced in later
phases. See [`docs/DECISIONS.md`](docs/DECISIONS.md) for firmness and open
choices — notably, the SQL parsing library is not yet finalized (ADR-0003).

## License

**To be decided** by the repository owner — see ADR-0006 in
[`docs/DECISIONS.md`](docs/DECISIONS.md). No license is applied yet, so the
package is not published/distributable until one is chosen.
