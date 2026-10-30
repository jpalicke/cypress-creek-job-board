# ABOUTME: Tests the pure parts of the discovery run: ranking order and the listing to posting step.
# ABOUTME: Scored rows sort by score then recency, then no score rows, then unscored rows.
from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from cypress_creek.discovery.adapters.base import Listing
from cypress_creek.discovery.run import RankedListing, ScoreStatus, posting_from_listing, rank
from cypress_creek.ingest.hashing import text_hash
from cypress_creek.ingest.models import PostingSource

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def make_listing(job_id: str, posted_days_ago: int | None = 1) -> Listing:
    return Listing(
        id=f"lever:acme:{job_id}",
        ats="lever",
        slug="acme",
        title=f"Engineer {job_id}",
        location="Austin",
        url=f"https://example.test/{job_id}",
        posted_at=None if posted_days_ago is None else NOW - timedelta(days=posted_days_ago),
        fetched_at=NOW,
        content_text=f"Build things {job_id}.",
        content_hash="a" * 64,
    )


def row(
    job_id: str,
    status: ScoreStatus,
    score: float | None = None,
    posted_days_ago: int | None = 1,
) -> RankedListing:
    return RankedListing(
        listing=make_listing(job_id, posted_days_ago),
        urls=(f"https://example.test/{job_id}",),
        status=status,
        score=score,
        strong=0,
        partial=0,
        none=0,
        incomplete=False,
        run_id=None if status is ScoreStatus.UNSCORED else "run-1",
    )


def ids(rows: list[RankedListing]) -> list[str]:
    return [item.listing.id.rsplit(":", 1)[1] for item in rows]


def test_ranking_is_by_score_then_recency_then_no_score_then_unscored() -> None:
    rows = [
        row("unscored", ScoreStatus.UNSCORED),
        row("no-score", ScoreStatus.NO_SCORE),
        row("low", ScoreStatus.SCORED, 20.0),
        row("b-old", ScoreStatus.SCORED, 80.0, posted_days_ago=30),
        row("c-new", ScoreStatus.SCORED, 80.0, posted_days_ago=2),
        row("a-undated", ScoreStatus.SCORED, 80.0, posted_days_ago=None),
    ]
    assert ids(rank(rows)) == [
        "c-new",
        "b-old",
        "a-undated",
        "low",
        "no-score",
        "unscored",
    ]


def test_a_zero_score_is_a_score_and_ranks_above_no_score() -> None:
    rows = [row("none", ScoreStatus.NO_SCORE), row("zero", ScoreStatus.SCORED, 0.0)]
    assert ids(rank(rows)) == ["zero", "none"]


def test_equal_rows_fall_back_to_the_id() -> None:
    rows = [row("b", ScoreStatus.SCORED, 50.0), row("a", ScoreStatus.SCORED, 50.0)]
    assert ids(rank(rows)) == ["a", "b"]


@given(
    st.lists(
        st.tuples(
            st.sampled_from(list(ScoreStatus)),
            st.one_of(st.none(), st.floats(0, 100)),
            st.one_of(st.none(), st.integers(0, 5)),
        ),
        max_size=10,
    ),
    st.randoms(use_true_random=False),
)
def test_ranking_does_not_depend_on_input_order(
    spec: list[tuple[ScoreStatus, float | None, int | None]], rng: object
) -> None:
    rows = [
        row(str(index), status, score if status is ScoreStatus.SCORED else None, days)
        for index, (status, score, days) in enumerate(spec)
    ]
    shuffled = list(rows)
    rng.shuffle(shuffled)  # type: ignore[attr-defined]
    assert rank(rows) == rank(shuffled)


def test_a_listing_becomes_a_feed_posting_with_its_own_text_and_hash() -> None:
    listing = make_listing("1")
    posting = posting_from_listing(listing)
    assert posting.id == listing.id
    assert posting.source is PostingSource.FEED
    assert posting.text == listing.content_text
    assert posting.text_hash == text_hash(listing.content_text)
    assert posting.origin_url == listing.url
    assert posting.created_at == listing.fetched_at
