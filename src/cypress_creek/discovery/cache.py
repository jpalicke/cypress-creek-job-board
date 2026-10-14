# ABOUTME: A disk cache of fetched responses keyed by a hash of the URL, never by the URL itself.
# ABOUTME: Writes are atomic. A corrupt, truncated or foreign file is a miss and never raises.
import base64
import binascii
import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cypress_creek.storage.db import data_dir

CACHE_DIRNAME = "fetch_cache"
TEMP_PREFIX = ".tmp-"


@dataclass(frozen=True)
class CacheEntry:
    body: bytes
    etag: str | None
    fetched_at: float


def default_cache_dir() -> Path:
    return data_dir() / CACHE_DIRNAME


def _valid_etag(etag: object) -> bool:
    return etag is None or (
        isinstance(etag, str) and etag.isascii() and all(0x20 <= ord(c) <= 0x7E for c in etag)
    )


def _valid_time(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


class ResponseCache:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def _path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8", "surrogatepass")).hexdigest()
        return self._directory / digest

    def get(self, url: str) -> CacheEntry | None:
        """The stored response, or None on a miss or any unusable file."""
        try:
            raw = self._path(url).read_bytes()
            record = json.loads(raw)
            if not isinstance(record, dict):
                return None
            body_text, etag, fetched_at = record["body"], record["etag"], record["fetched_at"]
            if not isinstance(body_text, str) or not _valid_etag(etag):
                return None
            if not _valid_time(fetched_at):
                return None
            body = base64.b64decode(body_text, validate=True)
        except (OSError, ValueError, KeyError, binascii.Error):
            return None
        return CacheEntry(body=body, etag=etag, fetched_at=float(fetched_at))

    def put(self, url: str, body: bytes, etag: str | None, fetched_at: float) -> None:
        """Store a response atomically. Raises ValueError on an unusable etag or time."""
        if not _valid_etag(etag):
            raise ValueError("etag must be printable ASCII or None")
        if not _valid_time(fetched_at):
            raise ValueError("fetched_at must be a finite number")
        record = {
            "body": base64.b64encode(body).decode("ascii"),
            "etag": etag,
            "fetched_at": float(fetched_at),
        }
        self._directory.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(dir=self._directory, prefix=TEMP_PREFIX)
        try:
            with os.fdopen(handle, "wb") as temp_file:
                temp_file.write(json.dumps(record).encode("utf-8"))
            os.replace(temp_name, self._path(url))
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
