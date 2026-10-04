"""Strongly typed, validated configuration for QueryShield.

This module is the Phase 2 configuration foundation: a small, validated settings
model plus a :func:`load_config` loader with a deterministic, documented
precedence. Only the sections the current foundation needs (``database`` plus a
couple of application-level settings) are modelled. Future sections — ``llm``,
``security``, ``policy``, ``cache``, ``audit``, ``analytics`` — are added by the
phases that introduce them. See ADR-0016 (library choice) and ADR-0017
(precedence + env-var scheme).

Precedence (highest wins)::

    explicit keyword overrides to load_config(...)
      > process environment variables (prefix QUERYSHIELD_)
      > a YAML config file (path from arg or QUERYSHIELD_CONFIG_FILE)
      > built-in safe defaults

Secrets (the database URL today, API keys later) are stored as
:class:`pydantic.SecretStr`, so they are not revealed by ``repr``/``str``/logging
and cannot leak through a :class:`~queryshield.errors.ConfigError` message (the
loader formats validation failures from field locations and messages only, never
from input values).

Nothing here is deployment-specific: host, port, credentials, database name,
pool sizes, and timeouts all come from configuration, never hard-coded. The only
built-in values are *safe, overridable defaults* for non-secret tunables.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlparse

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from queryshield.errors import ConfigError

#: Prefix every QueryShield environment variable must carry (so they never
#: collide with a host application's environment).
ENV_PREFIX = "QUERYSHIELD_"
#: Separator for nested keys in env vars, e.g. ``QUERYSHIELD_DATABASE__URL``.
ENV_NESTED_DELIMITER = "__"
#: Env var naming a YAML config file. Resolved by the loader, not a config field.
CONFIG_FILE_ENV = "QUERYSHIELD_CONFIG_FILE"

_VALID_DB_SCHEMES = frozenset({"postgres", "postgresql"})
_VALID_SSLMODES = frozenset(
    {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
)
_VALID_LOG_LEVELS = frozenset(
    {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
)
_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


class DatabaseConfig(BaseModel):
    """PostgreSQL connection and pool configuration.

    ``url`` is a standard libpq/PostgreSQL connection URL, e.g.
    ``postgresql://user:password@host:5432/dbname``. It is required and secret.
    Every other field has a safe, overridable default — none is deployment
    specific. ``extra="forbid"`` makes a typo in this security-sensitive section
    a hard error rather than a silently-ignored setting.
    """

    model_config = ConfigDict(extra="forbid")

    url: SecretStr = Field(
        description="PostgreSQL connection URL (libpq DSN). Required; secret.",
    )
    pool_min_size: int = Field(
        default=1, ge=0, description="Minimum number of pooled connections."
    )
    pool_max_size: int = Field(
        default=10, ge=1, description="Maximum number of pooled connections."
    )
    pool_timeout: float = Field(
        default=30.0,
        gt=0,
        description="Seconds to wait for a connection from the pool.",
    )
    connect_timeout: float = Field(
        default=10.0,
        gt=0,
        description="Seconds to wait when establishing a new connection.",
    )
    statement_timeout: float | None = Field(
        default=30.0,
        gt=0,
        description=(
            "PostgreSQL statement_timeout, in seconds, applied to every "
            "connection. None disables the per-statement timeout."
        ),
    )
    sslmode: str | None = Field(
        default=None,
        description=(
            "libpq sslmode (disable/allow/prefer/require/verify-ca/verify-full). "
            "None leaves the URL's own value (or libpq's default) in place; "
            "production deployments should set 'require' or stronger."
        ),
    )

    @field_validator("sslmode")
    @classmethod
    def _validate_sslmode(cls, value: str | None) -> str | None:
        if value is not None and value not in _VALID_SSLMODES:
            raise ValueError(f"sslmode must be one of {sorted(_VALID_SSLMODES)}")
        return value

    @model_validator(mode="after")
    def _validate_model(self) -> Self:
        if self.pool_max_size < self.pool_min_size:
            raise ValueError(
                "pool_max_size must be >= pool_min_size "
                f"(got max={self.pool_max_size}, min={self.pool_min_size})"
            )
        raw = self.url.get_secret_value()
        if not raw:
            raise ValueError("database url must not be empty")
        scheme = urlparse(raw).scheme.lower()
        if scheme not in _VALID_DB_SCHEMES:
            raise ValueError(
                "database url must be a PostgreSQL URL (scheme one of "
                f"{sorted(_VALID_DB_SCHEMES)})"
            )
        return self


class QueryShieldConfig(BaseModel):
    """Top-level, validated QueryShield configuration.

    Phase 2 models the ``database`` section and an application ``log_level``.
    Unknown top-level keys are ignored (``extra="ignore"``) so QueryShield can
    coexist with other ``QUERYSHIELD_``-prefixed environment variables — for
    example the integration-test DSN — without failing to load.
    """

    model_config = ConfigDict(extra="ignore")

    database: DatabaseConfig
    log_level: str = Field(
        default="INFO", description="Root logging level for the 'queryshield' logger."
    )

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in _VALID_LOG_LEVELS:
            raise ValueError(f"log_level must be one of {sorted(_VALID_LOG_LEVELS)}")
        return level


def load_config(
    *,
    config_file: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    **overrides: Any,
) -> QueryShieldConfig:
    """Load and validate configuration from all sources, highest priority last.

    Sources are merged deepest-to-shallowest so that, for any key, the
    highest-priority source that provides it wins:

    1. built-in safe defaults (the model's field defaults),
    2. a YAML file (``config_file`` arg, else ``QUERYSHIELD_CONFIG_FILE``),
    3. ``QUERYSHIELD_``-prefixed environment variables,
    4. explicit keyword ``overrides`` passed to this function.

    Args:
        config_file: Optional path to a YAML config file. Overrides the
            ``QUERYSHIELD_CONFIG_FILE`` environment variable when given.
        env: Environment mapping to read (defaults to ``os.environ``). Injectable
            so tests need not mutate global process state.
        **overrides: Highest-priority values, e.g.
            ``load_config(log_level="DEBUG")`` or
            ``load_config(database={"pool_max_size": 20})``.

    Returns:
        A validated :class:`QueryShieldConfig`.

    Raises:
        ConfigError: if any source is malformed or the merged configuration
            fails validation. The message never contains secret values.
    """
    environ: Mapping[str, str] = os.environ if env is None else env

    layers: list[Mapping[str, Any]] = []
    yaml_path = _resolve_config_file(config_file, environ)
    if yaml_path is not None:
        layers.append(_load_yaml_file(yaml_path, environ))
    layers.append(_env_to_mapping(environ))
    if overrides:
        layers.append(overrides)

    merged = _deep_merge(layers)
    try:
        return QueryShieldConfig.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from exc


def _resolve_config_file(
    config_file: str | os.PathLike[str] | None, environ: Mapping[str, str]
) -> Path | None:
    if config_file is not None:
        return Path(config_file)
    env_path = environ.get(CONFIG_FILE_ENV)
    if env_path:
        return Path(env_path)
    return None


def _load_yaml_file(path: Path, environ: Mapping[str, str]) -> Mapping[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not read config file '{path}': {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file '{path}' is not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"config file '{path}' must contain a mapping at the top level"
        )
    expanded = _expand_env_refs(data, environ, path)
    # ``data`` is a dict, so expansion yields a dict; narrow for the type checker.
    assert isinstance(expanded, dict)
    return expanded


def _expand_env_refs(obj: Any, environ: Mapping[str, str], path: Path) -> Any:
    """Recursively replace ``${VAR}`` references in YAML string values.

    This keeps secrets out of config files: the file can say
    ``url: ${QUERYSHIELD_DATABASE_URL}`` and the real value comes from the
    environment. An undefined reference is a fail-closed error, never an empty
    string.
    """
    if isinstance(obj, dict):
        return {
            key: _expand_env_refs(value, environ, path) for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [_expand_env_refs(item, environ, path) for item in obj]
    if isinstance(obj, str):

        def _replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in environ:
                raise ConfigError(
                    f"config file '{path}' references undefined environment "
                    f"variable '{name}'"
                )
            return environ[name]

        return _ENV_VAR_RE.sub(_replace, obj)
    return obj


def _env_to_mapping(environ: Mapping[str, str]) -> dict[str, Any]:
    """Project ``QUERYSHIELD_``-prefixed env vars into a nested mapping.

    ``QUERYSHIELD_DATABASE__POOL_MAX_SIZE=25`` becomes
    ``{"database": {"pool_max_size": "25"}}``. Values stay strings; pydantic
    performs typed coercion during validation. The control variable
    ``QUERYSHIELD_CONFIG_FILE`` is excluded (it selects the YAML file, it is not
    a config field).
    """
    result: dict[str, Any] = {}
    for key, value in environ.items():
        if not key.startswith(ENV_PREFIX) or key == CONFIG_FILE_ENV:
            continue
        stripped = key[len(ENV_PREFIX) :]
        if not stripped:
            continue
        parts = [part.lower() for part in stripped.split(ENV_NESTED_DELIMITER)]
        if any(not part for part in parts):
            # Malformed, e.g. a trailing delimiter: QUERYSHIELD_DATABASE__
            continue
        _assign_nested(result, parts, value)
    return result


def _assign_nested(root: dict[str, Any], parts: Sequence[str], value: Any) -> None:
    node = root
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


def _deep_merge(layers: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for layer in layers:
        _merge_into(merged, layer)
    return merged


def _merge_into(destination: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        existing = destination.get(key)
        if isinstance(value, Mapping):
            target = existing if isinstance(existing, dict) else {}
            _merge_into(target, value)
            destination[key] = target
        else:
            destination[key] = value


def _format_validation_error(exc: ValidationError) -> str:
    """Render a validation error without echoing any input values.

    Only the field location and the pydantic message are included, so a secret
    carried in (for example) the database URL can never leak into the error text
    even when a *different* field is what failed validation.
    """
    lines = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(part) for part in error["loc"]) or "(root)"
        lines.append(f"  - {location}: {error['msg']}")
    body = "\n".join(lines)
    return f"invalid QueryShield configuration:\n{body}"
