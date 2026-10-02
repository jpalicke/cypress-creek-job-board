# ABOUTME: Turns settings into a Provider by looking the provider name up in a registry of builders.
# ABOUTME: Adapters register themselves in later cards, and an unknown name is a typed config error.
from collections.abc import Callable

from cypress_creek.config import ConfigError, ProviderSettings
from cypress_creek.providers.base import Provider

Builder = Callable[[ProviderSettings], Provider]


class UnknownProvider(ConfigError):
    def __init__(self, provider: str, known: list[str]) -> None:
        listing = ", ".join(known) if known else "none registered"
        super().__init__(f"unknown provider {provider!r}; known: {listing}")
        self.provider = provider
        self.known = known


class ProviderRegistry:
    def __init__(self) -> None:
        self._builders: dict[str, Builder] = {}

    def register(self, name: str, builder: Builder) -> None:
        if name in self._builders:
            raise ValueError(f"provider {name!r} is already registered")
        self._builders[name] = builder

    def names(self) -> list[str]:
        return sorted(self._builders)

    def builder(self, name: str) -> Builder:
        try:
            return self._builders[name]
        except KeyError:
            raise UnknownProvider(name, self.names()) from None


REGISTRY = ProviderRegistry()


def get_provider(settings: ProviderSettings, registry: ProviderRegistry = REGISTRY) -> Provider:
    return registry.builder(settings.provider)(settings)
