# ABOUTME: Tests that a loopback openai_compatible adapter reads the context a server loaded.
# ABOUTME: The listing is LM Studio's own, served by a real loopback server with recorded fields.
import json

import pytest
from http_support import http_server

from cypress_creek.config import ConfigError, parse_settings
from cypress_creek.providers.openai_compatible import OpenAICompatibleProvider

LISTING = "/api/v0/models"


def _listing(model: str = "gemma-4-e4b", loaded: object = 16384, state: str = "loaded") -> bytes:
    """The shape LM Studio 0.4.17 returned, recorded by Joe P on 2026-10-30."""
    return json.dumps(
        {
            "data": [
                {
                    "id": model,
                    "object": "model",
                    "type": "vlm",
                    "state": state,
                    "max_context_length": 131072,
                    "loaded_context_length": loaded,
                },
                {
                    "id": "text-embedding-nomic-embed-text-v1.5",
                    "object": "model",
                    "type": "embeddings",
                    "state": "not-loaded",
                    "max_context_length": 2048,
                },
            ],
            "object": "list",
        }
    ).encode()


def _provider(port: int, **extra: object) -> OpenAICompatibleProvider:
    values: dict[str, object] = {
        "provider": "openai_compatible",
        "model": "gemma-4-e4b",
        "base_url": f"http://127.0.0.1:{port}/v1",
    }
    values.update(extra)
    return OpenAICompatibleProvider(parse_settings(values), environ={})


def test_the_loaded_context_is_used_when_the_config_does_not_set_one() -> None:
    with http_server(json_routes={LISTING: _listing(loaded=16384)}) as (port, requests):
        provider = _provider(port)
    assert provider.capabilities.context_tokens == 16384
    assert [path for path, _ in requests.received] == [LISTING]


def test_a_configured_context_at_or_below_the_loaded_one_wins() -> None:
    with http_server(json_routes={LISTING: _listing(loaded=16384)}) as (port, _):
        provider = _provider(port, context_tokens=4096)
    assert provider.capabilities.context_tokens == 4096


def test_a_configured_context_above_the_loaded_one_is_refused_loudly() -> None:
    with (
        http_server(json_routes={LISTING: _listing(loaded=8192)}) as (port, _),
        pytest.raises(ConfigError, match="8192") as caught,
    ):
        _provider(port, context_tokens=16384)
    assert "16384" in str(caught.value)


def test_a_server_without_the_listing_falls_back_to_the_config() -> None:
    with http_server(json_routes={}) as (port, _):
        explicit = _provider(port, context_tokens=4096)
        default = _provider(port)
    assert explicit.capabilities.context_tokens == 4096
    assert default.capabilities.context_tokens == 8192


def test_a_listing_that_does_not_load_the_model_falls_back() -> None:
    with http_server(json_routes={LISTING: _listing(model="another-model")}) as (port, _):
        other_model = _provider(port)
    with http_server(json_routes={LISTING: _listing(state="not-loaded")}) as (port, _):
        not_loaded = _provider(port)
    assert other_model.capabilities.context_tokens == 8192
    assert not_loaded.capabilities.context_tokens == 8192


@pytest.mark.parametrize("loaded", ["16384", -5, 0, True, 1.5, None])
def test_a_loaded_value_that_is_not_a_positive_integer_is_ignored(loaded: object) -> None:
    with http_server(json_routes={LISTING: _listing(loaded=loaded)}) as (port, _):
        provider = _provider(port, context_tokens=4096)
    assert provider.capabilities.context_tokens == 4096


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"data": "x"}', b'{"data": [1, null]}'])
def test_a_listing_that_is_not_the_expected_shape_is_ignored(body: bytes) -> None:
    with http_server(json_routes={LISTING: body}) as (port, _):
        provider = _provider(port)
    assert provider.capabilities.context_tokens == 8192


def test_a_loopback_backend_reports_a_strict_schema() -> None:
    # LM Studio 0.4.17 with one model enforced an enum schema against a prompt that asked for
    # a forbidden value (recorded by Joe P on 2026-10-30), so the pipeline can rely on it.
    with http_server(json_routes={}) as (port, _):
        provider = _provider(port)
    assert provider.capabilities.strict_schema is True
