# Integration tests

These tests exercise QueryShield against a **real PostgreSQL instance**. As of
**Phase 2** they cover the database adapter: connection + health check, pool
acquire/release, parameterised operations, commit, rollback, clean pool
shutdown, and a connection failure (invalid credentials).

## Running them

They read the connection string from `QUERYSHIELD_TEST_DATABASE_URL`. If it is
**unset, the tests skip** — a plain `pytest` run stays green without a database.
Point the variable at a **disposable** database (never a real one):

```bash
export QUERYSHIELD_TEST_DATABASE_URL=postgresql://user:password@localhost:5432/queryshield_test
pytest -m integration
```

A quick way to get a throwaway PostgreSQL locally:

```bash
docker run --rm -d --name queryshield-pg \
  -e POSTGRES_USER=queryshield_test \
  -e POSTGRES_PASSWORD=queryshield_test \
  -e POSTGRES_DB=queryshield_test \
  -p 5432:5432 postgres:16
```

CI runs these against an ephemeral `postgres:16` **service container** (see
[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)), so the environment
is reproducible and never depends on a developer's personal PostgreSQL install.
No Mistral API key is needed — the LLM is not part of this phase.

## Conventions

- Every test in this tree is marked `@pytest.mark.integration` (registered in
  [`pyproject.toml`](../../pyproject.toml)); module-level `pytestmark` applies it.
- Tests **skip**, not fail, when `QUERYSHIELD_TEST_DATABASE_URL` is absent.
- Run only these: `pytest -m integration`. Exclude them: `pytest -m "not integration"`.
- Any table a test needs is created with a unique name in a fixture and dropped
  afterwards. There is **no** fixed demo schema (no `customers`/`orders`/
  `products`) baked into the test database.
