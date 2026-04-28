from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.report import Report


class ReportRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def insert(self, data: dict) -> Report:
        report = Report(**data)
        self.db.add(report)
        await self.db.flush()
        return report

    async def list_by_case(self, case_id: UUID) -> list[Report]:
        result = await self.db.execute(
            select(Report)
            .where(Report.case_id == case_id)
            .order_by(Report.generated_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, report_id: UUID) -> Report | None:
        return await self.db.get(Report, report_id)
