# ABOUTME: Tests stage 2 retrieval against a real fact bank file and the real alias table.
# ABOUTME: No model is involved: gaps cost nothing, and the module imports no provider.
import ast
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from cypress_creek.facts import load_bank
from cypress_creek.facts.models import Bank
from cypress_creek.ingest.models import Importance, Requirement, RequirementKind
from cypress_creek.pipeline import retrieve as retrieve_module
from cypress_creek.pipeline.retrieve import MAX_CANDIDATES, RequirementCandidates, retrieve
from cypress_creek.providers.base import Capabilities, CostPerMtok
from cypress_creek.scoring.aliases import load_aliases
from cypress_creek.scoring.support import Gate, Support

TODAY = date(2024, 1, 1)
FREE = CostPerMtok(input=0, output=0)
LOCAL = Capabilities(context_tokens=8192, strict_schema=True, local=True, cost_per_mtok=FREE)
HOSTED = Capabilities(context_tokens=8192, strict_schema=True, local=False, cost_per_mtok=FREE)

BANK = """
facts:
  - id: F-0001
    claim: Ran a fictional Python data service.
    kind: project
    start: 2020-01-01
    end: 2023-01-01
    tags: [{name: python, level: expert}]
    verified_on: 2024-01-01
    evidence: {type: repo, pointer: "https://example.invalid/a"}
    share: shareable
  - id: F-0002
    claim: Operated a fictional PostgreSQL cluster.
    kind: project
    start: 2021-01-01
    tags: [{name: postgresql, level: working}]
    verified_on: 2024-01-01
    evidence: {type: repo, pointer: "https://example.invalid/b"}
    share: shareable
  - id: F-0003
    claim: Private fictional Rust work.
    kind: project
    tags: [{name: rust, level: expert}]
    verified_on: 2024-01-01
    evidence: {type: self_attested, pointer: notes}
    share: local_only
  - id: F-0004
    claim: Claimed Go work with no verification.
    kind: project
    tags: [{name: go, level: expert}]
    evidence: {type: self_attested, pointer: notes}
    share: shareable
"""


def _bank(tmp_path: Path, text: str = BANK) -> Bank:
    path = tmp_path / "bank.yaml"
    path.write_text(text, encoding="utf8")
    return load_bank(path)


def _requirement(term: str, *, years: int | None = None, number: int = 1) -> Requirement:
    return Requirement(
        id=f"R-{number}",
        text=f"Needs {term}.",
        span=(0, 10),
        kind=RequirementKind.YEARS if years else RequirementKind.SKILL,
        term=term,
        years=years,
        importance=Importance.REQUIRED,
    )


def _run(
    bank: Bank, requirements: Sequence[Requirement], capabilities: Capabilities = LOCAL
) -> list[RequirementCandidates]:
    return retrieve(requirements, bank, capabilities, TODAY, load_aliases())


def test_a_requirement_with_no_tagged_fact_is_a_gap_with_no_candidates(tmp_path: Path) -> None:
    [result] = _run(_bank(tmp_path), [_requirement("haskell")])
    assert result.fact_ids == []
    assert result.is_gap
    assert (result.support, result.gate) == (Support.NONE, Gate.NO_CANDIDATE)
    assert result.dropped_count == 0


def test_an_alias_finds_the_fact_tagged_with_the_canonical_name(tmp_path: Path) -> None:
    [result] = _run(_bank(tmp_path), [_requirement("postgres")])
    assert result.fact_ids == ["F-0002"]
    assert not result.is_gap
    assert result.support is Support.STRONG


def test_an_unverified_fact_is_never_a_candidate(tmp_path: Path) -> None:
    [result] = _run(_bank(tmp_path), [_requirement("go")])
    assert result.is_gap


def test_a_local_only_fact_is_a_candidate_for_a_local_backend_only(tmp_path: Path) -> None:
    bank = _bank(tmp_path)
    assert _run(bank, [_requirement("rust")], LOCAL)[0].fact_ids == ["F-0003"]
    assert _run(bank, [_requirement("rust")], HOSTED)[0].is_gap


def test_the_ceiling_comes_from_the_years_rule(tmp_path: Path) -> None:
    bank = _bank(tmp_path)
    [short] = _run(bank, [_requirement("python", years=5)])
    [met] = _run(bank, [_requirement("python", years=2)])
    assert (short.support, short.gate) == (Support.PARTIAL, Gate.YEARS_BELOW)
    assert (met.support, met.gate) == (Support.STRONG, Gate.YEARS_MET)


def _python_bank() -> str:
    rows = [
        ("F-0001", "familiar", "2024-01-01"),
        ("F-0002", "working", "2020-01-01"),
        ("F-0003", "expert", "2019-01-01"),
        ("F-0004", "expert", "2022-01-01"),
        ("F-0005", "expert", None),
        ("F-0006", "working", "2023-01-01"),
        ("F-0007", "familiar", "2024-01-01"),
        ("F-0008", "working", "2021-01-01"),
    ]
    facts = ""
    for fact_id, level, end in rows:
        start = "2005-01-01" if fact_id == "F-0002" else "2015-01-01"
        end_line = f"    end: {end}\n" if end else ""
        facts += (
            f"  - id: {fact_id}\n    claim: Fictional Python work {fact_id}.\n    kind: project\n"
            f"    start: {start}\n{end_line}    tags: [{{name: python, level: {level}}}]\n"
            "    verified_on: 2024-01-01\n"
            '    evidence: {type: repo, pointer: "https://example.invalid/x"}\n'
            "    share: shareable\n"
        )
    return "facts:\n" + facts


def test_candidates_are_capped_by_level_then_recency_and_the_rest_are_counted(
    tmp_path: Path,
) -> None:
    [result] = _run(_bank(tmp_path, _python_bank()), [_requirement("python")])
    assert MAX_CANDIDATES == 5
    assert result.fact_ids == ["F-0005", "F-0004", "F-0003", "F-0006", "F-0008"]
    assert result.dropped_count == 3


def test_the_ceiling_uses_every_matching_fact_not_only_the_kept_ones(tmp_path: Path) -> None:
    bank = _bank(tmp_path, _python_bank())
    # Only the dropped F-0002 reaches back to 2005, so 15 years is met only by counting it.
    [capped] = _run(bank, [_requirement("python", years=15)])
    assert capped.dropped_count == 3
    assert "F-0002" not in capped.fact_ids
    assert (capped.support, capped.gate) == (Support.STRONG, Gate.YEARS_MET)


def test_results_follow_the_input_order_and_repeat_exactly(tmp_path: Path) -> None:
    bank = _bank(tmp_path)
    requirements = [
        _requirement("postgres", number=1),
        _requirement("haskell", number=2),
        _requirement("python", number=3),
    ]
    first = _run(bank, requirements)
    assert [r.requirement_id for r in first] == ["R-1", "R-2", "R-3"]
    assert first == _run(bank, requirements)


def test_no_requirements_gives_no_results(tmp_path: Path) -> None:
    assert _run(_bank(tmp_path), []) == []


def test_the_module_imports_no_provider_code() -> None:
    tree = ast.parse(Path(retrieve_module.__file__ or "").read_text(encoding="utf-8"))
    imported = [
        alias.name if isinstance(node, ast.Import) else f"{node.module}.{alias.name}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    ]
    allowed = {"cypress_creek.providers.base.Capabilities"}
    assert [name for name in imported if "providers" in name and name not in allowed] == []
