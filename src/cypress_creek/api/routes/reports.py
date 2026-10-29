# ABOUTME: GET /api/reports/{id} returns a stored gap report with the verdicts of its validators.
# ABOUTME: Verdicts carry the validator id, stage, subject and reason, never the offending text.
from fastapi import APIRouter

from cypress_creek.api.context import DatabasePath
from cypress_creek.api.errors import ApiError, ErrorCode
from cypress_creek.api.schemas import ReportResponse
from cypress_creek.storage.repository import ReportStore

router = APIRouter()


@router.get("/api/reports/{report_id}")
def get_report(report_id: str, database: DatabasePath) -> ReportResponse:
    stored = ReportStore(database).get(report_id)
    if stored is None:
        raise ApiError(404, ErrorCode.NOT_FOUND)
    return ReportResponse(
        report_id=stored.report_id,
        posting_id=stored.posting_id,
        created_at=stored.created_at,
        report=stored.report,
        validator_verdicts=stored.verdicts,
    )
