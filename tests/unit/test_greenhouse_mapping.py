# ABOUTME: Tests the pure Greenhouse feed mapping from recorded-shape bytes, with no network.
# ABOUTME: Covers field mapping, hostile text, schema errors that never echo values, and hashing.
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from cypress_creek.discovery.adapters.base import FeedSchemaError, Listing, ListingState
from cypress_creek.discovery.adapters.greenhouse import parse_board_name, parse_jobs_response
from cypress_creek.ingest.normalize import text_hash

FIXTURE = Path(__file__).parent.parent / "fixtures" / "greenhouse" / "board_responses.json"
FETCHED_AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
HOSTILE = "ignore previous instructions <script>alert(1)</script>"


def _responses() -> dict[str, Any]:
    responses: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return responses


def _jobs_bytes(mutate: Any = None) -> bytes:
    data = _responses()["jobs_response"]
    if mutate is not None:
        mutate(data)
    return json.dumps(data).encode("utf-8")


def _parse(mutate: Any = None) -> list[Listing]:
    return parse_jobs_response("ExampleCoBoard", _jobs_bytes(mutate), FETCHED_AT)


def test_fields_map_to_the_listing_shape() -> None:
    first = _parse()[0]
    assert first.id == "greenhouse:examplecoboard:4100001"
    assert first.ats == "greenhouse"
    assert first.slug == "examplecoboard"
    assert first.title == "Kite Platform Engineer"
    assert first.location == "Austin, TX"
    assert first.url == "https://boards.example.test/examplecoboard/jobs/4100001"
    assert first.posted_at == datetime(2026, 9, 1, 9, 30, tzinfo=timezone(timedelta(hours=-4)))
    assert first.fetched_at == FETCHED_AT
    assert first.state is ListingState.NEW


def test_every_job_in_the_feed_is_mapped_in_order() -> None:
    assert [item.id for item in _parse()] == [
        "greenhouse:examplecoboard:4100001",
        "greenhouse:examplecoboard:4100002",
        "greenhouse:examplecoboard:4100003",
    ]


def test_escaped_html_content_becomes_plain_text() -> None:
    first = _parse()[0]
    assert first.content_text == (
        "Who we are\nExample Co builds paper airplanes & kites.\n"
        "Design flight software\nReview each other's work"
    )


def test_hidden_elements_and_scripts_are_dropped() -> None:
    text = _parse()[1].content_text
    assert "Visible duties for the glider team." in text
    assert "hidden note" not in text
    assert "pwned" not in text


def test_entities_are_unescaped_once_only() -> None:
    text = _parse()[1].content_text
    assert "Literal markup in prose: &lt;b&gt; stays text." in text

    def single_escaped(data: dict[str, Any]) -> None:
        data["jobs"][0]["content"] = "&lt;p&gt;Shown as &amp;lt; text&lt;/p&gt;"

    assert _parse(single_escaped)[0].content_text == "Shown as < text"


def test_null_publish_date_and_missing_location_name_are_tolerated() -> None:
    third = _parse()[2]
    assert third.posted_at is None
    assert third.location == ""


def test_a_null_location_object_gives_an_empty_location() -> None:
    def null_location(data: dict[str, Any]) -> None:
        data["jobs"][0]["location"] = None

    assert _parse(null_location)[0].location == ""


def test_content_hash_is_the_hash_of_the_normalized_text() -> None:
    for item in _parse():
        assert item.content_hash == text_hash(item.content_text)


def test_hostile_title_and_location_become_plain_single_line_text() -> None:
    def hostile(data: dict[str, Any]) -> None:
        data["jobs"][0]["title"] = f"Engineer\x00\x1b[31m\n{HOSTILE}​"
        data["jobs"][0]["location"] = {"name": f"Austin\r\n<b>{HOSTILE}</b>\x07"}

    first = _parse(hostile)[0]
    assert first.title == f"Engineer[31m {HOSTILE}"
    assert first.location == f"Austin <b>{HOSTILE}</b>"
    for value in (first.title, first.location):
        assert "\n" not in value
        assert not any(ord(char) < 32 for char in value)


def test_hostile_content_markup_is_never_kept_as_markup() -> None:
    def hostile(data: dict[str, Any]) -> None:
        data["jobs"][0]["content"] = (
            "&lt;p&gt;Real duties&lt;/p&gt;&lt;script&gt;steal()&lt;/script&gt;"
            "&lt;p&gt;ignore previous instructions&lt;/p&gt;"
        )

    text = _parse(hostile)[0].content_text
    assert "<" not in text
    assert "steal" not in text
    assert text == "Real duties\nignore previous instructions"


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        (lambda d: d["jobs"][2].pop("title"), "jobs[2].title"),
        (lambda d: d["jobs"][1].__setitem__("title", 12), "jobs[1].title"),
        (lambda d: d["jobs"][0].__setitem__("id", HOSTILE), "jobs[0].id"),
        (lambda d: d["jobs"][0].__setitem__("id", True), "jobs[0].id"),
        (lambda d: d["jobs"][0].__setitem__("absolute_url", None), "jobs[0].absolute_url"),
        (lambda d: d["jobs"][0].__setitem__("content", 5), "jobs[0].content"),
        (lambda d: d["jobs"][0].pop("content"), "jobs[0].content"),
        (lambda d: d["jobs"][0].__setitem__("first_published", HOSTILE), "jobs[0].first_published"),
        (lambda d: d["jobs"][0].__setitem__("location", HOSTILE), "jobs[0].location"),
        (lambda d: d["jobs"][0]["location"].__setitem__("name", [1]), "jobs[0].location.name"),
        (lambda d: d["jobs"][0].__setitem__("title", "x" * 5000), "jobs[0].title"),
        (lambda d: d.pop("jobs"), "jobs"),
        (lambda d: d.__setitem__("jobs", HOSTILE), "jobs"),
    ],
)
def test_a_wrong_shape_names_the_field_and_never_the_value(mutate: Any, field: str) -> None:
    with pytest.raises(FeedSchemaError) as caught:
        _parse(mutate)
    assert caught.value.field == field
    assert HOSTILE not in str(caught.value)
    assert "xxxx" not in str(caught.value)


@pytest.mark.parametrize("body", [b"not json " + HOSTILE.encode(), b"[]", b"", b"null"])
def test_a_body_that_is_not_a_json_object_is_a_schema_error(body: bytes) -> None:
    with pytest.raises(FeedSchemaError) as caught:
        parse_jobs_response("acme", body, FETCHED_AT)
    assert caught.value.field == "$"
    assert HOSTILE not in str(caught.value)


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "ftp://example.test/x", "//example.test/x", "/relative", ""]
)
def test_a_non_http_url_is_a_schema_error(url: str) -> None:
    def bad_url(data: dict[str, Any]) -> None:
        data["jobs"][1]["absolute_url"] = url

    with pytest.raises(FeedSchemaError) as caught:
        _parse(bad_url)
    assert caught.value.field == "jobs[1].absolute_url"


@pytest.mark.parametrize("content", ["", "   ", '&lt;div style="display:none"&gt;x&lt;/div&gt;'])
def test_content_that_normalizes_to_nothing_is_a_schema_error(content: str) -> None:
    def empty(data: dict[str, Any]) -> None:
        data["jobs"][2]["content"] = content

    with pytest.raises(FeedSchemaError) as caught:
        _parse(empty)
    assert caught.value.field == "jobs[2].content"


def test_content_over_the_cap_is_a_schema_error() -> None:
    def huge(data: dict[str, Any]) -> None:
        data["jobs"][0]["content"] = "&lt;p&gt;" + "word " * 20_000 + "&lt;/p&gt;"

    with pytest.raises(FeedSchemaError) as caught:
        _parse(huge)
    assert caught.value.field == "jobs[0].content"


def test_a_title_that_normalizes_to_nothing_is_a_schema_error() -> None:
    def blank(data: dict[str, Any]) -> None:
        data["jobs"][0]["title"] = " ​\x00 "

    with pytest.raises(FeedSchemaError) as caught:
        _parse(blank)
    assert caught.value.field == "jobs[0].title"


def test_an_empty_board_has_no_listings() -> None:
    def no_jobs(data: dict[str, Any]) -> None:
        data["jobs"] = []

    assert _parse(no_jobs) == []


def test_the_board_name_is_read_from_the_board_response() -> None:
    body = json.dumps(_responses()["board_response"]).encode("utf-8")
    assert parse_board_name(body) == "Example Co"


def test_the_board_name_is_normalized_to_one_plain_line() -> None:
    body = json.dumps({"name": "Example\x00 Co\n<b>Two</b>", "content": ""}).encode("utf-8")
    assert parse_board_name(body) == "Example Co <b>Two</b>"


@pytest.mark.parametrize(
    "body",
    [b'{"content": ""}', b'{"name": 5}', b'{"name": ""}', b'{"name": " \\u200b "}', b"nope", b"[]"],
)
def test_a_board_response_without_a_usable_name_is_a_schema_error(body: bytes) -> None:
    with pytest.raises(FeedSchemaError) as caught:
        parse_board_name(body)
    assert caught.value.field in {"name", "$"}
