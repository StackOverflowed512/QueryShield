# QueryShield

**Secure, Auditable Text-to-SQL Infrastructure for PostgreSQL.**

QueryShield is a security, governance, execution, caching, auditing, and
analytics layer that sits between an LLM that *generates* candidate SQL and a
PostgreSQL database that *executes* it. It exists to close the gap between "an
LLM can write SQL" and "it is safe to run LLM-written SQL against a production
database."

> ### ⚠️ Project status: Phase 1 — project foundation (no pipeline yet)
>
> This repository currently contains an **installable, type-checked, testable
> project skeleton** plus its **documentation** — **not** the QueryShield
> security/execution pipeline. The installed package exposes only its version.
> Everything in the architecture described below is **planned**; track what
> actually exists in
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

**Implemented (Phase 1 — foundation only):**

- Installable Python package exposing `queryshield.__version__` (and nothing else).
- `src/` layout, PEP 621 `pyproject.toml`, Hatchling build backend with a
  dynamic version sourced from the package.
- Test-suite foundation (`pytest`): real unit tests plus an integration-test
  placeholder, with a registered marker taxonomy.
- Lint + format (`ruff`) and strict typing (`mypy --strict`).
- GitHub Actions CI across Python 3.11 / 3.12 / 3.13.
- **Zero runtime dependencies.**

**Not implemented yet (planned):** schema retrieval, the Mistral LLM provider,
SQL parsing/AST, the deterministic policy engine, query rewriting/validation,
cost/complexity checks, the secure cache, PostgreSQL execution, audit/analytics,
and any HTTP API — plus the configuration model, error hierarchy, logging, and
the core interfaces / `RequestContext`. See
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
(`pytest`, `pytest-cov`, `ruff`, `mypy`). There are no runtime dependencies.

## Common tasks

```bash
pytest                   # run the test suite
ruff check .             # lint
ruff format --check .    # verify formatting (drop --check to apply)
mypy                     # strict type checking
```

Configuration for all of these lives in `pyproject.toml`.

## Project layout

```
src/queryshield/     # the package (currently: __version__ + py.typed only)
tests/unit/          # fast, isolated unit tests
tests/integration/   # placeholder; real PostgreSQL-backed tests arrive in Phase 2
docs/                # architecture, status, and decision records
.github/workflows/   # continuous integration
```

## Configuration

Copy `.env.example` to `.env` to see the environment variables that later phases
are expected to consume. **Nothing reads these yet** — the configuration layer
is not implemented. Never commit real secrets; `.env` is git-ignored.

## Documentation

| Document | Purpose |
|----------|---------|
| [`CLAUDE.md`](CLAUDE.md) | Primary project context, principles, and development rules. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System architecture, data flow, trust/security boundaries, interfaces. |
| [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) | Authoritative checklist of what is done, planned, and deferred. |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Architecture Decision Records. |

## Technology

Python ≥ 3.11 · Hatchling · pytest · ruff · mypy (adopted in Phase 1). ·
PostgreSQL · Mistral API (hosted, via API key) · Redis (optional) · pydantic
(intended for later phases). See [`docs/DECISIONS.md`](docs/DECISIONS.md) for
firmness and open choices — notably, the SQL parsing library is not yet
finalized (ADR-0003).

## License

**To be decided** by the repository owner — see ADR-0006 in
[`docs/DECISIONS.md`](docs/DECISIONS.md). No license is applied yet, so the
package is not published/distributable until one is chosen.
