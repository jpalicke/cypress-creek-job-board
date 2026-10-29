# ABOUTME: The company suggestion flow: ask a model for names, then filter them in code.
# ABOUTME: A name must pass V14 and miss the denied list and blacklist before anything resolves it.
import time
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from cypress_creek.discovery.blacklist import BlacklistEntry, Candidate, is_blacklisted
from cypress_creek.discovery.profile import TagProfile
from cypress_creek.discovery.resolver import Resolver
from cypress_creek.discovery.suggestion_store import AddOutcome, SuggestionStore
from cypress_creek.discovery.tombstones import Tombstones
from cypress_creek.pipeline.extract import failure_label
from cypress_creek.pipeline.prompt import Stage, build_company_prompt
from cypress_creek.pipeline.schemas import CompanyNamesOutput
from cypress_creek.pipeline.trace import PipelineTrace
from cypress_creek.providers import ProviderError
from cypress_creek.providers.base import Provider
from cypress_creek.providers.retry import RetryPolicy, call_with_retry
from cypress_creek.storage.company_key import CompanyNameError, company_key
from cypress_creek.validators.names import check_company_name

SCHEMA_VERSION = 1
COMPANY_MAX_OUTPUT_TOKENS = 600


class NameOutcome(StrEnum):
    ACCEPTED = "accepted"
    INVALID = "invalid"
    DUPLICATE = "duplicate"
    DENIED = "denied"
    BLACKLISTED = "blacklisted"


@dataclass(frozen=True)
class NameDecision:
    """What happened to one model supplied name. `name` is the cleaned display name and is only
    set for an accepted one. `raw` is the model's text, kept for the report and never trusted."""

    raw: str
    outcome: NameOutcome
    reason: str
    name: str | None = None


def clean_name(raw: str) -> str:
    """NFKC and single spaces, the form that is stored and shown once V14 has passed."""
    return " ".join(unicodedata.normalize("NFKC", raw).split())


def filter_names(
    raw_names: Iterable[str], tombstones: Tombstones, blacklist: Sequence[BlacklistEntry]
) -> list[NameDecision]:
    """Decide each name, in order: V14, a company key, repeats, denied, then the blacklist.

    The denied list and the blacklist are checked here, in code, on the company key, so a case,
    spacing, punctuation, legal suffix or lookalike letter variant of a blocked company is still
    blocked. The model is never told about either list."""
    decisions: list[NameDecision] = []
    seen: set[str] = set()
    for raw in raw_names:
        verdict = check_company_name(raw)
        if not verdict.passed:
            decisions.append(NameDecision(raw, NameOutcome.INVALID, f"V14: {verdict.reason}"))
            continue
        name = clean_name(raw)
        try:
            key = company_key(name)
        except CompanyNameError:
            decisions.append(NameDecision(raw, NameOutcome.INVALID, "no usable company key"))
            continue
        if key in seen:
            decisions.append(NameDecision(raw, NameOutcome.DUPLICATE, "repeated in this answer"))
        elif tombstones.denied_company(name) is not None:
            decisions.append(NameDecision(raw, NameOutcome.DENIED, "a human denied this company"))
        elif is_blacklisted(Candidate(name=name, slug=None, domain=None), blacklist) is not None:
            decisions.append(NameDecision(raw, NameOutcome.BLACKLISTED, "on the blacklist"))
        else:
            seen.add(key)
            decisions.append(NameDecision(raw, NameOutcome.ACCEPTED, "", name))
    return decisions


class SuggestionStatus(StrEnum):
    PENDING = "pending"
    INVALID = "invalid"
    DUPLICATE = "duplicate"
    DENIED = "denied"
    BLACKLISTED = "blacklisted"
    UNRESOLVED = "unresolved"
    ALREADY_PENDING = "already_pending"
    ALREADY_WATCHED = "already_watched"


_FROM_NAME = {
    NameOutcome.INVALID: SuggestionStatus.INVALID,
    NameOutcome.DUPLICATE: SuggestionStatus.DUPLICATE,
    NameOutcome.DENIED: SuggestionStatus.DENIED,
    NameOutcome.BLACKLISTED: SuggestionStatus.BLACKLISTED,
}
_FROM_ADD = {
    AddOutcome.ADDED: SuggestionStatus.PENDING,
    AddOutcome.DENIED: SuggestionStatus.DENIED,
    AddOutcome.ALREADY_PENDING: SuggestionStatus.ALREADY_PENDING,
    AddOutcome.ALREADY_WATCHED: SuggestionStatus.ALREADY_WATCHED,
}


@dataclass(frozen=True)
class NameResult:
    """The fate of one model supplied name. `raw` is untrusted text kept for the report."""

    raw: str
    status: SuggestionStatus
    detail: str = ""


@dataclass(frozen=True)
class SuggestionReport:
    results: tuple[NameResult, ...]

    def count(self, status: SuggestionStatus) -> int:
        return sum(1 for result in self.results if result.status is status)


def suggest_from_names(
    raw_names: Iterable[str],
    *,
    tombstones: Tombstones,
    blacklist: Sequence[BlacklistEntry],
    resolver: Resolver,
    store: SuggestionStore,
    proposed_by: str,
) -> SuggestionReport:
    """Everything after the model: filter in code, resolve what is left, queue it for review.

    This writes pending suggestions and nothing else. It cannot write the watchlist: only a
    human approval in review.py does that."""
    results: list[NameResult] = []
    for decision in filter_names(raw_names, tombstones, blacklist):
        if decision.name is None:
            results.append(NameResult(decision.raw, _FROM_NAME[decision.outcome], decision.reason))
            continue
        resolution = resolver.resolve(decision.name)
        if resolution is None:
            detail = "; ".join(resolver.last_errors) or "no board found"
            results.append(NameResult(decision.raw, SuggestionStatus.UNRESOLVED, detail))
        elif is_blacklisted(Candidate(decision.name, resolution.slug, None), blacklist):
            results.append(NameResult(decision.raw, SuggestionStatus.BLACKLISTED, "board slug"))
        else:
            added = store.add_pending(decision.name, proposed_by, resolution)
            results.append(NameResult(decision.raw, _FROM_ADD[added], resolution.evidence.value))
    return SuggestionReport(tuple(results))


class ProposalFailed(Exception):
    """The model call failed in a way that ends the run, such as an unreachable backend."""

    def __init__(self, label: str) -> None:
        super().__init__(label)
        self.label = label


def propose_names(
    provider: Provider,
    profile: TagProfile,
    *,
    sleep: Callable[[float], None] = time.sleep,
    policy: RetryPolicy | None = None,
    trace: PipelineTrace | None = None,
) -> list[str]:
    """One model call for company names. The names are untrusted until filter_names passes them.

    BudgetExceeded and any error without a failure label propagate."""
    capabilities = provider.capabilities
    prompt = build_company_prompt(profile.render(), CompanyNamesOutput)

    def attempt(feedback: str | None) -> list[str]:
        used = prompt
        system = prompt.system
        if feedback:
            system = f"{system}\n\nYour previous answer was rejected. Fix this: {feedback}"
        try:
            result = provider.complete_structured(
                system,
                used.data_block,
                CompanyNamesOutput,
                min(COMPANY_MAX_OUTPUT_TOKENS, capabilities.context_tokens // 2),
            )
        except ProviderError as error:
            if trace is not None and error.request_attempted:
                trace.record_call(
                    stage=Stage.COMPANY,
                    prompt_hash=used.prompt_hash,
                    schema_version=SCHEMA_VERSION,
                    usage=error.usage,
                    cost_per_mtok=capabilities.cost_per_mtok,
                    error_type=type(error).__name__,
                )
            raise
        if trace is not None:
            trace.record_call(
                stage=Stage.COMPANY,
                prompt_hash=used.prompt_hash,
                schema_version=SCHEMA_VERSION,
                usage=result.usage,
                cost_per_mtok=capabilities.cost_per_mtok,
            )
        return list(result.parsed.names)

    try:
        return call_with_retry(attempt, sleep=sleep, policy=policy)
    except ProviderError as error:
        label = failure_label(error)
        if label is None:
            raise
        raise ProposalFailed(label) from None
