# ABOUTME: Exercises bounded HTTP decoding and transport coordinates with hostile inputs.
# ABOUTME: Pure byte streams verify limits without replacing network implementations.
import ast
import gzip
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from cypress_creek.ingest.safe_http import (
    FetchLimits,
    SafeHttpError,
    _decode,
    _parse_worker_result,
    _request_coordinates,
)
from cypress_creek.ingest.url_guard import ValidatedTarget

_HTTP_CLIENTS = {"httpx", "requests", "aiohttp", "httpcore", "urllib.request", "http.client"}


def _is_http_client(module: str) -> bool:
    return any(module == client or module.startswith(f"{client}.") for client in _HTTP_CLIENTS)


def _forbidden_http_imports(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(
            _is_http_client(alias.name) for alias in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and any(
            _is_http_client(f"{node.module}.{alias.name}")
            for alias in node.names
            if node.module is not None
        ):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and _is_http_client(node.module)
        ):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "__import__"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and _is_http_client(node.args[0].value)
        ):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "importlib"
            and node.func.attr == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and _is_http_client(node.args[0].value)
        ):
            return True
    return False


@pytest.mark.parametrize(
    "source",
    [
        "import httpx",
        "import requests.sessions",
        "from aiohttp import ClientSession",
        "from urllib import request",
        "from http import client",
        "importlib.import_module('httpcore')",
        "__import__('httpx')",
    ],
)
def test_http_import_audit_detects_client_forms(source: str) -> None:
    assert _forbidden_http_imports(source)


def test_http_import_audit_allows_url_parsing() -> None:
    assert not _forbidden_http_imports("from urllib.parse import urlsplit")


@pytest.mark.parametrize(
    "field",
    ["max_wire_bytes", "max_decoded_bytes", "max_ratio", "connect_timeout", "total_timeout"],
)
@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_limits_must_be_positive_finite(field: str, value: float) -> None:
    with pytest.raises(ValueError):
        FetchLimits(**{field: value})  # type: ignore[arg-type]


def test_limits_are_immutable() -> None:
    limits = FetchLimits()
    with pytest.raises(FrozenInstanceError):
        limits.total_timeout = 1  # type: ignore[misc]


def test_byte_limits_reject_fractional_values() -> None:
    with pytest.raises(ValueError, match="integers"):
        FetchLimits(max_wire_bytes=1.5)  # type: ignore[arg-type]


def test_content_allow_list_cannot_be_empty() -> None:
    with pytest.raises(ValueError, match="nonempty"):
        FetchLimits(content_types=frozenset())


def test_coordinates_pin_ip_and_preserve_hostname_and_escapes() -> None:
    target = ValidatedTarget("https", "example.org", "1.1.1.1", 443)
    url, host = _request_coordinates("https://example.org/a%0d%0a?q=%2f#ignored", target)
    assert url == "https://1.1.1.1:443/a%0d%0a?q=%2f"
    assert host == "example.org"


def test_coordinates_bracket_ipv6_and_include_nondefault_port() -> None:
    target = ValidatedTarget("http", "2606:4700:4700::1111", "2606:4700:4700::1111", 443)
    assert _request_coordinates("http://[2606:4700:4700::1111]:443", target) == (
        "http://[2606:4700:4700::1111]:443/",
        "[2606:4700:4700::1111]:443",
    )


@pytest.mark.parametrize("encoding", ["", "identity", "gzip"])
def test_decode_preserves_body(encoding: str) -> None:
    body = b"a short document"
    wire = gzip.compress(body) if encoding == "gzip" else body
    assert _decode(iter([wire[:5], wire[5:]]), encoding, FetchLimits()) == body


@pytest.mark.parametrize(
    "encoding,wire,reason",
    [
        ("br", b"body", "invalid_encoding"),
        ("gzip", b"not gzip", "invalid_encoding"),
        ("gzip", gzip.compress(b"body")[:-2], "invalid_encoding"),
        ("gzip", gzip.compress(b"body") + gzip.compress(b"extra"), "invalid_encoding"),
        ("gzip", gzip.compress(b"body") + b"junk", "invalid_encoding"),
    ],
)
def test_decode_rejects_malformed_encoding(encoding: str, wire: bytes, reason: str) -> None:
    with pytest.raises(SafeHttpError) as caught:
        _decode(iter([wire]), encoding, FetchLimits())
    assert caught.value.reason_code == reason
    assert wire.decode(errors="replace") not in str(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        None,
        {"error": "safe_http", "reason": "unrecognized"},
        {"error": "url_guard", "reason": "unrecognized"},
        {"url": 1, "status": 200, "content_type": "text/plain", "body": ""},
        {"url": "https://example.org", "status": True, "content_type": "text/plain", "body": ""},
        {"url": "https://example.org", "status": 200, "content_type": "text/plain", "body": "!"},
    ],
)
def test_worker_result_rejects_invalid_schema(payload: object) -> None:
    with pytest.raises(SafeHttpError) as caught:
        _parse_worker_result(json.dumps(payload).encode(), FetchLimits())
    assert caught.value.reason_code == "network_error"


@pytest.mark.parametrize(
    "limits,wire,encoding,reason",
    [
        (FetchLimits(max_wire_bytes=3), b"1234", "", "too_large"),
        (FetchLimits(max_decoded_bytes=3), b"1234", "", "too_large"),
        (FetchLimits(max_decoded_bytes=3), gzip.compress(b"1234"), "gzip", "too_large"),
        (FetchLimits(max_ratio=2), gzip.compress(b"a" * 1000), "gzip", "decompression_ratio"),
    ],
)
def test_decode_enforces_limits(
    limits: FetchLimits, wire: bytes, encoding: str, reason: str
) -> None:
    with pytest.raises(SafeHttpError) as caught:
        _decode(iter([wire]), encoding, limits)
    assert caught.value.reason_code == reason


def test_http_client_imports_are_restricted() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "cypress_creek"
    allowed = {
        root / "ingest" / "safe_http.py",
        root / "providers" / "ollama.py",
    }
    violations = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if path not in allowed and _forbidden_http_imports(path.read_text(encoding="utf-8"))
    ]
    assert violations == []
