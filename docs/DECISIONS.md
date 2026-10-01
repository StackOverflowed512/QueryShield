# QueryShield — Architecture Decision Record (ADR) Log

> ADR-style log of **significant** technical decisions. Each entry records the
> decision, its context, alternatives considered, the reason, and the
> consequences. Trivial implementation details are intentionally **not**
> recorded here.
>
> Status values: **Accepted** · **Proposed** (reasonable default, may change) ·
> **Open** (explicitly undecided) · **Superseded**.

---

## ADR-0001 — The LLM is never a trusted security component
- **Status:** Accepted
- **Date:** 2026-10-01
- **Context:** QueryShield executes SQL that originates from an LLM (Mistral).
  LLM output is probabilistic and manipulable (prompt injection, hallucinated
  tables, false claims of safety).
- **Decision:** The LLM may only *propose* candidate SQL. No security decision
  may depend on LLM output or LLM-claimed metadata. All security verdicts are
  made by deterministic QueryShield code operating on the parsed SQL.
- **Alternatives considered:** (a) Trust the LLM to self-certify safe SQL —
  rejected, non-deterministic and trivially bypassed. (b) Ask a second LLM to
  judge the first — rejected, still non-deterministic and unauditable.
- **Reason:** Security must be deterministic, testable, and auditable.
- **Consequences:** A full deterministic analysis stack (parser, policy engine,
  rewriter, cost checks) is required and is the heart of the product. The LLM
  becomes a replaceable, untrusted edge component.

---

## ADR-0002 — PostgreSQL is the authoritative enforcement layer
- **Status:** Accepted
- **Date:** 2026-10-01
- **Context:** Application-layer checks can have bugs; a security product must
  not be the single point of failure for data access.
- **Decision:** Callers are mapped to **least-privilege PostgreSQL roles**, and
  execution relies on database privileges and row-level security (RLS) as the
  final authority. Application checks are defense in depth, not the only line.
- **Alternatives considered:** Enforce everything in the application and connect
  to the DB as a broadly privileged role — rejected, turns any app bug into a
  full data breach.
- **Reason:** Defense in depth; the database already has a mature, battle-tested
  authorization model.
- **Consequences:** Deployments must provision roles/RLS; QueryShield must map
  the `RequestContext` to a DB role at execution time. Documented as a
  deployment responsibility.

---

## ADR-0003 — SQL parsing library (parser-differential risk)
- **Status:** **Open**
- **Date:** 2026-10-01
- **Context:** The parser is the foundation of deterministic analysis. If the
  grammar QueryShield parses differs from the grammar PostgreSQL executes, a
  query can pass analysis yet behave differently when run (a *parser
  differential* vulnerability).
- **Decision (pending):** Evaluate two candidates in the parsing phase:
  - **`pglast`** (wraps `libpg_query`, the real PostgreSQL parser): maximal
    fidelity — what we parse is what PG parses — at the cost of a C dependency
    and PostgreSQL-only scope.
  - **`sqlglot`** (pure-Python, multi-dialect): easy to install and
    manipulate, but a *reimplementation* of the grammar, which reintroduces
    differential risk.
- **Alternatives considered:** Hand-rolled parser (rejected — enormous surface,
  guaranteed to drift from PG); regex-based inspection (rejected outright — the
  project forbids regex-based security).
- **Reason to defer:** The choice has real security weight and should be made
  with the policy engine's needs in view; no code depends on it yet.
- **Consequences:** Until decided, the parser phase must keep the library behind
  an abstraction so the engine is not coupled to either. Leaning toward `pglast`
  for fidelity; final call recorded when Phase 3 begins. Least-privilege
  roles + RLS (ADR-0002) remain the backstop regardless.

---

## ADR-0004 — Fail closed; no silent fallbacks
- **Status:** Accepted
- **Date:** 2026-10-01
- **Context:** The dangerous failure mode for a security layer is silently
  degrading to a weaker check when something breaks.
- **Decision:** When a required security step cannot be performed, the default
  is to **deny**. Any relaxation (e.g., continue when the cost backend is down)
  must be an explicit, documented configuration option. There are no implicit
  `except: pass` weakenings. See the fail-closed matrix in
  [`ARCHITECTURE.md`](ARCHITECTURE.md#4-trust--security-boundaries).
- **Alternatives considered:** Best-effort/degrade-open for availability —
  rejected as the default; offered only as explicit opt-in per failure type.
- **Reason:** Safety and predictability over convenience.
- **Consequences:** Operators must consciously opt into any availability-over-
  safety trade-off; those switches are configuration, surfaced and audited.

---

## ADR-0005 — Phase 0 is documentation-only
- **Status:** Accepted
- **Date:** 2026-10-01
- **Context:** The initiating task scoped Phase 0 to establishing context and
  documentation infrastructure, explicitly excluding functionality.
- **Decision:** Phase 0 creates only `CLAUDE.md`, the three `docs/` files,
  `README.md`, and `.gitignore`. No `pyproject.toml`, no `src/` package, no
  code or empty stub modules (empty stubs would imply functionality that does
  not exist).
- **Alternatives considered:** Scaffold an empty `src/queryshield/` package now
  — rejected; it blurs the planned/implemented line this phase is meant to keep
  crisp.
- **Reason:** Keep the planned-vs-implemented distinction honest and the first
  commit purely contextual.
- **Consequences:** The project skeleton is the first task of Phase 1.

---

## ADR-0006 — Defer open-source license selection to the owner
- **Status:** Accepted
- **Date:** 2026-10-01
- **Context:** The project is described as open source, which requires a
  license, but license choice carries legal/governance implications.
- **Decision:** Do not add a `LICENSE` file in Phase 0. Record it as a deferred
  decision for the repository owner.
- **Alternatives considered:** Pick a permissive license (e.g., MIT/Apache-2.0)
  by default — rejected; this would be inventing a requirement with legal
  weight.
- **Reason:** Licensing is the owner's decision, not an engineering default.
- **Consequences:** README notes the license as "to be decided." Distribution/
  publishing is blocked until chosen.

---

## ADR-0007 — Secure cache is principal-partitioned
- **Status:** Accepted
- **Date:** 2026-10-01
- **Context:** Caching query results across requests risks returning one
  principal's data to another (cross-tenant leak).
- **Decision:** Cache keys are derived from the full `RequestContext` principal
  **plus** the validated SQL **plus** a schema version. A result is cached only
  after it passes policy/validation. Keys are treated as a security control and
  unit-tested for cross-principal isolation.
- **Alternatives considered:** Key solely on query text — rejected, leaks across
  principals; key on NL text — rejected, same risk and ignores policy outcome.
- **Reason:** Prevent cross-principal data exposure via the cache.
- **Consequences:** Lower hit rates than a naive cache, accepted as the price of
  isolation. An optional NL-level cache remains a future extension that must
  preserve the same partitioning.

---

## ADR-0008 — Baseline language & tooling (proposed)
- **Status:** Proposed
- **Date:** 2026-10-01
- **Context:** A production-oriented Python project needs a consistent toolchain.
- **Decision (proposed):** Python ≥ 3.11, `src/` layout with PEP 621
  `pyproject.toml`, `pydantic` v2 / `pydantic-settings` for config, `pytest`
  (+`pytest-asyncio`) for tests with real-PostgreSQL integration, `ruff` +
  `ruff format` + `mypy --strict` for quality.
- **Alternatives considered:** Python 3.10 (rejected — want modern typing),
  flat layout (rejected — `src/` avoids import-shadowing in tests), dataclasses
  for config (rejected — want validation at the boundary).
- **Reason:** Mainstream, well-supported, strong typing and validation story.
- **Consequences:** Finalized when `pyproject.toml` lands in Phase 1; revisit
  only with cause.

---

## ADR-0009 — Mistral via API key only; no local inference
- **Status:** Accepted
- **Date:** 2026-10-01
- **Context:** The LLM integration target is the hosted Mistral API.
- **Decision:** Integrate Mistral through its hosted API using an API key from
  configuration/environment. Do **not** implement local inference, Ollama, or
  local model serving unless a future phase explicitly requests it. The model
  name is configuration, never hard-coded.
- **Alternatives considered:** Local/self-hosted models — explicitly out of
  scope for now.
- **Reason:** Matches the stated requirement and keeps the LLM a thin, swappable
  `LLMProvider`.
- **Consequences:** Deployments need network access and a Mistral key; the
  `LLMProvider` abstraction keeps a future local provider possible without core
  changes.

---

## ADR-0010 — `RequestContext` is the single security principal
- **Status:** Accepted
- **Date:** 2026-10-01
- **Context:** The system must support many tenants, users, roles, policies, and
  databases, and must never infer identity from LLM output.
- **Decision:** A single typed `RequestContext`, supplied by the trusted caller,
  carries tenant(s)/user/roles/database-selector/limit-overrides and threads
  through the entire pipeline. Cache keys, audit records, DB sessions, and
  schema filtering all derive from it.
- **Alternatives considered:** Global/ambient single-tenant config (rejected —
  violates multi-everything); deriving tenant from the query/LLM (rejected —
  untrusted).
- **Reason:** One trustworthy, explicit source of identity simplifies isolation
  and auditing.
- **Consequences:** Every stage signature takes the context; exact fields are
  finalized in Phase 1.
