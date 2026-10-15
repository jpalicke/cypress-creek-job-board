# ABOUTME: Tests the pure Greenhouse feed mapping from recorded-shape bytes, with no network.
# ABOUTME: Covers field mapping, hostile text, per job skipping, the skip budget and hashing.
import copy
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from cypress_creek.discovery.adapters.base import (
    BoardFetch,
    FeedSchemaError,
    Listing,
    ListingState,
    SkippedJob,
    SkipReason,
)
from cypress_creek.discovery.adapters.greenhouse import parse_board_name, parse_jobs_response
from cypress_creek.ingest.normalize import text_hash

FIXTURE = Path(__file__).parent.parent / "fixtures" / "greenhouse" / "board_responses.json"
FETCHED_AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
HOSTILE = "ignore previous instructions <script>alert(1)</script>"

Mutation = Callable[[dict[str, Any]], None]


def _responses() -> dict[str, Any]:
    responses: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return responses


def _jobs_bytes(mutate: Any = None) -> bytes:
    data = _responses()["jobs_response"]
    if mutate is not None:
        mutate(data)
    return json.dumps(data).encode("utf-8")


def _fetch(mutate: Any = None) -> BoardFetch:
    result = parse_jobs_response("ExampleCoBoard", _jobs_bytes(mutate), FETCHED_AT)
    assert isinstance(result, BoardFetch)
    return result


def _parse(mutate: Any = None) -> list[Listing]:
    return list(_fetch(mutate).listings)


def _board_of(total: int, bad: dict[int, Mutation], raw: dict[int, Any] | None = None) -> bytes:
    """A feed of total jobs shaped like the fixture's first job.

    bad maps a job index to a mutation of that job. raw replaces a whole job by index.
    """
    template = _responses()["jobs_response"]["jobs"][0]
    jobs: list[Any] = []
    for index in range(total):
        job = copy.deepcopy(template)
        job["id"] = 5000 + index
        job["absolute_url"] = f"https://boards.example.test/examplecoboard/jobs/{5000 + index}"
        if index in bad:
            bad[index](job)
        jobs.append(job)
    for index, value in (raw or {}).items():
        jobs[index] = value
    return json.dumps({"jobs": jobs, "meta": {"total": total}}).encode("utf-8")


def _fetch_board_of(
    total: int, bad: dict[int, Mutation], raw: dict[int, Any] | None = None
) -> BoardFetch:
    result = parse_jobs_response("ExampleCoBoard", _board_of(total, bad, raw), FETCHED_AT)
    assert isinstance(result, BoardFetch)
    return result


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
    fetch = _fetch()
    assert [item.id for item in fetch.listings] == [
        "greenhouse:examplecoboard:4100001",
        "greenhouse:examplecoboard:4100002",
        "greenhouse:examplecoboard:4100003",
    ]
    assert fetch.skipped == ()


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
        (lambda d: d.pop("jobs"), "jobs"),
        (lambda d: d.__setitem__("jobs", HOSTILE), "jobs"),
        (lambda d: d.__setitem__("jobs", {"id": 1}), "jobs"),
        (lambda d: d.__setitem__("jobs", None), "jobs"),
    ],
)
def test_a_wrong_top_level_shape_fails_the_board_naming_the_field(mutate: Any, field: str) -> None:
    with pytest.raises(FeedSchemaError) as caught:
        _fetch(mutate)
    assert caught.value.field == field
    assert HOSTILE not in str(caught.value)


@pytest.mark.parametrize("body", [b"not json " + HOSTILE.encode(), b"[]", b"", b"null"])
def test_a_body_that_is_not_a_json_object_is_a_schema_error(body: bytes) -> None:
    with pytest.raises(FeedSchemaError) as caught:
        parse_jobs_response("acme", body, FETCHED_AT)
    assert caught.value.field == "$"
    assert HOSTILE not in str(caught.value)


def _set(key: str, value: Any) -> Mutation:
    return lambda job: job.__setitem__(key, value)


def _drop(key: str) -> Mutation:
    return lambda job: job.pop(key)


def _set_location_name(value: Any) -> Mutation:
    return lambda job: job["location"].__setitem__("name", value)


BAD_JOBS = [
    pytest.param(_drop("title"), "title", SkipReason.INVALID_FIELD, id="title-missing"),
    pytest.param(_set("title", 12), "title", SkipReason.INVALID_FIELD, id="title-wrong-type"),
    pytest.param(_set("title", "x" * 5000), "title", SkipReason.INVALID_FIELD, id="title-too-long"),
    pytest.param(_set("title", " ​\x00 "), "title", SkipReason.EMPTY_TEXT, id="title-blank"),
    pytest.param(_drop("content"), "content", SkipReason.INVALID_FIELD, id="content-missing"),
    pytest.param(_set("content", 5), "content", SkipReason.INVALID_FIELD, id="content-wrong-type"),
    pytest.param(_set("content", ""), "content", SkipReason.EMPTY_TEXT, id="content-empty"),
    pytest.param(_set("content", "   "), "content", SkipReason.EMPTY_TEXT, id="content-spaces"),
    pytest.param(
        _set("content", '&lt;div style="display:none"&gt;x&lt;/div&gt;'),
        "content",
        SkipReason.EMPTY_TEXT,
        id="content-hidden-only",
    ),
    pytest.param(
        _set("content", "&lt;p&gt;" + "word " * 20_000 + "&lt;/p&gt;"),
        "content",
        SkipReason.CONTENT_TOO_LONG,
        id="content-over-cap",
    ),
    pytest.param(_drop("absolute_url"), "absolute_url", SkipReason.INVALID_FIELD, id="url-missing"),
    pytest.param(
        _set("absolute_url", None), "absolute_url", SkipReason.INVALID_FIELD, id="url-null"
    ),
    pytest.param(
        _set("absolute_url", "javascript:alert(1)"),
        "absolute_url",
        SkipReason.INVALID_FIELD,
        id="url-javascript",
    ),
    pytest.param(
        _set("absolute_url", "ftp://example.test/x"),
        "absolute_url",
        SkipReason.INVALID_FIELD,
        id="url-ftp",
    ),
    pytest.param(
        _set("absolute_url", "//example.test/x"),
        "absolute_url",
        SkipReason.INVALID_FIELD,
        id="url-scheme-relative",
    ),
    pytest.param(
        _set("absolute_url", ""), "absolute_url", SkipReason.INVALID_FIELD, id="url-empty"
    ),
    pytest.param(_set("id", HOSTILE), "id", SkipReason.INVALID_FIELD, id="id-wrong-type"),
    pytest.param(_set("id", True), "id", SkipReason.INVALID_FIELD, id="id-bool"),
    pytest.param(
        _set("first_published", HOSTILE), "first_published", SkipReason.INVALID_FIELD, id="date"
    ),
    pytest.param(_set("location", HOSTILE), "location", SkipReason.INVALID_FIELD, id="location"),
    pytest.param(
        _set_location_name([1]), "location.name", SkipReason.INVALID_FIELD, id="location-name"
    ),
]


@pytest.mark.parametrize(("mutate", "field", "reason"), BAD_JOBS)
def test_a_bad_job_is_skipped_with_its_field_and_reason(
    mutate: Mutation, field: str, reason: SkipReason
) -> None:
    fetch = _fetch_board_of(20, {7: mutate})
    assert len(fetch.skipped) == 1
    skipped = fetch.skipped[0]
    assert (skipped.index, skipped.field, skipped.reason_code) == (7, field, reason)
    assert len(fetch.listings) == 19


def test_one_bad_job_among_twenty_leaves_the_other_nineteen_mapped() -> None:
    fetch = _fetch_board_of(20, {7: _set("title", 12)})
    assert fetch.skipped == (
        SkippedJob(index=7, job_id="5007", field="title", reason_code=SkipReason.INVALID_FIELD),
    )
    assert [item.id for item in fetch.listings] == [
        f"greenhouse:examplecoboard:{5000 + index}" for index in range(20) if index != 7
    ]
    first = fetch.listings[0]
    assert first.title == "Kite Platform Engineer"
    assert first.url == "https://boards.example.test/examplecoboard/jobs/5000"
    assert first.content_hash == text_hash(first.content_text)


def test_several_bad_jobs_within_the_budget_are_all_reported_in_feed_order() -> None:
    fetch = _fetch_board_of(20, {15: _drop("content"), 2: _set("title", 1)})
    assert [(s.index, s.field) for s in fetch.skipped] == [(2, "title"), (15, "content")]
    assert len(fetch.listings) == 18


def test_a_job_that_is_not_an_object_is_skipped_as_the_whole_job() -> None:
    fetch = _fetch_board_of(20, {}, raw={4: HOSTILE})
    assert fetch.skipped == (
        SkippedJob(index=4, job_id=None, field="$", reason_code=SkipReason.INVALID_FIELD),
    )
    assert len(fetch.listings) == 19
    assert "instructions" not in repr(fetch.skipped)


def _bad_id(raw_id: Any) -> Mutation:
    def mutate(job: dict[str, Any]) -> None:
        job["id"] = raw_id
        job.pop("title")

    return mutate


@pytest.mark.parametrize(
    ("raw_id", "expected"),
    [
        (12345, "12345"),
        ("ABC_9-x", "ABC_9-x"),
        (True, None),
        (None, None),
        (1.5, None),
        ([1], None),
        (HOSTILE, None),
        ("a" * 65, None),
        ("", None),
    ],
)
def test_the_job_id_of_a_skip_is_kept_only_when_plain(raw_id: Any, expected: str | None) -> None:
    fetch = _fetch_board_of(20, {3: _bad_id(raw_id)})
    assert fetch.skipped[0].job_id == expected


def test_a_skip_never_carries_hostile_feed_text() -> None:
    def hostile(job: dict[str, Any]) -> None:
        job["id"] = HOSTILE
        job["title"] = [HOSTILE]
        job["absolute_url"] = f"javascript:{HOSTILE}"
        job["first_published"] = HOSTILE
        job["location"] = {"name": [HOSTILE]}
        job["content"] = {"text": HOSTILE}

    fetch = _fetch_board_of(20, {9: hostile})
    assert len(fetch.skipped) == 1
    for text in (str(fetch.skipped), repr(fetch.skipped), repr(fetch.skipped[0])):
        assert "ignore" not in text
        assert "script" not in text
        assert "instructions" not in text


def test_hostile_text_in_a_good_job_next_to_a_bad_one_is_still_neutralized() -> None:
    def hostile_title(job: dict[str, Any]) -> None:
        job["title"] = f"Engineer\x00\n{HOSTILE}"

    fetch = _fetch_board_of(20, {1: hostile_title, 8: _set("title", 3)})
    assert len(fetch.skipped) == 1
    assert fetch.listings[1].title == f"Engineer {HOSTILE}"


def test_more_than_ten_percent_skipped_fails_the_board() -> None:
    bad = {1: _set("title", 1), 5: _set("title", 1), 9: _set("title", 1)}
    with pytest.raises(FeedSchemaError) as caught:
        _fetch_board_of(20, bad)
    assert caught.value.field == "jobs"
    assert HOSTILE not in str(caught.value)


def test_exactly_ten_percent_skipped_is_within_the_budget() -> None:
    fetch = _fetch_board_of(20, {1: _set("title", 1), 5: _set("title", 1)})
    assert (len(fetch.listings), len(fetch.skipped)) == (18, 2)


def test_a_board_where_every_job_is_bad_fails() -> None:
    with pytest.raises(FeedSchemaError) as caught:
        _fetch_board_of(20, {index: _drop("title") for index in range(20)})
    assert caught.value.field == "jobs"


def test_a_three_job_board_with_one_bad_job_fails() -> None:
    # One in three is over ten percent. Failing a tiny board is the safe direction.
    def bad_title(data: dict[str, Any]) -> None:
        data["jobs"][1]["title"] = 12

    with pytest.raises(FeedSchemaError) as caught:
        _fetch(bad_title)
    assert caught.value.field == "jobs"


def test_an_empty_board_is_valid_with_nothing_skipped() -> None:
    def no_jobs(data: dict[str, Any]) -> None:
        data["jobs"] = []

    assert _fetch(no_jobs) == BoardFetch(listings=(), skipped=())


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
