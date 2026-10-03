# ABOUTME: Fetches public HTTP resources through pinned connections and bounded decoding.
# ABOUTME: A disposable worker bounds DNS, redirects, headers and body time together.
import base64
import json
import math
import subprocess
import sys
import time
import zlib
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from typing import cast, get_args
from urllib.parse import urljoin, urlsplit

import httpx

from cypress_creek.ingest.url_guard import ReasonCode, UrlGuardError, ValidatedTarget


@dataclass(frozen=True)
class FetchLimits:
    """Final-body size ceilings and a deadline shared by DNS and every redirect."""

    max_wire_bytes: int = 10_485_760
    max_decoded_bytes: int = 10_485_760
    max_ratio: float = 100.0
    connect_timeout: float = 5.0
    total_timeout: float = 30.0
    content_types: frozenset[str] = frozenset(
        {"text/html", "application/xhtml+xml", "text/plain", "application/pdf"}
    )

    def __post_init__(self) -> None:
        for value in (
            self.max_wire_bytes,
            self.max_decoded_bytes,
            self.max_ratio,
            self.connect_timeout,
            self.total_timeout,
        ):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError("Fetch limits must be positive and finite")
        if not isinstance(self.max_wire_bytes, int) or not isinstance(self.max_decoded_bytes, int):
            raise ValueError("Byte limits must be integers")
        if not isinstance(self.content_types, frozenset) or not self.content_types:
            raise ValueError("Content types must be a nonempty frozenset")


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status: int
    content_type: str
    body: bytes


class SafeHttpError(Exception):
    """A stable failure reason without remote response or connection details."""

    def __init__(self, reason_code: str) -> None:
        super().__init__("Resource could not be fetched safely")
        self.reason_code = reason_code


def _request_coordinates(url: str, target: ValidatedTarget) -> tuple[str, str]:
    parsed = urlsplit(url)
    ip = f"[{target.ip}]" if ":" in target.ip else target.ip
    host = f"[{target.host}]" if ":" in target.host else target.host
    if target.port != (443 if target.scheme == "https" else 80):
        host = f"{host}:{target.port}"
    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{target.scheme}://{ip}:{target.port}{path}{query}", host


def _decode(chunks: Iterable[bytes], encoding: str, limits: FetchLimits) -> bytes:
    if encoding not in {"", "identity", "gzip"}:
        raise SafeHttpError("invalid_encoding")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
    body = bytearray()
    wire_size = 0
    for chunk in chunks:
        wire_size += len(chunk)
        if wire_size > limits.max_wire_bytes:
            raise SafeHttpError("too_large")
        if decoder is None:
            decoded = chunk
        else:
            try:
                decoded = decoder.decompress(chunk, limits.max_decoded_bytes - len(body) + 1)
            except zlib.error:
                raise SafeHttpError("invalid_encoding") from None
            if decoder.unused_data:
                raise SafeHttpError("invalid_encoding")
        body.extend(decoded)
        if len(body) > limits.max_decoded_bytes:
            raise SafeHttpError("too_large")
        if len(body) > wire_size * limits.max_ratio:
            raise SafeHttpError("decompression_ratio")
    if decoder is not None and not decoder.eof:
        raise SafeHttpError("invalid_encoding")
    return bytes(body)


def _fetch(
    url: str, limits: FetchLimits, *, resolve: Callable[[str], ValidatedTarget]
) -> FetchResponse:
    for redirects in range(4):
        target = resolve(url)
        wire_url, host = _request_coordinates(url, target)
        try:
            with (
                httpx.Client(
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(limits.total_timeout, connect=limits.connect_timeout),
                ) as client,
                client.stream(
                    "GET",
                    wire_url,
                    headers={"Host": host, "Accept-Encoding": "gzip"},
                    extensions={"sni_hostname": target.host},
                ) as response,
            ):
                if response.status_code in {301, 302, 303, 307, 308}:
                    if redirects == 3:
                        raise SafeHttpError("too_many_redirects")
                    location = response.headers.get("location", "")
                    if not location or any(
                        char.isspace() or ord(char) < 32 or ord(char) == 127 or char == "\\"
                        for char in location
                    ):
                        raise SafeHttpError("invalid_redirect")
                    try:
                        url = urljoin(url, location)
                    except ValueError:
                        raise SafeHttpError("invalid_redirect") from None
                    continue
                if not 200 <= response.status_code < 300:
                    raise SafeHttpError("http_status")
                content_type = (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                )
                if content_type not in limits.content_types:
                    raise SafeHttpError("unsupported_content")
                body = _decode(
                    response.iter_raw(),
                    response.headers.get("content-encoding", "").lower(),
                    limits,
                )
                return FetchResponse(url, response.status_code, content_type, body)
        except httpx.TimeoutException:
            raise SafeHttpError("timeout") from None
        except (httpx.HTTPError, httpx.InvalidURL, UnicodeError):
            raise SafeHttpError("network_error") from None
    raise SafeHttpError("too_many_redirects")


def _run_worker(url: str, limits: FetchLimits, command: list[str]) -> FetchResponse:
    configuration = asdict(limits)
    configuration["content_types"] = sorted(limits.content_types)
    payload = json.dumps({"url": url, "limits": configuration}).encode()
    started = time.monotonic()
    try:
        with subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        ) as process:
            try:
                output, _ = process.communicate(
                    payload, timeout=max(0.0, limits.total_timeout - (time.monotonic() - started))
                )
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise SafeHttpError("timeout") from None
            if process.returncode != 0:
                raise SafeHttpError("network_error")
    except OSError:
        raise SafeHttpError("network_error") from None
    return _parse_worker_result(output, limits)


def _parse_worker_result(output: bytes, limits: FetchLimits) -> FetchResponse:
    """Accept only the worker protocol's known errors and complete response records."""
    try:
        result = json.loads(output)
        if result.get("error") == "url_guard":
            if result.get("reason") not in get_args(ReasonCode.__value__):
                raise ValueError("Unknown policy reason")
            raise UrlGuardError(cast(ReasonCode, result["reason"]))
        if result.get("error") == "safe_http":
            if result.get("reason") not in {
                "too_large",
                "decompression_ratio",
                "invalid_encoding",
                "unsupported_content",
                "timeout",
                "network_error",
                "too_many_redirects",
                "invalid_redirect",
                "http_status",
            }:
                raise ValueError("Unknown transport reason")
            raise SafeHttpError(result["reason"])
        if (
            "error" in result
            or not isinstance(result["url"], str)
            or type(result["status"]) is not int
            or not 200 <= result["status"] < 300
            or result["content_type"] not in limits.content_types
            or not isinstance(result["body"], str)
        ):
            raise ValueError("Invalid response record")
        body = base64.b64decode(result["body"], validate=True)
        if len(body) > limits.max_decoded_bytes:
            raise SafeHttpError("too_large")
        return FetchResponse(result["url"], result["status"], result["content_type"], body)
    except (ValueError, KeyError, TypeError, AttributeError):
        raise SafeHttpError("network_error") from None


_DEFAULT_LIMITS = FetchLimits()


def fetch_url(url: str, *, limits: FetchLimits = _DEFAULT_LIMITS) -> FetchResponse:
    """Fetch with public-address policy, pinned TLS and an overall worker deadline."""
    return _run_worker(url, limits, [sys.executable, "-m", "cypress_creek.ingest._fetch_worker"])
