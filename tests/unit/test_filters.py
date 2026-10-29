# ABOUTME: Tests the deterministic listing filters and the per-filter counts of what they removed.
# ABOUTME: No model is involved, and the age filter reads an injected today.
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from cypress_creek.discovery.adapters.base import Listing
from cypress_creek.discovery.filters import FilterName, ListingFilters, apply_filters

TODAY = date(2026, 3, 31)
NOW = datetime(2026, 3, 31, 12, tzinfo=UTC)


def make(job_id: str = "1", **overrides: object) -> Listing:
    fields: dict[str, object] = {
        "id": f"greenhouse:acme:{job_id}",
        "ats": "greenhouse",
        "slug": "acme",
        "title": "Platform Engineer",
        "location": "Austin, TX",
        "url": f"https://example.test/{job_id}",
        "posted_at": NOW,
        "fetched_at": NOW,
        "content_text": "Build services in Python and Go.",
        "content_hash": "abc",
    }
    fields.update(overrides)
    return Listing(**fields)  # type: ignore[arg-type]


def kept_ids(listings: list[Listing], **config: object) -> list[str]:
    report = apply_filters(listings, ListingFilters(**config), TODAY)  # type: ignore[arg-type]
    return [item.id for item in report.kept]


def test_no_filters_keep_everything_and_remove_nothing() -> None:
    report = apply_filters([make("1"), make("2")], ListingFilters(), TODAY)
    assert len(report.kept) == 2
    assert report.removed == {name: 0 for name in FilterName}
    assert report.total_removed == 0


def test_include_keywords_keep_a_listing_that_has_any_of_them() -> None:
    listings = [make("1"), make("2", content_text="Paint walls."), make("3", title="Rust Dev")]
    assert kept_ids(listings, include_keywords=("python", "rust")) == [
        "greenhouse:acme:1",
        "greenhouse:acme:3",
    ]


def test_a_keyword_matches_whole_words_only() -> None:
    assert kept_ids([make(content_text="We use javascript.")], include_keywords=("java",)) == []
    assert kept_ids([make(content_text="We use C++ daily.")], include_keywords=("c++",)) != []


def test_exclude_keywords_remove_a_listing_that_has_any_of_them() -> None:
    listings = [make("1"), make("2", content_text="Requires a security clearance.")]
    assert kept_ids(listings, exclude_keywords=("Security   Clearance",)) == ["greenhouse:acme:1"]


def test_location_keeps_a_listing_whose_location_names_an_allowed_place() -> None:
    listings = [make("1"), make("2", location="Berlin, Germany"), make("3", location="")]
    assert kept_ids(listings, locations=("austin", "berlin")) == [
        "greenhouse:acme:1",
        "greenhouse:acme:2",
    ]


def test_remote_true_keeps_only_remote_listings() -> None:
    listings = [make("1"), make("2", location="Remote - US"), make("3", title="Remote Engineer")]
    assert kept_ids(listings, remote=True) == ["greenhouse:acme:2", "greenhouse:acme:3"]


def test_remote_false_drops_remote_listings() -> None:
    listings = [make("1"), make("2", location="Remote - US")]
    assert kept_ids(listings, remote=False) == ["greenhouse:acme:1"]


def test_seniority_terms_remove_a_listing_by_its_title_only() -> None:
    listings = [
        make("1", title="Senior Engineer"),
        make("2", content_text="Work with senior staff."),
        make("3", title="Principal Engineer"),
    ]
    assert kept_ids(listings, exclude_seniority=("senior", "principal")) == ["greenhouse:acme:2"]


def test_age_removes_listings_posted_more_than_n_days_before_today() -> None:
    listings = [
        make("1", posted_at=datetime(2026, 3, 1, tzinfo=UTC)),
        make("2", posted_at=datetime(2026, 2, 28, 23, tzinfo=UTC)),
        make("3", posted_at=datetime(2026, 4, 5, tzinfo=UTC)),
    ]
    assert kept_ids(listings, max_age_days=30) == ["greenhouse:acme:1", "greenhouse:acme:3"]


def test_a_listing_with_no_posted_date_is_kept_by_the_age_filter() -> None:
    assert kept_ids([make(posted_at=None)], max_age_days=1) == ["greenhouse:acme:1"]


def test_the_report_counts_each_removal_under_the_first_filter_that_rejects_it() -> None:
    listings = [
        make("1", posted_at=datetime(2025, 1, 1, tzinfo=UTC), title="Senior Engineer"),
        make("2", title="Senior Engineer"),
        make("3", location="Berlin"),
        make("4", content_text="Paint."),
        make("5"),
    ]
    report = apply_filters(
        listings,
        ListingFilters(
            max_age_days=30,
            locations=("austin",),
            exclude_seniority=("senior",),
            include_keywords=("python",),
        ),
        TODAY,
    )
    assert [item.id for item in report.kept] == ["greenhouse:acme:5"]
    assert report.removed[FilterName.AGE] == 1
    assert report.removed[FilterName.SENIORITY] == 1
    assert report.removed[FilterName.LOCATION] == 1
    assert report.removed[FilterName.INCLUDE] == 1
    assert report.removed[FilterName.EXCLUDE] == 0
    assert report.total_removed == 4


def test_a_filter_that_removes_everything_says_which_filter_did() -> None:
    report = apply_filters(
        [make("1"), make("2")], ListingFilters(include_keywords=("cobol",)), TODAY
    )
    assert report.kept == ()
    assert report.removed[FilterName.INCLUDE] == 2


def test_the_kept_listings_keep_their_input_order() -> None:
    listings = [make("b"), make("a"), make("c")]
    assert kept_ids(listings) == ["greenhouse:acme:b", "greenhouse:acme:a", "greenhouse:acme:c"]


@pytest.mark.parametrize(
    "config",
    [
        {"include_keywords": ("",)},
        {"exclude_keywords": ("  ",)},
        {"locations": ("...",)},
        {"exclude_seniority": ("",)},
        {"max_age_days": 0},
        {"unknown": 1},
    ],
)
def test_a_bad_filter_config_is_refused(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ListingFilters(**config)  # type: ignore[arg-type]
