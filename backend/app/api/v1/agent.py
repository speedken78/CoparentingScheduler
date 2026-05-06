# app/api/v1/agent.py
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_db, get_request_context
from app.models.user import User
from app.services.agent_service import handle_message
from app.utils.errors import AgentLoopError

router = APIRouter(tags=["agent"])


class MessageRequest(BaseModel):
    text: str
    session_id: UUID | None = None   # 首次呼叫不傳，後續傳上一輪回傳的 session_id
    case_id: UUID


class MessageResponse(BaseModel):
    session_id: str
    reply: str
    actions_taken: list[dict]
    requires_clarification: bool
    clarification_options: list[dict]


@router.post("/message", response_model=MessageResponse)
async def post_message(
    body: MessageRequest,
    current_user: User = Depends(get_current_user),
    req_ctx: dict = Depends(get_request_context),
    db: AsyncSession = Depends(get_db),
):
    # 驗證 current_user 是 case 的成員（RLS 也會擋，但 service 層要明確驗）
    from app.repositories.membership_repo import MembershipRepository
    membership = await MembershipRepository(db).get(body.case_id, current_user.id)
    if not membership:
        raise HTTPException(403, detail="您不是此案件的成員")

    try:
        result = await handle_message(
            case_id=body.case_id,
            user_id=current_user.id,
            user_text=body.text,
            session_id=body.session_id,
            db=db,
            user=current_user,
            **req_ctx,
        )
    except AgentLoopError as e:
        raise HTTPException(500, detail=f"Agent 處理失敗：{e}")

    await db.commit()
    return result
