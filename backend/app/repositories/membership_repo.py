from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import CaseMembership
from app.models.user import User


class MembershipRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def insert(self, data: dict) -> CaseMembership:
        membership = CaseMembership(**data)
        self.db.add(membership)
        await self.db.flush()
        await self.db.refresh(membership)
        return membership

    async def get(self, case_id: UUID, user_id: UUID) -> Optional[CaseMembership]:
        result = await self.db.execute(
            select(CaseMembership).where(
                CaseMembership.case_id == case_id,
                CaseMembership.user_id == user_id,
                CaseMembership.revoked_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_members_with_user(self, case_id: UUID) -> list[dict]:
        result = await self.db.execute(
            select(CaseMembership, User)
            .join(User, User.id == CaseMembership.user_id)
            .where(
                CaseMembership.case_id == case_id,
                CaseMembership.revoked_at.is_(None),
            )
        )
        rows = result.all()
        return [
            {
                "relation": m.relation,
                "display_name": u.display_name,
                "joined_at": m.joined_at,
            }
            for m, u in rows
        ]
