# CLAUDE.md — QueryShield

> **Primary context file for Claude Code sessions.**
> Read this first, then read the three documents under `docs/` listed in
> [Context files](#context-files-read-these-every-phase) before writing or
> modifying any code.

---

## Current status (read carefully)

**Phase: 2 — Configuration system + PostgreSQL adapter foundation.**

Phase 1 (installable, testable skeleton) is complete and merged. Phase 2 adds
**two foundations and nothing else**: (1) a typed, validated **configuration
system** (`pydantic` v2 + a deterministic loader; precedence overrides > env >
YAML > defaults; fail-closed) and (2) a clean **database abstraction** with a
real **PostgreSQL adapter** (`psycopg` 3 + `psycopg_pool`, async: pooling, real
health check, read-only-by-default transactions, parameterised execution, clean
shutdown), plus the typed **error hierarchy** and library **logging** they need.

**Still *not* implemented** (planned): schema retrieval, the Mistral LLM, SQL
parsing/AST, the policy engine, rewriting, cost checks, the cache, audit, the
HTTP API, `RequestContext`, and any execution path for *arbitrary user- or
LLM-supplied* SQL. The adapter executes only QueryShield's own validated SQL and
never decides whether a query is authorized. Nothing in this file or in `docs/`
should be read as a claim that an unimplemented component already works.

> **Validation note:** the Phase 2 source and tests have been written but **not
> yet executed in this environment** — the sandbox's Bash command-safety
> classifier is temporarily unavailable, and the only local interpreter is
> Python 3.9 while the package requires ≥ 3.11. CI (quality matrix on 3.11–3.13
> + PostgreSQL integration) is the authoritative gate. See the Validation status
> in [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).

The authoritative, always-current status is
[`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md). When this
section and that file disagree, that file wins — and both should be fixed.

---

## 1. Project overview

**QueryShield — Secure, Auditable Text-to-SQL Infrastructure for PostgreSQL.**

QueryShield is a security, governance, execution, caching, auditing, and
analytics layer that sits **between an LLM that generates candidate SQL and a
PostgreSQL database**. A caller submits a natural-language request plus a
runtime security context; QueryShield retrieves the relevant schema, asks an
LLM (Mistral) for *candidate* SQL, then independently and deterministically
parses, validates, rewrites, cost-checks, caches, executes, and audits that
SQL.

The product's reason to exist is the gap between "an LLM can write SQL" and
"it is safe to run LLM-written SQL against a production database." QueryShield
fills that gap with deterministic, auditable controls that do **not** trust the
LLM.

High-level pipeline (see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the
full diagrams):

```
Caller → QueryShield Orchestrator → Schema Retrieval → LLM (Mistral) →
candidate SQL → SQL Parser/AST → Deterministic Policy Engine →
Query Rewriting/Validation → Cost/Complexity Checks → Secure Cache →
PostgreSQL → Result → Audit/Analytics
```

---

## 2. Architectural principles

1. **The LLM is never a trusted security component.** Mistral only *proposes*
   SQL. It is one untrusted input among others.
2. **Security decisions are deterministic.** Every security-relevant decision
   is made by code we control (parser, policy engine, rewriter, cost checks),
   never by the LLM and never by a pile of ad-hoc regexes.
3. **PostgreSQL is the final authority.** Application-layer checks are defense
   in depth. The database's own roles, privileges, and row-level security are
   the last and authoritative enforcement layer. QueryShield must map callers
   to least-privilege database principals so the DB can enforce access even if
   application logic has a bug.
4. **Fail closed. No silent fallbacks.** If a required security step cannot be
   performed (parse failure, policy engine error, cost check unavailable), the
   default behavior is to deny. Any relaxation must be an explicit, documented
   configuration choice — never an implicit `except: pass`.
5. **Security by default.** Where a safe default exists (read-only, SELECT-only,
   deny-by-default, principal-partitioned cache, mandatory audit), it is the
   default and must be explicitly overridden to loosen.
6. **Nothing deployment-specific is hard-coded.** See
   [Development rules](#5-development-rules).
7. **Extensible by interface.** Core logic depends on abstractions
   (`LLMProvider`, `DatabaseAdapter`, `SchemaRetriever`, `CacheBackend`,
   `PolicyRule`, `AuditStore`, `EventPublisher`), not on concrete vendors.
8. **Multi-everything.** Multiple tenants, users, roles, policies, and
   databases are first-class. A per-request `RequestContext` (the security
   principal) threads through the entire pipeline and is bound to a database
   principal at execution time. Nothing assumes a single tenant/user/DB.
9. **Auditable always.** Every request — allowed, denied, cached, or errored —
   produces a structured audit record.

---

## 3. Security principles (expanded)

- **Untrusted inputs:** the user's natural language, the LLM's candidate SQL,
  and *any* metadata the LLM emits (claimed table lists, claimed safety,
  claimed tenant, claimed permissions). None of these may drive a security
  decision.
- **Independent analysis:** the actual SQL string is parsed into an AST and
  analyzed. We never ask the LLM whether its own SQL is safe, and we never
  pattern-match our way to a safety verdict.
- **Principal isolation:** the `RequestContext` (tenant(s), user, roles,
  database selector, limits) is supplied at runtime by the trusted caller, not
  inferred from model output. Cache entries, audit records, and database
  sessions are all partitioned by this principal. A cache hit for one principal
  must never be returned to another.
- **Least privilege at the data layer:** execution uses a database role mapped
  to the principal, inside a read-only transaction by default, with a
  configurable `statement_timeout`.
- **Parser fidelity matters:** a difference between the grammar QueryShield
  parses and the grammar PostgreSQL executes is a security risk (parser
  differential). The parsing library choice is tracked as an open decision in
  [`docs/DECISIONS.md`](docs/DECISIONS.md).

---

## 4. Technology choices

These are the **intended** choices for the implementation phases. Items marked
"proposed" are reasonable defaults that may be revisited; items marked "open"
are explicitly undecided and tracked in [`docs/DECISIONS.md`](docs/DECISIONS.md).
The **tooling** choices (Python ≥ 3.11, `src/` layout, Hatchling, `pytest`,
`ruff`, `mypy`) were adopted in Phase 1. Phase 2 adopts the **config** and
**PostgreSQL driver** choices and pins their libraries in `pyproject.toml`
(`pydantic` v2, `PyYAML`, `psycopg` 3 + `psycopg_pool`). The remaining runtime
choices (SQL parser, LLM client, cache, HTTP API) are **not** installed yet —
each runtime library is introduced only in the phase that needs it.

| Concern              | Intended choice                                   | Firmness |
|----------------------|---------------------------------------------------|----------|
| Language             | Python ≥ 3.11                                     | adopted  |
| Packaging / layout   | `pyproject.toml` (PEP 621), `src/` layout, Hatchling | adopted |
| Config & validation  | `pydantic` v2 + explicit loader + `PyYAML` (not `pydantic-settings`) | adopted (ADR-0016/0017) |
| SQL parsing / AST    | `sqlglot` vs `pglast` (libpg_query)               | **open** |
| PostgreSQL driver    | `psycopg` 3 (+`psycopg_pool`), async              | adopted (ADR-0018/0019) |
| LLM client           | Mistral official SDK / HTTP; key from env         | proposed |
| Cache                | Redis (`redis-py`) + in-memory default            | proposed |
| HTTP API (optional)  | FastAPI, wrapping the library core                | proposed |
| Testing              | `pytest` (+`pytest-asyncio`, `pytest-cov`); real PostgreSQL via containers | adopted |
| Lint / type / format | `ruff`, `mypy` (strict), `ruff format`            | adopted  |
| Logging              | Structured logs (JSON-capable)                    | proposed |

**Hard constraint:** the LLM integration targets the **Mistral API via an API
key**. Do **not** implement local inference, Ollama, or local model serving
unless a later phase explicitly requests it.

---

## 5. Development rules

**Nothing deployment-specific may be hard-coded.** This includes, but is not
limited to: table names, column names, tenant IDs, user IDs, API keys, database
credentials, model names, security policies, row limits, JOIN limits, timeout
values, cache TTLs, and analytics settings. Such values come from
configuration, environment variables, the per-request `RequestContext`, or
pluggable interfaces. **Safe framework defaults are allowed only when they are
documented and overridable.**

- **Do not** build security from a fixed list of regexes, a fixed list of
  allowed/forbidden tables, or a fixed demo schema. The
  `customers/orders/products` triple may appear in *examples and tests only*;
  real schema is discovered dynamically from PostgreSQL.
- **Do not** assume one tenant, one user, one role, one policy, or one database.
- **Do** depend on interfaces, inject dependencies, and keep concrete vendors
  (Mistral, Redis, a specific driver) at the edges.
- **Do** use type hints everywhere, structured/typed errors, and validate
  configuration at startup.
- **Do** prefer async where it is justified (I/O: DB, cache, LLM, HTTP).
- **Avoid** speculative abstraction. Add an interface when a second
  implementation or a real seam exists — not "just in case."
- **If a requirement is genuinely unspecified**, choose a reasonable option,
  implement it, and record the decision in
  [`docs/DECISIONS.md`](docs/DECISIONS.md). Do not ask unnecessary questions,
  and do not invent requirements.

---

## 6. Testing rules

- Unit tests are mandatory for the deterministic core (parser usage, policy
  rules, rewriter, cost checks, cache key derivation). These are the security
  boundary and must be tested with adversarial inputs, not just happy paths.
- **Do not rely exclusively on mocks.** Integration tests must eventually run
  against a **real PostgreSQL instance** (ephemeral container preferred so CI
  and local runs are reproducible).
- The **LLM (Mistral) is mocked in unit tests** and exercised through
  contract-style tests; never make real paid LLM calls in the default test run.
- Every security control needs at least one test proving it **denies** a
  disallowed query, and that denial is **fail-closed** when the control itself
  errors.

---

## 7. Documentation rules

The four context files are engineering infrastructure, not decoration. Keep
them truthful: **never describe unimplemented behavior as if it exists.** Mark
planned vs. implemented explicitly.

- `CLAUDE.md` (this file) — project-level context and rules.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — architecture, data flow,
  trust/security boundaries, interfaces, extension points.
- [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) — the
  authoritative checklist of what is done, in progress, and deferred.
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — ADR-style log of significant
  decisions (decision, context, alternatives, reason, consequences). Do not log
  trivia.

---

## Context files (read these every phase)

**At the start of every implementation phase:**

1. Read `CLAUDE.md` (this file).
2. Read `docs/ARCHITECTURE.md`.
3. Read `docs/IMPLEMENTATION_STATUS.md`.
4. Read `docs/DECISIONS.md`.
5. Inspect the existing repository before modifying code.
6. Preserve the existing architecture unless there is a strong technical reason
   to change it.
7. If architecture must change, update the relevant context files **in the same
   phase**.

**At the end of every phase:**

1. Update `CLAUDE.md` if project-level context changed.
2. Update `docs/ARCHITECTURE.md` if architecture changed.
3. Update `docs/IMPLEMENTATION_STATUS.md`.
4. Update `docs/DECISIONS.md` for significant decisions.
5. Add/update tests.
6. Ensure documentation matches the actual implementation.
7. Report what was implemented, files created/modified, tests run and their
   results, and any known limitations or deferred work.

---

## Repository structure

See [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) for the
current (real) tree and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the
**planned** `src/queryshield/` package layout. As of Phase 2 the repository is:

```
QueryShield/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .gitignore
├── .env.example
├── .github/
│   └── workflows/
│       └── ci.yml
├── docs/
│   ├── ARCHITECTURE.md
│   ├── IMPLEMENTATION_STATUS.md
│   └── DECISIONS.md
├── src/
│   └── queryshield/
│       ├── __init__.py        # version + curated public API (config + errors)
│       ├── py.typed           # PEP 561 typing marker
│       ├── errors.py          # typed exception hierarchy
│       ├── config.py          # pydantic config models + load_config()
│       └── db/
│           ├── __init__.py    # curated db exports
│           ├── base.py        # DatabaseAdapter ABC + DatabaseSession Protocol
│           └── postgres.py    # PostgreSQLAdapter (psycopg 3 + psycopg_pool)
└── tests/
    ├── unit/
    │   ├── test_package.py
    │   ├── test_config.py
    │   ├── test_errors.py
    │   └── test_dsn.py
    └── integration/
        ├── README.md          # how to run the PostgreSQL integration tests
        ├── conftest.py        # skip-unless-DSN fixtures; disposable test table
        └── test_postgres_adapter.py
```
