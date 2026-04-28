from datetime import date
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_current_user, get_db
from app.models.user import User
from app.repositories.membership_repo import MembershipRepository
from app.repositories.report_repo import ReportRepository
from app.services.report_service import generate_report

router = APIRouter(prefix="/cases/{case_id}/reports", tags=["reports"])

VALID_REPORT_TYPES = ("monthly", "custom_range", "dispute", "full_history")


async def _require_member(case_id: UUID, user_id: UUID, db: AsyncSession):
    m = await MembershipRepository(db).get(case_id, user_id)
    if not m:
        raise HTTPException(403, detail="您不是此案件的成員")
    return m


class GenerateReportRequest(BaseModel):
    period_start: date
    period_end: date
    report_type: str = "monthly"


@router.post("/", status_code=201)
async def create_report(
    case_id: UUID,
    body: GenerateReportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_member(case_id, current_user.id, db)

    if body.period_end < body.period_start:
        raise HTTPException(422, detail="period_end 不可早於 period_start")
    if body.report_type not in VALID_REPORT_TYPES:
        raise HTTPException(422, detail="無效的 report_type")

    async with db.begin_nested():
        report = await generate_report(
            case_id=case_id,
            period_start=body.period_start,
            period_end=body.period_end,
            report_type=body.report_type,
            requesting_user_id=current_user.id,
            db=db,
        )

    await db.commit()

    return {
        "id": str(report.id),
        "pdf_path": report.pdf_gcs_path,
        "pdf_sha256": report.pdf_sha256,
        "last_audit_id": report.last_audit_id,
        "last_audit_hash": report.last_audit_hash,
        "generated_at": report.generated_at.isoformat() if report.generated_at else None,
    }


@router.get("/")
async def list_reports(
    case_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_member(case_id, current_user.id, db)
    reports = await ReportRepository(db).list_by_case(case_id)
    return {
        "items": [
            {
                "id": str(r.id),
                "report_type": r.report_type,
                "period_start": str(r.period_start),
                "period_end": str(r.period_end),
                "pdf_sha256": r.pdf_sha256,
                "generated_at": r.generated_at.isoformat(),
            }
            for r in reports
        ]
    }


@router.get("/{report_id}/download")
async def download_report(
    case_id: UUID,
    report_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_member(case_id, current_user.id, db)
    report = await ReportRepository(db).get_by_id(report_id)
    if not report or str(report.case_id) != str(case_id):
        raise HTTPException(404, detail="報告不存在")

    mode = getattr(settings, "PDF_STORAGE_MODE", "local")

    if mode == "local":
        pdf_path = Path(report.pdf_gcs_path)
        if not pdf_path.exists():
            raise HTTPException(404, detail="PDF 檔案不存在（可能已清除）")
        pdf_bytes = pdf_path.read_bytes()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="report_{report.period_start}_{report.period_end}.pdf"'
                )
            },
        )
    else:
        raise HTTPException(501, detail="GCS 下載尚未實作")
