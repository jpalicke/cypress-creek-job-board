# ABOUTME: Runs the pipeline over one posting: extract, retrieve, entail, then the gap report.
# ABOUTME: The run id is derived from the inputs, so a rerun of the same inputs is traceable.
import hashlib
import time
from collections.abc import Callable
from datetime import date

from cypress_creek.facts.hashing import bank_hash
from cypress_creek.facts.models import Bank
from cypress_creek.ingest.models import Posting
from cypress_creek.pipeline.entail import entail
from cypress_creek.pipeline.extract import ExtractionResult, ExtractionStatus, extract_requirements
from cypress_creek.pipeline.report import GapReport, Provenance, build_report
from cypress_creek.pipeline.retrieve import retrieve
from cypress_creek.providers.base import Provider, Usage
from cypress_creek.providers.retry import RetryPolicy
from cypress_creek.scoring.aliases import AliasTable, load_aliases
from cypress_creek.scoring.score import Weights

RUN_ID_HEX_CHARS = 16


def run_id(posting_hash: str, bank_digest: str, backend: str, model: str) -> str:
    """The same posting, bank, backend and model always give the same id.

    The fields are joined with a separator that cannot appear in a hash, so two different
    field splits never run together into one input."""
    joined = "\n".join((posting_hash, bank_digest, backend, model))
    digest = hashlib.sha256(joined.encode("utf8")).hexdigest()
    return f"run-{digest[:RUN_ID_HEX_CHARS]}"


def assess(
    posting: Posting,
    extraction: ExtractionResult,
    bank: Bank,
    provider: Provider,
    *,
    backend: str,
    model: str,
    aliases: AliasTable | None = None,
    today: date | None = None,
    weights: Weights | None = None,
    sleep: Callable[[float], None] = time.sleep,
    policy: RetryPolicy | None = None,
) -> GapReport:
    """Stages 2 to 5 over an extraction: retrieve, one entailment call per candidate, the report.

    A failed extraction skips them and gives the incomplete report. BudgetExceeded propagates."""
    candidates = []
    entailed = []
    if extraction.status is ExtractionStatus.OK:
        candidates = retrieve(
            extraction.requirements,
            bank,
            provider.capabilities,
            today or date.today(),
            aliases or load_aliases(),
        )
        entailed = [
            entail(requirement, candidate, bank, provider, sleep=sleep, policy=policy)
            for requirement, candidate in zip(extraction.requirements, candidates, strict=True)
        ]
    used = [extraction.usage, *(outcome.usage for outcome in entailed)]
    usage = Usage(
        input_tokens=sum(part.input_tokens for part in used if part),
        output_tokens=sum(part.output_tokens for part in used if part),
    )
    prompt_hashes = {"extract": extraction.prompt_hash}
    entail_hashes = {outcome.prompt_hash for outcome in entailed if outcome.prompt_hash}
    if entail_hashes:
        (prompt_hashes["entail"],) = entail_hashes
    provenance = Provenance(
        backend=backend,
        model=model,
        run_id=run_id(posting.text_hash, bank_hash(bank), backend, model),
        prompt_hashes=prompt_hashes,
        usage=usage,
    )
    return build_report(posting, extraction, candidates, entailed, bank, provenance, weights)


def analyze(
    posting: Posting,
    bank: Bank,
    provider: Provider,
    *,
    backend: str,
    model: str,
    aliases: AliasTable | None = None,
    today: date | None = None,
    weights: Weights | None = None,
    sleep: Callable[[float], None] = time.sleep,
    policy: RetryPolicy | None = None,
) -> GapReport:
    """The whole run over a normalized posting: extract its requirements, then assess them."""
    extraction = extract_requirements(posting.text, provider, sleep=sleep, policy=policy)
    return assess(
        posting,
        extraction,
        bank,
        provider,
        backend=backend,
        model=model,
        aliases=aliases,
        today=today,
        weights=weights,
        sleep=sleep,
        policy=policy,
    )
