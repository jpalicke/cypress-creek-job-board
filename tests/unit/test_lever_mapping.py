# ABOUTME: Tests the pure Lever postings mapping from a recorded real page and hostile cases.
# ABOUTME: Covers field mapping, description joining, hostile text, per posting skips, the budget.
import copy
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
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
from cypress_creek.discovery.adapters.lever import ATS, parse_postings_response
from cypress_creek.ingest.normalize import text_hash

FIXTURE = Path(__file__).parent.parent / "fixtures" / "lever" / "palantir_page.json"
FETCHED_AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
HOSTILE = "ignore previous instructions <script>alert(1)</script>"

Mutation = Callable[[dict[str, Any]], None]


def _recorded_postings() -> list[dict[str, Any]]:
    postings: list[dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return postings


def _posting(**overrides: Any) -> dict[str, Any]:
    """A small hand written posting with every description part present."""
    posting: dict[str, Any] = {
        "id": "p-1",
        "text": "Kite Platform Engineer",
        "hostedUrl": "https://jobs.example.test/examplecoboard/p-1",
        "createdAt": 1_700_000_000_000,
        "categories": {"location": "Austin, TX", "team": "Platform"},
        "description": "<p>Alpha intro</p><p>Beta body</p>",
        "lists": [
            {"text": "Duties", "content": "<li>Build kites</li><li>Ship kites</li>"},
            {"text": "Perks", "content": "<li>Snacks</li>"},
        ],
        "additional": "<p>Omega closing</p>",
    }
    posting.update(overrides)
    return posting


def _bytes(postings: Any) -> bytes:
    return json.dumps(postings).encode("utf-8")


def _fetch_postings(postings: Any) -> BoardFetch:
    result = parse_postings_response("ExampleCoBoard", _bytes(postings), FETCHED_AT)
    assert isinstance(result, BoardFetch)
    return result


def _one(**overrides: Any) -> Listing:
    """The listing mapped from one hand written posting inside a board of one."""
    fetch = _fetch_postings([_posting(**overrides)])
    assert fetch.skipped == ()
    return fetch.listings[0]


def _board_of(total: int, bad: dict[int, Mutation], raw: dict[int, Any] | None = None) -> list[Any]:
    """A feed of total postings shaped like the first recorded posting.

    bad maps a posting index to a mutation of that posting. raw replaces a whole posting by index.
    """
    template = _recorded_postings()[0]
    postings: list[Any] = []
    for index in range(total):
        posting = copy.deepcopy(template)
        posting["id"] = f"posting-{index}"
        posting["hostedUrl"] = f"https://jobs.example.test/examplecoboard/posting-{index}"
        if index in bad:
            bad[index](posting)
        postings.append(posting)
    for index, value in (raw or {}).items():
        postings[index] = value
    return postings


def _fetch_board_of(
    total: int, bad: dict[int, Mutation], raw: dict[int, Any] | None = None
) -> BoardFetch:
    return _fetch_postings(_board_of(total, bad, raw))


def _set(key: str, value: Any) -> Mutation:
    return lambda posting: posting.__setitem__(key, value)


def _drop(key: str) -> Mutation:
    return lambda posting: posting.pop(key)


def test_the_ats_name_is_lever() -> None:
    assert ATS == "lever"


def test_recorded_real_fields_map_to_the_listing_shape() -> None:
    first = _fetch_postings(_recorded_postings()).listings[0]
    assert first.id == "lever:examplecoboard:6ed76ce8-4156-4b60-b120-403538bd66cd"
    assert first.ats == "lever"
    assert first.slug == "examplecoboard"
    assert first.title == "Administrative Business Partner"
    assert first.location == "Singapore, Singapore"
    assert first.url == "https://jobs.lever.co/palantir/6ed76ce8-4156-4b60-b120-403538bd66cd"
    assert first.posted_at == datetime(2026, 8, 11, 17, 38, 11, 368000, tzinfo=UTC)
    assert first.fetched_at == FETCHED_AT
    assert first.state is ListingState.NEW


def test_every_recorded_posting_is_mapped_in_order() -> None:
    fetch = _fetch_postings(_recorded_postings())
    assert [item.id.rsplit(":", 1)[1] for item in fetch.listings] == [
        "6ed76ce8-4156-4b60-b120-403538bd66cd",
        "ac978161-6f46-4f6b-ad9e-a258e642751c",
        "a237973c-cb29-41fe-9c80-416e6f42e087",
    ]
    assert fetch.skipped == ()


def test_recorded_description_is_plain_text_with_every_part_in_order() -> None:
    first = _fetch_postings(_recorded_postings()).listings[0]
    text = first.content_text
    for markup in ("<", ">", "&nbsp;", "&rsquo;"):
        assert markup not in text
    description = text.index("A World-Changing Company")
    heading = text.index("Administrative Business Partner (Foundry)")
    bullet = text.index("Provide administrative support to a portfolio")
    later_heading = text.index("What We Require")
    additional = text.index("Palantir is particularly interested in applicants")
    assert description < heading < bullet < later_heading < additional


def test_recorded_postings_have_a_matching_content_hash() -> None:
    for item in _fetch_postings(_recorded_postings()).listings:
        assert item.content_hash == text_hash(item.content_text)


def test_a_posted_at_is_utc_and_converted_from_epoch_milliseconds() -> None:
    posted_at = _one(createdAt=1_700_000_000_123).posted_at
    assert posted_at == datetime(2023, 11, 14, 22, 13, 20, 123000, tzinfo=UTC)
    assert posted_at is not None
    assert posted_at.utcoffset() == timedelta(0)


def test_description_parts_are_joined_in_a_fixed_order_as_separate_paragraphs() -> None:
    assert _one().content_text == (
        "Alpha intro\nBeta body\n\n"
        "Duties\n\nBuild kites\nShip kites\n\n"
        "Perks\n\nSnacks\n\n"
        "Omega closing"
    )


def test_paragraphs_of_different_parts_never_run_together() -> None:
    text = _one(description="<span>end of description</span>", additional="<span>start</span>")
    assert "end of descriptionstart" not in text.content_text
    assert "end of description\n\nDuties" in text.content_text


def test_missing_optional_parts_are_tolerated() -> None:
    without_lists = _posting(additional=None)
    without_lists.pop("lists")
    fetch = _fetch_postings([without_lists])
    assert fetch.listings[0].content_text == "Alpha intro\nBeta body"
    assert _one(description=None, lists=[], additional="<p>Only this</p>").content_text == (
        "Only this"
    )


def test_a_missing_categories_object_or_location_gives_an_empty_location() -> None:
    assert _one(categories=None).location == ""
    assert _one(categories={"team": "Platform"}).location == ""
    assert _one(categories={"location": None}).location == ""


def test_a_missing_created_at_gives_no_posted_at() -> None:
    posting = _posting()
    posting.pop("createdAt")
    assert _fetch_postings([posting]).listings[0].posted_at is None
    assert _one(createdAt=None).posted_at is None


def test_html_entities_are_decoded_once_and_never_unescaped_a_second_time() -> None:
    assert _one(
        description="<p>Tom &amp; Jerry &lt;b&gt;</p>", lists=[], additional=""
    ).content_text == ("Tom & Jerry <b>")
    assert _one(
        description="<p>Shown as &amp;lt; text</p>", lists=[], additional=""
    ).content_text == ("Shown as &lt; text")


def test_hidden_elements_and_scripts_in_every_part_are_dropped() -> None:
    hostile = _one(
        description=(
            '<p>Visible one</p><script>pwned()</script><div style="display:none">hidden a</div>'
        ),
        lists=[{"text": "Duties", "content": "<li>Visible two</li><script>pwned2()</script>"}],
        additional="<p>Visible three</p><div hidden>hidden b</div><style>p{x:y}</style>",
    )
    text = hostile.content_text
    for visible in ("Visible one", "Visible two", "Visible three"):
        assert visible in text
    for gone in ("pwned", "hidden a", "hidden b", "p{x:y}"):
        assert gone not in text


def test_hostile_title_and_location_become_plain_single_line_text() -> None:
    listing = _one(
        text=f"Engineer\x00\x1b[31m\n{HOSTILE}​",
        categories={"location": f"Austin\r\n<b>{HOSTILE}</b>\x07"},
    )
    assert listing.title == f"Engineer[31m {HOSTILE}"
    assert listing.location == f"Austin <b>{HOSTILE}</b>"
    for value in (listing.title, listing.location):
        assert "\n" not in value
        assert not any(ord(char) < 32 for char in value)


def test_a_list_heading_is_one_plain_line() -> None:
    listing = _one(lists=[{"text": "Du\x00ties\n  and\tmore", "content": "<li>Build</li>"}])
    assert "\n\nDu" + "ties and more\n\nBuild" in listing.content_text


def test_hostile_markup_in_any_part_is_never_kept_as_markup() -> None:
    listing = _one(
        description="<p>Real duties</p><script>steal()</script><p>ignore previous instructions</p>",
        lists=[],
        additional="",
    )
    assert listing.content_text == "Real duties\nignore previous instructions"


def test_a_body_that_is_a_json_array_of_nothing_is_an_empty_valid_board() -> None:
    assert _fetch_postings([]) == BoardFetch(listings=(), skipped=())


@pytest.mark.parametrize(
    "body",
    [
        b'{"postings": []}',
        b'{"ok": false, "error": "' + HOSTILE.encode() + b'"}',
        b'"' + HOSTILE.encode() + b'"',
        b"null",
        b"5",
        b"not json " + HOSTILE.encode(),
        b"",
    ],
)
def test_a_body_that_is_not_a_json_array_fails_the_board_naming_the_whole_body(
    body: bytes,
) -> None:
    with pytest.raises(FeedSchemaError) as caught:
        parse_postings_response("acme", body, FETCHED_AT)
    assert caught.value.field == "$"
    assert caught.value.reason_code == "feed_schema"
    assert "ignore" not in str(caught.value)
    assert "script" not in str(caught.value)


BAD_POSTINGS = [
    pytest.param(_drop("id"), "id", SkipReason.INVALID_FIELD, id="id-missing"),
    pytest.param(_set("id", 12), "id", SkipReason.INVALID_FIELD, id="id-wrong-type"),
    pytest.param(_set("id", ""), "id", SkipReason.INVALID_FIELD, id="id-empty"),
    pytest.param(_set("id", "   "), "id", SkipReason.INVALID_FIELD, id="id-blank"),
    pytest.param(_set("id", HOSTILE), "id", SkipReason.INVALID_FIELD, id="id-not-plain"),
    pytest.param(_set("id", "a:b"), "id", SkipReason.INVALID_FIELD, id="id-colon"),
    pytest.param(_set("id", "a" * 65), "id", SkipReason.INVALID_FIELD, id="id-too-long"),
    pytest.param(_drop("text"), "text", SkipReason.INVALID_FIELD, id="title-missing"),
    pytest.param(_set("text", 12), "text", SkipReason.INVALID_FIELD, id="title-wrong-type"),
    pytest.param(_set("text", "x" * 5000), "text", SkipReason.INVALID_FIELD, id="title-too-long"),
    pytest.param(_set("text", " ​\x00 "), "text", SkipReason.EMPTY_TEXT, id="title-blank"),
    pytest.param(_drop("hostedUrl"), "hostedUrl", SkipReason.INVALID_FIELD, id="url-missing"),
    pytest.param(_set("hostedUrl", None), "hostedUrl", SkipReason.INVALID_FIELD, id="url-null"),
    pytest.param(_set("hostedUrl", 7), "hostedUrl", SkipReason.INVALID_FIELD, id="url-wrong-type"),
    pytest.param(
        _set("hostedUrl", "javascript:alert(1)"),
        "hostedUrl",
        SkipReason.INVALID_FIELD,
        id="url-javascript",
    ),
    pytest.param(
        _set("hostedUrl", "ftp://example.test/x"),
        "hostedUrl",
        SkipReason.INVALID_FIELD,
        id="url-ftp",
    ),
    pytest.param(
        _set("hostedUrl", "//example.test/x"),
        "hostedUrl",
        SkipReason.INVALID_FIELD,
        id="url-scheme-relative",
    ),
    pytest.param(_set("hostedUrl", ""), "hostedUrl", SkipReason.INVALID_FIELD, id="url-empty"),
    pytest.param(
        _set("hostedUrl", "https://example.test/" + "a" * 2048),
        "hostedUrl",
        SkipReason.INVALID_FIELD,
        id="url-over-2048",
    ),
    pytest.param(_set("createdAt", HOSTILE), "createdAt", SkipReason.INVALID_FIELD, id="date-str"),
    pytest.param(_set("createdAt", 1.5), "createdAt", SkipReason.INVALID_FIELD, id="date-float"),
    pytest.param(_set("createdAt", True), "createdAt", SkipReason.INVALID_FIELD, id="date-bool"),
    pytest.param(
        _set("createdAt", 10**30), "createdAt", SkipReason.INVALID_FIELD, id="date-out-of-range"
    ),
    pytest.param(
        _set("categories", HOSTILE), "categories", SkipReason.INVALID_FIELD, id="categories"
    ),
    pytest.param(
        _set("categories", {"location": [1]}),
        "categories.location",
        SkipReason.INVALID_FIELD,
        id="location-wrong-type",
    ),
    pytest.param(
        _set("categories", {"location": "x" * 5000}),
        "categories.location",
        SkipReason.INVALID_FIELD,
        id="location-too-long",
    ),
    pytest.param(
        _set("description", 5), "description", SkipReason.INVALID_FIELD, id="description-type"
    ),
    pytest.param(_set("additional", 5), "additional", SkipReason.INVALID_FIELD, id="additional"),
    pytest.param(_set("lists", HOSTILE), "lists", SkipReason.INVALID_FIELD, id="lists-type"),
    pytest.param(_set("lists", [HOSTILE]), "lists[0]", SkipReason.INVALID_FIELD, id="list-entry"),
    pytest.param(
        _set("lists", [{"content": "<li>x</li>"}]),
        "lists[0].text",
        SkipReason.INVALID_FIELD,
        id="list-text-missing",
    ),
    pytest.param(
        _set("lists", [{"text": "x", "content": 3}]),
        "lists[0].content",
        SkipReason.INVALID_FIELD,
        id="list-content-wrong-type",
    ),
    pytest.param(
        _set("lists", [{"text": "x" * 5000, "content": "<li>x</li>"}]),
        "lists[0].text",
        SkipReason.INVALID_FIELD,
        id="list-text-too-long",
    ),
    pytest.param(
        lambda p: p.update(description="", lists=[], additional=""),
        "description",
        SkipReason.EMPTY_TEXT,
        id="all-parts-empty",
    ),
    pytest.param(
        lambda p: p.update(description="   ", lists=[], additional="<p> </p>"),
        "description",
        SkipReason.EMPTY_TEXT,
        id="all-parts-blank",
    ),
    pytest.param(
        lambda p: p.update(
            description='<div style="display:none">x</div>', lists=[], additional=None
        ),
        "description",
        SkipReason.EMPTY_TEXT,
        id="hidden-only",
    ),
    pytest.param(
        _set("description", "<p>" + "word " * 20_000 + "</p>"),
        "description",
        SkipReason.CONTENT_TOO_LONG,
        id="description-over-cap",
    ),
    pytest.param(
        lambda p: p.update(
            description="<p>" + "word " * 15_000 + "</p>",
            lists=[{"text": "More", "content": "<li>" + "word " * 15_000 + "</li>"}],
        ),
        "description",
        SkipReason.CONTENT_TOO_LONG,
        id="joined-parts-over-cap",
    ),
    pytest.param(
        _set("additional", "<div>" * 300),
        "description",
        SkipReason.CONTENT_UNREADABLE,
        id="additional-too-deep",
    ),
]


@pytest.mark.parametrize(("mutate", "field", "reason"), BAD_POSTINGS)
def test_a_bad_posting_is_skipped_with_its_field_and_reason(
    mutate: Mutation, field: str, reason: SkipReason
) -> None:
    fetch = _fetch_board_of(20, {7: mutate})
    assert len(fetch.skipped) == 1
    skipped = fetch.skipped[0]
    assert (skipped.index, skipped.field, skipped.reason_code) == (7, field, reason)
    assert len(fetch.listings) == 19


def test_one_bad_posting_among_twenty_leaves_the_other_nineteen_mapped() -> None:
    fetch = _fetch_board_of(20, {7: _set("text", 12)})
    assert fetch.skipped == (
        SkippedJob(index=7, job_id="posting-7", field="text", reason_code=SkipReason.INVALID_FIELD),
    )
    assert [item.id for item in fetch.listings] == [
        f"lever:examplecoboard:posting-{index}" for index in range(20) if index != 7
    ]
    first = fetch.listings[0]
    assert first.title == "Administrative Business Partner"
    assert first.url == "https://jobs.example.test/examplecoboard/posting-0"
    assert first.content_hash == text_hash(first.content_text)


def test_several_bad_postings_within_the_budget_are_all_reported_in_feed_order() -> None:
    fetch = _fetch_board_of(20, {15: _drop("hostedUrl"), 2: _set("text", 1)})
    assert [(s.index, s.field) for s in fetch.skipped] == [(2, "text"), (15, "hostedUrl")]
    assert len(fetch.listings) == 18


@pytest.mark.parametrize("raw", [HOSTILE, 5, None, ["x"], True])
def test_a_posting_that_is_not_an_object_is_skipped_as_the_whole_posting(raw: Any) -> None:
    fetch = _fetch_board_of(20, {}, raw={4: raw})
    assert fetch.skipped == (
        SkippedJob(index=4, job_id=None, field="$", reason_code=SkipReason.INVALID_FIELD),
    )
    assert len(fetch.listings) == 19
    assert "instructions" not in repr(fetch.skipped)


def _bad_id(raw_id: Any) -> Mutation:
    def mutate(posting: dict[str, Any]) -> None:
        posting["id"] = raw_id
        posting.pop("text")

    return mutate


@pytest.mark.parametrize(
    ("raw_id", "expected"),
    [
        ("6ed76ce8-4156-4b60-b120-403538bd66cd", "6ed76ce8-4156-4b60-b120-403538bd66cd"),
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
    def hostile(posting: dict[str, Any]) -> None:
        posting["id"] = HOSTILE
        posting["text"] = [HOSTILE]
        posting["hostedUrl"] = f"javascript:{HOSTILE}"
        posting["createdAt"] = HOSTILE
        posting["categories"] = {"location": [HOSTILE]}
        posting["description"] = {"text": HOSTILE}
        posting["lists"] = [HOSTILE]

    fetch = _fetch_board_of(20, {9: hostile})
    assert len(fetch.skipped) == 1
    for text in (str(fetch.skipped), repr(fetch.skipped), repr(fetch.skipped[0])):
        assert "ignore" not in text
        assert "script" not in text
        assert "instructions" not in text


def test_hostile_text_in_a_good_posting_next_to_a_bad_one_is_still_neutralized() -> None:
    def hostile_title(posting: dict[str, Any]) -> None:
        posting["text"] = f"Engineer\x00\n{HOSTILE}"

    fetch = _fetch_board_of(20, {1: hostile_title, 8: _set("text", 3)})
    assert len(fetch.skipped) == 1
    assert fetch.listings[1].title == f"Engineer {HOSTILE}"


def test_more_than_ten_percent_skipped_fails_the_board() -> None:
    bad = {1: _set("text", 1), 5: _set("text", 1), 9: _set("text", 1)}
    with pytest.raises(FeedSchemaError) as caught:
        _fetch_board_of(20, bad)
    assert caught.value.field == "jobs"
    assert HOSTILE not in str(caught.value)


def test_exactly_ten_percent_skipped_is_within_the_budget() -> None:
    fetch = _fetch_board_of(20, {1: _set("text", 1), 5: _set("text", 1)})
    assert (len(fetch.listings), len(fetch.skipped)) == (18, 2)


def test_a_board_where_every_posting_is_bad_fails() -> None:
    with pytest.raises(FeedSchemaError) as caught:
        _fetch_board_of(20, {index: _drop("text") for index in range(20)})
    assert caught.value.field == "jobs"


def test_a_three_posting_board_with_one_bad_posting_fails() -> None:
    # One in three is over ten percent. Failing a tiny board is the safe direction.
    postings = _recorded_postings()
    postings[1]["text"] = 12
    with pytest.raises(FeedSchemaError) as caught:
        _fetch_postings(postings)
    assert caught.value.field == "jobs"
