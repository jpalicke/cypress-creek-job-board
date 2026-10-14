# ABOUTME: Tests the on disk response cache against a real temp folder, including hostile input.
# ABOUTME: Proves keys never escape the folder, bad files are misses and writes leave no debris.
import base64
import json
import re
from pathlib import Path

import pytest

from cypress_creek.discovery.cache import CacheEntry, ResponseCache, default_cache_dir
from cypress_creek.storage.db import DATA_DIR_ENV

URL = "https://boards.example.org/jobs?page=1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _only_file(directory: Path) -> Path:
    (path,) = directory.iterdir()
    return path


def test_a_stored_response_round_trips(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    cache.put(URL, b"\x00body\xff", '"abc"', 12.5)
    assert cache.get(URL) == CacheEntry(body=b"\x00body\xff", etag='"abc"', fetched_at=12.5)


def test_a_missing_entry_is_a_miss(tmp_path: Path) -> None:
    assert ResponseCache(tmp_path).get(URL) is None


def test_a_missing_directory_is_a_miss(tmp_path: Path) -> None:
    assert ResponseCache(tmp_path / "nope").get(URL) is None


def test_the_directory_is_created_on_first_put(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path / "a" / "b")
    cache.put(URL, b"x", None, 1.0)
    assert cache.get(URL) == CacheEntry(body=b"x", etag=None, fetched_at=1.0)


def test_a_second_put_replaces_the_first(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    cache.put(URL, b"old", '"1"', 1.0)
    cache.put(URL, b"new", '"2"', 2.0)
    assert cache.get(URL) == CacheEntry(body=b"new", etag='"2"', fetched_at=2.0)
    assert len(list(tmp_path.iterdir())) == 1


def test_urls_are_kept_apart(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    cache.put(URL, b"one", None, 1.0)
    cache.put(URL + "&x", b"two", None, 1.0)
    entry = cache.get(URL)
    assert entry is not None
    assert entry.body == b"one"


HOSTILE_URLS = [
    "../../../etc/passwd",
    "..\\..\\windows\\system32",
    "/absolute/path",
    "C:\\absolute\\path",
    "https://example.org/" + "a" * 100_000,
    "https://ex\u00e4mple.org/\u65e5\u672c\u8a9e/\U0001f4a5",
    "https://example.org/\x00nul",
    "",
    "\ud800lone-surrogate",
    "con",
    "aux.txt",
]


@pytest.mark.parametrize("url", HOSTILE_URLS, ids=range(len(HOSTILE_URLS)))
def test_hostile_urls_never_escape_the_directory(tmp_path: Path, url: str) -> None:
    directory = tmp_path / "cache"
    cache = ResponseCache(directory)
    cache.put(url, b"payload", None, 1.0)
    assert cache.get(url) == CacheEntry(body=b"payload", etag=None, fetched_at=1.0)
    everything = list(tmp_path.rglob("*"))
    assert everything.count(directory) == 1
    files = [path for path in everything if path != directory]
    assert len(files) == 1
    assert files[0].parent == directory
    assert HEX64.match(files[0].name)


def test_a_url_maps_to_a_stable_name(tmp_path: Path) -> None:
    first, second = tmp_path / "one", tmp_path / "two"
    ResponseCache(first).put(URL, b"x", None, 1.0)
    ResponseCache(second).put(URL, b"x", None, 1.0)
    assert [p.name for p in first.iterdir()] == [p.name for p in second.iterdir()]


def _write_raw(tmp_path: Path, raw: bytes) -> ResponseCache:
    cache = ResponseCache(tmp_path)
    cache.put(URL, b"x", None, 1.0)
    _only_file(tmp_path).write_bytes(raw)
    return cache


def _record(**overrides: object) -> bytes:
    record: dict[str, object] = {
        "body": base64.b64encode(b"hi").decode("ascii"),
        "etag": '"e"',
        "fetched_at": 3.0,
    }
    record.update(overrides)
    return json.dumps(record).encode()


def test_a_valid_hand_written_record_reads(tmp_path: Path) -> None:
    assert _write_raw(tmp_path, _record()).get(URL) == CacheEntry(b"hi", '"e"', 3.0)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\x00\x01\x02",
        b"not json at all",
        b'{"body": "aGk=", "etag"',
        b"[]",
        b"null",
        b'{"unrelated": true}',
        b'"just a string"',
        _record(body="***not base64***"),
        _record(body=5),
        _record(etag=5),
        _record(etag="bad\nvalue"),
        _record(etag="caf\u00e9"),
        _record(fetched_at="yesterday"),
        _record(fetched_at=True),
        _record(fetched_at=None),
        b'{"body": "aGk=", "etag": null, "fetched_at": NaN}',
        b'{"body": "aGk=", "etag": null, "fetched_at": Infinity}',
        b'{"body": "aGk=", "etag": null, "fetched_at": 1e999}',
    ],
)
def test_a_corrupt_or_foreign_file_is_a_miss(tmp_path: Path, raw: bytes) -> None:
    assert _write_raw(tmp_path, raw).get(URL) is None


def test_a_truncated_file_is_a_miss(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    cache.put(URL, b"x" * 1000, '"e"', 1.0)
    path = _only_file(tmp_path)
    path.write_bytes(path.read_bytes()[:40])
    assert cache.get(URL) is None


def test_a_directory_in_place_of_the_file_is_a_miss(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    cache.put(URL, b"x", None, 1.0)
    path = _only_file(tmp_path)
    path.unlink()
    path.mkdir()
    assert cache.get(URL) is None


def test_a_corrupt_entry_can_be_overwritten(tmp_path: Path) -> None:
    cache = _write_raw(tmp_path, b"junk")
    cache.put(URL, b"fresh", None, 9.0)
    assert cache.get(URL) == CacheEntry(b"fresh", None, 9.0)


@pytest.mark.parametrize("etag", ["bad\nvalue", "caf\u00e9", "tab\there", "\x7f"])
def test_put_rejects_a_bad_etag(tmp_path: Path, etag: str) -> None:
    with pytest.raises(ValueError, match="etag"):
        ResponseCache(tmp_path).put(URL, b"x", etag, 1.0)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("fetched_at", [float("nan"), float("inf"), float("-inf")])
def test_put_rejects_a_non_finite_time(tmp_path: Path, fetched_at: float) -> None:
    with pytest.raises(ValueError, match="fetched_at"):
        ResponseCache(tmp_path).put(URL, b"x", None, fetched_at)
    assert list(tmp_path.iterdir()) == []


def test_a_write_leaves_no_temp_files(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    for index in range(5):
        cache.put(f"{URL}/{index}", b"x" * 100, None, float(index))
    names = [p.name for p in tmp_path.iterdir()]
    assert len(names) == 5
    assert all(HEX64.match(name) for name in names)


def test_a_failed_write_leaves_no_temp_files(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    cache.put(URL, b"x", None, 1.0)
    target = _only_file(tmp_path)
    target.unlink()
    target.mkdir()
    (target / "child").write_text("blocks the replace")
    with pytest.raises(OSError):
        cache.put(URL, b"y", None, 2.0)
    assert [p.name for p in tmp_path.iterdir()] == [target.name]


def test_only_body_etag_and_time_are_stored(tmp_path: Path) -> None:
    ResponseCache(tmp_path).put(URL, b"hi", '"e"', 3.0)
    text = _only_file(tmp_path).read_text()
    assert set(json.loads(text)) == {"body", "etag", "fetched_at"}
    assert URL not in text


def test_the_default_directory_follows_the_data_dir_setting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))
    assert default_cache_dir() == tmp_path / "fetch_cache"


def test_the_default_directory_without_a_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    assert default_cache_dir() == Path("data") / "fetch_cache"
