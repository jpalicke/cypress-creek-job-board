# ABOUTME: Tests loading score weights from config/weights.yaml, the real file and bad files.
# ABOUTME: The shipped file must equal the published defaults so docs and data cannot drift.
from pathlib import Path

import pytest

from cypress_creek.scoring.score import DEFAULT_WEIGHTS_PATH, Weights, WeightsError, load_weights


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "weights.yaml"
    path.write_text(text, encoding="utf8")
    return path


def test_shipped_file_equals_the_published_defaults() -> None:
    assert load_weights() == Weights()
    assert DEFAULT_WEIGHTS_PATH.is_file()


def test_an_override_file_is_applied(tmp_path: Path) -> None:
    path = write(tmp_path, "weights:\n  required: 5\n  partial: 0.25\n")
    weights = load_weights(path)
    assert (weights.required, weights.partial, weights.preferred) == (5, 0.25, 1)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("weights: [1, 2]\n", "top level 'weights' mapping"),
        ("other: 1\n", "top level 'weights' mapping"),
        ("weights: {required: 0}\n", "invalid weights"),
        ("weights: {strong: 0.2, partial: 0.5}\n", "invalid weights"),
        ("weights: {bogus: 1}\n", "invalid weights"),
        ("weights: {required: [1}\n", "invalid YAML"),
    ],
)
def test_bad_files_are_refused(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(WeightsError, match=message):
        load_weights(write(tmp_path, text))


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(WeightsError, match="not found"):
        load_weights(tmp_path / "nope.yaml")
