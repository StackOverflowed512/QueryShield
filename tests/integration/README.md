# Integration tests

This directory is intentionally (almost) empty in **Phase 1**.

Integration tests exercise QueryShield against **real external services** —
most importantly a real PostgreSQL instance (and, later, a real cache backend
and the Mistral API). None of that functionality exists yet, so there are no
integration tests to run.

## Conventions (for when these tests arrive in Phase 2+)

- Mark every test in this tree with `@pytest.mark.integration` (the marker is
  registered in [`pyproject.toml`](../../pyproject.toml)).
- Integration tests must **skip**, not fail, when their required service is not
  configured/available (e.g. no `DATABASE_URL`). A developer running `pytest`
  with no database must still get a green, meaningful run.
- Run only these tests with: `pytest -m integration`.
- Exclude them with: `pytest -m "not integration"`.

Keeping this placeholder documents the intended structure without creating fake
tests that assert nothing.
