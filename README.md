# QueryShield

**Secure, Auditable Text-to-SQL Infrastructure for PostgreSQL.**

QueryShield is a security, governance, execution, caching, auditing, and
analytics layer that sits between an LLM that *generates* candidate SQL and a
PostgreSQL database that *executes* it. It exists to close the gap between "an
LLM can write SQL" and "it is safe to run LLM-written SQL against a production
database."

> ### ⚠️ Project status: Phase 0 — scaffolding only
>
> **QueryShield is not yet implemented.** This repository currently contains
> **documentation and project context only** — there is no runnable code, no
> package to install, and no tests. The documents below describe the *intended*
> architecture and clearly separate what is planned from what exists (nothing,
> functionally, yet). Track real progress in
> [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).

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

## Documentation

| Document | Purpose |
|----------|---------|
| [`CLAUDE.md`](CLAUDE.md) | Primary project context, principles, and development rules. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System architecture, data flow, trust/security boundaries, interfaces. |
| [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) | Authoritative checklist of what is done, planned, and deferred. |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Architecture Decision Records. |

## Technology (intended)

Python ≥ 3.11 · PostgreSQL · Mistral API (hosted, via API key) · Redis
(optional) · pydantic · pytest. See
[`docs/DECISIONS.md`](docs/DECISIONS.md) for firmness and open choices (e.g.,
the SQL parsing library is not yet finalized).

## License

**To be decided** by the repository owner — see ADR-0006 in
[`docs/DECISIONS.md`](docs/DECISIONS.md). No license is applied yet.
