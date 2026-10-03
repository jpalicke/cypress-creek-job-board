# ABOUTME: Tests provider settings: the loopback rule, file and environment loading, key handling.
# ABOUTME: Every failure is a typed ConfigError that never contains an API key value.
from pathlib import Path

import pytest

from cypress_creek.config import (
    CONFIG_ENV,
    ConfigError,
    ProviderSettings,
    load_settings,
    parse_settings,
    resolve_api_key,
)

KEY = "sk-test-SECRET-1234567890"
BASE = {"provider": "ollama", "model": "llama3.1"}


def _settings(**extra: object) -> ProviderSettings:
    return parse_settings({**BASE, **extra})


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434/v1",
        "http://[::1]:11434",
        "http://127.0.0.2:1234",
        "https://LOCALHOST/v1",
    ],
)
def test_loopback_urls_are_accepted(url: str) -> None:
    assert _settings(base_url=url).base_url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "http://10.0.0.5:11434",
        "http://localhost.evil.com",
        "http://127.0.0.1.evil.com",
        "http://localhost@evil.com",
        "http://[::2]:11434",
    ],
)
def test_a_non_loopback_url_is_rejected_without_allow_remote(url: str) -> None:
    with pytest.raises(ConfigError, match="allow_remote"):
        _settings(base_url=url)


def test_allow_remote_accepts_a_remote_url() -> None:
    settings = _settings(base_url="https://api.openai.com/v1", allow_remote=True)
    assert settings.base_url == "https://api.openai.com/v1"


@pytest.mark.parametrize(
    "url", ["ftp://localhost", "localhost:11434", "http://", "not a url", "http://[::1"]
)
def test_a_malformed_or_non_http_url_is_rejected_even_with_allow_remote(url: str) -> None:
    with pytest.raises(ConfigError, match="base_url"):
        _settings(base_url=url, allow_remote=True)


def test_a_rejected_url_never_echoes_its_credentials() -> None:
    with pytest.raises(ConfigError) as caught:
        _settings(base_url=f"https://user:{KEY}@evil.example/v1")
    assert KEY not in str(caught.value)


def test_defaults_are_local_and_safe() -> None:
    settings = _settings()
    assert settings.base_url is None
    assert settings.allow_remote is False
    assert settings.api_key_env is None
    assert settings.request_timeout_seconds > 0
    assert settings.connect_timeout_seconds > 0
    assert settings.context_tokens == 32768


@pytest.mark.parametrize(
    "bad",
    [
        {"provider": ""},
        {"model": " "},
        {"request_timeout_seconds": 0},
        {"connect_timeout_seconds": -1},
        {"context_tokens": 0},
        {"surprise": "field"},
    ],
)
def test_bad_values_and_unknown_fields_are_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(ConfigError):
        parse_settings({**BASE, **bad})


def test_missing_required_fields_name_the_field() -> None:
    with pytest.raises(ConfigError, match="provider"):
        parse_settings({"model": "x"})


def test_a_toml_file_is_loaded(tmp_path: Path) -> None:
    path = tmp_path / "provider.toml"
    path.write_text(
        'provider = "ollama"\nmodel = "llama3.1"\nbase_url = "http://localhost:11434"\n',
        encoding="utf-8",
    )
    settings = load_settings(path, environ={})
    assert settings.provider == "ollama"
    assert settings.base_url == "http://localhost:11434"


def test_environment_variables_override_the_file(tmp_path: Path) -> None:
    path = tmp_path / "provider.toml"
    path.write_text('provider = "ollama"\nmodel = "llama3.1"\n', encoding="utf-8")
    environ = {"CYPRESS_CREEK_MODEL": "qwen3", "CYPRESS_CREEK_REQUEST_TIMEOUT_SECONDS": "30"}
    settings = load_settings(path, environ=environ)
    assert settings.model == "qwen3"
    assert settings.request_timeout_seconds == 30


def test_environment_alone_can_configure_a_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    environ = {
        "CYPRESS_CREEK_PROVIDER": "ollama",
        "CYPRESS_CREEK_MODEL": "llama3.1",
        "CYPRESS_CREEK_ALLOW_REMOTE": "true",
    }
    assert load_settings(environ=environ).allow_remote is True


def test_a_blank_environment_value_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "provider.toml"
    path.write_text('provider = "ollama"\nmodel = "llama3.1"\n', encoding="utf-8")
    assert load_settings(path, environ={"CYPRESS_CREEK_MODEL": "  "}).model == "llama3.1"


def test_the_config_path_comes_from_the_environment(tmp_path: Path) -> None:
    path = tmp_path / "elsewhere.toml"
    path.write_text('provider = "ollama"\nmodel = "m"\n', encoding="utf-8")
    assert load_settings(environ={CONFIG_ENV: str(path)}).model == "m"


def test_a_missing_explicit_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "typo.toml", environ={})


def test_a_missing_default_file_leaves_the_environment_to_decide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="provider"):
        load_settings(environ={})


def test_invalid_toml_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "provider.toml"
    path.write_text("provider = = oops", encoding="utf-8")
    with pytest.raises(ConfigError, match="TOML"):
        load_settings(path, environ={})


def test_an_unreadable_encoding_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "provider.toml"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ConfigError):
        load_settings(path, environ={})


def test_the_api_key_is_read_from_the_named_environment_variable() -> None:
    settings = _settings(api_key_env="OPENAI_API_KEY")
    assert resolve_api_key(settings, environ={"OPENAI_API_KEY": KEY}) == KEY


def test_no_key_variable_means_no_key() -> None:
    assert resolve_api_key(_settings(), environ={}) is None


def test_a_missing_key_names_the_variable_but_never_a_value() -> None:
    settings = _settings(api_key_env="OPENAI_API_KEY")
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        resolve_api_key(settings, environ={"OTHER": KEY})


def test_settings_hold_the_variable_name_so_no_key_appears_in_their_repr() -> None:
    settings = _settings(api_key_env="OPENAI_API_KEY")
    resolve_api_key(settings, environ={"OPENAI_API_KEY": KEY})
    assert KEY not in repr(settings)
    assert KEY not in settings.model_dump_json()


def test_credentials_in_the_url_are_rejected_even_with_allow_remote() -> None:
    with pytest.raises(ConfigError, match="credentials") as caught:
        _settings(base_url=f"https://user:{KEY}@api.example.com/v1", allow_remote=True)
    assert KEY not in str(caught.value)


def test_budget_limits_are_optional_and_validated() -> None:
    assert _settings().max_input_tokens is None
    assert _settings(max_usd=0.5).max_usd == 0.5
    with pytest.raises(ConfigError, match="max_requests"):
        _settings(max_requests=0)


def test_budget_limits_can_come_from_the_environment() -> None:
    environ = {
        **{"CYPRESS_CREEK_PROVIDER": "ollama", "CYPRESS_CREEK_MODEL": "m"},
        "CYPRESS_CREEK_MAX_OUTPUT_TOKENS": "777",
    }
    assert load_settings(environ=environ).max_output_tokens == 777
