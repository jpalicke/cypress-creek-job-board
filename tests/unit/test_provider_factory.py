# ABOUTME: Tests the provider factory: unknown backends are a typed config error, builders run.
# ABOUTME: Builders here raise a marker so the tests prove dispatch without faking a provider.
import pytest

from cypress_creek.config import ConfigError, ProviderSettings, parse_settings
from cypress_creek.providers import Provider, ProviderRegistry, UnknownProvider, get_provider


class Dispatched(Exception):
    def __init__(self, settings: ProviderSettings) -> None:
        super().__init__("builder was called")
        self.settings = settings


def _builder(settings: ProviderSettings) -> Provider:
    raise Dispatched(settings)


def _settings(provider: str) -> ProviderSettings:
    return parse_settings({"provider": provider, "model": "m"})


def test_an_unknown_backend_is_a_typed_config_error() -> None:
    registry = ProviderRegistry()
    registry.register("ollama", _builder)
    with pytest.raises(UnknownProvider) as caught:
        get_provider(_settings("nope"), registry=registry)
    assert isinstance(caught.value, ConfigError)
    assert caught.value.provider == "nope"
    assert caught.value.known == ["ollama"]
    assert "ollama" in str(caught.value)


def test_an_empty_registry_says_so() -> None:
    with pytest.raises(UnknownProvider, match="none registered"):
        get_provider(_settings("ollama"), registry=ProviderRegistry())


def test_the_registered_builder_receives_the_settings() -> None:
    registry = ProviderRegistry()
    registry.register("ollama", _builder)
    settings = _settings("ollama")
    with pytest.raises(Dispatched) as caught:
        get_provider(settings, registry=registry)
    assert caught.value.settings is settings


def test_a_name_cannot_be_registered_twice() -> None:
    registry = ProviderRegistry()
    registry.register("ollama", _builder)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("ollama", _builder)


def test_known_names_are_sorted() -> None:
    registry = ProviderRegistry()
    registry.register("b", _builder)
    registry.register("a", _builder)
    assert registry.names() == ["a", "b"]
