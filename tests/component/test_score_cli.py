# ABOUTME: Scores run files against the real committed fixture labels, through the score CLI.
# ABOUTME: Runs are hand built from the labels (allowed inputs), never from a mocked pipeline.
import json
import shutil
from pathlib import Path

import pytest
from eval_support import case_record, header_for, mirror_report, write_run

from cypress_creek.eval_records import CaseRecord, RunHeader, load_run
from cypress_creek.facts import load_bank
from cypress_creek.facts.hashing import bank_hash
from evals.harness.fixtures import Fixture, discover_fixtures, load_fixture
from evals.harness.metrics import ScoreError
from evals.harness.score import RunMetrics, main, score_run

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "evals" / "fixtures"
BANK_PATH = ROOT / "evals" / "bank" / "sample_bank.yaml"
BANK = load_bank(BANK_PATH, strict=True)
LOADED: dict[str, Fixture] = {
    fixture.meta.fixture_id: fixture
    for fixture in (load_fixture(path) for path in discover_fixtures(FIXTURES))
}
IDS = sorted(LOADED)


def _run(
    tmp_path: Path,
    *,
    repeats: int = 3,
    ids: list[str] | None = None,
    bank_digest: str | None = None,
    complete: bool = True,
    customize: dict[tuple[str, int], dict[str, frozenset[str]]] | None = None,
    name: str = "run.jsonl",
) -> tuple[Path, RunHeader]:
    chosen = ids or IDS
    header = header_for(chosen, repeats, bank_digest or bank_hash(BANK))
    cases: list[CaseRecord] = []
    for repeat in range(1, repeats + 1):
        for case_id in chosen:
            fixture = LOADED[case_id]
            extra = (customize or {}).get((case_id, repeat), {})
            report = mirror_report(fixture.labels, fixture.text, **extra)
            cases.append(case_record(header, case_id, repeat, fixture.text, report))
    path = tmp_path / name
    write_run(path, header, cases, complete=complete)
    return path, header


def _score(path: Path) -> RunMetrics:
    return score_run(load_run(path), LOADED, BANK)


def test_a_run_that_agrees_with_every_label_scores_one_and_zero(tmp_path: Path) -> None:
    path, header = _run(tmp_path)
    result = _score(path)

    assert (result.backend, result.model, result.run_id) == (
        "ollama",
        "qwen3.5:0.8b",
        header.run_id,
    )
    assert (result.run_status, result.repeats_planned, result.repeats_scored) == ("complete", 3, 3)
    metrics = result.metrics
    for name in (
        "requirement_recall",
        "requirement_precision",
        "importance_agreement",
        "gap_recall",
    ):
        assert (metrics[name].mean, metrics[name].worst) == (1.0, 1.0)
    for name in ("false_support_rate", "grounding_violations_per_100", "attempted_raises"):
        assert (metrics[name].mean, metrics[name].worst) == (0.0, 0.0)
    assert result.missed_planted_gaps == []
    assert metrics["gap_recall"].runs == [1.0, 1.0, 1.0]


def test_one_bad_repeat_moves_the_worst_run_but_not_the_best(tmp_path: Path) -> None:
    case_id = IDS[0]
    planted = next(r.id for r in LOADED[case_id].labels.requirements if r.planted_gap)
    path, _ = _run(
        tmp_path,
        customize={(case_id, 2): {"claim_strong": frozenset({planted})}},
    )
    result = _score(path)

    gap = result.metrics["gap_recall"]
    false_support = result.metrics["false_support_rate"]
    assert gap.worst is not None and gap.mean is not None and false_support.worst is not None
    assert gap.worst < 1.0 and gap.runs[0] == 1.0 and gap.runs[2] == 1.0
    assert gap.mean < 1.0
    assert false_support.worst > 0.0
    assert [(m.case_id, m.repeat, m.label_id) for m in result.missed_planted_gaps] == [
        (case_id, 2, planted)
    ]
    assert result.missed_planted_gaps[0].fact_ids == ["F-0001"]


def test_a_repeat_with_a_missing_case_is_not_scored(tmp_path: Path) -> None:
    path, _ = _run(tmp_path, repeats=2, complete=False)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    result = _score(path)

    assert result.run_status == "incomplete"
    assert result.repeats_scored == 1
    assert result.metrics["requirement_recall"].runs == [1.0]


def test_a_run_with_no_complete_repeat_has_every_metric_not_run(tmp_path: Path) -> None:
    path, _ = _run(tmp_path, repeats=1, complete=False)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    result = _score(path)

    assert result.repeats_scored == 0
    assert {value.status for value in result.metrics.values()} == {"not_run"}


def test_a_run_made_with_another_bank_is_refused(tmp_path: Path) -> None:
    path, _ = _run(tmp_path, bank_digest="f" * 64)
    with pytest.raises(ScoreError, match="bank"):
        _score(path)


def test_a_case_without_a_fixture_is_refused(tmp_path: Path) -> None:
    header = header_for(["no-such-case"], 1, bank_hash(BANK))
    fixture = LOADED[IDS[0]]
    report = mirror_report(fixture.labels, fixture.text)
    path = tmp_path / "run.jsonl"
    write_run(
        path, header, [case_record(header, "no-such-case", 1, fixture.text, report)], complete=True
    )
    with pytest.raises(ScoreError, match="no-such-case"):
        _score(path)


def test_a_posting_that_differs_from_the_fixture_is_refused(tmp_path: Path) -> None:
    case_id = IDS[0]
    fixture = LOADED[case_id]
    header = header_for([case_id], 1, bank_hash(BANK))
    report = mirror_report(fixture.labels, fixture.text)
    path = tmp_path / "run.jsonl"
    other = case_record(header, case_id, 1, fixture.text + " changed", report)
    write_run(path, header, [other], complete=True)
    with pytest.raises(ScoreError, match="posting"):
        _score(path)


def test_the_cli_writes_deterministic_metrics_that_validate_against_the_schema(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, header = _run(tmp_path)
    out = tmp_path / "out"
    argv = [
        "--run",
        str(path),
        "--bank",
        str(BANK_PATH),
        "--fixtures",
        str(FIXTURES),
        "--out",
        str(out),
    ]

    assert main(argv) == 0
    (written,) = list(out.iterdir())
    assert written.name == f"ollama-qwen3.5_0.8b-{header.run_id[:12]}.json"
    first = written.read_text(encoding="utf-8")
    assert RunMetrics.model_validate_json(first).run_id == header.run_id
    stdout = capsys.readouterr().out
    assert "requirement_recall" in stdout

    again = tmp_path / "again"
    assert main([*argv[:-1], str(again)]) == 0
    assert (again / written.name).read_text(encoding="utf-8") == first


def test_the_cli_reports_a_backend_with_no_run_as_not_run(tmp_path: Path) -> None:
    path, _ = _run(tmp_path)
    out = tmp_path / "out"
    code = main(
        [
            "--run",
            str(path),
            "--expect-backend",
            "ollama",
            "--expect-backend",
            "anthropic",
            "--bank",
            str(BANK_PATH),
            "--fixtures",
            str(FIXTURES),
            "--out",
            str(out),
        ]
    )

    assert code == 0
    missing = json.loads((out / "anthropic-not-run.json").read_text(encoding="utf-8"))
    assert missing["backend"] == "anthropic"
    assert {value["status"] for value in missing["metrics"].values()} == {"not_run"}
    assert not (out / "ollama-not-run.json").exists()


def test_the_diff_view_lists_each_mismatch_with_its_case_and_repeat(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case_id = IDS[0]
    labels = LOADED[case_id].labels
    planted = next(r.id for r in labels.requirements if r.planted_gap)
    skipped = next(r.id for r in labels.requirements if r.id != planted)
    path, _ = _run(
        tmp_path,
        repeats=1,
        customize={
            (case_id, 1): {"claim_strong": frozenset({planted}), "skip": frozenset({skipped})}
        },
    )
    code = main(
        [
            "--run",
            str(path),
            "--bank",
            str(BANK_PATH),
            "--fixtures",
            str(FIXTURES),
            "--out",
            str(tmp_path / "out"),
            "--diff",
        ]
    )

    assert code == 0
    text = capsys.readouterr().out
    assert f"{case_id} repeat 1 {skipped}: not extracted" in text
    assert f"{case_id} repeat 1 {planted}: claims strong" in text
    assert "Missed planted gaps" in text


def test_the_cli_refuses_labels_that_are_not_committed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case_id = IDS[0]
    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES / case_id, copy / case_id)
    path, _ = _run(tmp_path, ids=[case_id], repeats=1)
    argv = ["--run", str(path), "--bank", str(BANK_PATH), "--fixtures", str(copy)]

    assert main([*argv, "--out", str(tmp_path / "out")]) == 1
    assert "labels.yaml is not tracked by git" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_the_cli_never_overwrites_a_metrics_file(tmp_path: Path) -> None:
    path, _ = _run(tmp_path, repeats=1)
    argv = [
        "--run",
        str(path),
        "--bank",
        str(BANK_PATH),
        "--fixtures",
        str(FIXTURES),
        "--out",
        str(tmp_path / "out"),
    ]
    assert main(argv) == 0
    assert main(argv) == 1
