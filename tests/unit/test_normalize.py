# ABOUTME: Tests posting text normalization: stripping hostile characters, NFKC, whitespace, cap.
# ABOUTME: Includes Hypothesis properties for idempotence and for typed-errors-only behavior.
import hashlib

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cypress_creek.ingest.errors import EmptyPosting, PostingTooLong
from cypress_creek.ingest.models import PostingWarning, WarningKind
from cypress_creek.ingest.normalize import MAX_CHARS, normalize, text_hash

ZERO_WIDTH = "​‌‍⁠﻿"
BIDI = "‎‏‪‫‬‭‮⁦⁧⁨⁩"
STRIPPED = ZERO_WIDTH + BIDI + "\x00\x07\x1b\x7f\x85"


def test_zero_width_and_bidi_characters_are_stripped_with_a_count() -> None:
    raw = "Py​thon ‮developer‬\x00"
    text, warnings = normalize(raw)
    assert text == "Python developer"
    assert warnings == [PostingWarning(kind=WarningKind.CONTROL_CHARS_STRIPPED, count=4)]


def test_clean_text_has_no_warnings() -> None:
    assert normalize("Plain posting") == ("Plain posting", [])


def test_over_the_cap_is_rejected_not_cut() -> None:
    with pytest.raises(PostingTooLong, match=str(MAX_CHARS)):
        normalize("a" * (MAX_CHARS + 1))


def test_exactly_the_cap_is_accepted() -> None:
    text, _ = normalize("a" * MAX_CHARS)
    assert len(text) == MAX_CHARS


def test_huge_raw_input_is_rejected_before_any_work() -> None:
    with pytest.raises(PostingTooLong):
        normalize(" " * (MAX_CHARS * 10 + 1))


@pytest.mark.parametrize("raw", ["", "   \n\t  ", ZERO_WIDTH + "\x00"])
def test_empty_after_normalization_is_rejected(raw: str) -> None:
    with pytest.raises(EmptyPosting):
        normalize(raw)


def test_nfkc_folds_compatibility_forms() -> None:
    text, _ = normalize("Ｐｙｔｈｏｎ ﬁnd ①")
    assert text == "Python find 1"


def test_nonbreaking_space_becomes_a_plain_space() -> None:
    assert normalize("a  b")[0] == "a b"


def test_runs_of_spaces_and_tabs_collapse() -> None:
    assert normalize("a  \t  b")[0] == "a b"


def test_single_newlines_are_kept_and_blank_line_runs_collapse() -> None:
    text, _ = normalize("Requirements:\n- one\n- two\n\n\n\n\nBenefits:\n- x")
    assert text == "Requirements:\n- one\n- two\n\nBenefits:\n- x"


def test_line_endings_are_unified_and_edges_trimmed() -> None:
    assert normalize("  \r\na\r\nb\rc d  \n")[0] == "a\nb\nc\nd"


def test_trailing_spaces_on_a_line_are_dropped() -> None:
    assert normalize("a  \nb")[0] == "a\nb"


def test_hash_is_stable_sha256_of_the_normalized_text() -> None:
    assert text_hash("abc") == hashlib.sha256(b"abc").hexdigest()
    assert text_hash("abc") == text_hash("abc")


@given(st.text(max_size=400))
def test_normalization_is_idempotent(raw: str) -> None:
    try:
        once, _ = normalize(raw)
    except EmptyPosting:
        return
    assert normalize(once) == (once, [])


@given(st.text(alphabet=st.sampled_from(list(STRIPPED + "ab \n")), max_size=200))
def test_output_never_contains_a_stripped_character(raw: str) -> None:
    try:
        text, _ = normalize(raw)
    except EmptyPosting:
        return
    assert not set(text) & set(STRIPPED)


@given(st.text(max_size=400))
def test_only_text_or_a_typed_error_comes_back(raw: str) -> None:
    try:
        text, _ = normalize(raw)
    except (EmptyPosting, PostingTooLong):
        return
    assert isinstance(text, str)
    assert text == text.strip()
