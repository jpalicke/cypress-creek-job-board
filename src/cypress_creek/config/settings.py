# ABOUTME: ProviderSettings, its loopback rule, TOML and environment loading, and API key lookup.
# ABOUTME: Errors are typed and built from field names and rules only, never from submitted values.
import ipaddress
import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

ENV_PREFIX = "CYPRESS_CREEK_"
CONFIG_ENV = "CYPRESS_CREEK_CONFIG"
DEFAULT_CONFIG_PATH = Path("config/provider.toml")

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ConfigError(Exception):
    """The configuration is missing, malformed or unsafe. Never carries a submitted value."""


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class ProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: NonBlank
    model: NonBlank
    base_url: str | None = None
    allow_remote: bool = False
    api_key_env: NonBlank | None = None
    request_timeout_seconds: float = Field(default=120.0, gt=0)
    connect_timeout_seconds: float = Field(default=5.0, gt=0)

    @model_validator(mode="after")
    def _check_base_url(self) -> "ProviderSettings":
        if self.base_url is None:
            return self
        try:
            parts = urlsplit(self.base_url)
            host = parts.hostname
        except ValueError:
            host = None
            parts = urlsplit("")
        if parts.scheme not in ("http", "https") or not host:
            raise ValueError("base_url must be an http or https URL with a host")
        if not self.allow_remote and not _is_loopback(host):
            raise ValueError(
                "base_url is not a loopback address; set allow_remote = true to use a remote host"
            )
        if parts.username is not None or parts.password is not None:
            raise ValueError("base_url must not contain credentials; use api_key_env")
        return self


def _describe(error: ValidationError) -> str:
    """Field names and rule messages only. Pydantic's own text would echo the submitted values."""
    lines = []
    for item in error.errors(include_input=False, include_url=False, include_context=False):
        where = ".".join(str(part) for part in item["loc"])
        lines.append(f"{where}: {item['msg']}" if where else item["msg"])
    return "; ".join(lines)


def parse_settings(data: Mapping[str, Any]) -> ProviderSettings:
    try:
        return ProviderSettings.model_validate(dict(data))
    except ValidationError as error:
        raise ConfigError(f"invalid provider settings: {_describe(error)}") from None


def _read_toml(path: Path, must_exist: bool) -> dict[str, Any]:
    if not path.is_file():
        if must_exist:
            raise ConfigError(f"config file not found: {path}")
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML in {path}: {error}") from None
    except (OSError, UnicodeDecodeError):
        raise ConfigError(f"could not read config file {path} as utf-8 text") from None


def load_settings(
    path: Path | None = None, environ: Mapping[str, str] | None = None
) -> ProviderSettings:
    """Read the TOML file, then let CYPRESS_CREEK_<FIELD> variables override it field by field.

    The file is `path`, else the CYPRESS_CREEK_CONFIG variable, else config/provider.toml. A file
    named explicitly must exist. The default may be absent when the environment sets everything.
    """
    environ = os.environ if environ is None else environ
    named = path if path is not None else (environ.get(CONFIG_ENV, "").strip() or None)
    data = _read_toml(Path(named) if named else DEFAULT_CONFIG_PATH, must_exist=named is not None)
    for name in ProviderSettings.model_fields:
        value = environ.get(ENV_PREFIX + name.upper(), "").strip()
        if value:
            data[name] = value
    return parse_settings(data)


def resolve_api_key(
    settings: ProviderSettings, environ: Mapping[str, str] | None = None
) -> str | None:
    """The key named by `api_key_env`, or None when the backend needs no key."""
    if settings.api_key_env is None:
        return None
    environ = os.environ if environ is None else environ
    key = environ.get(settings.api_key_env, "")
    if not key:
        raise ConfigError(f"environment variable {settings.api_key_env} is not set")
    return key
