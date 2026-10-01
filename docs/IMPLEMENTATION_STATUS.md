# QueryShield — Implementation Status

> **This file is the authoritative source of truth for what actually exists.**
> If any other document implies a feature works, this file overrides it.
> Last updated: **2026-10-01** (Phase 0).

Legend: ✅ done · 🚧 in progress · ⬜ not started · ⏸️ deferred (intentional)

---

## Current phase

**Phase 0 — Project context & documentation infrastructure.** 🚧 → ✅ on
completion of this phase.

Goal: establish the permanent context files and project scaffolding. **No
QueryShield functionality is implemented in this phase, by design.**

---

## Phase checklist

### Phase 0 — Context & documentation infrastructure 🚧
- [x] Inspect repository (confirmed empty, not a git repo)
- [x] `CLAUDE.md`
- [x] `docs/ARCHITECTURE.md`
- [x] `docs/IMPLEMENTATION_STATUS.md` (this file)
- [x] `docs/DECISIONS.md`
- [x] `README.md`
- [x] `.gitignore` (Python + secrets)
- [ ] Git repository initialized (left **uncommitted** — awaiting user)

### Phase 1 — Skeleton, configuration, errors, interfaces ⬜
- [ ] `pyproject.toml` (PEP 621), `src/queryshield/` layout, tooling config
- [ ] Validated configuration model + precedence (defaults→file→env→context)
- [ ] Typed error hierarchy (`QueryShieldError` + subclasses)
- [ ] Structured logging setup
- [ ] Abstract interfaces: `LLMProvider`, `DatabaseAdapter`, `SchemaRetriever`,
      `CacheBackend`, `PolicyRule`/`PolicyEngine`, `AuditStore`, `EventPublisher`
- [ ] `RequestContext` and core typed models (stubs with contracts)
- [ ] Unit tests for config validation & error types

### Phase 2 — Database adapter & schema retrieval ⬜
- [ ] `PostgreSQLAdapter`: connection/role management, read-only tx helpers
- [ ] `SchemaRetriever`: dynamic introspection, access-filtered view, versioning
- [ ] Schema caching
- [ ] **Integration tests against a real PostgreSQL instance**

### Phase 3 — SQL parsing & AST (deterministic security core) ⬜
- [ ] Parser abstraction + chosen library (see DECISIONS ADR-0003)
- [ ] AST normalization & identifier resolution
- [ ] Fail-closed on unparseable input
- [ ] Adversarial unit tests (feeds SQL strings directly, no LLM)

### Phase 4 — Deterministic policy engine ⬜
- [ ] `PolicyEngine` composing `PolicyRule`s from config
- [ ] Core rules: statement-type allowlist, table/column access vs. schema+grants,
      forbidden constructs, JOIN/subquery-depth limits
- [ ] Deny-by-default + structured `PolicyDecision`
- [ ] Fail-closed tests (rule error ⇒ deny)

### Phase 5 — Query rewriting & validation ⬜
- [ ] Deterministic rewrites (enforced `LIMIT`, tenant predicates, qualification)
- [ ] Re-parse/validate invariants post-rewrite
- [ ] Reject when safety cannot be proven

### Phase 6 — Cost & complexity checks ⬜
- [ ] Static complexity metrics
- [ ] `EXPLAIN`-based planner cost (never `EXPLAIN ANALYZE`)
- [ ] Configurable thresholds + fail-closed policy when unavailable

### Phase 7 — LLM provider (Mistral) ⬜
- [ ] `MistralProvider` behind `LLMProvider` (API key from env)
- [ ] Prompt construction from access-filtered schema
- [ ] Timeouts/retries; **mocked** unit tests + contract tests (no paid calls in CI)

### Phase 8 — Secure cache ⬜
- [ ] `CacheBackend` with principal-partitioned keys + schema version
- [ ] `InMemoryCache` (default) and `RedisCache`
- [ ] TTL config; cross-principal isolation tests

### Phase 9 — Execution ⬜
- [ ] Principal→DB-role mapping, read-only transactions, `statement_timeout`
- [ ] Result shaping & typed `PipelineResult`
- [ ] Integration tests against real PostgreSQL (incl. RLS enforcement)

### Phase 10 — Audit & analytics ⬜
- [ ] `AuditStore` (append-only, structured records incl. denials/errors)
- [ ] `EventPublisher` + analytics aggregation
- [ ] Tests proving audit occurs on allow/deny/error paths

### Phase 11 — API surface & end-to-end hardening ⬜
- [ ] FastAPI adapter over the library core
- [ ] Full end-to-end integration (real PG + mocked LLM)
- [ ] Security hardening pass, docs polish, example app/notebook

> Phase ordering is a plan, not a contract. Phases 3–6 (the deterministic core)
> can proceed independently of Phase 7 (LLM) because they operate on SQL strings
> directly. Re-sequencing is allowed if dependency-justified and recorded.

---

## Implemented modules

**None.** No Python package exists yet (`src/queryshield/` is planned for
Phase 1).

## Tests implemented

**None.** The test suite begins in Phase 1.

---

## Known limitations (as of Phase 0)

- The repository contains documentation and scaffolding only; there is no
  runnable code, no dependencies, and no tests.
- No `pyproject.toml`, so the project is not yet installable.
- The SQL parsing library is not finalized (ADR-0003, open).
- Git is not initialized by this phase's automation; the user will commit.

## Technical debt

- None accrued yet (no code).

## Intentionally deferred (⏸️)

- **All QueryShield functionality** — deferred to Phase 1+ by the explicit scope
  of Phase 0.
- **Source skeleton / `pyproject.toml`** — deferred to Phase 1 to keep Phase 0
  strictly documentation (ADR-0005).
- **LICENSE / open-source license selection** — deferred to the repository
  owner; a license is a legal decision QueryShield will not invent (ADR-0006).
- **CI configuration** — deferred until there is code and a test suite to run.
- **Local/offline LLM inference (Ollama etc.)** — out of scope unless a future
  phase explicitly requests it.
