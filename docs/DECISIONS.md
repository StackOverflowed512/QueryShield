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

## ADR-0003 — SQL parsing library: `pglast` (the real PostgreSQL grammar)
- **Status:** **Accepted (realized in Phase 4)**. Supersedes the earlier
  "Open / leaning toward" provisional state.
- **Date:** 2026-10-01; **decided 2026-10-08**.
- **Context:** The parser is the foundation of every deterministic decision
  QueryShield makes (CLAUDE.md §3, ADR-0001). If the grammar QueryShield parses
  differs from the grammar PostgreSQL executes, a query can pass analysis yet
  behave differently when run — a *parser differential* vulnerability, and the
  single largest architectural risk in the project
  ([`ARCHITECTURE.md`](ARCHITECTURE.md#10-known-architectural-risks-tracked-not-yet-mitigated)).
  Phase 4 must therefore pick one parser and commit to it.
- **Decision:** Use **`pglast`**, which wraps **`libpg_query`** — PostgreSQL's
  *own* parser, extracted from the server source. QueryShield parses candidate
  SQL with the same grammar the target database will execute it with, which
  eliminates the differential **by construction** rather than by careful
  reimplementation. The dependency is declared with an **upper bound**
  (`pglast>=6,<8`) so a major bump cannot silently swap the bundled
  `libpg_query` release line under us. The library is confined behind the
  QueryShield-owned `SQLParser` interface and QueryShield-owned parsed-query
  types; no pglast node type escapes the `queryshield.sql` package.
- **Alternatives considered:**
  - **`sqlglot`** (pure-Python, multi-dialect) — genuinely attractive: pure
    Python, no C toolchain, a much friendlier AST to manipulate. Rejected
    anyway, because it is a **reimplementation** of SQL grammars. Every dialect
    divergence from PostgreSQL is a potential parser differential, and a
    differential is exactly the vulnerability this layer exists to prevent.
    "Convenient" must not win over "the same grammar the database uses".
  - **Hand-rolled parser** — rejected; an enormous surface, guaranteed to drift
    from PostgreSQL.
  - **Regex / `str.startswith` inspection** — rejected outright; the project
    forbids pattern-matching its way to a security verdict (CLAUDE.md §5), and
    Phase 4's statement classification is AST-driven precisely because of this.
- **Reason:** Fidelity is the whole point of the layer. Parsing with
  PostgreSQL's own grammar means "what QueryShield analyzed" and "what
  PostgreSQL executes" are the same parse, so no differential can exist between
  them.
- **Consequences:**
  - `pglast` becomes a **runtime dependency from Phase 4** — the second
    vendor-touching dependency after psycopg, and like it, isolated behind an
    interface (`SQLParser`) with the concrete implementation
    (`PostgreSQLSQLParser`) living under `queryshield.sql`.
  - QueryShield is **PostgreSQL-only** at the parsing layer (already true of the
    database adapter, ADR-0018, and the schema retriever, ADR-0025). Supporting
    another engine would mean a second `SQLParser` implementation behind the
    same interface — no core change.
  - The import is **lazy** (`PostgreSQLSQLParser.parse`), so a host that never
    parses SQL is not forced to load a C extension at `import queryshield`.
  - The bundled `libpg_query` is versioned with `pglast`; the pin's minor range
    is chosen to track a grammar contemporaneous with the CI/test target
    (`postgres:16`, ADR-0021). A future PostgreSQL major bump means revisiting
    the pin **and** this ADR.
  - Least-privilege roles + RLS (ADR-0002) remain the backstop regardless: even
    a parser bug cannot grant access the database role would refuse.

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

---

## ADR-0023 — Dedicated schema-introspection layer behind a `SchemaRetriever` interface
- **Status:** Accepted (realized in Phase 3)
- **Date:** 2026-10-05
- **Context:** Phase 3 must discover a PostgreSQL database's *structure*
  (schemas, tables, views, columns, keys, constraints, indexes) to feed later
  stages (LLM prompting, the policy engine, the rewriter). It must reuse the
  Phase 2 database layer rather than open its own connections, be swappable (a
  different catalog source could exist), and fail closed with typed errors
  distinct from the database layer's — a reachable-but-failed catalog query, an
  internally inconsistent catalog, and an unreachable database are three
  different conditions a caller must be able to tell apart.
- **Decision:** Introduce a `queryshield.schema` package with an abstract
  **`SchemaRetriever`** (`async def retrieve() -> SchemaCatalog`) and a concrete
  **`PostgreSQLSchemaRetriever`** constructed with an existing
  `DatabaseAdapter`, running all introspection through it — **no second
  connection or pool implementation**. Add a **`SchemaError`** hierarchy
  (`SchemaRetrievalError`, `SchemaMetadataError`) that is **not** a subclass of
  `DatabaseError`: a reachable database whose catalog query fails becomes a
  `SchemaRetrievalError` (chained `from` the cause); a catalog whose rows are
  internally inconsistent becomes a `SchemaMetadataError` raised from a *pure*
  assembly step outside the I/O boundary; a connection failure propagates as the
  Phase 2 `DatabaseConnectionError`, unchanged. Introspection **never** returns a
  fabricated empty catalog on failure.
- **Alternatives considered:** (a) Fold introspection into the adapter — rejected;
  the adapter is a trusted *executor*, not a catalog model (ADR-0019), and this
  would bloat the trust boundary. (b) A new connection pool for introspection —
  rejected; duplicates ADR-0020 and splits the single execution path. (c) Reuse
  `DatabaseError` for schema faults — rejected; callers must distinguish "DB
  down" from "catalog malformed" from "catalog query failed".
- **Reason:** One connection path, a swappable interface, and a precise,
  fail-closed error contract that keeps metadata faults separate from I/O faults.
- **Consequences:** The retriever operates as whatever database identity the
  adapter is configured with; binding it to a per-request principal
  (`RequestContext`, ADR-0010) and to a dedicated `SchemaConfig` section is
  **deferred** to the phase that introduces request handling (ADR-0028). Future
  catalog sources implement the same interface without touching callers.

---

## ADR-0024 — Frozen, slotted dataclasses for the schema domain model
- **Status:** Accepted (realized in Phase 3)
- **Date:** 2026-10-05
- **Context:** The discovered schema is a **read-only snapshot** produced by
  trusted introspection code and consumed widely downstream. It must be
  immutable (a snapshot must not mutate after retrieval), cheap, and
  dependency-light, and it carries **no** security or governance data (no PII
  labels, no per-principal visibility) — that belongs to later layers.
- **Decision:** Model the catalog as **frozen, slotted `@dataclass`es** —
  `Column`, `PrimaryKey`, `UniqueConstraint`, `ForeignKey`, `Index`, `Table`,
  `View`, `Schema`, `SchemaCatalog` — with tuple (immutable) collections. A
  **`View` is modelled separately from `Table`**: a view has no primary or
  foreign keys, and a *materialized* view can carry indexes while a plain view's
  index tuple is always empty. Do **not** use `pydantic` for these types.
- **Alternatives considered:** (a) `pydantic` models — rejected; runtime
  validation buys nothing for objects *produced* by trusted code rather than
  *parsed* from untrusted input, and it is heavier. (b) A single `Relation` type
  with a kind flag — rejected; it would carry meaningless PK/FK fields on views,
  inviting misuse. (c) Mutable dataclasses or dicts — rejected; a snapshot must
  be immutable and typed.
- **Reason:** Immutability by construction, low cost, zero dependency, and
  consistency with the frozen-slotted `HealthCheckResult` from Phase 2.
- **Consequences:** The objects are hashable and safe to share; building them is
  the introspector's job; `mypy --strict` enforces the shapes. Downstream code
  treats a `SchemaCatalog` as strictly read-only.

---

## ADR-0025 — Introspect via `pg_catalog`, one read-only transaction, honoring `has_table_privilege`
- **Status:** Accepted (realized in Phase 3)
- **Date:** 2026-10-05
- **Context:** The retriever needs accurate PostgreSQL structure, including
  PG-specific detail the SQL-standard `information_schema` flattens or omits
  (exact rendered types, materialized views, partitioned tables, expression-index
  columns). It must **not** interpolate values into SQL, must **not** issue a
  query per object (no N+1), and must show a role only what it may actually read.
- **Decision:** Query **`pg_catalog`** (not `information_schema`) through
  **exactly six bounded statements in one read-only transaction**: (1) namespaces;
  then — after filtering the names in Python (ADR-0028) — (2) relations,
  (3) columns, (4) primary/unique constraints, (5) foreign keys, (6) indexes. The
  selected schema names are passed as a **single bound array parameter** used
  with **`= ANY(%s)`**, never string-interpolated. Relations are filtered by
  **`has_table_privilege(…, 'SELECT')`** so a role sees only what it may read.
  Column types are rendered with `pg_catalog.format_type` and kept verbatim as
  text (ADR-0026).
- **Alternatives considered:** (a) `information_schema` — rejected; it loses PG
  specifics (materialized views, partitioning, exact type text, expression
  indexes) and is often slower. (b) One query per table/relation — rejected; N+1,
  slow, and racier. (c) Building the schema allow-list into the SQL text —
  rejected by the no-hard-coding and no-interpolation rules.
- **Reason:** Fidelity, a bounded and auditable query count, parameter safety, and
  privilege-correct results.
- **Consequences:** The retriever is PostgreSQL-specific (acceptable behind
  `SchemaRetriever`); it reports exactly what its database identity is granted;
  the round-trip count is six regardless of catalog size. A foreign key may
  reference a relation outside the selection or unreadable by the role —
  recording the reference is not a claim of access to its target.

---

## ADR-0026 — Canonical identifiers preserved verbatim
- **Status:** Accepted (realized in Phase 3)
- **Date:** 2026-10-05
- **Context:** PostgreSQL identifiers may be mixed-case, contain spaces or
  Unicode, or be reserved words when quoted. Case-folding or otherwise
  normalizing them would make catalog lookups disagree with the database and
  could blur two genuinely distinct identifiers into one.
- **Decision:** Store every `name` **exactly as PostgreSQL reports it**
  (`pg_class.relname` et al.) — original case, spaces, Unicode, reserved words —
  and **never** case-fold or normalize. Lookups
  (`get_schema`/`get_table`/`get_view`/`get_column`) are **exact, case-sensitive**
  matches on the stored string. Rendering an identifier back into SQL (quoting)
  belongs to the future query-construction layer, not to these models.
- **Alternatives considered:** (a) Lower-casing or normalizing identifiers —
  rejected; it diverges from the database and is a correctness *and* security
  risk (an identifier-level differential). (b) Storing a normalized key alongside
  the raw name — rejected; speculative, unused, and a source of ambiguity.
- **Reason:** The model must mean exactly what the database means; identity is
  byte-for-byte.
- **Consequences:** Callers match names exactly. A case-insensitive convenience
  lookup, if ever needed, is an explicit future addition that must not become the
  default.

---

## ADR-0027 — Deterministic structural fingerprint
- **Status:** Accepted (realized in Phase 3)
- **Date:** 2026-10-05
- **Context:** Downstream caching and drift detection need a stable identifier
  for "the shape of this database" that changes **iff** the structure changes —
  independent of the order introspection assembled rows in, and independent of
  documentation or wall-clock time.
- **Decision:** `SchemaCatalog.from_schemas` computes a **SHA-256 over a canonical
  JSON encoding of the structure**, prefixed **`sha256:`**. The encoding sorts
  collections (schemas/tables/views by name, columns by `(ordinal, name)`,
  constraints and indexes by name) so assembly order is irrelevant, while
  semantically meaningful order (column ordinal; key/FK/index column order) is
  preserved and encoded. **Comments, retrieval time, and database identity are
  deliberately excluded.** JSON is emitted with
  `sort_keys=True, separators=(",", ":"), ensure_ascii=False`.
- **Alternatives considered:** (a) A timestamp or UUID per retrieval — rejected;
  not reproducible, defeats the caching/drift use. (b) Hashing a Python `repr` —
  rejected; order- and format-fragile. (c) Including comments — rejected;
  documentation is not structure and would cause spurious cache invalidation.
- **Reason:** A pure function of shape — exactly what a cache key or drift check
  wants.
- **Consequences:** Two structurally identical snapshots share a fingerprint; any
  structural change moves it; a comment change does not. The `sha256:` prefix
  makes the scheme self-describing, so a future algorithm is distinguishable from
  this one.

---

## ADR-0028 — Snapshot semantics, explicit refresh, and generic config-driven schema filtering
- **Status:** Accepted (realized in Phase 3)
- **Date:** 2026-10-05
- **Context:** Two related lifecycle questions: *which* schemas a retrieval
  covers, and *when* its data is considered current. The product forbids
  hard-coding deployment-specific schema names (CLAUDE.md §5) and forbids silent
  stale data (fail closed, ADR-0004).
- **Decision:** `SchemaCatalog` is an **immutable point-in-time snapshot** with
  **no implicit caching and no concept of staleness**; obtaining current
  structure is an **explicit `retrieve()`** that always re-introspects and
  returns a fresh, independent snapshot. Schema selection is a **generic,
  configurable `SchemaFilter`**: a safe default that **skips system schemas**
  (`pg_*`, `information_schema`) and admits everything else; an optional exact
  **allow-list** (`include`); and a **deny-list** (`exclude`) applied after it —
  all **case-sensitive** and **order-preserving**. No schema name (`public`,
  `customers`, …) is ever hard-coded, and an explicit empty allow-list
  legitimately selects **nothing** (short-circuiting the per-object queries)
  rather than erroring.
- **Alternatives considered:** (a) Caching the catalog inside the retriever with a
  TTL — rejected for Phase 3; it hides staleness. A cache, if added, belongs in an
  explicit `CacheBackend` with its own invalidation keyed on the fingerprint
  (ADR-0027). (b) Assuming the `public` schema — rejected by the no-hard-coding
  rule and the multi-schema reality. (c) Building include/exclude from a fixed
  list — rejected; deployment-specific.
- **Reason:** Honest, explicit freshness and deployment-agnostic scoping.
- **Consequences:** Callers decide when to refresh and may compare fingerprints
  (ADR-0027) to detect drift. Wiring the filter to a dedicated `SchemaConfig`
  section and to the per-request `RequestContext` principal (ADR-0010) is
  **deferred** to the request-handling phase; today the retriever takes an
  explicit `SchemaFilter` whose default skips system schemas.

---

## ADR-0029 — Parsing behind a `SQLParser` interface with a QueryShield-owned model
- **Status:** Accepted (realized in Phase 4)
- **Date:** 2026-10-08
- **Context:** The concrete parser is `pglast` (ADR-0003), a C extension whose
  node classes are generated to mirror libpg_query and whose API can shift
  between releases. Coupling the policy engine, rewriter, and cost checks
  directly to pglast node objects would spread that volatility across the whole
  codebase and hand each layer a raw, vendor-shaped AST to reason about.
- **Decision:** Parsing sits behind a QueryShield-owned
  `SQLParser` abstract base (async, like `SchemaRetriever`) with a single
  `PostgreSQLSQLParser` implementation. Its `parse()` returns a QueryShield-owned
  **`ParsedQuery`** — an immutable, strongly typed description of the statement
  built entirely from QueryShield dataclasses and enums. **No pglast type
  appears in any public signature or returned object**; the vendor AST is read
  only inside `PostgreSQLSQLParser` and converted immediately. Analysis utilities
  (walkers, extractors) operate on `ParsedQuery`, never on pglast nodes.
- **Alternatives considered:** (a) Return pglast nodes directly — rejected; it
  leaks a C-extension dependency and its release-to-release churn into every
  downstream layer, and makes the model impossible to construct in tests without
  pglast. (b) Wrap nodes in a thin `Any`-typed shim — rejected; a shim that
  exposes arbitrary attributes is pglast by another name and defeats type
  checking. (c) Serialise the AST to JSON and expose that — rejected; a generic
  dict is not a strongly typed model and pushes validation to every consumer.
- **Reason:** Interfaces hold the vendor at the edge (CLAUDE.md §2.7/§5). A
  QueryShield-owned model is stable, fully typed, and testable without the
  vendor present, and it can be tightened as later phases refine it.
- **Consequences:** A conversion layer from pglast nodes to `ParsedQuery` is
  owned and tested by QueryShield. Fields the model does not yet capture are
  simply absent (not exposed as opaque blobs); extending the model is a local,
  additive change. Swapping parsers later means reimplementing conversion only,
  behind the same `SQLParser` interface.

---

## ADR-0030 — Statement classification is AST-driven; multi-statement detection is structural
- **Status:** Accepted (realized in Phase 4)
- **Date:** 2026-10-08
- **Context:** Later phases must make a deterministic security decision *per
  statement*, so the first question about any candidate SQL is "how many
  statements are these, and what kind is each?" The tempting shortcuts —
  `sql.lower().startswith("select")`, counting `;`, `sql.split(";")` — are
  unsound: comments, string literals, dollar-quoting, and embedded semicolons
  break them, and a mis-split can hide a second statement from analysis. The
  project forbids regex- and prefix-based inspection (CLAUDE.md §5). Classification
  must also never trust any metadata the LLM emits about its own SQL (ADR-0001).
- **Decision:** Two rules, both structural:
  1. **How many statements** is determined by the parser, not the text: the
     PostgreSQL grammar parses the whole string into a list of top-level
     statements, and that count *is* the statement count. QueryShield never
     splits on `;`. Zero statements and multiple statements are both represented
     explicitly on `ParsedQuery`; **no statement is ever silently discarded**.
  2. **What kind a statement is** comes from its top-level AST node type —
     mapped to a QueryShield `StatementType` enum (`SELECT`, `INSERT`, `UPDATE`,
     `DELETE`, `MERGE`, DDL kinds, `GRANT`/`REVOKE`, …), with an explicit
     `UNKNOWN` for a node the mapping does not recognise. `UNKNOWN` is a real,
     fail-safe value: it is never treated as "safe" or "harmless".
- **Alternatives considered:** (a) Prefix/substring matching — rejected; trivially
  defeated by comments and whitespace, and banned by project doctrine. (b) Regex
  over the raw string — rejected outright. (c) Splitting on `;` — rejected;
  unsound around literals, dollar-quotes, and comments. (d) Trusting the LLM's
  stated statement type — rejected (ADR-0001).
- **Reason:** The only sound source of "what SQL is this" is the parse of that
  SQL. Structural detection cannot be fooled by text tricks that change the
  surface but not the parse.
- **Consequences:** Classification is exactly as correct as the parser (ADR-0003),
  which is why fidelity was chosen. New statement kinds map to `UNKNOWN` until a
  later phase adds them, and `UNKNOWN` flows through as "not yet understood",
  never as an allow. The policy engine (a later phase) consumes `StatementType`;
  Phase 4 only *reports* it and makes no allow/deny decision.

---

## ADR-0031 — Fail closed on unparseable input: structured error, no partial results
- **Status:** Accepted (realized in Phase 4)
- **Date:** 2026-10-08
- **Context:** Candidate SQL is untrusted (ADR-0001). When it is not valid
  PostgreSQL, the analysis layers must not be handed *something* to reason about
  — an empty AST, a partially parsed statement, or a best-effort guess would let
  a malformed query slip past checks that assume a complete parse. This is the
  parser's instance of the project-wide fail-closed rule (ADR-0004).
- **Decision:** `parse()` either returns a **complete** `ParsedQuery` for the
  whole input, or raises a structured **`SQLParseError`** (a `QueryShieldError`).
  It never returns a partial result and never silently degrades:
  - an empty or whitespace-only input, or input that yields no top-level
    statement, raises rather than returning an empty parse;
  - a parse failure is surfaced as `SQLParseError`, chaining the underlying
    parser exception as `__cause__` so diagnostics are preserved without leaking
    the vendor type into the public contract;
  - **no dialect retry**: QueryShield targets the PostgreSQL grammar (ADR-0003)
    and does **not** fall back to a different dialect or an alternative parser
    when parsing fails;
  - the error type is part of an extensible hierarchy so later phases can add
    more specific parse-related errors without breaking callers that catch
    `SQLParseError`.
- **Alternatives considered:** (a) Return an empty/partial AST with a flag —
  rejected; a downstream layer that forgets to check the flag analyses garbage.
  (b) `except Exception: return None` — rejected; an implicit weakening (ADR-0004).
  (c) Retry other dialects for a "best-effort" parse — rejected; parsing input
  with a grammar the database will not use reintroduces the differential
  (ADR-0003) and can turn an error into a false success.
- **Reason:** "Unparseable" must mean "unanalyzable", full stop. The safe default
  when structure cannot be established is refusal, not a guess.
- **Consequences:** Callers must handle `SQLParseError`; the default pipeline
  (a later phase) turns it into a denial. Because the failure is a typed
  exception with a preserved cause, it is auditable and debuggable. `SQLParseError`
  joins the top-level error hierarchy exported from `queryshield`.

---

## ADR-0032 — Verbatim identifiers and non-destructive normalization in the parsed model
- **Status:** Accepted (realized in Phase 4). Extends ADR-0026 (verbatim schema
  identifiers) to the parsed-query model.
- **Date:** 2026-10-08
- **Context:** A parse necessarily normalises *some* things (quoting, keyword
  case, whitespace), and the parsed model is the input to a security analysis
  that must not lose security-relevant detail. Two failure modes to avoid:
  losing the exact identifier the query names, and dropping structure (an
  alias, a `DISTINCT`, a join type, a locking clause) that a later policy check
  needs to see.
- **Decision:**
  - Identifiers (table, view, column, schema, alias, CTE, function names) are
    stored **exactly as the query wrote them** — original case, Unicode, quoting
    semantics preserved — with **no case-folding and no trim** beyond what the
    parser's identifier semantics require. Matching is exact-match, as in ADR-0026.
  - The parsed model **retains the original SQL string** alongside the structured
    fields, so nothing the structure omits is unrecoverable.
  - Normalization that *is* applied (e.g. resolving a quoted vs unquoted
    identifier to its canonical text, canonicalising keyword case in type
    names) is **deterministic** and must **not discard security-relevant
    structure**. Anything a later policy might key on — join type, set-operation
    kind (`UNION` vs `UNION ALL`), `DISTINCT`, grouping, ordering, `LIMIT`/`OFFSET`,
    window functions, locking clauses, parameters vs literal constants —
    is **explicitly modelled**, not flattened away. (Comments are not part of the
    parsed structure — PostgreSQL's grammar discards them — but remain recoverable
    from the retained original SQL string.)
- **Alternatives considered:** (a) Lower-case all identifiers for "consistency" —
  rejected; PostgreSQL treats unquoted identifiers case-insensitively but stores
  them folded, while quoted ones are case-sensitive, and a policy that matches on
  a folded name can match the wrong object or miss a quoted one. (b) Drop the
  original SQL once parsed — rejected; it destroys information irreversibly.
  (c) Represent structure as a free-form dict — rejected (see ADR-0029).
- **Reason:** The parsed model is evidence for a security decision; it must be
  faithful (exact identifiers) and complete (no dropped structure), while still
  being deterministic and comparable.
- **Consequences:** Downstream matching is exact and case-sensitive on stored
  identifiers, mirroring the schema layer. The model grows as more structure is
  captured; each addition is additive and typed. Phase 4 deliberately does **not**
  compute any fingerprint over queries (ADR-0027 covers the *schema*); a query
  fingerprint, if wanted, is deferred to the phase that has a reason for it.
