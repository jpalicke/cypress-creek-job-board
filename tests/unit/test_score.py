# ABOUTME: Tests the score formula against hand computed arithmetic and the no score case.
# ABOUTME: Hypothesis properties check bounds and monotonicity for any mix of matches.
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from cypress_creek.ingest.models import Importance
from cypress_creek.scoring.score import Match, Weights, downgrade, lowest, score
from cypress_creek.scoring.support import Support

REQUIRED, PREFERRED, UNSPECIFIED = Importance.REQUIRED, Importance.PREFERRED, Importance.UNSPECIFIED
STRONG, PARTIAL, NONE = Support.STRONG, Support.PARTIAL, Support.NONE


def match(
    n: int, importance: Importance, support: Support, ceiling: Support | None = None
) -> Match:
    return Match(
        requirement_id=f"R-{n}", importance=importance, ceiling=ceiling or support, support=support
    )


def test_zero_requirements_is_no_score_not_100_and_not_0() -> None:
    result = score([])
    assert result.score is None
    assert result.total == 0
    assert result.supported == 0


def test_one_required_strong_and_one_preferred_none_is_75() -> None:
    result = score([match(1, REQUIRED, STRONG), match(2, PREFERRED, NONE)])
    assert result.score == 100 * 3 / 4


def test_partial_counts_half() -> None:
    result = score([match(1, UNSPECIFIED, PARTIAL)])
    assert result.score == 100 * (2 * 0.5) / 2


def test_mixed_example_matches_hand_arithmetic() -> None:
    matches = [
        match(1, REQUIRED, STRONG),
        match(2, REQUIRED, PARTIAL),
        match(3, UNSPECIFIED, NONE),
        match(4, PREFERRED, PARTIAL),
    ]
    expected = 100 * (3 * 1.0 + 3 * 0.5 + 2 * 0.0 + 1 * 0.5) / (3 + 3 + 2 + 1)
    assert score(matches).score == pytest.approx(expected)


def test_all_none_is_zero_not_no_score() -> None:
    assert score([match(1, REQUIRED, NONE)]).score == 0


def test_counts_and_supported_out_of_total() -> None:
    result = score(
        [match(1, REQUIRED, STRONG), match(2, REQUIRED, PARTIAL), match(3, PREFERRED, NONE)]
    )
    assert result.total == 3
    assert result.supported == 2
    assert result.counts == {STRONG: 1, PARTIAL: 1, NONE: 1}


def test_inputs_echo_every_weight_and_value_used() -> None:
    result = score([match(1, REQUIRED, PARTIAL)])
    assert result.inputs.weights == Weights()
    [line] = result.inputs.lines
    assert (line.requirement_id, line.importance, line.support) == ("R-1", REQUIRED, PARTIAL)
    assert (line.weight, line.value) == (3, 0.5)


def test_custom_weights_are_applied_and_echoed() -> None:
    weights = Weights(required=5, unspecified=1, preferred=1)
    result = score([match(1, REQUIRED, STRONG), match(2, PREFERRED, NONE)], weights)
    assert result.score == 100 * 5 / 6
    assert result.inputs.weights == weights


def test_default_weights_are_the_published_ones() -> None:
    weights = Weights()
    assert (weights.required, weights.unspecified, weights.preferred) == (3, 2, 1)
    assert (weights.strong, weights.partial, weights.none) == (1.0, 0.5, 0.0)


@pytest.mark.parametrize(
    "bad",
    [
        {"required": 0},
        {"preferred": -1},
        {"strong": 1.5},
        {"none": -0.1},
        {"partial": 0.9, "strong": 0.5},
        {"partial": 0.5, "none": 0.7},
        {"extra": 1},
    ],
)
def test_invalid_weights_are_rejected(bad: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        Weights(**bad)


def test_downgrade_lowers_one_step_and_stops_at_none() -> None:
    assert downgrade(STRONG) == PARTIAL
    assert downgrade(PARTIAL) == NONE
    assert downgrade(NONE) == NONE


@pytest.mark.parametrize("a", list(Support))
@pytest.mark.parametrize("b", list(Support))
def test_lowest_is_the_lower_of_two_and_never_the_higher(a: Support, b: Support) -> None:
    order = [NONE, PARTIAL, STRONG]
    assert lowest(a, b) == order[min(order.index(a), order.index(b))]


def test_a_raised_support_is_refused() -> None:
    with pytest.raises(ValidationError, match="above its ceiling"):
        match(1, REQUIRED, STRONG, ceiling=PARTIAL)


def test_a_drop_of_two_steps_is_accepted() -> None:
    assert match(1, REQUIRED, NONE, ceiling=STRONG).support == NONE


def test_a_one_step_downgrade_is_accepted() -> None:
    assert match(1, REQUIRED, PARTIAL, ceiling=STRONG).support == PARTIAL


importances = st.sampled_from(list(Importance))
supports = st.sampled_from(list(Support))


@st.composite
def matches(draw: st.DrawFn) -> list[Match]:
    items = draw(st.lists(st.tuples(importances, supports, st.booleans()), max_size=30))
    return [
        match(n, importance, downgrade(ceiling) if lowered else ceiling, ceiling)
        for n, (importance, ceiling, lowered) in enumerate(items)
    ]


@given(matches())
def test_score_is_none_or_between_0_and_100(items: list[Match]) -> None:
    result = score(items)
    if not items:
        assert result.score is None
    else:
        assert result.score is not None
        assert 0 <= result.score <= 100


@given(matches())
def test_a_downgrade_never_raises_the_score(items: list[Match]) -> None:
    at_ceiling = [m.model_copy(update={"support": m.ceiling}) for m in items]
    ceiling_score, actual_score = score(at_ceiling).score, score(items).score
    if items:
        assert ceiling_score is not None and actual_score is not None
        assert actual_score <= ceiling_score + 1e-9


@given(st.lists(st.tuples(importances, supports), min_size=1, max_size=20), st.data())
def test_score_is_monotone_in_support(
    pairs: list[tuple[Importance, Support]], data: st.DataObject
) -> None:
    index = data.draw(st.integers(0, len(pairs) - 1))
    higher = data.draw(supports)
    before = [match(n, imp, sup) for n, (imp, sup) in enumerate(pairs)]
    raised = list(pairs)
    if list(Support).index(higher) > list(Support).index(raised[index][1]):
        raised[index] = (raised[index][0], higher)
    after = [match(n, imp, sup) for n, (imp, sup) in enumerate(raised)]
    low, high = score(before).score, score(after).score
    assert low is not None and high is not None
    assert low <= high + 1e-9


def test_pipeline_doc_worked_example_matches_the_code() -> None:
    matches = [
        match(1, REQUIRED, STRONG),
        match(2, REQUIRED, PARTIAL),
        match(3, UNSPECIFIED, NONE),
        match(4, PREFERRED, PARTIAL),
    ]
    result = score(matches).score
    assert result is not None
    doc = (Path(__file__).parents[2] / "docs" / "pipeline.md").read_text(encoding="utf-8")
    assert f"score               = 100 * 5.0 / 9 = {result:.1f}" in doc
