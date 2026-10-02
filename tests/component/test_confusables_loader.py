# ABOUTME: Tests loading the Unicode confusables data from config/confusables.txt, real and bad.
# ABOUTME: The shipped file must hold the known lookalikes and every malformed line is refused.
from pathlib import Path

import pytest

from cypress_creek.storage.company_key import (
    DEFAULT_CONFUSABLES_PATH,
    CompanyNameError,
    ConfusablesError,
    company_key,
    load_confusables,
)


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "confusables.txt"
    path.write_text(text, encoding="utf8")
    return path


def test_the_shipped_data_holds_the_known_lookalikes() -> None:
    table = load_confusables(DEFAULT_CONFUSABLES_PATH)
    assert len(table) > 5000
    assert table["а"] == "a"
    assert table["ο"] == "o"
    assert table["Ａ"] == "A"
    assert table["m"] == "rn"
    assert table["0"] == "O"
    assert table["1"] == "l"


def test_comments_blank_lines_and_trailing_notes_are_ignored(tmp_path: Path) -> None:
    path = write(tmp_path, "﻿# header\n\n0430 ;\t0061 ;\tMA\t# note\n006D ;\t0072 006E ;\tMA\n")
    assert load_confusables(path) == {"а": "a", "m": "rn"}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "no entries"),
        ("# only a comment\n", "no entries"),
        ("0430 ;\t0061\n", "line 1: expected"),
        ("zzzz ;\t0061 ;\tMA\n", "line 1: invalid code point"),
        ("110000 ;\t0061 ;\tMA\n", "line 1: invalid code point"),
        ("0430 ;\t ;\tMA\n", "line 1: needs one source"),
        ("0430 0431 ;\t0061 ;\tMA\n", "line 1: needs one source"),
        ("# c\n0430 ;\t0061 ;\tMA\n0430 ;\t0062 ;\tMA\n", "line 3: 0430 is listed twice"),
    ],
)
def test_bad_data_is_refused(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ConfusablesError, match=message):
        load_confusables(write(tmp_path, text))


def test_missing_data_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfusablesError, match="not found"):
        load_confusables(tmp_path / "nope.txt")


def test_every_character_in_the_shipped_data_folds_to_a_stable_key() -> None:
    for source, target in load_confusables(DEFAULT_CONFUSABLES_PATH).items():
        for name in (source, f"a{source}b", target):
            try:
                key = company_key(name)
            except CompanyNameError:
                continue
            assert company_key(key) == key, f"{name!r} is not stable"
