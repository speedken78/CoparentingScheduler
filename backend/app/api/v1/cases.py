from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, get_request_context
from app.models.user import User
from app.repositories.case_repo import CaseRepository
from app.repositories.child_repo import ChildRepository
from app.repositories.membership_repo import MembershipRepository
from app.schemas.case import (
    CaseDetailResponse,
    CaseListItem,
    CaseMemberInfo,
    CaseResponse,
    CreateCaseRequest,
    UpdateCaseRequest,
)
from app.schemas.child import ChildResponse, CreateChildRequest, UpdateChildRequest
from app.services import audit_service
from app.utils.errors import ErrorCode, error_response

router = APIRouter()


def _case_to_dict(case) -> dict:
    return {
        "case_name": case.case_name,
        "court_case_no": case.court_case_no,
        "custody_type": case.custody_type,
        "custody_ratio": case.custody_ratio,
        "timezone": case.timezone,
    }


def _child_to_dict(child) -> dict:
    return {
        "case_id": str(child.case_id),
        "display_name": child.display_name,
        "birth_date": child.birth_date.isoformat(),
        "notes": child.notes,
    }


@router.post("/", status_code=201, response_model=CaseResponse)
async def create_case(
    body: CreateCaseRequest,
    current_user: User = Depends(get_current_user),
    req_ctx: dict = Depends(get_request_context),
    db: AsyncSession = Depends(get_db),
):
    case_repo = CaseRepository(db)
    membership_repo = MembershipRepository(db)

    case = await case_repo.insert({
        "case_name": body.case_name,
        "court_case_no": body.court_case_no,
        "custody_type": body.custody_type,
        "custody_ratio": body.custody_ratio,
        "timezone": body.timezone or "Asia/Taipei",
        "created_by": current_user.id,
    })

    await membership_repo.insert({
        "case_id": case.id,
        "user_id": current_user.id,
        "relation": "parent_a",
        "invited_by": current_user.id,
    })

    await audit_service.log(
        db,
        case_id=case.id,
        actor_id=current_user.id,
        action="create_case",
        entity_type="family_case",
        entity_id=case.id,
        before_state=None,
        after_state=_case_to_dict(case),
        triggered_by="human",
        **req_ctx,
    )

    await db.commit()

    result = CaseResponse.model_validate(case)
    result.my_relation = "parent_a"
    return result


@router.get("/", response_model=dict)
async def list_cases(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    case_repo = CaseRepository(db)
    items = await case_repo.list_for_user(current_user.id)
    return {"items": [CaseListItem(**item) for item in items]}


@router.get("/{case_id}", response_model=CaseDetailResponse)
async def get_case(
    case_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    case_repo = CaseRepository(db)
    membership_repo = MembershipRepository(db)
    child_repo = ChildRepository(db)

    case = await case_repo.get_by_id(case_id)
    membership = await membership_repo.get(case_id=case_id, user_id=current_user.id)

    # Return 404 (not 403) to avoid leaking information about case existence
    if not case or not membership:
        raise HTTPException(
            status_code=404,
            detail=error_response(ErrorCode.CASE_NOT_FOUND, "找不到指定的家庭案件"),
        )

    members_raw = await membership_repo.list_members_with_user(case_id)
    children_raw = await child_repo.list_by_case(case_id)

    result = CaseDetailResponse.model_validate(case)
    result.my_relation = membership.relation
    result.members = [CaseMemberInfo.model_validate(m) for m in members_raw]
    result.children = [ChildResponse.model_validate(child_repo.to_response_dict(c)) for c in children_raw]
    return result


@router.patch("/{case_id}", response_model=CaseResponse)
async def update_case(
    case_id: UUID,
    body: UpdateCaseRequest,
    current_user: User = Depends(get_current_user),
    req_ctx: dict = Depends(get_request_context),
    db: AsyncSession = Depends(get_db),
):
    case_repo = CaseRepository(db)
    membership_repo = MembershipRepository(db)

    case = await case_repo.get_by_id(case_id)
    if not case:
        raise HTTPException(
            status_code=404,
            detail=error_response(ErrorCode.CASE_NOT_FOUND, "找不到指定的家庭案件"),
        )

    membership = await membership_repo.get(case_id=case_id, user_id=current_user.id)
    if not membership or membership.relation not in ("parent_a", "parent_b"):
        raise HTTPException(
            status_code=403,
            detail=error_response(ErrorCode.FORBIDDEN, "只有父母可以更新案件資訊"),
        )

    before_state = _case_to_dict(case)

    updates = body.model_dump(exclude_none=True)
    if updates:
        case = await case_repo.update(case, updates)

    after_state = _case_to_dict(case)

    await audit_service.log(
        db,
        case_id=case.id,
        actor_id=current_user.id,
        action="update_case",
        entity_type="family_case",
        entity_id=case.id,
        before_state=before_state,
        after_state=after_state,
        triggered_by="human",
        **req_ctx,
    )

    await db.commit()

    result = CaseResponse.model_validate(case)
    result.my_relation = membership.relation
    return result


# ── Children ────────────────────────────────────────────────────────────────

@router.post("/{case_id}/children", status_code=201, response_model=ChildResponse)
async def create_child(
    case_id: UUID,
    body: CreateChildRequest,
    current_user: User = Depends(get_current_user),
    req_ctx: dict = Depends(get_request_context),
    db: AsyncSession = Depends(get_db),
):
    membership_repo = MembershipRepository(db)
    child_repo = ChildRepository(db)
    case_repo = CaseRepository(db)

    case = await case_repo.get_by_id(case_id)
    membership = await membership_repo.get(case_id=case_id, user_id=current_user.id)
    if not case or not membership:
        raise HTTPException(
            status_code=404,
            detail=error_response(ErrorCode.CASE_NOT_FOUND, "找不到指定的家庭案件"),
        )
    if membership.relation not in ("parent_a", "parent_b"):
        raise HTTPException(
            status_code=403,
            detail=error_response(ErrorCode.FORBIDDEN, "只有父母可以新增小孩"),
        )

    if body.birth_date > date.today():
        raise HTTPException(
            status_code=422,
            detail=error_response(ErrorCode.VALIDATION_ERROR, "出生日期不可是未來日期"),
        )

    child = await child_repo.insert({
        "case_id": case_id,
        "display_name": body.display_name,
        "birth_date": body.birth_date,
        "notes": body.notes,
    })

    await audit_service.log(
        db,
        case_id=case_id,
        actor_id=current_user.id,
        action="create_child",
        entity_type="child",
        entity_id=child.id,
        before_state=None,
        after_state=_child_to_dict(child),
        triggered_by="human",
        **req_ctx,
    )

    await db.commit()

    return ChildResponse.model_validate(child_repo.to_response_dict(child))


@router.get("/{case_id}/children", response_model=dict)
async def list_children(
    case_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    membership_repo = MembershipRepository(db)
    membership = await membership_repo.get(case_id=case_id, user_id=current_user.id)
    if not membership:
        raise HTTPException(
            status_code=404,
            detail=error_response(ErrorCode.CASE_NOT_FOUND, "找不到指定的家庭案件"),
        )
    child_repo = ChildRepository(db)
    children = await child_repo.list_by_case(case_id)
    return {"items": [ChildResponse.model_validate(child_repo.to_response_dict(c)) for c in children]}


@router.patch("/{case_id}/children/{child_id}", response_model=ChildResponse)
async def update_child(
    case_id: UUID,
    child_id: UUID,
    body: UpdateChildRequest,
    current_user: User = Depends(get_current_user),
    req_ctx: dict = Depends(get_request_context),
    db: AsyncSession = Depends(get_db),
):
    membership_repo = MembershipRepository(db)
    child_repo = ChildRepository(db)

    membership = await membership_repo.get(case_id=case_id, user_id=current_user.id)
    if not membership or membership.relation not in ("parent_a", "parent_b"):
        raise HTTPException(
            status_code=403,
            detail=error_response(ErrorCode.FORBIDDEN, "只有父母可以更新小孩資訊"),
        )

    child = await child_repo.get_by_id(child_id=child_id, case_id=case_id)
    if not child:
        raise HTTPException(
            status_code=404,
            detail=error_response(ErrorCode.CHILD_NOT_FOUND, "找不到指定的小孩"),
        )

    before_state = _child_to_dict(child)

    updates = body.model_dump(exclude_none=True)
    if updates:
        child = await child_repo.update(child, updates)

    after_state = _child_to_dict(child)

    await audit_service.log(
        db,
        case_id=case_id,
        actor_id=current_user.id,
        action="update_child",
        entity_type="child",
        entity_id=child.id,
        before_state=before_state,
        after_state=after_state,
        triggered_by="human",
        **req_ctx,
    )

    await db.commit()

    return ChildResponse.model_validate(child_repo.to_response_dict(child))
