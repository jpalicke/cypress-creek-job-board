# ABOUTME: The fact bank routes: list, validate, and add, edit, share, verify and delete a fact.
# ABOUTME: A bad bank is reported as data. Only the verify route verifies, and an edit unverifies.
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter
from fastapi import Path as RoutePath

from cypress_creek.api.context import BankPath
from cypress_creek.api.errors import ApiError, ErrorCode, ErrorDetail
from cypress_creek.api.schemas import (
    ApiModel,
    BankProblem,
    FactsResponse,
    ValidateRequest,
    ValidateResponse,
)
from cypress_creek.facts import Bank, BankLoadError, FactValidationError, load_bank
from cypress_creek.facts.loader import parse_bank, safe_load_yaml
from cypress_creek.facts.models import Fact, Share
from cypress_creek.facts.store import BankStore, FactDraft, FactNotFound

router = APIRouter()

MAX_REASON_CHARS = 200


def load_bank_or_raise(path: Path) -> Bank:
    """Load the bank file, with API errors that name no path and quote no file content."""
    if not path.is_file():
        raise ApiError(404, ErrorCode.BANK_NOT_FOUND)
    try:
        return load_bank(path)
    except FactValidationError as error:
        detail = ErrorDetail(field=f"{error.fact_id}.{error.field}", problem=error.reason)
        raise ApiError(422, ErrorCode.BANK_INVALID, [detail]) from None
    except BankLoadError as error:
        reason = str(error).splitlines()[0][:MAX_REASON_CHARS]
        raise ApiError(
            422, ErrorCode.BANK_INVALID, [ErrorDetail(field="bank", problem=reason)]
        ) from None


@router.get("/api/facts")
def list_facts(path: BankPath) -> FactsResponse:
    bank = load_bank_or_raise(path)
    return FactsResponse(facts=bank.facts, unverified_ids=bank.unverified_ids())


@router.post("/api/facts/validate")
def validate_bank(request: ValidateRequest) -> ValidateResponse:
    try:
        data = safe_load_yaml(request.yaml)
        if not isinstance(data, dict):
            raise BankLoadError("bank must be a mapping with a 'facts' list")
        bank = parse_bank(data, strict=request.strict)
    except FactValidationError as error:
        problem = BankProblem(fact_id=error.fact_id, field=error.field, reason=error.reason)
        return ValidateResponse(valid=False, fact_count=0, unverified_ids=[], problem=problem)
    except BankLoadError as error:
        reason = str(error).splitlines()[0][:MAX_REASON_CHARS]
        problem = BankProblem(fact_id=None, field=None, reason=reason)
        return ValidateResponse(valid=False, fact_count=0, unverified_ids=[], problem=problem)
    return ValidateResponse(
        valid=True, fact_count=len(bank.facts), unverified_ids=bank.unverified_ids(), problem=None
    )


FactId = Annotated[str, RoutePath(pattern=r"^F-\d{4}$")]


class ShareRequest(ApiModel):
    share: Share


class RemovedResponse(ApiModel):
    removed: bool


def _invalid(error: FactValidationError) -> ApiError:
    return ApiError(
        422,
        ErrorCode.INVALID_REQUEST,
        [ErrorDetail(field=error.field, problem=error.reason[:MAX_REASON_CHARS])],
    )


def _guarded[T](path: Path, action: Callable[[BankStore], T]) -> T:
    """Run a store action, mapping its failures to typed API errors that quote nothing."""
    try:
        return action(BankStore(path))
    except FactNotFound:
        raise ApiError(404, ErrorCode.NOT_FOUND) from None
    except FactValidationError as error:
        raise _invalid(error) from None
    except BankLoadError:
        raise ApiError(422, ErrorCode.BANK_INVALID) from None


@router.post("/api/facts", status_code=201)
def add_fact(draft: FactDraft, path: BankPath) -> Fact:
    """A new fact is unverified and local only. Nothing in the body can say otherwise."""
    return _guarded(path, lambda store: store.add(draft))


@router.put("/api/facts/{fact_id}")
def edit_fact(fact_id: FactId, draft: FactDraft, path: BankPath) -> Fact:
    """Replace what a fact says. Changing it takes its verification away."""
    return _guarded(path, lambda store: store.update(fact_id, draft))


@router.put("/api/facts/{fact_id}/share")
def set_share(fact_id: FactId, body: ShareRequest, path: BankPath) -> Fact:
    return _guarded(path, lambda store: store.set_share(fact_id, body.share))


@router.post("/api/facts/{fact_id}/verify")
def verify_fact(fact_id: FactId, path: BankPath) -> Fact:
    """A person verifies one fact at a time. There is no bulk route and no body."""
    return _guarded(path, lambda store: store.verify(fact_id))


@router.post("/api/facts/{fact_id}/unverify")
def unverify_fact(fact_id: FactId, path: BankPath) -> Fact:
    return _guarded(path, lambda store: store.unverify(fact_id))


@router.delete("/api/facts/{fact_id}")
def delete_fact(fact_id: FactId, path: BankPath) -> RemovedResponse:
    _guarded(path, lambda store: store.delete(fact_id))
    return RemovedResponse(removed=True)
