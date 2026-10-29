# ABOUTME: Tests the E1 to E4 metrics against values worked out by hand from tiny labeled cases.
# ABOUTME: Covers matching, grounding, raises before the clamp, aggregation and not run.
from pathlib import Path

from eval_support import Got, Want, labels_for, report_for
from hypothesis import given
from hypothesis import strategies as st

from cypress_creek.facts import load_bank
from cypress_creek.facts.models import Bank
from cypress_creek.ingest.models import Importance
from cypress_creek.pipeline.entail import Entailment
from cypress_creek.pipeline.extract import DropReason
from cypress_creek.pipeline.report import ReportStatus
from cypress_creek.scoring.support import Support
from evals.harness.metrics import (
    METRICS,
    Direction,
    aggregate,
    pool,
    repeat_values,
    score_case,
)

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = load_bank(ROOT / "evals" / "bank" / "sample_bank.yaml", strict=True)
LURE = load_bank(ROOT / "evals" / "bank" / "sample_bank_unverified.yaml")
BANK = Bank(facts=[*SAMPLE.facts, *LURE.facts])

POSTING = (
    "Requirements:\n"
    "You must know Python.\n"
    "You must know Rust.\n"
    "You must know Kubernetes.\n"
    "You must know Go.\n"
)
PYTHON = "You must know Python."
RUST = "You must know Rust."
KUBERNETES = "You must know Kubernetes."
GO = "You must know Go."

WANTS = [
    Want(PYTHON, Support.STRONG, fact_ids=("F-0001",)),
    Want(RUST, Support.NONE, planted_gap="skill:rust"),
    Want(KUBERNETES, Support.PARTIAL, fact_ids=("F-0004",), planted_gap="skill:kubernetes"),
    Want(GO, Support.NONE, planted_gap="skill:go"),
]
LABELS = labels_for("case-1", WANTS)


def _values(rows: list[Got], **report: object) -> dict[str, float | None]:
    counts = pool([score_case(LABELS, POSTING, report_for(POSTING, rows, **report), BANK)])  # type: ignore[arg-type]
    return repeat_values(counts)


def test_a_recorded_output_scores_to_a_hand_computed_value() -> None:
    """The pipeline claims strong support for Rust (a planted gap) and never extracts Go."""
    rows = [
        Got(PYTHON, Support.STRONG, fact_ids=("F-0001",)),
        Got(RUST, Support.STRONG, fact_ids=("F-0001",)),
        Got(KUBERNETES, Support.PARTIAL, fact_ids=("F-0004",)),
    ]
    case = score_case(LABELS, POSTING, report_for(POSTING, rows), BANK, case_id="case-1", repeat=1)
    values = repeat_values(pool([case]))

    assert values["requirement_recall"] == 3 / 4
    assert values["requirement_precision"] == 1.0
    assert values["importance_agreement"] == 1.0
    assert values["gap_recall"] == 1 / 2
    assert values["false_support_rate"] == 1 / 3
    assert case.counts.planted_not_extracted == 1
    assert [(m.label_id, m.claimed, m.fact_ids) for m in case.missed] == [
        ("L-2", Support.STRONG, ["F-0001"])
    ]
    assert [m.planted_gap for m in case.missed] == ["skill:rust"]
    assert any("L-4" in line and "not extracted" in line for line in case.mismatches)
    assert any("L-2" in line and "claims strong" in line for line in case.mismatches)


def test_a_perfect_run_scores_one_everywhere_and_zero_on_the_bad_counts() -> None:
    rows = [
        Got(PYTHON, Support.STRONG, fact_ids=("F-0001",)),
        Got(RUST, Support.NONE),
        Got(KUBERNETES, Support.PARTIAL, fact_ids=("F-0004",)),
        Got(GO, Support.NONE),
    ]
    values = _values(rows)

    for name in ("requirement_recall", "requirement_precision", "importance_agreement"):
        assert values[name] == 1.0
    assert values["span_validity_rate"] == 1.0
    assert values["gap_recall"] == 1.0
    assert values["false_support_rate"] == 0.0
    assert values["grounding_violations_per_100"] == 0.0
    assert values["attempted_raises"] == 0
    assert values["raises_after_clamp"] == 0


def test_importance_that_differs_from_the_label_is_a_disagreement() -> None:
    rows = [
        Got(PYTHON, Support.STRONG, fact_ids=("F-0001",), importance=Importance.PREFERRED),
        Got(RUST, Support.NONE),
    ]
    assert _values(rows)["importance_agreement"] == 1 / 2


def test_a_row_must_cover_at_least_half_of_the_union_with_the_label_to_match() -> None:
    inside = "Python"
    rows = [Got(inside, Support.STRONG, fact_ids=("F-0001",))]
    assert _values(rows)["requirement_precision"] == 0.0
    long_enough = "You must know Pyth"
    rows = [Got(long_enough, Support.STRONG, fact_ids=("F-0001",))]
    assert _values(rows)["requirement_precision"] == 1.0


def test_dropped_proposals_and_cap_hits_feed_validity_and_hit_counts() -> None:
    rows = [Got(PYTHON, Support.STRONG, fact_ids=("F-0001",))]
    values = _values(
        rows,
        dropped=[DropReason.TEXT_NOT_IN_POSTING, DropReason.DUPLICATE_TERM],
        not_assessed_count=2,
    )
    # proposals: 1 kept, 2 dropped, 2 over the cap. One proposal had text not in the posting.
    assert values["span_validity_rate"] == 4 / 5
    assert values["dedupe_hits"] == 1
    assert values["cap_hits"] == 2


def test_downgrade_accuracy_compares_what_entailment_did_with_what_the_label_expects() -> None:
    rows = [
        # ceiling strong, label says strong: confirmed is right
        Got(PYTHON, Support.STRONG, fact_ids=("F-0001",), entailment=Entailment.CONFIRMED),
        # ceiling strong, label says none: downgraded to none is right
        Got(
            RUST,
            Support.NONE,
            ceiling=Support.STRONG,
            entailment=Entailment.DOWNGRADED,
        ),
        # ceiling strong, label says partial: confirmed strong is wrong (should downgrade)
        Got(
            KUBERNETES,
            Support.STRONG,
            fact_ids=("F-0004",),
            entailment=Entailment.CONFIRMED,
        ),
        # not run: not counted
        Got(GO, Support.NONE, entailment=Entailment.NOT_RUN),
    ]
    values = _values(rows)
    assert values["downgrade_accuracy"] == 2 / 3
    assert values["tag_gate_disagreement_rate"] == 1 / 3


def test_attempted_raises_are_counted_before_the_clamp_and_after_it() -> None:
    rows = [
        Got(PYTHON, Support.STRONG, fact_ids=("F-0001",), raise_attempted=True),
        Got(RUST, Support.NONE, ceiling=Support.NONE, raise_attempted=True),
        # a forged row whose support is above its ceiling
        Got(KUBERNETES, Support.STRONG, ceiling=Support.PARTIAL, fact_ids=("F-0004",)),
    ]
    values = _values(rows)
    assert values["attempted_raises"] == 2
    assert values["raises_after_clamp"] == 1


def test_grounding_violations_count_fabricated_unverified_and_uncited() -> None:
    rows = [
        Got(PYTHON, Support.STRONG, fact_ids=("F-9999",)),  # fabricated id
        Got(RUST, Support.PARTIAL, fact_ids=("F-0026",)),  # in the bank but not verified
        Got(KUBERNETES, Support.PARTIAL),  # support with no citation
        Got(GO, Support.NONE),
    ]
    counts = pool([score_case(LABELS, POSTING, report_for(POSTING, rows), BANK)])
    assert (counts.fabricated_ids, counts.unverified_citations, counts.uncited_claims) == (1, 1, 1)
    assert repeat_values(counts)["grounding_violations_per_100"] == 300.0


def test_an_incomplete_report_misses_every_label_and_has_no_precision() -> None:
    values = _values([], status=ReportStatus.INCOMPLETE)
    assert values["requirement_recall"] == 0.0
    assert values["requirement_precision"] is None
    assert values["gap_recall"] is None


def test_no_cases_gives_no_values_at_all() -> None:
    assert set(repeat_values(pool([])).values()) == {None}


def test_a_metric_with_no_runs_is_not_run_and_never_zero() -> None:
    result = aggregate([])
    assert {value.status for value in result.values()} == {"not_run"}
    assert all(value.mean is None and value.worst is None for value in result.values())
    assert set(result) == {metric.name for metric in METRICS}


def test_a_metric_missing_from_every_repeat_is_not_run() -> None:
    result = aggregate([{"requirement_precision": None}, {"requirement_precision": None}])
    assert result["requirement_precision"].status == "not_run"


def test_mean_and_worst_follow_the_metric_direction() -> None:
    result = aggregate(
        [
            {"requirement_recall": 1.0, "attempted_raises": 0},
            {"requirement_recall": 0.5, "attempted_raises": 2},
            {"requirement_recall": 0.75, "attempted_raises": 1},
        ]
    )
    recall = result["requirement_recall"]
    assert (recall.status, recall.mean, recall.worst, recall.runs) == (
        "scored",
        0.75,
        0.5,
        [1.0, 0.5, 0.75],
    )
    raises = result["attempted_raises"]
    assert (raises.mean, raises.worst) == (1.0, 2.0)
    assert recall.direction is Direction.HIGHER
    assert raises.direction is Direction.LOWER


def test_a_repeat_that_lacks_a_metric_is_skipped_for_that_metric_only() -> None:
    result = aggregate([{"requirement_recall": 1.0}, {"requirement_recall": None}])
    assert result["requirement_recall"].runs == [1.0]


@given(
    kept=st.lists(st.integers(min_value=0, max_value=3), min_size=0, max_size=4, unique=True),
    extra=st.integers(min_value=0, max_value=3),
)
def test_every_rate_is_between_zero_and_one_and_mirroring_the_labels_gives_one(
    kept: list[int], extra: int
) -> None:
    chosen = [WANTS[index] for index in sorted(kept)]
    rows = [Got(want.span, want.support, fact_ids=want.fact_ids) for want in chosen]
    values = _values(rows, dropped=[DropReason.INVALID_FIELD] * extra)
    for metric in METRICS:
        value = values[metric.name]
        if metric.is_rate and value is not None:
            assert 0.0 <= value <= 1.0
    if chosen:
        assert values["requirement_precision"] == 1.0
        assert values["importance_agreement"] == 1.0
    if len(chosen) == len(WANTS):
        assert values["requirement_recall"] == 1.0
