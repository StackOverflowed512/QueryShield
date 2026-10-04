"""Tests for the configuration system.

Covers the behaviours the Phase 2 spec calls out explicitly: valid config, a
missing required value, an invalid type, an invalid value, environment override,
YAML + precedence, malformed input, and — critically — that secret values never
leak through ``repr``/``str`` or through a :class:`ConfigError` message.

Environment is injected via the ``env=`` argument to :func:`load_config` so these
tests never mutate global process state and run deterministically in any order.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from queryshield.config import QueryShieldConfig, load_config
from queryshield.errors import ConfigError

VALID_URL = "postgresql://appuser:sup3r-s3cret@db.example.com:5432/appdb"
SECRET = "sup3r-s3cret"

pytestmark = pytest.mark.unit


def _env(**extra: str) -> dict[str, str]:
    return {"QUERYSHIELD_DATABASE__URL": VALID_URL, **extra}


def test_valid_config_from_env() -> None:
    config = load_config(env=_env())
    assert isinstance(config, QueryShieldConfig)
    assert config.database.url.get_secret_value() == VALID_URL


def test_safe_defaults_are_applied() -> None:
    config = load_config(env=_env())
    assert config.database.pool_min_size == 1
    assert config.database.pool_max_size == 10
    assert config.database.pool_timeout == 30.0
    assert config.database.connect_timeout == 10.0
    assert config.database.statement_timeout == 30.0
    assert config.database.sslmode is None
    assert config.log_level == "INFO"


def test_env_overrides_defaults_and_coerces_types() -> None:
    config = load_config(
        env=_env(
            QUERYSHIELD_DATABASE__POOL_MAX_SIZE="25",
            QUERYSHIELD_DATABASE__STATEMENT_TIMEOUT="5.5",
            QUERYSHIELD_LOG_LEVEL="debug",
        )
    )
    assert config.database.pool_max_size == 25
    assert config.database.statement_timeout == 5.5
    assert config.log_level == "DEBUG"  # normalised to upper-case


def test_missing_required_url_fails_closed() -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_config(env={})
    assert "database" in str(exc_info.value)


def test_invalid_type_is_rejected() -> None:
    with pytest.raises(ConfigError):
        load_config(env=_env(QUERYSHIELD_DATABASE__POOL_MAX_SIZE="not-an-int"))


def test_invalid_value_pool_sizes_inconsistent() -> None:
    with pytest.raises(ConfigError):
        load_config(
            env=_env(
                QUERYSHIELD_DATABASE__POOL_MIN_SIZE="20",
                QUERYSHIELD_DATABASE__POOL_MAX_SIZE="5",
            )
        )


def test_invalid_value_negative_timeout() -> None:
    with pytest.raises(ConfigError):
        load_config(env=_env(QUERYSHIELD_DATABASE__CONNECT_TIMEOUT="-1"))


def test_invalid_sslmode_is_rejected() -> None:
    with pytest.raises(ConfigError):
        load_config(env=_env(QUERYSHIELD_DATABASE__SSLMODE="bogus"))


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ConfigError):
        load_config(env=_env(QUERYSHIELD_LOG_LEVEL="verbose"))


def test_non_postgresql_url_scheme_is_rejected() -> None:
    with pytest.raises(ConfigError):
        load_config(env={"QUERYSHIELD_DATABASE__URL": "mysql://u:p@h:3306/db"})


def test_unrelated_prefixed_env_vars_are_ignored() -> None:
    # The integration-test DSN uses the QUERYSHIELD_ prefix; loading must not fail
    # just because such a variable is present in the environment.
    config = load_config(env=_env(QUERYSHIELD_TEST_DATABASE_URL="postgresql://x:y@h/z"))
    assert config.database.url.get_secret_value() == VALID_URL


def test_explicit_overrides_beat_environment() -> None:
    config = load_config(
        env=_env(QUERYSHIELD_DATABASE__POOL_MAX_SIZE="25"),
        database={"pool_max_size": 7},
    )
    assert config.database.pool_max_size == 7
    # The URL still comes from the environment (deep-merged, not replaced).
    assert config.database.url.get_secret_value() == VALID_URL


def test_top_level_override_beats_environment() -> None:
    config = load_config(env=_env(QUERYSHIELD_LOG_LEVEL="INFO"), log_level="ERROR")
    assert config.log_level == "ERROR"


def test_yaml_file_is_read_and_below_env(tmp_path: Path) -> None:
    yaml_file = tmp_path / "queryshield.yaml"
    yaml_file.write_text(
        f"log_level: WARNING\ndatabase:\n  url: {VALID_URL}\n  pool_max_size: 3\n",
        encoding="utf-8",
    )
    # YAML supplies everything; env overrides one value (env > yaml).
    config = load_config(
        config_file=yaml_file,
        env={"QUERYSHIELD_DATABASE__POOL_MAX_SIZE": "9"},
    )
    assert config.log_level == "WARNING"  # from YAML
    assert config.database.pool_max_size == 9  # env beats YAML
    assert config.database.url.get_secret_value() == VALID_URL


def test_yaml_config_file_env_var_is_honoured(tmp_path: Path) -> None:
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(f"database:\n  url: {VALID_URL}\n", encoding="utf-8")
    config = load_config(env={"QUERYSHIELD_CONFIG_FILE": str(yaml_file)})
    assert config.database.url.get_secret_value() == VALID_URL


def test_yaml_env_interpolation(tmp_path: Path) -> None:
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("database:\n  url: ${DB_URL}\n", encoding="utf-8")
    config = load_config(config_file=yaml_file, env={"DB_URL": VALID_URL})
    assert config.database.url.get_secret_value() == VALID_URL


def test_yaml_undefined_interpolation_fails_closed(tmp_path: Path) -> None:
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("database:\n  url: ${MISSING_VAR}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(config_file=yaml_file, env={})


def test_malformed_yaml_is_rejected(tmp_path: Path) -> None:
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("database: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(config_file=yaml_file, env={})


def test_missing_config_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(config_file=tmp_path / "does-not-exist.yaml", env={})


def test_secret_not_exposed_in_repr_or_str() -> None:
    config = load_config(env=_env())
    assert SECRET not in repr(config)
    assert SECRET not in str(config)
    assert SECRET not in repr(config.database)
    assert SECRET not in str(config.database)


def test_secret_not_exposed_in_validation_error() -> None:
    # A *different* field fails validation while the (secret-bearing) URL is
    # valid; the error message must not echo the URL's password.
    with pytest.raises(ConfigError) as exc_info:
        load_config(env=_env(QUERYSHIELD_DATABASE__POOL_MAX_SIZE="not-an-int"))
    assert SECRET not in str(exc_info.value)


def test_secret_value_is_still_accessible() -> None:
    config = load_config(env=_env())
    assert config.database.url.get_secret_value() == VALID_URL
