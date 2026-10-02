# ABOUTME: Tests the entailment stage around a real Ollama adapter that cannot answer.
# ABOUTME: A gap makes no call, and a failed call keeps the rule ceiling and marks it not run.
from pathlib import Path

import pytest

from cypress_creek.config import parse_settings
from cypress_creek.facts import load_bank
from cypress_creek.facts.models import Bank
from cypress_creek.ingest.models import Importance, Requirement, RequirementKind
from cypress_creek.pipeline.entail import ENTAIL_MAX_OUTPUT_TOKENS, Entailment, entail, entail_cap
from cypress_creek.pipeline.retrieve import RequirementCandidates
from cypress_creek.providers import BudgetExceeded
from cypress_creek.providers.budget import Budget, BudgetedProvider, BudgetTracker
from cypress_creek.providers.ollama import OllamaProvider
from cypress_creek.scoring.support import Gate, Support

BANK = """
facts:
  - id: F-0001
    claim: Ran a fictional Python data service for 3 years.
    kind: project
    tags: [{name: python, level: expert}]
    verified_on: 2024-01-01
    evidence: {type: repo, pointer: "https://example.invalid/a"}
    share: shareable
"""
REQUIREMENT = Requirement(
    id="R-1",
    text="Needs Python.",
    span=(0, 13),
    kind=RequirementKind.SKILL,
    term="python",
    importance=Importance.REQUIRED,
)
# Nothing listens on the discard port. A call that reached the network is ProviderUnavailable.
NOTHING_LISTENING = "http://127.0.0.1:9"


@pytest.fixture
def bank(tmp_path: Path) -> Bank:
    path = tmp_path / "bank.yaml"
    path.write_text(BANK, encoding="utf8")
    return load_bank(path)


def _provider(context_tokens: int = 4096) -> OllamaProvider:
    settings = parse_settings(
        {
            "provider": "ollama",
            "model": "qwen3.5:0.8b",
            "base_url": NOTHING_LISTENING,
            "context_tokens": context_tokens,
        }
    )
    return OllamaProvider(settings)


def _candidates(fact_ids: list[str], support: Support) -> RequirementCandidates:
    return RequirementCandidates(
        requirement_id="R-1",
        fact_ids=fact_ids,
        dropped_count=0,
        support=support,
        gate=Gate.TERM_MATCH if fact_ids else Gate.NO_CANDIDATE,
    )


def _no_sleep(_seconds: float) -> None:
    raise AssertionError("nothing in these tests should wait")


def test_a_gap_makes_no_call_and_needs_none(bank: Bank) -> None:
    inner = _provider()
    tracker = BudgetTracker(Budget(), inner.capabilities.cost_per_mtok)
    result = entail(
        REQUIREMENT, _candidates([], Support.NONE), bank, BudgetedProvider(inner, tracker)
    )
    assert result.entailment is Entailment.NOT_NEEDED
    assert result.match.support is Support.NONE
    assert result.fact_ids == []
    assert tracker.requests == 0


def test_an_unreachable_backend_keeps_the_ceiling_and_is_not_run(bank: Bank) -> None:
    result = entail(
        REQUIREMENT,
        _candidates(["F-0001"], Support.STRONG),
        bank,
        _provider(),
        sleep=_no_sleep,
    )
    assert result.entailment is Entailment.NOT_RUN
    assert result.failure == "provider_unavailable"
    assert result.match.support is Support.STRONG
    assert result.match.ceiling is Support.STRONG
    assert result.usage is None
    assert result.prompt_hash is not None
    assert len(result.prompt_hash) == 64


def test_a_budget_stop_is_not_swallowed(bank: Bank) -> None:
    inner = _provider()
    tracker = BudgetTracker(Budget(max_input_tokens=10), inner.capabilities.cost_per_mtok)
    with pytest.raises(BudgetExceeded):
        entail(
            REQUIREMENT,
            _candidates(["F-0001"], Support.STRONG),
            bank,
            BudgetedProvider(inner, tracker),
            sleep=_no_sleep,
        )
    assert tracker.requests == 0


def test_the_answer_cap_is_small_and_never_more_than_half_the_window() -> None:
    assert entail_cap(_provider(8192).capabilities) == ENTAIL_MAX_OUTPUT_TOKENS
    small = _provider().capabilities.model_copy(update={"context_tokens": 600})
    assert entail_cap(small) == 300
