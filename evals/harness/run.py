# ABOUTME: Loads dated eval cases and plans real-provider runs from the repository CLI.
# ABOUTME: Dry runs count known extraction work and bound model-dependent attempts without calls.
import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cypress_creek.config import describe_validation_error, load_settings
from cypress_creek.eval_records import CaseRecord, RunHeader, RunState, RunTerminal
from cypress_creek.eval_store import EvalStore
from cypress_creek.facts import load_bank
from cypress_creek.facts.hashing import bank_hash
from cypress_creek.facts.models import Bank
from cypress_creek.ingest.hashing import text_hash
from cypress_creek.ingest.models import Extractor, Posting, PostingSource
from cypress_creek.ingest.normalize import normalize
from cypress_creek.pipeline.entail import SCHEMA_VERSION as ENTAIL_SCHEMA_VERSION
from cypress_creek.pipeline.entail import entail_cap
from cypress_creek.pipeline.extract import SCHEMA_VERSION as EXTRACT_SCHEMA_VERSION
from cypress_creek.pipeline.extract import output_cap
from cypress_creek.pipeline.prompt import Stage, build_prompt
from cypress_creek.pipeline.run import analyze
from cypress_creek.pipeline.schemas import EntailmentOutput, ExtractionOutput
from cypress_creek.pipeline.trace import PipelineTrace
from cypress_creek.providers import Budget, BudgetExceeded, Provider, Usage, get_provider
from cypress_creek.providers.budget import (
    BudgetedProvider,
    BudgetTracker,
    PlannedCall,
    budget_from_settings,
    dry_run_estimate,
)
from cypress_creek.providers.retry import RetryPolicy
from cypress_creek.storage.db import connect, database_path, migrate
from cypress_creek.validators.requirements import MAX_REQUIREMENTS
from evals.harness.fixtures import discover_fixtures, load_fixture
from evals.harness.fixtures import fixture_set_hash as labeled_set_hash
from evals.harness.labels import LabelError, LabelsNotCommitted, require_committed_labels

ROOT = Path(__file__).resolve().parents[2]
BANK_PATH = ROOT / "evals" / "bank" / "sample_bank.yaml"
FIXTURES_PATH = ROOT / "evals" / "fixtures"


class CaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    posting: str = Field(min_length=1)
    as_of: date


class CaseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cases: list[CaseSpec] = Field(min_length=1)


@dataclass(frozen=True)
class EvalCase:
    id: str
    posting: Posting


def load_cases(path: Path) -> list[EvalCase]:
    """Load text and evaluation dates, refusing duplicate IDs before any provider work."""
    try:
        manifest = CaseManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        raise ValueError(f"invalid case manifest: {describe_validation_error(error)}") from None
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for spec in manifest.cases:
        if spec.id in seen:
            raise ValueError(f"duplicate case id: {spec.id}")
        seen.add(spec.id)
        text, warnings = normalize(spec.posting)
        cases.append(
            EvalCase(
                id=spec.id,
                posting=Posting(
                    id=spec.id,
                    source=PostingSource.PASTE,
                    text=text,
                    text_hash=text_hash(text),
                    extractor=Extractor(name="eval-case", version="1"),
                    warnings=warnings,
                    created_at=datetime.combine(spec.as_of, time.min, UTC),
                ),
            )
        )
    return cases


@dataclass(frozen=True)
class CaseSet:
    """The cases of a run and the hash recorded in its header as the fixture set hash."""

    cases: list[EvalCase]
    set_hash: str


def fixture_case_set(root: Path, only: Sequence[str] = ()) -> CaseSet:
    """The committed labeled fixtures as cases. The labels must be committed and unchanged, and
    are checked for every fixture before any case is built. A case id is the fixture id, which
    is what the scorer joins on. The posting is the fixture text exactly, so label spans hold."""
    directories = discover_fixtures(root)
    unknown = sorted(set(only) - {path.name for path in directories})
    if unknown:
        raise ValueError(f"no fixture named {unknown[0]}")
    chosen = [path for path in directories if not only or path.name in only]
    for directory in chosen:
        require_committed_labels(directory)
    fixtures = [load_fixture(directory) for directory in chosen]
    cases: list[EvalCase] = []
    for fixture in fixtures:
        text, warnings = normalize(fixture.text)
        if text != fixture.text:
            raise ValueError(f"{fixture.meta.fixture_id}: posting.txt is not normalized text")
        cases.append(
            EvalCase(
                id=fixture.meta.fixture_id,
                posting=Posting(
                    id=fixture.meta.fixture_id,
                    source=PostingSource.PASTE,
                    text=fixture.text,
                    text_hash=fixture.text_hash,
                    extractor=Extractor(name="eval-fixture", version="1"),
                    warnings=warnings,
                    created_at=datetime.combine(fixture.meta.retrieved, time.min, UTC),
                ),
            )
        )
    return CaseSet(cases, labeled_set_hash(fixtures))


def fixture_set_hash(cases: list[EvalCase]) -> str:
    """Hash the ordered normalized cases and all fields that affect a pipeline result."""
    payload = [
        {
            "id": case.id,
            "posting": case.posting.text,
            "warnings": [warning.model_dump(mode="json") for warning in case.posting.warnings],
            "as_of": case.posting.created_at.date().isoformat(),
        }
        for case in cases
    ]
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def dry_run_plan(
    cases: list[EvalCase], repeats: int, provider: Provider, budget: Budget
) -> dict[str, Any]:
    """Estimate known first calls and cap all calls that depend on model output and retries."""
    if repeats < 1:
        raise ValueError("repeats must be positive")
    capabilities = provider.capabilities
    calls: list[PlannedCall] = []
    for case in cases:
        prompt = build_prompt(Stage.EXTRACT, case.posting.text, [], capabilities, ExtractionOutput)
        for _ in range(repeats):
            calls.append(
                PlannedCall(
                    system=prompt.system,
                    data_block=prompt.data_block,
                    output_schema=ExtractionOutput,
                    max_output_tokens=output_cap(capabilities),
                )
            )
    extraction = dry_run_estimate(provider, budget, calls)
    pairs = len(cases) * repeats
    max_attempts_per_stage = 2 + RetryPolicy().max_rate_limit_retries
    max_attempts = pairs * (1 + MAX_REQUIREMENTS) * max_attempts_per_stage
    prices = capabilities.cost_per_mtok
    dollars_per_attempt_bound = (
        capabilities.context_tokens * prices.input
        + max(output_cap(capabilities), 500) * prices.output
    ) / 1_000_000
    return {
        "planned_pairs": pairs,
        "extraction_initial_calls_exact": extraction.requests,
        "extraction_input_tokens_estimate": extraction.input_tokens,
        "extraction_output_tokens_upper_bound": extraction.output_tokens,
        "entailment_initial_calls_upper_bound": pairs * MAX_REQUIREMENTS,
        "provider_attempts_upper_bound": max_attempts,
        "cost_usd_upper_bound": max_attempts * dollars_per_attempt_bound,
    }


def _header(
    cases: list[EvalCase],
    repeats: int,
    provider: Provider,
    backend: str,
    model: str,
    *,
    bank: Bank,
    set_hash: str | None = None,
) -> RunHeader:
    capabilities = provider.capabilities
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    return RunHeader(
        git_commit=commit,
        backend=backend,
        model=model,
        prompt_hashes={
            "extract": build_prompt(
                Stage.EXTRACT, "", [], capabilities, ExtractionOutput
            ).prompt_hash,
            "entail": build_prompt(
                Stage.ENTAIL, "", [], capabilities, EntailmentOutput
            ).prompt_hash,
        },
        schema_versions={"extract": EXTRACT_SCHEMA_VERSION, "entail": ENTAIL_SCHEMA_VERSION},
        fixture_set_hash=set_hash or fixture_set_hash(cases),
        bank_hash=bank_hash(bank),
        case_ids=[case.id for case in cases],
        repeats=repeats,
    )


def _resume_budget(state: RunState, provider: Provider, budget: Budget) -> BudgetTracker:
    """Replay observed usage; reserve a context-sized ceiling for unreported attempts."""
    tracker = BudgetTracker(budget, provider.capabilities.cost_per_mtok)
    calls = [call for case in state.cases for call in case.calls]
    calls.extend(state.failed_calls)
    for call in calls:
        usage = call.usage
        if usage is None:
            usage = Usage(
                input_tokens=provider.capabilities.context_tokens,
                output_tokens=(
                    output_cap(provider.capabilities)
                    if call.stage == Stage.EXTRACT
                    else entail_cap(provider.capabilities)
                ),
            )
        tracker.record_attempt(usage)
    return tracker


def _export_snapshot(store: EvalStore, header: RunHeader, path: Path | None) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        store.export_jsonl(header, path)


def run_live(
    cases: list[EvalCase],
    repeats: int,
    provider: Provider,
    budget: Budget,
    out: Path,
    *,
    backend: str,
    model: str,
    confirm_spend: bool,
    export: Path | None = None,
    set_hash: str | None = None,
) -> int:
    """Run pending pairs against the real provider and persist each result transactionally."""
    if not provider.capabilities.local and not confirm_spend:
        raise ValueError("hosted provider requires --confirm-spend")
    bank = load_bank(BANK_PATH, strict=True)
    header = _header(cases, repeats, provider, backend, model, bank=bank, set_hash=set_hash)
    connection = connect(out)
    try:
        migrate(connection)
        store = EvalStore(connection)
        store.start(header)
        state = store.load(header)
        if state.status == "complete":
            _export_snapshot(store, header, export)
            print(json.dumps({"run_id": header.run_id, "status": "complete"}))
            return 0
        tracker = _resume_budget(state, provider, budget)
        measured = BudgetedProvider(provider, tracker)
        pending = state.pending_pairs
        for case in cases:
            for repeat in range(1, repeats + 1):
                if (case.id, repeat) not in pending:
                    continue
                trace = PipelineTrace()
                reason: str | None = None
                try:
                    report = analyze(
                        case.posting,
                        bank,
                        measured,
                        backend=backend,
                        model=model,
                        today=case.posting.created_at.date(),
                        trace=trace,
                    )
                except BudgetExceeded:
                    reason = "budget_exceeded"
                else:
                    reason = (
                        "provider_unavailable"
                        if any(call.error_type == "ProviderUnavailable" for call in trace.calls)
                        else None
                    )
                if reason is not None:
                    store.append_terminal(
                        header,
                        RunTerminal(
                            run_id=header.run_id,
                            status="failed",
                            reason=reason,
                            calls=trace.calls,
                        ),
                    )
                    _export_snapshot(store, header, export)
                    print(
                        json.dumps({"run_id": header.run_id, "status": "failed", "reason": reason})
                    )
                    return 1
                store.append_case(
                    header,
                    CaseRecord(
                        run_id=header.run_id,
                        case_id=case.id,
                        repeat=repeat,
                        posting_hash=case.posting.text_hash,
                        report=report,
                        calls=trace.calls,
                        validators=trace.validators,
                    ),
                )
        store.append_terminal(header, RunTerminal(run_id=header.run_id, status="complete"))
        _export_snapshot(store, header, export)
        print(json.dumps({"run_id": header.run_id, "status": "complete"}))
        return 0
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan or run a SQLite-backed eval harness")
    parser.add_argument("--backend", required=True)
    parser.add_argument("--model", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--cases", type=Path, help="a JSON case manifest")
    source.add_argument(
        "--fixtures",
        type=Path,
        nargs="?",
        const=FIXTURES_PATH,
        help="run the committed labeled fixtures (default folder evals/fixtures)",
    )
    parser.add_argument("--only", action="append", default=[], metavar="FIXTURE_ID")
    parser.add_argument("--repeats", required=True, type=int)
    parser.add_argument("--out", type=Path, default=database_path())
    parser.add_argument("--export", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-spend", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run and args.export is not None:
        parser.error("--export requires a live run")
    if args.export is not None:
        scratch = (ROOT / "evals" / "scratch").resolve()
        if args.export.suffix != ".jsonl" or not args.export.resolve().is_relative_to(scratch):
            parser.error("--export must be a .jsonl path under evals/scratch/")
        if args.export.exists():
            parser.error("--export already exists")
    if args.only and args.fixtures is None:
        parser.error("--only needs --fixtures")
    set_hash: str | None = None
    if args.fixtures is not None:
        try:
            case_set = fixture_case_set(args.fixtures, args.only)
        except (ValueError, LabelError, LabelsNotCommitted) as error:
            print(f"run refused: {error}", file=sys.stderr)
            return 1
        cases, set_hash = case_set.cases, case_set.set_hash
    else:
        cases = load_cases(args.cases)
    environment = {
        **os.environ,
        "CYPRESS_CREEK_PROVIDER": args.backend,
        "CYPRESS_CREEK_MODEL": args.model,
    }
    settings = load_settings(environ=environment)
    provider = get_provider(settings)
    budget = budget_from_settings(settings)
    if args.dry_run:
        print(json.dumps(dry_run_plan(cases, args.repeats, provider, budget)))
        return 0
    return run_live(
        cases,
        args.repeats,
        provider,
        budget,
        args.out,
        backend=args.backend,
        model=args.model,
        confirm_spend=args.confirm_spend,
        export=args.export,
        set_hash=set_hash,
    )


if __name__ == "__main__":
    raise SystemExit(main())
