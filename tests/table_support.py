# ABOUTME: Builds run exports and metrics files for the table tests, the way the scorer writes them.
# ABOUTME: Runs mirror the real committed hand labels, and the metrics are what the scorer computes.
from collections.abc import Mapping, Sequence
from pathlib import Path

from eval_support import PROVENANCE, case_record, injection_records, mirror_report, write_run

from cypress_creek.eval_records import CaseRecord, RunHeader, load_run
from cypress_creek.facts import load_bank
from cypress_creek.facts.hashing import bank_hash
from cypress_creek.pipeline.trace import CallRecord
from cypress_creek.providers.base import Usage
from evals.harness.fixtures import Fixture, discover_fixtures, load_fixture
from evals.harness.injection import ATTACKED_SUFFIX, CLEAN_SUFFIX, load_corpus
from evals.harness.score import RunMetrics, score_run

ROOT = Path(__file__).resolve().parents[1]
BANK = load_bank(ROOT / "evals" / "bank" / "sample_bank.yaml", strict=True)
LABELED: dict[str, Fixture] = {
    fixture.meta.fixture_id: fixture
    for fixture in (load_fixture(path) for path in discover_fixtures(ROOT / "evals" / "fixtures"))
}
CORPUS = load_corpus(ROOT / "evals" / "fixtures" / "injection")
CASES = sorted(LABELED)
ATTACK_CASES = [
    f"{name}{suffix}" for name in sorted(CORPUS) for suffix in (ATTACKED_SUFFIX, CLEAN_SUFFIX)
]


def header(
    backend: str = "ollama",
    model: str = "qwen3.5:4b",
    *,
    prompt: str = "a",
    fixtures: str = "c",
    commit: str = "1",
    repeats: int = 3,
    attacks: bool = False,
) -> RunHeader:
    return RunHeader(
        git_commit=commit * 40,
        backend=backend,
        model=model,
        prompt_hashes={"extract": prompt * 64, "entail": "b" * 64},
        schema_versions={"extract": 1, "entail": 1},
        fixture_set_hash=fixtures * 64,
        bank_hash=bank_hash(BANK),
        case_ids=CASES + (ATTACK_CASES if attacks else []),
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


def records(
    head: RunHeader,
    repeat: int,
    calls: Sequence[CallRecord],
    *,
    drop_label_in_repeat: int | None = None,
    raise_rust: Mapping[str, bool] | None = None,
    disrupt: Sequence[str] = (),
) -> list[CaseRecord]:
    """One repeat of the labeled cases, then the injection pairs when the header names them."""
    extract_hash = head.prompt_hashes["extract"]
    own = [record.model_copy(update={"prompt_hash": extract_hash}) for record in calls]
    made: list[CaseRecord] = []
    for case_id in CASES:
        fixture = LABELED[case_id]
        skip: frozenset[str] = frozenset()
        if drop_label_in_repeat == repeat:
            skip = frozenset({fixture.labels.requirements[0].id})
        report = mirror_report(fixture.labels, fixture.text, skip=skip)
        made.append(
            case_record(head, case_id, repeat, fixture.text, report).model_copy(
                update={"calls": own}
            )
        )
    if ATTACK_CASES[0] in head.case_ids:
        for name in sorted(CORPUS):
            made += injection_records(
                head,
                CORPUS[name],
                repeat,
                raise_rust=bool((raise_rust or {}).get(name)),
                disrupt=name in disrupt,
            )
    provenance = PROVENANCE.model_copy(update={"backend": head.backend, "model": head.model})
    return [
        record.model_copy(
            update={"report": record.report.model_copy(update={"provenance": provenance})}
        )
        for record in made
    ]


def publish(
    results: Path,
    head: RunHeader,
    *,
    calls: Mapping[tuple[str, int], Sequence[CallRecord]] | None = None,
    scored: int | None = None,
    name: str | None = None,
    drop_label_in_repeat: int | None = None,
    raise_rust: Mapping[str, bool] | None = None,
    disrupt: Sequence[str] = (),
) -> RunMetrics:
    """Write a run export and the metrics file the scorer computes for it."""
    results.mkdir(parents=True, exist_ok=True)
    stem = name or f"{head.backend}-{head.model}".replace(":", "_")
    written = head.repeats if scored is None else scored
    cases: list[CaseRecord] = []
    for repeat in range(1, written + 1):
        shared = (calls or {}).get(("all", repeat), [call(0.0)])
        cases += records(
            head,
            repeat,
            shared,
            drop_label_in_repeat=drop_label_in_repeat,
            raise_rust=raise_rust,
            disrupt=disrupt,
        )
    path = results / f"{stem}.jsonl"
    write_run(path, head, cases, complete=scored is None)
    metrics = score_run(load_run(path), LABELED, BANK, CORPUS)
    (results / f"{stem}.json").write_text(
        metrics.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return metrics
