# ABOUTME: Tests conservative listing dedupe: same id first, then an exact normalized fingerprint.
# ABOUTME: Near matches and ambiguous groups stay separate, and the result ignores input order.
import dataclasses
from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from cypress_creek.discovery.adapters.base import Listing
from cypress_creek.discovery.dedupe import MergedListing, dedupe, fingerprint_text

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
KEYS = {
    ("greenhouse", "acme"): "acme",
    ("lever", "acme"): "acme",
    ("ashby", "acme"): "acme",
    ("greenhouse", "other"): "other",
}


def make(
    ats: str = "greenhouse",
    slug: str = "acme",
    job_id: str = "1",
    title: str = "Senior Engineer",
    location: str = "Austin, TX",
    **overrides: object,
) -> Listing:
    fields: dict[str, object] = {
        "id": f"{ats}:{slug}:{job_id}",
        "ats": ats,
        "slug": slug,
        "title": title,
        "location": location,
        "url": f"https://example.test/{ats}/{slug}/{job_id}",
        "posted_at": None,
        "fetched_at": NOW,
        "content_text": "Build things.",
        "content_hash": "abc",
    }
    fields.update(overrides)
    return Listing(**fields)  # type: ignore[arg-type]


def test_the_same_job_from_two_sources_merges_only_on_an_exact_match() -> None:
    same_a = make("greenhouse", job_id="1", title="Senior Engineer")
    same_b = make("lever", job_id="x", title="  SENIOR   engineer. ")
    near = make("ashby", job_id="y", title="Staff Engineer")
    merged = dedupe([same_a, same_b, near], KEYS)
    assert len(merged) == 2
    by_size = sorted(merged, key=lambda m: len(m.urls))
    assert by_size[0].listing.id == "ashby:acme:y"
    assert set(by_size[1].urls) == {same_a.url, same_b.url}


def test_one_word_of_difference_in_the_title_does_not_merge() -> None:
    merged = dedupe(
        [make("greenhouse", title="Senior Engineer"), make("lever", title="Senior Engineers")],
        KEYS,
    )
    assert len(merged) == 2


def test_a_different_location_does_not_merge() -> None:
    merged = dedupe([make("greenhouse"), make("lever", location="Remote")], KEYS)
    assert len(merged) == 2


def test_a_region_is_never_expanded_to_a_city() -> None:
    merged = dedupe(
        [make("greenhouse", location="Texas"), make("lever", location="Austin, Texas")], KEYS
    )
    assert len(merged) == 2


def test_a_different_company_does_not_merge() -> None:
    merged = dedupe([make("greenhouse", slug="acme"), make("greenhouse", slug="other")], KEYS)
    assert len(merged) == 2


def test_the_company_compares_by_company_key_not_by_slug() -> None:
    keys = {("greenhouse", "acme"): "acme", ("lever", "acme-inc"): "acme"}
    merged = dedupe([make("greenhouse"), make("lever", slug="acme-inc")], keys)
    assert len(merged) == 1


def test_punctuation_that_changes_the_meaning_is_kept() -> None:
    merged = dedupe(
        [make("greenhouse", title="C++ Engineer"), make("lever", title="C Engineer")], KEYS
    )
    assert len(merged) == 2
    merged = dedupe([make("greenhouse", title="C# Dev"), make("lever", title="C Dev")], KEYS)
    assert len(merged) == 2


def test_the_same_id_from_the_same_source_is_one_listing() -> None:
    older = make(fetched_at=NOW, content_hash="old")
    newer = make(fetched_at=NOW + timedelta(hours=1), content_hash="new")
    merged = dedupe([older, newer], KEYS)
    assert len(merged) == 1
    assert merged[0].listing.content_hash == "new"
    assert merged[0].urls == (newer.url,)


def test_two_roles_with_the_same_fingerprint_on_one_source_stay_separate() -> None:
    first = make("greenhouse", job_id="1")
    second = make("greenhouse", job_id="2")
    assert len(dedupe([first, second], KEYS)) == 2


def test_an_ambiguous_group_is_not_merged_at_all() -> None:
    group = [make("greenhouse", job_id="1"), make("greenhouse", job_id="2"), make("lever")]
    assert len(dedupe(group, KEYS)) == 3


def test_a_listing_with_no_known_company_is_never_merged_across_sources() -> None:
    merged = dedupe([make("greenhouse", slug="ghost"), make("lever", slug="ghost")], KEYS)
    assert len(merged) == 2


def test_a_merge_keeps_every_url_and_the_earliest_posted_at() -> None:
    early = NOW - timedelta(days=9)
    merged = dedupe(
        [
            make("greenhouse", posted_at=NOW),
            make("lever", posted_at=early),
            make("ashby", posted_at=None),
        ],
        KEYS,
    )
    (only,) = merged
    assert only.listing.posted_at == early
    assert len(only.urls) == 3
    assert only.source_ids == tuple(sorted(only.source_ids))
    assert len(only.source_ids) == 3


def test_a_merge_with_no_dates_has_no_posted_at() -> None:
    (only,) = dedupe([make("greenhouse"), make("lever")], KEYS)
    assert only.listing.posted_at is None


def test_an_empty_input_gives_an_empty_result() -> None:
    assert dedupe([], KEYS) == []


def test_fingerprint_text_folds_unicode_case_space_and_punctuation() -> None:
    assert fingerprint_text("  Ｓenior  Engineer, (Platform)! ") == "senior engineer platform"
    assert fingerprint_text("ǅ") == fingerprint_text("ǆ")


def test_a_merged_listing_is_immutable() -> None:
    (only,) = dedupe([make()], KEYS)
    assert isinstance(only, MergedListing)
    try:
        only.urls = ()  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("MergedListing must be frozen")


_atss = st.sampled_from(["greenhouse", "lever", "ashby"])
_titles = st.sampled_from(
    ["Engineer", "engineer.", "Staff Engineer", "Designer", "C++ Dev", "C Dev"]
)
_places = st.sampled_from(["Austin", "austin ", "Remote", "Texas"])
_listings = st.builds(
    lambda ats, n, title, place: make(ats, job_id=str(n), title=title, location=place),
    _atss,
    st.integers(0, 3),
    _titles,
    _places,
)


@given(st.lists(_listings, max_size=12), st.randoms(use_true_random=False))
def test_merge_is_independent_of_input_order(items: list[Listing], rng: object) -> None:
    shuffled = list(items)
    rng.shuffle(shuffled)  # type: ignore[attr-defined]
    assert dedupe(items, KEYS) == dedupe(shuffled, KEYS)


@given(st.lists(_listings, max_size=12, unique_by=lambda item: item.id))
def test_merge_never_joins_listings_with_different_fingerprints(items: list[Listing]) -> None:
    by_id = {item.id: item for item in items}
    for merged in dedupe(items, KEYS):
        members = [by_id[source_id] for source_id in merged.source_ids]
        prints = {(fingerprint_text(m.title), fingerprint_text(m.location)) for m in members}
        assert len(prints) == 1
        assert len({m.ats for m in members}) == len(members)
