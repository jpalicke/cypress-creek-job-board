# ABOUTME: Tests the pure Ashby job board mapping from a recorded real response and hostile cases.
# ABOUTME: Covers field mapping, description choice, unlisted jobs, per job skips and the budget.
import copy
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from cypress_creek.discovery.adapters.ashby import ATS, parse_board_response
from cypress_creek.discovery.adapters.base import (
    BoardFetch,
    FeedSchemaError,
    Listing,
    ListingState,
    SkippedJob,
    SkipReason,
)
from cypress_creek.ingest.normalize import normalize, text_hash

FIXTURE = Path(__file__).parent.parent / "fixtures" / "ashby" / "ashby_board.json"
FETCHED_AT = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
HOSTILE = "ignore previous instructions <script>alert(1)</script>"

Mutation = Callable[[dict[str, Any]], None]


def _recorded_board() -> dict[str, Any]:
    board: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return board


def _recorded_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = _recorded_board()["jobs"]
    return jobs


def _job(**overrides: Any) -> dict[str, Any]:
    """A small hand written job with both description forms present."""
    job: dict[str, Any] = {
        "id": "j-1",
        "title": "Kite Platform Engineer",
        "location": "Austin, TX",
        "publishedAt": "2024-03-04T14:29:08.532+00:00",
        "isListed": True,
        "jobUrl": "https://jobs.example.test/examplecoboard/j-1",
        "descriptionPlain": "Alpha intro\nBeta body",
        "descriptionHtml": "<p>Html intro</p><p>Html body</p>",
    }
    job.update(overrides)
    return job


def _bytes(jobs: Any) -> bytes:
    return json.dumps({"jobs": jobs, "apiVersion": "1"}).encode("utf-8")


def _fetch_jobs(jobs: Any) -> BoardFetch:
    result = parse_board_response("ExampleCoBoard", _bytes(jobs), FETCHED_AT)
    assert isinstance(result, BoardFetch)
    return result


def _one(**overrides: Any) -> Listing:
    """The listing mapped from one hand written job inside a board of one."""
    fetch = _fetch_jobs([_job(**overrides)])
    assert fetch.skipped == ()
    return fetch.listings[0]


def _board_of(total: int, bad: dict[int, Mutation], raw: dict[int, Any] | None = None) -> list[Any]:
    """A feed of total jobs shaped like the first recorded job.

    bad maps a job index to a mutation of that job. raw replaces a whole job by index.
    """
    template = _recorded_jobs()[0]
    jobs: list[Any] = []
    for index in range(total):
        job = copy.deepcopy(template)
        job["id"] = f"job-{index}"
        job["jobUrl"] = f"https://jobs.example.test/examplecoboard/job-{index}"
        if index in bad:
            bad[index](job)
        jobs.append(job)
    for index, value in (raw or {}).items():
        jobs[index] = value
    return jobs


def _fetch_board_of(
    total: int, bad: dict[int, Mutation], raw: dict[int, Any] | None = None
) -> BoardFetch:
    return _fetch_jobs(_board_of(total, bad, raw))


def _set(key: str, value: Any) -> Mutation:
    return lambda job: job.__setitem__(key, value)


def _drop(key: str) -> Mutation:
    return lambda job: job.pop(key)


def test_the_ats_name_is_ashby() -> None:
    assert ATS == "ashby"


def test_an_unlisted_job_is_dropped_and_counted() -> None:
    # No live board currently exposes an unlisted job, so the flag is edited in the recording.
    board = _recorded_board()
    board["jobs"][1]["isListed"] = False
    fetch = parse_board_response("ashby", json.dumps(board).encode("utf-8"), FETCHED_AT)
    assert [item.id for item in fetch.listings] == [
        "ashby:ashby:7458d4e9-da2e-47bd-98cb-adfda43d42b2",
        "ashby:ashby:86a60834-ba64-484d-9658-afa1bc97a957",
    ]
    assert fetch.skipped == ()
    assert fetch.unlisted == 1


def test_recorded_real_fields_map_to_the_listing_shape() -> None:
    fetch = parse_board_response("Ashby", _bytes(_recorded_jobs()), FETCHED_AT)
    first = fetch.listings[0]
    assert first.id == "ashby:ashby:7458d4e9-da2e-47bd-98cb-adfda43d42b2"
    assert first.ats == "ashby"
    assert first.slug == "ashby"
    assert first.title == "Engineering Manager - EU"
    assert first.location == "Remote - European Union"
    assert first.url == "https://jobs.ashbyhq.com/ashby/7458d4e9-da2e-47bd-98cb-adfda43d42b2"
    assert first.posted_at == datetime(2024, 3, 4, 14, 29, 8, 532000, tzinfo=UTC)
    assert first.fetched_at == FETCHED_AT
    assert first.state is ListingState.NEW
    assert fetch.unlisted == 0


def test_every_recorded_job_is_mapped_in_order() -> None:
    fetch = _fetch_jobs(_recorded_jobs())
    assert [item.id.rsplit(":", 1)[1] for item in fetch.listings] == [
        "7458d4e9-da2e-47bd-98cb-adfda43d42b2",
        "390e266b-4b6c-4490-ad74-05ff5e0bb36a",
        "86a60834-ba64-484d-9658-afa1bc97a957",
    ]
    assert fetch.skipped == ()


def test_recorded_listings_are_timezone_aware_https_with_text_and_a_matching_hash() -> None:
    for item in _fetch_jobs(_recorded_jobs()).listings:
        assert item.posted_at is not None
        assert item.posted_at.utcoffset() == timedelta(0)
        assert item.url.startswith("https://")
        assert item.content_text
        assert item.content_hash == text_hash(item.content_text)


def test_recorded_description_is_the_plain_text_form() -> None:
    for job, listing in zip(_recorded_jobs(), _fetch_jobs(_recorded_jobs()).listings, strict=True):
        assert listing.content_text == normalize(job["descriptionPlain"])[0]
        assert "<p>" not in listing.content_text


def test_a_posted_at_keeps_its_instant_whatever_the_offset() -> None:
    posted_at = _one(publishedAt="2024-03-04T09:29:08-05:00").posted_at
    assert posted_at == datetime(2024, 3, 4, 14, 29, 8, tzinfo=UTC)
    assert posted_at is not None
    assert posted_at.utcoffset() is not None


def test_a_missing_or_null_published_at_gives_no_posted_at() -> None:
    job = _job()
    job.pop("publishedAt")
    assert _fetch_jobs([job]).listings[0].posted_at is None
    assert _one(publishedAt=None).posted_at is None


def test_the_plain_description_is_preferred_over_the_html_one() -> None:
    assert _one().content_text == "Alpha intro\nBeta body"


def test_the_html_description_is_used_when_the_plain_one_is_missing() -> None:
    job = _job()
    job.pop("descriptionPlain")
    assert _fetch_jobs([job]).listings[0].content_text == "Html intro\nHtml body"


@pytest.mark.parametrize("plain", ["", "   ", " ​\x00 \n", None])
def test_the_html_description_is_used_when_the_plain_one_is_blank(plain: str | None) -> None:
    assert _one(descriptionPlain=plain).content_text == "Html intro\nHtml body"


def test_the_html_description_is_converted_to_text_without_scripts_or_hidden_parts() -> None:
    listing = _one(
        descriptionPlain="",
        descriptionHtml=(
            "<p>Visible one</p><script>pwned()</script>"
            '<div style="display:none">hidden a</div><p>Tom &amp; Jerry</p>'
            "<div hidden>hidden b</div><style>p{x:y}</style>"
        ),
    )
    assert listing.content_text == "Visible one\nTom & Jerry"


def test_the_plain_description_is_kept_as_text_and_the_html_one_is_not_read() -> None:
    listing = _one(
        descriptionPlain="Use <b> and &amp; as written",
        descriptionHtml="<div>" * 300,
    )
    assert listing.content_text == "Use <b> and &amp; as written"


def test_hostile_control_and_bidi_characters_are_stripped_from_the_description() -> None:
    plain = _one(descriptionPlain=f"Real\x00 duties‮\n\n\n\n{HOSTILE}\x1b[31m")
    assert plain.content_text == f"Real duties\n\n{HOSTILE}[31m"
    html = _one(descriptionPlain="", descriptionHtml=f"<p>Real\x00 duties‮</p><p>{HOSTILE}</p>")
    assert "\x00" not in html.content_text
    assert "‮" not in html.content_text
    assert "alert(1)" not in html.content_text


def test_hostile_title_and_location_become_plain_single_line_text() -> None:
    listing = _one(
        title=f"Engineer\x00\x1b[31m\n{HOSTILE}​",
        location=f"Austin\r\n<b>{HOSTILE}</b>\x07‮",
    )
    assert listing.title == f"Engineer[31m {HOSTILE}"
    assert listing.location == f"Austin <b>{HOSTILE}</b>"
    for value in (listing.title, listing.location):
        assert "\n" not in value
        assert not any(ord(char) < 32 for char in value)


def test_a_missing_or_null_location_gives_an_empty_location() -> None:
    job = _job()
    job.pop("location")
    assert _fetch_jobs([job]).listings[0].location == ""
    assert _one(location=None).location == ""
    assert _one(location="").location == ""


def test_the_slug_is_normalized_in_the_id_and_the_slug_field() -> None:
    fetch = parse_board_response("  ExampleCoBoard ", _bytes([_job()]), FETCHED_AT)
    assert fetch.listings[0].id == "ashby:examplecoboard:j-1"
    assert fetch.listings[0].slug == "examplecoboard"


def test_unknown_fields_are_ignored() -> None:
    listing = _one(department=HOSTILE, address={"x": [HOSTILE]}, isRemote="maybe")
    assert listing.title == "Kite Platform Engineer"


def test_a_body_with_an_empty_jobs_list_is_an_empty_valid_board() -> None:
    assert _fetch_jobs([]) == BoardFetch(listings=(), skipped=())
    assert _fetch_jobs([]).unlisted == 0


@pytest.mark.parametrize(
    ("body", "field"),
    [
        (b'{"apiVersion": "1"}', "jobs"),
        (b'{"jobs": null}', "jobs"),
        (b'{"jobs": {"id": "' + HOSTILE.encode() + b'"}}', "jobs"),
        (b'{"jobs": "' + HOSTILE.encode() + b'"}', "jobs"),
        (b"[]", "$"),
        (b'["' + HOSTILE.encode() + b'"]', "$"),
        (b'"' + HOSTILE.encode() + b'"', "$"),
        (b"null", "$"),
        (b"5", "$"),
        (b"not json " + HOSTILE.encode(), "$"),
        (b"", "$"),
    ],
)
def test_a_body_of_the_wrong_shape_fails_the_board_naming_the_field(
    body: bytes, field: str
) -> None:
    with pytest.raises(FeedSchemaError) as caught:
        parse_board_response("acme", body, FETCHED_AT)
    assert caught.value.field == field
    assert caught.value.reason_code == "feed_schema"
    assert "ignore" not in str(caught.value)
    assert "script" not in str(caught.value)


BAD_JOBS = [
    pytest.param(_drop("id"), "id", SkipReason.INVALID_FIELD, id="id-missing"),
    pytest.param(_set("id", 12), "id", SkipReason.INVALID_FIELD, id="id-wrong-type"),
    pytest.param(_set("id", ""), "id", SkipReason.INVALID_FIELD, id="id-empty"),
    pytest.param(_set("id", "   "), "id", SkipReason.INVALID_FIELD, id="id-blank"),
    pytest.param(_set("id", HOSTILE), "id", SkipReason.INVALID_FIELD, id="id-not-plain"),
    pytest.param(_set("id", "a:b"), "id", SkipReason.INVALID_FIELD, id="id-colon"),
    pytest.param(_set("id", "a" * 65), "id", SkipReason.INVALID_FIELD, id="id-too-long"),
    pytest.param(_drop("title"), "title", SkipReason.INVALID_FIELD, id="title-missing"),
    pytest.param(_set("title", 12), "title", SkipReason.INVALID_FIELD, id="title-wrong-type"),
    pytest.param(_set("title", "x" * 5000), "title", SkipReason.INVALID_FIELD, id="title-too-long"),
    pytest.param(_set("title", " ​\x00 "), "title", SkipReason.EMPTY_TEXT, id="title-blank"),
    pytest.param(_set("location", 12), "location", SkipReason.INVALID_FIELD, id="location-type"),
    pytest.param(
        _set("location", "x" * 5000), "location", SkipReason.INVALID_FIELD, id="location-too-long"
    ),
    pytest.param(_drop("jobUrl"), "jobUrl", SkipReason.INVALID_FIELD, id="url-missing"),
    pytest.param(_set("jobUrl", None), "jobUrl", SkipReason.INVALID_FIELD, id="url-null"),
    pytest.param(_set("jobUrl", 7), "jobUrl", SkipReason.INVALID_FIELD, id="url-wrong-type"),
    pytest.param(
        _set("jobUrl", "javascript:alert(1)"),
        "jobUrl",
        SkipReason.INVALID_FIELD,
        id="url-javascript",
    ),
    pytest.param(
        _set("jobUrl", "ftp://example.test/x"), "jobUrl", SkipReason.INVALID_FIELD, id="url-ftp"
    ),
    pytest.param(
        _set("jobUrl", "//example.test/x"),
        "jobUrl",
        SkipReason.INVALID_FIELD,
        id="url-scheme-relative",
    ),
    pytest.param(_set("jobUrl", ""), "jobUrl", SkipReason.INVALID_FIELD, id="url-empty"),
    pytest.param(
        _set("jobUrl", "https://example.test/" + "a" * 2048),
        "jobUrl",
        SkipReason.INVALID_FIELD,
        id="url-over-2048",
    ),
    pytest.param(
        _set("publishedAt", "2024-03-04T14:29:08"),
        "publishedAt",
        SkipReason.INVALID_FIELD,
        id="date-naive",
    ),
    pytest.param(
        _set("publishedAt", "2024-03-04"),
        "publishedAt",
        SkipReason.INVALID_FIELD,
        id="date-only",
    ),
    pytest.param(
        _set("publishedAt", HOSTILE), "publishedAt", SkipReason.INVALID_FIELD, id="date-garbage"
    ),
    pytest.param(
        _set("publishedAt", 1_700_000_000_000),
        "publishedAt",
        SkipReason.INVALID_FIELD,
        id="date-epoch-number",
    ),
    pytest.param(
        _set("publishedAt", True), "publishedAt", SkipReason.INVALID_FIELD, id="date-bool"
    ),
    pytest.param(
        _set("publishedAt", "2024-13-45T99:99:99+00:00"),
        "publishedAt",
        SkipReason.INVALID_FIELD,
        id="date-impossible",
    ),
    pytest.param(_drop("isListed"), "isListed", SkipReason.INVALID_FIELD, id="listed-missing"),
    pytest.param(_set("isListed", None), "isListed", SkipReason.INVALID_FIELD, id="listed-null"),
    pytest.param(
        _set("isListed", "true"), "isListed", SkipReason.INVALID_FIELD, id="listed-string-true"
    ),
    pytest.param(
        _set("isListed", "false"), "isListed", SkipReason.INVALID_FIELD, id="listed-string-false"
    ),
    pytest.param(_set("isListed", 0), "isListed", SkipReason.INVALID_FIELD, id="listed-zero"),
    pytest.param(_set("isListed", 1), "isListed", SkipReason.INVALID_FIELD, id="listed-one"),
    pytest.param(
        _set("descriptionPlain", 5),
        "descriptionPlain",
        SkipReason.INVALID_FIELD,
        id="plain-wrong-type",
    ),
    pytest.param(
        _set("descriptionHtml", 5),
        "descriptionHtml",
        SkipReason.INVALID_FIELD,
        id="html-wrong-type",
    ),
    pytest.param(
        lambda j: j.update(descriptionPlain="", descriptionHtml=""),
        "description",
        SkipReason.EMPTY_TEXT,
        id="both-descriptions-empty",
    ),
    pytest.param(
        lambda j: j.update(descriptionPlain="  ", descriptionHtml="<p> </p>"),
        "description",
        SkipReason.EMPTY_TEXT,
        id="both-descriptions-blank",
    ),
    pytest.param(
        lambda j: (j.pop("descriptionPlain"), j.pop("descriptionHtml")),
        "description",
        SkipReason.EMPTY_TEXT,
        id="both-descriptions-missing",
    ),
    pytest.param(
        lambda j: j.update(
            descriptionPlain=None, descriptionHtml='<div style="display:none">x</div>'
        ),
        "description",
        SkipReason.EMPTY_TEXT,
        id="html-hidden-only",
    ),
    pytest.param(
        _set("descriptionPlain", "word " * 20_000),
        "description",
        SkipReason.CONTENT_TOO_LONG,
        id="plain-over-cap",
    ),
    pytest.param(
        lambda j: j.update(descriptionPlain="", descriptionHtml="<p>" + "word " * 20_000 + "</p>"),
        "description",
        SkipReason.CONTENT_TOO_LONG,
        id="html-over-cap",
    ),
    pytest.param(
        _set("descriptionPlain", "x" * 600_000),
        "description",
        SkipReason.CONTENT_TOO_LONG,
        id="plain-over-raw-cap",
    ),
    pytest.param(
        lambda j: j.update(descriptionPlain="", descriptionHtml="<div>" * 300),
        "description",
        SkipReason.CONTENT_UNREADABLE,
        id="html-too-deep",
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
    assert fetch.unlisted == 0


def test_one_bad_job_among_twenty_leaves_the_other_nineteen_mapped() -> None:
    fetch = _fetch_board_of(20, {7: _set("title", 12)})
    assert fetch.skipped == (
        SkippedJob(index=7, job_id="job-7", field="title", reason_code=SkipReason.INVALID_FIELD),
    )
    assert [item.id for item in fetch.listings] == [
        f"ashby:examplecoboard:job-{index}" for index in range(20) if index != 7
    ]
    first = fetch.listings[0]
    assert first.title == "Engineering Manager - EU"
    assert first.url == "https://jobs.example.test/examplecoboard/job-0"
    assert first.content_hash == text_hash(first.content_text)


def test_several_bad_jobs_within_the_budget_are_all_reported_in_feed_order() -> None:
    fetch = _fetch_board_of(20, {15: _drop("jobUrl"), 2: _set("title", 1)})
    assert [(s.index, s.field) for s in fetch.skipped] == [(2, "title"), (15, "jobUrl")]
    assert len(fetch.listings) == 18


@pytest.mark.parametrize("raw", [HOSTILE, 5, None, ["x"], True])
def test_a_job_that_is_not_an_object_is_skipped_as_the_whole_job(raw: Any) -> None:
    fetch = _fetch_board_of(20, {}, raw={4: raw})
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
        ("7458d4e9-da2e-47bd-98cb-adfda43d42b2", "7458d4e9-da2e-47bd-98cb-adfda43d42b2"),
        ("ABC_9-x", "ABC_9-x"),
        (12345, None),
        (True, None),
        (None, None),
        ([1], None),
        (HOSTILE, None),
        ("a" * 65, None),
        ("", None),
    ],
)
def test_the_id_of_a_skip_is_kept_only_when_plain(raw_id: Any, expected: str | None) -> None:
    fetch = _fetch_board_of(20, {3: _bad_id(raw_id)})
    assert fetch.skipped[0].job_id == expected


def test_a_skip_never_carries_hostile_feed_text() -> None:
    def hostile(job: dict[str, Any]) -> None:
        job["id"] = HOSTILE
        job["title"] = [HOSTILE]
        job["jobUrl"] = f"javascript:{HOSTILE}"
        job["publishedAt"] = HOSTILE
        job["location"] = [HOSTILE]
        job["isListed"] = HOSTILE
        job["descriptionPlain"] = {"text": HOSTILE}
        job["descriptionHtml"] = [HOSTILE]

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
    jobs = _recorded_jobs()
    jobs[1]["title"] = 12
    with pytest.raises(FeedSchemaError) as caught:
        _fetch_jobs(jobs)
    assert caught.value.field == "jobs"


def _unlisted(job: dict[str, Any]) -> None:
    job["isListed"] = False


def test_unlisted_jobs_are_counted_and_never_become_listings_or_skips() -> None:
    fetch = _fetch_board_of(20, {2: _unlisted, 11: _unlisted, 12: _unlisted})
    assert fetch.unlisted == 3
    assert fetch.skipped == ()
    assert [item.id for item in fetch.listings] == [
        f"ashby:examplecoboard:job-{index}" for index in range(20) if index not in {2, 11, 12}
    ]


def test_a_board_of_only_unlisted_jobs_is_a_valid_empty_board() -> None:
    fetch = _fetch_board_of(20, {index: _unlisted for index in range(20)})
    assert (fetch.listings, fetch.skipped, fetch.unlisted) == ((), (), 20)


def test_a_mostly_unlisted_board_is_not_a_schema_failure() -> None:
    fetch = _fetch_board_of(20, {index: _unlisted for index in range(15)})
    assert (len(fetch.listings), len(fetch.skipped), fetch.unlisted) == (5, 0, 15)


def test_the_skip_budget_is_counted_over_listed_jobs_only() -> None:
    # Two bad of twenty is within the budget, but with three unlisted the listed total is seventeen
    # and two of seventeen is over ten percent.
    unlisted = {index: _unlisted for index in (3, 4, 5)}
    bad = {10: _set("title", 1), 11: _set("title", 1)}
    with pytest.raises(FeedSchemaError) as caught:
        _fetch_board_of(20, {**unlisted, **bad})
    assert caught.value.field == "jobs"


def test_exactly_ten_percent_of_the_listed_jobs_skipped_is_within_the_budget() -> None:
    unlisted = {index: _unlisted for index in range(10)}
    fetch = _fetch_board_of(20, {**unlisted, 15: _set("title", 1)})
    assert (len(fetch.listings), len(fetch.skipped), fetch.unlisted) == (9, 1, 10)


def test_an_unlisted_job_with_garbage_in_every_other_field_is_unlisted_not_skipped() -> None:
    def garbage(job: dict[str, Any]) -> None:
        job["id"] = HOSTILE
        job["title"] = [HOSTILE]
        job["jobUrl"] = f"javascript:{HOSTILE}"
        job["publishedAt"] = HOSTILE
        job["location"] = 5
        job["descriptionPlain"] = {"x": 1}
        job["descriptionHtml"] = 7
        job["isListed"] = False

    fetch = _fetch_board_of(20, {6: garbage})
    assert fetch.unlisted == 1
    assert fetch.skipped == ()
    assert len(fetch.listings) == 19


def test_an_unlisted_flag_is_only_trusted_when_it_is_the_json_false() -> None:
    # A hostile feed must not be able to hide a malformed job behind a look alike value.
    look_alikes: list[Any] = [0, "false", None, "", [], {}]
    for value in look_alikes:
        fetch = _fetch_board_of(20, {5: _set("isListed", value)})
        assert fetch.unlisted == 0
        assert [(s.index, s.field) for s in fetch.skipped] == [(5, "isListed")]


def test_an_unlisted_job_that_is_not_an_object_is_skipped_as_the_whole_job() -> None:
    fetch = _fetch_board_of(20, {}, raw={4: [False]})
    assert fetch.unlisted == 0
    assert [(s.index, s.field) for s in fetch.skipped] == [(4, "$")]


def test_unlisted_jobs_carry_no_feed_text_anywhere_in_the_result() -> None:
    def garbage(job: dict[str, Any]) -> None:
        job["id"] = HOSTILE
        job["title"] = HOSTILE
        job["isListed"] = False

    fetch = _fetch_board_of(20, {6: garbage})
    assert HOSTILE not in repr(fetch)
