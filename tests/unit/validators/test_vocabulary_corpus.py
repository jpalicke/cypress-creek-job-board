# ABOUTME: Measures what the closed vocabulary costs on honest rewordings of the sample bank facts.
# ABOUTME: The counts are pinned, so a change to the lists or the stem rule shows up as a diff here.
from pathlib import Path

import yaml

from cypress_creek.facts.loader import parse_bank
from cypress_creek.validators.claims import check_novel_terms

BANK = parse_bank(
    yaml.safe_load(
        (Path(__file__).resolve().parents[3] / "evals" / "bank" / "sample_bank.yaml").read_text(
            encoding="utf-8"
        )
    )
)

# (fact id, an honest reworded sentence, whether the closed vocabulary should call it clean)
HONEST = [
    (
        "F-0001",
        "Backend Developer at Gravy Boat Labs, where I built and ran Python services.",
        True,
    ),
    ("F-0001", "Built and ran Python services at Gravy Boat Labs as a Backend Developer.", True),
    ("F-0001", "Developed Python services at Gravy Boat Labs.", False),
    ("F-0001", "Created Python services for backend work.", False),
    ("F-0002", "Ran the PostgreSQL reporting warehouse at Turbo Tortoise Systems.", True),
    ("F-0002", "Senior Data Engineer who ran the PostgreSQL reporting warehouse.", True),
    ("F-0002", "Managed the PostgreSQL reporting warehouse.", False),
    (
        "F-0003",
        "Migrated a reporting database to PostgreSQL, cutting the nightly batch from 6 hours to "
        "90 minutes.",
        True,
    ),
    (
        "F-0003",
        "Cut the nightly batch from 6 hours to 90 minutes by migrating a reporting database to "
        "PostgreSQL.",
        False,
    ),
    ("F-0003", "Reduced the nightly batch from 6 hours to 90 minutes.", False),
    ("F-0004", "Packaged services in Docker and deployed them to a Kubernetes cluster.", True),
    (
        "F-0004",
        "Deployed Docker-packaged services to a Kubernetes cluster run by another team.",
        False,
    ),
    ("F-0004", "Deployed services to Kubernetes.", True),
    ("F-0004", "Worked with Docker and Kubernetes.", True),
    ("F-0005", "BS in Computer Science from Lake Bogus State University.", True),
    ("F-0005", "Earned a BS in Computer Science from Lake Bogus State University.", False),
    ("F-0006", "Holds the Cloud Pelican Associate certification.", True),
    ("F-0006", "Certified as a Cloud Pelican Associate.", False),
    ("F-0008", "Maintains a public Python library that validates CSV files.", True),
    ("F-0008", "Maintains a Python library with a pytest test suite.", True),
    ("F-0008", "Wrote a Python library for validating CSV files.", False),
    ("F-0008", "Has experience running Python libraries.", False),
]


def _clean(fact_id: str, sentence: str) -> bool:
    cited = [fact for fact in BANK.facts if fact.id == fact_id]
    return check_novel_terms(sentence, cited, "", closed_vocabulary=True).passed


def test_each_honest_sentence_is_judged_as_recorded() -> None:
    for fact_id, sentence, expected in HONEST:
        assert _clean(fact_id, sentence) is expected, sentence


def test_the_false_positive_rate_on_the_honest_corpus_is_pinned() -> None:
    flagged = [sentence for fact_id, sentence, _ in HONEST if not _clean(fact_id, sentence)]
    # 10 of 22 honest rewordings are flagged (45 percent): every one swaps in a word the fact does
    # not use. The price of a closed vocabulary is a human look at those, never a wrong "clean".
    assert (len(flagged), len(HONEST)) == (10, 22)
