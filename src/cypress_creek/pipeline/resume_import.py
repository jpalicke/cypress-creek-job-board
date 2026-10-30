# ABOUTME: Resume import: one model call proposes facts, then code keeps only what the resume says.
# ABOUTME: A failed candidate is dropped and counted, never repaired. Nothing here verifies a fact.
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Collection, Sequence

from pydantic import BaseModel, ConfigDict

from cypress_creek.facts.models import Kind
from cypress_creek.ingest.normalize import normalize
from cypress_creek.pipeline.extract import failure_label
from cypress_creek.pipeline.prompt import Prompt, Stage, build_prompt
from cypress_creek.pipeline.schemas import ResumeImportOutput
from cypress_creek.pipeline.trace import PipelineTrace
from cypress_creek.providers import ProviderError
from cypress_creek.providers.base import Provider, Usage
from cypress_creek.providers.retry import RetryPolicy, call_with_retry
from cypress_creek.terms import normalize_term
from cypress_creek.validators.candidates import ProposedFact, check_candidate_grounded

SCHEMA_VERSION = 1
MAX_OUTPUT_TOKENS = 4000
EMPTY_CLAIM = "empty_claim"
DUPLICATE = "duplicate"
ALREADY_IN_BANK = "already_in_bank"


class Candidate(BaseModel):
    """A fact the resume supports. It is a proposal only: unverified and local only if kept."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim: str
    kind: Kind
    tags: list[str]
    source: str


class ImportResult(BaseModel):
    """What one import found. `dropped` counts rejected proposals by reason, without their text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    candidates: list[Candidate]
    dropped: dict[str, int]
    failure: str | None = None
    prompt_hash: str | None = None
    usage: Usage | None = None


def claim_key(claim: str) -> str:
    """The comparison form of a claim: folded, spaces collapsed, edge punctuation dropped."""
    folded = " ".join(unicodedata.normalize("NFKC", claim).casefold().split())
    return folded.strip(" .,;:!?")


def accept_candidates(
    resume: str, output: ResumeImportOutput, known_claims: Collection[str] = ()
) -> tuple[list[Candidate], dict[str, int]]:
    """Keep each proposal V15 passes. Duplicates are merged and bank claims are not proposed."""
    kept: list[Candidate] = []
    dropped: Counter[str] = Counter()
    seen = {claim_key(claim) for claim in known_claims}
    banked = set(seen)
    for proposal in output.candidates:
        key = claim_key(proposal.claim)
        if not key:
            dropped[EMPTY_CLAIM] += 1
            continue
        tags = list(dict.fromkeys(name for tag in proposal.tags if (name := normalize_term(tag))))
        verdict = check_candidate_grounded(
            resume, ProposedFact(claim=proposal.claim, source=proposal.source, tags=tags)
        )
        if not verdict.passed:
            dropped[verdict.reason] += 1
        elif key in banked:
            dropped[ALREADY_IN_BANK] += 1
        elif key in seen:
            dropped[DUPLICATE] += 1
        else:
            seen.add(key)
            kept.append(
                Candidate(
                    claim=proposal.claim.strip(),
                    kind=proposal.kind,
                    tags=tags,
                    source=proposal.source.strip(),
                )
            )
    return kept, dict(dropped)


def propose_candidates(
    resume_text: str,
    provider: Provider,
    known_claims: Sequence[str] = (),
    *,
    sleep: Callable[[float], None] = time.sleep,
    policy: RetryPolicy | None = None,
    trace: PipelineTrace | None = None,
) -> ImportResult:
    """Ask the model once, then check every proposal against the normalized resume.

    The model sees only the resume and the schema. A typed provider failure is `not_run`;
    BudgetExceeded and any other error propagate. Raises EmptyPosting or PostingTooLong for a
    resume that cannot be read as text."""
    text, _ = normalize(resume_text)
    capabilities = provider.capabilities

    def build(feedback: str | None = None) -> Prompt:
        return build_prompt(
            Stage.IMPORT, text, [], capabilities, ResumeImportOutput, retry_feedback=feedback
        )

    def attempt(feedback: str | None) -> tuple[ResumeImportOutput, Usage]:
        used = build(feedback)
        cap = min(MAX_OUTPUT_TOKENS, capabilities.context_tokens // 2)
        try:
            result = provider.complete_structured(
                used.system, used.user_message, ResumeImportOutput, cap
            )
        except ProviderError as error:
            if trace is not None and error.request_attempted:
                trace.record_call(
                    stage=Stage.IMPORT,
                    prompt_hash=used.prompt_hash,
                    schema_version=SCHEMA_VERSION,
                    usage=error.usage,
                    cost_per_mtok=capabilities.cost_per_mtok,
                    error_type=type(error).__name__,
                )
            raise
        if trace is not None:
            trace.record_call(
                stage=Stage.IMPORT,
                prompt_hash=used.prompt_hash,
                schema_version=SCHEMA_VERSION,
                usage=result.usage,
                cost_per_mtok=capabilities.cost_per_mtok,
            )
        return result.parsed, result.usage

    prompt_hash = build().prompt_hash
    try:
        output, usage = call_with_retry(attempt, sleep=sleep, policy=policy)
    except ProviderError as error:
        label = failure_label(error)
        if label is None:
            raise
        return ImportResult(
            status="not_run", candidates=[], dropped={}, failure=label, prompt_hash=prompt_hash
        )
    kept, dropped = accept_candidates(text, output, known_claims)
    return ImportResult(
        status="done", candidates=kept, dropped=dropped, prompt_hash=prompt_hash, usage=usage
    )
