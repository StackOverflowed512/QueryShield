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

## ADR-0008 — Baseline language & tooling
- **Status:** Accepted (realized in Phase 1)
- **Date:** 2026-10-01
- **Context:** A production-oriented Python project needs a consistent toolchain.
- **Decision:** Python ≥ 3.11, `src/` layout with PEP 621 `pyproject.toml`,
  `pytest` for tests, and `ruff` + `ruff format` + `mypy --strict` for quality.
  These are realized in Phase 1's `pyproject.toml`. `pydantic` v2 /
  `pydantic-settings` (config) and `pytest-asyncio` + real-PostgreSQL
  integration remain the intended choices but are **deferred to the phases that
  introduce their consumers** — Phase 1 ships zero runtime dependencies
  (ADR-0012), so no config or async libraries are installed yet.
- **Alternatives considered:** Python 3.10 (rejected — want modern typing),
  flat layout (rejected — `src/` avoids import-shadowing in tests), dataclasses
  for config (rejected — want validation at the boundary).
- **Reason:** Mainstream, well-supported, strong typing and validation story.
- **Consequences:** The packaging/quality baseline is now fixed in
  `pyproject.toml`. Build-backend, version-source, test-layout, CI, and
  dependency-discipline specifics are recorded separately in ADR-0011…ADR-0015.
- **Update (Phase 2):** the config library is now pinned to **pydantic v2 +
  an explicit loader, not `pydantic-settings`** (ADR-0016 supersedes this
  ADR's `pydantic-settings` note), and the async + PostgreSQL-driver choices are
  realized in ADR-0018…ADR-0021.

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

---

## ADR-0011 — Hatchling build backend with dynamic version
- **Status:** Accepted
- **Date:** 2026-10-01
- **Context:** The project needs a PEP 517 build backend and a single source of
  truth for the version. Duplicating the version in both `pyproject.toml` and
  the package is a classic drift bug.
- **Decision:** Use **Hatchling** as the build backend and declare the version
  **dynamic**, sourced from `__version__` in `src/queryshield/__init__.py` via
  `[tool.hatch.version]`. The in-code literal is authoritative; the built
  distribution's metadata is derived from it, and a unit test asserts the two
  agree.
- **Alternatives considered:** setuptools (more boilerplate for a src-layout
  dynamic version); flit (fine, but Hatchling's version plugin and build targets
  are more flexible); hard-coding the version in `pyproject.toml` (rejected —
  drifts from the importable `__version__`).
- **Reason:** Minimal config, first-class dynamic-version support, no drift.
- **Consequences:** `hatchling` is a build-time requirement only, never a
  runtime dependency. Releasing remains blocked until a license is chosen
  (ADR-0006).

---

## ADR-0012 — Zero runtime dependencies in Phase 1
- **Status:** Accepted
- **Date:** 2026-10-01
- **Context:** Future phases will need a PostgreSQL driver, a Mistral client, a
  SQL parser, and a cache client. It is tempting to add them now.
- **Decision:** Phase 1 declares **`dependencies = []`**. Runtime libraries are
  added only in the phase that actually consumes them. Development/test tooling
  (`pytest`, `pytest-cov`, `ruff`, `mypy`) lives under the `dev`
  optional-dependency group, not as runtime dependencies.
- **Alternatives considered:** Pre-installing the anticipated stack now —
  rejected; it installs unused code, invites premature coupling, and would let
  "the dependency exists" masquerade as "the feature exists." It would also
  force the still-open SQL-parser choice (ADR-0003) prematurely.
- **Reason:** Honest dependency surface; nothing is pulled in before it is used.
- **Consequences:** Installing QueryShield pulls in nothing extra today. Each
  future phase adds and pins exactly the libraries it introduces, recorded as it
  happens.
- **Update (Phase 2):** honoured as designed — Phase 2 added exactly the three
  runtime libraries its two foundations consume: `pydantic` and `PyYAML` for the
  configuration system (ADR-0016/ADR-0017) and `psycopg[binary,pool]` for the
  database adapter (ADR-0018/ADR-0020). Still nothing for the LLM, parser, or
  cache.

---

## ADR-0013 — Test layout, marker taxonomy, and importlib import mode
- **Status:** Accepted
- **Date:** 2026-10-01
- **Context:** Test structure and pytest import semantics should be fixed early
  so later phases drop tests into an established convention.
- **Decision:** Tests live under `tests/`, split into `tests/unit/` and
  `tests/integration/`. Pytest runs with `--import-mode=importlib` and **no**
  `__init__.py` files in the test tree, decoupling tests from package import
  paths and avoiding module-name clashes. `--strict-markers` and
  `--strict-config` are enabled. A marker taxonomy is registered up front:
  `unit`, `integration`, `security`, `property`, `e2e`, `performance`.
  Integration tests must **skip** (not fail) when their external service is
  absent.
- **Alternatives considered:** `prepend`/`append` import modes with
  `__init__.py` packages (rejected — more fragile under a `src/` layout);
  registering markers lazily (rejected — `--strict-markers` would fail;
  declaring them now is cheap).
- **Reason:** A modern, robust pytest setup that scales to the planned
  security/integration/property suites without rework.
- **Consequences:** Contributors use the registered markers; CI can select or
  exclude suites by marker (e.g. `pytest -m "not integration"`).

---

## ADR-0014 — CI scope: quality gate only, no service containers yet
- **Status:** Accepted
- **Date:** 2026-10-01
- **Context:** CI should enforce quality from the first commit, but no code talks
  to external services yet.
- **Decision:** A GitHub Actions workflow runs the quality gate — `ruff check`,
  `ruff format --check`, `mypy`, `pytest` — on Python 3.11, 3.12, and 3.13 after
  `pip install -e ".[dev]"`. It deliberately provisions **no** PostgreSQL or
  Redis service and performs **no** build/publish/deploy. Those arrive with the
  integration tests and release process that need them.
- **Alternatives considered:** Standing up a PostgreSQL service container now
  (rejected — nothing uses it, so it would only prove a container can start);
  a single Python version (rejected — the project targets 3.11–3.13).
- **Reason:** Enforce quality immediately without pretending integration exists.
- **Consequences:** A PostgreSQL service job and a release workflow are future
  additions; the matrix grows when integration jobs land.
- **Update (Phase 2):** the PostgreSQL service-container job has now landed
  (ADR-0021): CI runs a `quality` matrix job (`pytest -m "not integration"`,
  3.11–3.13) plus a dedicated `integration` job against `postgres:16`. A
  build/publish/release workflow remains deferred (still blocked on a license,
  ADR-0006).

---

## ADR-0015 — Defer a CLI / `__main__` entry point
- **Status:** Accepted
- **Date:** 2026-10-01
- **Context:** Python projects often ship a console-script entry point.
  QueryShield has no user-facing behavior yet.
- **Decision:** Do **not** add a `[project.scripts]` entry point or a
  `__main__.py` in Phase 1. Add one only when there is real behavior to invoke,
  and decide deliberately then between a library-only distribution and a CLI.
- **Alternatives considered:** Scaffolding a no-op CLI now — rejected; a command
  that does nothing is fake functionality.
- **Reason:** No premature surface area; the entry point follows the feature.
- **Consequences:** QueryShield is a library-only distribution for now.

---

## ADR-0016 — Configuration via pydantic v2 models and an explicit loader (not pydantic-settings)
- **Status:** Accepted (realized in Phase 2). Supersedes the `pydantic-settings`
  portion of ADR-0008.
- **Date:** 2026-10-02
- **Context:** Phase 2 needs a strongly typed, validated configuration system:
  values from files and the environment, a deterministic and documented
  precedence, typed coercion, fail-closed rejection of malformed
  security-sensitive values, and — critically — it must coexist with *other*
  `QUERYSHIELD_`-prefixed environment variables (e.g. the integration-test DSN)
  without breaking.
- **Decision:** Model configuration as **pydantic v2** `BaseModel`s
  (`DatabaseConfig`, `QueryShieldConfig`) and load them with a **small, explicit
  `load_config` function** that merges layers deterministically and then calls
  `model_validate`. Use **PyYAML** for optional config files (ADR-0017). Do
  **not** adopt `pydantic-settings`.
- **Alternatives considered:** (a) `pydantic-settings` — its implicit env
  discovery, precedence, and `extra` handling are harder to pin down exactly and
  it wants to own the "ignore unrelated env vars" behaviour we need to control
  precisely; a hand-written loader is a few dozen lines and is fully
  deterministic and testable. (b) `dataclasses` + hand-rolled validation —
  rejected, reinvents pydantic's coercion/validation and secret handling. (c)
  Plain `os.environ` parsing — rejected, no typed validation at the boundary.
- **Reason:** Smallest dependency surface that still gives typed validation, with
  precedence and env-coexistence behaviour we fully control and unit-test.
- **Consequences:** Two runtime dependencies (`pydantic`, `PyYAML`). The loader
  owns precedence and the `${VAR}` interpolation rule (ADR-0017). Future config
  sections (`llm`, `policy`, `cache`, `audit`, …) are added as new models on
  `QueryShieldConfig` by the phases that introduce them.

---

## ADR-0017 — Configuration precedence and environment-variable scheme
- **Status:** Accepted (realized in Phase 2)
- **Date:** 2026-10-02
- **Context:** Precedence must be deterministic and documented, and the env-var
  scheme must not collide with a host application's variables.
- **Decision:** Effective precedence, highest wins:
  **explicit `load_config(...)` keyword overrides > `QUERYSHIELD_`-prefixed
  environment variables > a YAML config file > built-in safe defaults.** Layers
  are deep-merged, then validated once. Env scheme: prefix **`QUERYSHIELD_`**,
  nested keys separated by **`__`** (e.g. `QUERYSHIELD_DATABASE__URL`). The YAML
  file path comes from the `config_file` argument or `QUERYSHIELD_CONFIG_FILE`;
  YAML string values support `${VAR}` interpolation from the environment, and an
  **undefined `${VAR}` fails closed** (never an empty string). Unknown
  top-level `QUERYSHIELD_` variables are **ignored** (`extra="ignore"` on the
  root model) so the test DSN and other prefixed vars can coexist; the
  security-sensitive `database` section is `extra="forbid"` so a typo there is a
  hard error, not a silently-dropped setting.
- **Alternatives considered:** env-over-overrides precedence (rejected — explicit
  programmatic overrides should win, e.g. in tests/embedding); a single flat
  namespace without a prefix (rejected — collides with host env); forbidding
  unknown vars at the root (rejected — would break coexistence with the test DSN
  and any sibling tooling).
- **Reason:** Predictability, no env collisions, and safe coexistence, while
  keeping the security-relevant subsection strict.
- **Consequences:** Documented in `.env.example` and ARCHITECTURE §7. Callers get
  one validated object; malformed input raises `ConfigError` with field
  locations only (ADR-0022), never input values.

---

## ADR-0018 — PostgreSQL driver: psycopg 3
- **Status:** Accepted (realized in Phase 2). Refines the "proposed" driver note
  in ADR-0008 / CLAUDE.md §4.
- **Date:** 2026-10-02
- **Context:** The adapter needs one modern PostgreSQL driver with first-class
  async support, server-side parameter binding, connection pooling, and good
  typing. CLAUDE.md listed "asyncpg and/or psycopg 3 (proposed)".
- **Decision:** Use **psycopg 3** (`psycopg[binary,pool]`). Use its native
  parameter binding (`%s` placeholders) for all value passing, its
  `AsyncConnection` for async I/O, and `psycopg_pool.AsyncConnectionPool` for
  pooling (ADR-0020). The `[binary]` extra ships prebuilt wheels so local and CI
  installs are reproducible without a build toolchain.
- **Alternatives considered:** **asyncpg** — very fast, but its parameter style
  (`$1`) and type handling differ from libpq norms, it has no official sync mode,
  and psycopg 3's libpq alignment and `options=-c statement_timeout=…` support
  fit the security posture (ADR-0002) better. Supporting *both* drivers —
  rejected, see ADR-0019 (no dual sync/async or dual-driver surface).
- **Reason:** One well-typed, libpq-aligned driver with native async and pooling,
  minimizing parser/behaviour surprises and keeping configuration close to libpq.
- **Consequences:** `psycopg` is a runtime dependency from Phase 2. The adapter
  is psycopg-specific behind the `DatabaseAdapter` interface, so another driver
  could be added later without touching callers.

---

## ADR-0019 — Async-first database layer (single execution model)
- **Status:** Accepted (realized in Phase 2)
- **Date:** 2026-10-02
- **Context:** The Phase 2 task requires an explicit, documented choice between
  sync and async — and *not* implementing both. The pipeline's hot path is I/O
  (database, and later cache, LLM, HTTP).
- **Decision:** The database abstraction is **async-only**. `DatabaseAdapter` and
  `DatabaseSession` expose `async` methods exclusively; there is no parallel
  synchronous API. The adapter also documents and enforces the **trust
  boundary**: it executes already-validated SQL inside a transaction against a
  least-privilege principal and does **not** decide authorization — that belongs
  to the later deterministic security layers. There is deliberately no public
  "run any string" convenience API that bypasses the transaction/least-privilege
  machinery.
- **Alternatives considered:** Sync-only (rejected — blocks the event loop under
  concurrent I/O and fights the planned async LLM/HTTP edges); maintaining both
  sync and async surfaces (rejected explicitly by the task — double the surface,
  double the security-review burden, drift risk).
- **Reason:** One execution model matched to an I/O-bound pipeline; a smaller
  security surface to audit.
- **Consequences:** Callers use `await` / `async with`. Tests use
  `pytest-asyncio` (`asyncio_mode="auto"`). A synchronous wrapper, if ever
  needed, would be an explicit future addition behind the same interface.

---

## ADR-0020 — Connection pooling via psycopg_pool, fully configurable
- **Status:** Accepted (realized in Phase 2)
- **Date:** 2026-10-02
- **Context:** A server-side component needs connection reuse, bounded
  concurrency, a clean shutdown, and timeouts — none of which may be hard-coded
  (CLAUDE.md §5).
- **Decision:** Use `psycopg_pool.AsyncConnectionPool`. Pool size
  (`pool_min_size`/`pool_max_size`), the wait-for-connection `pool_timeout`, the
  new-connection `connect_timeout`, the server-side `statement_timeout`, and
  `sslmode` are all **configuration** with safe, overridable defaults.
  `statement_timeout` is applied once per connection via the libpq
  `options=-c statement_timeout=<ms>` parameter (no runtime `SET`, no
  transaction side effects), so it covers every pooled session. `open()` opens
  the pool (optionally waiting for the minimum connections) and `close()` drains
  it; the adapter is also an async context manager.
- **Alternatives considered:** No pool / connect-per-request (rejected — latency
  and connection storms); an application-level custom pool (rejected — reinvents
  a solved, well-tested component); hard-coded sizes/timeouts (rejected — the
  no-hard-coding rule).
- **Reason:** A battle-tested pool with every knob exposed as config and a
  deterministic, fail-closed open/close lifecycle.
- **Consequences:** `psycopg[pool]` is required. The health check uses a pooled
  connection and reports **unhealthy** (never healthy) when the database cannot
  be reached.

---

## ADR-0021 — Integration testing against a disposable real PostgreSQL
- **Status:** Accepted (realized in Phase 2). Extends ADR-0014 ("the matrix grows
  when integration jobs land").
- **Date:** 2026-10-02
- **Context:** Testing rules (CLAUDE.md §6) forbid relying solely on mocks: the
  adapter must be proven against a real PostgreSQL, reproducibly, without
  depending on any developer's personal installation.
- **Decision:** Integration tests read `QUERYSHIELD_TEST_DATABASE_URL` and
  **skip** (not fail) when it is unset, so a plain `pytest` run is green with no
  database. CI runs them against an ephemeral **`postgres:16` service
  container** with test-only credentials in a dedicated `integration` job; the
  `quality` job runs `pytest -m "not integration"` across the Python matrix. No
  Mistral key is present anywhere. Any table a test needs is created with a
  **uniquely generated name** (a `uuid4` hex, never caller input) and dropped
  afterwards; there is no fixed demo schema in the test database. Coverage:
  health check, pool acquire/release under concurrency, parameterised execution,
  a hostile value proving no interpolation, commit visibility, rollback on
  error, write blocked in a read-only transaction, operations failing after
  shutdown, and invalid credentials reported without leaking the password.
- **Alternatives considered:** Mock-only tests (rejected by the rules — would not
  exercise real transaction/read-only/pool behaviour); `testcontainers`
  (reasonable, but the GitHub Actions service container is simpler and equally
  reproducible for CI; local devs can use a throwaway `docker run`); a shared
  long-lived test database (rejected — not reproducible, risks cross-run state).
- **Reason:** Real behaviour, reproducible in CI, zero dependence on personal
  setups, and safe-by-default skipping locally.
- **Consequences:** Two CI jobs. Contributors opt in locally by exporting
  `QUERYSHIELD_TEST_DATABASE_URL` at a disposable database (see
  `tests/integration/README.md`).

---

## ADR-0022 — Secret handling: typed secrets, DSN sanitisation, and scrubbing
- **Status:** Accepted (realized in Phase 2)
- **Date:** 2026-10-02
- **Context:** The task forbids secrets (DB passwords, DSNs, API keys) from
  appearing in logs, `repr`/`str`, or exception messages, and requires that
  diagnostic information not be destroyed internally (use exception chaining).
- **Decision:** Store secret config values as **`pydantic.SecretStr`** (the
  database `url` today, API keys later), so `repr`/`str`/logging never reveal
  them. The config loader renders validation failures from **field location and
  message only** (`errors(include_url=False)`), never from input values, so a
  secret in one field cannot leak when a *different* field fails. The PostgreSQL
  adapter keeps only a **sanitised descriptor** (`host=… dbname=… user=…`, via
  `sanitize_dsn`) for logs, and **scrubs** the full DSN and password out of every
  outgoing error message (`scrub_secrets`) before wrapping the driver exception
  in a `QueryShieldError` subclass **with `raise … from exc`** so the original
  traceback is preserved internally while the user-facing message stays
  secret-free.
- **Alternatives considered:** Plain `str` secrets with ad-hoc redaction at log
  sites (rejected — easy to forget one site; `SecretStr` is safe by
  construction); swallowing driver errors to avoid leaks (rejected — destroys
  diagnostics and violates fail-closed clarity).
- **Reason:** Secrets must be unleakable by default, while diagnostics are
  preserved through chaining.
- **Consequences:** Error text is sanitised and may be slightly less detailed
  than a raw driver error; the full chained cause remains available to internal
  logging/debuggers. New secret-bearing fields must use `SecretStr`, and new
  error paths must scrub before raising.
