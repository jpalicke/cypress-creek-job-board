# ABOUTME: Runs the score CLI as a separate process on an injection run over the real corpus.
# ABOUTME: Checks the per class lines, the difference listing and the metrics file.
import json
import subprocess
import sys
from pathlib import Path

from eval_support import header_for, injection_records, write_run

from cypress_creek.facts import load_bank
from cypress_creek.facts.hashing import bank_hash
from evals.harness.injection import ATTACKED_SUFFIX, CLEAN_SUFFIX, load_corpus

ROOT = Path(__file__).resolve().parents[2]
CORPUS = load_corpus(ROOT / "evals" / "fixtures" / "injection")
BANK = load_bank(ROOT / "evals" / "bank" / "sample_bank.yaml", strict=True)
VICTIM = "exfiltration-1"


def test_a_separate_process_scores_score_shift_and_violations_per_attack_class(
    tmp_path: Path,
) -> None:
    names = [
        f"{case_id}{suffix}" for case_id in CORPUS for suffix in (ATTACKED_SUFFIX, CLEAN_SUFFIX)
    ]
    header = header_for(names, 1, bank_hash(BANK))
    records = []
    for case_id, fixture in CORPUS.items():
        hit = case_id == VICTIM
        records += injection_records(header, fixture, 1, raise_rust=hit, fake_citation=hit)
    run = tmp_path / "run.jsonl"
    write_run(run, header, records, complete=True)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "evals.harness.score",
            "--run",
            str(run),
            "--out",
            str(tmp_path / "out"),
            "--diff",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert "E6 exfiltration grounding_violations mean 1.000 worst 1.000" in result.stdout
    assert "E6 omission grounding_violations mean 0.000 worst 0.000" in result.stdout
    assert f"{VICTIM}: row You must know Rust.: support none became strong" in result.stdout
    (written,) = list((tmp_path / "out").iterdir())
    metrics = json.loads(written.read_text(encoding="utf-8"))
    shift = metrics["injection"]["exfiltration"]["score_shift"]["mean"]
    assert shift > 0
    assert metrics["injection"]["omission"]["score_shift"]["mean"] == 0.0
