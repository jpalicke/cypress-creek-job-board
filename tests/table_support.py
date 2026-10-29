# ABOUTME: Builds run exports and metrics files for the table tests, the way the scorer writes them.
# ABOUTME: Shared by the component and end to end table tests so both start from the same inputs.
from collections.abc import Mapping, Sequence
from pathlib import Path

from eval_support import PROVENANCE, report_for, write_run

from cypress_creek.eval_records import CaseRecord, RunHeader
from cypress_creek.ingest.hashing import text_hash
from cypress_creek.pipeline.trace import CallRecord
from cypress_creek.providers.base import Usage
from evals.harness.metrics import aggregate
from evals.harness.score import RunMetrics

POSTING = "Needs Python."
CASES = ["case-a", "case-b"]


def header(
    backend: str = "ollama",
    model: str = "qwen3.5:4b",
    *,
    prompt: str = "a",
    fixtures: str = "c",
    commit: str = "1",
    repeats: int = 3,
) -> RunHeader:
    return RunHeader(
        git_commit=commit * 40,
        backend=backend,
        model=model,
        prompt_hashes={"extract": prompt * 64, "entail": "b" * 64},
        schema_versions={"extract": 1, "entail": 1},
        fixture_set_hash=fixtures * 64,
        bank_hash="d" * 64,
        case_ids=CASES,
        repeats=repeats,
    )


def call(cost: float | None, error: str | None = None) -> CallRecord:
    usage = None if cost is None else Usage(input_tokens=10, output_tokens=5)
    return CallRecord(
        stage="extract",
        prompt_hash="a" * 64,
        schema_version=1,
        outcome="error" if error else "success",
        error_type=error,
        usage=usage if (error is None or cost is not None) else None,
        cost_usd=cost,
    )


def case(head: RunHeader, case_id: str, repeat: int, calls: Sequence[CallRecord]) -> CaseRecord:
    return CaseRecord(
        run_id=head.run_id,
        case_id=case_id,
        repeat=repeat,
        posting_hash=text_hash(POSTING),
        report=report_for(POSTING, []).model_copy(
            update={
                "provenance": PROVENANCE.model_copy(
                    update={"backend": head.backend, "model": head.model}
                )
            }
        ),
        calls=list(calls),
        validators=[],
    )


def metrics_for(head: RunHeader, *, scored: int | None = None, recall: float = 0.75) -> RunMetrics:
    repeats = head.repeats if scored is None else scored
    per_repeat = [
        {"requirement_recall": recall, "grounding_violations_per_100": 0.0} for _ in range(repeats)
    ]
    return RunMetrics(
        backend=head.backend,
        model=head.model,
        run_id=head.run_id,
        run_status="complete",
        repeats_planned=head.repeats,
        repeats_scored=repeats,
        cases=CASES,
        metrics=aggregate(per_repeat),
        missed_planted_gaps=[],
    )


def publish(
    results: Path,
    head: RunHeader,
    *,
    calls: Mapping[tuple[str, int], Sequence[CallRecord]] | None = None,
    scored: int | None = None,
    name: str | None = None,
) -> None:
    """Write a run export and its metrics file the way the scorer and a human would."""
    results.mkdir(parents=True, exist_ok=True)
    stem = name or f"{head.backend}-{head.model}".replace(":", "_")
    extract_hash = head.prompt_hashes["extract"]

    def own(records: Sequence[CallRecord]) -> list[CallRecord]:
        return [record.model_copy(update={"prompt_hash": extract_hash}) for record in records]

    cases = [
        case(head, case_id, repeat, own((calls or {}).get((case_id, repeat), [call(0.0)])))
        for repeat in range(1, head.repeats + 1)
        for case_id in CASES
    ]
    write_run(results / f"{stem}.jsonl", head, cases, complete=True)
    (results / f"{stem}.json").write_text(
        metrics_for(head, scored=scored).model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
