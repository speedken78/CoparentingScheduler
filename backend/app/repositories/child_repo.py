from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.child import Child


def _age_years(birth_date: date) -> int:
    today = date.today()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


class ChildRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def insert(self, data: dict) -> Child:
        child = Child(**data)
        self.db.add(child)
        await self.db.flush()
        await self.db.refresh(child)
        return child

    async def get_by_id(self, child_id: UUID, case_id: UUID) -> Optional[Child]:
        result = await self.db.execute(
            select(Child).where(
                Child.id == child_id,
                Child.case_id == case_id,
                Child.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_case(self, case_id: UUID) -> list[Child]:
        result = await self.db.execute(
            select(Child).where(
                Child.case_id == case_id,
                Child.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def update(self, child: Child, data: dict) -> Child:
        for key, value in data.items():
            setattr(child, key, value)
        await self.db.flush()
        await self.db.refresh(child)
        return child

    @staticmethod
    def to_response_dict(child: Child) -> dict:
        return {
            "id": child.id,
            "case_id": child.case_id,
            "display_name": child.display_name,
            "birth_date": child.birth_date,
            "age_years": _age_years(child.birth_date),
            "notes": child.notes,
            "created_at": child.created_at,
        }
