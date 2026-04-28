from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.services.audit_anchor_service import run_anchor_job, verify_hash_chain
from app.services.expansion_maintenance import extend_all_active_rules

router = APIRouter(prefix="/admin", tags=["admin"])


def verify_job_token(x_job_token: str = Header(...)):
    if x_job_token != settings.JOB_SECRET_TOKEN:
        raise HTTPException(403, detail="Invalid job token")


@router.post("/jobs/anchor-audit-log")
async def job_anchor_audit_log(
    _: None = Depends(verify_job_token),
    db: AsyncSession = Depends(get_db),
):
    """每小時由 Cloud Scheduler 觸發。"""
    result = await run_anchor_job(db)
    await db.commit()
    return result


@router.post("/jobs/expand-rules")
async def job_expand_rules(
    _: None = Depends(verify_job_token),
    db: AsyncSession = Depends(get_db),
):
    """每日由 Cloud Scheduler 觸發。"""
    result = await extend_all_active_rules(db)
    await db.commit()
    return result


@router.get("/jobs/verify-hash-chain/{case_id}")
async def job_verify_hash_chain(
    case_id: str,
    _: None = Depends(verify_job_token),
    db: AsyncSession = Depends(get_db),
):
    """手動觸發：驗證指定 case 的 hash chain 完整性。"""
    result = await verify_hash_chain(UUID(case_id), db)
    return result
