# ABOUTME: Tests building a normalized Posting from raw text for the paste, link and PDF sources.
# ABOUTME: The builder is the one place text becomes a Posting, so hashes and ids cannot drift.
from datetime import UTC, datetime

import pytest

from cypress_creek.ingest.build import build_posting, new_posting_id
from cypress_creek.ingest.errors import EmptyPosting, PostingTooLong
from cypress_creek.ingest.hashing import text_hash
from cypress_creek.ingest.models import Extractor, PostingSource, WarningKind

NOW = datetime(2026, 10, 29, tzinfo=UTC)
EXTRACTOR = Extractor(name="paste", version="1")


def test_text_is_normalized_hashed_and_warned_about() -> None:
    posting = build_posting(
        "Python​  experience\r\n\r\n\r\n\r\nrequired",
        PostingSource.PASTE,
        EXTRACTOR,
        now=NOW,
    )

    assert posting.text == "Python experience\n\nrequired"
    assert posting.text_hash == text_hash(posting.text)
    assert [(w.kind, w.count) for w in posting.warnings] == [
        (WarningKind.CONTROL_CHARS_STRIPPED, 1)
    ]
    assert posting.created_at == NOW
    assert posting.origin_url is None


def test_a_link_keeps_its_origin_and_an_id_is_made_when_none_is_given() -> None:
    posting = build_posting(
        "Role", PostingSource.LINK, EXTRACTOR, origin_url="https://example.com/job", now=NOW
    )

    assert posting.origin_url == "https://example.com/job"
    assert posting.id.startswith("post-")
    assert len(posting.id) == len("post-") + 16


def test_ids_are_unique_and_plain() -> None:
    ids = {new_posting_id() for _ in range(50)}

    assert len(ids) == 50
    assert all(i.removeprefix("post-").isalnum() for i in ids)


def test_an_explicit_id_is_used() -> None:
    assert (
        build_posting("Role", PostingSource.PASTE, EXTRACTOR, posting_id="p1", now=NOW).id == "p1"
    )


def test_empty_and_over_long_text_raise_the_typed_errors() -> None:
    with pytest.raises(EmptyPosting):
        build_posting(" \n\t ", PostingSource.PASTE, EXTRACTOR, now=NOW)
    with pytest.raises(PostingTooLong):
        build_posting("a" * 50_001, PostingSource.PASTE, EXTRACTOR, now=NOW)
