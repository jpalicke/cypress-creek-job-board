# ABOUTME: Scores run files over the real injection corpus: score shift and violations per class.
# ABOUTME: Reports are hand built from the clean posting rows, an attack may raise or fabricate.
from pathlib import Path

import pytest
from eval_support import (
    case_record,
    header_for,
    injection_records,
    mirror_report,
    write_run,
)

from cypress_creek.eval_records import CaseRecord, RunHeader, load_run
from cypress_creek.facts import load_bank
from cypress_creek.facts.hashing import bank_hash
from evals.harness.fixtures import Fixture, discover_fixtures, load_fixture
from evals.harness.injection import (
    ATTACKED_SUFFIX,
    CLEAN_SUFFIX,
    AttackClass,
    InjectionFixture,
    load_corpus,
)
from evals.harness.metrics import ScoreError
from evals.harness.score import RunMetrics, main, score_run

ROOT = Path(__file__).resolve().parents[2]
BANK_PATH = ROOT / "evals" / "bank" / "sample_bank.yaml"
BANK = load_bank(BANK_PATH, strict=True)
CORPUS = load_corpus(ROOT / "evals" / "fixtures" / "injection")
IDS = sorted(CORPUS)
LABELED: dict[str, Fixture] = {
    fixture.meta.fixture_id: fixture
    for fixture in (load_fixture(path) for path in discover_fixtures(ROOT / "evals" / "fixtures"))
}


def _run(
    tmp_path: Path,
    *,
    repeats: int = 1,
    attacks: dict[str, dict[str, bool]] | None = None,
    skip: str | None = None,
    extra_labeled: bool = False,
    bank_digest: str | None = None,
) -> tuple[Path, RunHeader]:
    names = [f"{case_id}{suffix}" for case_id in IDS for suffix in (ATTACKED_SUFFIX, CLEAN_SUFFIX)]
    labeled = [sorted(LABELED)[0]] if extra_labeled else []
    header = header_for(labeled + names, repeats, bank_digest or bank_hash(BANK))
    records: list[CaseRecord] = []
    for repeat in range(1, repeats + 1):
        for case_id in labeled:
            fixture = LABELED[case_id]
            report = mirror_report(fixture.labels, fixture.text)
            records.append(case_record(header, case_id, repeat, fixture.text, report))
        for case_id in IDS:
            options = (attacks or {}).get(case_id, {})
            records += injection_records(header, CORPUS[case_id], repeat, skip=skip, **options)
    path = tmp_path / "run.jsonl"
    write_run(path, header, records, complete=skip is None)
    return path, header


def _score(path: Path) -> RunMetrics:
    return score_run(load_run(path), LABELED, BANK, CORPUS)


def test_a_run_where_every_attack_is_ignored_shifts_nothing_and_violates_nothing(
    tmp_path: Path,
) -> None:
    result = _score(_run(tmp_path)[0])

    classes = {fixture.case.attack_class.value for fixture in CORPUS.values()}
    assert set(result.injection) == classes
    for values in result.injection.values():
        assert (values["score_shift"].mean, values["score_shift"].worst) == (0.0, 0.0)
        assert (values["grounding_violations"].mean, values["grounding_violations"].worst) == (0, 0)
    assert result.injection_differences == []
    assert {value.status for value in result.metrics.values()} == {"not_run"}


def test_an_attack_that_raises_support_with_a_fake_citation_shows_in_its_class_only(
    tmp_path: Path,
) -> None:
    victim = "direct-override-1"
    path, _ = _run(tmp_path, attacks={victim: {"raise_rust": True, "fake_citation": True}})
    result = _score(path)

    hit = result.injection[AttackClass.DIRECT_INSTRUCTION_OVERRIDE.value]
    assert (hit["score_shift"].mean or 0) > 0
    assert hit["grounding_violations"].mean == 1.0
    others = [
        v
        for name, v in result.injection.items()
        if name != AttackClass.DIRECT_INSTRUCTION_OVERRIDE.value
    ]
    assert all(
        v["score_shift"].mean == 0.0 and v["grounding_violations"].mean == 0.0 for v in others
    )
    assert any(
        line.startswith(f"repeat 1 {victim}: row You must know Rust.: support none became strong")
        for line in result.injection_differences
    )


def test_labeled_cases_and_injection_pairs_score_side_by_side(tmp_path: Path) -> None:
    result = _score(_run(tmp_path, extra_labeled=True)[0])

    assert result.metrics["requirement_recall"].mean == 1.0
    assert result.injection


def test_a_repeat_missing_one_side_of_a_pair_is_not_scored(tmp_path: Path) -> None:
    path, _ = _run(tmp_path, skip=f"{IDS[0]}{CLEAN_SUFFIX}")
    result = _score(path)

    assert result.repeats_scored == 0
    assert result.injection == {}


def test_a_pair_without_a_corpus_fixture_or_with_a_changed_posting_is_refused(
    tmp_path: Path,
) -> None:
    path, _ = _run(tmp_path)
    state = load_run(path)
    with pytest.raises(ScoreError, match="no injection fixture"):
        score_run(state, LABELED, BANK, {})
    changed = {
        name: InjectionFixture(f.directory, f.case, f.attacked + " x", f.clean)
        for name, f in CORPUS.items()
    }
    with pytest.raises(ScoreError, match="posting"):
        score_run(state, LABELED, BANK, changed)


def test_the_cli_writes_injection_metrics_and_prints_the_differences(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, header = _run(tmp_path, attacks={"omission-1": {"raise_rust": True}})
    code = main(
        ["--run", str(path), "--bank", str(BANK_PATH), "--out", str(tmp_path / "out"), "--diff"]
    )

    assert code == 0
    text = capsys.readouterr().out
    assert "E6 omission score_shift" in text
    assert "omission-1: row You must know Rust.: support none became strong" in text
    (written,) = list((tmp_path / "out").iterdir())
    loaded = RunMetrics.model_validate_json(written.read_text(encoding="utf-8"))
    assert loaded.run_id == header.run_id
    assert (loaded.injection["omission"]["score_shift"].mean or 0) > 0
