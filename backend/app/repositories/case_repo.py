from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import CaseMembership, FamilyCase
from app.models.child import Child


class CaseRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def insert(self, data: dict) -> FamilyCase:
        case = FamilyCase(**data)
        self.db.add(case)
        await self.db.flush()
        await self.db.refresh(case)
        return case

    async def get_by_id(self, case_id: UUID) -> Optional[FamilyCase]:
        result = await self.db.execute(
            select(FamilyCase).where(
                FamilyCase.id == case_id,
                FamilyCase.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def update(self, case: FamilyCase, data: dict) -> FamilyCase:
        for key, value in data.items():
            setattr(case, key, value)
        await self.db.flush()
        await self.db.refresh(case)
        return case

    async def list_for_user(self, user_id: UUID) -> list[dict]:
        """Return list of cases with my_relation, member_count, child_count."""
        # RLS already filters to cases the user belongs to
        stmt = (
            select(
                FamilyCase,
                CaseMembership.relation.label("my_relation"),
                func.count(CaseMembership.id).over(partition_by=FamilyCase.id).label("member_count"),
            )
            .join(CaseMembership, CaseMembership.case_id == FamilyCase.id)
            .where(
                CaseMembership.user_id == user_id,
                CaseMembership.revoked_at.is_(None),
                FamilyCase.deleted_at.is_(None),
            )
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        items = []
        for row in rows:
            case = row[0]
            my_relation = row[1]
            # Count children
            child_count_result = await self.db.execute(
                select(func.count()).where(
                    Child.case_id == case.id,
                    Child.deleted_at.is_(None),
                )
            )
            child_count = child_count_result.scalar_one()

            # Count members
            member_count_result = await self.db.execute(
                select(func.count()).where(
                    CaseMembership.case_id == case.id,
                    CaseMembership.revoked_at.is_(None),
                )
            )
            member_count = member_count_result.scalar_one()

            items.append({
                "id": case.id,
                "case_name": case.case_name,
                "custody_type": case.custody_type,
                "my_relation": my_relation,
                "member_count": member_count,
                "child_count": child_count,
                "created_at": case.created_at,
            })
        return items
