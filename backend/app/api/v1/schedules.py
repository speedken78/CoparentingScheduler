from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_db
from app.models.user import User
from app.repositories.rule_repo import RuleRepository
from app.repositories.event_repo import EventRepository
from app.repositories.revocation_proposal_repo import RevocationProposalRepository
from app.repositories.membership_repo import MembershipRepository
from app.services.schedule_service import confirm_revocation

router = APIRouter(prefix="/cases/{case_id}", tags=["schedules"])


async def _require_member(case_id: UUID, user_id: UUID, db: AsyncSession):
    m = await MembershipRepository(db).get(case_id, user_id)
    if not m:
        raise HTTPException(403, detail="您不是此案件的成員")
    return m


@router.get("/rules")
async def list_rules(
    case_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_member(case_id, current_user.id, db)
    rules = await RuleRepository(db).list_active(case_id)
    return {
        "items": [
            {
                "id": str(r.id),
                "rrule": r.rrule,
                "custodian_id": str(r.custodian_id),
                "start_time": str(r.start_time)[:5],
                "end_time": str(r.end_time)[:5],
                "effective_from": str(r.effective_from),
                "effective_until": str(r.effective_until) if r.effective_until else None,
                "source": r.source,
            }
            for r in rules
        ]
    }


@router.get("/events")
async def list_events(
    case_id: UUID,
    start: datetime = Query(...),
    end: datetime = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_member(case_id, current_user.id, db)
    events = await EventRepository(db).list_in_range(case_id, start, end)
    return {
        "items": [
            {
                "id": str(e.id),
                "starts_at": e.starts_at.isoformat(),
                "ends_at": e.ends_at.isoformat(),
                "custodian_id": str(e.custodian_id),
                "status": e.status,
                "rule_id": str(e.rule_id) if e.rule_id else None,
                "handover_location": e.handover_location,
                "notes": e.notes,
            }
            for e in events
        ]
    }


@router.delete("/events/{event_id}")
async def delete_event(
    case_id: UUID,
    event_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    m = await _require_member(case_id, current_user.id, db)
    event = await EventRepository(db).soft_delete(event_id, case_id)
    if not event:
        raise HTTPException(404, detail="事件不存在")
    if str(event.custodian_id) != str(current_user.id) and m.relation not in ("parent_a", "parent_b"):
        raise HTTPException(403, detail="無權刪除此事件")
    await db.commit()
    return {"status": "deleted"}


@router.get("/revocation-proposals")
async def list_revocation_proposals(
    case_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_member(case_id, current_user.id, db)
    proposals = await RevocationProposalRepository(db).list_pending(case_id)
    return {
        "items": [
            {
                "id": str(p.id),
                "rule_id": str(p.rule_id) if p.rule_id else None,
                "rule_hint": p.rule_hint,
                "revocation_reason": p.revocation_reason,
                "effective_from": str(p.effective_from),
                "expires_at": p.expires_at.isoformat(),
            }
            for p in proposals
        ]
    }


class ConfirmRevocationRequest(BaseModel):
    rule_id: UUID | None = None


@router.post("/revocation-proposals/{proposal_id}/confirm")
async def confirm_revocation_endpoint(
    case_id: UUID,
    proposal_id: UUID,
    body: ConfirmRevocationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    m = await _require_member(case_id, current_user.id, db)
    if m.relation not in ("parent_a", "parent_b"):
        raise HTTPException(403, detail="只有父母可以確認撤銷")

    if body.rule_id:
        proposal = await RevocationProposalRepository(db).get_by_id(proposal_id)
        if proposal:
            proposal.rule_id = body.rule_id
            await db.flush()

    try:
        async with db.begin_nested():
            result = await confirm_revocation(proposal_id, current_user.id, db, user=current_user)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))

    await db.commit()
    return result


@router.get("/gcal-sync-status")
async def get_gcal_sync_status(
    case_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_member(case_id, current_user.id, db)

    from sqlalchemy import func
    from app.models.gcal_sync_log import GCalSyncLog

    result = await db.execute(
        select(GCalSyncLog.status, func.count(GCalSyncLog.id))
        .where(GCalSyncLog.user_id == current_user.id)
        .group_by(GCalSyncLog.status)
    )
    counts = {row[0]: row[1] for row in result.all()}

    return {
        "gcal_scope_granted": current_user.gcal_scope_granted,
        "sync_counts": {
            "success": counts.get("success", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
        },
    }
