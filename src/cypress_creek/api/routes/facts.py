# ABOUTME: GET /api/facts lists the fact bank and POST /api/facts/validate checks a bank file.
# ABOUTME: A bad bank is reported as data with a short reason. The submitted YAML is never echoed.
from pathlib import Path

from fastapi import APIRouter

from cypress_creek.api.context import BankPath
from cypress_creek.api.errors import ApiError, ErrorCode, ErrorDetail
from cypress_creek.api.schemas import BankProblem, FactsResponse, ValidateRequest, ValidateResponse
from cypress_creek.facts import Bank, BankLoadError, FactValidationError, load_bank
from cypress_creek.facts.loader import parse_bank, safe_load_yaml

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
